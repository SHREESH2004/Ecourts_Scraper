// Test script to check what conviction_analysis looks like from the API
const judgeName = "HON'BLE MR. JUSTICE K. VINOD CHANDRAN";

console.log(`Fetching judge detail for: ${judgeName}`);

// We'll simulate the API call by using fetch (in a real browser)
// Since we can't actually make HTTP requests in this Node.js environment,
// we'll just check the structure conceptually

// Based on our earlier test with the Python script, we know the structure should be:
// {
//   total_cases: number,
//   criminal_cases: number,
//   civil_cases: number,
//   other_cases: number,
//   outcome_distribution: {
//     CONVICTED: number,
//     ACQUITTED: number,
//     CONVICTION_UPHELD: number,
//     CONVICTION_MODIFIED: number,
//     CONVICTION_REVERSED: number,
//     ACQUITTAL_UPHELD: number,
//     ACQUITTAL_REVERSED: number,
//     PARTLY_ALLOWED: number,
//     DISMISSED: number,
//     REMANDED: number,
//     OTHER: number,
//     UNKNOWN: number
//   },
//   supreme_court_conviction_rate: {
//     rate: number,
//     formula: string,
//     description: string,
//     numerator: number,
//     denominator: number
//   },
//   traditional_conviction_rate: {
//     rate: number,
//     formula: string,
//     description: string,
//     numerator: number,
//     denominator: number,
//     note: string
//   }
// }

// Let's verify that the generateJudgeAnalysis function can handle this structure

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

// Escape HTML
function escapeHTML(str) {
  return str.replace(/[&<>"']/g,
    tag => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[tag]));
  }

// Generate judge analysis content with enhanced visualizations
function generateJudgeAnalysis(summary, cases, convictionAnalysis) {
  console.log("generateJudgeAnalysis called with:");
  console.log("  summary:", summary);
  console.log("  cases.length:", cases ? cases.length : 0);
  console.log("  convictionAnalysis:", convictionAnalysis);

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

  console.log("About to generate HTML...");

  // Generate HTML with enhanced visualizations
  try {
    const html = `
      <div class="analysis-grid">
        <!-- Conviction Rate Analysis -->
        <div class="analysis-card" style="border-left: 3px solid var(--accent-amber);">
          <h3 class="analysis-title"><i data-lucide="scale" style="width: 20px; height: 20px;"></i> Conviction Rate Analysis</h3>
          <div class="analysis-stats">
            <div class="stat-item">
              <span class="stat-label">Supreme Court Conviction Rate</span>
              <span class="stat-value">${convictionAnalysis.supreme_court_conviction_rate?.rate || 0}%</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">Based on Appeals</span>
              <span class="stat-value">${convictionAnalysis.supreme_court_conviction_rate?.numerator || 0} upheld/modified out of ${convictionAnalysis.supreme_court_conviction_rate?.denominator || 0} criminal appeals</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">Likely Criminal Cases</span>
              <span class="stat-value">${convictionAnalysis.criminal_cases || 0} (${((convictionAnalysis.criminal_cases || 0) / (convictionAnalysis.total_cases || 1) * 100).toFixed(1)}%)</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">Likely Civil Cases</span>
              <span class="stat-value">${convictionAnalysis.civil_cases || 0} (${((convictionAnalysis.civil_cases || 0) / (convictionAnalysis.total_cases || 1) * 100).toFixed(1)}%)</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">Other Cases</span>
              <span class="stat-value">${convictionAnalysis.other_cases || 0} (${((convictionAnalysis.other_cases || 0) / (convictionAnalysis.total_cases || 1) * 100).toFixed(1)}%)</span>
            </div>
          </div>
          <div class="outcome-distribution">
            <div class="distribution-label">Outcome Distribution:</div>
            <div class="distribution-grid">
              ${Object.entries(convictionAnalysis.outcome_distribution || {}).map(([category, count]) => {
                const percentage = convictionAnalysis.total_cases > 0 ? (count / convictionAnalysis.total_cases * 100) : 0;
                return `
                  <div class="distribution-item">
                    <span class="distribution-label">${category.replace(/_/g, ' ')}:</span>
                    <span class="distribution-value">${count} (${percentage.toFixed(1)}%)</span>
                  </div>
                `;
              }).join('')}
            </div>
          </div>
        </div>

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

    console.log("HTML generation successful");
    return html;
  } catch (error) {
    console.error("Error generating HTML:", error);
    return `<div class="error-state"><p>Error generating analysis: ${error.message}</p></div>`;
  }
}

// Test with data matching what we got from our Python test
const testSummary = {
  judge_name: "HON'BLE MR. JUSTICE K. VINOD CHANDRAN",
  total_cases: 148
};

const testCases = [
  {
    title: "BOMBAY GARAGE AHMEDABAD LIMITEDVSJ P ISCON PRIVATE LTD.",
    status: "COMPLETED",
    duration_days: 1002,
    judgment_by: "HON'BLE MR. JUSTICE K. VINOD CHANDRAN"
  },
  {
    title: "SAURABH BAJAJVSSTATE OF CHHATTISGARH",
    status: "COMPLETED",
    duration_days: 271,
    judgment_by: "HON'BLE MR. JUSTICE J.B. PARDIWALA"
  },
  {
    title: "IN RE: RECENT RAPE INCIDENTS IN DELHI NCR",
    status: "COMPLETED",
    duration_days: 270,
    judgment_by: "HON'BLE MR. JUSTICE J.B. PARDIWALA"
  }
];

const testConvictionAnalysis = {
  "total_cases": 148,
  "criminal_cases": 61,
  "civil_cases": 33,
  "other_cases": 54,
  "outcome_distribution": {
    "CONVICTED": 2,
    "ACQUITTED": 5,
    "CONVICTION_UPHELD": 36,
    "CONVICTION_MODIFIED": 0,
    "CONVICTION_REVERSED": 0,
    "ACQUITTAL_UPHELD": 2,
    "ACQUITTAL_REVERSED": 0,
    "PARTLY_ALLOWED": 9,
    "DISMISSED": 0,
    "REMANDED": 2,
    "OTHER": 81,
    "UNKNOWN": 13
  },
  "supreme_court_conviction_rate": {
    "rate": 94.74,
    "formula": "(CONVICTION_UPHELD + CONVICTION_MODIFIED) / (CONVICTION_UPHELD + CONVICTION_MODIFIED + ACQUITTAL_UPHELD + ACQUITTAL_REVERSED) × 100",
    "description": "Proportion of criminal appeals where conviction was upheld or modified",
    "numerator": 36,
    "denominator": 38
  },
  "traditional_conviction_rate": {
    "rate": 4.65,
    "formula": "CONVICTED / (CONVICTED + ACQUITTED) × 100",
    "description": "Traditional conviction rate (requires trial-court outcome data)",
    "numerator": 2,
    "denominator": 43,
    "note": "This requires trial-court outcome data which is not available in the current dataset"
  }
};

console.log("=== Testing generateJudgeAnalysis function ===");
try {
  const result = generateJudgeAnalysis(testSummary, testCases, testConvictionAnalysis);
  console.log("=== Test completed successfully ===");
  console.log("Result type:", typeof result);
  console.log("Result length:", result.length);
  console.log("Result preview (first 200 chars):", result.substring(0, 200));
} catch (error) {
  console.error("=== Test failed with error ===");
  console.error(error);
}