#!/usr/bin/env python3
"""Refresh the private portfolio and publish only an encrypted vault.

This process never writes plaintext portfolio or broker data into the repository.
It uses read-only Toss endpoints and cannot submit, change, or cancel orders.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PRIVATE_ROOT = Path.home() / ".30gogo" / "data"
PRIVATE_SOURCE = PRIVATE_ROOT / "private-portfolio.json"
HISTORY_DB = PRIVATE_ROOT / "portfolio_history.sqlite"
VAULT = ROOT / "portfolio.vault.json"
OPENAPI_BASE = "https://openapi.tossinvest.com"
SEOUL = ZoneInfo("Asia/Seoul")
EXCLUDE_TOSS = {"CASH", "SPACEX"}
KEYCHAIN_ACCOUNT = "30gogo"
KEYCHAIN_SERVICES = {
    "client_id": "30gogo.toss.client-id",
    "client_secret": "30gogo.toss.client-secret",
    "account_seq": "30gogo.toss.account-seq",
}


def now_dt() -> datetime:
    return datetime.now(SEOUL)


def hour_bucket() -> str:
    return now_dt().replace(minute=0, second=0, microsecond=0).isoformat()


def keychain(service: str) -> str:
    result = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-a", KEYCHAIN_ACCOUNT, "-s", service, "-w"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def credentials() -> dict[str, str]:
    values = {name: keychain(service) for name, service in KEYCHAIN_SERVICES.items()}
    if not all(values.values()):
        raise RuntimeError("macOS Keychain에 Toss 자격정보가 모두 저장되지 않았습니다.")
    return values


def request_json(url: str, *, method: str = "GET", headers: dict | None = None, body: bytes | None = None) -> dict:
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read().decode("utf-8") or "{}")
            message = payload.get("message") or payload.get("error", {}).get("message")
        except Exception:
            message = None
        raise RuntimeError(message or f"Toss API HTTP {error.code}") from None


class TossReadOnlyClient:
    def __init__(self) -> None:
        self.creds = credentials()
        self.token = self._token()

    def _token(self) -> str:
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.creds["client_id"],
            "client_secret": self.creds["client_secret"],
        }).encode()
        data = request_json(
            f"{OPENAPI_BASE}/oauth2/token",
            method="POST",
            headers={"content-type": "application/x-www-form-urlencoded"},
            body=body,
        )
        token = data.get("access_token")
        if not token:
            raise RuntimeError("Toss access token을 발급받지 못했습니다.")
        return token

    def get(self, path: str, params: dict | None = None, *, account: bool = False) -> dict:
        query = urllib.parse.urlencode(params or {})
        url = f"{OPENAPI_BASE}{path}{'?' + query if query else ''}"
        headers = {"Authorization": f"Bearer {self.token}"}
        if account:
            headers["X-Tossinvest-Account"] = self.creds["account_seq"]
        return request_json(url, headers=headers)


def result(data):
    return data.get("result", data) if isinstance(data, dict) else data


def rows(data: dict) -> list[dict]:
    value = result(data)
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("items", "prices", "stocks", "holdings"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def number(value, currency: str = "KRW") -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        for key in (currency.lower(), currency.upper(), "amount", "amountAfterCost"):
            if value.get(key) is not None:
                return number(value[key], currency)
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def load_private() -> dict:
    if not PRIVATE_SOURCE.exists():
        raise RuntimeError(f"개인 원본이 없습니다: {PRIVATE_SOURCE}")
    return json.loads(PRIVATE_SOURCE.read_text(encoding="utf-8"))


def update_assets(payload: dict, client: TossReadOnlyClient) -> tuple[list[dict], dict]:
    assets = payload["assets"]
    symbols = [asset["ticker"] for asset in assets if asset["ticker"] not in EXCLUDE_TOSS]
    prices = {str(row.get("symbol", "")).upper(): row for row in rows(client.get("/api/v1/prices", {"symbols": ",".join(symbols)}))}
    holdings = {str(row.get("symbol", "")).upper(): row for row in rows(client.get("/api/v1/holdings", account=True))}
    rate_data = result(client.get("/api/v1/exchange-rate", {"baseCurrency": "USD", "quoteCurrency": "KRW"})) or {}
    usd_krw = number(rate_data.get("rate") or rate_data.get("midRate")) or 1350.0

    for asset in assets:
        ticker = str(asset.get("ticker", "")).upper()
        if ticker in EXCLUDE_TOSS:
            continue
        quote = prices.get(ticker)
        holding = holdings.get(ticker)
        currency = str((holding or quote or {}).get("currency") or "KRW").upper()
        fx = usd_krw if currency == "USD" else 1.0
        asset_qty = float(asset.get("quantity") or 0)
        holding_qty = number((holding or {}).get("quantity"), currency)
        partial_account = holding_qty is not None and asset_qty > holding_qty + 1e-6

        if holding and not partial_account:
            market = holding.get("marketValue") or {}
            value_native = number(market.get("amount"), currency)
            cost_native = number(market.get("purchaseAmount"), currency)
            last = number(holding.get("lastPrice"), currency)
            if value_native is None and holding_qty is not None and last is not None:
                value_native = holding_qty * last
            if holding_qty is not None:
                asset["quantity"] = holding_qty
            if value_native is not None:
                asset["value"] = value_native * fx
            if cost_native is not None:
                asset["cost"] = cost_native * fx
        elif quote:
            last = number(quote.get("lastPrice"), currency)
            if last and asset_qty:
                asset["value"] = asset_qty * last * fx
        asset["profit"] = float(asset.get("value") or 0) - float(asset.get("cost") or 0)

    total = sum(float(asset.get("value") or 0) for asset in assets)
    for asset in assets:
        quantity = float(asset.get("quantity") or 0)
        asset["weight"] = float(asset.get("value") or 0) / total if total else 0
        asset["price_krw"] = float(asset.get("value") or 0) / quantity if quantity else (1 if asset.get("ticker") == "CASH" else 0)

    guru_rows = (payload.get("guruData") or {}).get("rows") or []
    for guru in guru_rows:
        ticker = str(guru.get("ticker", "")).upper()
        quote = prices.get(ticker)
        if quote and number(quote.get("lastPrice"), str(quote.get("currency") or "KRW")):
            guru["price"] = number(quote.get("lastPrice"), str(quote.get("currency") or "KRW"))
            guru["currency"] = quote.get("currency") or guru.get("currency")
        asset = next((item for item in assets if str(item.get("ticker", "")).upper() == ticker), None)
        if asset:
            guru["weight"] = asset["weight"]
            guru["returnPct"] = (float(asset.get("profit") or 0) / float(asset.get("cost") or 1)) * 100

    snapshot = {
        "asOf": now_dt().isoformat(),
        "source": "Local read-only Toss Open API sync",
        "usdKrw": usd_krw,
        "updatedTickers": sorted(set(prices) & set(symbols)),
        "quoteCount": len(prices),
    }
    return assets, snapshot


def init_db(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            as_of TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL DEFAULT 'Encrypted local history',
            total_krw REAL NOT NULL,
            cash_krw REAL NOT NULL,
            usd_krw REAL,
            created_at TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_positions (
            snapshot_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            name TEXT NOT NULL,
            quantity REAL NOT NULL,
            price_krw REAL NOT NULL,
            value_krw REAL NOT NULL,
            cost_krw REAL NOT NULL,
            profit_krw REAL NOT NULL,
            weight REAL NOT NULL,
            PRIMARY KEY (snapshot_id, ticker),
            FOREIGN KEY (snapshot_id) REFERENCES portfolio_snapshots(id) ON DELETE CASCADE
        )
    """)


