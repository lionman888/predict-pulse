#!/usr/bin/env python3
"""Predict Pulse: read-only Predict market snapshots and anomaly alerts."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


BASE_URL = "https://api.predict.fun/v1"


def read_secret(path: str | None, env_name: str | None = None) -> str:
    if env_name and os.getenv(env_name):
        return os.environ[env_name].strip()
    if path:
        value = Path(path).expanduser().read_text().strip()
        if value:
            return value
    raise RuntimeError(f"missing secret: {env_name or path}")


def load_env_value(path: str, key: str) -> str:
    for line in Path(path).expanduser().read_text().splitlines():
        if line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    raise RuntimeError(f"{key} missing in {path}")


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def quote_price(quote: Any) -> float | None:
    return as_float((quote or {}).get("price")) if isinstance(quote, dict) else None


@dataclass
class Snapshot:
    captured_at: int
    market_id: str
    title: str
    question: str
    category_slug: str
    outcome: str
    probability: float | None
    best_bid: float | None
    best_ask: float | None
    spread: float | None
    volume24h_usd: float | None
    volume_total_usd: float | None
    liquidity_usd: float | None

    @property
    def market_url(self) -> str:
        if self.category_slug:
            return f"https://predict.fun/category/{self.category_slug}"
        return "https://predict.fun"


class PredictAPI:
    def __init__(self, api_key: str, base_url: str = BASE_URL, timeout: int = 20):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, path: str, query: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, str]]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(
            url,
            headers={
                "accept": "application/json",
                "origin": "https://predict.fun",
                "referer": "https://predict.fun/",
                "user-agent": "PredictPulse/0.1",
                "x-api-key": self.api_key,
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.load(response)
            headers = {key.lower(): value for key, value in response.headers.items()}
        return payload, headers

    def markets(self, limit: int) -> tuple[list[dict[str, Any]], dict[str, str]]:
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        cursor: str | None = None
        last_headers: dict[str, str] = {}
        while len(rows) < limit:
            query: dict[str, Any] = {"first": min(20, limit - len(rows)), "status": "OPEN"}
            if cursor:
                query["after"] = cursor
            payload, last_headers = self.get("markets", query)
            page = payload.get("data") or []
            if not page:
                break
            added = 0
            for row in page:
                market_id = str(row.get("id") or "")
                if market_id and market_id not in seen:
                    rows.append(row)
                    seen.add(market_id)
                    added += 1
            next_cursor = payload.get("cursor")
            if not next_cursor or next_cursor == cursor or added == 0:
                break
            cursor = str(next_cursor)
        return rows[:limit], last_headers

    def stats(self, market_id: str) -> dict[str, Any]:
        payload, _ = self.get(f"markets/{market_id}/stats")
        return payload.get("data") or {}


class Store:
    def __init__(self, path: str):
        db_path = Path(path).expanduser()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              captured_at INTEGER NOT NULL,
              market_id TEXT NOT NULL,
              title TEXT NOT NULL,
              question TEXT NOT NULL,
              category_slug TEXT NOT NULL,
              outcome TEXT NOT NULL,
              probability REAL,
              best_bid REAL,
              best_ask REAL,
              spread REAL,
              volume24h_usd REAL,
              volume_total_usd REAL,
              liquidity_usd REAL
            );
            CREATE INDEX IF NOT EXISTS idx_snapshots_market_time
              ON snapshots(market_id, captured_at DESC);
            CREATE TABLE IF NOT EXISTS alerts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              created_at INTEGER NOT NULL,
              market_id TEXT NOT NULL,
              kind TEXT NOT NULL,
              severity TEXT NOT NULL,
              title TEXT NOT NULL,
              body TEXT NOT NULL,
              delivered INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_market_kind_time
              ON alerts(market_id, kind, created_at DESC);
            """
        )
        self.db.commit()

    def baseline(self, market_id: str, at_or_before: int) -> Snapshot | None:
        row = self.db.execute(
            "SELECT * FROM snapshots WHERE market_id=? AND captured_at<=? ORDER BY captured_at DESC LIMIT 1",
            (market_id, at_or_before),
        ).fetchone()
        return Snapshot(**{key: row[key] for key in Snapshot.__dataclass_fields__}) if row else None

    def latest(self, market_id: str) -> Snapshot | None:
        row = self.db.execute(
            "SELECT * FROM snapshots WHERE market_id=? ORDER BY captured_at DESC LIMIT 1", (market_id,)
        ).fetchone()
        return Snapshot(**{key: row[key] for key in Snapshot.__dataclass_fields__}) if row else None

    def insert_snapshots(self, rows: list[Snapshot]):
        names = list(Snapshot.__dataclass_fields__)
        sql = f"INSERT INTO snapshots ({','.join(names)}) VALUES ({','.join('?' for _ in names)})"
        self.db.executemany(sql, [[getattr(row, name) for name in names] for row in rows])
        self.db.commit()

    def in_cooldown(self, market_id: str, kind: str, after: int) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM alerts WHERE market_id=? AND kind=? AND created_at>=? LIMIT 1",
            (market_id, kind, after),
        ).fetchone()
        return bool(row)

    def record_alert(self, alert: dict[str, Any], delivered: bool):
        self.db.execute(
            "INSERT INTO alerts(created_at,market_id,kind,severity,title,body,delivered) VALUES(?,?,?,?,?,?,?)",
            (
                alert["created_at"], alert["market_id"], alert["kind"], alert["severity"],
                alert["title"], alert["body"], int(delivered),
            ),
        )
        self.db.commit()

    def summary(self) -> dict[str, int]:
        markets = self.db.execute("SELECT COUNT(DISTINCT market_id) FROM snapshots").fetchone()[0]
        snapshots = self.db.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        alerts = self.db.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
        return {"markets": markets, "snapshots": snapshots, "alerts": alerts}

    def prune(self, before: int) -> int:
        cursor = self.db.execute("DELETE FROM snapshots WHERE captured_at<?", (before,))
        self.db.commit()
        return cursor.rowcount


