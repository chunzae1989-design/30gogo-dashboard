#!/usr/bin/env python3
"""Create one monthly Guru research cohort without any trading capability."""
from __future__ import annotations

import argparse
import calendar
import json
import sys
from datetime import date, datetime, time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from guru_research import MARKET_MODEL, init_research_db  # noqa: E402
from guru_research_pipeline import GuruMarketPipeline, normalize_candles  # noqa: E402
from toss_snapshot_sync import PRIVATE_SOURCE, TossReadOnlyClient  # noqa: E402

DATABASE = Path.home() / ".30gogo" / "data" / "guru_research.sqlite"


def valid_month_end_run(score_as_of: str, today: date | None = None) -> tuple[bool, str]:
    score_date = date.fromisoformat(score_as_of)
    today = today or date.today()
    month_end = calendar.monthrange(score_date.year, score_date.month)[1]
    if month_end - score_date.day > 4:
        return False, "월말 마지막 5일 밖의 날짜는 점수 기준일로 사용할 수 없습니다."
    if score_date > today or (today - score_date).days > 4:
        return False, "사후 기간선택을 막기 위해 기준일 4일 이내에만 새 코호트를 만들 수 있습니다."
    return True, ""


def latest_completed_session(client: TossReadOnlyClient, now: datetime | None = None) -> str:
    now = now or datetime.now(ZoneInfo("America/New_York"))
    rows = normalize_candles(client.get("/api/v1/candles", {
        "symbol": "QQQ",
        "interval": "1d",
        "count": 10,
        "adjusted": "true",
    }))
    include_today = now.weekday() < 5 and now.time() >= clock_time(16, 15)
    today = now.date().isoformat()
    eligible = [row["date"] for row in rows if row["date"] < today or (include_today and row["date"] == today)]
    if not eligible:
        raise RuntimeError("완료된 미국장 거래일을 확인하지 못했습니다.")
    return max(eligible)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a read-only monthly Guru research cohort")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--score-as-of", help="US month-end session date (YYYY-MM-DD)")
    mode.add_argument("--bootstrap-current", action="store_true", help="Freeze the first Nasdaq-100 baseline at the latest completed US session")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    today = datetime.now(ZoneInfo("America/New_York")).date()
    if not PRIVATE_SOURCE.exists():
        print(json.dumps({"ok": False, "created": False, "reason": "개인 원본이 없습니다."}, ensure_ascii=False))
        return 2
    private = json.loads(PRIVATE_SOURCE.read_text(encoding="utf-8"))
    held = [str(row.get("ticker") or "").upper() for row in private.get("assets") or []]
    client = TossReadOnlyClient()
    with init_research_db(DATABASE) as connection:
        if args.bootstrap_current:
            if connection.execute("SELECT 1 FROM cohorts WHERE model_version=? LIMIT 1", (MARKET_MODEL,)).fetchone():
                status = {"ok": False, "created": False, "reason": "Nasdaq-100 최초 기준선이 이미 고정되어 있습니다."}
            else:
                score_as_of = latest_completed_session(client)
                status = GuruMarketPipeline(connection, client).run(score_as_of, held, cohort_kind="bootstrap")
        else:
            valid, reason = valid_month_end_run(args.score_as_of, today)
            if not valid:
                status = {"ok": False, "created": False, "reason": reason}
            else:
                status = GuruMarketPipeline(connection, client).run(args.score_as_of, held, cohort_kind="monthly")
    print(json.dumps(status, ensure_ascii=False))
    return 0 if status.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