def store_snapshot(assets: list[dict], usd_krw: float) -> None:
    PRIVATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sqlite3.connect(HISTORY_DB) as connection:
        init_db(connection)
        bucket = hour_bucket()
        existing = connection.execute("SELECT id FROM portfolio_snapshots WHERE as_of=?", (bucket,)).fetchone()
        if existing:
            connection.execute("DELETE FROM portfolio_positions WHERE snapshot_id=?", (existing[0],))
            connection.execute("DELETE FROM portfolio_snapshots WHERE id=?", (existing[0],))
        total = sum(float(asset.get("value") or 0) for asset in assets)
        cash = sum(float(asset.get("value") or 0) for asset in assets if asset.get("ticker") == "CASH")
        cursor = connection.execute(
            "INSERT INTO portfolio_snapshots(as_of,source,total_krw,cash_krw,usd_krw,created_at) VALUES(?,?,?,?,?,?)",
            (bucket, "Read-only Toss Open API snapshot", total, cash, usd_krw, now_dt().isoformat()),
        )
        snapshot_id = int(cursor.lastrowid)
        connection.executemany(
            "INSERT INTO portfolio_positions(snapshot_id,ticker,name,quantity,price_krw,value_krw,cost_krw,profit_krw,weight) VALUES(?,?,?,?,?,?,?,?,?)",
            [(
                snapshot_id,
                asset.get("ticker") or "",
                asset.get("name") or asset.get("ticker") or "",
                float(asset.get("quantity") or 0),
                float(asset.get("price_krw") or 0),
                float(asset.get("value") or 0),
                float(asset.get("cost") or 0),
                float(asset.get("profit") or 0),
                float(asset.get("weight") or 0),
            ) for asset in assets],
        )
        connection.commit()


