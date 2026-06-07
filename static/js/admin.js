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
}
function showAdmin() {
  document.getElementById("login-view").classList.add("hidden");
  document.getElementById("admin-view").classList.remove("hidden");
  document.getElementById("logout-link").classList.remove("hidden");
  refreshAll();
}

// --- Config (categories + tiers) --------------------------------------------
let CONFIG = null;
async function loadConfig() {
  CONFIG = await api("/api/config");
  const catSel = document.getElementById("c-category");
  catSel.innerHTML = CONFIG.categories.map((c) => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join("");
  const hint = document.getElementById("tier-hint");
  hint.innerHTML = CONFIG.task_tiers
    .map((t) => `<button type="button" data-min="${t.min}" title="${t.name}: ${t.min}–${t.max}">${t.name} (${t.min}–${t.max})</button>`)
    .join("");
  hint.querySelectorAll("button").forEach((b) =>
    b.addEventListener("click", () => { document.getElementById("a-units").value = b.dataset.min; })
  );
}

// --- Data refresh ------------------------------------------------------------
async function refreshAll() {
  try {
    const [stats, contributors, ledger] = await Promise.all([
      api("/api/stats"), api("/api/contributors"), api("/api/ledger"),
    ]);
    renderStats(stats);
    renderContributorSelect(contributors);
    renderAccounts(contributors);
    renderRecent(ledger.slice(0, 10));
  } catch (err) {
    toast(err.message, false);
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
    .map((c) => `<option value="${c.id}">${escapeHtml(c.name)} — ${fmtUnits(c.total_units)} units</option>`)
    .join("");
}

function renderAccounts(contributors) {
  const body = document.getElementById("accounts-body");
  if (!contributors.length) {
    body.innerHTML = `<tr><td colspan="5" style="text-align:center;color:var(--text-dim);padding:20px">No accounts yet.</td></tr>`;
    return;
  }
  body.innerHTML = contributors.map((c) => `
    <tr>
      <td>${escapeHtml(c.name)}</td>
      <td><span class="pill">${escapeHtml(c.category)}</span></td>
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
    const { token } = await api("/api/auth/login", { method: "POST", body: { password: document.getElementById("password").value } });
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

document.getElementById("contributor-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/contributors", {
      method: "POST", auth: true,
      body: {
        name: document.getElementById("c-name").value,
        email: document.getElementById("c-email").value || null,
        category: document.getElementById("c-category").value,
      },
    });
    e.target.reset();
    toast("Account created.");
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

// --- Boot --------------------------------------------------------------------
(async function init() {
  await loadConfig();
  if (getToken()) showAdmin(); else showLogin();
})();
