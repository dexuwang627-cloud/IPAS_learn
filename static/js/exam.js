import { authFetch } from './api.js';
import { API, escapeHtml } from './utils.js';
import { renderQuiz, getUserAnswers, setUserAnswers, setCurrentQuiz } from './quiz.js';

let examState = null;

export function getExamState() { return examState; }

export function clearExamState() {
  if (examState) {
    if (examState.timer) clearInterval(examState.timer);
    document.removeEventListener('visibilitychange', onTabSwitch);
    examState = null;
  }
}

export async function startExam() {
  const btn = document.getElementById('btn-start-exam');
  if (!btn) return;
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> LOADING...';

  try {
    const body = {
      chapter: document.getElementById('sel-chapter').value || null,
      difficulty: Number(document.getElementById('sel-difficulty').value) || null,
      num_choice: Number(document.getElementById('num-choice').value),
      num_tf: Number(document.getElementById('num-tf').value),
      num_multichoice: Number(document.getElementById('num-mc').value),
      num_scenario: Number(document.getElementById('num-scenario').value),
      duration_min: Number(document.getElementById('exam-duration')?.value || 60),
    };
    const res = await authFetch(API + '/exam/start', {
      method: 'POST', body: JSON.stringify(body),
    });
    if (!res.ok) { const err = await res.json(); alert(err.detail || 'Failed'); return; }
    const data = await res.json();

    examState = {
      exam_id: data.exam_id,
      duration_min: data.duration_min,
      started_at: data.started_at,
      tab_switches: 0,
    };
    setCurrentQuiz(data);
    setUserAnswers({});

    renderQuiz(data.questions);
    document.getElementById('quiz-setup').classList.add('hidden');
    document.getElementById('quiz-area').classList.remove('hidden');
    document.getElementById('quiz-result').classList.add('hidden');

    startExamTimer();
    enableTabSwitchDetection();
  } finally {
    btn.disabled = false; btn.textContent = 'EXAM MODE';
  }
}

function startExamTimer() {
  const timerEl = document.getElementById('exam-timer');
  if (!timerEl || !examState) return;
  timerEl.classList.remove('hidden');
  timerEl.style.color = 'var(--accent)';

  const deadline = new Date(examState.started_at).getTime() + examState.duration_min * 60 * 1000;

  examState.timer = setInterval(() => {
    const remaining = Math.max(0, deadline - Date.now());
    const mins = Math.floor(remaining / 60000);
    const secs = Math.floor((remaining % 60000) / 1000);
    timerEl.textContent = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;

    if (remaining <= 300000) timerEl.style.color = 'var(--danger)';
    if (remaining <= 0) {
      clearInterval(examState.timer);
      timerEl.textContent = '00:00';
      submitExam();
    }
  }, 1000);
}

function enableTabSwitchDetection() {
  if (!examState) return;
  document.addEventListener('visibilitychange', onTabSwitch);
}

async function onTabSwitch() {
  if (!examState || document.visibilityState !== 'hidden') return;
  examState.tab_switches++;
  try {
    await authFetch(API + '/exam/' + examState.exam_id + '/tab-switch', { method: 'POST' });
  } catch (e) {}
  alert('Tab switch detected (' + examState.tab_switches + '). This may reduce your score.');
}

