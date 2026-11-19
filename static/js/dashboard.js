/**
 * Dashboard Logic - eCourts Judicial Intelligence
 */

let judgeChartInstance = null;
let hcOutcomePieChart = null;
let hcOutcomeCountChart = null;
let hcOutcomeCoverageChart = null;
let dashboardOutcomeCharts = {};
const overallCourtSnapshot = { highCourt: null, supremeCourt: null, highAnalysis: null, supremeAnalysis: null, highLoaded: false, supremeLoaded: false, highFailed: false, supremeFailed: false };

async function loadDashboard() {
  initSidebar('dashboard');

  const kpiJudges = document.getElementById('kpi-total-judges');
  const kpiPdfs = document.getElementById('kpi-total-pdfs');
  const kpiFirst = document.getElementById('kpi-first-seen');
  const kpiLast = document.getElementById('kpi-last-seen');
  const kpiPdfsFooter = document.getElementById('kpi-pdfs-footer');
  const recentTbody = document.getElementById('recent-activity-tbody');
  const courtTbody = document.getElementById('court-activity-tbody');

  // Show loading skeleton in tables
  recentTbody.innerHTML = `
    <tr><td colspan="3"><div class="skeleton" style="height: 28px; margin: 4px 0;"></div></td></tr>
    <tr><td colspan="3"><div class="skeleton" style="height: 28px; margin: 4px 0;"></div></td></tr>
    <tr><td colspan="3"><div class="skeleton" style="height: 28px; margin: 4px 0;"></div></td></tr>
  `;
  courtTbody.innerHTML = `
    <tr><td colspan="4"><div class="skeleton" style="height: 28px; margin: 4px 0;"></div></td></tr>
    <tr><td colspan="4"><div class="skeleton" style="height: 28px; margin: 4px 0;"></div></td></tr>
  `;

  try {
    const res = await API.get('/api/overview');
    const data = res.data;

    // 1. Populate KPIs
    kpiJudges.textContent = formatNumber(data.total_judges);
    kpiPdfs.textContent = formatNumber(data.total_pdfs);
    kpiFirst.textContent = formatDate(data.first_seen);
    kpiLast.textContent = formatDate(data.last_seen);

    if (data.downloaded_pdfs_count) {
      kpiPdfsFooter.innerHTML = `<span class="badge badge-emerald badge-mono" style="font-size: 10px;">${formatNumber(data.downloaded_pdfs_count)} downloaded</span> on disk`;
      const sidebarMeta = document.getElementById('sidebar-db-meta');
      if (sidebarMeta) {
        sidebarMeta.textContent = `${formatNumber(data.total_pdfs)} Total / ${formatNumber(data.downloaded_pdfs_count)} Downloaded`;
      }
    }

    // 2. Render Judge Activity Chart
    renderJudgeActivityChart(data.top_judges || []);

    // 3. Render Recent Activity Table
    renderRecentActivity(data.recent_activity || []);

    // 4. Render Court Activity Table
    renderCourtActivity(data.court_activity || []);

    renderIcons();

  } catch (err) {
    console.error('Failed to load dashboard data:', err);
    showToast('Failed to load dashboard data. Check backend connection.', 'error');
    recentTbody.innerHTML = `
      <tr>
        <td colspan="3" style="text-align: center; color: var(--accent-rose); padding: 24px;">
          Failed to load recent activity.
        </td>
      </tr>
    `;
    courtTbody.innerHTML = `
      <tr>
        <td colspan="4" style="text-align: center; color: var(--accent-rose); padding: 24px;">
          Failed to load court activity.
        </td>
      </tr>
    `;
  }
}

