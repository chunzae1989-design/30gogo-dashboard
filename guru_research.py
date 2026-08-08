#!/usr/bin/env python3
"""Point-in-time research ledger for the Guru validation lab.

The module is deliberately independent from holdings and order code. It stores
research observations locally and returns only aggregate data for the encrypted
dashboard payload.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Iterable

LEGACY_MODEL = "legacy-holdings-v1"
MARKET_MODEL = "guru-market-nasdaq-v2"
LENSES = ("Buffett", "Lynch", "Graham", "Greenblatt", "Innovation", "Momentum")
HORIZONS = {"1M": 21, "3M": 63, "6M": 126, "12M": 252}
REQUIRED_GROUPS = {
    "value": ("pe", "pb"),
    "profitability": ("roe", "operatingMargin"),
    "growth": ("revenueGrowth", "netIncomeGrowth"),
    "trend": ("position52w",),
}


def finite(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, value))


def high_score(value, low: float, high: float):
    value = finite(value)
    if value is None:
        return None
    if high == low:
        return 50.0
    return clamp((value - low) / (high - low) * 100)


def low_score(value, low: float, high: float):
    score = high_score(value, low, high)
    return None if score is None else 100 - score


def avg_present(values: Iterable[float | None]):
    values = [float(value) for value in values if value is not None]
    return None if not values else mean(values)


def _position_52w(metrics: dict) -> float | None:
    direct = finite(metrics.get("position52w"))
    if direct is not None:
        return direct
    price = finite(metrics.get("price"))
    low = finite(metrics.get("low52"))
    high = finite(metrics.get("high52"))
    if price is None or low is None or high is None or high <= low:
        return None
    return clamp((price - low) / (high - low), 0, 1)


def score_market_company(metrics: dict) -> dict:
    """Score one company without holdings-based penalties or missing-data defaults."""
    data = dict(metrics or {})
    data["position52w"] = _position_52w(data)
    present = {key for key, value in data.items() if finite(value) is not None}
    missing_groups = [group for group, keys in REQUIRED_GROUPS.items() if not any(key in present for key in keys)]

    growth = avg_present((finite(data.get("revenueGrowth")), finite(data.get("netIncomeGrowth"))))
    pe = finite(data.get("pe"))
    peg = None if pe is None or growth is None or growth <= 0 else pe / growth
    earnings_yield = None if pe is None or pe <= 0 else 100 / pe
    position = finite(data.get("position52w"))
    daily_change = finite(data.get("dailyChange"))

    lens_inputs = {
        "Buffett": [
            high_score(data.get("roe"), 5, 30),
            high_score(data.get("operatingMargin"), 5, 35),
            high_score(data.get("fcfYield"), 0, 8),
            low_score(data.get("debtEquity"), 0, 2),
            low_score(pe, 10, 45),
        ],
        "Lynch": [
            high_score(growth, 0, 35),
            low_score(peg, 0.5, 3),
            high_score(position, 0.15, 0.85),
        ],
        "Graham": [
            low_score(pe, 8, 35),
            low_score(data.get("pb"), 1, 10),
            high_score(data.get("currentRatio"), 0.8, 2.5),
            low_score(data.get("debtEquity"), 0, 1.5),
        ],
        "Greenblatt": [
            high_score(earnings_yield, 1, 8),
            high_score(data.get("roe"), 5, 30),
            high_score(data.get("operatingMargin"), 5, 35),
        ],
        # Theme priors are intentionally neutral. Actual financial/trend inputs
        # still have to exist before this lens counts toward coverage.
        "Innovation": [
            50.0,
            high_score(data.get("revenueGrowth"), 0, 40),
            high_score(data.get("grossMargin"), 15, 70),
            high_score(position, 0.15, 0.85),
        ],
        "Momentum": [
            high_score(position, 0.1, 0.9),
            high_score(daily_change, -5, 5),
        ],
    }
    scores = {}
    calculable = []
    for lens, values in lens_inputs.items():
        actual = values[1:] if lens == "Innovation" else values
        if any(value is not None for value in actual):
            scores[lens] = round(avg_present(values), 1)
            calculable.append(lens)
        else:
            scores[lens] = None

    exclusion = []
    if missing_groups:
        exclusion.append("핵심 자료 부족: " + ", ".join(missing_groups))
    if len(calculable) < 5:
        exclusion.append(f"계산 가능한 렌즈 {len(calculable)}/6")
    eligible = not exclusion
    company_score = round(avg_present(scores.values()), 1) if eligible else None
    return {
        "modelVersion": MARKET_MODEL,
        "eligible": eligible,
        "companyScore": company_score,
        "scores": scores,
        "lensCoverage": len(calculable),
        "dataCompleteness": round(len(present & set().union(*REQUIRED_GROUPS.values())) / 7 * 100, 1),
        "exclusionReasons": exclusion,
        "metrics": data,
    }


def dedupe_universe(rows: Iterable[dict]) -> list[dict]:
    """Deduplicate tickers and keep the most liquid share class for one CIK."""
    by_ticker = {}
    for raw in rows:
        row = dict(raw)
        ticker = str(row.get("ticker") or "").strip().upper().replace("/", ".")
        if not ticker:
            continue
        row["ticker"] = ticker
        current = by_ticker.get(ticker)
        if current is None or (finite(row.get("dollarVolume")) or 0) > (finite(current.get("dollarVolume")) or 0):
            by_ticker[ticker] = row
    by_cik = {}
    no_cik = []
    for row in by_ticker.values():
        cik = str(row.get("cik") or "").lstrip("0")
        if not cik:
            no_cik.append(row)
            continue
        current = by_cik.get(cik)
        if current is None or (finite(row.get("dollarVolume")) or 0) > (finite(current.get("dollarVolume")) or 0):
            by_cik[cik] = row
    return sorted([*by_cik.values(), *no_cik], key=lambda row: row["ticker"])


def select_top_five(scored: Iterable[dict], held_tickers: Iterable[str]) -> list[dict]:
    held = {str(ticker).upper() for ticker in held_tickers}
    eligible = [dict(row) for row in scored if row.get("eligible") and str(row.get("ticker", "")).upper() not in held]
    eligible.sort(key=lambda row: (-float(row.get("companyScore") or 0), str(row.get("ticker") or "")))
    return [{**row, "paperWeight": 0.2, "researchOnly": True} for row in eligible[:5]]


def rank(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=values.__getitem__)
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        shared = (start + end - 1) / 2 + 1
        for index in order[start:end]:
            result[index] = shared
        start = end
    return result


def spearman(pairs: Iterable[tuple[float, float]]) -> float | None:
    pairs = [(float(left), float(right)) for left, right in pairs if finite(left) is not None and finite(right) is not None]
    if len(pairs) < 3:
        return None
    left, right = rank([pair[0] for pair in pairs]), rank([pair[1] for pair in pairs])
    left_mean, right_mean = mean(left), mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    denominator = math.sqrt(sum((x - left_mean) ** 2 for x in left) * sum((y - right_mean) ** 2 for y in right))
    return None if denominator == 0 else numerator / denominator


def forward_return(prices: list[float], entry_index: int, trading_days: int) -> float | None:
    target = entry_index + trading_days
    if entry_index < 0 or target >= len(prices):
        return None
    entry, exit_price = finite(prices[entry_index]), finite(prices[target])
    if entry is None or exit_price is None or entry <= 0:
        return None
    return exit_price / entry - 1


def metrics_for_horizon(rows: Iterable[dict], horizon: str) -> dict:
    matured = [row for row in rows if finite(row.get("companyScore")) is not None and finite(row.get("return")) is not None]
    pairs = [(row["companyScore"], row["return"]) for row in matured]
    sorted_rows = sorted(matured, key=lambda row: row["companyScore"])
    bucket = max(1, math.ceil(len(sorted_rows) * 0.2)) if sorted_rows else 0
    spread = None if not sorted_rows else mean(row["return"] for row in sorted_rows[-bucket:]) - mean(row["return"] for row in sorted_rows[:bucket])
    top5 = [row for row in matured if row.get("top5")]
    hit_rate = None if not top5 else sum(1 for row in top5 if row["return"] > 0) / len(top5)
    score_buckets = []
    for low, high in ((0, 39), (40, 59), (60, 79), (80, 100)):
        values = [row["return"] for row in matured if low <= row["companyScore"] <= high]
        score_buckets.append({
            "label": f"{low}-{high}",
            "sampleSize": len(values),
            "averageReturn": mean(values) if values else None,
        })
    return {
        "horizon": horizon,
        "tradingDays": HORIZONS[horizon],
        "status": "ready" if matured else "pending",
        "sampleSize": len(matured),
        "spearman": spearman(pairs),
        "topBottomSpread": spread,
        "top5HitRate": hit_rate,
        "scoreBuckets": score_buckets,
    }


def init_research_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS universe_members (
          as_of TEXT NOT NULL, ticker TEXT NOT NULL, name TEXT NOT NULL DEFAULT '', cik TEXT,
          sources TEXT NOT NULL, dollar_volume REAL, PRIMARY KEY(as_of,ticker)
        );
        CREATE TABLE IF NOT EXISTS scores (
          model_version TEXT NOT NULL, score_as_of TEXT NOT NULL, ticker TEXT NOT NULL,
          company_score REAL, eligible INTEGER NOT NULL, payload_json TEXT NOT NULL,
          PRIMARY KEY(model_version,score_as_of,ticker)
        );
        CREATE TABLE IF NOT EXISTS cohorts (
          model_version TEXT NOT NULL, score_as_of TEXT NOT NULL, entry_date TEXT,
          status TEXT NOT NULL, created_at TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'monthly',
          PRIMARY KEY(model_version,score_as_of)
        );
        CREATE TABLE IF NOT EXISTS cohort_positions (
          model_version TEXT NOT NULL, score_as_of TEXT NOT NULL, ticker TEXT NOT NULL,
          score REAL NOT NULL, entry_price REAL, weight REAL NOT NULL, held_at_signal INTEGER NOT NULL,
          PRIMARY KEY(model_version,score_as_of,ticker)
        );
        CREATE TABLE IF NOT EXISTS price_observations (
          ticker TEXT NOT NULL, price_date TEXT NOT NULL, adjusted_close REAL NOT NULL,
          source TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY(ticker,price_date)
        );
        CREATE TABLE IF NOT EXISTS legacy_observations (
          model_version TEXT NOT NULL, as_of TEXT NOT NULL, ticker TEXT NOT NULL,
          name TEXT NOT NULL DEFAULT '', score REAL NOT NULL, price REAL,
          PRIMARY KEY(model_version,as_of,ticker)
        );
        CREATE TABLE IF NOT EXISTS research_meta (
          key TEXT PRIMARY KEY, payload_json TEXT NOT NULL, updated_at TEXT NOT NULL
        );
    """)
    cohort_columns = {row[1] for row in connection.execute("PRAGMA table_info(cohorts)").fetchall()}
    if "kind" not in cohort_columns:
        connection.execute("ALTER TABLE cohorts ADD COLUMN kind TEXT NOT NULL DEFAULT 'monthly'")
    connection.commit()
    os.chmod(path, 0o600)
    return connection


