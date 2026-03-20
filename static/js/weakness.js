import { authFetch } from './api.js';
import { getSupabaseClient, getCurrentUser } from './auth.js';
import { API, escapeHtml, TYPE_LABELS, TYPE_BADGE_CLASS } from './utils.js';
import { getCurrentQuiz, renderQuiz, setCurrentQuiz, setUserAnswers } from './quiz.js';

let sessionHistory = JSON.parse(localStorage.getItem('ipas_history') || '[]');

export function saveHistory(results) {
  const quiz = getCurrentQuiz();
  const now = new Date().toISOString();
  for (const r of results) {
    sessionHistory.push({
      id: r.id, type: r.type,
      content: (r.content || '').substring(0, 100),
      chapter: findChapterForQuestion(r.id, quiz),
      is_correct: r.is_correct, user_answer: r.user_answer, timestamp: now,
    });
  }
  if (sessionHistory.length > 500) sessionHistory = sessionHistory.slice(-500);
  localStorage.setItem('ipas_history', JSON.stringify(sessionHistory));
}

function findChapterForQuestion(qid, quiz) {
  if (!quiz || !quiz.questions) return 'unknown';
  const q = quiz.questions.find(q => q.id === qid);
  return q ? (q.chapter || 'unknown') : 'unknown';
}

export async function renderWeakness() {
  const container = document.getElementById('weakness-content');
  const logContainer = document.getElementById('weakness-log');
  const detailCard = document.getElementById('weakness-detail-card');

  if (getSupabaseClient() && getCurrentUser()) {
    try {
      const res = await authFetch(API + '/history/weakness');
      if (res.ok) {
        const data = await res.json();
        if (data.stats && data.stats.length > 0) {
          renderWeaknessFromStats(container, logContainer, detailCard, data.stats);
          return;
        }
      }
    } catch (e) {}
  }

  if (sessionHistory.length === 0) {
    container.innerHTML = '<div class="weakness-empty">\u5C1A\u7121\u4F5C\u7B54\u7D00\u9304\u3002\u5B8C\u6210\u6E2C\u9A57\u5F8C\u6703\u81EA\u52D5\u8A18\u9304\u3002</div>';
    detailCard.classList.add('hidden');
    return;
  }

  const chapters = {};
  for (const h of sessionHistory) {
    const ch = h.chapter || 'unknown';
    if (!chapters[ch]) chapters[ch] = { total: 0, correct: 0, wrong: [] };
    chapters[ch].total++;
    if (h.is_correct) chapters[ch].correct++;
    else chapters[ch].wrong.push(h);
  }

  const sorted = Object.entries(chapters)
    .map(([ch, data]) => ({
      chapter: ch, total: data.total, correct: data.correct,
      pct: Math.round((data.correct / data.total) * 100), wrong: data.wrong,
    }))
    .sort((a, b) => a.pct - b.pct);

  const totalQ = sessionHistory.length;
  const totalCorrect = sessionHistory.filter(h => h.is_correct).length;
  const overallPct = Math.round((totalCorrect / totalQ) * 100);

  container.innerHTML = `
    <div style="display:flex;gap:12px;margin-bottom:20px;">
      <div class="stat-item" style="flex:1"><div class="num">${totalQ}</div><div class="label">Total Answers</div></div>
      <div class="stat-item" style="flex:1"><div class="num" style="color:${overallPct >= 60 ? 'var(--accent)' : 'var(--danger)'}">${overallPct}%</div><div class="label">Overall</div></div>
      <div class="stat-item" style="flex:1"><div class="num" style="color:var(--danger)">${totalQ - totalCorrect}</div><div class="label">Wrong</div></div>
    </div>` + sorted.map(item => {
    const barColor = item.pct >= 80 ? 'var(--accent)' : item.pct >= 50 ? 'var(--warn)' : 'var(--danger)';
    return `<div class="weakness-item">
      <div class="weakness-label" title="${escapeHtml(item.chapter)}">${escapeHtml(item.chapter)}</div>
      <div class="weakness-bar-wrap"><div class="weakness-bar" style="width:${item.pct}%;background:${barColor}"></div></div>
      <div class="weakness-pct" style="color:${barColor}">${item.pct}%</div>
      <div class="weakness-count">${item.correct}/${item.total}</div>
    </div>`;
  }).join('');

  detailCard.classList.remove('hidden');
  const allWrong = sorted.flatMap(s => s.wrong).slice(-20).reverse();
  if (allWrong.length === 0) {
    logContainer.innerHTML = '<div class="weakness-empty">No wrong answers recorded.</div>';
  } else {
    logContainer.innerHTML = allWrong.map(w => `
      <div style="padding:10px 0;border-bottom:1px solid var(--border);font-size:13px;">
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:4px;">
          <span class="badge ${TYPE_BADGE_CLASS[w.type] || 'badge-choice'}">${TYPE_LABELS[w.type] || w.type}</span>
          <span style="color:var(--text-muted);font-family:var(--mono);font-size:11px;">#${w.id}</span>
          <span style="color:var(--text-muted);font-size:11px;margin-left:auto;">${w.timestamp ? w.timestamp.slice(0, 10) : ''}</span>
        </div>
        <div style="color:var(--text-dim);line-height:1.5;">${escapeHtml(w.content)}...</div>
        <div style="font-family:var(--mono);font-size:11px;margin-top:4px;">
          <span style="color:var(--danger)">yours: ${w.user_answer}</span>
        </div>
      </div>
    `).join('');
  }
}

