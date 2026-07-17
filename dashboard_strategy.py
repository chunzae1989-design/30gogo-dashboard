"""Private dashboard strategy and valuation-cache helpers."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path


QQQ_NEW_MONEY_POLICY = {
    "strategy": "QQQ_CASH",
    "qqqShare": 0.55,
    "cashShare": 0.45,
    "effectiveFrom": "2026-07-17",
}

QQQ_ALLOCATION_PLAN = [
    {"ticker": "QQQ", "share": 0.55, "note": "신규 투자금의 중심 복리 엔진"},
    {"ticker": "CASH", "share": 0.45, "note": "QQQ 월간 리밸런싱과 급락 대응 현금 버킷"},
    {"ticker": "379800", "hold": True, "note": "기존 보유 유지, 신규 투자금 배정 없음"},
    {"ticker": "TSLA", "hold": True, "note": "현재 집중도가 높아 신규 투자금 배정 없음"},
    {"ticker": "RKLB", "hold": True, "note": "고변동 기존 포지션 관리"},
    {"ticker": "SPACEX", "hold": True, "note": "기존 포지션 수량·평단·현재가 관리"},
]


def _as_of(value: object) -> datetime:
    text = str(value or "").strip().replace(" KST", "")
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(datetime.now().strftime(pattern))], pattern)
        except ValueError:
            continue
    return datetime.min


def _valid_guru(data: object) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("rows"), list)
        and len(data["rows"]) > 0
        and isinstance(data.get("philosophies"), list)
    )


def apply_qqq_new_money_policy(payload: dict) -> None:
    config = payload.setdefault("dashboardConfig", {})
    config["newMoneyPolicy"] = deepcopy(QQQ_NEW_MONEY_POLICY)
    config["allocationPlan"] = deepcopy(QQQ_ALLOCATION_PLAN)
    config["rules"] = [
        rule for rule in config.get("rules", [])
        if not (str(rule.get("ticker")) == "379800" and rule.get("operator") == "min")
    ]


def promote_latest_guru_cache(payload: dict, paths: list[Path]) -> dict:
    current = payload.get("guruData") if _valid_guru(payload.get("guruData")) else None
    selected = current
    selected_path = None
    for path in paths:
        if not path.exists():
            continue
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if _valid_guru(candidate) and (selected is None or _as_of(candidate.get("asOf")) > _as_of(selected.get("asOf"))):
            selected = candidate
            selected_path = path
    if selected is not None:
        payload["guruData"] = selected
    return {
        "updated": selected_path is not None,
        "asOf": (selected or {}).get("asOf"),
        "source": str(selected_path) if selected_path else "payload",
    }


def latest_daily_change(candles: list[dict]) -> dict | None:
    valid = [
        row for row in candles
        if row.get("timestamp") and float(row.get("closePrice") or 0) > 0
    ]
    valid.sort(key=lambda row: str(row["timestamp"]), reverse=True)
    if len(valid) < 2:
        return None
    latest, previous = valid[0], valid[1]
    latest_close = float(latest["closePrice"])
    previous_close = float(previous["closePrice"])
    return {
        "changePct": (latest_close / previous_close - 1) * 100,
        "asOf": str(latest["timestamp"]),
    }
