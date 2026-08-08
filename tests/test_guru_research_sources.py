from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from guru_research import init_research_db
from guru_research_sources import fact_series, filing_acceptance_map, latest_fact, refresh_universe


class GuruResearchSourcesTest(unittest.TestCase):
    def test_sec_fact_respects_filing_cutoff(self):
        facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            {"val": 100, "filed": "2026-01-10", "end": "2025-12-31", "form": "10-K"},
            {"val": 999, "filed": "2026-03-10", "end": "2025-12-31", "form": "10-K"},
        ]}}}}}
        selected = latest_fact(facts, ("Revenues",), "2026-02-01")
        self.assertEqual(selected[2], 100)

    def test_sec_fact_uses_acceptance_time_not_only_filing_date(self):
        facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            {"val": 100, "filed": "2026-01-31", "end": "2025-12-31", "form": "10-K", "accn": "early"},
            {"val": 999, "filed": "2026-02-01", "end": "2025-12-31", "form": "10-K", "accn": "late"},
        ]}}}}}
        accepted = {"early": "2026-02-01T20:30:00Z", "late": "2026-02-01T22:30:00Z"}
        selected = latest_fact(
            facts,
            ("Revenues",),
            "2026-02-01T21:00:00Z",
            acceptance_by_accession=accepted,
            strict_acceptance=True,
        )
        self.assertEqual(selected[2], 100)

    def test_sec_acceptance_timestamp_is_normalized(self):
        result = filing_acceptance_map({"filings": {"recent": {
            "accessionNumber": ["abc"],
            "acceptanceDateTime": ["2026-02-01163000.000Z"],
        }}})
        self.assertEqual(result["abc"], "2026-02-01T163000.000Z")

    def test_annual_series_excludes_interim_values_inside_10k(self):
        facts = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            {"val": 40, "start": "2025-01-01", "end": "2025-12-31", "filed": "2026-02-01", "form": "10-K"},
            {"val": 10, "start": "2025-07-01", "end": "2025-09-30", "filed": "2026-02-01", "form": "10-K"},
            {"val": 38, "start": "2024-01-01", "end": "2024-12-31", "filed": "2025-02-01", "form": "10-K"},
        ]}}}}}
        self.assertEqual(fact_series(facts, ("Revenues",), "2026-03-01"), [("2025-12-31", 40.0), ("2024-12-31", 38.0)])

    def test_universe_failure_preserves_previous_month_and_creates_no_new_list(self):
        with TemporaryDirectory() as directory:
            with init_research_db(Path(directory) / "research.sqlite") as connection:
                connection.execute("INSERT INTO universe_members(as_of,ticker,name,sources) VALUES('2026-06-30','AAA','A','[]')")
                connection.commit()
                result = refresh_universe(connection, "2026-07-31", [], [])
                months = connection.execute("SELECT DISTINCT as_of FROM universe_members ORDER BY as_of").fetchall()
        self.assertFalse(result["created"])
        self.assertTrue(result["stale"])
        self.assertEqual([row[0] for row in months], ["2026-06-30"])

    def test_complete_lists_merge_overlap(self):
        sp = [{"ticker": f"S{i:03}", "name": "S"} for i in range(490)]
        ndx = [{"ticker": f"N{i:03}", "name": "N"} for i in range(95)] + [{"ticker": "S001", "name": "S"}]
        with TemporaryDirectory() as directory:
            with init_research_db(Path(directory) / "research.sqlite") as connection:
                result = refresh_universe(connection, "2026-07-31", sp, ndx)
        self.assertTrue(result["created"])
        self.assertEqual(result["count"], 585)

    def test_nasdaq_only_mode_does_not_require_sp500(self):
        ndx = [{"ticker": f"N{i:03}", "name": "Nasdaq"} for i in range(95)]
        with TemporaryDirectory() as directory:
            with init_research_db(Path(directory) / "research.sqlite") as connection:
                result = refresh_universe(connection, "2026-08-07", [], ndx, mode="nasdaq100")
                sources = connection.execute("SELECT DISTINCT sources FROM universe_members").fetchall()
        self.assertTrue(result["created"])
        self.assertEqual(result["name"], "Nasdaq-100")
        self.assertEqual([row[0] for row in sources], ['["Nasdaq-100"]'])


if __name__ == "__main__":
    unittest.main()
