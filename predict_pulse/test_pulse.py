import tempfile
import unittest
from pathlib import Path

from predict_pulse.pulse import (
    Notifier,
    PredictAPI,
    Snapshot,
    Store,
    category_slug,
    choose_markets,
    detect,
    market_segment,
    probability,
    suppress_systemic_alerts,
    validate_config,
)


def row(at, probability_value=0.5, volume=100, liquidity=1000, spread=0.02):
    return Snapshot(at, "1", "T", "Q", "slug", "Yes", probability_value, 0.49, 0.51, spread, volume, volume, liquidity)


class PulseTests(unittest.TestCase):
    def test_market_pagination_uses_after_and_deduplicates(self):
        class FakeAPI(PredictAPI):
            def __init__(self):
                pass

            def get(self, path, query=None):
                if not query.get("after"):
                    return {"data": [{"id": 1}], "cursor": "next"}, {}
                self.assert_query = query
                return {"data": [{"id": 1}, {"id": 2}], "cursor": None}, {}

        api = FakeAPI()
        markets, _ = api.markets(3)
        self.assertEqual([row["id"] for row in markets], [1, 2])
        self.assertEqual(api.assert_query["after"], "next")

    def test_probability_uses_two_sided_book(self):
        result = probability(
            [
                {"name": "Yes", "bestBid": {"price": 0.42}, "bestAsk": {"price": 0.46}},
                {"name": "No", "bestBid": {"price": 0.54}, "bestAsk": {"price": 0.58}},
            ]
        )
        self.assertAlmostEqual(result[1], 0.44)
        self.assertAlmostEqual(result[4], 0.04)

    def test_probability_derives_missing_side_from_complement(self):
        result = probability(
            [
                {"name": "Yes", "bestBid": None, "bestAsk": {"price": 0.60}},
                {"name": "No", "bestBid": {"price": 0.40}, "bestAsk": {"price": 0.44}},
            ]
        )
        self.assertAlmostEqual(result[1], 0.58)
        self.assertAlmostEqual(result[4], 0.04)

    def test_probability_rejects_crossed_spread(self):
        result = probability(
            [
                {"name": "Yes", "bestBid": {"price": 0.60}, "bestAsk": {"price": 0.55}},
                {"name": "No", "bestBid": {"price": 0.45}, "bestAsk": {"price": 0.40}},
            ]
        )
        self.assertIsNone(result[4])

    def test_probability_does_not_invent_midpoint_from_one_sided_book(self):
        result = probability([{"name": "Yes", "bestBid": None, "bestAsk": {"price": 0.60}}])
        self.assertIsNone(result[1])
        self.assertIsNone(result[4])
        self.assertEqual(result[3], 0.60)

    def test_systemic_alert_storm_is_suppressed(self):
        items = [{"kind": "liquidity"} for _ in range(13)] + [{"kind": "volume"}]
        filtered, suppressed = suppress_systemic_alerts(items, 50)
        self.assertEqual(filtered, [{"kind": "volume"}])
        self.assertEqual(suppressed, {"liquidity"})

    def test_category_slug_accepts_predict_link(self):
        self.assertEqual(
            category_slug("https://predict.fun/category/will-bitcoin-hit-100k"),
            "will-bitcoin-hit-100k",
        )
        with self.assertRaisesRegex(ValueError, "not a Predict URL"):
            category_slug("https://example.com/category/nope")

    def test_market_segment_classification(self):
        self.assertEqual(market_segment({"variantData": {"type": "ESPORTS_LOL"}}), "esports")
        self.assertEqual(market_segment({"marketVariant": "CRYPTO_UP_DOWN"}), "crypto")
        self.assertEqual(market_segment({"marketType": "SPORTS_MONEYLINE"}), "sports")

    def test_watchlist_fetches_category_markets(self):
        class FakeAPI:
            def category(self, slug):
                return [{"id": 1, "categorySlug": slug, "tradingStatus": "OPEN"}]

        cfg = {
            "max_markets": 10,
            "monitoring": {
                "mode": "watchlist",
                "market_urls": ["https://predict.fun/category/example"],
            },
        }
        markets, _ = choose_markets(FakeAPI(), cfg)
        self.assertEqual(markets[0]["categorySlug"], "example")

    def test_detector_probability_alert(self):
        cfg = {
            "thresholds": {
                "probability_points_15m": 5,
                "probability_points_60m": 10,
                "volume24h_delta_usd": 1000,
                "liquidity_change_percent": 25,
                "spread_change_points": 5,
            }
        }
        alerts = detect(row(1000, 0.58), row(990, 0.55), row(100, 0.50), None, cfg)
        self.assertIn("probability_15m", [item["kind"] for item in alerts])

    def test_detector_covers_all_signal_types(self):
        cfg = {
            "thresholds": {
                "probability_points_15m": 5,
                "probability_points_60m": 10,
                "volume24h_delta_usd": 1000,
                "liquidity_change_percent": 25,
                "spread_change_points": 5,
            }
        }
        current = row(4000, 0.70, volume=1500, liquidity=1500, spread=0.10)
        previous = row(3990, 0.69, volume=100, liquidity=1490, spread=0.09)
        baseline15 = row(3000, 0.50, volume=100, liquidity=1000, spread=0.02)
        baseline60 = row(100, 0.50, volume=100, liquidity=1000, spread=0.02)
        kinds = {item["kind"] for item in detect(current, previous, baseline15, baseline60, cfg)}
        self.assertEqual(kinds, {"probability_15m", "probability_60m", "volume", "liquidity", "spread"})

    def test_store_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(str(Path(directory) / "pulse.sqlite3"))
            store.insert_snapshots([row(1000)])
            self.assertEqual(store.latest("1").market_id, "1")
            self.assertEqual(store.summary()["snapshots"], 1)

    def test_store_deduplicates_and_prunes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(str(Path(directory) / "pulse.sqlite3"))
            store.insert_snapshots([row(1000), row(1000, 0.6), row(2000)])
            self.assertEqual(store.summary()["snapshots"], 2)
            self.assertEqual(store.latest("1").captured_at, 2000)
            self.assertEqual(store.prune(1500), 1)

    def test_failed_delivery_does_not_start_cooldown(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(str(Path(directory) / "pulse.sqlite3"))
            item = {
                "created_at": 1000,
                "market_id": "1",
                "kind": "spread",
                "severity": "low",
                "title": "T",
                "body": "B",
            }
            store.record_alert(item, False)
            self.assertFalse(store.in_cooldown("1", "spread", 900))
            item["created_at"] = 1100
            store.record_alert(item, True)
            self.assertTrue(store.in_cooldown("1", "spread", 900))

    def test_config_rejects_rate_limit_overrun(self):
        config = {
            "api_key_file": "/var/lib/predict-pulse/test-key",
            "database": "/var/lib/predict-pulse/test-db",
            "poll_seconds": 15,
            "max_markets": 200,
            "stats_workers": 6,
            "rate_limit_per_minute": 240,
            "thresholds": {
                "probability_points_15m": 5,
                "probability_points_60m": 10,
                "volume24h_delta_usd": 1000,
                "liquidity_change_percent": 25,
                "spread_change_points": 5,
            },
        }
        with self.assertRaisesRegex(ValueError, "exceed API limit"):
            validate_config(config)

    def test_notifier_continues_when_one_sink_fails(self):
        class FakeNotifier(Notifier):
            calls = []

            @staticmethod
            def post(url, data=None):
                FakeNotifier.calls.append(url)
                if "api.day.app" in url:
                    raise OSError("bark unavailable")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bark").write_text("bark-key")
            (root / "telegram").write_text("telegram-token")
            notifier = FakeNotifier(
                {
                    "console": True,
                    "bark": {"enabled": True, "key_file": str(root / "bark")},
                    "telegram": {"enabled": True, "token_file": str(root / "telegram"), "chat_id": "1"},
                }
            )
            delivered = notifier.send({"title": "T", "body": "B"})
            self.assertTrue(delivered)
            self.assertEqual(len(FakeNotifier.calls), 2)


if __name__ == "__main__":
    unittest.main()
