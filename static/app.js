// clientctl — frontend
// Reads /api/apps/list to render the grid and /api/capabilities to hide
// features the running system does not support. Polling cadence:
// apps 1.5s, battery 5s, sysinfo 2s, lock 3s.

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => r.querySelectorAll(s);

// ── Themes ───────────────────────────────────────────────────────────
// To add a custom theme: define a [data-theme="name"] block in style.css
// AND register it here with a label + two preview swatch colors.

// Themes are loaded dynamically from /api/themes (which reads themes.yml
// on the server). Picker rebuilds itself once the response arrives.
let THEMES = [];                        // [{id, label, preview: {...}}]
const THEME_KEY     = "clientctl-theme";
const DEFAULT_THEME = "dark";

async function loadThemes() {
  try {
    const res = await fetch("/api/themes", { cache: "no-store" });
    if (!res.ok) return;
    const d = await res.json();
    const ids     = d.themes  || [];
    const labels  = d.labels  || {};
    const previews = d.previews || {};
    THEMES = ids.map(id => {
      const p = previews[id] || {};
      return {
        id,
        label: labels[id] || id,
        preview: {
          bg:     p.surface || p.bg     || "#1a1a20",
          border: p.border  || "#34343f",
          text:   p.text    || "#f0f0f5",
          accent: p.accent  || "#5a8dee",
          // Build a soft glow at 22% from the accent. CSS color-mix is
          // available in modern Safari/Chrome/Firefox.
          glow:   `color-mix(in srgb, ${p.accent || "#5a8dee"} 22%, transparent)`,
        },
      };
    });
    // Synthesize an "auto" entry that follows prefers-color-scheme. Built
    // client-side because it has no palette of its own — picks dark or
    // light at runtime from the OS.
    THEMES.push({
      id:    "auto",
      label: "Auto",
      preview: {
        bg:     "linear-gradient(135deg, #0d0d10 0 50%, #f5f5f7 50% 100%)",
        border: "#5a8dee",
        text:   "#8a8a96",
        accent: "#5a8dee",
        glow:   "color-mix(in srgb, #5a8dee 22%, transparent)",
      },
    });
    if (d.default) applyTheme(getTheme()); // re-paint pressed-state
    if ($("#theme-picker")) renderThemePicker();
  } catch (e) {
    console.warn("themes load failed:", e);
  }
}

function getTheme() {
  try { return localStorage.getItem(THEME_KEY) || DEFAULT_THEME; }
  catch { return DEFAULT_THEME; }
}

// Live media-query for the auto theme. Recreated whenever applyTheme
// runs so we don't accumulate stale listeners across selections.
let _autoMq      = null;
let _autoHandler = null;

function applyTheme(name) {
  // Strip any previous auto-listener so picking a different theme doesn't
  // leave a zombie OS-preference handler firing in the background.
  if (_autoMq && _autoHandler) {
    _autoMq.removeEventListener("change", _autoHandler);
    _autoMq = null; _autoHandler = null;
  }

  const allowed = new Set(THEMES.map(t => t.id));
  if (!allowed.has(name)) name = DEFAULT_THEME;
  try { localStorage.setItem(THEME_KEY, name); } catch {}

  if (name === "auto") {
    _autoMq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      document.documentElement.dataset.theme = _autoMq.matches ? "dark" : "light";
    };
    _autoHandler = apply;
    _autoMq.addEventListener("change", apply);
    apply();
  } else {
    document.documentElement.dataset.theme = name;
  }

  // Re-paint pressed-state on picker buttons
  $$("#theme-picker .theme-btn").forEach(btn => {
    btn.setAttribute("aria-pressed", btn.dataset.theme === name ? "true" : "false");
  });
}

function renderThemePicker() {
  const picker = $("#theme-picker");
  if (!picker) return;
  picker.innerHTML = "";
  const current = getTheme();
  for (const t of THEMES) {
    const btn = document.createElement("button");
    btn.className = "theme-btn";
    btn.dataset.theme = t.id;
    btn.setAttribute("aria-pressed", t.id === current ? "true" : "false");
    btn.setAttribute("title", t.label);
    // Inline custom properties drive the live preview — each card is
    // painted in the colors of the theme it represents.
    const p = t.preview;
    btn.style.setProperty("--tb-bg",     p.bg);
    btn.style.setProperty("--tb-border", p.border);
    btn.style.setProperty("--tb-text",   p.text);
    btn.style.setProperty("--tb-accent", p.accent);
    btn.style.setProperty("--tb-glow",   p.glow);
    btn.innerHTML = `
      <span class="theme-swatch" aria-hidden="true"></span>
      <span class="theme-name"></span>
    `;
    btn.querySelector(".theme-name").textContent = t.label;
    btn.addEventListener("click", () => applyTheme(t.id));
    picker.appendChild(btn);
  }
}

// Apply on page load (the <head> bootstrap already set data-theme;
// here we kick off the async theme-list fetch so the picker can render).
applyTheme(getTheme());
loadThemes();

const loginScreen   = $("#login");
const appScreen     = $("#app");
const screenLock    = $("#screen-lock");
const codeInput     = $("#code-input");
const loginBtn      = $("#login-btn");
const loginError    = $("#login-error");
const lockBtn       = $("#lock-btn");
const toast         = $("#toast");
const pingEl        = $("#ping");

const volumeBtn       = $("#volume-btn");
const volumeDropdown  = $("#volume-dropdown");
const volumeRow       = $("#volume-row");
const volumeMute      = $("#volume-mute");
const volumeSlider    = $("#volume-slider");
const volumeValue     = $("#volume-value");

const brightnessBtn       = $("#brightness-btn");
const brightnessDropdown  = $("#brightness-dropdown");
const brightnessContainer = $("#brightness-bars");
const brightnessTpl       = $("#brightness-bar-tpl");

const gridContainer = $("#grid");
const cellAppTpl    = $("#cell-app-tpl");
const cellCachyTpl  = $("#cell-cachy-tpl");
const statsRow      = $("#stats");

const dropdowns = [];
let capabilities = {};

// Inline data-URL fallback for the Cachy-Update cell. Used when the server
// is unreachable (e.g. after server-kill) so the cell stays visually intact
// instead of showing a broken-image icon. Data URLs survive server death
// because they don't require a network round-trip.
const CACHY_FALLBACK_ICON =
  "data:image/svg+xml;utf8," + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#8a8a96">' +
    '<path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16zM12 4.15L18.04 7.5 12 11 5.96 7.5 12 4.15zM5 9.21l6 3.46v7.13l-6-3.43V9.21zm8 10.59v-7.13l6-3.46v7.16l-6 3.43z"/>' +
    "</svg>"
  );

// WebAuthn (passkey API) is only available in secure contexts:
// HTTPS, localhost, 127.0.0.1, ::1. On plain LAN HTTP this is undefined.
// We use this to gate every passkey button so users don't get a cryptic
// "navigator.credentials is undefined" error on click.
const WEBAUTHN_AVAILABLE = !!(
  window.isSecureContext &&
  window.PublicKeyCredential &&
  navigator.credentials &&
  typeof navigator.credentials.get === "function" &&
  typeof navigator.credentials.create === "function"
);

// ── Toast ────────────────────────────────────────────────

