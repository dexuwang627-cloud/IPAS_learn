import { initParticles } from './particles.js';
import { initAuth, toggleAuthMode, doLogout } from './auth.js';
import { startQuiz, submitQuiz, resetQuiz, selectAnswer } from './quiz.js';
import { startExam, submitExam, getExamState, viewExamResults } from './exam.js';
import { renderWeakness, startWeaknessPractice } from './weakness.js';
import { loadBank } from './bank.js';
import { initSearchUI, doSearch } from './search.js';
import { authFetch } from './api.js';
import { API } from './utils.js';

// Expose to inline onclick handlers
window.selectAnswer = selectAnswer;
window.startQuiz = startQuiz;
window.submitQuiz = submitQuiz;
window.resetQuiz = resetQuiz;
window.startExam = startExam;
window.submitExam = submitExam;
window.loadBank = loadBank;
window.doSearch = doSearch;
window.toggleAuthMode = toggleAuthMode;
window.doLogout = doLogout;
window.renderWeakness = renderWeakness;
window.startWeaknessPractice = startWeaknessPractice;
window.viewExamResults = viewExamResults;

// Tab switching
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    document.querySelectorAll('[id^="tab-"]').forEach(p => p.classList.add('hidden'));
    document.getElementById('tab-' + tab.dataset.tab).classList.remove('hidden');

    if (tab.dataset.tab === 'bank') loadBank();
    if (tab.dataset.tab === 'weakness') renderWeakness();
  });
});

// Submit dispatcher: exam mode or practice
window.handleSubmit = function() {
  if (getExamState()) submitExam();
  else submitQuiz();
};

// Init: load stats and chapters
async function init() {
  try {
    const [statsRes, chapRes] = await Promise.all([
      authFetch(API + '/stats').then(r => r.json()),
      authFetch(API + '/chapters').then(r => r.json()),
    ]);

    const bar = document.getElementById('stats-bar');
    const byType = statsRes.by_type || {};
    bar.innerHTML = `
      <div class="stat-item"><div class="num">${statsRes.total}</div><div class="label">Total</div></div>
      <div class="stat-item"><div class="num">${Object.keys(statsRes.by_chapter || {}).length}</div><div class="label">Chapters</div></div>
      <div class="stat-item"><div class="num">${byType.choice || 0}</div><div class="label">Choice</div></div>
      <div class="stat-item"><div class="num">${(byType.multichoice || 0) + (byType.scenario_choice || 0) + (byType.scenario_multichoice || 0)}</div><div class="label">MC+Scen</div></div>
      <div class="stat-item"><div class="num">${byType.truefalse || 0}</div><div class="label">T/F</div></div>
    `;

    const chapters = chapRes.chapters || [];
    ['sel-chapter', 'bank-chapter'].forEach(id => {
      const sel = document.getElementById(id);
      const existing = new Set(Array.from(sel.options).map(o => o.value));
      chapters.forEach(c => {
        if (!existing.has(c)) {
          const opt = document.createElement('option');
          opt.value = c; opt.textContent = c;
          sel.appendChild(opt);
        }
      });
    });
  } catch (e) {}

  initSearchUI();
}

// Boot
initParticles('noise-canvas');
initAuth(init);
