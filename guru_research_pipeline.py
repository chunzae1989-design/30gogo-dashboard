#!/usr/bin/env python3
"""Monthly, point-in-time Guru candidate pipeline.

The pipeline is read-only. It may read public market/fundamental endpoints and
write the private research SQLite ledger, but it has no order operations.
"""
from __future__ import annotations

import json
import math
import time
from datetime import date, datetime, time as clock_time
from pathlib import Path
from statistics import mean
from typing import Callable, Iterable
from zoneinfo import ZoneInfo

from guru_research import (
    apply_cohort_entries,
    dedupe_universe,
    score_market_company,
    set_research_meta,
    store_adjusted_prices,
    store_market_scores,
)
from guru_research_sources import (
    NASDAQ100_URL,
    SEC_COMPANYFACTS,
    SEC_SUBMISSIONS,
    SEC_TICKERS_URL,
    SP500_URL,
    fact_series,
    fetch_text,
    filing_acceptance_map,
    latest_fact,
    parse_constituent_table,
    refresh_universe,
)

NEW_YORK = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")
MIN_MARKET_COVERAGE = 0.90
MIN_SEC_COVERAGE = 0.80
INDEX_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140 Safari/537.36"

FACTS = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "netIncome": ("NetIncomeLoss", "ProfitLoss"),
    "operatingIncome": ("OperatingIncomeLoss",),
    "grossProfit": ("GrossProfit",),
    "operatingCashFlow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "equity": ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
    "liabilities": ("Liabilities",),
    "currentAssets": ("AssetsCurrent",),
    "currentLiabilities": ("LiabilitiesCurrent",),
}


