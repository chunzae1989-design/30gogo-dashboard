"""Pure portfolio performance calculations for the encrypted dashboard payload."""

from __future__ import annotations

from datetime import date, datetime


OFFICIAL_START = "2026-06-23"


def _day(value: str) -> str:
    return str(value or "")[:10]


def _daily_snapshots(history: dict, official_start: str) -> list[dict]:
    by_day: dict[str, dict] = {}
    for snapshot in history.get("snapshots") or []:
        day = _day(snapshot.get("asOf"))
        if day and day >= official_start:
            by_day[day] = snapshot
    return [by_day[key] for key in sorted(by_day)]


def _xirr(cash_flows: list[tuple[str, float]]) -> float | None:
    if len(cash_flows) < 2 or not any(value < 0 for _, value in cash_flows) or not any(value > 0 for _, value in cash_flows):
        return None
    start = date.fromisoformat(cash_flows[0][0])

    def npv(rate: float) -> float:
        return sum(value / ((1 + rate) ** ((date.fromisoformat(day) - start).days / 365)) for day, value in cash_flows)

    low, high = -0.9999, 10.0
    low_value, high_value = npv(low), npv(high)
    if low_value * high_value > 0:
        return None
    for _ in range(160):
        middle = (low + high) / 2
        middle_value = npv(middle)
        if abs(middle_value) < 0.01:
            return middle
        if low_value * middle_value <= 0:
            high, high_value = middle, middle_value
        else:
            low, low_value = middle, middle_value
    return (low + high) / 2


def _benchmark_by_day(prices: list[dict], daily: list[dict]) -> tuple[dict[str, float], str | None]:
    if not prices:
        return {}, None
    fx_by_day = {_day(row.get("asOf")): float(row.get("usdKrw") or 0) for row in daily}
    last_fx = next((value for value in fx_by_day.values() if value > 0), 1350.0)
    values: dict[str, float] = {}
    source_as_of = None
    for row in sorted(prices, key=lambda item: item.get("date") or ""):
        day = _day(row.get("date"))
        if not day:
            continue
        fx = fx_by_day.get(day) or last_fx
        if fx > 0:
            last_fx = fx
        close_native = float(row.get("close") or 0)
        if close_native > 0:
            values[day] = close_native * (last_fx if str(row.get("currency") or "USD").upper() == "USD" else 1)
            source_as_of = max(source_as_of or day, day)
    return values, source_as_of


def _contributions(daily: list[dict]) -> list[dict]:
    totals: dict[str, dict] = {}
    for previous, current in zip(daily, daily[1:]):
        previous_positions = {row.get("ticker"): row for row in previous.get("positions") or []}
        current_positions = {row.get("ticker"): row for row in current.get("positions") or []}
        for ticker in previous_positions.keys() | current_positions.keys():
            before = previous_positions.get(ticker) or {}
            after = current_positions.get(ticker) or {}
            quantity = float(before.get("quantity") or 0)
            price_before = float(before.get("priceKrw") or 0)
            price_after = float(after.get("priceKrw") or price_before)
            contribution = quantity * (price_after - price_before)
            item = totals.setdefault(ticker or "-", {"ticker": ticker or "-", "name": after.get("name") or before.get("name") or ticker or "-", "amountKrw": 0.0})
            item["amountKrw"] += contribution
    return sorted(totals.values(), key=lambda item: abs(item["amountKrw"]), reverse=True)


