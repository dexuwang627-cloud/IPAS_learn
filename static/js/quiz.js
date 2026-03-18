import { authFetch } from './api.js';
import { API, escapeHtml, TYPE_LABELS, TYPE_BADGE_CLASS, isMultichoice } from './utils.js';
import { getExamState, clearExamState } from './exam.js';
import { saveHistory } from './weakness.js';

let currentQuiz = null;
let userAnswers = {};

export function getCurrentQuiz() { return currentQuiz; }
export function getUserAnswers() { return userAnswers; }
export function setCurrentQuiz(q) { currentQuiz = q; }
export function setUserAnswers(a) { userAnswers = a; }

export async function startQuiz() {
  const btn = document.getElementById('btn-start');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> LOADING...';

  try {
    const body = {
      chapter: document.getElementById('sel-chapter').value || null,
      difficulty: Number(document.getElementById('sel-difficulty').value) || null,
      num_choice: Number(document.getElementById('num-choice').value),
      num_tf: Number(document.getElementById('num-tf').value),
      num_multichoice: Number(document.getElementById('num-mc').value),
      num_scenario: Number(document.getElementById('num-scenario').value),
    };
    const res = await authFetch(API + '/quiz', {
      method: 'POST', body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      alert(err.detail || 'Failed to start quiz');
      return;
    }
    currentQuiz = await res.json();
    userAnswers = {};

    if (currentQuiz.total === 0) {
      alert('\u984C\u5EAB\u4E2D\u6C92\u6709\u7B26\u5408\u689D\u4EF6\u7684\u984C\u76EE');
      return;
    }

    renderQuiz(currentQuiz.questions);
    document.getElementById('quiz-setup').classList.add('hidden');
    document.getElementById('quiz-area').classList.remove('hidden');
    document.getElementById('quiz-result').classList.add('hidden');
  } finally {
    btn.disabled = false; btn.textContent = 'PRACTICE';
  }
}

export function renderQuiz(questions) {
  const list = document.getElementById('questions-list');
  let html = '';
  let currentScenarioId = null;
  let qNum = 0;

  for (const q of questions) {
    qNum++;
    const typeLabel = TYPE_LABELS[q.type] || q.type;
    const typeBadgeClass = TYPE_BADGE_CLASS[q.type] || 'badge-choice';
    const diffBadge = `<span class="badge badge-d${q.difficulty}">Lv.${q.difficulty}</span>`;
    const typeBadge = `<span class="badge ${typeBadgeClass}">${typeLabel}</span>`;

    if (q.scenario_id && q.scenario_id !== currentScenarioId) {
      currentScenarioId = q.scenario_id;
      html += `<div class="scenario-block">
        <div class="scenario-label">Scenario // ${q.scenario_id}</div>
        <div class="scenario-text">${escapeHtml(q.scenario_text || '')}</div>
      </div>`;
    } else if (!q.scenario_id) {
      currentScenarioId = null;
    }

    const multiHint = isMultichoice(q.type)
      ? '<div class="q-hint">* MULTI-SELECT: \u9078\u64C7\u6240\u6709\u6B63\u78BA\u9078\u9805</div>' : '';

    let optionsHtml = '';
    if (q.type === 'truefalse') {
      optionsHtml = `<div class="tf-options">
        <div class="tf-btn" data-qid="${q.id}" data-val="T" onclick="selectAnswer(${q.id},'T',this,'truefalse')">O \u6B63\u78BA</div>
        <div class="tf-btn" data-qid="${q.id}" data-val="F" onclick="selectAnswer(${q.id},'F',this,'truefalse')">X \u932F\u8AA4</div>
      </div>`;
    } else {
      const multi = isMultichoice(q.type);
      optionsHtml = `<div class="options">
        ${['A','B','C','D'].map(k => {
          const val = q['option_' + k.toLowerCase()];
          if (!val) return '';
          const indicator = multi
            ? '<span class="option-check"></span>'
            : `<span class="option-label">${k}</span>`;
          return `<div class="option-btn" data-qid="${q.id}" data-val="${k}"
                       onclick="selectAnswer(${q.id},'${k}',this,'${q.type}')">
            ${indicator}
            ${multi ? `<span class="option-label" style="margin-left:-4px;">${k}</span>` : ''}
            <span>${escapeHtml(val)}</span>
          </div>`;
        }).join('')}
      </div>`;
    }

    html += `<div class="question-card" id="qcard-${q.id}">
      <div class="q-header">
        <span class="q-num">${qNum}</span>
        <div class="q-badges">${typeBadge}${diffBadge}</div>
      </div>
      <div class="q-text">${escapeHtml(q.content)}</div>
      ${multiHint}
      ${optionsHtml}
    </div>`;
  }

  list.innerHTML = html;
}

export function selectAnswer(qid, val, el, qType) {
  if (!document.getElementById('quiz-result').classList.contains('hidden')) return;
  const card = document.getElementById('qcard-' + qid);

  if (isMultichoice(qType)) {
    el.classList.toggle('selected');
    const selected = Array.from(card.querySelectorAll('.option-btn.selected'))
      .map(b => b.dataset.val).sort().join('');
    userAnswers[String(qid)] = selected;
  } else if (qType === 'truefalse') {
    card.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('selected'));
    el.classList.add('selected');
    userAnswers[String(qid)] = val;
  } else {
    card.querySelectorAll('.option-btn').forEach(b => b.classList.remove('selected'));
    el.classList.add('selected');
    userAnswers[String(qid)] = val;
  }
}

