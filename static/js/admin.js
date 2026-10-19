// Admin console: login, create accounts, award units.

const TOKEN_KEY = "axxspace_admin_token";

function getToken() { return localStorage.getItem(TOKEN_KEY); }
function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); }

function eur(n) { return "€" + Number(n).toLocaleString("en-IE", { maximumFractionDigits: 2 }); }
function fmtUnits(n) { return Number(n).toLocaleString("en-IE", { minimumFractionDigits: 1, maximumFractionDigits: 1 }); }
function fmtDate(iso) {
  return new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function toast(msg, ok = true) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast show " + (ok ? "good" : "bad");
  setTimeout(() => (t.className = "toast"), 3600);
}

async function api(path, { method = "GET", body, auth = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) headers["Authorization"] = `Bearer ${getToken()}`;
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && auth) { clearToken(); showLogin(); }
    throw new Error(data.detail || `Request failed (${res.status})`);
  }
  return data;
}

// --- View switching ----------------------------------------------------------
function showLogin() {
  document.getElementById("login-view").classList.remove("hidden");
  document.getElementById("admin-view").classList.add("hidden");
  document.getElementById("logout-link").classList.add("hidden");
  stopAutoRefresh();
}
function showAdmin() {
  document.getElementById("login-view").classList.add("hidden");
  document.getElementById("admin-view").classList.remove("hidden");
  document.getElementById("logout-link").classList.remove("hidden");
  refreshAll();
  startAutoRefresh();
}

// --- Auto-refresh ------------------------------------------------------------
const POLL_INTERVAL_MS = 30_000; // poll every 30 seconds
let _pollTimer = null;

function startAutoRefresh() {
  stopAutoRefresh();
  _pollTimer = setInterval(() => {
    // Skip if the tab is hidden — fire immediately when it becomes visible again.
    if (!document.hidden) refreshAll(true);
  }, POLL_INTERVAL_MS);
}

function stopAutoRefresh() {
  if (_pollTimer !== null) { clearInterval(_pollTimer); _pollTimer = null; }
}

// Refresh instantly when the user switches back to this tab.
document.addEventListener("visibilitychange", () => {
  const adminVisible = !document.getElementById("admin-view").classList.contains("hidden");
  if (!document.hidden && getToken() && adminVisible) {
    refreshAll(true);
  }
});

// --- Live indicator ----------------------------------------------------------
function setLiveIndicator(state) {
  // state: 'syncing' | 'live' | 'error'
  const el = document.getElementById("live-indicator");
  if (!el) return;
  el.className = "live-badge " + state;
  el.textContent = state === "syncing" ? "⟳ Syncing…"
                 : state === "error"   ? "⚠ Offline"
                 :                       "● Live";
}

