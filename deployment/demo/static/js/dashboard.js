/**
 * Dashboard Logic - eCourts Judicial Intelligence
 */

let judgeChartInstance = null;
let demoOutcomeCharts = {};
const demoCourtSnapshot = { high: null, supreme: null, highAnalysis: null, supremeAnalysis: null, highLoaded: false, supremeLoaded: false, highFailed: false, supremeFailed: false };

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

async function loadHighCourtOverview() {
  try {
    const response = await API.get('/api/high-court/overview');
    demoCourtSnapshot.highLoaded = true;
    demoCourtSnapshot.high = response.data || null;
    const total = response.data?.total_cases;
    if (total === null || total === undefined) {
      updateDemoOverall();
      return;
    }
    document.getElementById('kpi-hc-records').textContent = formatNumber(total);
    document.getElementById('kpi-hc-judges').textContent = formatNumber(response.data.total_judges);
    const analysis = response.data.conviction_analysis || {};
    demoCourtSnapshot.highAnalysis = analysis;
    const outcomes = analysis.outcomes || {};
    const classified = Number(analysis.classified_appeals || 0);
    const cards = [
      ['upheld', 'kpi-hc-upheld-rate', 'kpi-hc-upheld-count'],
      ['set_aside', 'kpi-hc-set-aside-rate', 'kpi-hc-set-aside-count'],
      ['modified', 'kpi-hc-modified-rate', 'kpi-hc-modified-count'],
    ];
    cards.forEach(([key, rateId, countId]) => {
      const outcome = outcomes[key] || {};
      const rate = outcome.rate;
      document.getElementById(rateId).textContent =
        rate === null || rate === undefined ? '—' : `${Number(rate).toFixed(1)}%`;
      document.getElementById(countId).textContent =
        `${formatNumber(outcome.count || 0)} / ${formatNumber(classified)} classified appeals`;
    });
    const coverage = analysis.classification_coverage_rate;
    document.getElementById('hc-outcomes-coverage').textContent =
      `${formatNumber(classified)} of ${formatNumber(analysis.candidate_appeals || 0)} likely accused-versus-State criminal appeals classified` +
      (coverage === null || coverage === undefined ? '.' : ` (${Number(coverage).toFixed(1)}%).`) +
      ' These are estimated appeal outcomes, not trial-court conviction rates.';
    document.getElementById('hc-kpi-grid').style.display = 'grid';
    document.getElementById('hc-outcomes-header').style.display = 'flex';
    document.getElementById('hc-outcome-kpi-grid').style.display = 'grid';
    document.getElementById('hc-outcomes-coverage').style.display = 'block';
    const outcomesSection = document.getElementById('demo-hc-chart-section');
    if (outcomesSection) outcomesSection.style.display = '';
    renderDemoCourtCharts('hc', {
      upheld: Number(outcomes.upheld?.count || 0),
      setAside: Number(outcomes.set_aside?.count || 0),
      modified: Number(outcomes.modified?.count || 0),
      classified,
      candidates: Number(analysis.candidate_appeals || 0),
      scope: 'High Court'
    });
    updateDemoOverall();
    renderIcons();
  } catch (err) {
    demoCourtSnapshot.highLoaded = true;
    demoCourtSnapshot.highFailed = true;
    updateDemoOverall();
    console.log('High Court record count not available:', err.message);
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
    demoCourtSnapshot.supremeLoaded = true;
    demoCourtSnapshot.supreme = res.data || null;
    updateDemoOverall();
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
    demoCourtSnapshot.supremeLoaded = true;
    demoCourtSnapshot.supremeFailed = true;
    updateDemoOverall();
  }

  // Load conviction statistics
  try {
    const res = await API.get('/api/supreme-court/conviction-stats');
    if (res.data) {
      const stats = res.data;
      demoCourtSnapshot.supremeAnalysis = stats;
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
        const section = document.getElementById('demo-sc-chart-section');
        if (section) section.style.display = '';
        const distribution = stats.outcome_distribution || {};
        renderDemoCourtCharts('sc', {
          upheld: Number(distribution.CONVICTION_UPHELD || 0),
          setAside: Number(distribution.CONVICTION_SET_ASIDE || 0),
          modified: Number(distribution.CONVICTION_MODIFIED || 0),
          classified: Number(affirmation.denominator || 0),
          candidates: Number(stats.conviction_appeal_candidates || 0),
          scope: 'Supreme Court'
        });
        updateDemoOverall();
        renderIcons();
      }
    }
  } catch (err) {
    // Conviction stats not available, keep section hidden or show empty values
    console.log('Supreme Court conviction stats not available:', err.message);
    demoCourtSnapshot.supremeAnalysis = null;
    updateDemoOverall();
    const scConvictionRate = document.getElementById('kpi-sc-conviction-rate');
    const scReversalRate = document.getElementById('kpi-sc-conviction-reversal-rate');
    const scCoverage = document.getElementById('kpi-sc-outcome-coverage');
    if (scConvictionRate) scConvictionRate.textContent = '—';
    if (scReversalRate) scReversalRate.textContent = '—';
    if (scCoverage) scCoverage.textContent = '—';
  }
}

