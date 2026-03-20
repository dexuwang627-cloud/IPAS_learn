import { authFetch } from './api.js';
import { API, escapeHtml } from './utils.js';

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

    // Summary is available for all tiers
    if (summaryRes.ok) {
      const summary = await summaryRes.json();
      renderSummaryStats(summary);
    }
    if (!trendRes.ok || !volumeRes.ok || !chapterRes.ok) return;

    const [trend, volume, chapter] = await Promise.all([
      trendRes.json(), volumeRes.json(), chapterRes.json(),
    ]);

    renderAccuracyTrend(trend.data);
    renderVolumeChart(volume.data);
    renderChapterAccuracy(chapter.data);
  } catch (e) {
    const el = document.getElementById('dashboard-summary');
    if (el && !el.innerHTML.trim()) {
      el.innerHTML = '<div style="text-align:center;color:var(--text-muted);font-size:13px;padding:20px;">Start practicing to see your dashboard stats</div>';
    }
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

export async function renderChapterProgress() {
  const el = document.getElementById('chapter-progress');
  if (!el) return;
  try {
    const res = await authFetch(API + '/dashboard/chapter-progress');
    if (!res.ok) { el.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">Login to see progress</div>'; return; }
    const { data } = await res.json();
    if (!data || !data.length) { el.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">No data yet. Start practicing!</div>'; return; }
    el.innerHTML = data.map(ch => {
      const covPct = Math.min(ch.coverage, 100);
      const accPct = ch.accuracy;
      const covColor = covPct >= 80 ? 'var(--accent)' : covPct >= 40 ? 'var(--warn)' : 'var(--danger)';
      const accColor = accPct >= 80 ? 'var(--accent)' : accPct >= 50 ? 'var(--warn)' : 'var(--danger)';
      return `
        <div style="margin-bottom:16px;">
          <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:4px;">
            <span style="font-size:13px;color:var(--text);max-width:60%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(ch.chapter)}">${escapeHtml(ch.chapter)}</span>
            <span style="font-family:var(--mono);font-size:11px;color:var(--text-dim);">${ch.attempted}/${ch.total_in_bank} questions</span>
          </div>
          <div style="display:flex;gap:8px;align-items:center;">
            <span style="font-family:var(--mono);font-size:10px;color:var(--text-muted);min-width:48px;">Coverage</span>
            <div style="flex:1;height:6px;background:var(--surface-2);border-radius:3px;overflow:hidden;">
              <div style="width:${covPct}%;height:100%;background:${covColor};border-radius:3px;transition:width 0.6s;"></div>
            </div>
            <span style="font-family:var(--mono);font-size:11px;font-weight:600;min-width:42px;text-align:right;color:${covColor};">${covPct}%</span>
          </div>
          <div style="display:flex;gap:8px;align-items:center;margin-top:3px;">
            <span style="font-family:var(--mono);font-size:10px;color:var(--text-muted);min-width:48px;">Accuracy</span>
            <div style="flex:1;height:6px;background:var(--surface-2);border-radius:3px;overflow:hidden;">
              <div style="width:${accPct}%;height:100%;background:${accColor};border-radius:3px;transition:width 0.6s;"></div>
            </div>
            <span style="font-family:var(--mono);font-size:11px;font-weight:600;min-width:42px;text-align:right;color:${accColor};">${accPct}%</span>
          </div>
        </div>
      `;
    }).join('');
  } catch {
    el.innerHTML = '<div style="color:var(--text-muted);font-size:13px;">Failed to load</div>';
  }
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
