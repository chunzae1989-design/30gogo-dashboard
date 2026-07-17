import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dashboard_strategy import apply_qqq_new_money_policy, latest_daily_change, promote_latest_guru_cache


def guru(as_of):
    return {"asOf": as_of, "philosophies": [{"key": "Buffett"}], "rows": [{"ticker": "QQQ"}]}


class DashboardStrategyTest(unittest.TestCase):
    def test_promotes_only_newer_valid_guru_cache(self):
        payload = {"guruData": guru("2026-07-16 07:00 KST")}
        with TemporaryDirectory() as directory:
            path = Path(directory) / "valuation_cache.json"
            path.write_text(json.dumps(guru("2026-07-17 07:23 KST")), encoding="utf-8")
            status = promote_latest_guru_cache(payload, [path])
        self.assertTrue(status["updated"])
        self.assertEqual(payload["guruData"]["asOf"], "2026-07-17 07:23 KST")

    def test_applies_qqq_cash_new_money_policy(self):
        payload = {"dashboardConfig": {
            "allocationPlan": [{"ticker": "379800", "share": 1}],
            "rules": [{"ticker": "379800", "operator": "min"}, {"ticker": "TSLA", "operator": "max"}],
        }}
        apply_qqq_new_money_policy(payload)
        active = [row for row in payload["dashboardConfig"]["allocationPlan"] if not row.get("hold")]
        self.assertEqual([(row["ticker"], row["share"]) for row in active], [("QQQ", 0.55), ("CASH", 0.45)])
        self.assertEqual(payload["dashboardConfig"]["newMoneyPolicy"]["strategy"], "QQQ_CASH")
        self.assertEqual([rule["ticker"] for rule in payload["dashboardConfig"]["rules"]], ["TSLA"])

    def test_calculates_latest_daily_change(self):
        change = latest_daily_change([
            {"timestamp": "2026-07-16T13:00:00+09:00", "closePrice": "100"},
            {"timestamp": "2026-07-17T13:00:00+09:00", "closePrice": "110"},
        ])
        self.assertAlmostEqual(change["changePct"], 10)
        self.assertEqual(change["asOf"], "2026-07-17T13:00:00+09:00")


if __name__ == "__main__":
    unittest.main()