function updateDemoOverall() {
  if (!demoCourtSnapshot.highLoaded || !demoCourtSnapshot.supremeLoaded) return;
  const high = demoCourtSnapshot.high || {};
  const supreme = demoCourtSnapshot.supreme || {};
  const cases = Number(high.total_cases || 0) + Number(supreme.total_cases || 0);
  const judges = Number(high.total_judges || 0) + Number(supreme.total_judges || 0);
  document.getElementById('demo-overall-cases').textContent = formatNumber(cases);
  document.getElementById('demo-overall-judges').textContent = formatNumber(judges);
  document.getElementById('demo-overall-status').textContent =
    (demoCourtSnapshot.highFailed || demoCourtSnapshot.supremeFailed) ? 'Partial totals: one court could not be loaded' : 'Combined court records';

  const hc = demoCourtSnapshot.highAnalysis?.outcomes || {};
  const sc = demoCourtSnapshot.supremeAnalysis?.outcome_distribution || {};
  const totals = {
    upheld: Number(hc.upheld?.count || 0) + Number(sc.CONVICTION_UPHELD || 0),
    setAside: Number(hc.set_aside?.count || 0) + Number(sc.CONVICTION_SET_ASIDE || 0),
    modified: Number(hc.modified?.count || 0) + Number(sc.CONVICTION_MODIFIED || 0)
  };
  totals.classified = totals.upheld + totals.setAside + totals.modified;
  totals.candidates = Number(demoCourtSnapshot.highAnalysis?.candidate_appeals || 0) + Number(demoCourtSnapshot.supremeAnalysis?.conviction_appeal_candidates || 0);
  totals.scope = 'both courts';
  renderDemoCourtCharts('overall', totals);
  const note = document.getElementById('demo-overall-note');
  if (note) {
    const ready = [demoCourtSnapshot.highAnalysis, demoCourtSnapshot.supremeAnalysis].filter(Boolean).length;
    note.textContent = `${ready === 2 ? 'Combined High Court and Supreme Court' : ready === 1 ? 'Only one court’s outcome analysis is available' : 'Outcome analysis is not available'}; ${formatNumber(totals.classified)} classified appeals form the denominator. These are estimated appeal outcomes, not trial-court conviction rates.`;
  }
}