def set_research_meta(connection: sqlite3.Connection, key: str, payload: dict) -> None:
    connection.execute("""
      INSERT INTO research_meta(key,payload_json,updated_at) VALUES(?,?,?)
      ON CONFLICT(key) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at
    """, (key, json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
    connection.commit()


def get_research_meta(connection: sqlite3.Connection, key: str) -> dict:
    row = connection.execute("SELECT payload_json FROM research_meta WHERE key=?", (key,)).fetchone()
    if not row:
        return {}
    try:
        return json.loads(row[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def store_legacy_observations(connection: sqlite3.Connection, observations: Iterable[dict]) -> int:
    connection.execute("DELETE FROM legacy_observations WHERE model_version=?", (LEGACY_MODEL,))
    rows = []
    for row in observations:
        if finite(row.get("score")) is None:
            continue
        rows.append((LEGACY_MODEL, str(row.get("asOf") or ""), str(row.get("ticker") or "").upper(), str(row.get("name") or ""), float(row["score"]), finite(row.get("price"))))
    connection.executemany("""
        INSERT INTO legacy_observations(model_version,as_of,ticker,name,score,price)
        VALUES(?,?,?,?,?,?) ON CONFLICT(model_version,as_of,ticker) DO UPDATE SET
        name=excluded.name,score=excluded.score,price=COALESCE(excluded.price,legacy_observations.price)
    """, rows)
    connection.commit()
    return len(rows)


def store_market_scores(
    connection: sqlite3.Connection,
    score_as_of: str,
    scored: Iterable[dict],
    held_tickers: Iterable[str],
    *,
    source_complete: bool,
    cohort_kind: str = "monthly",
) -> dict:
    """Freeze a monthly score set and its Top 5 membership atomically."""
    if not source_complete:
        return {"created": False, "reason": "source coverage failed"}
    if connection.execute("SELECT 1 FROM cohorts WHERE model_version=? AND score_as_of=?", (MARKET_MODEL, score_as_of)).fetchone():
        return {"created": False, "reason": "cohort already frozen"}
    rows = [dict(row) for row in scored]
    selected = select_top_five(rows, held_tickers)
    if len(selected) != 5:
        return {"created": False, "reason": "fewer than five eligible unheld companies"}
    rank_by_ticker = {row["ticker"]: index + 1 for index, row in enumerate(selected)}
    connection.execute("BEGIN")
    try:
        for row in rows:
            row["candidateRank"] = rank_by_ticker.get(str(row.get("ticker") or "").upper())
            connection.execute("""
              INSERT INTO scores(model_version,score_as_of,ticker,company_score,eligible,payload_json)
              VALUES(?,?,?,?,?,?) ON CONFLICT(model_version,score_as_of,ticker) DO UPDATE SET
              company_score=excluded.company_score,eligible=excluded.eligible,payload_json=excluded.payload_json
            """, (MARKET_MODEL, score_as_of, str(row.get("ticker") or "").upper(), row.get("companyScore"), 1 if row.get("eligible") else 0, json.dumps(row, ensure_ascii=False)))
        connection.execute("""
          INSERT INTO cohorts(model_version,score_as_of,entry_date,status,created_at,kind)
          VALUES(?,?,NULL,'waiting_entry',?,?) ON CONFLICT(model_version,score_as_of) DO NOTHING
        """, (MARKET_MODEL, score_as_of, datetime.now(timezone.utc).isoformat(), cohort_kind))
        for row in selected:
            connection.execute("""
              INSERT INTO cohort_positions(model_version,score_as_of,ticker,score,entry_price,weight,held_at_signal)
              VALUES(?,?,?,?,NULL,0.2,0) ON CONFLICT(model_version,score_as_of,ticker) DO NOTHING
            """, (MARKET_MODEL, score_as_of, row["ticker"], row["companyScore"]))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {"created": True, "scoreCount": len(rows), "candidateCount": 5}


def store_adjusted_prices(connection: sqlite3.Connection, ticker: str, rows: Iterable[dict], source: str = "Toss OpenAPI adjusted daily") -> int:
    values = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        price_date = str(row.get("date") or row.get("timestamp") or "")[:10]
        close = finite(row.get("adjustedClose") if row.get("adjustedClose") is not None else row.get("closePrice"))
        if price_date and close is not None and close > 0:
            values.append((str(ticker).upper(), price_date, close, source, fetched_at))
    connection.executemany("""
      INSERT INTO price_observations(ticker,price_date,adjusted_close,source,fetched_at)
      VALUES(?,?,?,?,?) ON CONFLICT(ticker,price_date) DO UPDATE SET
      adjusted_close=excluded.adjusted_close,source=excluded.source,fetched_at=excluded.fetched_at
    """, values)
    connection.commit()
    return len(values)


def apply_cohort_entries(connection: sqlite3.Connection) -> int:
    """Freeze the first common trading-day close after each monthly signal."""
    cohorts = connection.execute(
        "SELECT score_as_of FROM cohorts WHERE model_version=? AND status='waiting_entry' ORDER BY score_as_of",
        (MARKET_MODEL,),
    ).fetchall()
    completed = 0
    for cohort in cohorts:
        score_as_of = cohort[0]
        tickers = [row[0] for row in connection.execute(
            "SELECT ticker FROM cohort_positions WHERE model_version=? AND score_as_of=? ORDER BY ticker",
            (MARKET_MODEL, score_as_of),
        ).fetchall()]
        if len(tickers) != 5:
            continue
        dates_by_ticker = []
        for ticker in tickers:
            dates_by_ticker.append({row[0] for row in connection.execute(
                "SELECT price_date FROM price_observations WHERE ticker=? AND price_date>? ORDER BY price_date",
                (ticker, score_as_of),
            ).fetchall()})
        common_dates = set.intersection(*dates_by_ticker) if dates_by_ticker else set()
        if not common_dates:
            continue
        entry_date = min(common_dates)
        prices = {
            ticker: connection.execute(
                "SELECT adjusted_close FROM price_observations WHERE ticker=? AND price_date=?",
                (ticker, entry_date),
            ).fetchone()[0]
            for ticker in tickers
        }
        connection.execute("BEGIN")
        try:
            for ticker, price in prices.items():
                connection.execute("""
                  UPDATE cohort_positions SET entry_price=?
                  WHERE model_version=? AND score_as_of=? AND ticker=? AND entry_price IS NULL
                """, (price, MARKET_MODEL, score_as_of, ticker))
            connection.execute("""
              UPDATE cohorts SET entry_date=?,status='tracking'
              WHERE model_version=? AND score_as_of=? AND status='waiting_entry'
            """, (entry_date, MARKET_MODEL, score_as_of))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        completed += 1
    return completed


def _series(connection: sqlite3.Connection, ticker: str, after: str) -> list[tuple[str, float]]:
    return [(row[0], float(row[1])) for row in connection.execute(
        "SELECT price_date,adjusted_close FROM price_observations WHERE ticker=? AND price_date>? ORDER BY price_date",
        (ticker, after),
    ).fetchall()]


def _series_from(connection: sqlite3.Connection, ticker: str, start: str) -> list[tuple[str, float]]:
    return [(row[0], float(row[1])) for row in connection.execute(
        "SELECT price_date,adjusted_close FROM price_observations WHERE ticker=? AND price_date>=? ORDER BY price_date",
        (ticker, start),
    ).fetchall()]


def _max_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    peak = values[0]
    drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            drawdown = min(drawdown, value / peak - 1)
    return drawdown


def metrics_by_horizon_from_db(connection: sqlite3.Connection) -> dict:
    score_dates = [row[0] for row in connection.execute("SELECT DISTINCT score_as_of FROM scores WHERE model_version=? ORDER BY score_as_of", (MARKET_MODEL,)).fetchall()]
    output = {}
    for horizon, trading_days in HORIZONS.items():
        observations = []
        cohort_returns, universe_returns, qqq_returns, spy_returns, drawdowns = [], [], [], [], []
        elapsed = 0
        for score_date in score_dates:
            cohort_row = connection.execute(
                "SELECT entry_date FROM cohorts WHERE model_version=? AND score_as_of=?",
                (MARKET_MODEL, score_date),
            ).fetchone()
            entry_date = cohort_row[0] if cohort_row and cohort_row[0] else None
            rows = [json.loads(row[0]) for row in connection.execute(
                "SELECT payload_json FROM scores WHERE model_version=? AND score_as_of=? AND eligible=1",
                (MARKET_MODEL, score_date),
            ).fetchall()]
            cohort = []
            date_observations = []
            for row in rows:
                series = _series_from(connection, row["ticker"], entry_date) if row.get("candidateRank") and entry_date else _series(connection, row["ticker"], score_date)
                elapsed = max(elapsed, max(0, len(series) - 1))
                value = forward_return([item[1] for item in series], 0, trading_days)
                if value is not None:
                    observation = {"companyScore": row["companyScore"], "return": value, "top5": bool(row.get("candidateRank"))}
                    observations.append(observation)
                    date_observations.append(observation)
                    if row.get("candidateRank"):
                        cohort.append(value)
            matured = [row["return"] for row in date_observations if row.get("return") is not None]
            if matured:
                universe_returns.append(mean(matured))
            if len(cohort) == 5:
                cohort_returns.append(mean(cohort))
                top_series = [
                    _series_from(connection, row["ticker"], entry_date) if entry_date else _series(connection, row["ticker"], score_date)
                    for row in rows if row.get("candidateRank")
                ]
                if len(top_series) == 5 and min(map(len, top_series)) > 1:
                    length = min(min(map(len, top_series)), trading_days + 1)
                    normalized = [mean(series[index][1] / series[0][1] for series in top_series) for index in range(length)]
                    drawdowns.append(_max_drawdown(normalized))
            for benchmark, target in (("QQQ", qqq_returns), ("SPY", spy_returns)):
                series = _series_from(connection, benchmark, entry_date) if entry_date else _series(connection, benchmark, score_date)
                value = forward_return([item[1] for item in series], 0, trading_days)
                if value is not None:
                    target.append(value)
        metric = metrics_for_horizon(observations, horizon)
        metric["elapsedTradingDays"] = min(trading_days, elapsed)
        metric["top5Return"] = mean(cohort_returns) if cohort_returns else None
        metric["universeReturn"] = mean(universe_returns) if universe_returns else None
        metric["qqqReturn"] = mean(qqq_returns) if qqq_returns else None
        metric["spyReturn"] = mean(spy_returns) if spy_returns else None
        metric["excessVsQqq"] = None if not cohort_returns or not qqq_returns else mean(cohort_returns) - mean(qqq_returns)
        metric["excessVsSpy"] = None if not cohort_returns or not spy_returns else mean(cohort_returns) - mean(spy_returns)
        metric["maxDrawdown"] = min(drawdowns) if drawdowns else None
        output[horizon] = metric
    return output


def legacy_validation(connection: sqlite3.Connection) -> dict:
    rows = connection.execute("SELECT * FROM legacy_observations WHERE model_version=? ORDER BY as_of,ticker", (LEGACY_MODEL,)).fetchall()
    by_ticker = defaultdict(list)
    for row in rows:
        by_ticker[row["ticker"]].append(row)
    comparisons = []
    for ticker, values in by_ticker.items():
        priced = [row for row in values if finite(row["price"]) is not None and row["price"] > 0]
        if len(priced) < 2:
            continue
        first, last = priced[0], priced[-1]
        comparisons.append({
            "ticker": ticker,
            "name": first["name"],
            "score": first["score"],
            "startDate": first["as_of"],
            "endDate": last["as_of"],
            "return": last["price"] / first["price"] - 1,
            "startPrice": first["price"],
            "endPrice": last["price"],
        })
    pairs = [(row["score"], row["return"]) for row in comparisons]
    return {
        "modelVersion": LEGACY_MODEL,
        "status": "pilot" if comparisons else "pending",
        "sampleSize": len(comparisons),
        "rows": sorted(comparisons, key=lambda row: row["score"], reverse=True),
        "spearman": spearman(pairs),
        "warning": "보유종목의 짧은 관찰 파일럿이며 예측력 확정 근거가 아닙니다.",
    }


def research_payload(connection: sqlite3.Connection, *, score_as_of: str = "", quote_as_of: str = "") -> dict:
    latest_universe = connection.execute("SELECT MAX(as_of) FROM universe_members").fetchone()[0]
    universe_rows = [] if not latest_universe else connection.execute("SELECT ticker,name,cik,sources FROM universe_members WHERE as_of=? ORDER BY ticker", (latest_universe,)).fetchall()
    score_date = score_as_of or connection.execute("SELECT MAX(score_as_of) FROM scores WHERE model_version=?", (MARKET_MODEL,)).fetchone()[0] or ""
    scores = [] if not score_date else connection.execute("SELECT payload_json FROM scores WHERE model_version=? AND score_as_of=? ORDER BY company_score DESC", (MARKET_MODEL, score_date)).fetchall()
    score_rows = [json.loads(row[0]) for row in scores]
    candidate_quotes = (get_research_meta(connection, "candidateQuotes").get("items") or {})
    for row in score_rows:
        quote = candidate_quotes.get(str(row.get("ticker") or "").upper())
        if quote:
            row["lastPrice"] = quote.get("lastPrice")
            row["quoteTimestamp"] = quote.get("timestamp")
    candidates = [row for row in score_rows if row.get("candidateRank") in (1, 2, 3, 4, 5)]
    cohorts = [dict(row) for row in connection.execute("SELECT * FROM cohorts WHERE model_version=? ORDER BY score_as_of DESC", (MARKET_MODEL,)).fetchall()]
    completeness = 0 if not score_rows else round(sum(float(row.get("dataCompleteness") or 0) for row in score_rows) / len(score_rows), 1)
    universe_status = get_research_meta(connection, "universeStatus")
    pipeline_status = get_research_meta(connection, "pipelineStatus")
    stale = bool(universe_status.get("stale")) or not candidates
    quality_message = pipeline_status.get("message") or universe_status.get("reason")
    if not quality_message:
        quality_message = "Nasdaq-100 시점보존 후보가 아직 없습니다." if not candidates else "공시 접수시점과 수정주가 기준"
    return {
        "modelVersion": MARKET_MODEL,
        "universe": {
            "name": universe_status.get("name") or "Nasdaq-100",
            "asOf": latest_universe or "",
            "totalCount": len(universe_rows),
            "eligibleCount": sum(1 for row in score_rows if row.get("eligible")),
            "members": [dict(row) for row in universe_rows],
            "sources": universe_status.get("sources") or [
                {"label": "Nasdaq-100", "url": "https://www.nasdaq.com/solutions/global-indexes/nasdaq-100/companies"},
            ],
        },
        "candidates": candidates,
        "legacyValidation": legacy_validation(connection),
        "cohorts": cohorts,
        "metricsByHorizon": metrics_by_horizon_from_db(connection),
        "scoreAsOf": score_date,
        "quoteAsOf": quote_as_of,
        "dataQuality": {
            "status": "ready" if candidates and not stale else "waiting",
            "completeness": completeness,
            "stale": stale,
            "message": quality_message,
            "universe": universe_status,
            "pipeline": pipeline_status,
        },
        "methodology": {
            "currency": "USD",
            "entry": "신호 다음 거래일 종가",
            "returnType": "수정주가 가격수익률",
            "costs": "배당·세금·거래비용 미반영",
            "researchOnly": True,
        },
    }
