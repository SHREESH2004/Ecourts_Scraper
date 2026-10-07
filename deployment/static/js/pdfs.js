/**
 * PDF Library Logic - eCourts Judicial Intelligence
 */

let pdfState = {
  query: '',
  judge: '',
  date: '',
  court: '',
  page: 1,
  limit: 25,
  total: 0,
  totalPages: 1,
  filtersLoaded: false
};

async function fetchPDFs() {
  const tbody = document.getElementById('pdfs-tbody');
  const emptyEl = document.getElementById('pdfs-empty');
  const errorEl = document.getElementById('pdfs-error');
  const paginationEl = document.getElementById('pdfs-pagination');
  const countBadge = document.getElementById('pdfs-count-badge');

  emptyEl.style.display = 'none';
  errorEl.style.display = 'none';

  // Skeleton rows
  tbody.innerHTML = Array.from({ length: 6 }).map(() => `
    <tr>
      <td><div class="skeleton" style="height: 20px; width: 80%;"></div></td>
      <td><div class="skeleton" style="height: 20px; width: 60%;"></div></td>
      <td><div class="skeleton" style="height: 20px; width: 80px;"></div></td>
      <td><div class="skeleton" style="height: 20px; width: 60px;"></div></td>
      <td><div class="skeleton" style="height: 20px; width: 40px;"></div></td>
      <td><div class="skeleton" style="height: 20px; width: 120px;"></div></td>
      <td style="text-align: right;"><div class="skeleton" style="height: 20px; width: 130px; margin-left: auto;"></div></td>
    </tr>
  `).join('');

  try {
    const res = await API.get('/api/pdfs', {
      q: pdfState.query,
      judge: pdfState.judge,
      date: pdfState.date,
      court: pdfState.court,
      page: pdfState.page,
      limit: pdfState.limit
    });

    pdfState.total = res.total;
    pdfState.totalPages = res.total_pages;

    countBadge.textContent = `${formatNumber(res.total)} Documents`;

    // Populate filter dropdowns on initial load
    if (!pdfState.filtersLoaded && res.filters) {
      populateFilters(res.filters);
      pdfState.filtersLoaded = true;
    }

    if (res.items.length === 0) {
      tbody.innerHTML = '';
      emptyEl.style.display = 'flex';
      paginationEl.style.display = 'none';
      renderIcons();
      return;
    }

    tbody.innerHTML = res.items.map(pdf => {
      const isDownloaded = pdf.has_file;
      const sizeTag = pdf.source_url
        ? `<span class="badge badge-mono" style="font-size: 10px;">Court-hosted PDF</span>`
        : isDownloaded
        ? `<span class="badge badge-mono badge-emerald" style="font-size: 10px;">${formatFileSize(pdf.file_size)}</span>`
        : `<span class="badge badge-mono" style="font-size: 10px;">DB Only</span>`;

      const openAction = isDownloaded
        ? `<a href="/pdf-viewer.html?file=${encodeURIComponent(pdf.filename)}&id=${pdf.id}" class="btn btn-outline btn-sm">
             <i data-lucide="eye" style="width: 12px; height: 12px;"></i>
             <span>Open</span>
           </a>`
        : `<button class="btn btn-outline btn-sm" disabled title="PDF is not available in cloud storage">Open</button>`;

      const downloadAction = isDownloaded
        ? `<a href="/api/pdf/${encodeURIComponent(pdf.filename)}?id=${pdf.id}&download=1" class="btn btn-secondary btn-sm">
             <i data-lucide="download" style="width: 12px; height: 12px;"></i>
             <span>Download</span>
           </a>`
        : `<button class="btn btn-secondary btn-sm" disabled title="PDF is not available in cloud storage">Download</button>`;

      return `
        <tr>
          <td>
            <div style="display: flex; flex-direction: column; gap: 2px;">
              <div style="display: flex; align-items: center; gap: 6px;">
                <i data-lucide="file-text" style="width: 14px; height: 14px; color: var(--text-tertiary); flex-shrink: 0;"></i>
                <span class="cell-mono cell-primary" style="font-size: 12px; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHTML(pdf.filename)}">
                  ${escapeHTML(pdf.filename)}
                </span>
              </div>
              <div>${sizeTag}</div>
            </div>
          </td>
          <td>
            <a href="/judge.html?name=${encodeURIComponent(pdf.judge_name)}" class="cell-primary" style="font-weight: 500; font-size: 12px; hover: text-blue;">
              ${escapeHTML(pdf.judge_name)}
            </a>
          </td>
          <td class="cell-mono" style="color: var(--text-tertiary);">${formatDate(pdf.cause_list_date)}</td>
          <td>${escapeHTML(pdf.state_name)}</td>
          <td style="color: var(--text-tertiary);">${escapeHTML(pdf.district_code)}</td>
          <td>
            <div style="font-size: 12px;">${escapeHTML(pdf.court_name)}</div>
          </td>
          <td style="text-align: right;">
            <div style="display: inline-flex; align-items: center; gap: 6px;">
              ${openAction}
              ${downloadAction}
            </div>
          </td>
        </tr>
      `;
    }).join('');

    // Update pagination controls
    paginationEl.style.display = 'flex';
    const start = (pdfState.page - 1) * pdfState.limit + 1;
    const end = Math.min(pdfState.page * pdfState.limit, pdfState.total);
    document.getElementById('pdf-pagination-info').textContent = `Showing ${start}-${end} of ${formatNumber(pdfState.total)} documents`;
    document.getElementById('pdf-page-display').textContent = `${pdfState.page} / ${pdfState.totalPages}`;

    document.getElementById('pdf-prev-btn').disabled = pdfState.page <= 1;
    document.getElementById('pdf-next-btn').disabled = pdfState.page >= pdfState.totalPages;

    renderIcons();
  } catch (err) {
    console.error('Failed to load PDFs:', err);
    tbody.innerHTML = '';
    errorEl.style.display = 'flex';
    document.getElementById('pdfs-error-msg').textContent = err.message || 'Error communicating with backend API';
    paginationEl.style.display = 'none';
    renderIcons();
  }
}