export async function submitExam() {
  if (!examState) return;

  document.removeEventListener('visibilitychange', onTabSwitch);
  if (examState.timer) clearInterval(examState.timer);

  const userAnswers = getUserAnswers();
  const res = await authFetch(API + '/exam/' + examState.exam_id + '/submit', {
    method: 'POST',
    body: JSON.stringify({ answers: userAnswers, tab_switches: examState.tab_switches }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || 'Submission failed');
    return;
  }
  const result = await res.json();

  // Capture exam_id before nulling state; sanitize for safe attribute injection
  const safeExamId = String(examState.exam_id).replace(/[^a-z0-9\-]/gi, '');

  const pct = Number(result.percentage) || 0;
  const score = Number(result.score) || 0;
  const total = Number(result.total) || 0;
  const color = pct >= 60 ? 'var(--accent)' : 'var(--danger)';
  let penaltyHtml = '';
  if (result.penalty > 0) {
    penaltyHtml = `<div style="color:var(--danger);font-size:13px;margin-top:8px;">
      Tab switch penalty: -${Number(result.penalty)} (${Number(result.tab_switches)} switches)
    </div>`;
  }

  document.getElementById('quiz-result').innerHTML = `
    <div class="card score-card">
      <div class="score-big" style="color:${color}">${pct}%</div>
      <div class="score-label">${score} / ${total} correct</div>
      ${penaltyHtml}
      <div class="score-bar"><div class="score-fill" style="width:${pct}%;background:${color}"></div></div>
      ${result.expired ? '<div style="color:var(--warn);margin-top:8px;">Time expired</div>' : ''}
      <div style="margin-top:20px;display:flex;gap:10px;justify-content:center;">
        <button class="btn btn-primary" onclick="resetQuiz()">RETRY</button>
        <button class="btn btn-outline" onclick="viewExamResults('${safeExamId}')">VIEW DETAILS</button>
      </div>
    </div>`;
  document.getElementById('quiz-result').classList.remove('hidden');

  // Mark answers on cards
  if (result.results) {
    result.results.forEach(r => {
      const card = document.getElementById('qcard-' + r.id);
      if (!card) return;
      card.classList.add(r.is_correct ? 'correct' : 'wrong');
      const tag = document.createElement('div');
      tag.innerHTML = r.is_correct
        ? '<span class="result-tag result-correct">CORRECT</span>'
        : `<span class="result-tag result-wrong">WRONG // ans: ${escapeHtml(r.correct_answer)}</span>`;
      card.appendChild(tag);
      if (r.explanation) {
        const exp = document.createElement('div');
        exp.className = 'explanation';
        exp.textContent = r.explanation;
        card.appendChild(exp);
      }
    });
  }

  const timerEl = document.getElementById('exam-timer');
  if (timerEl) timerEl.classList.add('hidden');
  examState = null;
}

export async function viewExamResults(examId) {
  try {
    const res = await authFetch(API + '/exam/' + examId + '/results');
    if (!res.ok) return;
    const data = await res.json();
    renderExamDetails(data);
  } catch (e) {}
}

function renderExamDetails(data) {
  const container = document.getElementById('quiz-result');
  const results = data.question_results || [];
  const chapterStats = {};
  for (const r of results) {
    const ch = r.chapter || 'unknown';
    if (!chapterStats[ch]) chapterStats[ch] = { total: 0, correct: 0 };
    chapterStats[ch].total++;
    if (r.is_correct) chapterStats[ch].correct++;
  }

  const chapterHtml = Object.entries(chapterStats).map(([ch, s]) => {
    const pct = Math.round((s.correct / s.total) * 100);
    const barColor = pct >= 80 ? 'var(--accent)' : pct >= 50 ? 'var(--warn)' : 'var(--danger)';
    return `<div class="weakness-item">
      <div class="weakness-label">${escapeHtml(ch)}</div>
      <div class="weakness-bar-wrap"><div class="weakness-bar" style="width:${pct}%;background:${barColor}"></div></div>
      <div class="weakness-pct" style="color:${barColor}">${pct}%</div>
      <div class="weakness-count">${s.correct}/${s.total}</div>
    </div>`;
  }).join('');

  container.innerHTML = `
    <div class="card score-card">
      <div class="score-big" style="color:${data.percentage >= 60 ? 'var(--accent)' : 'var(--danger)'}">${data.percentage}%</div>
      <div class="score-label">${data.score} / ${data.total} correct</div>
      ${data.penalty > 0 ? `<div style="color:var(--danger);font-size:13px;margin-top:8px;">Penalty: -${data.penalty}</div>` : ''}
      <div class="score-bar"><div class="score-fill" style="width:${data.percentage}%;background:${data.percentage >= 60 ? 'var(--accent)' : 'var(--danger)'}"></div></div>
      <div style="margin-top:20px;"><button class="btn btn-primary" onclick="resetQuiz()">BACK</button></div>
    </div>
    <div class="card"><h2>// CHAPTER BREAKDOWN</h2>${chapterHtml}</div>
    <div class="card"><h2>// QUESTION DETAILS</h2>
      ${results.map((r, i) => `<div style="padding:12px 0;border-bottom:1px solid var(--border);">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
          <span class="q-num">${i + 1}</span>
          <span class="result-tag ${r.is_correct ? 'result-correct' : 'result-wrong'}">${r.is_correct ? 'CORRECT' : 'WRONG'}</span>
          <span style="font-size:11px;color:var(--text-muted);margin-left:auto;">${escapeHtml(r.chapter || '')}</span>
        </div>
        <div style="font-size:14px;line-height:1.6;margin-bottom:6px;">${escapeHtml(r.content || '')}</div>
        <div style="font-family:var(--mono);font-size:12px;">
          <span style="color:${r.is_correct ? 'var(--accent)' : 'var(--danger)'}">Your: ${escapeHtml(r.user_answer || '-')}</span>
          ${!r.is_correct ? `<span style="color:var(--accent);margin-left:12px;">Correct: ${escapeHtml(r.correct_answer || '')}</span>` : ''}
        </div>
        ${r.explanation ? `<div class="explanation" style="margin-top:8px;">${escapeHtml(r.explanation)}</div>` : ''}
      </div>`).join('')}
    </div>`;
}
