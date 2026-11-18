function safeJudgmentUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : "";
  } catch {
    return "";
  }
}

// Format duration from days to years/days
function formatDuration(days) {
  if (!days || days === 0) return "—";
  const years = days / 365.25;
  const yearsInt = Math.floor(years);
  const remainingDays = Math.round((years - yearsInt) * 365.25);

  if (yearsInt === 0) {
    return `${remainingDays} days`;
  } else if (remainingDays === 0) {
    return `${yearsInt} year${yearsInt !== 1 ? 's' : ''}`;
  } else {
    return `${yearsInt} year${yearsInt !== 1 ? 's' : ''}, ${remainingDays} days`;
  }
}

// Get case type badge from title
function getCaseTypeBadge(caseTitle) {
  if (!caseTitle) return '<span class="badge badge-gray">UNKNOWN</span>';

  const titleUpper = caseTitle.toUpperCase();
  const criminalIndicators = ['STATE OF', 'CRIMINAL', 'CRL.', 'IPC ', 'CRPC '];
  const civilIndicators = ['VSB', 'VST', ' COMPANY', ' CORPORATION', ' BANK', ' AUTHORITY', ' W.', ' W.S.'];

  const isCriminal = criminalIndicators.some(indicator => titleUpper.includes(indicator));
  const isCivil = civilIndicators.some(indicator => titleUpper.includes(indicator));

  if (isCriminal) {
    return '<span class="badge badge-danger">LIKELY CRIMINAL</span>';
  } else if (isCivil) {
    return '<span class="badge badge-primary">LIKELY CIVIL</span>';
  } else {
    return '<span class="badge badge-gray">OTHER</span>';
  }
}