function renderJudgeActivityChart(topJudges) {
  const canvas = document.getElementById('judge-activity-chart');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  if (judgeChartInstance) {
    judgeChartInstance.destroy();
  }

  // Display top 12 benches
  const displayItems = topJudges.slice(0, 12);
  const labels = displayItems.map(j => {
    const name = j.judge_name;
    return name.length > 36 ? name.substring(0, 34) + '...' : name;
  });
  const fullNames = displayItems.map(j => j.judge_name);
  const values = displayItems.map(j => j.total_pdfs);

  judgeChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Total PDFs',
        data: values,
        backgroundColor: 'rgba(59, 130, 246, 0.75)',
        hoverBackgroundColor: '#3b82f6',
        borderColor: '#3b82f6',
        borderWidth: 1,
        borderRadius: 4,
        barPercentage: 0.7
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      onClick: (evt, activeElements) => {
        if (activeElements.length > 0) {
          const index = activeElements[0].index;
          const judgeName = fullNames[index];
          window.location.href = `/judge.html?name=${encodeURIComponent(judgeName)}`;
        }
      },
      plugins: {
        legend: {
          display: false
        },
        tooltip: {
          backgroundColor: '#18181b',
          titleColor: '#f4f4f5',
          bodyColor: '#a1a1aa',
          borderColor: '#27272a',
          borderWidth: 1,
          padding: 10,
          displayColors: false,
          callbacks: {
            title: function(items) {
              const idx = items[0].dataIndex;
              return fullNames[idx];
            },
            label: function(item) {
              const idx = item.dataIndex;
              const j = displayItems[idx];
              return `PDFs: ${j.total_pdfs}  |  Active: ${formatDate(j.first_seen)} to ${formatDate(j.last_seen)}`;
            },
            afterLabel: function() {
              return 'Click bar to view dossier →';
            }
          }
        }
      },
      scales: {
        x: {
          grid: {
            color: '#1f1f23',
            drawBorder: false
          },
          ticks: {
            color: '#71717a',
            font: { family: 'JetBrains Mono', size: 11 }
          }
        },
        y: {
          grid: {
            display: false
          },
          ticks: {
            color: '#a1a1aa',
            font: { family: 'Inter', size: 12 }
          }
        }
      }
    }
  });
}

