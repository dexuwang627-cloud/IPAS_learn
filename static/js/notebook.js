import { authFetch } from './api.js';
import { API, escapeHtml, TYPE_LABELS, TYPE_BADGE_CLASS } from './utils.js';
import { renderQuiz, setCurrentQuiz, setUserAnswers } from './quiz.js';

let currentFilter = 'all';
let currentSort = 'recent';
let currentPage = 0;
const PAGE_SIZE = 20;

export async function renderNotebook() {
  const container = document.getElementById('notebook-list');
  if (!container) return;

  container.innerHTML = '<div style="text-align:center;padding:40px;"><span class="spinner"></span></div>';

  try {
    const params = new URLSearchParams({
      filter: currentFilter,
      sort: currentSort,
      limit: PAGE_SIZE,
      offset: currentPage * PAGE_SIZE,
    });
    const [itemsRes, statsRes] = await Promise.all([
      authFetch(API + '/notebook?' + params),
      authFetch(API + '/notebook/stats'),
    ]);
    if (!itemsRes.ok || !statsRes.ok) {
      container.innerHTML = '<div class="notebook-empty">Failed to load notebook</div>';
      return;
    }
    const data = await itemsRes.json();
    const stats = await statsRes.json();

    renderNotebookStats(stats);
    renderNotebookItems(data.items, data.total);
  } catch (e) {
    container.innerHTML = '<div class="notebook-empty">Failed to load notebook</div>';
  }
}

function renderNotebookStats(stats) {
  const el = document.getElementById('notebook-stats');
  if (!el) return;
  el.innerHTML = `
    <div class="stat-card"><div class="stat-num">${stats.total}</div><div class="stat-label">Wrong</div></div>
    <div class="stat-card"><div class="stat-num">${stats.bookmarked}</div><div class="stat-label">Bookmarked</div></div>
    <div class="stat-card"><div class="stat-num">${(stats.by_source || {}).quiz || 0}</div><div class="stat-label">From Quiz</div></div>
    <div class="stat-card"><div class="stat-num">${(stats.by_source || {}).exam || 0}</div><div class="stat-label">From Exam</div></div>
  `;
}

function renderNotebookItems(items, total) {
  const container = document.getElementById('notebook-list');
  if (!items.length) {
    container.innerHTML = '<div class="notebook-empty">No items in notebook yet. Wrong answers will appear here automatically.</div>';
    return;
  }

  const html = items.map(item => {
    const q = item.question || {};
    const typeLabel = TYPE_LABELS[q.type] || q.type || '';
    const badgeClass = TYPE_BADGE_CLASS[q.type] || 'badge-choice';
    const bookmarkClass = item.bookmarked ? 'active' : '';

    return `<div class="notebook-item">
      <div class="notebook-header">
        <div class="q-badges">
          <span class="badge ${badgeClass}">${typeLabel}</span>
          <span class="badge badge-d${q.difficulty || 1}">Lv.${q.difficulty || 1}</span>
          <span class="badge" style="background:var(--surface2)">${escapeHtml(q.chapter_group || '')}</span>
        </div>
        <button class="bookmark-btn ${bookmarkClass}" onclick="toggleBookmark(${item.question_id})" title="Bookmark">
          ${item.bookmarked ? '\u2605' : '\u2606'}
        </button>
      </div>
      <div class="notebook-content">${escapeHtml(q.content || '')}</div>
      <div class="notebook-meta">
        <span>Wrong ${item.wrong_count}x</span>
        <span>${item.last_wrong_at ? new Date(item.last_wrong_at).toLocaleDateString() : ''}</span>
        <span class="badge" style="font-size:10px;">${escapeHtml(item.source)}</span>
      </div>
      <div class="notebook-answer">
        <span style="color:var(--accent);">Answer: ${escapeHtml(q.answer || '')}</span>
        ${q.explanation ? `<div class="explanation" style="margin-top:6px;">${escapeHtml(q.explanation)}</div>` : ''}
      </div>
      <button class="btn-sm btn-danger" onclick="removeFromNotebook(${item.question_id})" style="margin-top:8px;">Remove</button>
    </div>`;
  }).join('');

  const pageInfo = total > PAGE_SIZE
    ? `<div style="text-align:center;margin-top:16px;color:var(--text-muted);">
        Showing ${currentPage * PAGE_SIZE + 1}-${Math.min((currentPage + 1) * PAGE_SIZE, total)} of ${total}
        ${currentPage > 0 ? `<button class="btn-sm" onclick="notebookPage(${currentPage - 1})">Prev</button>` : ''}
        ${(currentPage + 1) * PAGE_SIZE < total ? `<button class="btn-sm" onclick="notebookPage(${currentPage + 1})">Next</button>` : ''}
      </div>` : '';

  container.innerHTML = html + pageInfo;
}

export async function toggleBookmark(questionId) {
  const res = await authFetch(API + '/notebook/' + questionId + '/bookmark', {
    method: 'POST',
  });
  if (res.ok) {
    renderNotebook();
  }
}

export async function removeFromNotebook(questionId) {
  const res = await authFetch(API + '/notebook/' + questionId, {
    method: 'DELETE',
  });
  if (res.ok) {
    renderNotebook();
  }
}

export async function startNotebookPractice() {
  const btn = document.getElementById('btn-notebook-practice');
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }

  try {
    const res = await authFetch(API + '/notebook/practice', {
      method: 'POST',
      body: JSON.stringify({ num_questions: 20, filter: currentFilter }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || 'No questions available');
      return;
    }
    const data = await res.json();
    setCurrentQuiz(data);
    setUserAnswers({});

    document.querySelector('[data-tab="quiz"]').click();
    renderQuiz(data.questions);
    document.getElementById('quiz-setup').classList.add('hidden');
    document.getElementById('quiz-area').classList.remove('hidden');
    document.getElementById('quiz-result').classList.add('hidden');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'PRACTICE FROM NOTEBOOK'; }
  }
}

export function filterNotebook(filter) {
  currentFilter = filter;
  currentPage = 0;
  document.querySelectorAll('.notebook-filter-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.filter === filter);
  });
  renderNotebook();
}

export function sortNotebook(sort) {
  currentSort = sort;
  currentPage = 0;
  renderNotebook();
}

export function notebookPage(page) {
  currentPage = page;
  renderNotebook();
}
