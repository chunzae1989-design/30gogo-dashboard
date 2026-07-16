(() => {
  "use strict";

  const DB_NAME = "30gogo-vault";
  const STORE_NAME = "deviceKeys";
  const RECORD_ID = "pages-vault";
  const REMEMBER_MS = 30 * 24 * 60 * 60 * 1000;
  const IDLE_MS = 15 * 60 * 1000;
  const GENERIC_ERROR = "잠금을 해제할 수 없습니다";

  let envelope = null;
  let deviceKey = null;
  let unlockedPayload = null;
  let onUnlock = null;
  let idleTimer = null;
  let started = false;
  let localRuntime = false;

  const bytes = (base64) => Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));

  function openDatabase() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, 1);
      request.onupgradeneeded = () => request.result.createObjectStore(STORE_NAME, { keyPath: "id" });
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async function readDeviceKey() {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readonly");
      const request = tx.objectStore(STORE_NAME).get(RECORD_ID);
      request.onsuccess = () => resolve(request.result || null);
      request.onerror = () => reject(request.error);
      tx.oncomplete = () => db.close();
    });
  }

  async function storeDeviceKey(key) {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).put({
        id: RECORD_ID,
        key,
        keyId: envelope.keyId,
        expiresAt: Date.now() + REMEMBER_MS,
      });
      tx.oncomplete = () => { db.close(); resolve(); };
      tx.onerror = () => { db.close(); reject(tx.error); };
    });
  }

  async function deleteDeviceKey() {
    const db = await openDatabase();
    return new Promise((resolve) => {
      const tx = db.transaction(STORE_NAME, "readwrite");
      tx.objectStore(STORE_NAME).delete(RECORD_ID);
      tx.oncomplete = tx.onerror = () => { db.close(); resolve(); };
    });
  }

  async function gunzip(data) {
    if (typeof DecompressionStream !== "function") throw new Error("gzip unsupported");
    const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("gzip"));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  }

  async function decryptPayload(key) {
    const compressed = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: bytes(envelope.payload.iv) },
      key,
      bytes(envelope.payload.ciphertext),
    );
    const plain = await gunzip(compressed);
    const payload = JSON.parse(new TextDecoder().decode(plain));
    if (!Array.isArray(payload?.assets) || !payload.assets.length) throw new Error("payload invalid");
    return payload;
  }

  async function unwrapWithPassphrase(passphrase) {
    const material = await crypto.subtle.importKey(
      "raw",
      new TextEncoder().encode(passphrase),
      "PBKDF2",
      false,
      ["deriveKey"],
    );
    const wrappingKey = await crypto.subtle.deriveKey(
      {
        name: "PBKDF2",
        hash: "SHA-256",
        salt: bytes(envelope.passwordWrap.salt),
        iterations: envelope.passwordWrap.iterations,
      },
      material,
      { name: "AES-GCM", length: 256 },
      false,
      ["decrypt"],
    );
    const rawKey = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: bytes(envelope.passwordWrap.iv) },
      wrappingKey,
      bytes(envelope.passwordWrap.wrappedKey),
    );
    return crypto.subtle.importKey("raw", rawKey, { name: "AES-GCM" }, false, ["decrypt"]);
  }

  function lockMarkup() {
    return `
      <div class="vault-shell" role="dialog" aria-modal="true" aria-labelledby="vaultTitle">
        <div class="vault-brand">30gogo</div>
        <h1 id="vaultTitle">30gogo 투자관제실 잠금 해제</h1>
        <p id="vaultDescription">암호는 이 브라우저에서만 복호화에 사용되며 전송되거나 저장되지 않습니다.</p>
        <form id="vaultForm">
          <label for="vaultPassphrase">암호</label>
          <input id="vaultPassphrase" type="password" minlength="20" autocomplete="current-password" required />
          <label class="vault-check"><input id="vaultRemember" type="checkbox" checked /> 이 기기에서 30일간 기억</label>
          <button type="submit" id="vaultUnlock">잠금 해제</button>
        </form>
        <button type="button" class="vault-resume" id="vaultResume" hidden>다시 열기</button>
        <p class="vault-error" id="vaultError" role="alert"></p>
        <small id="vaultUpdated"></small>
      </div>`;
  }

  function mount() {
    let root = document.getElementById("vaultLock");
    if (!root) {
      root = document.createElement("div");
      root.id = "vaultLock";
      root.innerHTML = lockMarkup();
      document.body.append(root);
    }
    document.body.classList.add("vault-locked");
    document.getElementById("vaultForm").addEventListener("submit", handleUnlock);
    document.getElementById("vaultResume").addEventListener("click", resumeFromDeviceKey);
    return root;
  }

  function setBusy(busy) {
    const button = document.getElementById("vaultUnlock");
    const input = document.getElementById("vaultPassphrase");
    if (button) { button.disabled = busy; button.textContent = busy ? "확인 중..." : "잠금 해제"; }
    if (input) input.disabled = busy;
  }

  function showError() {
    const error = document.getElementById("vaultError");
    if (error) error.textContent = GENERIC_ERROR;
  }

  function installDeviceLockButton() {
    if (document.getElementById("vaultDeviceLock")) return;
    const button = document.createElement("button");
    button.id = "vaultDeviceLock";
    button.type = "button";
    button.textContent = "이 기기 잠금";
    button.addEventListener("click", async () => {
      await deleteDeviceKey();
      deviceKey = null;
      unlockedPayload = null;
      location.reload();
    });
    document.body.append(button);
  }

  function resetIdleTimer() {
    clearTimeout(idleTimer);
    if (!unlockedPayload || localRuntime) return;
    idleTimer = setTimeout(coverForIdle, IDLE_MS);
  }

  function coverForIdle() {
    document.body.classList.add("vault-locked");
    const form = document.getElementById("vaultForm");
    const resume = document.getElementById("vaultResume");
    const description = document.getElementById("vaultDescription");
    if (form) form.hidden = Boolean(deviceKey);
    if (resume) resume.hidden = !deviceKey;
    if (description) description.textContent = deviceKey ? "보안을 위해 화면을 가렸습니다. 이 기기에 저장된 키로 다시 엽니다." : "암호를 입력해 다시 잠금을 해제하세요.";
  }

  function finishUnlock(payload, key) {
    deviceKey = key;
    unlockedPayload = payload;
    onUnlock(payload);
    document.body.classList.remove("vault-locked");
    document.getElementById("vaultForm").hidden = false;
    document.getElementById("vaultResume").hidden = true;
    document.getElementById("vaultPassphrase").value = "";
    if (!localRuntime) installDeviceLockButton();
    resetIdleTimer();
  }

  async function resumeFromDeviceKey() {
    try {
      if (!deviceKey) throw new Error("missing key");
      const payload = await decryptPayload(deviceKey);
      finishUnlock(payload, deviceKey);
    } catch {
      await deleteDeviceKey();
      deviceKey = null;
      document.getElementById("vaultForm").hidden = false;
      document.getElementById("vaultResume").hidden = true;
      showError();
    }
  }

  async function handleUnlock(event) {
    event.preventDefault();
    const passphrase = document.getElementById("vaultPassphrase").value;
    if (passphrase.length < 20) { showError(); return; }
    setBusy(true);
    document.getElementById("vaultError").textContent = "";
    try {
      const key = await unwrapWithPassphrase(passphrase);
      const payload = await decryptPayload(key);
      if (document.getElementById("vaultRemember").checked) await storeDeviceKey(key);
      else await deleteDeviceKey();
      finishUnlock(payload, key);
    } catch {
      showError();
    } finally {
      setBusy(false);
    }
  }

  async function autoUnlock() {
    try {
      const record = await readDeviceKey();
      if (!record || record.keyId !== envelope.keyId || record.expiresAt <= Date.now()) {
        if (record) await deleteDeviceKey();
        return false;
      }
      const payload = await decryptPayload(record.key);
      finishUnlock(payload, record.key);
      return true;
    } catch {
      await deleteDeviceKey();
      return false;
    }
  }

  async function start(options) {
    if (started) return;
    started = true;
    onUnlock = options.onUnlock;
    mount();

    try {
      localRuntime = document.querySelector('meta[name="30gogo-local"]')?.content === "1";
      if (localRuntime) {
        const response = await fetch("/__local/private-data", { cache: "no-store" });
        if (!response.ok) throw new Error("local data unavailable");
        const payload = await response.json();
        finishUnlock(payload, null);
        return;
      }

      const response = await fetch(`portfolio.vault.json?v=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error("vault unavailable");
      envelope = await response.json();
      document.getElementById("vaultUpdated").textContent = envelope.generatedAt
        ? `암호화 스냅샷 ${new Date(envelope.generatedAt).toLocaleString("ko-KR")}`
        : "";
      await autoUnlock();
    } catch {
      showError();
    }
  }

  ["pointerdown", "keydown", "touchstart"].forEach((name) => document.addEventListener(name, resetIdleTimer, { passive: true }));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") return;
    if (document.body.classList.contains("vault-locked") && deviceKey) resumeFromDeviceKey();
    else resetIdleTimer();
  });

  window.VaultLock = { start, lockCurrentDevice: deleteDeviceKey };
})();