function renderWeaknessFromStats(container, logContainer, detailCard, stats) {
  const totalQ = stats.reduce((s, r) => s + r.total, 0);
  const totalCorrect = stats.reduce((s, r) => s + r.correct, 0);
  const overallPct = totalQ ? Math.round((totalCorrect / totalQ) * 100) : 0;

  const sorted = stats.map(s => ({
    chapter: s.chapter, total: s.total, correct: s.correct,
    pct: Math.round((s.correct / s.total) * 100),
  })).sort((a, b) => a.pct - b.pct);

  container.innerHTML = `
    <div style="display:flex;gap:12px;margin-bottom:20px;">
      <div class="stat-item" style="flex:1"><div class="num">${totalQ}</div><div class="label">Total Answers</div></div>
      <div class="stat-item" style="flex:1"><div class="num" style="color:${overallPct >= 60 ? 'var(--accent)' : 'var(--danger)'}">${overallPct}%</div><div class="label">Overall</div></div>
      <div class="stat-item" style="flex:1"><div class="num" style="color:var(--danger)">${totalQ - totalCorrect}</div><div class="label">Wrong</div></div>
    </div>` + sorted.map(item => {
    const barColor = item.pct >= 80 ? 'var(--accent)' : item.pct >= 50 ? 'var(--warn)' : 'var(--danger)';
    return `<div class="weakness-item">
      <div class="weakness-label" title="${escapeHtml(item.chapter)}">${escapeHtml(item.chapter)}</div>
      <div class="weakness-bar-wrap"><div class="weakness-bar" style="width:${item.pct}%;background:${barColor}"></div></div>
      <div class="weakness-pct" style="color:${barColor}">${item.pct}%</div>
      <div class="weakness-count">${item.correct}/${item.total}</div>
    </div>`;
  }).join('') + `
    <div style="text-align:center;margin-top:20px;">
      <button class="btn btn-primary" onclick="startWeaknessPractice()">PRACTICE WEAK CHAPTERS</button>
    </div>`;
  detailCard.classList.add('hidden');
}

export async function startWeaknessPractice() {
  try {
    const res = await authFetch(API + '/quiz/weakness', {
      method: 'POST',
      body: JSON.stringify({ num_questions: 15, num_weak_chapters: 3 }),
    });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || 'Failed to generate weakness quiz');
      return;
    }
    const data = await res.json();
    setCurrentQuiz(data);
    setUserAnswers({});

    // Switch to quiz tab
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelector('[data-tab="quiz"]').classList.add('active');
    document.querySelectorAll('[id^="tab-"]').forEach(p => p.classList.add('hidden'));
    document.getElementById('tab-quiz').classList.remove('hidden');

    renderQuiz(data.questions);
    document.getElementById('quiz-setup').classList.add('hidden');
    document.getElementById('quiz-area').classList.remove('hidden');
    document.getElementById('quiz-result').classList.add('hidden');
  } catch (e) {
    alert('Error: ' + e.message);
  }
}