def probability(outcomes: list[dict[str, Any]]) -> tuple[str, float | None, float | None, float | None, float | None]:
    if not outcomes:
        return "", None, None, None, None
    primary = outcomes[0]
    name = str(primary.get("name") or "Outcome 1")
    bid = quote_price(primary.get("bestBid"))
    ask = quote_price(primary.get("bestAsk"))
    if bid is not None and ask is not None:
        price = (bid + ask) / 2
        spread = max(0.0, ask - bid)
    elif bid is not None:
        price, spread = bid, None
    elif ask is not None:
        price, spread = ask, None
    else:
        price, spread = None, None
    if len(outcomes) > 1 and (price is None or spread is None):
        other_bid = quote_price(outcomes[1].get("bestBid"))
        other_ask = quote_price(outcomes[1].get("bestAsk"))
        derived_bid = 1 - other_ask if other_ask is not None else None
        derived_ask = 1 - other_bid if other_bid is not None else None
        bid = bid if bid is not None else derived_bid
        ask = ask if ask is not None else derived_ask
        if bid is not None and ask is not None:
            price = (bid + ask) / 2
            spread = max(0.0, ask - bid)
    return name, price, bid, ask, spread


def build_snapshot(market: dict[str, Any], stats: dict[str, Any], captured_at: int) -> Snapshot:
    outcome, chance, bid, ask, spread = probability(market.get("outcomes") or [])
    return Snapshot(
        captured_at=captured_at,
        market_id=str(market.get("id") or ""),
        title=str(market.get("title") or market.get("question") or "Untitled market"),
        question=str(market.get("question") or market.get("title") or ""),
        category_slug=str(market.get("categorySlug") or ""),
        outcome=outcome,
        probability=chance,
        best_bid=bid,
        best_ask=ask,
        spread=spread,
        volume24h_usd=as_float(stats.get("volume24hUsd")),
        volume_total_usd=as_float(stats.get("volumeTotalUsd")),
        liquidity_usd=as_float(stats.get("totalLiquidityUsd")),
    )


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous) * 100


