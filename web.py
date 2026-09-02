#!/usr/bin/env python3
"""Read-only web dashboard for Predict Pulse."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from flask import Flask, Response, jsonify, send_from_directory


ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("PREDICT_PULSE_DB", "/var/lib/predict-pulse/pulse.sqlite3"))
WEB_ROOT = ROOT / "web"
app = Flask(__name__)


def connect():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def market_url(slug: str) -> str:
    return f"https://predict.fun/category/{slug}" if slug else "https://predict.fun"


def dashboard_data():
    with connect() as db:
        latest_time = db.execute("SELECT MAX(captured_at) FROM snapshots").fetchone()[0] or 0
        market_count = db.execute("SELECT COUNT(DISTINCT market_id) FROM snapshots").fetchone()[0]
        snapshot_count = db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        alert_count = db.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
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
                "SELECT probability FROM snapshots WHERE market_id=? AND captured_at<=? ORDER BY captured_at DESC LIMIT 1",
                (row["market_id"], row["captured_at"] - 900),
            ).fetchone()
            old60 = db.execute(
                "SELECT probability FROM snapshots WHERE market_id=? AND captured_at<=? ORDER BY captured_at DESC LIMIT 1",
                (row["market_id"], row["captured_at"] - 3600),
            ).fetchone()
            p = row["probability"]
            delta15 = (p - old15[0]) * 100 if p is not None and old15 and old15[0] is not None else None
            delta60 = (p - old60[0]) * 100 if p is not None and old60 and old60[0] is not None else None
            movers.append({
                "market_id": row["market_id"],
                "title": row["title"],
                "question": row["question"],
                "outcome": row["outcome"],
                "probability": p,
                "delta15": delta15,
                "delta60": delta60,
                "spread": row["spread"],
                "volume24h": row["volume24h_usd"],
                "liquidity": row["liquidity_usd"],
                "url": market_url(row["category_slug"]),
            })
        movers.sort(key=lambda row: max(abs(row["delta15"] or 0), abs(row["delta60"] or 0)), reverse=True)
        alerts = [dict(row) for row in db.execute("SELECT * FROM alerts ORDER BY created_at DESC LIMIT 30").fetchall()]
    return {
        "status": "healthy" if latest_time and time.time() - latest_time < 180 else "stale",
        "updated_at": latest_time,
        "market_count": market_count,
        "snapshot_count": snapshot_count,
        "alert_count": alert_count,
        "movers": movers[:30],
        "alerts": alerts,
    }


@app.get("/")
def index():
    return send_from_directory(WEB_ROOT, "index.html")


@app.get("/<path:name>")
def assets(name: str):
    return send_from_directory(WEB_ROOT, name)


@app.get("/api/health")
def health():
    payload = dashboard_data()
    return jsonify({key: payload[key] for key in ("status", "updated_at", "market_count", "snapshot_count", "alert_count")})


@app.get("/favicon.ico")
def favicon():
    return Response(status=204)


@app.get("/api/dashboard")
def dashboard():
    return jsonify(dashboard_data())


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8091")))