function populateFilters(filters) {
  const judgeSel = document.getElementById('pdf-judge-filter');
  const dateSel = document.getElementById('pdf-date-filter');
  const courtSel = document.getElementById('pdf-court-filter');

  // Judges
  (filters.judges || []).forEach(j => {
    const opt = document.createElement('option');
    opt.value = j;
    opt.textContent = j.length > 36 ? j.substring(0, 34) + '...' : j;
    opt.title = j;
    judgeSel.appendChild(opt);
  });

  // Dates
  (filters.dates || []).forEach(d => {
    const opt = document.createElement('option');
    opt.value = d;
    opt.textContent = formatDate(d);
    dateSel.appendChild(opt);
  });

  // Courts
  (filters.courts || []).forEach(c => {
    const opt = document.createElement('option');
    opt.value = c.court_code;
    opt.textContent = c.label;
    courtSel.appendChild(opt);
  });
}

function resetAllFilters() {
  document.getElementById('pdf-search-input').value = '';
  document.getElementById('pdf-judge-filter').value = '';
  document.getElementById('pdf-date-filter').value = '';
  document.getElementById('pdf-court-filter').value = '';

  pdfState.query = '';
  pdfState.judge = '';
  pdfState.date = '';
  pdfState.court = '';
  pdfState.page = 1;

  fetchPDFs();
}

document.addEventListener('DOMContentLoaded', () => {
  initSidebar('pdfs');

  const searchInput = document.getElementById('pdf-search-input');
  const judgeFilter = document.getElementById('pdf-judge-filter');
  const dateFilter = document.getElementById('pdf-date-filter');
  const courtFilter = document.getElementById('pdf-court-filter');
  const resetBtn = document.getElementById('clear-pdf-filters-btn');
  const emptyResetBtn = document.getElementById('empty-reset-filters-btn');
  const limitSelect = document.getElementById('pdf-limit-select');
  const prevBtn = document.getElementById('pdf-prev-btn');
  const nextBtn = document.getElementById('pdf-next-btn');
  const retryBtn = document.getElementById('retry-pdfs-btn');

  // Debounced search
  const handleSearch = debounce(() => {
    pdfState.query = searchInput.value.trim();
    pdfState.page = 1;
    fetchPDFs();
  }, 280);

  searchInput.addEventListener('input', handleSearch);

  // Filters change
  judgeFilter.addEventListener('change', () => {
    pdfState.judge = judgeFilter.value;
    pdfState.page = 1;
    fetchPDFs();
  });

  dateFilter.addEventListener('change', () => {
    pdfState.date = dateFilter.value;
    pdfState.page = 1;
    fetchPDFs();
  });

  courtFilter.addEventListener('change', () => {
    pdfState.court = courtFilter.value;
    pdfState.page = 1;
    fetchPDFs();
  });

  // Reset
  resetBtn.addEventListener('click', resetAllFilters);
  emptyResetBtn.addEventListener('click', resetAllFilters);

  // Pagination
  limitSelect.addEventListener('change', () => {
    pdfState.limit = parseInt(limitSelect.value, 10);
    pdfState.page = 1;
    fetchPDFs();
  });

  prevBtn.addEventListener('click', () => {
    if (pdfState.page > 1) {
      pdfState.page--;
      fetchPDFs();
    }
  });

  nextBtn.addEventListener('click', () => {
    if (pdfState.page < pdfState.totalPages) {
      pdfState.page++;
      fetchPDFs();
    }
  });

  retryBtn.addEventListener('click', () => {
    fetchPDFs();
  });

  fetchPDFs();
});
