"""Authoritative source adapters used by the prospective Guru ledger."""
from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

from guru_research import dedupe_universe, set_research_meta

SP500_URL = "https://www.spglobal.com/spdji/en/indices/equity/sp-500/"
NASDAQ100_URL = "https://www.nasdaq.com/solutions/global-indexes/nasdaq-100/companies"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_cell = False
        self.cells = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self.in_cell = True
            self.cells.append("")

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self.in_cell = False
        if tag == "tr" and self.cells:
            self.rows.append([re.sub(r"\s+", " ", value).strip() for value in self.cells])
            self.cells = []

    def handle_data(self, data):
        if self.in_cell and self.cells:
            self.cells[-1] += data


def parse_constituent_table(html: str) -> list[dict]:
    parser = TableParser()
    parser.feed(html)
    output = []
    for cells in parser.rows:
        ticker_index = next((index for index, value in enumerate(cells) if re.fullmatch(r"[A-Z]{1,5}(?:[.-][A-Z])?", value)), None)
        if ticker_index is None:
            continue
        ticker = cells[ticker_index].replace("-", ".")
        name = next((value for index, value in enumerate(cells) if index != ticker_index and len(value) > 2), ticker)
        output.append({"ticker": ticker, "name": name})
    return dedupe_universe(output)


def fetch_text(url: str, user_agent: str, timeout: int = 45, attempts: int = 3) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt + 1 >= attempts:
                raise
        except (ConnectionError, TimeoutError, urllib.error.URLError):
            if attempt + 1 >= attempts:
                raise
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"공개 자료를 가져오지 못했습니다: {url}")


def normalize_sec_timestamp(value: str) -> str:
    value = str(value or "")
    if len(value) > 10 and value[10].isdigit():
        return f"{value[:10]}T{value[10:]}"
    return value


def annual_duration_ok(row: dict) -> bool:
    start = str(row.get("start") or "")
    end = str(row.get("end") or "")
    if not start or not end:
        return True
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days >= 300
    except ValueError:
        return False


def filing_acceptance_map(submissions: dict) -> dict[str, str]:
    recent = (submissions.get("filings") or {}).get("recent") or {}
    accessions = recent.get("accessionNumber") or []
    accepted = recent.get("acceptanceDateTime") or []
    return {
        str(accession): normalize_sec_timestamp(str(accepted[index]))
        for index, accession in enumerate(accessions)
        if index < len(accepted) and accession and accepted[index]
    }


def latest_fact(
    companyfacts: dict,
    tags: tuple[str, ...],
    cutoff: str,
    *,
    annual: bool = True,
    acceptance_by_accession: dict[str, str] | None = None,
    strict_acceptance: bool = False,
):
    candidates = []
    for tag in tags:
        fact = (companyfacts.get("facts", {}).get("us-gaap", {}).get(tag) or {})
        for units in (fact.get("units") or {}).values():
            for row in units:
                filed = str(row.get("filed") or "")
                form = str(row.get("form") or "")
                if not filed or filed > cutoff or form not in ({"10-K", "20-F", "40-F"} if annual else {"10-K", "10-Q", "20-F", "40-F"}):
                    continue
                if annual and not annual_duration_ok(row):
                    continue
                if acceptance_by_accession is not None:
                    accepted = acceptance_by_accession.get(str(row.get("accn") or ""))
                    if strict_acceptance and not accepted:
                        continue
                    if accepted and accepted > cutoff:
                        continue
                value = row.get("val")
                if isinstance(value, (int, float)):
                    candidates.append((acceptance_by_accession.get(str(row.get("accn") or ""), filed) if acceptance_by_accession else filed, str(row.get("end") or ""), value, tag, row))
    return max(candidates, default=None, key=lambda item: (item[0], item[1]))