function renderRecentActivity(recentItems) {
  const tbody = document.getElementById('recent-activity-tbody');
  if (!tbody) return;

  if (recentItems.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="3" style="text-align: center; color: var(--text-tertiary); padding: 24px;">
          No recent activity records available.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = recentItems.map(item => `
    <tr class="clickable" onclick="window.location.href='/judge.html?name=${encodeURIComponent(item.judge_name)}'">
      <td class="cell-mono" style="color: var(--text-tertiary);">${formatDate(item.date)}</td>
      <td class="cell-primary">
        <div style="font-weight: 500; font-size: 13px;">${escapeHTML(item.judge_name)}</div>
      </td>
      <td style="text-align: right;">
        <span class="badge badge-mono badge-blue">${item.pdf_count}</span>
      </td>
    </tr>
  `).join('');
}

function renderCourtActivity(courtItems) {
  const tbody = document.getElementById('court-activity-tbody');
  if (!tbody) return;

  if (courtItems.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="4" style="text-align: center; color: var(--text-tertiary); padding: 24px;">
          No court activity records available.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = courtItems.map(item => `
    <tr>
      <td class="cell-primary">${escapeHTML(item.state_name)}</td>
      <td style="color: var(--text-tertiary);">${escapeHTML(item.district_code)}</td>
      <td>
        <div style="font-weight: 500;">${escapeHTML(item.court_name)}</div>
        <div style="font-size: 11px; color: var(--text-tertiary);">${item.judges_count} Judges Active</div>
      </td>
      <td style="text-align: right;">
        <span class="badge badge-mono badge-emerald">${formatNumber(item.pdf_count)}</span>
      </td>
    </tr>
  `).join('');
}

async function loadSupremeCourtOverview() {
  try {
    const res = await API.get('/api/supreme-court/overview');
    overallCourtSnapshot.supremeLoaded = true;
    overallCourtSnapshot.supremeCourt = res.data || null;
    updateOverallCourtSummary();
    if (res.data) {
      const sc = res.data;
      const grid = document.getElementById('sc-kpi-grid');
      if (grid) {
        grid.style.display = '';
        document.getElementById('kpi-sc-cases').textContent = formatNumber(sc.total_cases);
        document.getElementById('kpi-sc-judges').textContent = formatNumber(sc.total_judges);
        document.getElementById('kpi-sc-earliest').textContent = formatDate(sc.earliest_judgment);
        document.getElementById('kpi-sc-latest').textContent = formatDate(sc.latest_judgment);
        renderIcons();
      }
    }
  } catch (err) {
    // SC data not available, keep section hidden - that's fine
    console.log('Supreme Court overview not available:', err.message);
    overallCourtSnapshot.supremeLoaded = true;
    overallCourtSnapshot.supremeFailed = true;
    updateOverallCourtSummary();
  }

  // Load conviction statistics
  try {
    const res = await API.get('/api/supreme-court/conviction-stats');
    if (res.data) {
      const stats = res.data;
      overallCourtSnapshot.supremeAnalysis = stats;
      const scConvictionRate = document.getElementById('kpi-sc-conviction-rate');
      const scReversalRate = document.getElementById('kpi-sc-conviction-reversal-rate');
      const scCoverage = document.getElementById('kpi-sc-outcome-coverage');
      const affirmationFooter = document.getElementById('kpi-sc-conviction-footer');
      const reversalFooter = document.getElementById('kpi-sc-reversal-footer');
      const coverageFooter = document.getElementById('kpi-sc-coverage-footer');

      if (scConvictionRate && scReversalRate && scCoverage) {
        const affirmation = stats.conviction_affirmation_rate;
        const reversal = stats.conviction_reversal_rate;
        const coverage = stats.outcome_classification_coverage;
        scConvictionRate.textContent = affirmation.rate === null ? '—' : `${affirmation.rate}%`;
        scReversalRate.textContent = reversal.rate === null ? '—' : `${reversal.rate}%`;
        scCoverage.textContent = coverage.rate === null ? '—' : `${coverage.rate}%`;
        if (affirmationFooter) {
          affirmationFooter.textContent = `${formatNumber(affirmation.numerator)} inferred affirmations / ${formatNumber(affirmation.denominator)} classified appeals`;
        }
        if (reversalFooter) {
          reversalFooter.textContent = `${formatNumber(reversal.numerator)} inferred reversals / ${formatNumber(reversal.denominator)} classified appeals`;
        }
        if (coverageFooter) {
          coverageFooter.textContent = `${formatNumber(coverage.numerator)} classified / ${formatNumber(coverage.denominator)} likely conviction appeals`;
        }
        renderSupremeCourtOutcomeCharts(stats);
        updateOverallCourtSummary();
        renderIcons();
      }
    }
  } catch (err) {
    // Conviction stats not available, keep section hidden or show empty values
    console.log('Supreme Court conviction stats not available:', err.message);
    overallCourtSnapshot.supremeAnalysis = null;
    updateOverallCourtSummary();
    const scConvictionRate = document.getElementById('kpi-sc-conviction-rate');
    const scReversalRate = document.getElementById('kpi-sc-conviction-reversal-rate');
    const scCoverage = document.getElementById('kpi-sc-outcome-coverage');
    if (scConvictionRate) scConvictionRate.textContent = '—';
    if (scReversalRate) scReversalRate.textContent = '—';
    if (scCoverage) scCoverage.textContent = '—';
  }
}

async function loadHighCourtOverview() {
  const grid = document.getElementById('high-court-kpi-grid');
  if (!grid) return;
  const chartSection = document.getElementById('hc-outcome-charts');
  try {
    const result = await API.get('/api/high-court/overview');
    const stats = result.data || {};
    const analysis = stats.conviction_analysis || {};
    overallCourtSnapshot.highCourt = stats;
    overallCourtSnapshot.highAnalysis = analysis;
    overallCourtSnapshot.highLoaded = true;
    updateOverallCourtSummary();
    const outcomes = analysis.outcomes || {};
    const upheld = outcomes.upheld || {};
    const reversed = outcomes.set_aside || {};
    const modified = outcomes.modified || {};
    const classified = Number(analysis.classified_appeals || 0);
    const candidates = Number(analysis.candidate_appeals || 0);
    document.getElementById('kpi-high-court-cases').textContent = formatNumber(stats.total_cases || 0);
    document.getElementById('kpi-high-court-judges').textContent = formatNumber(stats.total_judges || 0);
    document.getElementById('kpi-hc-conviction-rate').textContent =
      classified && upheld.rate != null ? `${upheld.rate}%` : '—';
    document.getElementById('kpi-hc-conviction-reversal-rate').textContent =
      classified && reversed.rate != null ? `${reversed.rate}%` : '—';
    document.getElementById('kpi-hc-outcome-coverage').textContent =
      analysis.classification_coverage_rate == null ? '—' : `${analysis.classification_coverage_rate}%`;
    document.getElementById('kpi-hc-conviction-footer').textContent =
      `${formatNumber(upheld.count || 0)} inferred affirmations / ${formatNumber(classified)} classified appeals`;
    document.getElementById('kpi-hc-reversal-footer').textContent =
      `${formatNumber(reversed.count || 0)} inferred reversals / ${formatNumber(classified)} classified appeals`;
    document.getElementById('kpi-hc-coverage-footer').textContent =
      `${formatNumber(classified)} classified / ${formatNumber(candidates)} likely conviction appeals`;
    grid.style.display = '';
    if (chartSection) {
      chartSection.style.display = '';
      renderHighCourtOutcomeCharts({ upheld, reversed, modified, classified, candidates, analysis });
    }
    renderIcons();
  } catch (err) {
    console.warn('High Court index totals are unavailable:', err.message);
    overallCourtSnapshot.highLoaded = true;
    overallCourtSnapshot.highFailed = true;
    updateOverallCourtSummary();
    grid.style.display = 'none';
    if (chartSection) chartSection.style.display = 'none';
  }
}

function renderHighCourtOutcomeCharts({ upheld, reversed, modified, classified, candidates, analysis }) {
  if (typeof Chart === 'undefined') return;
  const outcomeRows = [
    { label: 'Conviction upheld', count: Number(upheld.count || 0), color: '#34d399' },
    { label: 'Conviction set aside', count: Number(reversed.count || 0), color: '#fb7185' },
    { label: 'Conviction modified', count: Number(modified.count || 0), color: '#fbbf24' }
  ];
  const counts = outcomeRows.map((item) => item.count);
  const labels = outcomeRows.map((item) => item.label);
  const colors = outcomeRows.map((item) => item.color);
  const denominator = document.getElementById('hc-outcome-denominator');
  if (denominator) denominator.textContent = `Classified appeals: ${formatNumber(classified)}`;

  const note = document.getElementById('hc-outcome-method-note');
  if (note) {
    note.textContent = `The outcome shares use ${formatNumber(classified)} classified appeals as the denominator. Classification coverage is ${analysis.classification_coverage_rate == null ? 'not available' : `${analysis.classification_coverage_rate}%`} of ${formatNumber(candidates)} likely conviction appeals. Categories are estimated from case and disposition labels; they do not measure trial-court conviction rates.`;
  }

  const coverageSummary = document.getElementById('hc-coverage-summary');
  const unclassified = Math.max(candidates - classified, 0);
  if (coverageSummary) {
    coverageSummary.textContent = `${formatNumber(classified)} classified · ${formatNumber(unclassified)} without a classifiable outcome`;
  }

  const pieCanvas = document.getElementById('hc-outcome-pie-chart');
  if (pieCanvas) {
    if (hcOutcomePieChart) hcOutcomePieChart.destroy();
    hcOutcomePieChart = new Chart(pieCanvas.getContext('2d'), {
      type: 'doughnut',
      data: { labels, datasets: [{ data: counts, backgroundColor: colors, borderColor: '#111318', borderWidth: 3, hoverOffset: 8 }] },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '52%',
        plugins: {
          legend: { position: 'bottom', labels: { color: '#c4c7d0', padding: 18, usePointStyle: true, pointStyle: 'circle' } },
          tooltip: { callbacks: { label: (item) => {
            const share = classified ? (Number(item.raw || 0) / classified * 100).toFixed(1) : '0.0';
            return `${item.label}: ${formatNumber(item.raw)} (${share}% of classified appeals)`;
          } } }
        }
      }
    });
  }

  const countCanvas = document.getElementById('hc-outcome-count-chart');
  if (countCanvas) {
    if (hcOutcomeCountChart) hcOutcomeCountChart.destroy();
    hcOutcomeCountChart = new Chart(countCanvas.getContext('2d'), {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Appeals', data: counts, backgroundColor: colors, borderRadius: 6, maxBarThickness: 42 }] },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (item) => {
            const share = classified ? (Number(item.raw || 0) / classified * 100).toFixed(1) : '0.0';
            return `${formatNumber(item.raw)} appeals (${share}% of classified appeals)`;
          } } }
        },
        scales: {
          x: { beginAtZero: true, grid: { color: 'rgba(148, 163, 184, 0.12)' }, ticks: { color: '#a1a1aa', callback: (value) => formatNumber(value) } },
          y: { grid: { display: false }, ticks: { color: '#d4d4d8' } }
        }
      }
    });
  }

  const coverageCanvas = document.getElementById('hc-outcome-coverage-chart');
  if (coverageCanvas) {
    if (hcOutcomeCoverageChart) hcOutcomeCoverageChart.destroy();
    hcOutcomeCoverageChart = new Chart(coverageCanvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: ['Likely conviction appeals'],
        datasets: [
          { label: 'Classified outcome', data: [classified], backgroundColor: '#60a5fa', borderRadius: 5 },
          { label: 'No classifiable outcome', data: [unclassified], backgroundColor: '#52525b', borderRadius: 5 }
        ]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true, beginAtZero: true, grid: { color: 'rgba(148, 163, 184, 0.12)' }, ticks: { color: '#a1a1aa', callback: (value) => formatNumber(value) } },
          y: { stacked: true, grid: { display: false }, ticks: { color: '#d4d4d8' } }
        },
        plugins: {
          legend: { position: 'bottom', labels: { color: '#c4c7d0', padding: 14, usePointStyle: true, pointStyle: 'circle' } },
          tooltip: { callbacks: { label: (item) => `${item.dataset.label}: ${formatNumber(item.raw)}` } }
        }
      }
    });
  }
}