const TOAST_ICONS = {
  success: '<path d="M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>',
  error:   '<path d="M11 15h2v2h-2zm0-8h2v6h-2zm.99-5C6.47 2 2 6.48 2 12s4.47 10 9.99 10C17.52 22 22 17.52 22 12S17.52 2 11.99 2zM12 20c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z"/>',
  info:    '<path d="M11 7h2v2h-2zm0 4h2v6h-2zm1-9C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8z"/>',
};

// ── Custom confirm modal ─────────────────────────────────
// Replaces window.confirm() with a styled, theme-aware popup that matches
// the rest of the UI. Returns a Promise<boolean>.

function confirmModal({ title, message, confirmText = "Confirm", cancelText = "Cancel", danger = false } = {}) {
  return new Promise((resolve) => {
    const modal = document.createElement("div");
    modal.className = "modal confirm-modal";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.innerHTML = `
      <div class="modal-card">
        <h2 class="confirm-title"></h2>
        <p class="modal-message"></p>
        <div class="modal-actions">
          <button class="secondary confirm-cancel"></button>
          <button class="confirm-ok"></button>
        </div>
      </div>
    `;
    modal.querySelector(".confirm-title").textContent   = title;
    modal.querySelector(".modal-message").textContent   = message;
    const cancelBtn = modal.querySelector(".confirm-cancel");
    const okBtn     = modal.querySelector(".confirm-ok");
    cancelBtn.textContent = cancelText;
    okBtn.textContent     = confirmText;
    if (danger) okBtn.classList.add("danger");

    const close = (result) => {
      document.removeEventListener("keydown", onKey, true);
      modal.remove();
      resolve(result);
    };
    const onKey = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); close(false); }
      if (e.key === "Enter")  { e.stopPropagation(); close(true);  }
    };

    cancelBtn.addEventListener("click", () => close(false));
    okBtn.addEventListener("click",     () => close(true));
    modal.addEventListener("click", (e) => { if (e.target === modal) close(false); });
    document.addEventListener("keydown", onKey, true);

    document.body.appendChild(modal);
    setTimeout(() => okBtn.focus(), 50);
  });
}

let toastTimer = null;
function showToast(msg, kind = "info") {
  if (!["success","error","info"].includes(kind)) kind = "info";
  toast.innerHTML =
    `<svg class="toast-icon" viewBox="0 0 24 24" aria-hidden="true">${TOAST_ICONS[kind]}</svg>` +
    `<span class="toast-text"></span>`;
  toast.querySelector(".toast-text").textContent = msg;
  toast.className = "toast " + kind;
  void toast.offsetHeight;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 1800);
}

// ── API ──────────────────────────────────────────────────

async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 204) return { ok: true };
  return res.json();
}

let lastStatus = { authed: false, screen_locked: false, passkey_count: 0 };

