/**
 * Invite code redemption + tier display
 */
import { authFetch } from './api.js';
import { API } from './utils.js';

let _tierCache = null;

export async function fetchTierStatus() {
  try {
    const res = await authFetch(API + '/me/pro');
    if (!res.ok) return null;
    _tierCache = await res.json();
    return _tierCache;
  } catch { return null; }
}

export function getCachedTier() { return _tierCache; }

export async function updateTierUI() {
  const status = await fetchTierStatus();
  if (!status) return;

  const badge = document.getElementById('tier-badge');
  if (badge) {
    badge.textContent = status.tier.toUpperCase();
    badge.className = 'tier-badge tier-' + status.tier;
  }

  const counter = document.getElementById('daily-counter');
  if (counter) {
    if (status.remaining_questions === null) {
      counter.textContent = 'Unlimited';
      counter.classList.remove('hidden');
      counter.className = 'daily-counter';
    } else {
      const limit = status.limits?.daily_questions || 10;
      counter.textContent = status.remaining_questions + '/' + limit + ' remaining today';
      counter.classList.remove('hidden');
      counter.className = 'daily-counter' + (status.remaining_questions <= 2 ? ' warn' : '');
    }
  }

  const proInfo = document.getElementById('org-name');
  if (proInfo) {
    if (status.pro) {
      const exp = new Date(status.pro.expires_at);
      proInfo.textContent = 'Pro until ' + exp.toLocaleDateString('zh-TW');
      proInfo.classList.remove('hidden');
    } else {
      proInfo.textContent = '';
      proInfo.classList.add('hidden');
    }
  }

  _updateLockIcons(status.tier);
}

function _updateLockIcons(tier) {
  document.querySelectorAll('[data-pro-only]').forEach(el => {
    const lock = el.querySelector('.lock-icon');
    if (tier === 'pro') {
      if (lock) lock.classList.add('hidden');
      el.classList.remove('locked');
    } else {
      if (lock) lock.classList.remove('hidden');
      el.classList.add('locked');
    }
  });
}

export function showRedeemModal() {
  const modal = document.getElementById('org-modal');
  if (modal) modal.classList.remove('hidden');
}

export function hideRedeemModal() {
  const modal = document.getElementById('org-modal');
  if (modal) modal.classList.add('hidden');
  const input = document.getElementById('invite-code-input');
  if (input) input.value = '';
  const err = document.getElementById('join-error');
  if (err) { err.textContent = ''; err.style.display = 'none'; }
}

export async function redeemCode() {
  const input = document.getElementById('invite-code-input');
  const err = document.getElementById('join-error');
  const btn = document.querySelector('#org-modal .btn-primary');
  const code = (input?.value || '').trim().toUpperCase();

  if (err) { err.textContent = ''; err.style.display = 'none'; }

  if (!/^[A-Z0-9]{8}$/.test(code)) {
    if (err) { err.textContent = 'Invalid code format (8 alphanumeric chars)'; err.style.display = 'block'; }
    return;
  }

  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }

  try {
    const res = await authFetch(API + '/me/pro/redeem', {
      method: 'POST',
      body: JSON.stringify({ invite_code: code }),
    });
    const data = await res.json();
    if (!res.ok) {
      if (err) { err.textContent = data.detail || 'Failed to redeem'; err.style.display = 'block'; }
      return;
    }
    hideRedeemModal();
    await updateTierUI();
    _toast('Pro activated!');
  } catch (e) {
    if (err) { err.textContent = 'Network error'; err.style.display = 'block'; }
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'REDEEM'; }
  }
}

function _toast(msg) {
  const t = document.createElement('div');
  t.style.cssText = 'position:fixed;top:20px;right:20px;padding:12px 20px;border-radius:8px;font-family:var(--mono);font-size:13px;z-index:999;background:var(--accent-dim);color:var(--accent);border:1px solid var(--accent);animation:slideIn 0.3s ease;';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity 0.3s'; }, 2500);
  setTimeout(() => t.remove(), 3000);
}