def build_performance(
    history: dict,
    cash_flows: list[dict],
    benchmark_prices: list[dict],
    reviewed_through: str | None,
    official_start: str = OFFICIAL_START,
) -> dict:
    daily = _daily_snapshots(history, official_start)
    if not daily:
        return {
            "officialStart": official_start,
            "status": "unavailable",
            "method": "daily-twr-end-of-day-flows",
            "series": [],
            "cashFlows": cash_flows,
            "contributions": [],
            "summary": {},
        }

    flows = [
        {**flow, "date": _day(flow.get("date") or flow.get("asOf")), "amountKrw": float(flow.get("amountKrw") or 0)}
        for flow in cash_flows
        if _day(flow.get("date") or flow.get("asOf")) >= official_start
    ]
    flows_by_day: dict[str, float] = {}
    for flow in flows:
        flows_by_day[flow["date"]] = flows_by_day.get(flow["date"], 0.0) + flow["amountKrw"]

    benchmark_values, benchmark_as_of = _benchmark_by_day(benchmark_prices, daily)
    benchmark_days = sorted(benchmark_values)
    benchmark_base = next((benchmark_values[day] for day in benchmark_days if day >= _day(daily[0].get("asOf"))), None)
    benchmark_cursor = benchmark_base
    cumulative = 1.0
    peak = 1.0
    max_drawdown = 0.0
    series = []
    previous_value = float(daily[0].get("totalKrw") or 0)

    for index, snapshot in enumerate(daily):
        day = _day(snapshot.get("asOf"))
        value = float(snapshot.get("totalKrw") or 0)
        external_flow = 0.0 if index == 0 else flows_by_day.get(day, 0.0)
        daily_return = 0.0 if index == 0 or previous_value <= 0 else (value - external_flow) / previous_value - 1
        if index:
            cumulative *= 1 + daily_return
        peak = max(peak, cumulative)
        drawdown = cumulative / peak - 1 if peak else 0.0
        max_drawdown = min(max_drawdown, drawdown)
        eligible = [benchmark_values[item] for item in benchmark_days if item <= day]
        if eligible:
            benchmark_cursor = eligible[-1]
        benchmark_index = (benchmark_cursor / benchmark_base * 100) if benchmark_base and benchmark_cursor else None
        series.append({
            "date": day,
            "portfolioValueKrw": value,
            "externalFlowKrw": external_flow,
            "dailyReturn": daily_return,
            "portfolioIndex": cumulative * 100,
            "benchmarkIndex": benchmark_index,
            "drawdown": drawdown,
        })
        previous_value = value

    start_value = float(daily[0].get("totalKrw") or 0)
    end_value = float(daily[-1].get("totalKrw") or 0)
    net_flow = sum(flow["amountKrw"] for flow in flows if flow["date"] > _day(daily[0].get("asOf")))
    investor_flows = [(_day(daily[0].get("asOf")), -start_value)]
    investor_flows.extend((flow["date"], -flow["amountKrw"]) for flow in flows if flow["date"] > _day(daily[0].get("asOf")))
    investor_flows.append((_day(daily[-1].get("asOf")), end_value))
    money_weighted = _xirr(investor_flows)
    portfolio_return = cumulative - 1
    benchmark_return = (series[-1]["benchmarkIndex"] / 100 - 1) if series[-1]["benchmarkIndex"] is not None else None
    last_day = _day(daily[-1].get("asOf"))

    return {
        "officialStart": official_start,
        "reviewedThrough": reviewed_through,
        "status": "official" if reviewed_through and reviewed_through >= last_day else "provisional",
        "method": "daily-twr-end-of-day-flows",
        "benchmark": {"symbol": "QQQ", "currency": "KRW", "asOf": benchmark_as_of},
        "series": series,
        "cashFlows": sorted(flows, key=lambda item: (item["date"], item.get("id") or 0), reverse=True),
        "contributions": _contributions(daily),
        "summary": {
            "startValueKrw": start_value,
            "endValueKrw": end_value,
            "netExternalFlowKrw": net_flow,
            "portfolioReturn": portfolio_return,
            "moneyWeightedReturn": money_weighted,
            "benchmarkReturn": benchmark_return,
            "excessReturn": portfolio_return - benchmark_return if benchmark_return is not None else None,
            "maxDrawdown": max_drawdown,
            "snapshotDays": len(daily),
            "cashFlowCount": len(flows),
            "lastDate": last_day,
        },
    }
