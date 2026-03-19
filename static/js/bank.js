import { authFetch } from './api.js';
import { API, escapeHtml, TYPE_LABELS, TYPE_BADGE_CLASS } from './utils.js';

export async function loadBank() {
  const ch = document.getElementById('bank-chapter').value;
  const diff = document.getElementById('bank-diff').value;
  const type = document.getElementById('bank-type').value;
  const params = new URLSearchParams();
  if (ch) params.set('chapter', ch);
  if (diff) params.set('difficulty', diff);
  if (type) params.set('q_type', type);
  params.set('limit', '100');

  const list = document.getElementById('bank-list');
  list.innerHTML = '<div class="card" style="text-align:center;padding:40px;"><span class="spinner"></span></div>';

  const res = await authFetch(API + '/questions?' + params);
  const data = await res.json();

  if (!data.questions || data.questions.length === 0) {
    list.innerHTML = '<div class="card" style="text-align:center;color:var(--text-muted)">No questions found</div>';
    return;
  }

  list.innerHTML = data.questions.map(q => {
    const typeLabel = TYPE_LABELS[q.type] || q.type;
    const typeBadge = `<span class="badge ${TYPE_BADGE_CLASS[q.type] || 'badge-choice'}">${typeLabel}</span>`;
    const diffBadge = `<span class="badge badge-d${q.difficulty}">Lv.${q.difficulty}</span>`;

    let opts = '';
    if (q.type !== 'truefalse') {
      opts = ['A','B','C','D'].map(k => {
        const v = q['option_' + k.toLowerCase()];
        return v ? `<div style="margin-left:12px;font-size:12px;color:var(--text-dim);padding:2px 0;">
          <span style="font-family:var(--mono);color:var(--text-muted);">${k}.</span> ${escapeHtml(v)}</div>` : '';
      }).join('');
    }

    return `<div class="card" style="padding:16px;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
        ${typeBadge}${diffBadge}
        <span style="font-size:11px;color:var(--text-muted);margin-left:auto;font-family:var(--mono);">${escapeHtml(q.chapter || '')}</span>
      </div>
      ${q.scenario_text ? `<div style="font-size:12px;color:var(--text-muted);margin-bottom:6px;padding:8px;background:var(--surface-2);border-radius:4px;border-left:2px solid #a855f7;">${escapeHtml(q.scenario_text).substring(0, 150)}...</div>` : ''}
      <div style="font-size:14px;margin-bottom:6px;line-height:1.6;">${escapeHtml(q.content)}</div>
      ${opts}
      <div style="font-family:var(--mono);font-size:12px;color:var(--accent);margin-top:8px;">ans: ${q.answer}</div>
      ${q.explanation ? `<div class="explanation" style="margin-top:6px;">${escapeHtml(q.explanation)}</div>` : ''}
    </div>`;
  }).join('');
}