async function fetchStatus() {
  try {
    const res = await fetch("/api/status", { credentials: "same-origin", cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

function applyAuthState(data) {
  lastStatus = data || lastStatus;
  const hasPasskeys     = (data?.passkey_count || 0) > 0;
  const passkeyUsable   = hasPasskeys && WEBAUTHN_AVAILABLE;
  const showInsecure    = hasPasskeys && !WEBAUTHN_AVAILABLE;

  if (!data?.authed) {
    appScreen.classList.add("hidden");
    screenLock.classList.add("hidden");
    loginScreen.classList.remove("hidden");
    $("#login-passkey-btn").hidden    = !passkeyUsable;
    $("#login-insecure-hint").hidden  = !showInsecure;
    // Stop every polling timer — no point hitting the server while we
    // sit on the login card. They restart from initApp() after auth.
    stopAllPolling();
    initialized = false;
    setTimeout(() => codeInput.focus(), 80);
    return;
  }

  // Authed: keep watching for screen-lock state changes from KDE.
  startLockPolling();
  loginScreen.classList.add("hidden");
  if (data.screen_locked) {
    appScreen.classList.add("hidden");
    screenLock.classList.remove("hidden");
    $("#unlock-passkey-btn").hidden    = !passkeyUsable;
    $("#unlock-insecure-hint").hidden  = !showInsecure;
    if (passkeyUsable) {
      $("#screen-lock-sub").textContent = "PC is locked. Unlock with your passkey.";
    } else if (showInsecure) {
      $("#screen-lock-sub").textContent = "PC is locked.";
    } else {
      $("#screen-lock-sub").textContent =
        "PC is locked. Unlock with code or physically at the PC.";
    }
  } else {
    screenLock.classList.add("hidden");
    appScreen.classList.remove("hidden");
    initApp();
  }
}

async function checkAuth() {
  const data = await fetchStatus();
  applyAuthState(data || { authed: false });
}

// ── Capabilities ─────────────────────────────────────────

async function loadCapabilities() {
  try {
    const res = await fetch("/api/capabilities", { cache: "no-store" });
    if (!res.ok) return;
    capabilities = await res.json();
  } catch {}
  applyCapabilities();
}

function applyCapabilities() {
  $$("[data-cap]").forEach((el) => {
    const cap = el.dataset.cap;
    let val = capabilities[cap];
    if (cap === "brightness") val = capabilities.kde_brightness || capabilities.ddc;
    if (val === false || val === "none" || val === undefined) {
      el.hidden = true;
    } else {
      el.hidden = false;
    }
  });

  // Version + repo link in the bottom-right footer (and settings dropdown)
  const v = capabilities.version;
  if (v) {
    const tag = "v" + v;
    const badge = $("#app-version");
    if (badge) badge.textContent = tag;
    const inSettings = $("#settings-version");
    if (inSettings) inSettings.textContent = tag;
  }
  const footer = $("#app-footer");
  const repo   = $("#app-repo");
  const repoUrl = (capabilities.repo_url || "").trim();
  if (repo) {
    if (repoUrl) {
      repo.href = repoUrl;
      repo.hidden = false;
    } else {
      repo.removeAttribute("href");
      repo.hidden = true;
    }
  }
  // Footer is shown as long as we have a version to display
  if (footer && v) footer.hidden = false;
}

// ── Login ────────────────────────────────────────────────

codeInput.addEventListener("input", (e) => {
  let v = e.target.value.replace(/\D/g, "").slice(0, 6);
  if (v.length > 3) v = v.slice(0, 3) + " " + v.slice(3);
  e.target.value = v;
  loginError.innerHTML = "&nbsp;";
});

codeInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") loginBtn.click();
});

loginBtn.addEventListener("click", async () => {
  const code = codeInput.value.replace(/\s/g, "");
  if (code.length < 6) { loginError.textContent = "Enter all 6 digits"; return; }
  loginBtn.disabled = true;
  const remember = !!$("#remember-input")?.checked;
  try {
    const res = await api("/api/login", { body: { code, remember } });
    if (res.ok) {
      codeInput.value = "";
      loginError.innerHTML = "&nbsp;";
      await checkAuth();
    } else {
      loginError.textContent = res.error || "Login failed";
    }
  } finally {
    loginBtn.disabled = false;
  }
});

// ── Lock ─────────────────────────────────────────────────

lockBtn.addEventListener("click", async () => {
  const reqPromise = api("/api/lock");
  showToast("Locking screen", "info");
  setTimeout(checkAuth, 600);
  setTimeout(checkAuth, 1500);
  const res = await reqPromise;
  if (!res.ok) showToast(res.error || "Lock failed", "error");
});

// ── System buttons ───────────────────────────────────────

const notifBtn      = $("#notif-btn");
const powerBtn      = $("#power-btn");
const shutdownBtn   = $("#shutdown-btn");
const serverKillBtn = $("#server-kill-btn");
const logoutBtn     = $("#logout-btn");

function _updateNotifVisuals(inhibited) {
  const inh = inhibited ? "true" : "false";
  if (notifBtn) notifBtn.dataset.inhibited = inh;
  const t = $("#notif-toggle-btn");
  if (t) t.dataset.inhibited = inh;
  const hint = $("#notif-toggle-hint");
  if (hint) hint.hidden = !inhibited;
}

async function refreshNotifState() {
  try {
    const res = await fetch("/api/notif/state", { credentials: "same-origin", cache: "no-store" });
    if (!res.ok) return;
    const d = await res.json();
    _updateNotifVisuals(!!d.inhibited);
  } catch {}
}

// ── Battery ──────────────────────────────────────────────

// Pure renderer — accepts a status object as-is (from SSE push or from
// the polling fetch). Stays free of network code so both paths share it.
function _renderBattery(d) {
  const el = $("#battery");
  if (!el || !d) return;
  if (!d.present) { el.hidden = true; return; }
  el.hidden = false;
  $("#battery-text").textContent = d.percent + "%";

  let state = d.state || "discharging";
  if (state === "discharging") {
    if      (d.percent <= 5)  state = "empty";
    else if (d.percent <= 20) state = "low";
  }
  el.dataset.state = state;

  const fill = el.querySelector(".battery-fill");
  if (fill) {
    const pct   = Math.max(0, Math.min(100, d.percent));
    const total = 14;
    const h     = total * pct / 100;
    fill.setAttribute("y",      String(6 + (total - h)));
    fill.setAttribute("height", String(h));
  }
}

async function refreshBatteryState() {
  // Skip the fetch when SSE is delivering this — saves one request every
  // 5 seconds on every connected client. Polling resumes automatically
  // when SSE is dropped (sse.connected goes back to false on error).
  if (sse.connected) return;
  try {
    const res = await fetch("/api/battery", { credentials: "same-origin", cache: "no-store" });
    if (!res.ok) return;
    _renderBattery(await res.json());
  } catch {}
}

let batteryTimer = null;
function startBatteryPolling() {
  refreshBatteryState();
  clearInterval(batteryTimer);
  batteryTimer = setInterval(refreshBatteryState, 5000);
}

// ── Sysinfo (CPU / RAM / GPU / NET) — stats row ─────────

function _fmtBps(bps) {
  if (bps < 1024) return bps + " B/s";
  if (bps < 1024 * 1024) return Math.round(bps / 1024) + " KB/s";
  return (bps / 1048576).toFixed(1) + " MB/s";
}

function _setStatLevel(el, pct) {
  if (pct >= 90) el.dataset.level = "crit";
  else if (pct >= 70) el.dataset.level = "high";
  else el.removeAttribute("data-level");
}

function _setStat(id, pct) {
  const el  = $("#stat-" + id);
  const val = $("#stat-" + id + "-val");
  const bar = $("#stat-" + id + "-bar");
  if (!el) return;
  el.hidden = false;
  if (val) val.textContent = pct + "%";
  if (bar) bar.style.width = Math.max(0, Math.min(100, pct)) + "%";
  _setStatLevel(el, pct);
}

function _renderSysinfo(d) {
  if (!d) return;
  if (typeof d.cpu === "number") _setStat("cpu", d.cpu);
  if (typeof d.mem === "number") _setStat("mem", d.mem);

  // GPU pill stays visible; "—" if not readable
  const gpuEl = $("#stat-gpu");
  if (gpuEl) {
    if (typeof d.gpu === "number") {
      gpuEl.removeAttribute("data-empty");
      _setStat("gpu", d.gpu);
    } else {
      gpuEl.dataset.empty = "true";
      $("#stat-gpu-val").textContent = "—";
      $("#stat-gpu-bar").style.width = "0%";
      gpuEl.removeAttribute("data-level");
    }
  }

  if (typeof d.procs === "number") {
    $("#stat-procs-val").textContent = d.procs;
  }
  if (d.net) {
    $("#stat-net-val").textContent = "↓ " + _fmtBps(d.net.rx) + "   ↑ " + _fmtBps(d.net.tx);
  }
  statsRow.hidden = false;
}

async function refreshSysinfo() {
  // SSE delivers this every 2s. Skip the parallel poll when it's live.
  if (sse.connected) return;
  try {
    const res = await fetch("/api/sysinfo", { credentials: "same-origin", cache: "no-store" });
    if (!res.ok) return;
    _renderSysinfo(await res.json());
  } catch {}
}

let sysinfoTimer = null;
function startSysinfoPolling() {
  refreshSysinfo();
  clearInterval(sysinfoTimer);
  sysinfoTimer = setInterval(refreshSysinfo, 2000);
}

// ── Power profile ────────────────────────────────────────

async function refreshPowerState() {
  try {
    const res = await fetch("/api/power/state", { credentials: "same-origin" });
    if (!res.ok) return;
    const d = await res.json();
    if (powerBtn) powerBtn.dataset.profile = d.profile || "balanced";
  } catch {}
}

const POWER_LABELS = {
  "power-saver": "Power saver",
  "balanced":    "Balanced",
  "performance": "Performance",
};
powerBtn?.addEventListener("click", async () => {
  const res = await api("/api/power/cycle");
  if (res.ok) {
    powerBtn.dataset.profile = res.profile;
    showToast(POWER_LABELS[res.profile] || res.profile, "success");
  } else {
    showToast(res.error || "Error", "error");
  }
});

shutdownBtn?.addEventListener("click", async () => {
  const ok = await confirmModal({
    title:       "Shut down?",
    message:     "The PC will power off after the system dialog confirms.",
    confirmText: "Shut down",
    danger:      true,
  });
  if (!ok) return;
  const res = await api("/api/shutdown");
  if (res.ok) showToast("Shutdown dialog opened", "success");
  else        showToast(res.error || "Error", "error");
});

serverKillBtn?.addEventListener("click", async () => {
  const ok = await confirmModal({
    title:       "Stop clientctl server?",
    message:     "The server and its Cloudflare tunnel will both shut down. " +
                 "You'll need physical access to the PC to start clientctl again.",
    confirmText: "Stop server",
    danger:      true,
  });
  if (!ok) return;
  await api("/api/server/kill");
  showToast("Server stopped — connection lost", "");
  // Stop every polling interval so we don't keep firing requests at a
  // dead server (which would also re-trigger the cachy icon fallback
  // every 30s and the lock-state poll every 3s).
  for (const t of [pingTimer, batteryTimer, sysinfoTimer, appStateTimer,
                   cachyTimer, lockPollTimer, _notifLiveTimer, _audioLiveTimer]) {
    if (t) clearInterval(t);
  }
  setTimeout(() => {
    appScreen.classList.add("hidden");
    pingEl.dataset.state = "bad";
    pingEl.textContent = "off";
  }, 200);
});

logoutBtn?.addEventListener("click", async () => {
  const ok = await confirmModal({
    title:       "Sign out?",
    message:     "You'll need to enter the code or use a passkey to sign back in.",
    confirmText: "Sign out",
  });
  if (!ok) return;
  await api("/api/logout");
  document.cookie = "session=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; SameSite=Lax";
  stopAllPolling();
  initialized = false;
  showToast("Signed out", "success");
  setTimeout(() => checkAuth(), 200);
});

// ── Notifications dropdown ───────────────────────────────

const notifDropdown = $("#notif-dropdown");
const notifList     = $("#notif-list");
const notifClearBtn = $("#notif-clear-btn");
const notifToggle   = $("#notif-toggle-btn");

dropdowns.push({ btn: notifBtn, menu: notifDropdown });

notifBtn?.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleDropdown(notifBtn, notifDropdown);
});

