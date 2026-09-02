"""Read-only web dashboard for Predict Pulse."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse
from pathlib import Path

from flask import Flask, Response, jsonify, send_from_directory

from predict_pulse.pulse import PredictAPI, build_snapshot, read_secret

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("PREDICT_PULSE_DB", "/var/lib/predict-pulse/pulse.sqlite3"))
WEB_ROOT = ROOT / "web"
app = Flask(__name__)
_CACHE_LOCK = threading.Lock()
_CACHE_VALUE = None
_CACHE_AT = 0.0
CACHE_SECONDS = float(os.getenv("DASHBOARD_CACHE_SECONDS", "5"))
CONFIG_PATH = Path(os.getenv("PREDICT_PULSE_CONFIG", "/etc/predict-pulse/config.json"))
_CATEGORY_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CATEGORY_FETCHES: list[float] = []
_CATEGORY_LOCK = threading.Lock()


class CategoryRateLimit(RuntimeError):
    pass


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
        "style-src 'self'; script-src 'self'; frame-ancestors 'none'"
    )
    return response


def connect():
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("PRAGMA query_only=ON")
    return db


def market_url(slug: str) -> str:
    safe_slug = urllib.parse.quote(slug, safe="-_")
    return f"https://predict.fun/category/{safe_slug}" if safe_slug else "https://predict.fun"


def snapshot_json(row):
    return {
        "market_id": row.market_id,
        "title": row.title,
        "question": row.question,
        "probability": row.probability,
        "best_bid": row.best_bid,
        "best_ask": row.best_ask,
        "delta15": None,
        "delta60": None,
        "spread": row.spread,
        "volume24h": row.volume24h_usd,
        "liquidity": row.liquidity_usd,
        "segment": row.segment,
        "category_slug": row.category_slug,
        "url": market_url(row.category_slug),
    }


def live_category(slug: str) -> list[dict]:
    now = time.monotonic()
    with _CATEGORY_LOCK:
        cached = _CATEGORY_CACHE.get(slug)
        if cached and now - cached[0] < 60:
            return cached[1]
        _CATEGORY_FETCHES[:] = [stamp for stamp in _CATEGORY_FETCHES if now - stamp < 60]
        if len(_CATEGORY_FETCHES) >= 10:
            raise CategoryRateLimit("category lookup rate limit reached")
        _CATEGORY_FETCHES.append(now)
    config = json.loads(CONFIG_PATH.read_text())
    api = PredictAPI(
        read_secret(config.get("api_key_file"), config.get("api_key_env")),
        config.get("base_url") or "https://api.predict.fun/v1",
    )
    markets = api.category(slug)[:50]
    stats: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, max(1, len(markets)))) as pool:
        futures = {pool.submit(api.stats, str(row["id"])): str(row["id"]) for row in markets if row.get("id")}
        for future in concurrent.futures.as_completed(futures):
            stats[futures[future]] = future.result()
    captured_at = int(time.time())
    result = [snapshot_json(build_snapshot(row, stats.get(str(row.get("id")), {}), captured_at)) for row in markets]
    with _CATEGORY_LOCK:
        _CATEGORY_CACHE[slug] = (now, result)
    return result


def _dashboard_data_uncached():
    with connect() as db:
        now = int(time.time())
        latest_time = db.execute("SELECT MAX(captured_at) FROM snapshots").fetchone()[0] or 0
        market_count = db.execute("SELECT COUNT(DISTINCT market_id) FROM snapshots").fetchone()[0]
        snapshot_count = db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        alert_count = db.execute("SELECT COUNT(*) FROM alerts WHERE created_at>=?", (now - 86400,)).fetchone()[0]
        latest = db.execute(
            """
            SELECT s.* FROM snapshots s
            JOIN (SELECT market_id, MAX(captured_at) AS t FROM snapshots GROUP BY market_id) x
              ON x.market_id=s.market_id AND x.t=s.captured_at
            ORDER BY s.volume24h_usd DESC NULLS LAST
            """
        ).fetchall()
        movers = []
        for row in latest:
            old15 = db.execute(
                "SELECT probability,best_bid,best_ask FROM snapshots WHERE market_id=? AND captured_at<=? "
                "ORDER BY captured_at DESC LIMIT 1",
                (row["market_id"], row["captured_at"] - 900),
            ).fetchone()
            old60 = db.execute(
                "SELECT probability,best_bid,best_ask FROM snapshots WHERE market_id=? AND captured_at<=? "
                "ORDER BY captured_at DESC LIMIT 1",
                (row["market_id"], row["captured_at"] - 3600),
            ).fetchone()
            p = row["probability"]
            current_two_sided = row["best_bid"] is not None and row["best_ask"] is not None
            old15_two_sided = old15 and old15[1] is not None and old15[2] is not None
            old60_two_sided = old60 and old60[1] is not None and old60[2] is not None
            valid15 = p is not None and current_two_sided and old15_two_sided and old15[0] is not None
            valid60 = p is not None and current_two_sided and old60_two_sided and old60[0] is not None
            delta15 = (p - old15[0]) * 100 if valid15 else None
            delta60 = (p - old60[0]) * 100 if valid60 else None
            movers.append(
                {
                    "market_id": row["market_id"],
                    "title": row["title"],
                    "question": row["question"],
                    "outcome": row["outcome"],
                    "probability": p,
                    "best_bid": row["best_bid"],
                    "best_ask": row["best_ask"],
                    "delta15": delta15,
                    "delta60": delta60,
                    "spread": row["spread"],
                    "volume24h": row["volume24h_usd"],
                    "liquidity": row["liquidity_usd"],
                    "segment": row["segment"],
                    "category_slug": row["category_slug"],
                    "url": market_url(row["category_slug"]),
                }
            )
        movers.sort(key=lambda row: max(abs(row["delta15"] or 0), abs(row["delta60"] or 0)), reverse=True)
        moved15_count = sum(1 for row in movers if abs(row["delta15"] or 0) >= 1.0)
        active_movers = [
            row for row in movers
            if max(abs(row["delta15"] or 0), abs(row["delta60"] or 0)) >= 0.1
        ]
        if active_movers:
            visible_markets = active_movers[:30]
            display_mode = "movers"
        else:
            visible_markets = sorted(
                movers,
                key=lambda row: (row["liquidity"] or 0, row["volume24h"] or 0),
                reverse=True,
            )[:15]
            display_mode = "watchlist"
        alerts = [dict(row) for row in db.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT 30").fetchall()]
    return {
        "status": "healthy" if latest_time and time.time() - latest_time < 180 else "stale",
        "updated_at": latest_time,
        "market_count": market_count,
        "snapshot_count": snapshot_count,
        "alert_count": alert_count,
        "moved15_count": moved15_count,
        "display_mode": display_mode,
        "movers": visible_markets,
        "markets": movers,
        "alerts": alerts,
    }


def dashboard_data():
    global _CACHE_AT, _CACHE_VALUE
    with _CACHE_LOCK:
        if _CACHE_VALUE is not None and time.monotonic() - _CACHE_AT < CACHE_SECONDS:
            return _CACHE_VALUE
        _CACHE_VALUE = _dashboard_data_uncached()
        _CACHE_AT = time.monotonic()
        return _CACHE_VALUE


@app.get("/")
def index():
    return send_from_directory(WEB_ROOT, "index.html")


@app.get("/<path:name>")
def assets(name: str):
    return send_from_directory(WEB_ROOT, name)


@app.get("/api/health")
def health():
    payload = dashboard_data()
    body = {key: payload[key] for key in ("status", "updated_at", "market_count", "snapshot_count", "alert_count")}
    return jsonify(body), 200 if payload["status"] == "healthy" else 503


@app.get("/favicon.ico")
def favicon():
    return Response(status=204)


@app.get("/api/dashboard")
def dashboard():
    return jsonify(dashboard_data())


@app.get("/api/category/<slug>")
def category(slug: str):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,159}", slug):
        return jsonify({"error": "invalid category slug"}), 400
    try:
        markets = live_category(slug)
    except CategoryRateLimit:
        return jsonify({"error": "too many category lookups; retry shortly"}), 429
    except (OSError, RuntimeError, ValueError, KeyError):
        return jsonify({"error": "category unavailable"}), 502
    return jsonify({"slug": slug, "markets": markets}), 200 if markets else 404


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8091")))
