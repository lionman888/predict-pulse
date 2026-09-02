import tempfile
import time
import unittest
from pathlib import Path

import web
from predict_pulse.pulse import Snapshot, Store


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        web.DB_PATH = Path(self.temp.name) / "pulse.sqlite3"
        web._CACHE_VALUE = None
        web._CACHE_AT = 0.0
        self.store = Store(str(web.DB_PATH))
        now = int(time.time())
        self.store.insert_snapshots(
            [
                Snapshot(now - 901, "1", "Market", "Question", "slug", "Yes", 0.40, 0.39, 0.41, 0.02, 10, 20, 100),
                Snapshot(now, "1", "Market", "Question", "slug", "Yes", 0.50, 0.49, 0.51, 0.02, 20, 30, 120),
            ]
        )
        self.client = web.app.test_client()

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_health(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "healthy")
        self.assertEqual(response.json["market_count"], 1)

    def test_dashboard_mover(self):
        response = self.client.get("/api/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertAlmostEqual(response.json["movers"][0]["delta15"], 10.0)
        self.assertEqual(response.json["movers"][0]["best_bid"], 0.49)
        self.assertEqual(response.json["moved15_count"], 1)
        self.assertEqual(response.json["display_mode"], "movers")
        self.assertEqual(response.json["movers"][0]["url"], "https://predict.fun/category/slug")

    def test_health_returns_503_for_stale_data(self):
        self.store.db.execute("UPDATE snapshots SET captured_at=captured_at-10000")
        self.store.db.commit()
        web._CACHE_VALUE = None
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["status"], "stale")

    def test_dashboard_falls_back_to_liquid_watchlist(self):
        self.store.db.execute("UPDATE snapshots SET probability=0.50")
        self.store.db.commit()
        web._CACHE_VALUE = None
        response = self.client.get("/api/dashboard")
        self.assertEqual(response.json["display_mode"], "watchlist")
        self.assertEqual(len(response.json["movers"]), 1)


if __name__ == "__main__":
    unittest.main()