// --- Config (categories + tiers) --------------------------------------------
let CONFIG = null;
async function loadConfig() {
  CONFIG = await api("/api/config");
  const options = CONFIG.categories
    .map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`)
    .join("");
  // Populate both create-account forms
  document.getElementById("m-category").innerHTML = options;
  document.getElementById("i-category").innerHTML = options;
  const hint = document.getElementById("tier-hint");
  hint.innerHTML = CONFIG.task_tiers
    .map((t) => `<button type="button" data-min="${t.min}" title="${t.name}: ${t.min}–${t.max}">${t.name} (${t.min}–${t.max})</button>`)
    .join("");
  hint.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => { document.getElementById("a-units").value = b.dataset.min; })
  );
}

// --- Data refresh ------------------------------------------------------------
async function refreshAll(silent = false) {
  if (!silent) setLiveIndicator("syncing");
  try {
    const [stats, contributors, ledger, submissions] = await Promise.all([
      api("/api/stats"),
      api("/api/contributors"),
      api("/api/ledger"),
      api("/api/submissions?status=pending", { auth: true }),
    ]);
    renderStats(stats);
    renderContributorSelect(contributors);
    renderAccounts(contributors);
    renderRecent(ledger.slice(0, 10));
    renderSubmissions(submissions);
    setLiveIndicator("live");
    const el = document.getElementById("last-refreshed");
    if (el) el.textContent = "Last updated: " + new Date().toLocaleTimeString("en-GB");
  } catch (err) {
    setLiveIndicator("error");
    if (!silent) toast(err.message, false);
  }
}

function renderStats(s) {
  document.getElementById("stat-grid").innerHTML = `
    <div class="stat"><div class="label">Allocated</div><div class="value">${fmtUnits(s.allocated_units)} / ${fmtUnits(s.total_pool_units)}</div>
      <div class="sub">${fmtUnits(s.allocated_pct)}% awarded</div>
      <div class="progress"><span style="width:${Math.min(100, s.allocated_pct)}%"></span></div></div>
    <div class="stat"><div class="label">Remaining</div><div class="value">${fmtUnits(s.remaining_units)}</div>
      <div class="sub">${eur(s.remaining_units * s.eur_per_unit)} left</div></div>
    <div class="stat"><div class="label">Accounts</div><div class="value">${s.contributor_count}</div>
      <div class="sub">${s.award_count} awards</div></div>
    <div class="stat"><div class="label">Allocated Value</div><div class="value">${eur(s.allocated_value_eur)}</div>
      <div class="sub">of ${eur(s.total_pool_value_eur)}</div></div>`;
}

function renderContributorSelect(contributors) {
  const sel = document.getElementById("a-contributor");
  if (!contributors.length) {
    sel.innerHTML = `<option value="" disabled selected>Create an account first</option>`;
    return;
  }
  sel.innerHTML = contributors
    .map((c) => `<option value="${c.id}">${escapeHtml(c.name)} (${c.role}) — ${fmtUnits(c.total_units)} units</option>`)
    .join("");
}

function renderAccounts(contributors) {
  const body = document.getElementById("accounts-body");
  if (!contributors.length) {
    body.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-dim);padding:20px">No accounts yet.</td></tr>`;
    return;
  }
  body.innerHTML = contributors.map((c) => `
    <tr>
      <td>${escapeHtml(c.name)}</td>
      <td><span class="pill">${escapeHtml(c.category)}</span></td>
      <td><span class="pill pill-role pill-${escapeHtml(c.role)}">${escapeHtml(c.role)}</span></td>
      <td>${c.email ? escapeHtml(c.email) : "—"}</td>
      <td class="units">${fmtUnits(c.total_units)}</td>
      <td>${eur(c.total_value_eur)}</td>
    </tr>`).join("");
}

function renderRecent(entries) {
  const body = document.getElementById("recent-body");
  if (!entries.length) {
    body.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-dim);padding:20px">No awards yet.</td></tr>`;
    return;
  }
  body.innerHTML = entries.map((e) => `
    <tr>
      <td>${fmtDate(e.date_awarded)}</td>
      <td>${escapeHtml(e.contributor_name)}</td>
      <td>${escapeHtml(e.task_description)}</td>
      <td>${e.task_reference ? escapeHtml(e.task_reference) : "—"}</td>
      <td class="units">${fmtUnits(e.units_awarded)}</td>
      <td>${escapeHtml(e.approving_reviewer)}</td>
    </tr>`).join("");
}

// --- Event handlers ----------------------------------------------------------
document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const { token } = await api("/api/auth/login", {
      method: "POST",
      body: { password: document.getElementById("password").value },
    });
    setToken(token);
    document.getElementById("password").value = "";
    toast("Logged in.");
    showAdmin();
  } catch (err) {
    toast(err.message, false);
  }
});

document.getElementById("logout-link").addEventListener("click", (e) => {
  e.preventDefault();
  clearToken();
  toast("Logged out.");
  showLogin();
});

// Create member account
document.getElementById("member-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/contributors", {
      method: "POST", auth: true,
      body: {
        name: document.getElementById("m-name").value,
        email: document.getElementById("m-email").value || null,
        category: document.getElementById("m-category").value,
        role: "member",
      },
    });
    e.target.reset();
    toast("Member account created.");
    refreshAll();
  } catch (err) {
    toast(err.message, false);
  }
});

// Create investor account
document.getElementById("investor-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/contributors", {
      method: "POST", auth: true,
      body: {
        name: document.getElementById("i-name").value,
        email: document.getElementById("i-email").value || null,
        category: document.getElementById("i-category").value,
        role: "investor",
      },
    });
    e.target.reset();
    toast("Investor account created.");
    refreshAll();
  } catch (err) {
    toast(err.message, false);
  }
});

