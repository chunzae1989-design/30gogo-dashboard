#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import {
  createCipheriv,
  createHash,
  pbkdf2Sync,
  randomBytes,
} from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync, chmodSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import vm from "node:vm";
import { gzipSync } from "node:zlib";

const ROOT = resolve(import.meta.dirname, "..");
const PRIVATE_ROOT = join(homedir(), ".30gogo", "data");
const PRIVATE_SOURCE = join(PRIVATE_ROOT, "private-portfolio.json");
const VAULT_PATH = join(ROOT, "portfolio.vault.json");
const KEYCHAIN_ACCOUNT = "30gogo";
const PASSPHRASE_SERVICE = "30gogo.pages.vault-passphrase";
const DATA_KEY_SERVICE = "30gogo.pages.vault-data-key";
const PBKDF2_ITERATIONS = 600_000;

function ensurePrivateRoot() {
  mkdirSync(PRIVATE_ROOT, { recursive: true, mode: 0o700 });
  chmodSync(PRIVATE_ROOT, 0o700);
}

function readJson(path, fallback = null) {
  if (!existsSync(path)) return fallback;
  return JSON.parse(readFileSync(path, "utf8"));
}

function extractInitialPrivateData() {
  const indexPath = join(ROOT, "index.html");
  const source = readFileSync(indexPath, "utf8");
  const assetsMatch = source.match(/let assets=(\[[\s\S]*?\n\]);\nconst guruData=/);
  const guruMatch = source.match(/const guruData=(\{[^\n]+\});\nconst goals=/);
  const profileMatch = source.match(/profile=\{age:([\d.]+),monthly:([\d.]+)\}/);
  if (!assetsMatch || !guruMatch || !profileMatch) {
    throw new Error("현재 index.html에서 초기 포트폴리오를 찾지 못했습니다.");
  }

  const assets = vm.runInNewContext(`(${assetsMatch[1]})`, Object.create(null), { timeout: 1_000 });
  const guruData = JSON.parse(guruMatch[1]);
  const payload = {
    schemaVersion: 1,
    generatedAt: new Date().toISOString(),
    assets,
    guruData,
    profile: {
      age: Number(profileMatch[1]),
      monthly: Number(profileMatch[2]),
    },
    portfolioHistory: readJson(join(ROOT, "portfolio_history.json"), { snapshots: [] }),
    tossSnapshot: readJson(join(ROOT, "toss_snapshot.json"), null),
    valuationCache: readJson(join(ROOT, "valuation_cache.json"), null),
  };

  ensurePrivateRoot();
  writeFileSync(PRIVATE_SOURCE, `${JSON.stringify(payload, null, 2)}\n`, { mode: 0o600 });
  chmodSync(PRIVATE_SOURCE, 0o600);
  return payload;
}

function keychainRead(service) {
  try {
    return execFileSync("/usr/bin/security", [
      "find-generic-password",
      "-a",
      KEYCHAIN_ACCOUNT,
      "-s",
      service,
      "-w",
    ], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
  } catch {
    return "";
  }
}

function keychainWrite(service, value) {
  execFileSync("/usr/bin/security", [
    "add-generic-password",
    "-U",
    "-a",
    KEYCHAIN_ACCOUNT,
    "-s",
    service,
    "-w",
    value,
  ], { stdio: "ignore" });
}

function ensureSecret(service, bytes) {
  const existing = keychainRead(service);
  if (existing) return existing;
  const generated = randomBytes(bytes).toString("base64url");
  keychainWrite(service, generated);
  return generated;
}

function encryptAesGcm(key, plaintext, iv) {
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  return Buffer.concat([cipher.update(plaintext), cipher.final(), cipher.getAuthTag()]);
}

function buildVault() {
  const source = readJson(PRIVATE_SOURCE);
  if (!source?.assets?.length) throw new Error(`로컬 원본이 없습니다: ${PRIVATE_SOURCE}`);

  const passphrase = ensureSecret(PASSPHRASE_SERVICE, 24);
  const dataKey = Buffer.from(ensureSecret(DATA_KEY_SERVICE, 32), "base64url");
  if (dataKey.length !== 32) throw new Error("Keychain 데이터 키 길이가 올바르지 않습니다.");

  const compressed = gzipSync(Buffer.from(JSON.stringify(source), "utf8"), { level: 9 });
  const payloadIv = randomBytes(12);
  const payloadCiphertext = encryptAesGcm(dataKey, compressed, payloadIv);

  const salt = randomBytes(16);
  const wrappingKey = pbkdf2Sync(passphrase, salt, PBKDF2_ITERATIONS, 32, "sha256");
  const wrapIv = randomBytes(12);
  const wrappedKey = encryptAesGcm(wrappingKey, dataKey, wrapIv);
  const keyId = createHash("sha256").update(dataKey).digest("hex").slice(0, 16);

  const envelope = {
    version: 1,
    generatedAt: new Date().toISOString(),
    keyId,
    compression: "gzip",
    cipher: "AES-256-GCM",
    payload: {
      iv: payloadIv.toString("base64"),
      ciphertext: payloadCiphertext.toString("base64"),
    },
    passwordWrap: {
      kdf: "PBKDF2-HMAC-SHA-256",
      iterations: PBKDF2_ITERATIONS,
      salt: salt.toString("base64"),
      iv: wrapIv.toString("base64"),
      wrappedKey: wrappedKey.toString("base64"),
    },
  };
  writeFileSync(VAULT_PATH, `${JSON.stringify(envelope)}\n`, { mode: 0o644 });
  return { keyId, generatedAt: envelope.generatedAt, bytes: Buffer.byteLength(JSON.stringify(envelope)) };
}

function rotateAll() {
  keychainWrite(PASSPHRASE_SERVICE, randomBytes(24).toString("base64url"));
  keychainWrite(DATA_KEY_SERVICE, randomBytes(32).toString("base64url"));
  return buildVault();
}

const command = process.argv[2] || "build";
let result;
if (command === "bootstrap") {
  const payload = extractInitialPrivateData();
  result = { privateSource: PRIVATE_SOURCE, assets: payload.assets.length };
} else if (command === "build") {
  result = buildVault();
} else if (command === "rotate-all") {
  result = rotateAll();
} else {
  throw new Error("사용법: node scripts/vault.mjs bootstrap|build|rotate-all");
}

process.stdout.write(`${JSON.stringify({ ok: true, ...result })}\n`);
