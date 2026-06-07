// Public dashboard: pool stats, growth charts and the contribution ledger.

const COLORS = [
  "#6d8bff", "#36d6c3", "#f0a020", "#ef5a5a", "#a78bfa",
  "#38c172", "#ff8fab", "#5ad1ff", "#ffd166", "#c0c8e0",
];

function eur(n) {
  return "€" + Number(n).toLocaleString("en-IE", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}
function fmtUnits(n) {
  return Number(n).toLocaleString("en-IE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}
function fmtDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

async function getJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

function renderStats(s) {
  const grid = document.getElementById("stat-grid");
  grid.innerHTML = `
    <div class="stat">
      <div class="label">Allocated Units</div>
      <div class="value">${fmtUnits(s.allocated_units)} <span style="font-size:0.9rem;color:var(--text-dim)">/ ${fmtUnits(s.total_pool_units)}</span></div>
      <div class="sub">${fmtUnits(s.allocated_pct)}% of the pool awarded</div>
      <div class="progress"><span style="width:${Math.min(100, s.allocated_pct)}%"></span></div>
    </div>
    <div class="stat">
      <div class="label">Remaining Units</div>
      <div class="value">${fmtUnits(s.remaining_units)}</div>
      <div class="sub">${eur(s.remaining_units * s.eur_per_unit)} available to award</div>
    </div>
    <div class="stat">
      <div class="label">Allocated Value</div>
      <div class="value">${eur(s.allocated_value_eur)}</div>
      <div class="sub">of ${eur(s.total_pool_value_eur)} total reference value</div>
    </div>
    <div class="stat">
      <div class="label">Accounts</div>
      <div class="value">${s.contributor_count}</div>
      <div class="sub">${s.award_count} award${s.award_count === 1 ? "" : "s"} recorded</div>
    </div>`;
}

const chartBase = {
  responsive: true,
  maintainAspectRatio: true,
  plugins: { legend: { labels: { color: "#9aa6c0", boxWidth: 12 } } },
  scales: {
    x: { ticks: { color: "#9aa6c0" }, grid: { color: "#243049" } },
    y: { ticks: { color: "#9aa6c0" }, grid: { color: "#243049" }, beginAtZero: true },
  },
};

function renderOverall(growth) {
  const ctx = document.getElementById("overallChart");
  const labels = growth.overall.map((p) => fmtDate(p.date));
  const data = growth.overall.map((p) => p.cumulative_units);
  new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Cumulative Units (all accounts)",
        data,
        borderColor: "#6d8bff",
        backgroundColor: "rgba(109,139,255,0.18)",
        fill: true, tension: 0.3, pointRadius: 3, borderWidth: 2,
      }],
    },
    options: chartBase,
  });
}

function renderPerContributor(growth) {
  const ctx = document.getElementById("perContribChart");
  // Union of all dates across contributors for a shared x-axis.
  const dateSet = new Set();
  growth.per_contributor.forEach((c) => c.points.forEach((p) => dateSet.add(p.date)));
  const dates = Array.from(dateSet).sort();
  const datasets = growth.per_contributor.map((c, i) => {
    const map = Object.fromEntries(c.points.map((p) => [p.date, p.cumulative_units]));
    let last = 0;
    const series = dates.map((d) => { if (d in map) last = map[d]; return last; });
    const color = COLORS[i % COLORS.length];
    return { label: c.name, data: series, borderColor: color, backgroundColor: color, tension: 0.3, pointRadius: 2, borderWidth: 2 };
  });
  new Chart(ctx, {
    type: "line",
    data: { labels: dates.map(fmtDate), datasets },
    options: chartBase,
  });
}

function renderHoldings(contributors) {
  const ctx = document.getElementById("holdingsChart");
  const sorted = [...contributors].sort((a, b) => b.total_units - a.total_units);
  new Chart(ctx, {
    type: "bar",
    data: {
      labels: sorted.map((c) => c.name),
      datasets: [{
        label: "Units Held",
        data: sorted.map((c) => c.total_units),
        backgroundColor: sorted.map((_, i) => COLORS[i % COLORS.length]),
        borderRadius: 6,
      }],
    },
    options: { ...chartBase, plugins: { legend: { display: false } } },
  });
}

function renderLedger(entries) {
  document.getElementById("ledger-count").textContent =
    `${entries.length} ${entries.length === 1 ? "entry" : "entries"}`;
  const body = document.getElementById("ledger-body");
  if (!entries.length) {
    body.innerHTML = `<tr><td colspan="8" style="color:var(--text-dim);text-align:center;padding:24px">No awards recorded yet.</td></tr>`;
    return;
  }
  body.innerHTML = entries.map((e) => `
    <tr>
      <td>${fmtDate(e.date_awarded)}</td>
      <td>${escapeHtml(e.contributor_name)}</td>
      <td>${escapeHtml(e.task_description)}</td>
      <td>${e.task_reference ? escapeHtml(e.task_reference) : "—"}</td>
      <td class="units">${fmtUnits(e.units_awarded)}</td>
      <td>${eur(e.value_eur)}</td>
      <td>${escapeHtml(e.approving_reviewer)}</td>
      <td>${e.remarks ? escapeHtml(e.remarks) : "—"}</td>
    </tr>`).join("");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function toast(msg, ok = true) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.className = "toast show " + (ok ? "good" : "bad");
  setTimeout(() => (t.className = "toast"), 3200);
}

async function load() {
  try {
    const [stats, growth, contributors, ledger] = await Promise.all([
      getJSON("/api/stats"),
      getJSON("/api/growth"),
      getJSON("/api/contributors"),
      getJSON("/api/ledger"),
    ]);
    renderStats(stats);
    renderOverall(growth);
    renderPerContributor(growth);
    renderHoldings(contributors);
    renderLedger(ledger);
  } catch (err) {
    console.error(err);
    toast("Failed to load dashboard data.", false);
  }
}

load();
