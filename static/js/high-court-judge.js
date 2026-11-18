/**
 * Judge Dossier Logic - eCourts Judicial Intelligence
 */

let judgeData = null;
let activityChartInstance = null;
let currentRange = 'all';

async function loadJudgeDossier() {
  initSidebar('judges');

  const params = new URLSearchParams(window.location.search);
  const judgeName = params.get('name');
  const profileSource = params.get('source');

  if (!judgeName) {
    showToast('No judge specified. Redirecting to directory...', 'error');
    setTimeout(() => {
      window.location.href = '/judges.html';
    }, 1500);
    return;
  }

  document.getElementById('breadcrumb-judge-name').textContent = judgeName;
  document.getElementById('judge-title-name').textContent = judgeName;
  if (profileSource !== 'high_court') loadJudgeDecisions(judgeName);

  try {
    const res = await API.get('/api/judge', { name: judgeName, source: profileSource });
    judgeData = res.data;

    if (judgeData.data_source === 'high_court_case_index') {
      document.getElementById('judge-status-badge').textContent = 'Scraped Case Index';
      document.getElementById('judge-profile-subtitle').textContent = 'High Court cases and estimated criminal appeal outcomes from scraped records';
      document.getElementById('judge-total-label').textContent = 'High Court Cases';
      document.getElementById('judge-total-footer').textContent = 'Scraped case records in the index';
      document.getElementById('judge-first-label').textContent = 'Earliest Decision';
      document.getElementById('judge-first-footer').textContent = 'Oldest indexed case decision';
      document.getElementById('judge-last-label').textContent = 'Latest Decision';
      document.getElementById('judge-last-footer').textContent = 'Most recent indexed case decision';
      document.getElementById('judge-activity-panel').style.display = 'none';
      document.getElementById('judge-courts-panel').style.display = 'none';
      document.getElementById('judge-pdfs-panel').style.display = 'none';
      renderHighCourtDecisionAnalysis(
        judgeData.conviction_analysis || {},
        judgeData.analysis_summary || {}
      );
      setHighCourtDecisionNotice(judgeData.conviction_analysis || {});
    }

    // 1. Populate Summary KPIs
    document.getElementById('judge-kpi-total').textContent = formatNumber(judgeData.summary.total_pdfs);
    document.getElementById('judge-kpi-first').textContent = formatDate(judgeData.summary.first_seen);
    document.getElementById('judge-kpi-last').textContent = formatDate(judgeData.summary.last_seen);
    document.getElementById('judge-kpi-courts').textContent = formatNumber(judgeData.summary.courts_count);

    // 2. Render Activity Chart
    renderActivityChart(judgeData.activity || []);

    // 3. Render Courts Table
    renderCourtsTable(judgeData.courts || []);

    // 4. Render PDFs Table
    renderPdfsTable(judgeData.pdfs || []);

    renderIcons();
  } catch (err) {
    console.error('Failed to load judge details:', err);
    showToast(`Failed to load dossier: ${err.message}`, 'error');
    document.getElementById('judge-title-name').textContent = judgeName;
  }
}

function renderActivityChart(activity) {
  const canvas = document.getElementById('judge-activity-timeline-chart');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  if (activityChartInstance) {
    activityChartInstance.destroy();
  }

  // Filter based on selected range
  let filtered = [...activity];
  if (currentRange === '7') {
    filtered = filtered.slice(-7);
  } else if (currentRange === '14') {
    filtered = filtered.slice(-14);
  }

  const labels = filtered.map(a => formatDate(a.date));
  const rawDates = filtered.map(a => a.date);
  const counts = filtered.map(a => a.pdf_count);

  activityChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        label: 'Cause List Documents',
        data: counts,
        backgroundColor: 'rgba(59, 130, 246, 0.75)',
        hoverBackgroundColor: '#3b82f6',
        borderColor: '#3b82f6',
        borderWidth: 1,
        borderRadius: 4,
        maxBarThickness: 36
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
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
              return `Cause List Date: ${rawDates[idx]}`;
            },
            label: function(item) {
              return `PDFs Published: ${item.raw}`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: {
            display: false
          },
          ticks: {
            color: '#71717a',
            font: { family: 'JetBrains Mono', size: 11 }
          }
        },
        y: {
          beginAtZero: true,
          grid: {
            color: '#1f1f23',
            drawBorder: false
          },
          ticks: {
            precision: 0,
            color: '#71717a',
            font: { family: 'JetBrains Mono', size: 11 }
          }
        }
      }
    }
  });
}