export async function submitQuiz() {
  if (Object.keys(userAnswers).length === 0) {
    alert('\u8ACB\u81F3\u5C11\u4F5C\u7B54\u4E00\u984C');
    return;
  }

  const res = await authFetch(API + '/quiz/check', {
    method: 'POST', body: JSON.stringify({ answers: userAnswers }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.detail || 'Failed to submit quiz');
    return;
  }
  const result = await res.json();

  saveHistory(result.results);

  const pct = result.percentage;
  const color = pct >= 60 ? 'var(--accent)' : 'var(--danger)';
  document.getElementById('quiz-result').innerHTML = `
    <div class="card score-card">
      <div class="score-big" style="color:${color}">${pct}%</div>
      <div class="score-label">${result.score} / ${result.total} correct</div>
      <div class="score-bar"><div class="score-fill" style="width:${pct}%;background:${color}"></div></div>
      <div style="margin-top:20px;display:flex;gap:10px;justify-content:center;">
        <button class="btn btn-primary" onclick="resetQuiz()">RETRY</button>
        <button class="btn btn-outline" onclick="document.querySelector('[data-tab=weakness]').click()">VIEW WEAKNESS</button>
      </div>
    </div>`;
  document.getElementById('quiz-result').classList.remove('hidden');

  // Mark answers on cards
  result.results.forEach(r => {
    const card = document.getElementById('qcard-' + r.id);
    if (!card) return;
    card.classList.add(r.is_correct ? 'correct' : 'wrong');

    if (isMultichoice(r.type)) {
      const correctLetters = r.correct_answer.split('');
      const userLetters = new Set((r.user_answer || '').toUpperCase().replace(/[^A-D]/g, '').split(''));
      correctLetters.forEach(letter => {
        const el = card.querySelector(`[data-val="${letter}"]`);
        if (el) el.classList.add('correct-answer');
      });
      userLetters.forEach(letter => {
        if (!correctLetters.includes(letter)) {
          const el = card.querySelector(`[data-val="${letter}"]`);
          if (el) el.classList.add('wrong-answer');
        }
      });
    } else {
      const correctEl = card.querySelector(`[data-val="${r.correct_answer}"]`);
      if (correctEl) correctEl.classList.add('correct-answer');
      if (!r.is_correct) {
        const wrongEl = card.querySelector(`[data-val="${r.user_answer}"]`);
        if (wrongEl) wrongEl.classList.add('wrong-answer');
      }
    }

    const tag = document.createElement('div');
    tag.innerHTML = r.is_correct
      ? '<span class="result-tag result-correct">CORRECT</span>'
      : `<span class="result-tag result-wrong">WRONG // ans: ${escapeHtml(r.correct_answer)}</span>`;
    card.appendChild(tag);

    if (r.partial_correct !== undefined && !r.is_correct) {
      const pi = document.createElement('div');
      pi.className = 'partial-info';
      pi.textContent = `${r.partial_correct}/${r.total_correct} correct selections`;
      card.appendChild(pi);
    }

    if (r.explanation) {
      const exp = document.createElement('div');
      exp.className = 'explanation';
      exp.textContent = r.explanation;
      card.appendChild(exp);
    }

    if (r.similar_questions && r.similar_questions.length > 0) {
      const sim = document.createElement('div');
      sim.className = 'similar-block';
      sim.innerHTML = `<div class="similar-label">Similar Questions</div>` +
        r.similar_questions.map(s =>
          `<div class="similar-item">#${s.id} ${escapeHtml(s.content || '').substring(0, 80)}...</div>`
        ).join('');
      card.appendChild(sim);
    }
  });
}

export function resetQuiz() {
  const examSt = getExamState();
  if (examSt) {
    clearExamState();
  }
  const timerEl = document.getElementById('exam-timer');
  if (timerEl) timerEl.classList.add('hidden');
  document.getElementById('quiz-setup').classList.remove('hidden');
  document.getElementById('quiz-area').classList.add('hidden');
  document.getElementById('quiz-result').classList.add('hidden');
  currentQuiz = null;
  userAnswers = {};
}