def alert(kind: str, severity: str, row: Snapshot, headline: str, detail: str) -> dict[str, Any]:
    body = f"{row.question}\n{detail}\n{row.market_url}"
    return {
        "created_at": row.captured_at,
        "market_id": row.market_id,
        "kind": kind,
        "severity": severity,
        "title": f"Predict Pulse｜{headline}",
        "body": body,
    }


def detect(row: Snapshot, previous: Snapshot | None, baseline15: Snapshot | None, baseline60: Snapshot | None, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    thresholds = cfg["thresholds"]
    alerts: list[dict[str, Any]] = []
    if row.probability is not None and baseline15 and baseline15.probability is not None:
        delta = (row.probability - baseline15.probability) * 100
        if abs(delta) >= float(thresholds["probability_points_15m"]):
            direction = "急升" if delta > 0 else "急跌"
            alerts.append(alert("probability_15m", "high", row, f"概率15分钟{direction} {delta:+.1f}点", f"{row.outcome} 当前约 {row.probability:.1%}"))
    if row.probability is not None and baseline60 and baseline60.probability is not None:
        delta = (row.probability - baseline60.probability) * 100
        if abs(delta) >= float(thresholds["probability_points_60m"]):
            direction = "上升" if delta > 0 else "下降"
            alerts.append(alert("probability_60m", "medium", row, f"概率1小时{direction} {delta:+.1f}点", f"{row.outcome} 当前约 {row.probability:.1%}"))
    if previous and row.volume24h_usd is not None and previous.volume24h_usd is not None:
        delta = row.volume24h_usd - previous.volume24h_usd
        if delta >= float(thresholds["volume24h_delta_usd"]):
            alerts.append(alert("volume", "medium", row, f"成交量增加 ${delta:,.0f}", f"24小时成交量约 ${row.volume24h_usd:,.0f}"))
    if baseline15:
        change = pct_change(row.liquidity_usd, baseline15.liquidity_usd)
        if change is not None and abs(change) >= float(thresholds["liquidity_change_percent"]):
            direction = "增加" if change > 0 else "下降"
            alerts.append(alert("liquidity", "medium", row, f"流动性15分钟{direction} {change:+.1f}%", f"当前流动性约 ${row.liquidity_usd:,.0f}"))
        if row.spread is not None and baseline15.spread is not None:
            delta = (row.spread - baseline15.spread) * 100
            if abs(delta) >= float(thresholds["spread_change_points"]):
                direction = "扩大" if delta > 0 else "收窄"
                alerts.append(alert("spread", "low", row, f"价差15分钟{direction} {delta:+.1f}点", f"当前价差约 {row.spread:.1%}"))
    return alerts


class Notifier:
    def __init__(self, cfg: dict[str, Any], dry_run: bool = False):
        self.cfg = cfg
        self.dry_run = dry_run

    @staticmethod
    def post(url: str, data: dict[str, Any] | None = None) -> None:
        encoded = urllib.parse.urlencode(data).encode() if data else None
        request = urllib.request.Request(url, data=encoded, headers={"user-agent": "PredictPulse/0.1"})
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status >= 300:
                raise RuntimeError(f"notification HTTP {response.status}")

    def send(self, item: dict[str, Any]) -> bool:
        print(json.dumps({"alert": item}, ensure_ascii=False), flush=True)
        if self.dry_run:
            return True
        delivered = False
        bark = self.cfg.get("bark") or {}
        if bark.get("enabled"):
            if bark.get("key_env_file"):
                key = load_env_value(bark["key_env_file"], bark.get("key_name", "BARK_KEY"))
            else:
                key = read_secret(bark.get("key_file"), bark.get("key_env"))
            title = urllib.parse.quote(item["title"], safe="")
            body = urllib.parse.quote(item["body"], safe="")
            self.post(f"https://api.day.app/{key}/{title}/{body}?group=PredictPulse")
            delivered = True
        telegram = self.cfg.get("telegram") or {}
        if telegram.get("enabled"):
            token = read_secret(telegram.get("token_file"), telegram.get("token_env"))
            self.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                {"chat_id": str(telegram["chat_id"]), "text": f"{item['title']}\n\n{item['body']}", "disable_web_page_preview": "true"},
            )
            delivered = True
        return delivered or bool(self.cfg.get("console", True))