def history_payload(years: int) -> dict:
    cutoff = (now_dt() - timedelta(days=365 * years)).isoformat()
    with sqlite3.connect(HISTORY_DB) as connection:
        connection.row_factory = sqlite3.Row
        init_db(connection)
        snapshots = connection.execute("SELECT * FROM portfolio_snapshots WHERE as_of>=? ORDER BY as_of", (cutoff,)).fetchall()
        result_rows = []
        for snapshot in snapshots:
            positions = connection.execute("SELECT * FROM portfolio_positions WHERE snapshot_id=? ORDER BY value_krw DESC", (snapshot["id"],)).fetchall()
            result_rows.append({
                "asOf": snapshot["as_of"],
                "source": "Encrypted local history",
                "totalKrw": snapshot["total_krw"],
                "cashKrw": snapshot["cash_krw"],
                "usdKrw": snapshot["usd_krw"],
                "positions": [{
                    "ticker": row["ticker"], "name": row["name"], "quantity": row["quantity"],
                    "priceKrw": row["price_krw"], "valueKrw": row["value_krw"],
                    "costKrw": row["cost_krw"], "profitKrw": row["profit_krw"], "weight": row["weight"],
                } for row in positions],
            })
    return {"generatedAt": now_dt().isoformat(), "source": "Encrypted local SQLite history", "retentionYears": years, "snapshots": result_rows}


def publish(commit: bool, push: bool, as_of: str) -> str:
    subprocess.run(["node", "scripts/vault.mjs", "build"], cwd=ROOT, check=True)
    subprocess.run(["node", "scripts/security-check.mjs"], cwd=ROOT, check=True)
    if not commit and not push:
        return "vault rebuilt locally"
    subprocess.run(["git", "add", "portfolio.vault.json"], cwd=ROOT, check=True)
    changed = subprocess.run(["git", "diff", "--cached", "--quiet", "--", "portfolio.vault.json"], cwd=ROOT).returncode != 0
    if changed and commit:
        subprocess.run(["git", "commit", "-m", f"update encrypted portfolio vault {as_of}", "--", "portfolio.vault.json"], cwd=ROOT, check=True)
    if push and changed and commit:
        subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, check=True)
    return "encrypted vault committed" if changed else "no encrypted changes"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update private Toss snapshot and publish an encrypted vault")
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--history-years", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = load_private()
    assets, snapshot = update_assets(payload, TossReadOnlyClient())
    store_snapshot(assets, snapshot["usdKrw"])
    payload["assets"] = assets
    payload["generatedAt"] = now_dt().isoformat()
    payload["tossSnapshot"] = snapshot
    payload["portfolioHistory"] = history_payload(args.history_years)
    PRIVATE_SOURCE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(PRIVATE_SOURCE, 0o600)
    status = publish(args.commit, args.push, snapshot["asOf"])
    print(json.dumps({
        "ok": True,
        "status": status,
        "asOf": snapshot["asOf"],
        "updatedCount": len(snapshot["updatedTickers"]),
        "historySnapshots": len(payload["portfolioHistory"]["snapshots"]),
        "vault": str(VAULT),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