function getSupremeOutcomeCounts(stats) {
  const distribution = stats?.outcome_distribution || {};
  return {
    upheld: Number(distribution.CONVICTION_UPHELD || 0),
    setAside: Number(distribution.CONVICTION_SET_ASIDE || 0),
    modified: Number(distribution.CONVICTION_MODIFIED || 0),
    candidates: Number(stats?.conviction_appeal_candidates || 0)
  };
}

function renderSupremeCourtOutcomeCharts(stats) {
  const section = document.getElementById('sc-outcome-charts');
  if (!section || !stats) return;
  section.style.display = '';
  const counts = getSupremeOutcomeCounts(stats);
  const classified = counts.upheld + counts.setAside + counts.modified;
  const coverageRate = counts.candidates ? (classified / counts.candidates * 100) : null;
  renderOutcomeChartSet('sc', {
    upheld: counts.upheld,
    setAside: counts.setAside,
    modified: counts.modified,
    classified,
    candidates: counts.candidates,
    coverageRate,
    scope: 'Supreme Court'
  });
}

function updateOverallCourtSummary() {
  const status = document.getElementById('overall-court-data-status');
  if (!status) return;
  if (!overallCourtSnapshot.highLoaded || !overallCourtSnapshot.supremeLoaded) {
    status.textContent = 'Loading High Court and Supreme Court totals';
    return;
  }

  const high = overallCourtSnapshot.highCourt || {};
  const supreme = overallCourtSnapshot.supremeCourt || {};
  const totalCases = Number(high.total_cases || 0) + Number(supreme.total_cases || 0);
  const totalJudges = Number(high.total_judges || 0) + Number(supreme.total_judges || 0);
  document.getElementById('kpi-overall-cases').textContent = formatNumber(totalCases);
  document.getElementById('kpi-overall-judges').textContent = formatNumber(totalJudges);
  status.textContent = (overallCourtSnapshot.highFailed || overallCourtSnapshot.supremeFailed)
    ? 'Partial totals: one court could not be loaded'
    : 'Combined court records';

  const highOutcomes = overallCourtSnapshot.highAnalysis?.outcomes || {};
  const scCounts = getSupremeOutcomeCounts(overallCourtSnapshot.supremeAnalysis);
  const upheld = Number(highOutcomes.upheld?.count || 0) + scCounts.upheld;
  const setAside = Number(highOutcomes.set_aside?.count || 0) + scCounts.setAside;
  const modified = Number(highOutcomes.modified?.count || 0) + scCounts.modified;
  const classified = upheld + setAside + modified;
  const candidates = Number(overallCourtSnapshot.highAnalysis?.candidate_appeals || 0) + scCounts.candidates;
  const coverageRate = candidates ? classified / candidates * 100 : null;
  renderOutcomeChartSet('overall', { upheld, setAside, modified, classified, candidates, coverageRate, scope: 'both courts' });
}