class Pulse:
    def __init__(self, config: dict[str, Any], dry_run: bool = False):
        self.config = config
        self.api = PredictAPI(read_secret(config.get("api_key_file"), config.get("api_key_env")), config.get("base_url", BASE_URL))
        self.store = Store(config["database"])
        self.notifier = Notifier(config.get("notifications") or {"console": True}, dry_run=dry_run)
        self.dry_run = dry_run

    def collect(self) -> dict[str, Any]:
        now = int(time.time())
        markets, headers = self.api.markets(int(self.config.get("max_markets", 50)))
        workers = max(1, min(int(self.config.get("stats_workers", 6)), 12))
        stats: dict[str, dict[str, Any]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.api.stats, str(row["id"])): str(row["id"]) for row in markets}
            for future in concurrent.futures.as_completed(futures):
                market_id = futures[future]
                try:
                    stats[market_id] = future.result()
                except Exception as exc:
                    print(json.dumps({"warning": "stats_failed", "market_id": market_id, "error": str(exc)[:160]}), file=sys.stderr)
                    stats[market_id] = {}
        snapshots = [build_snapshot(row, stats.get(str(row.get("id")), {}), now) for row in markets if row.get("id")]
        candidates: list[dict[str, Any]] = []
        cooldown_after = now - int(self.config.get("cooldown_minutes", 30)) * 60
        for row in snapshots:
            previous = self.store.latest(row.market_id)
            baseline15 = self.store.baseline(row.market_id, now - 15 * 60)
            baseline60 = self.store.baseline(row.market_id, now - 60 * 60)
            for item in detect(row, previous, baseline15, baseline60, self.config):
                if not self.store.in_cooldown(row.market_id, item["kind"], cooldown_after):
                    candidates.append(item)
        self.store.insert_snapshots(snapshots)
        retention_days = max(1, int(self.config.get("retention_days", 30)))
        pruned = self.store.prune(now - retention_days * 86400)
        delivered = 0
        for item in candidates:
            ok = self.notifier.send(item)
            self.store.record_alert(item, ok)
            delivered += int(ok)
        return {
            "captured_at": now,
            "markets": len(snapshots),
            "alerts": len(candidates),
            "delivered": delivered,
            "rate_limit_remaining": headers.get("ratelimit-remaining"),
            "pruned": pruned,
            "database": self.store.summary(),
        }

    def run(self, once: bool = False):
        interval = max(15, int(self.config.get("poll_seconds", 60)))
        while True:
            started = time.monotonic()
            try:
                print(json.dumps({"cycle": self.collect()}, ensure_ascii=False), flush=True)
            except Exception as exc:
                print(json.dumps({"error": str(exc)[:500]}), file=sys.stderr, flush=True)
                if once:
                    raise
            if once:
                return
            time.sleep(max(1, interval - (time.monotonic() - started)))


def load_config(path: str) -> dict[str, Any]:
    return json.loads(Path(path).expanduser().read_text())


def main():
    parser = argparse.ArgumentParser(description="Predict Pulse read-only anomaly monitor")
    parser.add_argument("--config", required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print alerts without external notifications")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--test-notify", action="store_true")
    args = parser.parse_args()
    pulse = Pulse(load_config(args.config), dry_run=args.dry_run)
    if args.status:
        print(json.dumps(pulse.store.summary(), ensure_ascii=False, indent=2))
        return
    if args.test_notify:
        item = {
            "created_at": int(time.time()),
            "market_id": "test",
            "kind": "test",
            "severity": "low",
            "title": "Predict Pulse｜通知测试",
            "body": "东京监控服务已连接，Bark/Telegram 通知通道可用。",
        }
        print(json.dumps({"delivered": pulse.notifier.send(item)}, ensure_ascii=False))
        return
    pulse.run(once=args.once)


if __name__ == "__main__":
    main()
