/**
 * Organization management + tier display
 */
import { authFetch } from './api.js';
import { API } from './utils.js';

let _tierCache = null;

export async function fetchTierStatus() {
  try {
    const res = await authFetch(API + '/me/org');
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
      counter.textContent = '';
      counter.classList.add('hidden');
    } else {
      counter.textContent = status.remaining_questions + '/5 remaining';
      counter.classList.remove('hidden');
      counter.className = 'daily-counter' + (status.remaining_questions <= 1 ? ' warn' : '');
    }
  }

  const orgName = document.getElementById('org-name');
  if (orgName) {
    orgName.textContent = status.organization ? status.organization.org_name : '';
    orgName.classList.toggle('hidden', !status.organization);
  }

  // Show/hide lock icons
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

export function showJoinModal() {
  const modal = document.getElementById('org-modal');
  if (modal) modal.classList.remove('hidden');
}

export function hideJoinModal() {
  const modal = document.getElementById('org-modal');
  if (modal) modal.classList.add('hidden');
  const input = document.getElementById('invite-code-input');
  if (input) input.value = '';
  const err = document.getElementById('join-error');
  if (err) err.textContent = '';
}

export async function joinOrg() {
  const input = document.getElementById('invite-code-input');
  const err = document.getElementById('join-error');
  const code = (input?.value || '').trim().toUpperCase();

  if (!/^[A-Z0-9]{8}$/.test(code)) {
    if (err) err.textContent = 'Invalid code format (8 alphanumeric chars)';
    return;
  }

  try {
    const res = await authFetch(API + '/me/org/join', {
      method: 'POST',
      body: JSON.stringify({ invite_code: code }),
    });
    const data = await res.json();
    if (!res.ok) {
      if (err) err.textContent = data.detail || 'Failed to join';
      return;
    }
    hideJoinModal();
    await updateTierUI();
  } catch (e) {
    if (err) err.textContent = 'Network error';
  }
}

export async function leaveOrg() {
  if (!confirm('Leave this organization? You will lose Pro access.')) return;
  try {
    const res = await authFetch(API + '/me/org/leave', { method: 'POST' });
    if (res.ok) await updateTierUI();
  } catch {}
}