function _fmtNotifTime(ts) {
  const now = Date.now() / 1000;
  const diff = Math.max(0, now - ts);
  if (diff < 60)    return "now";
  if (diff < 3600)  return Math.floor(diff / 60) + " min";
  if (diff < 86400) return Math.floor(diff / 3600) + " h";
  return Math.floor(diff / 86400) + " d";
}

async function refreshNotifList() {
  try {
    const res = await fetch("/api/notif/list", { credentials: "same-origin" });
    if (!res.ok) return;
    const d = await res.json();
    const items = d.notifications || [];
    if (!items.length) {
      notifList.innerHTML = '<div class="notif-empty">No new notifications</div>';
      notifClearBtn.hidden = true;
      return;
    }
    notifClearBtn.hidden = false;
    notifList.innerHTML = "";
    for (const n of items) {
      const item = document.createElement("div");
      item.className = "notif-item";
      item.innerHTML = `
        <div class="notif-item-head">
          <span class="notif-item-app"></span>
          <span class="notif-item-time"></span>
        </div>
        <div class="notif-item-summary"></div>
        <div class="notif-item-body"></div>
      `;
      $(".notif-item-app",     item).textContent = n.app || "—";
      $(".notif-item-time",    item).textContent = _fmtNotifTime(n.ts);
      $(".notif-item-summary", item).textContent = n.summary || "";
      $(".notif-item-body",    item).textContent = n.body    || "";
      if (!n.body) $(".notif-item-body", item).remove();
      notifList.appendChild(item);
    }
  } catch {}
}

notifToggle?.addEventListener("click", async (e) => {
  e.stopPropagation();
  const res = await api("/api/notif/toggle");
  if (res.ok) {
    _updateNotifVisuals(!!res.inhibited);
    showToast(res.inhibited ? "Do not disturb on" : "Notifications back on", "success");
  }
});

notifClearBtn?.addEventListener("click", async (e) => {
  e.stopPropagation();
  await api("/api/notif/clear");
  refreshNotifList();
});

// ── Slider helper ────────────────────────────────────────

function paintSlider(slider) {
  const min = +slider.min || 0;
  const max = +slider.max || 100;
  const val = +slider.value;
  const pct = ((val - min) / (max - min)) * 100;
  slider.style.setProperty("--pct", pct + "%");
}

// ── Dropdown logic ───────────────────────────────────────

if (volumeBtn && volumeDropdown)
  dropdowns.push({ btn: volumeBtn, menu: volumeDropdown });
if (brightnessBtn && brightnessDropdown)
  dropdowns.push({ btn: brightnessBtn, menu: brightnessDropdown });

function closeDropdowns(except = null) {
  for (const { btn, menu } of dropdowns) {
    if (menu === except) continue;
    menu.hidden = true;
    btn.setAttribute("aria-expanded", "false");
  }
}

let _notifLiveTimer = null;
let _audioLiveTimer = null;

function toggleDropdown(btn, menu) {
  const open = !menu.hidden;
  clearInterval(_notifLiveTimer); _notifLiveTimer = null;
  clearInterval(_audioLiveTimer); _audioLiveTimer = null;

  if (open) {
    menu.hidden = true;
    btn.setAttribute("aria-expanded", "false");
  } else {
    closeDropdowns(menu);
    menu.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    if (menu === brightnessDropdown) loadDisplays();
    if (menu === volumeDropdown) {
      loadVolume();
      loadAudioStreams();
      _audioLiveTimer = setInterval(loadAudioStreams, 2000);
    }
    if (menu.id === "notif-dropdown") {
      refreshNotifState();
      refreshNotifList();
      _notifLiveTimer = setInterval(refreshNotifList, 1500);
    }
  }
}

volumeBtn?.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleDropdown(volumeBtn, volumeDropdown);
});

brightnessBtn?.addEventListener("click", (e) => {
  e.stopPropagation();
  toggleDropdown(brightnessBtn, brightnessDropdown);
});

