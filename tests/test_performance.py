import unittest

from performance_core import build_performance


def snapshot(day, total, price=100, quantity=10):
    return {
        "asOf": f"{day}T22:00:00+09:00",
        "totalKrw": total,
        "usdKrw": 1400,
        "positions": [{"ticker": "TEST", "name": "Test", "quantity": quantity, "priceKrw": price, "valueKrw": price * quantity}],
    }


class PerformanceTest(unittest.TestCase):
    def test_twr_removes_external_deposit(self):
        history = {"snapshots": [
            snapshot("2026-06-23", 1_000),
            snapshot("2026-06-24", 1_200),
            snapshot("2026-06-25", 1_320),
        ]}
        flows = [{"id": 1, "date": "2026-06-24", "amountKrw": 100, "kind": "deposit", "note": "test"}]
        benchmark = [
            {"date": "2026-06-23", "close": 100, "currency": "KRW"},
            {"date": "2026-06-25", "close": 110, "currency": "KRW"},
        ]
        result = build_performance(history, flows, benchmark, "2026-06-25")
        self.assertAlmostEqual(result["summary"]["portfolioReturn"], 0.21, places=8)
        self.assertAlmostEqual(result["summary"]["benchmarkReturn"], 0.10, places=8)
        self.assertAlmostEqual(result["summary"]["excessReturn"], 0.11, places=8)
        self.assertEqual(result["status"], "official")

    def test_unreviewed_ledger_is_provisional(self):
        history = {"snapshots": [snapshot("2026-06-23", 1_000), snapshot("2026-06-24", 900)]}
        result = build_performance(history, [], [], "2026-06-23")
        self.assertEqual(result["status"], "provisional")
        self.assertAlmostEqual(result["summary"]["maxDrawdown"], -0.10)

    def test_qqq_benchmark_is_converted_to_krw(self):
        first = snapshot("2026-06-23", 1_000)
        second = snapshot("2026-06-24", 1_000)
        first["usdKrw"] = 1_000
        second["usdKrw"] = 900
        benchmark = [
            {"date": "2026-06-23", "close": 100, "currency": "USD"},
            {"date": "2026-06-24", "close": 110, "currency": "USD"},
        ]
        result = build_performance({"snapshots": [first, second]}, [], benchmark, "2026-06-24")
        self.assertAlmostEqual(result["summary"]["benchmarkReturn"], -0.01, places=8)


if __name__ == "__main__":
    unittest.main()
