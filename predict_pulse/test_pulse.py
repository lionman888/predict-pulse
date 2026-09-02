import tempfile
import unittest
from pathlib import Path

from predict_pulse.pulse import PredictAPI, Snapshot, Store, detect, probability


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
        result = probability([
            {"name": "Yes", "bestBid": {"price": 0.42}, "bestAsk": {"price": 0.46}},
            {"name": "No", "bestBid": {"price": 0.54}, "bestAsk": {"price": 0.58}},
        ])
        self.assertAlmostEqual(result[1], 0.44)
        self.assertAlmostEqual(result[4], 0.04)

    def test_probability_derives_missing_side_from_complement(self):
        result = probability([
            {"name": "Yes", "bestBid": None, "bestAsk": {"price": 0.60}},
            {"name": "No", "bestBid": {"price": 0.40}, "bestAsk": {"price": 0.44}},
        ])
        self.assertAlmostEqual(result[1], 0.58)
        self.assertAlmostEqual(result[4], 0.04)

    def test_detector_probability_alert(self):
        cfg = {"thresholds": {"probability_points_15m": 5, "probability_points_60m": 10, "volume24h_delta_usd": 1000, "liquidity_change_percent": 25, "spread_change_points": 5}}
        alerts = detect(row(1000, 0.58), row(990, 0.55), row(100, 0.50), None, cfg)
        self.assertIn("probability_15m", [item["kind"] for item in alerts])

    def test_store_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(str(Path(directory) / "pulse.sqlite3"))
            store.insert_snapshots([row(1000)])
            self.assertEqual(store.latest("1").market_id, "1")
            self.assertEqual(store.summary()["snapshots"], 1)


if __name__ == "__main__":
    unittest.main()
