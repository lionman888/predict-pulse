"""Read-only web dashboard for Predict Pulse."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import urllib.parse
from pathlib import Path

from flask import Flask, Response, jsonify, send_from_directory

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("PREDICT_PULSE_DB", "/var/lib/predict-pulse/pulse.sqlite3"))
WEB_ROOT = ROOT / "web"
app = Flask(__name__)
_CACHE_LOCK = threading.Lock()
_CACHE_VALUE = None
_CACHE_AT = 0.0
CACHE_SECONDS = float(os.getenv("DASHBOARD_CACHE_SECONDS", "5"))


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
                    "url": market_url(row["category_slug"]),
                }
            )
        movers.sort(key=lambda row: max(abs(row["delta15"] or 0), abs(row["delta60"] or 0)), reverse=True)
        moved15_count = sum(1 for row in movers if abs(row["delta15"] or 0) >= 1.0)
        active_movers = [
            row for row in movers
            if max(abs(row["delta15"] or 0), abs(row["delta60"] or 0)) >= 0.1
        ]
        alerts = [dict(row) for row in db.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT 30").fetchall()]
    return {
        "status": "healthy" if latest_time and time.time() - latest_time < 180 else "stale",
        "updated_at": latest_time,
        "market_count": market_count,
        "snapshot_count": snapshot_count,
        "alert_count": alert_count,
        "moved15_count": moved15_count,
        "movers": active_movers[:30],
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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8091")))