document.addEventListener("click", (e) => {
  for (const { menu } of dropdowns) {
    if (!menu.hidden && !menu.contains(e.target)) {
      closeDropdowns();
      return;
    }
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDropdowns();
});

// ── Volume ───────────────────────────────────────────────

let volumeSendTimer = null;
function debouncedVolumeSet(v) {
  clearTimeout(volumeSendTimer);
  volumeSendTimer = setTimeout(async () => {
    const res = await api("/api/volume", { body: { volume: v } });
    if (res.ok) syncVolume(res);
  }, 80);
}

// Track active drag per slider — without this, the thumb snaps back to
// the previous value during the server roundtrip while the user is still
// dragging.
let volumeDragging = false;
volumeSlider?.addEventListener("pointerdown",   () => volumeDragging = true);
volumeSlider?.addEventListener("pointerup",     () => volumeDragging = false);
volumeSlider?.addEventListener("pointercancel", () => volumeDragging = false);
volumeSlider?.addEventListener("touchstart",    () => volumeDragging = true,  { passive: true });
volumeSlider?.addEventListener("touchend",      () => volumeDragging = false, { passive: true });
volumeSlider?.addEventListener("touchcancel",   () => volumeDragging = false, { passive: true });

function syncVolume(state) {
  if (!state) return;
  if (typeof state.volume === "number" && !volumeDragging) {
    volumeSlider.value = state.volume;
    volumeValue.textContent = state.volume + "%";
    paintSlider(volumeSlider);
  }
  const muted = state.muted ? "true" : "false";
  volumeRow.dataset.muted   = muted;
  volumeMute.dataset.muted  = muted;
  volumeBtn.dataset.muted   = muted;
}

async function loadVolume() {
  const res = await fetch("/api/volume", { credentials: "same-origin" });
  if (res.ok) syncVolume(await res.json());
}

// ── Per-app audio streams ────────────────────────────────

const audioStreamsContainer = $("#audio-streams");
const streamSendTimers = new Map();
let streamDragging = false;   // any stream slider currently dragged

async function loadAudioStreams() {
  if (!audioStreamsContainer) return;
  // Don't re-render while dragging — would break the active drag
  if (streamDragging) return;
  try {
    const res = await fetch("/api/audio/streams", { credentials: "same-origin", cache: "no-store" });
    if (!res.ok) return;
    const d = await res.json();
    const streams = d.streams || [];

    // Index existing rows — avoids full DOM rebuild
    const existing = new Map();
    for (const row of audioStreamsContainer.querySelectorAll(".audio-stream")) {
      existing.set(row.dataset.id, row);
    }

    const seen = new Set();
    for (const s of streams) {
      const sid = String(s.id);
      seen.add(sid);
      let row = existing.get(sid);
      if (!row) {
        row = document.createElement("div");
        row.className = "audio-stream";
        row.dataset.id = sid;
        row.innerHTML = `
          <button class="audio-stream-mute" aria-label="Mute">
            <svg class="i-vol"  viewBox="0 0 24 24"><path d="M3 10v4a1 1 0 001 1h3l4 4V5L7 9H4a1 1 0 00-1 1zm13 2a4 4 0 00-2-3.46v6.92A4 4 0 0016 12z"/></svg>
          </button>
          <span class="audio-stream-name"></span>
          <input type="range" class="slider" min="0" max="100" value="${s.volume}">
          <span class="ctrl-value">${s.volume}%</span>
        `;
        const slider  = $(".slider", row);
        const valueEl = $(".ctrl-value", row);
        const muteBtn = $(".audio-stream-mute", row);

        const setDrag = (v) => () => streamDragging = v;
        slider.addEventListener("pointerdown",   setDrag(true));
        slider.addEventListener("pointerup",     setDrag(false));
        slider.addEventListener("pointercancel", setDrag(false));
        slider.addEventListener("touchstart",    setDrag(true),  { passive: true });
        slider.addEventListener("touchend",      setDrag(false), { passive: true });
        slider.addEventListener("touchcancel",   setDrag(false), { passive: true });

        slider.addEventListener("input", () => {
          const v = +slider.value;
          valueEl.textContent = v + "%";
          paintSlider(slider);
          clearTimeout(streamSendTimers.get(s.id));
          streamSendTimers.set(s.id, setTimeout(async () => {
            await api(`/api/audio/stream/${s.id}`, { body: { volume: v } });
          }, 80));
        });
        muteBtn.addEventListener("click", async (e) => {
          e.stopPropagation();
          row.dataset.muted = row.dataset.muted === "true" ? "false" : "true";
          await api(`/api/audio/stream/${s.id}`, { body: { mute: "toggle" } });
        });
        audioStreamsContainer.appendChild(row);
      }
      // Update values (only if not currently dragging this slider)
      $(".audio-stream-name", row).textContent = s.name;
      row.dataset.muted = s.muted ? "true" : "false";
      const slider  = $(".slider", row);
      const valueEl = $(".ctrl-value", row);
      if (document.activeElement !== slider) {
        slider.value = s.volume;
        valueEl.textContent = s.volume + "%";
        paintSlider(slider);
      }
    }
    // Remove streams that disappeared
    for (const [sid, row] of existing) {
      if (!seen.has(sid)) row.remove();
    }
  } catch {}
}

volumeSlider?.addEventListener("input", () => {
  const v = +volumeSlider.value;
  volumeValue.textContent = v + "%";
  paintSlider(volumeSlider);
  debouncedVolumeSet(v);
});

volumeMute?.addEventListener("click", async (e) => {
  e.stopPropagation();
  const res = await api("/api/volume", { body: { mute: "toggle" } });
  if (res.ok) syncVolume(res);
});

// ── Brightness ───────────────────────────────────────────

const brightnessTimers = new Map();

function makeBrightnessRow(d) {
  const node = brightnessTpl.content.firstElementChild.cloneNode(true);
  const slider = $(".slider", node);
  const value  = $(".ctrl-value", node);
  const name   = $(".display-name", node);

  slider.value = d.brightness;
  slider.dataset.id = d.id;
  value.textContent = d.brightness + "%";
  name.textContent = d.name || d.id;
  paintSlider(slider);

  slider.addEventListener("input", () => {
    const v = +slider.value;
    value.textContent = v + "%";
    paintSlider(slider);
    clearTimeout(brightnessTimers.get(d.id));
    brightnessTimers.set(d.id, setTimeout(async () => {
      const res = await api(`/api/brightness/${d.id}`, { body: { brightness: v } });
      if (!res.ok) showToast(res.error || "Brightness change failed", "error");
    }, 100));
  });
  return node;
}

async function loadDisplays() {
  const res = await fetch("/api/displays", { credentials: "same-origin" });
  if (!res.ok) return;
  const data = await res.json();
  brightnessContainer.innerHTML = "";
  for (const d of (data.displays || [])) {
    brightnessContainer.appendChild(makeBrightnessRow(d));
  }
  if (!(data.displays || []).length) {
    const empty = document.createElement("div");
    empty.style.cssText = "padding: 14px; color: var(--muted); font-size: 13px; text-align: center;";
    empty.textContent = "no display detected";
    brightnessContainer.appendChild(empty);
  }
}

// ── Ping ─────────────────────────────────────────────────
//
// What "ping" means here:
//   - Round-trip time of an authenticated GET /api/ping (HTTP/1.1+ keep-alive
//     after the first sample, so we measure mostly net + TLS-resume + Flask
//     dispatch — no DNS/handshake jitter on every probe).
//   - Each tick takes ONE sample. The displayed number is the median of
//     the last 3 samples to smooth out one-off jitter, and the tooltip
//     shows the spread (max − min) so connection quality is legible.
//
// Three-tier classification beats binary good/bad: a 50ms LAN connection
// and a 180ms tunnel both fit "good" by the old 120ms threshold, but they
// feel very different. New cuts: <60 good, <200 ok, ≥200 bad.

let pingTimer = null;
const PING_HISTORY = [];
const PING_HISTORY_LEN = 3;
const PING_TIMEOUT_MS  = 3000;

function _pingState(median) {
  if (median == null) return "bad";
  if (median <  60)   return "good";
  if (median < 200)   return "ok";
  return "bad";
}

function _median(arr) {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2);
}

async function measurePing() {
  // AbortController gives us a hard timeout; without it, a dropped
  // tunnel can hang the fetch for ~30s before the browser gives up,
  // so the user sees a stale "32 ms" while the server is actually gone.
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), PING_TIMEOUT_MS);
  // Cache-bust query: even with `cache: "no-store"` some intermediaries
  // (service workers, HTTP/3 0-RTT replays) can return a cached 204.
  const url  = `/api/ping?t=${Date.now()}`;
  const t0   = performance.now();
  try {
    const res = await fetch(url, {
      cache: "no-store",
      credentials: "same-origin",
      signal: ctrl.signal,
    });
    if (!res.ok && res.status !== 204) throw new Error("status " + res.status);
    const ms = Math.round(performance.now() - t0);
    PING_HISTORY.push(ms);
    if (PING_HISTORY.length > PING_HISTORY_LEN) PING_HISTORY.shift();
  } catch {
    // On failure we don't push to the history; instead we surface the
    // outage immediately so the user sees the connection problem.
    PING_HISTORY.length = 0;
    pingEl.textContent  = "—";
    pingEl.dataset.state = "bad";
    pingEl.title = "no response within " + (PING_TIMEOUT_MS / 1000) + "s";
    return;
  } finally {
    clearTimeout(timer);
  }

  const med = _median(PING_HISTORY);
  pingEl.textContent  = med + " ms";
  pingEl.dataset.state = _pingState(med);
  // Tooltip shows the spread so the user can tell a steady 80ms from
  // a flaky 80ms (jitter ±200).
  const lo = Math.min(...PING_HISTORY);
  const hi = Math.max(...PING_HISTORY);
  pingEl.title = PING_HISTORY.length < 2
    ? `${med} ms`
    : `${med} ms · last ${PING_HISTORY.length} samples ${lo}–${hi} ms (jitter ${hi - lo})`;
}

