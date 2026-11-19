/* Small shared chart renderer for judge-level conviction outcome analysis. */
const judgeOutcomeChartInstances = {};

function renderJudgeOutcomeCharts(prefix, { upheld = 0, setAside = 0, modified = 0, classified = 0, candidates = 0 }) {
  if (typeof Chart === 'undefined') return;
  const chartRoot = document.getElementById(`${prefix}-outcome-chart-grid`);
  if (!chartRoot) return;

  const labels = ['Conviction upheld', 'Conviction set aside', 'Conviction modified'];
  const values = [Number(upheld || 0), Number(setAside || 0), Number(modified || 0)];
  const colors = ['#34d399', '#fb7185', '#fbbf24'];
  const denominator = Number(classified || 0);
  const possible = Number(candidates || 0);
  const unclassified = Math.max(possible - denominator, 0);
  const denominatorLabel = document.getElementById(`${prefix}-outcome-chart-denominator`);
  if (denominatorLabel) denominatorLabel.textContent = `Classified appeals: ${formatNumber(denominator)}`;
  const coverage = document.getElementById(`${prefix}-outcome-chart-coverage-text`);
  if (coverage) {
    const rate = possible ? (denominator / possible * 100).toFixed(1) : '0.0';
    coverage.textContent = `${formatNumber(denominator)} of ${formatNumber(possible)} likely conviction appeals have a classifiable outcome (${rate}%).`;
  }

  const charts = [
    { key: 'share', id: `${prefix}-outcome-share-chart` },
    { key: 'counts', id: `${prefix}-outcome-count-chart` },
    { key: 'coverage', id: `${prefix}-outcome-coverage-chart` }
  ];
  for (const chart of charts) {
    const canvas = document.getElementById(chart.id);
    if (!canvas) continue;
    const instanceKey = `${prefix}-${chart.key}`;
    if (judgeOutcomeChartInstances[instanceKey]) judgeOutcomeChartInstances[instanceKey].destroy();
    let config;

    if (chart.key === 'share') {
      config = {
        type: 'doughnut',
        data: { labels, datasets: [{ data: values, backgroundColor: colors, borderColor: '#111318', borderWidth: 3, hoverOffset: 7 }] },
        options: {
          responsive: true, maintainAspectRatio: false, cutout: '52%',
          plugins: {
            legend: { position: 'bottom', labels: { color: '#c4c7d0', padding: 13, usePointStyle: true } },
            tooltip: { callbacks: { label: (item) => `${item.label}: ${formatNumber(item.raw)} (${denominator ? (item.raw / denominator * 100).toFixed(1) : '0.0'}% of classified appeals)` } }
          }
        }
      };
    } else if (chart.key === 'counts') {
      config = {
        type: 'bar',
        data: { labels, datasets: [{ label: 'Appeals', data: values, backgroundColor: colors, borderRadius: 6, maxBarThickness: 38 }] },
        options: {
          indexAxis: 'y', responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: (item) => `${formatNumber(item.raw)} appeals (${denominator ? (item.raw / denominator * 100).toFixed(1) : '0.0'}% of classified appeals)` } } },
          scales: {
            x: { beginAtZero: true, grid: { color: 'rgba(148, 163, 184, 0.12)' }, ticks: { color: '#a1a1aa', callback: (value) => formatNumber(value) } },
            y: { grid: { display: false }, ticks: { color: '#d4d4d8' } }
          }
        }
      };
    } else {
      config = {
        type: 'bar',
        data: { labels: ['Likely conviction appeals'], datasets: [
          { label: 'Classified outcome', data: [denominator], backgroundColor: '#60a5fa', borderRadius: 5 },
          { label: 'No classifiable outcome', data: [unclassified], backgroundColor: '#52525b', borderRadius: 5 }
        ] },
        options: {
          indexAxis: 'y', responsive: true, maintainAspectRatio: false,
          scales: {
            x: { stacked: true, beginAtZero: true, grid: { color: 'rgba(148, 163, 184, 0.12)' }, ticks: { color: '#a1a1aa', callback: (value) => formatNumber(value) } },
            y: { stacked: true, grid: { display: false }, ticks: { color: '#d4d4d8' } }
          },
          plugins: {
            legend: { position: 'bottom', labels: { color: '#c4c7d0', padding: 12, usePointStyle: true } },
            tooltip: { callbacks: { label: (item) => `${item.dataset.label}: ${formatNumber(item.raw)}` } }
          }
        }
      };
    }

    judgeOutcomeChartInstances[instanceKey] = new Chart(canvas.getContext('2d'), config);
  }
}