function renderCourtsTable(courts) {
  const tbody = document.getElementById('judge-courts-tbody');
  if (!tbody) return;

  if (courts.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="4" style="text-align: center; color: var(--text-tertiary); padding: 24px;">
          No court assignments recorded for this judge.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = courts.map(c => `
    <tr>
      <td class="cell-primary">${escapeHTML(c.state_name)}</td>
      <td style="color: var(--text-tertiary);">${escapeHTML(c.district_code)}</td>
      <td>
        <div style="font-weight: 500;">${escapeHTML(c.court_name)}</div>
        <div style="font-size: 11px; color: var(--text-tertiary);" class="cell-mono">Court Code: ${c.court_code}</div>
      </td>
      <td style="text-align: right;">
        <span class="badge badge-mono badge-blue">${formatNumber(c.pdf_count)}</span>
      </td>
    </tr>
  `).join('');
}

function renderPdfsTable(pdfs) {
  const tbody = document.getElementById('judge-pdfs-tbody');
  const badge = document.getElementById('judge-pdf-count-badge');
  if (!tbody) return;

  badge.textContent = `${formatNumber(pdfs.length)} Documents`;

  if (pdfs.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="5" style="text-align: center; color: var(--text-tertiary); padding: 32px;">
          No associated PDF files found for this judge.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = pdfs.map(pdf => {
    const isDownloaded = pdf.has_file;
    const storageBadge = isDownloaded
      ? `<span class="badge badge-mono badge-emerald" title="File verified on disk"><i data-lucide="check" style="width: 11px; height: 11px;"></i> ${formatFileSize(pdf.file_size)}</span>`
      : `<span class="badge badge-mono badge-amber" title="Record in DB, file not cached locally">Metadata only</span>`;

    const openAction = isDownloaded
      ? `<a href="/pdf-viewer.html?file=${encodeURIComponent(pdf.filename)}" class="btn btn-outline btn-sm">
           <i data-lucide="external-link" style="width: 12px; height: 12px;"></i>
           <span>Open</span>
         </a>`
      : `<button class="btn btn-outline btn-sm" disabled title="PDF not yet downloaded">Open</button>`;

    const downloadAction = isDownloaded
      ? `<a href="/api/pdf/${encodeURIComponent(pdf.filename)}?download=1" class="btn btn-secondary btn-sm" download>
           <i data-lucide="download" style="width: 12px; height: 12px;"></i>
           <span>Download</span>
         </a>`
      : `<button class="btn btn-secondary btn-sm" disabled title="PDF not yet downloaded">Download</button>`;

    return `
      <tr>
        <td>
          <div style="display: flex; align-items: center; gap: 8px;">
            <i data-lucide="file-text" style="width: 15px; height: 15px; color: var(--text-tertiary); flex-shrink: 0;"></i>
            <div style="min-width: 0;">
              <div class="cell-mono cell-primary" style="font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 320px;" title="${escapeHTML(pdf.filename)}">
                ${escapeHTML(pdf.filename)}
              </div>
            </div>
          </div>
        </td>
        <td class="cell-mono" style="color: var(--text-tertiary);">${formatDate(pdf.cause_list_date)}</td>
        <td>
          <div style="font-size: 12px; color: var(--text-secondary);">${escapeHTML(pdf.court_name)}</div>
        </td>
        <td>${storageBadge}</td>
        <td style="text-align: right;">
          <div style="display: inline-flex; align-items: center; gap: 6px;">
            ${openAction}
            ${downloadAction}
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

async function loadJudgeDecisions(judgeName) {
  const notice = document.getElementById('judge-decisions-notice');
  const analysis = document.getElementById('judge-decisions-analysis');
  try {
    const result = await API.get('/api/high-court/judge-decisions', {
      name: judgeName,
      page: 1,
      limit: 1,
      summary_only: true
    });
    const conviction = result.conviction_analysis || {};
    renderHighCourtDecisionAnalysis(conviction, result.summary || {});
    setHighCourtDecisionNotice(conviction);
  } catch (err) {
    console.error('Failed to load High Court appeal outcomes:', err);
    notice.textContent = err.message || 'Criminal appeal outcomes could not be loaded.';
    analysis.innerHTML = '';
  }
}

function setHighCourtDecisionNotice(conviction = {}) {
  const notice = document.getElementById('judge-decisions-notice');
  const classified = Number(conviction.classified_appeals || 0);
  const candidates = Number(conviction.candidate_appeals || 0);
  notice.textContent = classified
    ? `Estimated from scraped appeal dispositions: ${formatNumber(classified)} classified of ${formatNumber(candidates)} likely criminal appeals`
    : `No classifiable scraped appeal outcomes for this judge (${formatNumber(candidates)} possible appeals checked).`;
}

function renderHighCourtDecisionAnalysis(conviction = {}, summary = {}) {
  const analysis = document.getElementById('judge-decisions-analysis');
  const outcomes = conviction.outcomes || {};
  const classified = Number(conviction.classified_appeals || 0);
  const outcomeCards = [
    ['upheld', 'Conviction upheld'],
    ['set_aside', 'Conviction set aside'],
    ['modified', 'Conviction modified'],
  ].map(([key, label]) => {
    const outcome = outcomes[key] || {};
    const rate = outcome.rate;
    const hasRate = classified > 0 && rate !== null && rate !== undefined;
    const rateLabel = !hasRate
      ? 'No data'
      : `${Number(rate).toFixed(1)}%`;
    return `
      <article class="high-court-outcome-card high-court-outcome-${key}">
        <div class="high-court-outcome-card-top">
          <span>${label}</span>
          <strong>${rateLabel}</strong>
        </div>
        <div class="high-court-rate-track" role="img" aria-label="${rateLabel} ${label.toLowerCase()}">
          <span style="width:${hasRate ? Math.max(0, Math.min(100, Number(rate))) : 0}%"></span>
        </div>
        <small>${classified ? `${formatNumber(outcome.count || 0)} of ${formatNumber(classified)} classified appeals` : 'No classified scraped appeal outcomes'}</small>
      </article>
    `;
  }).join('');
  const median = summary.median_duration_days === null || summary.median_duration_days === undefined
    ? 'No data'
    : `${formatNumber(summary.median_duration_days)} days`;
  const maximum = summary.max_duration_days === null || summary.max_duration_days === undefined
    ? 'No data'
    : `${formatNumber(summary.max_duration_days)} days`;

  analysis.innerHTML = `
    <div class="high-court-analysis-layout">
      <section class="high-court-analysis-section">
        <div class="high-court-analysis-heading">
          <div>
            <span class="high-court-eyebrow">OUTCOME BREAKDOWN</span>
            <h3>Classified criminal appeals</h3>
          </div>
          <span class="high-court-analysis-total">${formatNumber(classified)} analyzed</span>
        </div>
        <div class="high-court-outcome-rates">
          ${outcomeCards}
        </div>
      </section>
      <section class="high-court-time-section">
        <div class="high-court-analysis-heading">
          <div>
            <span class="high-court-eyebrow">CASE TIMING</span>
            <h3>Filing to decision</h3>
          </div>
        </div>
        <div class="high-court-time-rates">
          <article class="high-court-time-card">
            <span class="high-court-time-icon"><i data-lucide="clock-3"></i></span>
            <div><small>Median duration</small><strong>${median}</strong></div>
          </article>
          <article class="high-court-time-card">
            <span class="high-court-time-icon"><i data-lucide="timer"></i></span>
            <div><small>Longest duration</small><strong>${maximum}</strong></div>
          </article>
        </div>
        <p class="high-court-time-caption">${formatNumber(summary.duration_records || 0)} records with both filing and decision dates</p>
      </section>
    </div>
  `;
  renderIcons();
}

document.addEventListener('DOMContentLoaded', () => {
  loadJudgeDossier();

  // Date range filter buttons
  document.querySelectorAll('#date-filter-group button').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#date-filter-group button').forEach(b => {
        b.classList.remove('active', 'btn-secondary');
        b.classList.add('btn-outline');
      });
      btn.classList.add('active', 'btn-secondary');
      btn.classList.remove('btn-outline');

      currentRange = btn.dataset.range;
      if (judgeData && judgeData.activity) {
        renderActivityChart(judgeData.activity);
      }
    });
  });
});