function startPing() {
  PING_HISTORY.length = 0;
  measurePing();
  clearInterval(pingTimer);
  pingTimer = setInterval(measurePing, 2000);
}

// ── Grid (rendered from /api/apps/list) ─────────────────

let gridCells = [];

async function loadGrid() {
  try {
    const res = await fetch("/api/apps/list", { credentials: "same-origin", cache: "no-store" });
    if (!res.ok) return;
    const d = await res.json();
    gridCells = d.cells || [];
    renderGrid();
  } catch {}
}

function renderGrid() {
  gridContainer.innerHTML = "";
  for (const c of gridCells) {
    const tpl = c.type === "cachy" ? cellCachyTpl : cellAppTpl;
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.dataset.app = c.id;
    if (c.type === "app") {
      $(".cell-label", node).textContent = c.name;
      node.setAttribute("aria-label", "Open " + c.name);
      $(".cell-icon", node).src = `/api/app/${c.id}/icon?t=${Date.now()}`;
    } else if (c.type === "cachy") {
      // Cachy icon is refreshed every 30s — if the server dies between
      // ticks we'd otherwise get a broken-image. Fall back to a local
      // data URL on any load error.
      const icon = $(".cell-icon", node);
      icon.src = CACHY_FALLBACK_ICON;     // initial value before first refresh
      icon.addEventListener("error", () => { icon.src = CACHY_FALLBACK_ICON; });
    }
    attachCellHandlers(node, c);
    gridContainer.appendChild(node);
  }
}

function attachCellHandlers(cell, info) {
  cell.addEventListener("click", async () => {
    if (info.type === "cachy") {
      const res = await api("/api/cachy/run");
      if (res.ok) showToast("Cachy-Update opened", "success");
      else        showToast(res.error || "Launch failed", "error");
      return;
    }
    const res = await api(`/api/app/${info.id}/toggle`);
    if (res.ok) {
      const word = res.action === "launched" ? "launched" : "toggled";
      showToast(`${res.name} ${word}`, "success");
      refreshAppStates();
    } else {
      showToast(res.error || "Error", "error");
    }
  });
  if (info.type === "app") {
    setupLongPress(cell, () => openActionMenu(cell));
  }
}

// ── Long-press ───────────────────────────────────────────

function setupLongPress(el, onLong) {
  let timer = null;
  let triggered = false;
  let startXY = null;

  const start = (e) => {
    triggered = false;
    const t = e.touches ? e.touches[0] : e;
    startXY = { x: t.clientX, y: t.clientY };
    timer = setTimeout(() => {
      triggered = true;
      timer = null;
      if (navigator.vibrate) navigator.vibrate(15);
      onLong(e);
    }, 500);
  };
  const cancel = () => { if (timer) { clearTimeout(timer); timer = null; } };
  const move = (e) => {
    if (!startXY) return;
    const t = e.touches ? e.touches[0] : e;
    if (Math.hypot(t.clientX - startXY.x, t.clientY - startXY.y) > 10) cancel();
  };

  el.addEventListener("touchstart", start, { passive: true });
  el.addEventListener("touchmove",  move,  { passive: true });
  el.addEventListener("touchend",   cancel, { passive: true });
  el.addEventListener("touchcancel", cancel, { passive: true });
  el.addEventListener("mousedown",  start);
  el.addEventListener("mousemove",  move);
  el.addEventListener("mouseup",    cancel);
  el.addEventListener("mouseleave", cancel);
  el.addEventListener("contextmenu", (e) => e.preventDefault());

  el.addEventListener("click", (e) => {
    if (triggered) {
      e.stopPropagation();
      e.preventDefault();
      triggered = false;
    }
  }, true);
}

// ── Action menu ──────────────────────────────────────────

const actionMenu     = $("#action-menu");
const actionBackdrop = $("#action-menu-backdrop");
const actionTitle    = $("#action-menu-title");
const actionPauseLbl = $("#action-pause-label");
let   actionTarget   = null;

const PAUSE_PATH    = "M6 4h4v16H6zm8 0h4v16h-4z";
const PLAY_PATH     = "M8 5v14l11-7z";
// Minimize: a horizontal bar near the centre. Restore: an outlined window.
const MINIMIZE_PATH = "M20 14H4v-2h16v2z";
const RESTORE_PATH  = "M4 4h16v16H4V4zm2 4v10h12V8H6z";

async function openActionMenu(cell) {
  const id = cell.dataset.app;
  if (!id) return;
  const res = await fetch(`/api/app/${id}/status`, { credentials: "same-origin" });
  if (!res.ok) return;
  const st = await res.json();

  if (!st.running) { showToast(`${st.name} is not running`); return; }

  actionTarget = id;
  actionTitle.textContent = st.name;
  actionPauseLbl.textContent = st.paused ? "Resume" : "Pause";
  const pausePath = $("#action-pause-path");
  if (pausePath) pausePath.setAttribute("d", st.paused ? PLAY_PATH : PAUSE_PATH);

  // Window state: visible → user can minimize, minimized → user can restore.
  const winLbl  = $("#action-window-label");
  const winPath = $("#action-window-path");
  if (winLbl)  winLbl.textContent  = st.visible ? "Minimize" : "Restore";
  if (winPath) winPath.setAttribute("d", st.visible ? MINIMIZE_PATH : RESTORE_PATH);

  actionMenu.hidden = false;
  actionBackdrop.hidden = false;
}

function closeActionMenu() {
  actionTarget = null;
  actionMenu.hidden = true;
  actionBackdrop.hidden = true;
}

actionBackdrop.addEventListener("click", closeActionMenu);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !actionMenu.hidden) closeActionMenu();
});

$$(".action-menu-item", actionMenu).forEach((btn) => {
  btn.addEventListener("click", async () => {
    const act = btn.dataset.act;
    const id = actionTarget;
    if (!id) return;
    // The "window" action piggybacks on the existing /toggle endpoint —
    // KWin's _TOGGLE_JS already minimises if any window is visible and
    // restores otherwise, exactly the semantics we want here.
    const wasVisible = $("#action-window-label")?.textContent === "Minimize";
    closeActionMenu();
    const path = act === "window" ? "toggle" : act;
    const res  = await api(`/api/app/${id}/${path}`);
    if (res.ok) {
      const labels = {
        close:  "closed",
        pause:  res.action === "resumed" ? "resumed" : "paused",
        kill:   "killed",
        window: wasVisible ? "minimized" : "restored",
      };
      showToast(`${res.name} ${labels[act] || ""}`, "success");
      refreshAppStates();
    } else {
      showToast(res.error || "Error", "error");
    }
  });
});

// ── App state polling ────────────────────────────────────

let appStateTimer = null;

