/**
 * Dashboard Logic - eCourts Judicial Intelligence
 */

let judgeChartInstance = null;

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

    // Load Supreme Court overview (separate API call, non-blocking)
    loadSupremeCourtOverview();
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
  }
}

document.addEventListener('DOMContentLoaded', () => {
  loadDashboard();
  const refreshBtn = document.getElementById('refresh-dashboard-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      showToast('Refreshing dashboard...', 'info');
      loadDashboard();
    });
  }
});