def chunks(values: list[str], size: int = 200) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def result_rows(payload: dict) -> list[dict]:
    value = payload.get("result", payload) if isinstance(payload, dict) else payload
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("items", "stocks", "prices"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def market_close_cutoff(as_of: str) -> str:
    close = datetime.combine(date.fromisoformat(as_of), clock_time(16, 0), tzinfo=NEW_YORK)
    return close.astimezone(UTC).isoformat().replace("+00:00", "Z")


def sec_ticker_map(payload: dict) -> dict[str, dict]:
    rows = payload.values() if isinstance(payload, dict) else []
    output = {}
    for row in rows:
        ticker = str(row.get("ticker") or "").upper().replace("-", ".")
        cik = str(row.get("cik_str") or "").zfill(10)
        if ticker and cik.strip("0"):
            output[ticker] = {"cik": cik, "name": str(row.get("title") or ticker)}
    return output


def _number(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _fact_value(companyfacts: dict, acceptance: dict, cutoff: str, key: str, *, annual: bool = True):
    found = latest_fact(
        companyfacts,
        FACTS[key],
        cutoff,
        annual=annual,
        acceptance_by_accession=acceptance,
        strict_acceptance=True,
    )
    return None if found is None else float(found[2])


def _growth(series: list[tuple[str, float]]):
    if len(series) < 2:
        return None
    current, previous = float(series[0][1]), float(series[1][1])
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def financial_metrics(companyfacts: dict, submissions: dict, cutoff: str, price: float, shares: float) -> dict:
    acceptance = filing_acceptance_map(submissions)
    values = {
        key: _fact_value(companyfacts, acceptance, cutoff, key, annual=key not in {"equity", "liabilities", "currentAssets", "currentLiabilities"})
        for key in FACTS
    }
    market_cap = price * shares if price > 0 and shares > 0 else None
    revenue = values["revenue"]
    net_income = values["netIncome"]
    equity = values["equity"]
    operating_cash_flow = values["operatingCashFlow"]
    capex = values["capex"]

    revenue_series = fact_series(
        companyfacts,
        FACTS["revenue"],
        cutoff,
        acceptance_by_accession=acceptance,
        strict_acceptance=True,
    )
    income_series = fact_series(
        companyfacts,
        FACTS["netIncome"],
        cutoff,
        acceptance_by_accession=acceptance,
        strict_acceptance=True,
    )

    def ratio(numerator, denominator, multiplier=1):
        if numerator is None or denominator in (None, 0):
            return None
        return numerator / denominator * multiplier

    accepted = sorted(value for value in acceptance.values() if value <= cutoff)
    return {
        "pe": ratio(market_cap, net_income),
        "pb": ratio(market_cap, equity),
        "roe": ratio(net_income, equity, 100),
        "operatingMargin": ratio(values["operatingIncome"], revenue, 100),
        "grossMargin": ratio(values["grossProfit"], revenue, 100),
        "fcfYield": ratio(None if operating_cash_flow is None or capex is None else operating_cash_flow - abs(capex), market_cap, 100),
        "debtEquity": ratio(values["liabilities"], equity),
        "currentRatio": ratio(values["currentAssets"], values["currentLiabilities"]),
        "revenueGrowth": _growth(revenue_series),
        "netIncomeGrowth": _growth(income_series),
        "filingAcceptedAt": accepted[-1] if accepted else None,
    }


def normalize_candles(payload: dict) -> list[dict]:
    result = payload.get("result", payload) if isinstance(payload, dict) else {}
    rows = result.get("candles") if isinstance(result, dict) else []
    output = []
    for row in rows or []:
        timestamp = str(row.get("timestamp") or "")
        close = _number(row.get("closePrice"))
        volume = _number(row.get("volume"))
        if timestamp and close and close > 0:
            output.append({"date": timestamp[:10], "timestamp": timestamp, "adjustedClose": close, "volume": volume or 0})
    return output


def candle_metrics(candles: list[dict]) -> dict:
    ordered = sorted({row["date"]: row for row in candles}.values(), key=lambda row: row["date"])
    if len(ordered) < 2:
        return {}
    closes = [float(row["adjustedClose"]) for row in ordered]
    low, high, price = min(closes), max(closes), closes[-1]
    dollar_volumes = [float(row["adjustedClose"]) * float(row.get("volume") or 0) for row in ordered[-21:]]
    return {
        "price": price,
        "low52": low,
        "high52": high,
        "position52w": None if high <= low else (price - low) / (high - low),
        "dailyChange": (price / closes[-2] - 1) * 100,
        "dollarVolume": mean(dollar_volumes) if dollar_volumes else 0,
    }


class GuruMarketPipeline:
    def __init__(
        self,
        connection,
        toss_client,
        *,
        public_user_agent: str = "30gogo-research/1.0 contact: research@30gogo.local",
        fetcher: Callable[[str, str], str] = fetch_text,
        sleep: Callable[[float], None] = time.sleep,
        universe_mode: str = "nasdaq100",
    ):
        self.connection = connection
        self.toss = toss_client
        self.user_agent = public_user_agent
        self.fetcher = fetcher
        self.sleep = sleep
        self.universe_mode = universe_mode

    def _json(self, url: str) -> dict:
        return json.loads(self.fetcher(url, self.user_agent))

    def _candles(self, ticker: str, as_of: str, wanted: int = 260) -> list[dict]:
        before = datetime.combine(date.fromisoformat(as_of), clock_time(23, 59, 59), tzinfo=NEW_YORK).isoformat()
        rows = []
        while len(rows) < wanted:
            page = self.toss.get("/api/v1/candles", {
                "symbol": ticker,
                "interval": "1d",
                "count": min(200, wanted - len(rows)),
                "before": before,
                "adjusted": "true",
            })
            result = page.get("result", page) if isinstance(page, dict) else {}
            values = normalize_candles(page)
            if not values:
                break
            rows.extend(values)
            next_before = result.get("nextBefore") if isinstance(result, dict) else None
            if not next_before or next_before == before:
                break
            before = next_before
            self.sleep(0.22)
        return list({row["date"]: row for row in rows}.values())

    def _master(self, tickers: list[str]) -> dict[str, dict]:
        output = {}
        for batch in chunks(tickers):
            for row in result_rows(self.toss.get("/api/v1/stocks", {"symbols": ",".join(batch)})):
                ticker = str(row.get("symbol") or "").upper().replace("-", ".")
                if ticker:
                    output[ticker] = row
            self.sleep(0.22)
        return output

    def _load_official_universe(self) -> tuple[list[dict], list[dict], dict]:
        errors = {}
        sp_rows = []
        if self.universe_mode != "nasdaq100":
            try:
                sp_rows = parse_constituent_table(self.fetcher(SP500_URL, INDEX_USER_AGENT))
            except Exception as error:
                errors["sp500"] = str(error)
        try:
            ndx_rows = parse_constituent_table(self.fetcher(NASDAQ100_URL, INDEX_USER_AGENT))
        except Exception as error:
            ndx_rows, errors["nasdaq100"] = [], str(error)
        return sp_rows, ndx_rows, errors

    def run(self, score_as_of: str, held_tickers: Iterable[str], *, cohort_kind: str = "monthly") -> dict:
        cutoff = market_close_cutoff(score_as_of)
        sp_rows, ndx_rows, source_errors = self._load_official_universe()
        universe_complete = len(ndx_rows) >= 95 if self.universe_mode == "nasdaq100" else len(sp_rows) >= 490 and len(ndx_rows) >= 95
        if not universe_complete:
            status = refresh_universe(self.connection, score_as_of, sp_rows, ndx_rows, mode=self.universe_mode)
            message = status["reason"]
            if source_errors:
                message += " " + "; ".join(f"{key}: {value}" for key, value in source_errors.items())
            pipeline_status = {"ok": False, "stale": True, "scoreAsOf": score_as_of, "message": message}
            set_research_meta(self.connection, "pipelineStatus", pipeline_status)
            return pipeline_status

        ticker_reference = sec_ticker_map(self._json(SEC_TICKERS_URL))
        source_rows = ndx_rows if self.universe_mode == "nasdaq100" else [*sp_rows, *ndx_rows]
        for row in source_rows:
            reference = ticker_reference.get(row["ticker"])
            if reference:
                row.update(reference)
        merged = dedupe_universe(source_rows)
        tickers = [row["ticker"] for row in merged]
        master = self._master(tickers)
        candles_by_ticker = {}
        for ticker in tickers:
            try:
                candles = self._candles(ticker, score_as_of)
                if candles:
                    candles_by_ticker[ticker] = candles
                    store_adjusted_prices(self.connection, ticker, candles)
            except Exception:
                continue
            self.sleep(0.22)

        for row in source_rows:
            row.update(candle_metrics(candles_by_ticker.get(row["ticker"], [])))
        universe_status = refresh_universe(self.connection, score_as_of, sp_rows, ndx_rows, mode=self.universe_mode)
        market_coverage = len(candles_by_ticker) / max(1, len(tickers))
        master_coverage = len(master) / max(1, len(tickers))
        if not universe_status.get("ok") or min(market_coverage, master_coverage) < MIN_MARKET_COVERAGE:
            pipeline_status = {
                "ok": False,
                "stale": True,
                "scoreAsOf": score_as_of,
                "message": f"Toss 시세/종목정보 커버리지 부족으로 새 코호트를 만들지 않았습니다. candles={market_coverage:.1%}, stocks={master_coverage:.1%}",
            }
            set_research_meta(self.connection, "pipelineStatus", pipeline_status)
            return pipeline_status

        universe = [dict(row) for row in self.connection.execute(
            "SELECT ticker,name,cik,sources,dollar_volume FROM universe_members WHERE as_of=? ORDER BY ticker",
            (score_as_of,),
        ).fetchall()]
        scored, sec_ok = [], 0
        for row in universe:
            ticker, cik = row["ticker"], str(row.get("cik") or "").zfill(10)
            info, trend = master.get(ticker) or {}, candle_metrics(candles_by_ticker.get(ticker, []))
            shares, price = _number(info.get("sharesOutstanding")), _number(trend.get("price"))
            if not cik.strip("0") or not shares or not price:
                continue
            try:
                companyfacts = self._json(SEC_COMPANYFACTS.format(cik=cik))
                submissions = self._json(SEC_SUBMISSIONS.format(cik=cik))
                fundamental = financial_metrics(companyfacts, submissions, cutoff, price, shares)
                sec_ok += 1
            except Exception:
                continue
            metrics = {**trend, **{key: value for key, value in fundamental.items() if key != "filingAcceptedAt"}}
            result = score_market_company(metrics)
            pe = _number(metrics.get("pe"))
            result.update({
                "ticker": ticker,
                "name": str(info.get("englishName") or info.get("name") or row["name"] or ticker),
                "sources": ["Toss OpenAPI", "SEC EDGAR"],
                "filingAcceptedAt": fundamental.get("filingAcceptedAt"),
                "valuationRisk": "고평가 주의" if pe is not None and pe > 45 else "점수와 별도 검토",
                "summary": "기업점수는 보유비중 행동판단과 분리된 연구 신호입니다.",
            })
            scored.append(result)
            self.sleep(0.12)

        sec_coverage = sec_ok / max(1, len(universe))
        source_complete = sec_coverage >= MIN_SEC_COVERAGE
        cohort = store_market_scores(
            self.connection,
            score_as_of,
            scored,
            held_tickers,
            source_complete=source_complete,
            cohort_kind=cohort_kind,
        )
        if cohort.get("created"):
            message = "Nasdaq-100 최초 기준선과 미보유 Top 5를 고정했습니다." if cohort_kind == "bootstrap" else "Nasdaq-100 월말 점수 원장과 미보유 Top 5를 고정했습니다."
        else:
            message = str(cohort.get("reason") or "새 코호트를 만들지 않았습니다.")
        pipeline_status = {
            "ok": bool(cohort.get("created")),
            "stale": not bool(cohort.get("created")),
            "scoreAsOf": score_as_of,
            "message": message,
            "universeCount": len(universe),
            "scoreCount": len(scored),
            "eligibleCount": sum(1 for row in scored if row.get("eligible")),
            "marketCoverage": round(market_coverage, 4),
            "secCoverage": round(sec_coverage, 4),
        }
        set_research_meta(self.connection, "pipelineStatus", pipeline_status)
        apply_cohort_entries(self.connection)
        return pipeline_status
