#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import { createDecipheriv } from "node:crypto";
import { chmodSync, mkdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { gunzipSync } from "node:zlib";

const root = resolve(import.meta.dirname, "..");
const privateRoot = join(homedir(), ".30gogo", "data");
const outputPath = join(privateRoot, "guru_legacy_observations.json");
const keyText = execFileSync("/usr/bin/security", [
  "find-generic-password", "-a", "30gogo", "-s", "30gogo.pages.vault-data-key", "-w",
], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
const dataKey = Buffer.from(keyText, "base64url");
if (dataKey.length !== 32) throw new Error("Keychain vault 데이터 키가 올바르지 않습니다.");

function decryptEnvelope(envelope) {
  if (envelope.cipher !== "AES-256-GCM" || envelope.compression !== "gzip") throw new Error("지원하지 않는 vault 형식입니다.");
  const ciphertext = Buffer.from(envelope.payload.ciphertext, "base64");
  const decipher = createDecipheriv("aes-256-gcm", dataKey, Buffer.from(envelope.payload.iv, "base64"));
  decipher.setAuthTag(ciphertext.subarray(ciphertext.length - 16));
  const compressed = Buffer.concat([decipher.update(ciphertext.subarray(0, -16)), decipher.final()]);
  return JSON.parse(gunzipSync(compressed).toString("utf8"));
}

const commits = execFileSync("git", ["log", "--follow", "--format=%H", "--", "portfolio.vault.json"], {
  cwd: root, encoding: "utf8", maxBuffer: 8 * 1024 * 1024,
}).trim().split(/\s+/).filter(Boolean).reverse();
const observations = new Map();
let decrypted = 0;
for (const commit of commits) {
  let envelope;
  try {
    envelope = JSON.parse(execFileSync("git", ["show", `${commit}:portfolio.vault.json`], {
      cwd: root, encoding: "utf8", maxBuffer: 24 * 1024 * 1024,
    }));
    const payload = decryptEnvelope(envelope);
    decrypted += 1;
    const scoreAsOf = payload?.guruData?.asOf || "";
    const asOf = payload?.generatedAt || envelope.generatedAt;
    for (const row of payload?.guruData?.rows || []) {
      const ticker = String(row.ticker || "").toUpperCase();
      if (!ticker || !Number.isFinite(Number(row.finalScore))) continue;
      const key = `${asOf}|${ticker}`;
      observations.set(key, {
        asOf,
        scoreAsOf,
        ticker,
        name: String(row.name || ticker),
        score: Number(row.finalScore),
        price: Number.isFinite(Number(row.price)) && Number(row.price) > 0 ? Number(row.price) : null,
      });
    }
  } catch {
    continue;
  }
}

mkdirSync(privateRoot, { recursive: true, mode: 0o700 });
const result = {
  modelVersion: "legacy-holdings-v1",
  generatedAt: new Date().toISOString(),
  source: "Locally decrypted Git vault history",
  revisionsScanned: commits.length,
  revisionsDecrypted: decrypted,
  observations: [...observations.values()].sort((a, b) => a.asOf.localeCompare(b.asOf) || a.ticker.localeCompare(b.ticker)),
};
writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`, { mode: 0o600 });
chmodSync(outputPath, 0o600);
process.stdout.write(`${JSON.stringify({ ok: true, outputPath, observations: result.observations.length, revisionsDecrypted: decrypted })}\n`);