function _appState(st) {
  if (!st.running) return "off";
  if (st.paused)   return "paused";
  if (st.visible)  return "active";
  return "background";
}

async function refreshAppStates() {
  try {
    const res = await fetch("/api/apps/status", { credentials: "same-origin", cache: "no-store" });
    if (!res.ok) return;
    const d = await res.json();
    if (!d.apps) return;
    for (const cell of $$(".cell-app")) {
      const st = d.apps[cell.dataset.app];
      if (!st) continue;
      cell.dataset.appState = _appState(st);
      cell.dataset.paused   = st.paused ? "true" : "false";
      cell.dataset.running  = st.running ? "true" : "false";
    }
  } catch {}
}

function startAppStatePolling() {
  refreshAppStates();
  clearInterval(appStateTimer);
  appStateTimer = setInterval(refreshAppStates, 1500);
}

// ── Cachy cell ───────────────────────────────────────────

let cachyTimer = null;
async function refreshCachy() {
  if (!capabilities.cachy) return;
  const cachyIcon = $("#cachy-icon");
  if (cachyIcon) cachyIcon.src = `/api/cachy/icon?t=${Date.now()}`;
  try {
    const res  = await fetch("/api/cachy/state", { credentials: "same-origin", cache: "no-store" });
    const data = await res.json();
    const cell = document.querySelector('[data-action="cachy"]');
    if (data.ok && cell) cell.dataset.state = data.available ? "available" : "ok";
  } catch {}
}

function startCachyPolling() {
  if (!capabilities.cachy) return;
  refreshCachy();
  clearInterval(cachyTimer);
  cachyTimer = setInterval(refreshCachy, 30_000);
}

// ── Init after login ─────────────────────────────────────

let initialized = false;
async function initApp() {
  if (initialized) return;
  initialized = true;
  await loadCapabilities();
  await loadGrid();
  // Preload everything that's behind a dropdown — they'll feel instant
  // when the user opens them. Network calls run in parallel; ddcutil can
  // be slow but we don't block on it.
  Promise.allSettled([
    loadVolume(),
    loadAudioStreams(),
    loadDisplays(),
    refreshNotifState(),
    refreshPowerState(),
    refreshBatteryState(),
    refreshSysinfo(),
  ]);
  startPing();
  startCachyPolling();
  startAppStatePolling();
  // Sysinfo + battery + lock state come via SSE on /api/events; the
  // matching polling loops act as fallback when the EventSource isn't
  // yet connected (or the browser has no support).
  openEventStream();
  startBatteryPolling();
  startSysinfoPolling();
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && initialized) {
    loadVolume();
    refreshCachy();
    refreshAppStates();
    refreshNotifState();
    refreshPowerState();
  }
});

// ── WebAuthn / passkey ───────────────────────────────────

function _b64urlToBuf(s) {
  s = (s || "").replace(/-/g, "+").replace(/_/g, "/");
  s += "=".repeat((4 - s.length % 4) % 4);
  const bin = atob(s);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return buf.buffer;
}

function _bufToB64url(buf) {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function passkeyRegister(name, password) {
  const beginRes = await fetch("/api/passkey/register/begin", {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, password }),
  });
  if (!beginRes.ok) {
    const err = await beginRes.json().catch(() => ({}));
    throw new Error(err.error || "Failed to start registration");
  }
  const opts = await beginRes.json();
  const token = opts._token;

  const publicKey = {
    ...opts,
    challenge: _b64urlToBuf(opts.challenge),
    user: { ...opts.user, id: _b64urlToBuf(opts.user.id) },
    excludeCredentials: (opts.excludeCredentials || []).map(c => ({
      ...c, id: _b64urlToBuf(c.id),
    })),
  };
  delete publicKey._token;

  const cred = await navigator.credentials.create({ publicKey });
  const credPayload = {
    _token: token,
    id: cred.id,
    rawId: _bufToB64url(cred.rawId),
    type: cred.type,
    response: {
      attestationObject: _bufToB64url(cred.response.attestationObject),
      clientDataJSON:    _bufToB64url(cred.response.clientDataJSON),
    },
    clientExtensionResults: cred.getClientExtensionResults(),
  };

  const finishRes = await fetch("/api/passkey/register/finish", {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(credPayload),
  });
  const data = await finishRes.json();
  if (!finishRes.ok || !data.ok) throw new Error(data.error || "Verification failed");
  return data;
}

async function passkeyAuthenticate() {
  const beginRes = await fetch("/api/passkey/auth/begin", {
    method: "POST", credentials: "same-origin",
  });
  if (!beginRes.ok) {
    const err = await beginRes.json().catch(() => ({}));
    throw new Error(err.error || "Failed to start auth");
  }
  const opts = await beginRes.json();
  const token = opts._token;

  const publicKey = {
    ...opts,
    challenge: _b64urlToBuf(opts.challenge),
    allowCredentials: (opts.allowCredentials || []).map(c => ({
      ...c, id: _b64urlToBuf(c.id),
    })),
  };
  delete publicKey._token;

  const cred = await navigator.credentials.get({ publicKey });
  const credPayload = {
    _token: token,
    id: cred.id,
    rawId: _bufToB64url(cred.rawId),
    type: cred.type,
    response: {
      authenticatorData: _bufToB64url(cred.response.authenticatorData),
      clientDataJSON:    _bufToB64url(cred.response.clientDataJSON),
      signature:         _bufToB64url(cred.response.signature),
      userHandle:        cred.response.userHandle ? _bufToB64url(cred.response.userHandle) : null,
    },
    clientExtensionResults: cred.getClientExtensionResults(),
  };

  const finishRes = await fetch("/api/passkey/auth/finish", {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(credPayload),
  });
  const data = await finishRes.json();
  if (!finishRes.ok || !data.ok) throw new Error(data.error || "Verification failed");
  return data;
}

$("#login-passkey-btn")?.addEventListener("click", async () => {
  loginError.textContent = "";
  try {
    await passkeyAuthenticate();
    showToast("Signed in", "success");
    await checkAuth();
  } catch (e) {
    loginError.textContent = e.message || "Error";
  }
});

$("#unlock-passkey-btn")?.addEventListener("click", async () => {
  $("#unlock-error").textContent = "";
  try {
    await passkeyAuthenticate();
    showToast("Unlocked", "success");
    await checkAuth();
  } catch (e) {
    $("#unlock-error").textContent = e.message || "Error";
  }
});

$("#unlock-code-btn")?.addEventListener("click", async () => {
  document.cookie = "session=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; SameSite=Lax";
  await checkAuth();
});

// ── Settings dropdown ────────────────────────────────────

const settingsBtn      = $("#settings-btn");
const settingsDropdown = $("#settings-dropdown");
const passkeyList      = $("#passkey-list");
const passkeyAddBtn    = $("#passkey-add-btn");
const passkeyCount     = $("#passkey-count");
const passkeyModal     = $("#passkey-modal");

if (settingsBtn && settingsDropdown) {
  dropdowns.push({ btn: settingsBtn, menu: settingsDropdown });
  settingsBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleDropdown(settingsBtn, settingsDropdown);
    if (!settingsDropdown.hidden) {
      refreshPasskeys();
      renderThemePicker();   // (re-)build chips so the active state is fresh
    }
  });
}

