import { authFetch } from './api.js';
import { API } from './utils.js';

let accuracyChart = null;
let volumeChart = null;
let chapterChart = null;
let currentGranularity = 'day';

function getChartTheme() {
  return {
    textColor: '#737373',
    gridColor: 'rgba(115, 115, 115, 0.15)',
    fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
    accent: '#00ff9d',
    warn: '#ffd600',
    danger: '#ff4444',
    blue: '#4dabf7',
  };
}

function destroyCharts() {
  if (accuracyChart) { accuracyChart.destroy(); accuracyChart = null; }
  if (volumeChart) { volumeChart.destroy(); volumeChart = null; }
  if (chapterChart) { chapterChart.destroy(); chapterChart = null; }
}

export async function renderDashboard() {
  const container = document.getElementById('tab-dashboard');
  if (!container) return;

  try {
    const [trendRes, volumeRes, chapterRes, summaryRes] = await Promise.all([
      authFetch(API + '/dashboard/accuracy-trend?granularity=' + currentGranularity),
      authFetch(API + '/dashboard/volume'),
      authFetch(API + '/dashboard/chapter-accuracy'),
      authFetch(API + '/dashboard/summary'),
    ]);

    if (!trendRes.ok || !volumeRes.ok || !chapterRes.ok || !summaryRes.ok) return;

    const [trend, volume, chapter, summary] = await Promise.all([
      trendRes.json(), volumeRes.json(), chapterRes.json(), summaryRes.json(),
    ]);

    renderSummaryStats(summary);
    renderAccuracyTrend(trend.data);
    renderVolumeChart(volume.data);
    renderChapterAccuracy(chapter.data);
  } catch (e) {
    // silent fail
  }
}

function renderSummaryStats(s) {
  const el = document.getElementById('dashboard-summary');
  if (!el) return;
  el.innerHTML = `
    <div class="stat-card"><div class="stat-num">${s.total_answered}</div><div class="stat-label">Total Answered</div></div>
    <div class="stat-card"><div class="stat-num">${s.overall_accuracy}%</div><div class="stat-label">Accuracy</div></div>
    <div class="stat-card"><div class="stat-num">${s.current_streak}</div><div class="stat-label">Day Streak</div></div>
    <div class="stat-card"><div class="stat-num">${s.best_streak}</div><div class="stat-label">Best Streak</div></div>
    <div class="stat-card"><div class="stat-num">${s.total_days_active}</div><div class="stat-label">Days Active</div></div>
    <div class="stat-card"><div class="stat-num">${s.wrong_notebook_count}</div><div class="stat-label">Wrong Q's</div></div>
  `;
}

function renderAccuracyTrend(data) {
  const canvas = document.getElementById('chart-accuracy');
  if (!canvas || typeof Chart === 'undefined') return;
  if (accuracyChart) accuracyChart.destroy();

  const theme = getChartTheme();
  accuracyChart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: data.map(d => d.date),
      datasets: [{
        label: 'Accuracy %',
        data: data.map(d => d.accuracy),
        borderColor: theme.accent,
        backgroundColor: theme.accent + '20',
        fill: true,
        tension: 0.3,
        pointRadius: 3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: { display: true, text: 'ACCURACY TREND', color: theme.textColor, font: { family: theme.fontFamily } },
      },
      scales: {
        x: { ticks: { color: theme.textColor, font: { family: theme.fontFamily, size: 10 } }, grid: { color: theme.gridColor } },
        y: { min: 0, max: 100, ticks: { color: theme.textColor, callback: v => v + '%' }, grid: { color: theme.gridColor } },
      },
    },
  });
}

function renderVolumeChart(data) {
  const canvas = document.getElementById('chart-volume');
  if (!canvas || typeof Chart === 'undefined') return;
  if (volumeChart) volumeChart.destroy();

  const theme = getChartTheme();
  volumeChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: data.map(d => d.date),
      datasets: [{
        label: 'Questions',
        data: data.map(d => d.count),
        backgroundColor: theme.blue + '80',
        borderColor: theme.blue,
        borderWidth: 1,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: { display: true, text: 'DAILY VOLUME', color: theme.textColor, font: { family: theme.fontFamily } },
      },
      scales: {
        x: { ticks: { color: theme.textColor, font: { size: 10 } }, grid: { color: theme.gridColor } },
        y: { beginAtZero: true, ticks: { color: theme.textColor, stepSize: 1 }, grid: { color: theme.gridColor } },
      },
    },
  });
}

function renderChapterAccuracy(data) {
  const canvas = document.getElementById('chart-chapters');
  if (!canvas || typeof Chart === 'undefined') return;
  if (chapterChart) chapterChart.destroy();

  const theme = getChartTheme();
  const colors = data.map(d =>
    d.accuracy >= 80 ? theme.accent : d.accuracy >= 50 ? theme.warn : theme.danger
  );

  chapterChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: data.map(d => d.chapter),
      datasets: [{
        label: 'Accuracy %',
        data: data.map(d => d.accuracy),
        backgroundColor: colors.map(c => c + '80'),
        borderColor: colors,
        borderWidth: 1,
      }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: { display: true, text: 'CHAPTER ACCURACY', color: theme.textColor, font: { family: theme.fontFamily } },
      },
      scales: {
        x: { min: 0, max: 100, ticks: { color: theme.textColor, callback: v => v + '%' }, grid: { color: theme.gridColor } },
        y: { ticks: { color: theme.textColor, font: { size: 11 } }, grid: { display: false } },
      },
    },
  });
}

export function toggleGranularity(g) {
  currentGranularity = g;
  document.querySelectorAll('.granularity-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.granularity === g);
  });
  // Only re-fetch accuracy trend
  authFetch(API + '/dashboard/accuracy-trend?granularity=' + g).then(async res => {
    if (res.ok) {
      const data = await res.json();
      renderAccuracyTrend(data.data);
    }
  });
}
