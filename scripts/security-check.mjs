#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const failures = [];
const tracked = execFileSync("git", ["ls-files", "-z"], { cwd: root })
  .toString("utf8")
  .split("\0")
  .filter(Boolean);

const forbiddenTracked = [
  /^\.env(?:\.|$)/,
  /(?:^|\/)portfolio_history\.json$/,
  /(?:^|\/)toss_snapshot\.json$/,
  /(?:^|\/)valuation_cache\.json$/,
  /\.sqlite(?:-(?:wal|shm))?$/,
  /(?:^|\/)toss-trade-(?:ui|guard)/,
  /(?:^|\/)local-trade-ui\.js$/,
];

for (const file of tracked) {
  if (existsSync(resolve(root, file)) && forbiddenTracked.some((pattern) => pattern.test(file))) failures.push(`금지된 추적 파일: ${file}`);
}

const publicFiles = ["index.html", "app.js", "vault-lock.js", "qqq-core.js", "qqq-upgrade.js"];
const forbiddenPublic = [
  [/TOSS_CLIENT_(?:ID|SECRET)/i, "Toss 자격정보 변수"],
  [/tossAccessToken|accountSeq|X-Tossinvest-Account/i, "토큰 또는 계좌 식별자 코드"],
  [/\/api\/v1\/orders|\/trade\/execute|\/trade\/preview/i, "주문 endpoint"],
  [/Samsung HR|Age\s*37|삼성전자 근무/i, "개인 직장/나이 정보"],
  [/\b(?:TSLA|RKLB|SPACEX|ANET|VRT|COHR|MTSI|005930|035720|379800)\b/i, "실제 보유 종목 식별자"],
  [/portfolio_history\.json|toss_snapshot\.json|valuation_cache\.json/i, "평문 자산 파일 참조"],
  [/cdn\.jsdelivr\.net|unpkg\.com/i, "외부 CDN 스크립트"],
];

for (const file of publicFiles) {
  const path = resolve(root, file);
  if (!existsSync(path)) { failures.push(`공개 파일 누락: ${file}`); continue; }
  const source = readFileSync(path, "utf8");
  for (const [pattern, label] of forbiddenPublic) {
    if (pattern.test(source)) failures.push(`${file}: ${label} 발견`);
  }
}

try {
  const vault = JSON.parse(readFileSync(resolve(root, "portfolio.vault.json"), "utf8"));
  const allowed = ["cipher", "compression", "generatedAt", "keyId", "passwordWrap", "payload", "version"];
  const extra = Object.keys(vault).filter((key) => !allowed.includes(key));
  if (extra.length) failures.push(`vault 최상위 평문 필드: ${extra.join(", ")}`);
  if (vault.cipher !== "AES-256-GCM" || vault.compression !== "gzip") failures.push("vault 암호화 형식이 올바르지 않습니다.");
  if (!vault.payload?.ciphertext || !vault.passwordWrap?.wrappedKey) failures.push("vault 암호문 또는 래핑 키가 없습니다.");
} catch (error) {
  failures.push(`portfolio.vault.json 검증 실패: ${error.message}`);
}

try {
  const vendor = readFileSync(resolve(root, "vendor/chart.umd.min.js"));
  const expected = readFileSync(resolve(root, "vendor/chart.umd.min.js.sha256"), "utf8").trim().split(/\s+/)[0];
  const actual = createHash("sha256").update(vendor).digest("hex");
  if (actual !== expected) failures.push("고정 Chart.js 파일 체크섬 불일치");
} catch (error) {
  failures.push(`Chart.js 검증 실패: ${error.message}`);
}

if (failures.length) {
  process.stderr.write(`${failures.map((item) => `- ${item}`).join("\n")}\n`);
  process.exit(1);
}

process.stdout.write("security-check: ok\n");