def fact_series(
    companyfacts: dict,
    tags: tuple[str, ...],
    cutoff: str,
    *,
    acceptance_by_accession: dict[str, str] | None = None,
    strict_acceptance: bool = False,
) -> list[tuple[str, float]]:
    by_end = {}
    for tag in tags:
        fact = (companyfacts.get("facts", {}).get("us-gaap", {}).get(tag) or {})
        for units in (fact.get("units") or {}).values():
            for row in units:
                accepted = (acceptance_by_accession or {}).get(str(row.get("accn") or ""))
                accepted_in_time = accepted <= cutoff if accepted else not strict_acceptance
                if str(row.get("filed") or "") <= cutoff and accepted_in_time and str(row.get("form") or "") in {"10-K", "20-F", "40-F"} and annual_duration_ok(row) and isinstance(row.get("val"), (int, float)):
                    end = str(row.get("end") or "")
                    current = by_end.get(end)
                    timestamp = accepted or str(row.get("filed"))
                    if end and (current is None or timestamp > current[0]):
                        by_end[end] = (timestamp, float(row["val"]))
    return sorted(((end, value[1]) for end, value in by_end.items()), reverse=True)


def refresh_universe(
    connection: sqlite3.Connection,
    as_of: str,
    sp_rows: list[dict] | None,
    ndx_rows: list[dict] | None,
    *,
    mode: str = "union",
) -> dict:
    """Persist only complete official lists; preserve the prior list on failure."""
    nasdaq_only = mode == "nasdaq100"
    complete = bool(ndx_rows and len(ndx_rows) >= 95) if nasdaq_only else bool(sp_rows and len(sp_rows) >= 490 and ndx_rows and len(ndx_rows) >= 95)
    if not complete:
        previous = connection.execute("SELECT MAX(as_of) FROM universe_members").fetchone()[0]
        result = {
            "ok": False,
            "created": False,
            "stale": True,
            "asOf": previous,
            "name": "Nasdaq-100" if nasdaq_only else "S&P 500 + Nasdaq-100",
            "reason": "공식 구성종목 커버리지 부족으로 새 코호트를 만들지 않았습니다.",
            "spCount": len(sp_rows or []),
            "nasdaqCount": len(ndx_rows or []),
        }
        set_research_meta(connection, "universeStatus", result)
        return result
    merged = {}
    source_rows = (("Nasdaq-100", ndx_rows),) if nasdaq_only else (("S&P 500", sp_rows), ("Nasdaq-100", ndx_rows))
    for source, rows in source_rows:
        for row in rows:
            ticker = str(row.get("ticker") or "").upper()
            if not ticker:
                continue
            current = merged.setdefault(ticker, {**row, "ticker": ticker, "sources": []})
            current["sources"].append(source)
    rows = dedupe_universe(merged.values())
    connection.execute("DELETE FROM universe_members WHERE as_of=?", (as_of,))
    connection.executemany("""
      INSERT INTO universe_members(as_of,ticker,name,cik,sources,dollar_volume)
      VALUES(?,?,?,?,?,?) ON CONFLICT(as_of,ticker) DO UPDATE SET
      name=excluded.name,cik=excluded.cik,sources=excluded.sources,dollar_volume=excluded.dollar_volume
    """, [(as_of, row["ticker"], row.get("name") or row["ticker"], row.get("cik"), json.dumps(row.get("sources") or []), row.get("dollarVolume")) for row in rows])
    connection.commit()
    result = {
        "ok": True,
        "created": True,
        "stale": False,
        "asOf": as_of,
        "name": "Nasdaq-100" if nasdaq_only else "S&P 500 + Nasdaq-100",
        "count": len(rows),
        "spCount": len(sp_rows or []),
        "nasdaqCount": len(ndx_rows or []),
        "sources": ([{"label": "Nasdaq-100", "url": NASDAQ100_URL}] if nasdaq_only else [
            {"label": "S&P 500", "url": SP500_URL},
            {"label": "Nasdaq-100", "url": NASDAQ100_URL},
        ]),
    }
    set_research_meta(connection, "universeStatus", result)
    return result