function renderOutcomeChartSet(prefix, { upheld, setAside, modified, classified, candidates, coverageRate, scope }) {
  if (typeof Chart === 'undefined') return;
  const labels = ['Conviction upheld', 'Conviction set aside', 'Conviction modified'];
  const values = [upheld, setAside, modified];
  const colors = ['#34d399', '#fb7185', '#fbbf24'];
  const denominator = document.getElementById(`${prefix}-outcome-denominator`);
  if (denominator) denominator.textContent = `Classified appeals: ${formatNumber(classified)}`;
  const note = document.getElementById(`${prefix}-outcome-method-note`);
  if (note) {
    let outcomeScope = `Outcome shares use ${formatNumber(classified)} classified ${scope} appeals as the denominator.`;
    if (prefix === 'overall') {
      const available = [];
      if (overallCourtSnapshot.highAnalysis) available.push('High Court');
      if (overallCourtSnapshot.supremeAnalysis) available.push('Supreme Court');
      if (available.length < 2) {
        outcomeScope = `${available.join(' and ') || 'No court'} outcome counts only; the other court’s outcome analysis is unavailable. The available counts use ${formatNumber(classified)} classified appeals as the denominator.`;
      }
    }
    note.textContent = `${outcomeScope} Classification coverage is ${coverageRate == null ? 'not available' : `${coverageRate.toFixed(1)}%`} of ${formatNumber(candidates)} likely conviction appeals. These are estimated appeal outcomes, not trial-court conviction rates.`;
  }
  const coverageSummary = document.getElementById(`${prefix}-coverage-summary`);
  if (coverageSummary) coverageSummary.textContent = `${formatNumber(classified)} classified · ${formatNumber(Math.max(candidates - classified, 0))} without a classifiable outcome`;

  const specs = [
    { key: 'pie', type: 'doughnut', canvas: `${prefix}-outcome-pie-chart` },
    { key: 'count', type: 'bar', canvas: `${prefix}-outcome-count-chart` },
    { key: 'coverage', type: 'bar', canvas: `${prefix}-outcome-coverage-chart` }
  ];
  for (const spec of specs) {
    const canvas = document.getElementById(spec.canvas);
    if (!canvas) continue;
    const instanceKey = `${prefix}-${spec.key}`;
    if (dashboardOutcomeCharts[instanceKey]) dashboardOutcomeCharts[instanceKey].destroy();
    let config;
    if (spec.key === 'pie') {
      config = {
        type: spec.type,
        data: { labels, datasets: [{ data: values, backgroundColor: colors, borderColor: '#111318', borderWidth: 3, hoverOffset: 8 }] },
        options: {
          responsive: true, maintainAspectRatio: false, cutout: '52%',
          plugins: {
            legend: { position: 'bottom', labels: { color: '#c4c7d0', padding: 14, usePointStyle: true, pointStyle: 'circle' } },
            tooltip: { callbacks: { label: (item) => `${item.label}: ${formatNumber(item.raw)} (${classified ? (item.raw / classified * 100).toFixed(1) : '0.0'}% of classified appeals)` } }
          }
        }
      };
    } else if (spec.key === 'count') {
      config = {
        type: spec.type,
        data: { labels, datasets: [{ label: 'Appeals', data: values, backgroundColor: colors, borderRadius: 6, maxBarThickness: 42 }] },
        options: {
          indexAxis: 'y', responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false }, tooltip: { callbacks: { label: (item) => `${formatNumber(item.raw)} appeals (${classified ? (item.raw / classified * 100).toFixed(1) : '0.0'}% of classified appeals)` } } },
          scales: { x: { beginAtZero: true, grid: { color: 'rgba(148, 163, 184, 0.12)' }, ticks: { color: '#a1a1aa', callback: (value) => formatNumber(value) } }, y: { grid: { display: false }, ticks: { color: '#d4d4d8' } } }
        }
      };
    } else {
      config = {
        type: spec.type,
        data: { labels: [scope === 'both courts' ? 'Both courts' : scope], datasets: [
          { label: 'Classified outcome', data: [classified], backgroundColor: '#60a5fa', borderRadius: 5 },
          { label: 'No classifiable outcome', data: [Math.max(candidates - classified, 0)], backgroundColor: '#52525b', borderRadius: 5 }
        ] },
        options: {
          indexAxis: 'y', responsive: true, maintainAspectRatio: false,
          scales: { x: { stacked: true, beginAtZero: true, grid: { color: 'rgba(148, 163, 184, 0.12)' }, ticks: { color: '#a1a1aa', callback: (value) => formatNumber(value) } }, y: { stacked: true, grid: { display: false }, ticks: { color: '#d4d4d8' } } },
          plugins: { legend: { position: 'bottom', labels: { color: '#c4c7d0', padding: 12, usePointStyle: true, pointStyle: 'circle' } }, tooltip: { callbacks: { label: (item) => `${item.dataset.label}: ${formatNumber(item.raw)}` } } }
        }
      };
    }
    dashboardOutcomeCharts[instanceKey] = new Chart(canvas.getContext('2d'), config);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  loadDashboard();
  loadHighCourtOverview();
  loadSupremeCourtOverview();
  const refreshBtn = document.getElementById('refresh-dashboard-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      showToast('Refreshing dashboard...', 'info');
      loadDashboard();
      loadHighCourtOverview();
      loadSupremeCourtOverview();
    });
  }
});
