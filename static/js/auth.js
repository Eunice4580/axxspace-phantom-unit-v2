/**
 * auth.js — shared token helpers used by login.html and member.js
 */

const TOKEN_KEY  = 'axxspace_member_token';
const NAME_KEY   = 'axxspace_member_name';
const ID_KEY     = 'axxspace_member_id';

function getToken()    { return localStorage.getItem(TOKEN_KEY); }
function getMemberName(){ return localStorage.getItem(NAME_KEY); }
function getMemberId() { return localStorage.getItem(ID_KEY); }
function isLoggedIn()  { return !!getToken(); }

function saveSession(data) {
  localStorage.setItem(TOKEN_KEY, data.token);
  localStorage.setItem(NAME_KEY,  data.name);
  localStorage.setItem(ID_KEY,    String(data.contributor_id));
}

function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(NAME_KEY);
  localStorage.removeItem(ID_KEY);
}

function doLogout() {
  clearSession();
  window.location.href = '/login';
}

/** POST /api/members/login  — throws Error on failure */
async function authLogin(email, password) {
  const res = await fetch('/api/members/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || 'Login failed.');
  saveSession(data);
  return data;
}

/** POST /api/members/register  — throws Error on failure */
async function authRegister(name, email, password, category) {
  const res = await fetch('/api/members/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, email, password, category }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || 'Registration failed.');
  saveSession(data);
  return data;
}

/** GET /api/members/me with Bearer token — throws on 401 */
async function fetchMemberProfile() {
  const token = getToken();
  if (!token) throw new Error('Not authenticated.');
  const res = await fetch('/api/members/me', {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (res.status === 401) {
    clearSession();
    window.location.href = '/login';
    throw new Error('Session expired.');
  }
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || 'Failed to load profile.');
  return data;
}

/* ── Toast ──────────────────────────────────────────────────────────── */
function showToast(msg, type = 'success') {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.className = `toast show ${type}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 3200);
}
