from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from guru_research import (
    LEGACY_MODEL,
    MARKET_MODEL,
    dedupe_universe,
    forward_return,
    init_research_db,
    metrics_for_horizon,
    score_market_company,
    select_top_five,
    store_market_scores,
    store_adjusted_prices,
    metrics_by_horizon_from_db,
    store_legacy_observations,
    legacy_validation,
    apply_cohort_entries,
    research_payload,
    set_research_meta,
)


class GuruResearchTest(unittest.TestCase):
    def fixture(self):
        return {
            "pe": 24, "pb": 5, "roe": 22, "operatingMargin": 28,
            "fcfYield": 3, "debtEquity": .4, "currentRatio": 1.8,
            "revenueGrowth": 18, "netIncomeGrowth": 20, "grossMargin": 55,
            "position52w": .72, "dailyChange": 1.2,
        }

    def test_market_score_is_versioned_and_has_no_holdings_penalty(self):
        result = score_market_company(self.fixture())
        self.assertTrue(result["eligible"])
        self.assertEqual(result["modelVersion"], MARKET_MODEL)
        self.assertEqual(result["lensCoverage"], 6)
        self.assertGreater(result["companyScore"], 50)
        self.assertEqual(MARKET_MODEL, "guru-market-nasdaq-v2")

    def test_missing_core_data_is_excluded_not_defaulted(self):
        result = score_market_company({"pe": 20, "roe": 15})
        self.assertFalse(result["eligible"])
        self.assertIsNone(result["companyScore"])
        self.assertTrue(any("growth" in reason for reason in result["exclusionReasons"]))

    def test_dedupes_cik_by_liquidity(self):
        rows = [
            {"ticker": "AAA", "cik": "1", "dollarVolume": 10},
            {"ticker": "AAB", "cik": "1", "dollarVolume": 20},
            {"ticker": "BBB", "cik": "2", "dollarVolume": 15},
        ]
        self.assertEqual([row["ticker"] for row in dedupe_universe(rows)], ["AAB", "BBB"])

    def test_excludes_current_holdings_from_top_five(self):
        rows = [{"ticker": f"T{i}", "eligible": True, "companyScore": 90 - i} for i in range(7)]
        selected = select_top_five(rows, ["T0", "T2"])
        self.assertEqual([row["ticker"] for row in selected], ["T1", "T3", "T4", "T5", "T6"])
        self.assertTrue(all(row["paperWeight"] == .2 for row in selected))

    def test_forward_return_uses_next_index_and_fixed_trading_days(self):
        prices = [100 + i for i in range(80)]
        self.assertAlmostEqual(forward_return(prices, 1, 21), 122 / 101 - 1)
        self.assertIsNone(forward_return(prices, 70, 21))

    def test_pending_metric_when_horizon_not_mature(self):
        metric = metrics_for_horizon([], "3M")
        self.assertEqual(metric["status"], "pending")
        self.assertEqual(metric["tradingDays"], 63)

    def test_source_failure_creates_no_cohort_and_top_five_membership_is_frozen(self):
        rows = [{"ticker": f"T{i}", "eligible": True, "companyScore": 90 - i, "scores": {}} for i in range(7)]
        with TemporaryDirectory() as directory:
            with init_research_db(Path(directory) / "guru.sqlite") as connection:
                failed = store_market_scores(connection, "2026-07-31", rows, [], source_complete=False)
                self.assertFalse(failed["created"])
                created = store_market_scores(connection, "2026-07-31", rows, ["T0"], source_complete=True)
                self.assertTrue(created["created"])
                kind = connection.execute("SELECT kind FROM cohorts").fetchone()[0]
                fixed = [row[0] for row in connection.execute("SELECT ticker FROM cohort_positions ORDER BY score DESC")]
                store_market_scores(connection, "2026-07-31", rows, ["T0", "T1", "T2"], source_complete=True)
                still_fixed = [row[0] for row in connection.execute("SELECT ticker FROM cohort_positions ORDER BY score DESC")]
        self.assertEqual(fixed, ["T1", "T2", "T3", "T4", "T5"])
        self.assertEqual(still_fixed, fixed)
        self.assertEqual(kind, "monthly")

    def test_bootstrap_cohort_kind_is_frozen(self):
        rows = [{"ticker": f"T{i}", "eligible": True, "companyScore": 90 - i, "scores": {}} for i in range(5)]
        with TemporaryDirectory() as directory:
            with init_research_db(Path(directory) / "guru.sqlite") as connection:
                store_market_scores(connection, "2026-08-07", rows, [], source_complete=True, cohort_kind="bootstrap")
                kind = connection.execute("SELECT kind FROM cohorts").fetchone()[0]
        self.assertEqual(kind, "bootstrap")

    def test_candidate_quote_is_included_in_encrypted_payload(self):
        rows = [{"ticker": f"T{i}", "eligible": True, "companyScore": 90 - i, "scores": {}} for i in range(5)]
        with TemporaryDirectory() as directory:
            with init_research_db(Path(directory) / "guru.sqlite") as connection:
                store_market_scores(connection, "2026-08-07", rows, [], source_complete=True, cohort_kind="bootstrap")
                set_research_meta(connection, "candidateQuotes", {"items": {"T0": {"lastPrice": 123.45, "timestamp": "2026-08-08T00:00:00Z"}}})
                payload = research_payload(connection)
        self.assertEqual(payload["candidates"][0]["lastPrice"], 123.45)

    def test_price_ledger_matures_21_day_metrics_without_lookahead(self):
        rows = [{"ticker": f"T{i}", "eligible": True, "companyScore": 90 - i, "scores": {}} for i in range(5)]
        with TemporaryDirectory() as directory:
            with init_research_db(Path(directory) / "guru.sqlite") as connection:
                store_market_scores(connection, "2026-07-01", rows, [], source_complete=True)
                for row in rows:
                    store_adjusted_prices(connection, row["ticker"], [{"date": f"2026-07-{day:02}", "adjustedClose": 100 + day} for day in range(2, 24)])
                for benchmark in ("QQQ", "SPY"):
                    store_adjusted_prices(connection, benchmark, [{"date": f"2026-07-{day:02}", "adjustedClose": 200 + day} for day in range(2, 24)])
                metrics = metrics_by_horizon_from_db(connection)
        self.assertEqual(metrics["1M"]["status"], "ready")
        self.assertEqual(metrics["1M"]["sampleSize"], 5)
        self.assertIsNotNone(metrics["1M"]["excessVsQqq"])

    def test_cohort_entry_uses_first_common_trading_day_after_signal(self):
        rows = [{"ticker": f"T{i}", "eligible": True, "companyScore": 90 - i, "scores": {}} for i in range(5)]
        with TemporaryDirectory() as directory:
            with init_research_db(Path(directory) / "guru.sqlite") as connection:
                store_market_scores(connection, "2026-07-31", rows, [], source_complete=True)
                for index, row in enumerate(rows):
                    prices = [{"date": "2026-08-03", "adjustedClose": 100 + index}]
                    if index:
                        prices.append({"date": "2026-08-04", "adjustedClose": 101 + index})
                    else:
                        prices = [{"date": "2026-08-04", "adjustedClose": 101}]
                    store_adjusted_prices(connection, row["ticker"], prices)
                completed = apply_cohort_entries(connection)
                cohort = connection.execute("SELECT entry_date,status FROM cohorts").fetchone()
                entry_prices = connection.execute("SELECT entry_price FROM cohort_positions").fetchall()
        self.assertEqual(completed, 1)
        self.assertEqual(tuple(cohort), ("2026-08-04", "tracking"))
        self.assertTrue(all(row[0] is not None for row in entry_prices))

    def test_legacy_model_is_separate_and_deduplicated(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "guru.sqlite"
            with init_research_db(path) as connection:
                store_legacy_observations(connection, [
                    {"asOf": "2026-07-16", "ticker": "AAA", "score": 71, "price": 100},
                    {"asOf": "2026-07-16", "ticker": "AAA", "score": 71, "price": 100},
                    {"asOf": "2026-08-08", "ticker": "AAA", "score": 70, "price": 112},
                ])
                result = legacy_validation(connection)
            self.assertEqual(result["modelVersion"], LEGACY_MODEL)
            self.assertEqual(result["sampleSize"], 1)
            self.assertAlmostEqual(result["rows"][0]["return"], .12)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_legacy_anet_cohr_pilot_regression_does_not_imply_prediction(self):
        with TemporaryDirectory() as directory:
            with init_research_db(Path(directory) / "guru.sqlite") as connection:
                store_legacy_observations(connection, [
                    {"asOf": "2026-07-16", "ticker": "ANET", "name": "Arista Networks", "score": 71, "price": 100},
                    {"asOf": "2026-08-08", "ticker": "ANET", "name": "Arista Networks", "score": 78, "price": 112.01},
                    {"asOf": "2026-07-16", "ticker": "COHR", "name": "Coherent", "score": 41, "price": 100},
                    {"asOf": "2026-08-08", "ticker": "COHR", "name": "Coherent", "score": 42, "price": 134.66},
                ])
                result = legacy_validation(connection)
        by_ticker = {row["ticker"]: row for row in result["rows"]}
        self.assertAlmostEqual(by_ticker["ANET"]["return"], .1201)
        self.assertAlmostEqual(by_ticker["COHR"]["return"], .3466)
        self.assertIn("예측력 확정", result["warning"])


if __name__ == "__main__":
    unittest.main()