// Format number with commas
function formatNumber(num) {
  return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

// Format date
function formatDate(dateStr) {
  if (!dateStr) return "—";
  try {
    const options = { year: 'numeric', month: 'short', day: 'numeric' };
    return new Date(dateStr).toLocaleDateString(undefined, options);
  } catch {
    return dateStr;
  }
}

const convictionOutcomeLabels = {
  CONVICTION_UPHELD: "Conviction affirmed",
  CONVICTION_MODIFIED: "Conviction modified",
  CONVICTION_SET_ASIDE: "Conviction set aside"
};

function generateConvictionAnalysis(summary, cases, convictionAnalysis) {
  const totalCases = convictionAnalysis.total_cases ?? (cases || []).length;
  const criminalCases = convictionAnalysis.criminal_cases ?? 0;
  const civilCases = convictionAnalysis.civil_cases ?? 0;
  const otherCases = convictionAnalysis.other_cases ?? 0;
  const affirmation = convictionAnalysis.conviction_affirmation_rate || {};
  const reversal = convictionAnalysis.conviction_reversal_rate || {};
  const coverage = convictionAnalysis.outcome_classification_coverage || {};
  const casePercentage = count => totalCases ? (count / totalCases) * 100 : 0;
  const showRate = metric => metric.rate === null || metric.rate === undefined
    ? "Not available"
    : `${metric.rate}%`;

  return `
    <div class="conviction-analysis-content">
      <section class="verified-rate-grid" aria-label="Estimated conviction appeal metrics">
        <div class="verified-rate-card affirmation-rate">
          <div class="metric-label">Estimated conviction affirmation rate</div>
          <div class="metric-value">${showRate(affirmation)}</div>
          <div class="metric-description">
            ${formatNumber(affirmation.numerator || 0)} fully upheld /
            ${formatNumber(affirmation.denominator || 0)} eligible final appeals
          </div>
        </div>
        <div class="verified-rate-card reversal-rate">
          <div class="metric-label">Estimated conviction reversal rate</div>
          <div class="metric-value">${showRate(reversal)}</div>
          <div class="metric-description">
            ${formatNumber(reversal.numerator || 0)} set aside /
            ${formatNumber(reversal.denominator || 0)} eligible final appeals
          </div>
        </div>
        <div class="verified-rate-card coverage-rate">
          <div class="metric-label">Outcome classification coverage</div>
          <div class="metric-value">${showRate(coverage)}</div>
          <div class="metric-description">
            ${formatNumber(coverage.numerator || 0)} classified outcomes /
            ${formatNumber(coverage.denominator || 0)} likely conviction appeals
          </div>
        </div>
      </section>

      <section class="judge-outcome-chart-section" aria-label="Conviction outcome charts">
        <div class="judge-outcome-chart-intro">
          <h3>Appeal outcomes for this judge</h3>
          <p>Shares use classified conviction appeals as the denominator. The coverage chart shows likely appeals that do not have a classifiable outcome.</p>
          <span class="judge-outcome-chart-denominator" id="sc-judge-outcome-chart-denominator">Classified appeals: —</span>
        </div>
        <div class="judge-outcome-chart-grid" id="sc-judge-outcome-chart-grid">
          <article class="judge-outcome-chart-card"><h4>Outcome share</h4><p>Percent of classified appeals.</p><div class="judge-outcome-chart-canvas"><canvas id="sc-judge-outcome-share-chart" role="img" aria-label="Pie chart of this judge’s Supreme Court appeal outcomes"></canvas></div></article>
          <article class="judge-outcome-chart-card"><h4>Appeals by outcome</h4><p>Number of classified appeals in each category.</p><div class="judge-outcome-chart-canvas"><canvas id="sc-judge-outcome-count-chart" role="img" aria-label="Bar chart of this judge’s Supreme Court appeal outcome counts"></canvas></div></article>
          <article class="judge-outcome-chart-card"><h4>Classification coverage</h4><p>Likely conviction appeals with and without a classifiable outcome.</p><div class="judge-outcome-chart-canvas"><canvas id="sc-judge-outcome-coverage-chart" role="img" aria-label="Bar chart of this judge’s classified and unclassified appeals"></canvas></div><small id="sc-judge-outcome-chart-coverage-text"></small></article>
        </div>
      </section>

      <section class="analysis-group">
        <div class="analysis-group-heading">
          <h3>Case type</h3>
          <p>Estimated from case-title keywords</p>
        </div>
        <div class="analysis-type-grid">
          ${[
            ['Likely criminal', criminalCases, 'criminal'],
            ['Likely civil', civilCases, 'civil'],
            ['Other / unclear', otherCases, 'other']
          ].map(([label, count, type]) => `
            <div class="analysis-metric type-${type}">
              <div class="metric-label">${label}</div>
              <div class="metric-value">${formatNumber(count)} <span>(${casePercentage(count).toFixed(1)}%)</span></div>
              <div class="metric-progress" role="img" aria-label="${label}: ${casePercentage(count).toFixed(1)} percent of records">
                <div class="metric-progress-bar" style="width: ${casePercentage(count)}%"></div>
              </div>
            </div>
          `).join('')}
        </div>
      </section>

      <section class="analysis-group">
        <div class="analysis-group-heading">
          <h3>Recorded appeal outcomes</h3>
          <p>Automatically inferred from the available case and outcome labels</p>
        </div>
        <div class="outcome-list">
          ${Object.entries(convictionAnalysis.outcome_distribution || {}).filter(([, count]) => count > 0).map(([category, count]) => {
            const percentage = affirmation.denominator ? (count / affirmation.denominator * 100) : 0;
            const label = convictionOutcomeLabels[category] || category;
            return `
              <div class="outcome-item">
                <span class="outcome-label">${escapeHTML(label)}</span>
                <span class="outcome-count">${formatNumber(count)} <span>${percentage.toFixed(1)}%</span></span>
              </div>
            `;
          }).join('') || '<p class="outcome-empty">No categorized outcome records are available.</p>'}
        </div>
        <p class="analysis-outcome-count">
          ${formatNumber(convictionAnalysis.conviction_appeal_candidates || 0)} likely appeals against conviction identified from the case number and party names.
        </p>
      </section>
    </div>
  `;
}

// Generate detailed judge analysis content (existing function)
function generateJudgeAnalysis(summary, cases, convictionAnalysis) {
  if (!cases || cases.length === 0) {
    return `
      <div class="empty-state">
        <i data-lucide="activity" style="width: 32px; height: 32px;"></i>
        <p>No case data available for analysis.</p>
      </div>
    `;
  }

  // Calculate analysis metrics
  const totalCases = cases.length;
  const criminalCases = cases.filter(c =>
    ['STATE OF', 'CRIMINAL', 'CRL.', 'IPC ', 'CRPC '].some(indicator =>
      (c.title || '').toUpperCase().includes(indicator))
  ).length;
  const civilCases = cases.filter(c =>
    ['VSB', 'VST', ' COMPANY', ' CORPORATION', ' BANK', ' AUTHORITY', ' W.', ' W.S.'].some(indicator =>
      (c.title || '').toUpperCase().includes(indicator))
  ).length;
  const otherCases = totalCases - criminalCases - civilCases;

  // Duration stats
  const durations = cases.map(c => c.duration_days || 0).filter(d => d > 0);
  const avgDuration = durations.reduce((a, b) => a + b, 0) / durations.length || 0;
  const medianDuration = durations.length > 0 ?
    durations.slice().sort((a, b) => a - b)[Math.floor(durations.length / 2)] : 0;
  const maxDuration = Math.max(...durations) || 0;
  const minDuration = Math.min(...durations.filter(d => d > 0)) || 0;

  // Priority score calculation (for this judge's cases)
  const priorityCases = cases.map(caseRecord => {
    const titleUpper = (caseRecord.title || '').toUpperCase();
    const isCriminal = ['STATE OF', 'CRIMINAL', 'CRL.', 'IPC ', 'CRPC '].some(
      indicator => titleUpper.includes(indicator));
    let priorityScore = 0;

    if (isCriminal) {
      if (caseRecord.status === 'COMPLETED') {
        priorityScore = caseRecord.duration_days || 0;
      } else if (['PENDING', 'HEARING', 'RESERVED'].includes(caseRecord.status || '')) {
        priorityScore = (caseRecord.duration_days || 0) * 2;
      }
    }

    return { ...caseRecord, priorityScore };
  }).sort((a, b) => b.priorityScore - a.priorityScore); // Sort by priority descending

  // Generate HTML with enhanced visualizations
  return `
    <div class="analysis-grid">
      <!-- Case Type Distribution -->
      <div class="analysis-card">
        <h3 class="analysis-title"><i data-lucide="pie-chart" style="width: 20px; height: 20px;"></i> Case Type Distribution</h3>
        <div class="analysis-stats">
          <div class="stat-item">
            <span class="stat-label">Likely Criminal</span>
            <div class="stat-progress-container">
              <div class="stat-progress-bar" style="width: ${(criminalCases/totalCases)*100}%"></div>
            </div>
            <span class="stat-value">${criminalCases} (${((criminalCases/totalCases)*100).toFixed(1)}%)</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Likely Civil</span>
            <div class="stat-progress-container">
              <div class="stat-progress-bar" style="width: ${(civilCases/totalCases)*100}%" class="bg-primary"></div>
            </div>
            <span class="stat-value">${civilCases} (${((civilCases/totalCases)*100).toFixed(1)}%)</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Other/Unclear</span>
            <div class="stat-progress-container">
              <div class="stat-progress-bar" style="width: ${(otherCases/totalCases)*100}%" class="bg-gray"></div>
            </div>
            <span class="stat-value">${otherCases} (${((otherCases/totalCases)*100).toFixed(1)}%)</span>
          </div>
        </div>
      </div>

      <!-- Duration Statistics -->
      <div class="analysis-card">
        <h3 class="analysis-title"><i data-lucide="clock" style="width: 20px; height: 20px;"></i> Duration Statistics</h3>
        <div class="analysis-stats">
          <div class="stat-item">
            <span class="stat-label">Average</span>
            <span class="stat-value">${formatDuration(avgDuration)}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Median</span>
            <span class="stat-value">${formatDuration(medianDuration)}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Maximum</span>
            <span class="stat-value">${formatDuration(maxDuration)}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Minimum</span>
            <span class="stat-value">${formatDuration(minDuration > 0 ? minDuration : 0)}</span>
          </div>
        </div>
        <div class="duration-chart">
          <div class="chart-label">Case Duration Distribution</div>
          <div class="chart-container">
            ${durations.map(duration => `
              <div class="chart-bar" style="height: ${Math.min((duration / maxDuration) * 100, 100)}%"
                   title="${formatDuration(duration)}"></div>
            `).join('')}
          </div>
        </div>
      </div>

      <!-- Priority Cases -->
      <div class="analysis-card">
        <h3 class="analysis-title"><i data-lucide="alert-triangle" style="width: 20px; height: 20px;"></i> Priority Case Analysis</h3>
        <div class="analysis-stats">
          <div class="stat-item">
            <span class="stat-label">Highest Priority Score</span>
            <span class="stat-value">${priorityCases[0]?.priorityScore || 0}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Cases Requiring Review</span>
            <span class="stat-value">${priorityCases.filter(p => p.priorityScore > 0).length}</span>
          </div>
          <div class="stat-item">
            <span class="stat-label">Average Priority Score</span>
            <span class="stat-value">${(priorityCases.reduce((a, b) => a + b.priorityScore, 0) / priorityCases.length || 0).toFixed(0)}</span>
          </div>
        </div>

        ${priorityCases.slice(0, 5).map((pc, index) => {
          const isHighPriority = pc.priorityScore > 0;
          return `
            <div class="priority-case ${isHighPriority ? 'priority-high' : ''}">
              <div class="priority-header">
                <span class="priority-rank">#${index + 1}</span>
                <span class="priority-score ${isHighPriority ? 'score-high' : ''}">${pc.priorityScore}</span>
              </div>
              <div class="priority-title">${escapeHTML(pc.title || '—')}</div>
              <div class="priority-meta">
                <span>${formatDuration(pc.duration_days)}</span> •
                <span>${getCaseTypeBadge(pc.title)}</span> •
                <span>${escapeHTML(pc.judgment_by || '—')}</span>
              </div>
              ${isHighPriority ? '<div class="priority-flag"><i data-lucide="alert-circle"></i> Requires Attention</div>' : ''}
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

async function loadSupremeCourtJudge() {
  initSidebar("judges");
  const judgeName = new URLSearchParams(window.location.search).get("name");
  const tbody = document.getElementById("sc-judge-cases");
  const error = document.getElementById("sc-judge-error");
  const convictionContent = document.getElementById("sc-judge-conviction-content");
  const analysisContent = document.getElementById("sc-judge-analysis-content");

  if (!judgeName) {
    error.style.display = "flex";
    document.getElementById("sc-judge-error-message").textContent = "No judge was specified.";
    tbody.innerHTML = "";
    return;
  }

  document.getElementById("sc-judge-title").textContent = judgeName;
  document.getElementById("sc-judge-breadcrumb").textContent = judgeName;

  try {
    const response = await API.get(`/api/supreme-court/judges/${encodeURIComponent(judgeName)}`);
    const { summary, cases } = response.data;
    document.getElementById("sc-judge-total-cases").textContent = formatNumber(summary.total_cases);
    document.getElementById("sc-judge-unique-cases").textContent = formatNumber(summary.unique_cases);
    document.getElementById("sc-judge-first-date").textContent = formatDate(summary.earliest_judgment);
    document.getElementById("sc-judge-last-date").textContent = formatDate(summary.latest_judgment);
    document.getElementById("sc-judge-summary").style.display = "grid";
    document.getElementById("sc-judge-case-count").textContent = `${formatNumber(cases.length)} Cases`;

    // Generate and insert conviction analysis (enhanced KPI section)
    convictionContent.innerHTML = generateConvictionAnalysis(summary, cases, response.data.conviction_analysis || {});
    renderJudgeOutcomeCharts('sc-judge', (() => {
      const conviction = response.data.conviction_analysis || {};
      const distribution = conviction.outcome_distribution || {};
      const affirmation = conviction.conviction_affirmation_rate || {};
      return {
        upheld: Number(distribution.CONVICTION_UPHELD || 0),
        setAside: Number(distribution.CONVICTION_SET_ASIDE || 0),
        modified: Number(distribution.CONVICTION_MODIFIED || 0),
        classified: Number(affirmation.denominator || 0),
        candidates: Number(conviction.conviction_appeal_candidates || 0)
      };
    })());

    // Generate and insert detailed analysis
    analysisContent.innerHTML = generateJudgeAnalysis(summary, cases, response.data.conviction_analysis || {});

    if (cases.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; padding: 24px;">No case records found.</td></tr>';
      return;
    }

    tbody.innerHTML = cases.map(caseRecord => {
      const judgmentUrl = safeJudgmentUrl(caseRecord.judgment_url);
      const judgment = judgmentUrl
        ? `<a href="${escapeHTML(judgmentUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-outline btn-sm">Open</a>`
        : '<span style="color: var(--text-tertiary);">Unavailable</span>';
      const caseTypeBadge = getCaseTypeBadge(caseRecord.title);
      const durationFormatted = formatDuration(caseRecord.duration_days);
      return `
        <tr>
          <td class="cell-mono">${escapeHTML(caseRecord.case_id || "—")}</td>
          <td class="cell-primary">${escapeHTML(caseRecord.title || "—")}</td>
          <td>${caseTypeBadge}</td>
          <td class="cell-mono">${durationFormatted}</td>
          <td class="cell-mono">${formatDate(caseRecord.judgment_date)}</td>
          <td>${escapeHTML(caseRecord.bench || "—")}</td>
          <td class="cell-mono">${escapeHTML(caseRecord.citation || "—")}</td>
          <td>${judgment}</td>
          <td>${escapeHTML(caseRecord.verdict || "No outcome label")}</td>
        </tr>
      `;
    }).join("");
    renderIcons();
  } catch (err) {
    console.error("Failed to load Supreme Court judge details:", err);
    tbody.innerHTML = "";
    error.style.display = "flex";
    document.getElementById("sc-judge-error-message").textContent = err.message;
    convictionContent.innerHTML = `
      <div class="empty-state">
        <i data-lucide="alert-triangle" style="width: 32px; height: 32px; color: var(--accent-amber);"></i>
        <p>Error loading conviction analysis: ${escapeHTML(err.message)}</p>
      </div>
    `;
    analysisContent.innerHTML = `
      <div class="empty-state">
        <i data-lucide="alert-triangle" style="width: 32px; height: 32px; color: var(--accent-amber);"></i>
        <p>Error loading detailed analysis: ${escapeHTML(err.message)}</p>
      </div>
    `;
    renderIcons();
  }
}

document.addEventListener("DOMContentLoaded", loadSupremeCourtJudge);
