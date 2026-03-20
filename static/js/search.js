import { authFetch } from './api.js';
import { API, escapeHtml, TYPE_LABELS, TYPE_BADGE_CLASS } from './utils.js';

let searchTimer = null;

export function initSearchUI() {
  const input = document.getElementById('search-input');
  if (!input) return;
  input.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => doSearch(), 300);
  });
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { clearTimeout(searchTimer); doSearch(); }
  });
}

export async function doSearch() {
  const input = document.getElementById('search-input');
  const container = document.getElementById('search-results');
  if (!input || !container) return;
  const q = input.value.trim();
  if (q.length < 2) { container.innerHTML = ''; return; }

  container.innerHTML = '<div style="text-align:center;padding:12px;"><span class="spinner"></span></div>';

  try {
    const res = await authFetch(API + '/questions/search?q=' + encodeURIComponent(q) + '&limit=20');
    if (!res.ok) { container.innerHTML = ''; return; }
    const data = await res.json();
    renderSearchResults(container, data.questions, data.total, q);
  } catch (e) {
    container.innerHTML = '';
  }
}

function highlightMatch(text, query) {
  if (!text || !query) return escapeHtml(text || '');
  const escaped = escapeHtml(text);
  const re = new RegExp('(' + escapeHtml(query).replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
  return escaped.replace(re, '<span class="search-highlight">$1</span>');
}

function renderSearchResults(container, questions, total, query) {
  if (!questions || questions.length === 0) {
    container.innerHTML = `<div class="search-info">No results for "${escapeHtml(query)}"</div>`;
    return;
  }

  container.innerHTML = `<div class="search-info">${total} results for "${escapeHtml(query)}"</div>` +
    questions.map(q => {
      const typeLabel = TYPE_LABELS[q.type] || q.type;
      const typeBadge = `<span class="badge ${TYPE_BADGE_CLASS[q.type] || 'badge-choice'}">${typeLabel}</span>`;
      const diffBadge = `<span class="badge badge-d${q.difficulty}">Lv.${q.difficulty}</span>`;
      return `<div style="padding:12px 0;border-bottom:1px solid var(--border);">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
          ${typeBadge}${diffBadge}
          <span style="font-size:11px;color:var(--text-muted);margin-left:auto;">${escapeHtml(q.chapter || '')}</span>
        </div>
        <div style="font-size:14px;line-height:1.6;">${highlightMatch(q.content, query)}</div>
      </div>`;
    }).join('');
}