document.getElementById("award-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const entry = await api("/api/ledger", {
      method: "POST", auth: true,
      body: {
        contributor_id: Number(document.getElementById("a-contributor").value),
        task_description: document.getElementById("a-task").value,
        task_reference: document.getElementById("a-ref").value || null,
        units_awarded: Number(document.getElementById("a-units").value),
        approving_reviewer: document.getElementById("a-reviewer").value,
        remarks: document.getElementById("a-remarks").value || null,
      },
    });
    e.target.reset();
    toast(`Awarded ${fmtUnits(entry.units_awarded)} units to ${entry.contributor_name}.`);
    refreshAll();
  } catch (err) {
    toast(err.message, false);
  }
});

// --- Submissions -------------------------------------------------------------
function renderSubmissions(submissions) {
  const body  = document.getElementById("submissions-body");
  const count = document.getElementById("submissions-count");
  count.textContent = `${submissions.length} pending`;

  if (!submissions.length) {
    body.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-dim);padding:20px">No pending submissions.</td></tr>`;
    return;
  }

  body.innerHTML = submissions.map((s) => `
    <tr>
      <td>${fmtDate(s.submitted_at)}</td>
      <td>${escapeHtml(s.contributor_name)}</td>
      <td>${escapeHtml(s.task_description)}</td>
      <td>${s.task_reference ? escapeHtml(s.task_reference) : "—"}</td>
      <td>${s.remarks ? escapeHtml(s.remarks) : "—"}</td>
      <td style="white-space:nowrap;">
        <button class="btn-sm btn-award"  onclick="openModal(${s.id},'award','Award units for: ${escapeHtml(s.contributor_name)}','Award units to this member and explain what was verified.')">Award</button>
        <button class="btn-sm btn-done"   onclick="openModal(${s.id},'done','Mark as Done: ${escapeHtml(s.contributor_name)}','Mark this task as done without awarding units. Add a note for the member.')">Done</button>
        <button class="btn-sm btn-cancel" onclick="openModal(${s.id},'cancel','Cancel submission: ${escapeHtml(s.contributor_name)}','Explain to the member why this submission is being cancelled.')">Cancel</button>
      </td>
    </tr>`).join("");
}

// --- Resolve modal -----------------------------------------------------------
let _modalSubmissionId = null;
let _modalAction = null;

function openModal(submissionId, action, title, desc) {
  _modalSubmissionId = submissionId;
  _modalAction = action;

  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-desc").textContent  = desc;
  document.getElementById("modal-note").value = "";
  document.getElementById("modal-units").value = "";
  document.getElementById("modal-reviewer").value = "";

  // Show award-specific fields only when awarding
  const awardExtra = document.getElementById("modal-award-extra");
  awardExtra.classList.toggle("visible", action === "award");

  // Style confirm button by action
  const btn = document.getElementById("modal-confirm-btn");
  btn.className = "btn btn-primary";
  if (action === "cancel") btn.style.background = "rgba(239,68,68,0.7)";
  else if (action === "done") btn.style.background = "rgba(99,102,241,0.7)";
  else btn.style.background = "";

  document.getElementById("resolve-modal").classList.add("open");
  document.getElementById("modal-note").focus();
}

function closeModal() {
  document.getElementById("resolve-modal").classList.remove("open");
  _modalSubmissionId = null;
  _modalAction = null;
}

// Close modal when clicking the backdrop
document.getElementById("resolve-modal").addEventListener("click", (e) => {
  if (e.target === e.currentTarget) closeModal();
});

document.getElementById("modal-confirm-btn").addEventListener("click", async () => {
  const note     = document.getElementById("modal-note").value.trim();
  const units    = parseFloat(document.getElementById("modal-units").value);
  const reviewer = document.getElementById("modal-reviewer").value.trim();

  if (!note) { toast("Please write a short note before confirming.", false); return; }
  if (_modalAction === "award" && (!units || !reviewer)) {
    toast("Units and reviewer are required to award.", false); return;
  }

  const body = { action: _modalAction, admin_note: note };
  if (_modalAction === "award") {
    body.units_awarded = units;
    body.approving_reviewer = reviewer;
  }

  try {
    await api(`/api/submissions/${_modalSubmissionId}/resolve`, {
      method: "POST", auth: true, body,
    });
    closeModal();
    const label = _modalAction === "award" ? "awarded" : _modalAction === "done" ? "marked done" : "cancelled";
    toast(`Submission ${label}.`);
    refreshAll();
  } catch (err) {
    toast(err.message, false);
  }
});

// --- Boot --------------------------------------------------------------------
(async function init() {
  await loadConfig();
  if (getToken()) showAdmin(); else showLogin();
})();
