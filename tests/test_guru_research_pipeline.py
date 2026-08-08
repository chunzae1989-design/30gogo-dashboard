import unittest

from guru_research_pipeline import candle_metrics, market_close_cutoff, sec_ticker_map


class GuruResearchPipelineTest(unittest.TestCase):
    def test_market_close_cutoff_uses_new_york_close(self):
        self.assertEqual(market_close_cutoff("2026-07-31"), "2026-07-31T20:00:00Z")

    def test_sec_ticker_map_normalizes_share_class_separator(self):
        result = sec_ticker_map({"0": {"ticker": "BRK-B", "cik_str": 1067983, "title": "Berkshire"}})
        self.assertEqual(result["BRK.B"]["cik"], "0001067983")

    def test_candle_metrics_uses_adjusted_closes_and_liquidity(self):
        result = candle_metrics([
            {"date": "2026-07-30", "adjustedClose": 100, "volume": 10},
            {"date": "2026-07-31", "adjustedClose": 110, "volume": 20},
        ])
        self.assertAlmostEqual(result["dailyChange"], 10)
        self.assertEqual(result["position52w"], 1)
        self.assertEqual(result["dollarVolume"], 1600)


if __name__ == "__main__":
    unittest.main()