async function refreshPasskeys() {
  const res = await fetch("/api/passkey/list", { credentials: "same-origin" });
  if (!res.ok) return;
  const d = await res.json();
  passkeyCount.textContent = `${d.count}/${d.max}`;

  // Add button is disabled if any of:
  //   - quota reached
  //   - server has no PASSKEY_REGISTRATION_PASSWORD configured
  //   - browser context is insecure (no WebAuthn API)
  const regEnabled = d.registration_enabled !== false;
  const quotaOk    = d.count < d.max;
  passkeyAddBtn.disabled = !regEnabled || !quotaOk || !WEBAUTHN_AVAILABLE;

  const hint = $("#passkey-disabled-hint");
  if (!WEBAUTHN_AVAILABLE) {
    hint.hidden = false;
    hint.innerHTML =
      'Passkeys require HTTPS. Open clientctl via your tunnel or ' +
      '<code>localhost</code> to enable registration.';
  } else if (!regEnabled) {
    hint.hidden = false;
    hint.innerHTML =
      'Registration disabled. Set <code>PASSKEY_REGISTRATION_PASSWORD</code> ' +
      'in <code>.env</code> and restart the server to enable.';
  } else {
    hint.hidden = true;
  }

  passkeyList.innerHTML = "";
  if (!d.passkeys.length) {
    const empty = document.createElement("div");
    empty.className = "passkey-empty";
    empty.textContent = "No passkey registered yet";
    passkeyList.appendChild(empty);
    return;
  }
  for (const p of d.passkeys) {
    const item = document.createElement("div");
    item.className = "passkey-item";
    item.innerHTML = `
      <div class="passkey-info">
        <span class="passkey-name"></span>
        <span class="passkey-meta"></span>
      </div>
      <button class="passkey-delete" aria-label="Delete">
        <svg viewBox="0 0 24 24"><path d="M6 19a2 2 0 002 2h8a2 2 0 002-2V7H6zM19 4h-3.5l-1-1h-5l-1 1H5v2h14z"/></svg>
      </button>
    `;
    $(".passkey-name", item).textContent = p.name || "—";
    // Production-safe device identification: date + time + MAC if we
    // could read it from /proc/net/arp at register time, else compact
    // UA summary as fallback (tunneled clients aren't on our L2).
    const fmtDateTime = (sec) => new Date(sec * 1000).toLocaleString([], {
      year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
    const when  = fmtDateTime(p.created || 0);
    const ident = p.mac || p.ua || p.ip || "";
    // Sign-in stats: server-side counter (independent of WebAuthn's
    // sign_count, which Apple/Hello pin to 0 by spec).
    const used = p.use_count
      ? `${p.use_count}× · last ${fmtDateTime(p.last_used)}`
      : "never used";
    const head = ident ? `${when} · ${ident}` : when;
    $(".passkey-meta", item).innerHTML =
      `${head}<br><span class="passkey-uses">${used}</span>`;
    $(".passkey-delete", item).addEventListener("click", async () => {
      const ok = await confirmModal({
        title:       `Delete passkey "${p.name}"?`,
        message:     "This device will no longer be able to sign in or unlock " +
                     "without re-registering. The setup password will be required.",
        confirmText: "Delete",
        danger:      true,
      });
      if (!ok) return;
      await api("/api/passkey/delete", { body: { id: p.id } });
      refreshPasskeys();
    });
    passkeyList.appendChild(item);
  }
}

passkeyAddBtn?.addEventListener("click", () => {
  $("#passkey-name-input").value = "";
  $("#passkey-pw-input").value = "";
  $("#passkey-modal-error").innerHTML = "&nbsp;";
  passkeyModal.hidden = false;
  setTimeout(() => $("#passkey-name-input").focus(), 50);
});

$("#passkey-cancel-btn")?.addEventListener("click", () => {
  passkeyModal.hidden = true;
});

$("#passkey-confirm-btn")?.addEventListener("click", async () => {
  const name = $("#passkey-name-input").value.trim() || "Device";
  const pw   = $("#passkey-pw-input").value;
  const errEl = $("#passkey-modal-error");
  errEl.textContent = "";
  try {
    const res = await passkeyRegister(name, pw);
    showToast(`Passkey "${res.name}" created`, "success");
    passkeyModal.hidden = true;
    refreshPasskeys();
  } catch (e) {
    errEl.textContent = e.message || "Error";
  }
});

// ── Periodic lock-state polling ──────────────────────────

let lockPollTimer = null;
function startLockPolling() {
  clearInterval(lockPollTimer);
  lockPollTimer = setInterval(async () => {
    // SSE pushes lock-state changes; only fall back to polling when the
    // stream is down. Keeps an auth-validity check on the server-side
    // session even when nothing is changing.
    if (sse.connected) return;
    const data = await fetchStatus();
    if (!data) return;
    if (data.authed !== lastStatus.authed ||
        data.screen_locked !== lastStatus.screen_locked) {
      applyAuthState(data);
    } else {
      lastStatus = data;
    }
  }, 3000);
}

function stopAllPolling() {
  for (const t of [pingTimer, batteryTimer, sysinfoTimer, appStateTimer,
                   cachyTimer, lockPollTimer, _notifLiveTimer, _audioLiveTimer]) {
    if (t) clearInterval(t);
  }
  pingTimer = batteryTimer = sysinfoTimer = appStateTimer =
    cachyTimer = lockPollTimer = _notifLiveTimer = _audioLiveTimer = null;
  closeEventStream();
}

// ── Server-Sent Events — live state push ─────────────────────────
//
// Replaces the sysinfoTimer / batteryTimer / lockPollTimer loops with a
// single long-lived HTTP connection. EventSource has built-in reconnect,
// so we don't carry our own retry logic.
//
// If EventSource isn't available (very old Safari) or the connection
// keeps failing, the polling loops in initApp() are still in place as a
// fallback — sse.connected gates whether they get cleared.

const sse = { es: null, connected: false };

function closeEventStream() {
  if (sse.es) {
    try { sse.es.close(); } catch {}
    sse.es = null;
  }
  sse.connected = false;
}

function openEventStream() {
  if (!window.EventSource) return;            // ancient browser fallback
  closeEventStream();
  const es = new EventSource("/api/events");
  sse.es = es;
  es.addEventListener("open", () => { sse.connected = true; });
  es.addEventListener("error", () => { sse.connected = false; });
  es.addEventListener("sysinfo", (ev) => {
    try { _renderSysinfo(JSON.parse(ev.data)); } catch {}
  });
  es.addEventListener("battery", (ev) => {
    try { _renderBattery(JSON.parse(ev.data)); } catch {}
  });
  es.addEventListener("lock", (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (data.screen_locked !== lastStatus.screen_locked) {
        // Lock-state changed — re-fetch full status to redraw the panel.
        fetchStatus().then(s => s && applyAuthState(s));
      } else {
        lastStatus = { ...lastStatus, ...data };
      }
    } catch {}
  });
}

// Service worker — runs only on secure contexts (HTTPS or localhost).
// Errors are swallowed: if the SW can't register, the panel still works
// fine, just without the offline shell.
if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => { /* ignore */ });
}

checkAuth();