function renderDemoCourtCharts(prefix, { upheld = 0, setAside = 0, modified = 0, classified = 0, candidates = 0, scope = '' }) {
  if (typeof Chart === 'undefined') return;
  const chartPrefix = `demo-${prefix}`;
  const labels = ['Conviction upheld', 'Conviction set aside', 'Conviction modified'];
  const values = [Number(upheld || 0), Number(setAside || 0), Number(modified || 0)];
  const colors = ['#34d399', '#fb7185', '#fbbf24'];
  const denominator = Number(classified || 0);
  const possible = Number(candidates || 0);
  const unclassified = Math.max(possible - denominator, 0);
  const denominatorNode = document.getElementById(`${chartPrefix}-denominator`);
  if (denominatorNode) denominatorNode.textContent = `Classified appeals: ${formatNumber(denominator)}`;
  const coverageText = document.getElementById(`${chartPrefix}-coverage-text`);
  if (coverageText) coverageText.textContent = `${formatNumber(denominator)} classified · ${formatNumber(unclassified)} without a classifiable outcome`;
  const note = document.getElementById(`${chartPrefix}-note`);
  if (note && prefix !== 'overall') note.textContent = `${scope} outcome shares use ${formatNumber(denominator)} classified appeals as the denominator. Classification coverage is ${possible ? (denominator / possible * 100).toFixed(1) : '0.0'}% of ${formatNumber(possible)} likely conviction appeals. Outcomes are estimates from case and disposition labels.`;

  const specs = [
    { kind: 'pie', id: `${chartPrefix}-pie` },
    { kind: 'count', id: `${chartPrefix}-count` },
    { kind: 'coverage', id: `${chartPrefix}-coverage` }
  ];
  specs.forEach(({ kind, id }) => {
    const canvas = document.getElementById(id);
    if (!canvas) return;
    const key = `${prefix}-${kind}`;
    if (demoOutcomeCharts[key]) demoOutcomeCharts[key].destroy();
    const tooltipPercent = (value) => denominator ? (Number(value || 0) / denominator * 100).toFixed(1) : '0.0';
    let config;
    if (kind === 'pie') {
      config = { type: 'doughnut', data: { labels, datasets: [{ data: values, backgroundColor: colors, borderColor: '#111318', borderWidth: 3, hoverOffset: 7 }] }, options: { responsive: true, maintainAspectRatio: false, cutout: '52%', plugins: { legend: { position: 'bottom', labels: { color: '#c4c7d0', padding: 13, usePointStyle: true } }, tooltip: { callbacks: { label: (item) => `${item.label}: ${formatNumber(item.raw)} (${tooltipPercent(item.raw)}% of classified appeals)` } } } } };
    } else if (kind === 'count') {
      config = { type: 'bar', data: { labels, datasets: [{ label: 'Appeals', data: values, backgroundColor: colors, borderRadius: 6, maxBarThickness: 40 }] }, options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: (item) => `${formatNumber(item.raw)} appeals (${tooltipPercent(item.raw)}% of classified appeals)` } } }, scales: { x: { beginAtZero: true, grid: { color: 'rgba(148, 163, 184, 0.12)' }, ticks: { color: '#a1a1aa', callback: (value) => formatNumber(value) } }, y: { grid: { display: false }, ticks: { color: '#d4d4d8' } } } } };
    } else {
      config = { type: 'bar', data: { labels: [scope || 'Court appeals'], datasets: [{ label: 'Classified outcome', data: [denominator], backgroundColor: '#60a5fa', borderRadius: 5 }, { label: 'No classifiable outcome', data: [unclassified], backgroundColor: '#52525b', borderRadius: 5 }] }, options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, scales: { x: { stacked: true, beginAtZero: true, grid: { color: 'rgba(148, 163, 184, 0.12)' }, ticks: { color: '#a1a1aa', callback: (value) => formatNumber(value) } }, y: { stacked: true, grid: { display: false }, ticks: { color: '#d4d4d8' } } }, plugins: { legend: { position: 'bottom', labels: { color: '#c4c7d0', padding: 12, usePointStyle: true } }, tooltip: { callbacks: { label: (item) => `${item.dataset.label}: ${formatNumber(item.raw)}` } } } } };
    }
    demoOutcomeCharts[key] = new Chart(canvas.getContext('2d'), config);
  });
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
