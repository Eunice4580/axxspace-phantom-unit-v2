/**
 * member.js — powers the /member personal dashboard page
 *
 * Redirects to /login if no token is found. Fetches the member profile
 * from GET /api/members/me and renders all stats, chart and ledger.
 */

(async function () {
  // Guard: redirect to login if not authenticated
  if (!isLoggedIn()) {
    window.location.href = '/login';
    return;
  }

  let profile;
  try {
    profile = await fetchMemberProfile();
  } catch (err) {
    showToast(err.message, 'error');
    return;
  }

  // Hide skeleton, show content
  document.getElementById('loading-state').style.display  = 'none';
  document.getElementById('member-content').style.display = 'block';

  /* ── Welcome banner ───────────────────────────────────────── */
  document.getElementById('welcome-name').textContent =
    '👋 Hello, ' + profile.name;
  document.getElementById('welcome-email').textContent =
    profile.email || 'Member';
  document.getElementById('badge-category').textContent = profile.category;
  document.getElementById('badge-rank').textContent =
    profile.rank > 0 ? `#${profile.rank} Rank` : 'Unranked';
  document.getElementById('badge-units').textContent =
    `${profile.total_units} Units`;

  /* ── Stat cards ───────────────────────────────────────────── */
  document.getElementById('stat-units').textContent  = profile.total_units.toFixed(1);
  document.getElementById('stat-value').textContent  = `€${profile.total_value_eur.toFixed(2)}`;
  document.getElementById('stat-awards').textContent = profile.ledger.length;
  document.getElementById('stat-rank').textContent   =
    profile.rank > 0 ? `#${profile.rank}` : '—';

  /* ── Growth chart ─────────────────────────────────────────── */
  const ctx = document.getElementById('memberGrowthChart').getContext('2d');

  if (profile.growth_points.length === 0) {
    ctx.canvas.parentElement.innerHTML +=
      '<p class="muted" style="text-align:center;padding:2rem">No awards yet — your chart will appear here once you receive your first units.</p>';
    ctx.canvas.style.display = 'none';
  } else {
    new Chart(ctx, {
      type: 'line',
      data: {
        labels: profile.growth_points.map(p => p.date),
        datasets: [{
          label: 'Cumulative Units',
          data: profile.growth_points.map(p => p.cumulative_units),
          borderColor: '#6366f1',
          backgroundColor: 'rgba(99,102,241,.12)',
          borderWidth: 2.5,
          pointBackgroundColor: '#6366f1',
          pointRadius: 4,
          pointHoverRadius: 7,
          fill: true,
          tension: 0.45,
        }],
      },
      options: {
        responsive: true,
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: '#1e1e2e',
            borderColor: '#6366f1',
            borderWidth: 1,
            callbacks: {
              label: ctx => ` ${ctx.parsed.y.toFixed(1)} units`,
            },
          },
        },
        scales: {
          x: {
            ticks: { color: '#6b7280', font: { size: 11 } },
            grid:  { color: 'rgba(255,255,255,.05)' },
          },
          y: {
            beginAtZero: true,
            ticks: { color: '#6b7280', font: { size: 11 } },
            grid:  { color: 'rgba(255,255,255,.05)' },
          },
        },
      },
    });
  }

  /* ── Personal ledger table ────────────────────────────────── */
  const ledgerCount = document.getElementById('ledger-count');
  const tbody       = document.getElementById('ledger-body');
  const emptyMsg    = document.getElementById('empty-ledger');
  const table       = document.getElementById('ledger-table');

  ledgerCount.textContent = `${profile.ledger.length} ${profile.ledger.length === 1 ? 'entry' : 'entries'}`;

  if (profile.ledger.length === 0) {
    table.style.display   = 'none';
    emptyMsg.style.display = 'block';
  } else {
    profile.ledger.forEach(entry => {
      const date = new Date(entry.date_awarded).toLocaleDateString('en-GB', {
        day: '2-digit', month: 'short', year: 'numeric',
      });
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${date}</td>
        <td>${escHtml(entry.task_description)}</td>
        <td>${entry.task_reference ? escHtml(entry.task_reference) : '<span class="muted">—</span>'}</td>
        <td><strong style="color:#34d399">${entry.units_awarded.toFixed(1)}</strong></td>
        <td>€${entry.value_eur.toFixed(2)}</td>
        <td>${escHtml(entry.approving_reviewer)}</td>
        <td>${entry.remarks ? escHtml(entry.remarks) : '<span class="muted">—</span>'}</td>
      `;
      tbody.appendChild(tr);
    });
  }
})();

function escHtml(str) {
  const d = document.createElement('div');
  d.appendChild(document.createTextNode(str));
  return d.innerHTML;
}
