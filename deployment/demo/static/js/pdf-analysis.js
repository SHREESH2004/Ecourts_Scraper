/**
 * All-India PDF Intelligence & Case Extraction Frontend Controller (`pdf-analysis.js`)
 * Supports:
 *   1. Supreme Court of India (National: Supreme Court -> Court/Bench Grouping -> PDFs -> Cases)
 *   2. High Courts (State -> High Court -> Bench -> PDFs -> Cases)
 *   3. District & Subordinate Courts (State -> District -> Court Complex -> Establishment -> PDFs -> Cases)
 */

const PIState = {
  preset: 'previous_3_days',
  statesCatalog: [],
  benchesCatalog: [],
  geoJson: null,

  // Active hierarchy navigation filters
  selectedCourtType: '', // '', 'supreme_court', 'high_court', 'district_court'
  selectedStateCode: '',
  selectedStateName: '',
  selectedDistrictCode: '',
  selectedDistrictName: '',
  selectedComplexCode: '',
  selectedComplexName: '',
  selectedBenchCode: '',
  selectedBenchName: '',
  selectedDocumentId: null,
  selectedDocumentFilename: '',

  // Case records table state
  caseQuery: '',
  caseDocCategory: '',
  caseType: '',
  caseJudge: '',
  caseStatus: '',
  caseSort: 'listing_date',
  caseOrder: 'desc',
  casePage: 1,
  caseLimit: 25,

  // Job polling timer
  jobPollTimer: null
};

const DOC_CATEGORY_LABELS = {
  daily_cause_list: 'Daily Cause List',
  supplementary_cause_list: 'Supplementary Cause List',
  daily_order: 'Daily Order',
  final_judgment: 'Final Judgment',
  other_case_pdf: 'Other Case PDF'
};

const COURT_TIER_LABELS = {
  supreme_court: 'Supreme Court',
  high_court: 'High Court',
  district_court: 'District Court'
};

function toISODate(d) {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function applyDatePreset(preset) {
  PIState.preset = preset;
  document.querySelectorAll('.pi-preset-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.preset === preset);
  });

  const fromInput = document.getElementById('pi-from-date');
  const toInput = document.getElementById('pi-to-date');
  if (!fromInput || !toInput || preset === 'custom') return;

  const today = new Date();
  const start = new Date(today);
  if (preset === 'previous_3_days') {
    start.setDate(today.getDate() - 2);
  } else if (preset === 'previous_7_days') {
    start.setDate(today.getDate() - 6);
  } else if (preset === 'previous_15_days') {
    start.setDate(today.getDate() - 14);
  }

  fromInput.value = toISODate(start);
  toInput.value = toISODate(today);
}

// ---------------------------------------------------------------------------
// 1. Scraper Form Cascading Dropdowns & Capability Check
// ---------------------------------------------------------------------------
async function loadStatesAndMapData() {
  try {
    const [statesRes, benchesRes, geoRes] = await Promise.all([
      API.get('/api/pdf-intelligence/states'),
      API.get('/api/pdf-intelligence/benches'),
      fetch('/api/pdf-intelligence/map-geojson').then(r => r.json())
    ]);

    PIState.statesCatalog = statesRes.states || [];
    PIState.benchesCatalog = benchesRes.benches || [];
    PIState.geoJson = geoRes;

    populateScraperStateDropdown();
    renderIndiaMap();
    renderHierarchyInspector();
    updateHierarchyBreadcrumbs();
  } catch (err) {
    console.error('Failed to load states/map data:', err);
    showToast(`Failed to load court hierarchy: ${err.message}`, 'error');
  }
}

function populateScraperStateDropdown() {
  const stateSelect = document.getElementById('pi-scrape-state');
  if (!stateSelect) return;

  const currentVal = stateSelect.value;
  stateSelect.innerHTML = '<option value="">Select State / UT...</option>';

  PIState.statesCatalog.forEach(st => {
    const opt = document.createElement('option');
    opt.value = st.state_code;
    const hcCount = st.high_court_benches || 0;
    const dcCount = st.district_court_complexes || 0;
    opt.textContent = `${st.state_name} (${hcCount} HC · ${dcCount} DC Complex)`;
    stateSelect.appendChild(opt);
  });

  if (currentVal) {
    stateSelect.value = currentVal;
  } else {
    const mh = PIState.statesCatalog.find(s => s.state_code === '1');
    if (mh) stateSelect.value = '1';
  }
  updateScraperHierarchyOptions();
}

function updateScraperHierarchyOptions() {
  const courtType = document.getElementById('pi-scrape-court-type').value;
  const docCategory = document.getElementById('pi-scrape-doc-category').value;
  const fieldState = document.getElementById('pi-field-state');
  const fieldDistrict = document.getElementById('pi-field-district');
  const fieldComplex = document.getElementById('pi-field-complex');
  const labelBench = document.getElementById('pi-label-bench');

  const stateSelect = document.getElementById('pi-scrape-state');
  const distSelect = document.getElementById('pi-scrape-district');
  const complexSelect = document.getElementById('pi-scrape-complex');
  const benchSelect = document.getElementById('pi-scrape-bench');
  const alertBox = document.getElementById('pi-source-capability-alert');
  const startBtn = document.getElementById('pi-start-scrape-btn');

  // Case A: National-level Supreme Court
  if (courtType === 'supreme_court') {
    fieldState.style.display = 'none';
    fieldDistrict.style.display = 'none';
    fieldComplex.style.display = 'none';
    labelBench.textContent = 'Supreme Court Bench Grouping';

    const scBenches = PIState.benchesCatalog.filter(b => b.court_type === 'supreme_court');
    const prevBench = benchSelect.value;
    benchSelect.innerHTML = '';
    scBenches.forEach(b => {
      const opt = document.createElement('option');
      opt.value = b.bench_code;
      opt.textContent = b.bench_name;
      benchSelect.appendChild(opt);
    });
    if (prevBench && scBenches.some(b => b.bench_code === prevBench)) {
      benchSelect.value = prevBench;
    }

    const chosen = scBenches.find(b => b.bench_code === benchSelect.value) || scBenches[0];
    alertBox.style.display = 'block';
    alertBox.className = 'pi-capability-banner supported';
    alertBox.innerHTML = `<strong>Supreme Court Source Adapter (<code>sci.gov.in</code>):</strong> National-level court (not assigned to any state/district). Supports Daily &amp; Supplementary Cause Lists, Daily Orders, and Final Judgments. Storage namespace: <code>pdf-intelligence/supreme-court/</code>.`;
    startBtn.disabled = false;
    return;
  }

  // Case B & C: High Courts or District Courts (State-scoped)
  fieldState.style.display = '';
  fieldDistrict.style.display = '';
  fieldComplex.style.display = courtType === 'district_court' ? '' : 'none';
  labelBench.textContent = courtType === 'district_court' ? 'Court / Establishment' : 'High Court Bench';

  const stateCode = stateSelect.value;
  if (!stateCode) {
    distSelect.innerHTML = '<option value="">Select State First</option>';
    complexSelect.innerHTML = '<option value="">Select State First</option>';
    benchSelect.innerHTML = '<option value="">Select State First</option>';
    alertBox.style.display = 'none';
    return;
  }

  const stateObj = PIState.statesCatalog.find(s => s.state_code.toUpperCase() === stateCode.toUpperCase());
  const catalogStateCode = courtType === 'high_court' && stateCode.toUpperCase() === 'LA' ? '12' : stateCode;
  const stateBenches = PIState.benchesCatalog.filter(
    b => b.court_type === courtType && (b.state_code || '').toUpperCase() === catalogStateCode.toUpperCase()
  );

  // Populate Districts
  const distMap = new Map();
  stateBenches.forEach(b => {
    if (b.district_code) distMap.set(b.district_code, b.district_name);
  });

  const prevDist = distSelect.value;
  distSelect.innerHTML = '<option value="">All Supported Districts</option>';
  distMap.forEach((dName, dCode) => {
    const opt = document.createElement('option');
    opt.value = dCode;
    opt.textContent = dName;
    distSelect.appendChild(opt);
  });
  if (prevDist && distMap.has(prevDist)) {
    distSelect.value = prevDist;
  }

  const activeDist = distSelect.value;
  let distFiltered = activeDist
    ? stateBenches.filter(b => b.district_code === activeDist)
    : stateBenches;

  // Populate Court Complexes if District Court
  if (courtType === 'district_court') {
    const cxMap = new Map();
    distFiltered.forEach(b => {
      if (b.complex_code) cxMap.set(b.complex_code, b.complex_name);
    });
    const prevCx = complexSelect.value;
    complexSelect.innerHTML = '<option value="">All Court Complexes</option>';
    cxMap.forEach((cxName, cxCode) => {
      const opt = document.createElement('option');
      opt.value = cxCode;
      opt.textContent = cxName;
      complexSelect.appendChild(opt);
    });
    if (prevCx && cxMap.has(prevCx)) {
      complexSelect.value = prevCx;
    }
    if (complexSelect.value) {
      distFiltered = distFiltered.filter(b => b.complex_code === complexSelect.value);
    }
  }

  // Populate Benches / Establishments
  const prevBench = benchSelect.value;
  benchSelect.innerHTML = '';
  if (!distFiltered.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'No registered bench/establishment for selection';
    benchSelect.appendChild(opt);
  } else {
    distFiltered.forEach(b => {
      const opt = document.createElement('option');
      opt.value = b.bench_code;
      opt.textContent = courtType === 'district_court'
        ? `${b.establishment_name || b.bench_name} (${b.complex_name})`
        : `${b.bench_name} (${b.district_name})`;
      benchSelect.appendChild(opt);
    });
    if (prevBench && distFiltered.some(b => b.bench_code === prevBench)) {
      benchSelect.value = prevBench;
    }
  }

  const chosenBench = distFiltered.find(b => b.bench_code === benchSelect.value) || distFiltered[0];
  alertBox.style.display = 'block';

  if (chosenBench && chosenBench.source_supported) {
    if (chosenBench.requires_manual_verification) {
      alertBox.className = 'pi-capability-banner unsupported';
      alertBox.innerHTML = `<strong>District Court Adapter (<code>services.ecourts.gov.in</code>) — Manual Verification Notice:</strong> Hierarchy (${escapeHTML(chosenBench.district_name)} &rarr; ${escapeHTML(chosenBench.complex_name)} &rarr; ${escapeHTML(chosenBench.establishment_name)}) is verified. Note: ${escapeHTML(chosenBench.source_limitation || 'Live portal queries require a Securimage session CAPTCHA.')} Storage namespace: <code>pdf-intelligence/district-court/</code>.`;
    } else {
      alertBox.className = 'pi-capability-banner supported';
      alertBox.innerHTML = `<strong>High Court Source Adapter (<code>hcservices.ecourts.gov.in</code>):</strong> ${escapeHTML(chosenBench.court_name)} &mdash; ${escapeHTML(chosenBench.bench_name)} (${escapeHTML(chosenBench.district_name)}) supports inclusive date-range discovery for <code>${escapeHTML(DOC_CATEGORY_LABELS[docCategory] || docCategory)}</code>. Storage namespace: <code>pdf-intelligence/high-court/</code>.`;
    }
    startBtn.disabled = false;
  } else {
    alertBox.className = 'pi-capability-banner unsupported';
    const reason = (chosenBench && chosenBench.source_limitation)
      || (stateObj && stateObj.jurisdiction_note)
      || 'No automated source adapter is available for this selection.';
    alertBox.innerHTML = `<strong>Official Source Limitation Reported:</strong> ${escapeHTML(reason)}`;
    startBtn.disabled = false;
  }
}

async function handleStartScrape(e) {
  e.preventDefault();
  const courtType = document.getElementById('pi-scrape-court-type').value;
  const docCategory = document.getElementById('pi-scrape-doc-category').value;
  const stateCode = courtType === 'supreme_court' ? null : document.getElementById('pi-scrape-state').value;
  const districtCode = courtType === 'supreme_court' ? null : document.getElementById('pi-scrape-district').value;
  const complexCode = courtType === 'district_court' ? document.getElementById('pi-scrape-complex').value : null;
  const benchCode = document.getElementById('pi-scrape-bench').value;
  const startDate = document.getElementById('pi-from-date').value;
  const endDate = document.getElementById('pi-to-date').value;

  if (courtType !== 'supreme_court' && !stateCode) {
    showToast('Please select a State / Union Territory.', 'error');
    return;
  }
  if (!startDate || !endDate) {
    showToast('Please select both From and To dates.', 'error');
    return;
  }

  const btn = document.getElementById('pi-start-scrape-btn');
  btn.disabled = true;

  try {
    const res = await API.post('/api/pdf-intelligence/jobs', {
      court_type: courtType,
      document_category: docCategory,
      state_code: stateCode || null,
      district_code: districtCode || null,
      complex_code: complexCode || null,
      establishment_code: courtType === 'district_court' ? (benchCode || null) : null,
      bench_code: benchCode || null,
      start_date: startDate,
      end_date: endDate,
      preset: PIState.preset
    });

    showToast(`Started PDF Intelligence job ${res.job.job_uid}`, 'success');
    await loadJobsStatus();
    startJobPolling();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// 2. Durable Scrape Jobs Monitor & Polling
// ---------------------------------------------------------------------------
async function loadJobsStatus() {
  try {
    const res = await API.get('/api/pdf-intelligence/jobs', { limit: 15 });
    const jobs = res.jobs || [];
    renderJobsTable(jobs);

    const activeJob = jobs.find(j => j.status === 'running' || j.status === 'queued');
    const badge = document.getElementById('pi-active-job-badge');
    const stepText = document.getElementById('pi-active-job-step');
    const progWrap = document.getElementById('pi-job-progress-wrap');
    const progFill = document.getElementById('pi-job-progress-fill');

    if (activeJob) {
      badge.textContent = activeJob.status.toUpperCase();
      badge.className = 'badge badge-mono badge-blue';
      stepText.textContent = `${activeJob.job_uid}: ${activeJob.current_step || 'Processing...'} (${activeJob.progress_pct}%)`;
      progWrap.style.display = 'block';
      progFill.style.width = `${Math.max(5, activeJob.progress_pct || 5)}%`;
      startJobPolling();
    } else {
      stopJobPolling();
      const latest = jobs[0];
      if (latest) {
        badge.textContent = latest.status.toUpperCase();
        badge.className = latest.status === 'completed'
          ? 'badge badge-mono badge-emerald'
          : (latest.status === 'failed' ? 'badge badge-mono badge-rose' : 'badge badge-mono');
        stepText.textContent = `Latest job ${latest.job_uid}: ${latest.current_step || latest.status}`;
      } else {
        badge.textContent = 'IDLE';
        badge.className = 'badge badge-mono';
        stepText.textContent = 'No scrape jobs recorded yet';
      }
      progWrap.style.display = 'none';
    }
  } catch (err) {
    console.error('Error loading jobs:', err);
  }
}

function renderJobsTable(jobs) {
  const tbody = document.getElementById('pi-jobs-tbody');
  if (!tbody) return;

  if (!jobs.length) {
    tbody.innerHTML = '<tr><td colspan="12" style="text-align: center; color: var(--text-tertiary);">No PDF Intelligence scrape jobs have been run yet.</td></tr>';
    return;
  }

  tbody.innerHTML = jobs.map(j => {
    const statusClass = j.status === 'completed'
      ? 'badge-emerald'
      : (j.status === 'running' || j.status === 'queued' ? 'badge-blue' : 'badge-rose');
    const msg = j.limitation_notice || j.error_summary || j.current_step || '—';
    const tierBadge = COURT_TIER_LABELS[j.court_type] || j.court_type;
    const scopeTitle = j.court_type === 'supreme_court'
      ? 'Supreme Court of India (National)'
      : `${j.state_name || ''}${j.district_name ? ' · ' + j.district_name : ''}`;
    const subTitle = j.complex_name
      ? `${j.complex_name} — ${j.establishment_name || j.bench_name || ''}`
      : (j.bench_name || j.court_name || '');

    return `
      <tr>
        <td class="cell-mono" style="font-size: 11.5px;">${escapeHTML(j.job_uid)}</td>
        <td><span class="badge badge-mono">${escapeHTML(tierBadge)}</span></td>
        <td>
          <div style="font-weight: 500;">${escapeHTML(scopeTitle)}</div>
          <div style="font-size: 11px; color: var(--text-tertiary);">${escapeHTML(subTitle)}</div>
        </td>
        <td style="font-size: 11.5px;">${escapeHTML(DOC_CATEGORY_LABELS[j.document_category] || j.document_category || 'Cause List')}</td>
        <td class="cell-mono" style="font-size: 11.5px;">${escapeHTML(j.start_date)} &rarr; ${escapeHTML(j.end_date)}</td>
        <td><span class="badge badge-mono ${statusClass}">${escapeHTML(j.status)}</span></td>
        <td class="cell-mono" style="text-align: right;">${formatNumber(j.discovered_count)}</td>
        <td class="cell-mono" style="text-align: right;">${formatNumber(j.downloaded_count)}</td>
        <td class="cell-mono" style="text-align: right;">${formatNumber(j.skipped_duplicate_count)}</td>
        <td class="cell-mono" style="text-align: right; color: var(--accent-emerald); font-weight: 600;">${formatNumber(j.case_records_count)}</td>
        <td class="cell-mono" style="text-align: right;">${formatNumber(j.failed_count)}</td>
        <td style="font-size: 11.5px; color: var(--text-secondary); max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHTML(msg)}">
          ${escapeHTML(msg)}
        </td>
      </tr>
    `;
  }).join('');
}

function startJobPolling() {
  if (PIState.jobPollTimer) return;
  PIState.jobPollTimer = setInterval(async () => {
    await loadJobsStatus();
    await Promise.all([
      loadStatesAndMapData(),
      loadDocumentsList(),
      loadCaseRecords(),
      loadDailyAnalytics()
    ]);
  }, 3000);
}

function stopJobPolling() {
  if (PIState.jobPollTimer) {
    clearInterval(PIState.jobPollTimer);
    PIState.jobPollTimer = null;
  }
}

// ---------------------------------------------------------------------------
// 3. Interactive India GeoJSON Map & Multi-Tier Hierarchy Navigation
// ---------------------------------------------------------------------------
function projectLonLat(lon, lat) {
  const minLon = 67.8;
  const maxLon = 97.8;
  const minLat = 6.5;
  const maxLat = 37.3;
  const width = 620;
  const height = 680;
  const pad = 24;

  const x = pad + ((lon - minLon) / (maxLon - minLon)) * (width - pad * 2);
  const y = height - pad - ((lat - minLat) / (maxLat - minLat)) * (height - pad * 2);
  return [x, y];
}

function renderIndiaMap() {
  const polyGroup = document.getElementById('pi-map-polygons');
  const labelGroup = document.getElementById('pi-map-labels');
  const pinGroup = document.getElementById('pi-map-pins');
  const hoverLabel = document.getElementById('pi-map-hover-label');

  if (!polyGroup || !PIState.geoJson || !PIState.geoJson.features) return;

  polyGroup.innerHTML = '';
  labelGroup.innerHTML = '';
  pinGroup.innerHTML = '';

  const stateStatsByIso = new Map();
  PIState.statesCatalog.forEach(s => {
    stateStatsByIso.set(s.state_iso_code, s);
  });

  PIState.geoJson.features.forEach(feat => {
    const props = feat.properties || {};
    const iso = props.state_iso_code;
    const stateStat = stateStatsByIso.get(iso) || {};
    const stateCode = stateStat.state_code || props.state_code;
    const stateName = stateStat.state_name || props.state_name;

    const coords = (feat.geometry && feat.geometry.coordinates && feat.geometry.coordinates[0]) || [];
    if (!coords.length) return;

    const pointsStr = coords.map(([lon, lat]) => {
      const [x, y] = projectLonLat(lon, lat);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');

    const poly = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    poly.setAttribute('points', pointsStr);

    let cls = 'pi-state-poly';
    if (stateStat.total_pdfs > 0) cls += ' has-data';
    else if (stateStat.has_supported_source || (stateStat.district_court_complexes || 0) > 0) cls += ' supported';
    if (PIState.selectedStateCode && PIState.selectedStateCode.toUpperCase() === String(stateCode).toUpperCase()) {
      cls += ' selected';
    }
    poly.setAttribute('class', cls);
    poly.dataset.stateCode = stateCode;
    poly.dataset.stateName = stateName;

    poly.addEventListener('mouseenter', () => {
      const pdfs = stateStat.total_pdfs || 0;
      const cases = stateStat.total_cases || 0;
      const hc = stateStat.high_court_benches || 0;
      const dc = stateStat.district_court_complexes || 0;
      hoverLabel.textContent = `${stateName}: ${pdfs} PDF(s), ${cases} Case(s) · ${hc} HC Bench(es), ${dc} DC Complex(es)`;
    });

    poly.addEventListener('click', () => {
      if (PIState.selectedCourtType === 'supreme_court') {
        // Switching to a state exits national-only Supreme Court filter
        PIState.selectedCourtType = '';
        document.querySelectorAll('.pi-tab-btn').forEach(t => {
          t.classList.toggle('active', t.dataset.ctype === '');
        });
      }
      selectHierarchyState(stateCode, stateName);
    });

    polyGroup.appendChild(poly);

    if (props.label_lon && props.label_lat) {
      const [lx, ly] = projectLonLat(props.label_lon, props.label_lat);
      const textEl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
      textEl.setAttribute('x', lx.toFixed(1));
      textEl.setAttribute('y', ly.toFixed(1));
      textEl.setAttribute('class', 'pi-state-label');
      textEl.textContent = iso.replace('IN-', '');
      labelGroup.appendChild(textEl);
    }
  });

  // Plot verified court pins (Supreme Court, High Courts, District Court Complexes)
  PIState.benchesCatalog.forEach(b => {
    if (b.latitude == null || b.longitude == null) return;
    if (PIState.selectedCourtType && b.court_type !== PIState.selectedCourtType) return;

    const [px, py] = projectLonLat(b.longitude, b.latitude);
    const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    circle.setAttribute('cx', px.toFixed(1));
    circle.setAttribute('cy', py.toFixed(1));
    const isSelectedBench = (
      (PIState.selectedBenchCode || '').toUpperCase() === b.bench_code.toUpperCase() &&
      (PIState.selectedStateCode || '').toUpperCase() === (b.state_code || '').toUpperCase()
    );
    circle.setAttribute('r', isSelectedBench ? '6' : (b.court_type === 'supreme_court' ? '5.5' : '4'));
    circle.setAttribute('class', isSelectedBench ? 'pi-bench-pin selected' : 'pi-bench-pin');

    circle.addEventListener('mouseenter', () => {
      const locText = b.court_type === 'supreme_court'
        ? 'Supreme Court of India (New Delhi)'
        : `${b.district_name}, ${b.state_name}`;
      hoverLabel.textContent = `[${COURT_TIER_LABELS[b.court_type]}] ${b.bench_name} (${locText}) — ${b.pdf_count} PDF(s), ${b.case_count} Case(s)`;
    });

    circle.addEventListener('click', (ev) => {
      ev.stopPropagation();
      selectHierarchyBench(b);
    });

    pinGroup.appendChild(circle);
  });
}

function selectHierarchyState(stateCode, stateName) {
  PIState.selectedStateCode = stateCode || '';
  PIState.selectedStateName = stateName || '';
  PIState.selectedDistrictCode = '';
  PIState.selectedDistrictName = '';
  PIState.selectedComplexCode = '';
  PIState.selectedComplexName = '';
  PIState.selectedBenchCode = '';
  PIState.selectedBenchName = '';
  PIState.selectedDocumentId = null;
  PIState.selectedDocumentFilename = '';
  PIState.casePage = 1;

  const scrapeState = document.getElementById('pi-scrape-state');
  if (scrapeState && stateCode) {
    scrapeState.value = stateCode;
    updateScraperHierarchyOptions();
  }

  renderIndiaMap();
  renderHierarchyInspector();
  updateHierarchyBreadcrumbs();
  loadDocumentsList();
  loadCaseRecords();
  loadDailyAnalytics();
}

function selectHierarchyDistrict(districtCode, districtName) {
  PIState.selectedDistrictCode = districtCode || '';
  PIState.selectedDistrictName = districtName || '';
  PIState.selectedComplexCode = '';
  PIState.selectedComplexName = '';
  PIState.selectedBenchCode = '';
  PIState.selectedBenchName = '';
  PIState.selectedDocumentId = null;
  PIState.selectedDocumentFilename = '';
  PIState.casePage = 1;

  renderHierarchyInspector();
  updateHierarchyBreadcrumbs();
  loadDocumentsList();
  loadCaseRecords();
  loadDailyAnalytics();
}

function selectHierarchyComplex(complexCode, complexName) {
  PIState.selectedComplexCode = complexCode || '';
  PIState.selectedComplexName = complexName || '';
  PIState.selectedBenchCode = '';
  PIState.selectedBenchName = '';
  PIState.selectedDocumentId = null;
  PIState.selectedDocumentFilename = '';
  PIState.casePage = 1;

  renderHierarchyInspector();
  updateHierarchyBreadcrumbs();
  loadDocumentsList();
  loadCaseRecords();
  loadDailyAnalytics();
}

function selectHierarchyBench(bench) {
  PIState.selectedCourtType = bench.court_type || PIState.selectedCourtType;
  document.querySelectorAll('.pi-tab-btn').forEach(t => {
    t.classList.toggle('active', t.dataset.ctype === PIState.selectedCourtType);
  });

  PIState.selectedStateCode = bench.state_code || '';
  PIState.selectedStateName = bench.state_name || '';
  PIState.selectedDistrictCode = bench.district_code || '';
  PIState.selectedDistrictName = bench.district_name || '';
  PIState.selectedComplexCode = bench.complex_code || '';
  PIState.selectedComplexName = bench.complex_name || '';
  PIState.selectedBenchCode = bench.bench_code || '';
  PIState.selectedBenchName = bench.bench_name || '';
  PIState.selectedDocumentId = null;
  PIState.selectedDocumentFilename = '';
  PIState.casePage = 1;

  renderIndiaMap();
  renderHierarchyInspector();
  updateHierarchyBreadcrumbs();
  loadDocumentsList();
  loadCaseRecords();
  loadDailyAnalytics();
}

function selectHierarchyDocument(docId, pdfFilename) {
  PIState.selectedDocumentId = docId;
  PIState.selectedDocumentFilename = pdfFilename || `Document #${docId}`;
  PIState.casePage = 1;

  updateHierarchyBreadcrumbs();
  loadCaseRecords();
}

function updateHierarchyBreadcrumbs() {
  const cRoot = document.getElementById('pi-crumb-root');
  const cRootLabel = document.getElementById('pi-crumb-root-label');
  const cState = document.getElementById('pi-crumb-state');
  const sepDist = document.getElementById('pi-sep-district');
  const cDist = document.getElementById('pi-crumb-district');
  const sepComplex = document.getElementById('pi-sep-complex');
  const cComplex = document.getElementById('pi-crumb-complex');
  const cBench = document.getElementById('pi-crumb-bench');
  const cPdf = document.getElementById('pi-crumb-pdf');
  const subtitle = document.getElementById('pi-hierarchy-subtitle');

  if (PIState.selectedCourtType === 'supreme_court') {
    subtitle.textContent = 'Supreme Court Navigation: Supreme Court (National) → Court / Bench Grouping → PDFs → Extracted Cases';
    cRootLabel.textContent = 'Supreme Court of India (National)';
    cState.style.display = 'none';
    sepDist.style.display = 'none';
    cDist.style.display = 'none';
    sepComplex.style.display = 'none';
    cComplex.style.display = 'none';
    cRoot.classList.toggle('active', !PIState.selectedBenchCode);
  } else if (PIState.selectedCourtType === 'district_court') {
    subtitle.textContent = 'District Court Navigation: India → State / UT → District → Court Complex → Court / Establishment → PDFs → Cases';
    cRootLabel.textContent = 'India (District Courts)';
    cState.style.display = '';
    sepDist.style.display = '';
    cDist.style.display = '';
    sepComplex.style.display = '';
    cComplex.style.display = '';
    cRoot.classList.toggle('active', !PIState.selectedStateCode);
  } else {
    subtitle.textContent = PIState.selectedCourtType === 'high_court'
      ? 'High Court Navigation: India → State / UT → High Court → Bench → PDFs → Cases'
      : 'All-India Navigation: Supreme Court · High Courts · District Courts → PDFs → Cases';
    cRootLabel.textContent = PIState.selectedCourtType === 'high_court' ? 'India (High Courts)' : 'India (All Categories)';
    cState.style.display = '';
    sepDist.style.display = '';
    cDist.style.display = '';
    sepComplex.style.display = 'none';
    cComplex.style.display = 'none';
    cRoot.classList.toggle('active', !PIState.selectedStateCode && !PIState.selectedBenchCode);
  }

  if (PIState.selectedStateCode) {
    cState.disabled = false;
    cState.textContent = `State: ${PIState.selectedStateName}`;
    cState.classList.toggle('active', Boolean(PIState.selectedStateCode && !PIState.selectedDistrictCode && !PIState.selectedBenchCode));
  } else {
    cState.disabled = true;
    cState.textContent = 'State: All';
    cState.classList.remove('active');
  }

  if (PIState.selectedDistrictCode) {
    cDist.disabled = false;
    cDist.textContent = `District: ${PIState.selectedDistrictName}`;
    cDist.classList.toggle('active', Boolean(PIState.selectedDistrictCode && !PIState.selectedComplexCode && !PIState.selectedBenchCode));
  } else {
    cDist.disabled = true;
    cDist.textContent = 'District: All';
    cDist.classList.remove('active');
  }

  if (PIState.selectedComplexCode) {
    cComplex.disabled = false;
    cComplex.textContent = `Complex: ${PIState.selectedComplexName}`;
    cComplex.classList.toggle('active', Boolean(PIState.selectedComplexCode && !PIState.selectedBenchCode));
  } else {
    cComplex.disabled = true;
    cComplex.textContent = 'Court Complex: All';
    cComplex.classList.remove('active');
  }

  if (PIState.selectedBenchCode) {
    cBench.disabled = false;
    cBench.textContent = `${PIState.selectedCourtType === 'district_court' ? 'Establishment' : 'Bench'}: ${PIState.selectedBenchName}`;
    cBench.classList.toggle('active', Boolean(PIState.selectedBenchCode && !PIState.selectedDocumentId));
  } else {
    cBench.disabled = true;
    cBench.textContent = PIState.selectedCourtType === 'district_court' ? 'Establishment: All' : 'Court / Bench: All';
    cBench.classList.remove('active');
  }

  if (PIState.selectedDocumentId) {
    cPdf.disabled = false;
    cPdf.textContent = `PDF: ${PIState.selectedDocumentFilename}`;
    cPdf.classList.add('active');
  } else {
    cPdf.disabled = true;
    cPdf.textContent = 'PDF: All';
    cPdf.classList.remove('active');
  }
}

function renderHierarchyInspector() {
  const heading = document.getElementById('pi-inspector-heading');
  const badge = document.getElementById('pi-benches-count-badge');
  const noteBox = document.getElementById('pi-jurisdiction-note-box');
  const distChips = document.getElementById('pi-districts-chips');
  const complexChips = document.getElementById('pi-complexes-chips');
  const benchesContainer = document.getElementById('pi-benches-list');

  let benches = PIState.benchesCatalog.slice();
  if (PIState.selectedCourtType) {
    benches = benches.filter(b => b.court_type === PIState.selectedCourtType);
  }
  if (PIState.selectedCourtType !== 'supreme_court' && PIState.selectedStateCode) {
    benches = benches.filter(b => (b.state_code || '').toUpperCase() === PIState.selectedStateCode.toUpperCase());
  }

  // Jurisdiction note for shared High Courts
  const stObj = PIState.statesCatalog.find(
    s => s.state_code.toUpperCase() === (PIState.selectedStateCode || '').toUpperCase()
  );
  if (stObj && stObj.jurisdiction_note && PIState.selectedCourtType !== 'supreme_court') {
    noteBox.style.display = 'block';
    noteBox.textContent = stObj.jurisdiction_note;
  } else {
    noteBox.style.display = 'none';
  }

  // Render District chips when a State is selected (for HC or DC)
  const distMap = new Map();
  benches.forEach(b => {
    if (b.district_code) distMap.set(b.district_code, b.district_name);
  });

  if (PIState.selectedCourtType !== 'supreme_court' && PIState.selectedStateCode && distMap.size > 0) {
    let chipsHtml = `<button type="button" class="pi-chip ${!PIState.selectedDistrictCode ? 'active' : ''}" data-dcode="" data-dname="">All Districts (${distMap.size})</button>`;
    distMap.forEach((dName, dCode) => {
      const isAct = PIState.selectedDistrictCode === dCode ? 'active' : '';
      chipsHtml += `<button type="button" class="pi-chip ${isAct}" data-dcode="${escapeHTML(dCode)}" data-dname="${escapeHTML(dName)}">${escapeHTML(dName)}</button>`;
    });
    distChips.innerHTML = chipsHtml;
    distChips.querySelectorAll('.pi-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        selectHierarchyDistrict(chip.dataset.dcode, chip.dataset.dname);
      });
    });
  } else {
    distChips.innerHTML = '';
  }

  if (PIState.selectedDistrictCode) {
    benches = benches.filter(b => b.district_code === PIState.selectedDistrictCode);
  }

  // Render Court Complex chips when District Courts exist in the current scope
  const complexMap = new Map();
  benches.forEach(b => {
    if (b.court_type === 'district_court' && b.complex_code) {
      complexMap.set(b.complex_code, b.complex_name);
    }
  });

  if ((PIState.selectedCourtType === 'district_court' || PIState.selectedDistrictCode) && complexMap.size > 0) {
    complexChips.style.display = 'flex';
    let cxHtml = `<button type="button" class="pi-chip ${!PIState.selectedComplexCode ? 'active' : ''}" data-cxcode="" data-cxname="">All Court Complexes (${complexMap.size})</button>`;
    complexMap.forEach((cxName, cxCode) => {
      const isAct = PIState.selectedComplexCode === cxCode ? 'active' : '';
      cxHtml += `<button type="button" class="pi-chip ${isAct}" data-cxcode="${escapeHTML(cxCode)}" data-cxname="${escapeHTML(cxName)}">Complex: ${escapeHTML(cxName)}</button>`;
    });
    complexChips.innerHTML = cxHtml;
    complexChips.querySelectorAll('.pi-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        selectHierarchyComplex(chip.dataset.cxcode, chip.dataset.cxname);
      });
    });
  } else {
    complexChips.style.display = 'none';
    complexChips.innerHTML = '';
  }

  if (PIState.selectedComplexCode) {
    benches = benches.filter(b => b.complex_code === PIState.selectedComplexCode);
  }

  if (PIState.selectedCourtType === 'supreme_court') {
    heading.textContent = 'Supreme Court of India — National Court / Bench Groupings';
  } else if (PIState.selectedStateName) {
    heading.textContent = `Courts, Benches & Establishments in ${PIState.selectedStateName}${PIState.selectedDistrictName ? ' / ' + PIState.selectedDistrictName : ''}`;
  } else {
    heading.textContent = 'Verified Courts, Benches & Establishments Across India';
  }
  badge.textContent = `${benches.length} Available`;

  if (!benches.length) {
    benchesContainer.innerHTML = `<div style="grid-column: 1 / -1; color: var(--text-tertiary); font-size: 12px; padding: 10px;">No registered courts or benches match this filter in the verified catalog.</div>`;
    return;
  }

  benchesContainer.innerHTML = benches.map(b => {
    const isAct = (
      (PIState.selectedBenchCode || '').toUpperCase() === b.bench_code.toUpperCase() &&
      (PIState.selectedStateCode || '').toUpperCase() === (b.state_code || '').toUpperCase()
    ) ? 'active' : '';
    const catBadge = b.court_type === 'supreme_court' ? 'SC' : (b.court_type === 'high_court' ? 'HC' : 'DC');
    const locSubtitle = b.court_type === 'supreme_court'
      ? 'National Jurisdiction · New Delhi'
      : (b.complex_name ? `${b.complex_name} (${b.district_name})` : `${b.district_name}, ${b.state_name}`);

    return `
      <div class="pi-bench-card ${isAct}" data-location-key="${escapeHTML(b.location_key)}">
        <div class="pi-bench-card-title">[${catBadge}] ${escapeHTML(b.bench_name)}</div>
        <div class="pi-bench-card-meta">
          <span>${escapeHTML(locSubtitle)}</span>
          <span class="cell-mono">${formatNumber(b.pdf_count)} PDFs · ${formatNumber(b.case_count)} Cases</span>
        </div>
      </div>
    `;
  }).join('');

  benchesContainer.querySelectorAll('.pi-bench-card').forEach(card => {
    card.addEventListener('click', () => {
      const locKey = card.dataset.locationKey;
      const benchObj = PIState.benchesCatalog.find(x => x.location_key === locKey);
      if (benchObj) selectHierarchyBench(benchObj);
    });
  });
}

// ---------------------------------------------------------------------------
// 4. Scoped PDFs List & Retry Trigger
// ---------------------------------------------------------------------------
async function loadDocumentsList() {
  const tbody = document.getElementById('pi-documents-tbody');
  const countBadge = document.getElementById('pi-docs-count-badge');
  if (!tbody) return;

  try {
    const res = await API.get('/api/pdf-intelligence/documents', {
      court_type: PIState.selectedCourtType,
      state_code: PIState.selectedCourtType === 'supreme_court' ? '' : PIState.selectedStateCode,
      district_code: PIState.selectedCourtType === 'supreme_court' ? '' : PIState.selectedDistrictCode,
      complex_code: PIState.selectedComplexCode,
      bench_code: PIState.selectedBenchCode,
      limit: 50
    });

    const docs = res.items || [];
    countBadge.textContent = `${formatNumber(res.total || 0)} PDFs`;

    if (!docs.length) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; color: var(--text-tertiary);">No PDFs stored for the current selection yet. Use the Date-Range Scraper above to scrape this court/bench.</td></tr>';
      return;
    }

    tbody.innerHTML = docs.map(d => {
      const statusBadge = d.extraction_status === 'completed' || d.extraction_status === 'ocr_completed'
        ? 'badge-emerald'
        : (d.extraction_status === 'failed' ? 'badge-rose' : 'badge-blue');
      const isSelectedDoc = PIState.selectedDocumentId === d.id;
      const courtLabel = d.court_type === 'supreme_court'
        ? `Supreme Court — ${d.bench_name}`
        : (d.complex_name ? `${d.complex_name} — ${d.bench_name}` : `${d.court_name} — ${d.bench_name}`);

      return `
        <tr style="${isSelectedDoc ? 'background-color: var(--accent-blue-subtle);' : ''}">
          <td>
            <div class="cell-mono" style="font-size: 11.5px; font-weight: 500;">${escapeHTML(d.pdf_filename)}</div>
            <div class="cell-mono" style="font-size: 10px; color: var(--text-tertiary);">
              ${escapeHTML(d.storage_namespace)} · SHA256: ${escapeHTML((d.content_sha256 || 'pending').slice(0, 12))}...
            </div>
          </td>
          <td><span class="badge badge-mono">${escapeHTML(DOC_CATEGORY_LABELS[d.document_category] || d.document_category)}</span></td>
          <td class="cell-mono" style="font-size: 12px;">${escapeHTML(d.listing_date || '—')}</td>
          <td style="font-size: 12px;">${escapeHTML(courtLabel)}</td>
          <td><span class="badge badge-mono ${statusBadge}">${escapeHTML(d.extraction_status)}</span></td>
          <td class="cell-mono" style="text-align: right; font-weight: 600;">${formatNumber(d.case_count)}</td>
          <td style="text-align: right; white-space: nowrap;">
            <button type="button" class="btn btn-outline btn-sm pi-filter-doc-btn" data-doc-id="${d.id}" data-doc-fn="${escapeHTML(d.pdf_filename)}" title="Filter Case Records to this PDF">
              Cases
            </button>
            <a href="${escapeHTML(d.original_pdf_link)}" target="_blank" class="btn btn-outline btn-sm" title="Open Original PDF">
              PDF
            </a>
            <button type="button" class="btn btn-outline btn-sm pi-retry-doc-btn" data-doc-id="${d.id}" title="Retry Extraction">
              Retry
            </button>
          </td>
        </tr>
      `;
    }).join('');

    tbody.querySelectorAll('.pi-filter-doc-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        selectHierarchyDocument(Number(btn.dataset.docId), btn.dataset.docFn);
      });
    });

    tbody.querySelectorAll('.pi-retry-doc-btn').forEach(btn => {
      btn.addEventListener('click', async () => {
        const docId = Number(btn.dataset.docId);
        btn.disabled = true;
        try {
          await API.post(`/api/pdf-intelligence/documents/${docId}/retry`);
          showToast(`Retried document #${docId} successfully`, 'success');
          await Promise.all([loadDocumentsList(), loadCaseRecords(), loadDailyAnalytics()]);
        } catch (err) {
          showToast(`Retry failed: ${err.message}`, 'error');
        } finally {
          btn.disabled = false;
        }
      });
    });
  } catch (err) {
    console.error('Failed to load documents list:', err);
  }
}

// ---------------------------------------------------------------------------
// 5. PDF Analysis Case Records Table, CSV Export & Details Modal
// ---------------------------------------------------------------------------
function getCaseQueryParams() {
  return {
    court_type: PIState.selectedCourtType,
    state_code: PIState.selectedCourtType === 'supreme_court' ? '' : PIState.selectedStateCode,
    district_code: PIState.selectedCourtType === 'supreme_court' ? '' : PIState.selectedDistrictCode,
    complex_code: PIState.selectedComplexCode,
    bench_code: PIState.selectedBenchCode,
    document_id: PIState.selectedDocumentId,
    document_category: PIState.caseDocCategory,
    q: PIState.caseQuery,
    case_type: PIState.caseType,
    judge: PIState.caseJudge,
    extraction_status: PIState.caseStatus,
    sort: PIState.caseSort,
    order: PIState.caseOrder,
    page: PIState.casePage,
    limit: PIState.caseLimit
  };
}

async function loadCaseRecords() {
  const tbody = document.getElementById('pi-cases-tbody');
  const totalBadge = document.getElementById('pi-cases-total-badge');
  const pageInfo = document.getElementById('pi-cases-page-info');
  const pageNum = document.getElementById('pi-cases-page-num');
  const prevBtn = document.getElementById('pi-cases-prev-btn');
  const nextBtn = document.getElementById('pi-cases-next-btn');
  const typeFilter = document.getElementById('pi-case-type-filter');

  if (!tbody) return;

  try {
    const res = await API.get('/api/pdf-intelligence/cases', getCaseQueryParams());
    const items = res.items || [];
    const total = res.total || 0;
    const page = res.page || 1;
    const totalPages = res.total_pages || 1;

    totalBadge.textContent = `${formatNumber(total)} Cases`;
    pageInfo.textContent = `Showing ${items.length} of ${formatNumber(total)} extracted case records`;
    pageNum.textContent = `${page} / ${totalPages}`;
    prevBtn.disabled = page <= 1;
    nextBtn.disabled = page >= totalPages;

    if (typeFilter && res.available_case_types) {
      const currentType = typeFilter.value;
      typeFilter.innerHTML = '<option value="">All Case Types</option>';
      res.available_case_types.forEach(ct => {
        const opt = document.createElement('option');
        opt.value = ct;
        opt.textContent = ct;
        typeFilter.appendChild(opt);
      });
      typeFilter.value = currentType;
    }

    if (!items.length) {
      tbody.innerHTML = '<tr><td colspan="17" style="text-align: center; padding: 28px; color: var(--text-tertiary);">No extracted case records match the active hierarchy and search filters.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(c => {
      const confClass = c.confidence_label === 'high'
        ? 'badge-emerald'
        : (c.confidence_label === 'medium' ? 'badge-blue' : 'badge-amber');
      const idSub = [];
      if (c.diary_number) idSub.push(`Diary: ${c.diary_number}`);
      if (c.cnr_number) idSub.push(`CNR: ${c.cnr_number}`);
      if (c.filing_number) idSub.push(`Filing: ${c.filing_number}`);

      const courtCol = c.court_type === 'supreme_court'
        ? 'Supreme Court of India'
        : (c.complex_name || c.court_name);
      const benchCol = c.establishment_name || c.bench_name;

      return `
        <tr>
          <td class="cell-mono" style="white-space: nowrap;">
            <div style="font-weight: 600;">${escapeHTML(c.case_number)}</div>
            ${idSub.length ? `<div style="font-size: 10.5px; color: var(--text-tertiary);">${escapeHTML(idSub.join(' · '))}</div>` : ''}
          </td>
          <td style="max-width: 220px;">${escapeHTML(c.case_title)}</td>
          <td style="max-width: 160px;">${escapeHTML(c.petitioner || '—')}</td>
          <td style="max-width: 160px;">${escapeHTML(c.respondent || '—')}</td>
          <td><span class="badge badge-mono">${escapeHTML(c.case_type)}</span></td>
          <td style="font-size: 11.5px;">${escapeHTML(DOC_CATEGORY_LABELS[c.document_category] || c.document_category)}</td>
          <td class="cell-mono" style="white-space: nowrap;">${escapeHTML(c.listing_date || '—')}</td>
          <td class="cell-mono" style="white-space: nowrap;">${escapeHTML(c.order_date || '—')}</td>
          <td class="cell-mono" style="white-space: nowrap;">${escapeHTML(c.judgment_date || '—')}</td>
          <td style="max-width: 170px; font-size: 12px;">${escapeHTML(c.judge_names || '—')}</td>
          <td style="font-size: 12px;">${escapeHTML(courtCol)}</td>
          <td style="font-size: 12px;">${escapeHTML(benchCol)}</td>
          <td class="cell-mono" style="font-size: 11px; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHTML(c.pdf_filename)}">
            ${escapeHTML(c.pdf_filename)}
          </td>
          <td><span class="badge badge-mono">${escapeHTML(c.extraction_status)}</span></td>
          <td style="text-align: right;"><span class="badge badge-mono ${confClass}">${c.confidence_pct}%</span></td>
          <td>
            <a href="${escapeHTML(c.original_pdf_link)}" target="_blank" class="btn btn-outline btn-sm">PDF</a>
          </td>
          <td style="text-align: right;">
            <button type="button" class="btn btn-secondary btn-sm pi-view-case-btn" data-case-id="${c.id}">
              View
            </button>
          </td>
        </tr>
      `;
    }).join('');

    tbody.querySelectorAll('.pi-view-case-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        openCaseDetailsModal(Number(btn.dataset.caseId));
      });
    });
  } catch (err) {
    console.error('Failed to load case records:', err);
  }
}

async function openCaseDetailsModal(caseId) {
  const backdrop = document.getElementById('pi-case-modal-backdrop');
  const titleEl = document.getElementById('pi-modal-title');
  const typeEl = document.getElementById('pi-modal-case-type');
  const bodyEl = document.getElementById('pi-modal-body');

  try {
    const res = await API.get(`/api/pdf-intelligence/cases/${caseId}`);
    const c = res.case;
    typeEl.textContent = `${COURT_TIER_LABELS[c.court_type] || c.court_type} · ${c.case_type} · ${c.confidence_pct}% Confidence`;
    titleEl.textContent = `${c.case_number} — ${c.case_title}`;

    const details = c.extracted_details || {};
    const hierarchyPath = c.court_type === 'supreme_court'
      ? `Supreme Court of India (National) → ${c.bench_name}`
      : (c.court_type === 'district_court'
        ? `${c.state_name} → ${c.district_name} → ${c.complex_name || c.court_name} → ${c.establishment_name || c.bench_name}`
        : `${c.state_name} → ${c.district_name} → ${c.court_name} → ${c.bench_name}`);

    bodyEl.innerHTML = `
      <div class="pi-detail-grid">
        <div class="pi-detail-item">
          <span class="pi-detail-label">Case Number</span>
          <div class="pi-detail-val cell-mono">${escapeHTML(c.case_number)}</div>
        </div>
        <div class="pi-detail-item">
          <span class="pi-detail-label">Document Category</span>
          <div class="pi-detail-val">${escapeHTML(DOC_CATEGORY_LABELS[c.document_category] || c.document_category)}</div>
        </div>
        <div class="pi-detail-item">
          <span class="pi-detail-label">Diary Number (SC)</span>
          <div class="pi-detail-val cell-mono">${escapeHTML(c.diary_number || '—')}</div>
        </div>
        <div class="pi-detail-item">
          <span class="pi-detail-label">CNR Number</span>
          <div class="pi-detail-val cell-mono">${escapeHTML(c.cnr_number || '—')}</div>
        </div>
        <div class="pi-detail-item">
          <span class="pi-detail-label">Filing Number (DC)</span>
          <div class="pi-detail-val cell-mono">${escapeHTML(c.filing_number || '—')}</div>
        </div>
        <div class="pi-detail-item">
          <span class="pi-detail-label">Item / Serial No.</span>
          <div class="pi-detail-val cell-mono">${escapeHTML(c.item_number || '—')}</div>
        </div>
        <div class="pi-detail-item">
          <span class="pi-detail-label">Listing Date</span>
          <div class="pi-detail-val cell-mono">${escapeHTML(c.listing_date || '—')}</div>
        </div>
        <div class="pi-detail-item">
          <span class="pi-detail-label">Order Date</span>
          <div class="pi-detail-val cell-mono">${escapeHTML(c.order_date || 'Not provided in document')}</div>
        </div>
        <div class="pi-detail-item">
          <span class="pi-detail-label">Judgment Date</span>
          <div class="pi-detail-val cell-mono">${escapeHTML(c.judgment_date || 'Not provided in document')}</div>
        </div>
        <div class="pi-detail-item">
          <span class="pi-detail-label">Court Room / Number</span>
          <div class="pi-detail-val">${escapeHTML(c.court_room || '—')}</div>
        </div>
        <div class="pi-detail-item">
          <span class="pi-detail-label">Petitioner</span>
          <div class="pi-detail-val">${escapeHTML(c.petitioner || '—')}</div>
        </div>
        <div class="pi-detail-item">
          <span class="pi-detail-label">Respondent</span>
          <div class="pi-detail-val">${escapeHTML(c.respondent || '—')}</div>
        </div>
        <div class="pi-detail-item" style="grid-column: 1 / -1;">
          <span class="pi-detail-label">Presiding Judge(s)</span>
          <div class="pi-detail-val">${escapeHTML(c.judge_names || '—')}</div>
        </div>
        <div class="pi-detail-item" style="grid-column: 1 / -1;">
          <span class="pi-detail-label">Advocates / Advocate-on-Record (AOR)</span>
          <div class="pi-detail-val">${escapeHTML(c.advocate_on_record ? `AOR: ${c.advocate_on_record} | ${c.advocates}` : (c.advocates || '—'))}</div>
        </div>
        <div class="pi-detail-item" style="grid-column: 1 / -1;">
          <span class="pi-detail-label">Unified Court Hierarchy</span>
          <div class="pi-detail-val">${escapeHTML(hierarchyPath)} (Page ${c.page_number})</div>
        </div>
      </div>
      <div>
        <span class="pi-detail-label" style="margin-bottom: 6px;">Raw Extracted PDF Segment (${escapeHTML(details.extraction_method || c.extraction_status)})</span>
        <pre class="pi-raw-excerpt">${escapeHTML(c.raw_excerpt || 'No excerpt stored')}</pre>
      </div>
      <div style="display: flex; justify-content: flex-end; gap: 10px;">
        <a href="${escapeHTML(c.original_pdf_link)}" target="_blank" class="btn btn-primary btn-sm">Open Original PDF</a>
      </div>
    `;
    backdrop.style.display = 'flex';
  } catch (err) {
    showToast(`Could not load case details: ${err.message}`, 'error');
  }
}

// ---------------------------------------------------------------------------
// 6. Daily Analytics & Multi-Tier Comparison (Supreme, High, District Courts)
// ---------------------------------------------------------------------------
async function loadDailyAnalytics(drilldownDate = null) {
  const fromDate = document.getElementById('pi-analytics-from').value;
  const toDate = document.getElementById('pi-analytics-to').value;

  try {
    const res = await API.get('/api/pdf-intelligence/analytics/daily', {
      start_date: fromDate,
      end_date: toDate,
      court_type: PIState.selectedCourtType,
      state_code: PIState.selectedCourtType === 'supreme_court' ? '' : PIState.selectedStateCode,
      district_code: PIState.selectedCourtType === 'supreme_court' ? '' : PIState.selectedDistrictCode,
      complex_code: PIState.selectedComplexCode,
      bench_code: PIState.selectedBenchCode,
      drilldown_date: drilldownDate
    });

    const data = res.data || {};
    const sum = data.summary || {};

    document.getElementById('pi-kpi-discovered').textContent = formatNumber(sum.pdfs_discovered || 0);
    document.getElementById('pi-kpi-discovered-sub').textContent = `${formatNumber(sum.cause_list_pdfs || 0)} Cause Lists · ${formatNumber(sum.order_judgment_pdfs || 0)} Orders/Judgments`;
    document.getElementById('pi-kpi-downloaded').textContent = formatNumber(sum.pdfs_downloaded || 0);
    document.getElementById('pi-kpi-processed').textContent = formatNumber(sum.pdfs_processed || 0);
    document.getElementById('pi-kpi-cases').textContent = formatNumber(sum.total_case_records || 0);
    document.getElementById('pi-kpi-cases-sub').textContent = `${formatNumber(sum.cause_list_cases || 0)} Cause-List · ${formatNumber(sum.order_judgment_cases || 0)} Order/Judgment`;
    document.getElementById('pi-kpi-failures').textContent = formatNumber(sum.extraction_failures || 0);
    document.getElementById('pi-kpi-success-rate').textContent = `${(sum.processing_success_rate || 0).toFixed(1)}%`;

    const sidebarMeta = document.getElementById('pi-sidebar-meta');
    if (sidebarMeta) {
      sidebarMeta.textContent = `${formatNumber(sum.pdfs_processed || 0)} PDFs · ${formatNumber(sum.total_case_records || 0)} Cases`;
    }

    renderTierComparisonCards(data.by_court_category || {});
    renderDailySeriesTable(data.daily_series || []);
    renderStatBars('pi-analytics-by-type', data.cases_by_type || [], 'case_type', 'count');
    renderStatBars('pi-analytics-by-bench', data.cases_by_court_bench || [], 'bench_name', 'total_case_records');
    renderStatBars('pi-analytics-by-judge', data.cases_by_judge || [], 'judge_name', 'case_count');

    if (drilldownDate && data.drilldown) {
      renderDrilldownPanel(data.drilldown);
    }
  } catch (err) {
    console.error('Failed to load daily analytics:', err);
  }
}

function renderTierComparisonCards(byCat) {
  const grid = document.getElementById('pi-tier-comparison-grid');
  if (!grid) return;

  const tiers = [
    { key: 'supreme_court', title: 'Supreme Court of India', accent: 'var(--accent-amber)' },
    { key: 'high_court', title: 'High Courts & Benches', accent: 'var(--accent-blue)' },
    { key: 'district_court', title: 'District & Subordinate Courts', accent: 'var(--accent-emerald)' }
  ];

  grid.innerHTML = tiers.map(t => {
    const stat = byCat[t.key] || {};
    return `
      <div class="kpi-card" style="border-left: 3px solid ${t.accent};">
        <div class="kpi-header">
          <span class="kpi-label">${escapeHTML(t.title)}</span>
          <span class="badge badge-mono">${formatNumber(stat.pdfs_processed || 0)} PDFs</span>
        </div>
        <div class="kpi-value" style="font-size: 22px;">${formatNumber(stat.total_case_records || 0)} Cases</div>
        <div class="kpi-footer">
          Cause-List Cases: <strong>${formatNumber(stat.cause_list_cases || 0)}</strong> &middot;
          Order/Judgment Cases: <strong>${formatNumber(stat.order_judgment_cases || 0)}</strong>
        </div>
      </div>
    `;
  }).join('');
}

function renderDailySeriesTable(series) {
  const tbody = document.getElementById('pi-daily-series-tbody');
  if (!tbody) return;

  if (!series.length) {
    tbody.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-tertiary);">No daily analytics records available for the selected filters.</td></tr>';
    return;
  }

  tbody.innerHTML = series.map(row => `
    <tr>
      <td class="cell-mono" style="font-weight: 600;">${escapeHTML(row.date)}</td>
      <td class="cell-mono" style="text-align: right;">${formatNumber(row.pdfs_discovered)}</td>
      <td class="cell-mono" style="text-align: right;">${formatNumber(row.pdfs_processed)}</td>
      <td class="cell-mono" style="text-align: right;">${formatNumber(row.cause_list_cases || 0)}</td>
      <td class="cell-mono" style="text-align: right;">${formatNumber(row.order_judgment_cases || 0)}</td>
      <td class="cell-mono" style="text-align: right; color: var(--accent-emerald); font-weight: 600;">${formatNumber(row.total_case_records)}</td>
      <td class="cell-mono" style="text-align: right;">${Number(row.processing_success_rate || 0).toFixed(1)}%</td>
      <td style="text-align: right;">
        <button type="button" class="btn btn-outline btn-sm pi-drilldown-btn" data-date="${escapeHTML(row.date)}">
          Drill Down
        </button>
      </td>
    </tr>
  `).join('');

  tbody.querySelectorAll('.pi-drilldown-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      loadDailyAnalytics(btn.dataset.date);
    });
  });
}

function renderStatBars(containerId, items, labelKey, countKey) {
  const el = document.getElementById(containerId);
  if (!el) return;

  if (!items.length) {
    el.innerHTML = '<div style="font-size: 12px; color: var(--text-tertiary);">No records</div>';
    return;
  }

  el.innerHTML = items.slice(0, 12).map(it => `
    <div class="pi-stat-row">
      <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 75%;" title="${escapeHTML(it[labelKey])}">
        ${escapeHTML(it[labelKey])}
      </span>
      <span class="cell-mono" style="font-weight: 600; color: var(--accent-blue);">
        ${formatNumber(it[countKey])}
      </span>
    </div>
  `).join('');
}

function renderDrilldownPanel(drilldown) {
  const panel = document.getElementById('pi-drilldown-panel');
  const title = document.getElementById('pi-drilldown-title');
  const content = document.getElementById('pi-drilldown-content');
  if (!panel || !content) return;

  title.textContent = `Drill-Down for ${drilldown.date} — ${drilldown.documents_total} Source PDF(s), ${drilldown.cases_total} Individual Case Record(s)`;
  const docs = drilldown.documents || [];
  const cases = drilldown.cases || [];

  content.innerHTML = `
    <div style="margin-bottom: 10px; font-size: 12px; color: var(--text-secondary);">
      <strong>Source PDFs (${docs.length}):</strong>
      ${docs.map(d => `<a href="${escapeHTML(d.original_pdf_link)}" target="_blank" class="badge badge-mono" style="margin-left: 6px;">[${escapeHTML(COURT_TIER_LABELS[d.court_type] || d.court_type)}] ${escapeHTML(d.pdf_filename)} (${d.case_count} cases)</a>`).join(' ') || 'None'}
    </div>
    <div class="table-container" style="max-height: 220px; overflow-y: auto;">
      <table class="data-table">
        <thead>
          <tr>
            <th>Tier</th>
            <th>Case Number</th>
            <th>Case Title</th>
            <th>Doc Category</th>
            <th>Judge(s)</th>
            <th>Court / Bench / Establishment</th>
            <th>PDF</th>
          </tr>
        </thead>
        <tbody>
          ${cases.map(c => `
            <tr>
              <td><span class="badge badge-mono">${escapeHTML(COURT_TIER_LABELS[c.court_type] || c.court_type)}</span></td>
              <td class="cell-mono">${escapeHTML(c.case_number)}</td>
              <td>${escapeHTML(c.case_title)}</td>
              <td>${escapeHTML(DOC_CATEGORY_LABELS[c.document_category] || c.document_category)}</td>
              <td>${escapeHTML(c.judge_names || '—')}</td>
              <td>${escapeHTML(c.complex_name ? `${c.complex_name} — ${c.bench_name}` : c.bench_name)}</td>
              <td><a href="${escapeHTML(c.original_pdf_link)}" target="_blank" class="cell-mono" style="color: var(--accent-blue);">${escapeHTML(c.pdf_filename)}</a></td>
            </tr>
          `).join('') || '<tr><td colspan="7" style="text-align:center;">No case records on this date</td></tr>'}
        </tbody>
      </table>
    </div>
  `;
  panel.style.display = 'block';
}

// ---------------------------------------------------------------------------
// 7. Initialization & Event Listeners
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', async () => {
  initSidebar('pdf-intelligence');
  applyDatePreset('previous_3_days');

  document.querySelectorAll('.pi-preset-btn').forEach(btn => {
    btn.addEventListener('click', () => applyDatePreset(btn.dataset.preset));
  });

  ['pi-from-date', 'pi-to-date'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('change', () => applyDatePreset('custom'));
    }
  });

  // Scraper cascading selects
  ['pi-scrape-court-type', 'pi-scrape-doc-category', 'pi-scrape-state', 'pi-scrape-district', 'pi-scrape-complex', 'pi-scrape-bench'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', updateScraperHierarchyOptions);
  });

  document.getElementById('pi-scrape-form').addEventListener('submit', handleStartScrape);

  // Map & Hierarchy reset and breadcrumb clicks
  document.getElementById('pi-reset-map-btn').addEventListener('click', () => {
    PIState.selectedCourtType = '';
    document.querySelectorAll('.pi-tab-btn').forEach(t => {
      t.classList.toggle('active', t.dataset.ctype === '');
    });
    selectHierarchyState('', '');
  });

  document.getElementById('pi-crumb-root').addEventListener('click', () => selectHierarchyState('', ''));
  document.getElementById('pi-crumb-state').addEventListener('click', () => {
    if (PIState.selectedStateCode) selectHierarchyState(PIState.selectedStateCode, PIState.selectedStateName);
  });
  document.getElementById('pi-crumb-district').addEventListener('click', () => {
    if (PIState.selectedDistrictCode) selectHierarchyDistrict(PIState.selectedDistrictCode, PIState.selectedDistrictName);
  });
  document.getElementById('pi-crumb-complex').addEventListener('click', () => {
    if (PIState.selectedComplexCode) selectHierarchyComplex(PIState.selectedComplexCode, PIState.selectedComplexName);
  });
  document.getElementById('pi-crumb-bench').addEventListener('click', () => {
    if (PIState.selectedBenchCode) {
      PIState.selectedDocumentId = null;
      PIState.selectedDocumentFilename = '';
      updateHierarchyBreadcrumbs();
      loadCaseRecords();
    }
  });

  // Court category tabs (All / Supreme Court / High Courts / District Courts)
  document.querySelectorAll('.pi-tab-btn').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.pi-tab-btn').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      PIState.selectedCourtType = tab.dataset.ctype || '';
      if (PIState.selectedCourtType === 'supreme_court') {
        PIState.selectedStateCode = '';
        PIState.selectedStateName = '';
        PIState.selectedDistrictCode = '';
        PIState.selectedDistrictName = '';
        PIState.selectedComplexCode = '';
        PIState.selectedComplexName = '';
      }
      PIState.selectedBenchCode = '';
      PIState.selectedBenchName = '';
      PIState.selectedDocumentId = null;
      PIState.selectedDocumentFilename = '';
      PIState.casePage = 1;

      renderIndiaMap();
      renderHierarchyInspector();
      updateHierarchyBreadcrumbs();
      loadDocumentsList();
      loadCaseRecords();
      loadDailyAnalytics();
    });
  });

  // Case search, filters, sorting, pagination, and CSV export
  document.getElementById('pi-case-search').addEventListener('input', debounce((e) => {
    PIState.caseQuery = e.target.value.trim();
    PIState.casePage = 1;
    loadCaseRecords();
  }, 250));

  document.getElementById('pi-case-doc-cat-filter').addEventListener('change', (e) => {
    PIState.caseDocCategory = e.target.value;
    PIState.casePage = 1;
    loadCaseRecords();
  });

  document.getElementById('pi-case-type-filter').addEventListener('change', (e) => {
    PIState.caseType = e.target.value;
    PIState.casePage = 1;
    loadCaseRecords();
  });

  document.getElementById('pi-case-judge-filter').addEventListener('input', debounce((e) => {
    PIState.caseJudge = e.target.value.trim();
    PIState.casePage = 1;
    loadCaseRecords();
  }, 250));

  document.getElementById('pi-case-status-filter').addEventListener('change', (e) => {
    PIState.caseStatus = e.target.value;
    PIState.casePage = 1;
    loadCaseRecords();
  });

  document.getElementById('pi-clear-case-filters-btn').addEventListener('click', () => {
    document.getElementById('pi-case-search').value = '';
    document.getElementById('pi-case-doc-cat-filter').value = '';
    document.getElementById('pi-case-type-filter').value = '';
    document.getElementById('pi-case-judge-filter').value = '';
    document.getElementById('pi-case-status-filter').value = '';
    PIState.caseQuery = '';
    PIState.caseDocCategory = '';
    PIState.caseType = '';
    PIState.caseJudge = '';
    PIState.caseStatus = '';
    PIState.selectedDocumentId = null;
    PIState.selectedDocumentFilename = '';
    PIState.casePage = 1;
    updateHierarchyBreadcrumbs();
    loadCaseRecords();
  });

  document.querySelectorAll('#pi-cases-table th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      if (PIState.caseSort === col) {
        PIState.caseOrder = PIState.caseOrder === 'asc' ? 'desc' : 'asc';
      } else {
        PIState.caseSort = col;
        PIState.caseOrder = 'desc';
      }
      loadCaseRecords();
    });
  });

  document.getElementById('pi-cases-limit').addEventListener('change', (e) => {
    PIState.caseLimit = Number(e.target.value) || 25;
    PIState.casePage = 1;
    loadCaseRecords();
  });

  document.getElementById('pi-cases-prev-btn').addEventListener('click', () => {
    if (PIState.casePage > 1) {
      PIState.casePage -= 1;
      loadCaseRecords();
    }
  });

  document.getElementById('pi-cases-next-btn').addEventListener('click', () => {
    PIState.casePage += 1;
    loadCaseRecords();
  });

  document.getElementById('pi-export-csv-btn').addEventListener('click', () => {
    const params = new URLSearchParams();
    const qp = getCaseQueryParams();
    Object.keys(qp).forEach(k => {
      if (qp[k] !== null && qp[k] !== undefined && qp[k] !== '') {
        params.append(k, qp[k]);
      }
    });
    params.set('format', 'csv');
    window.location.href = `/api/pdf-intelligence/cases?${params.toString()}`;
  });

  document.getElementById('pi-apply-analytics-filter-btn').addEventListener('click', () => loadDailyAnalytics());
  document.getElementById('pi-close-drilldown-btn').addEventListener('click', () => {
    document.getElementById('pi-drilldown-panel').style.display = 'none';
  });

  document.getElementById('pi-modal-close-btn').addEventListener('click', () => {
    document.getElementById('pi-case-modal-backdrop').style.display = 'none';
  });
  document.getElementById('pi-case-modal-backdrop').addEventListener('click', (e) => {
    if (e.target.id === 'pi-case-modal-backdrop') {
      e.target.style.display = 'none';
    }
  });

  document.getElementById('pi-refresh-all-btn').addEventListener('click', async () => {
    await Promise.all([
      loadStatesAndMapData(),
      loadJobsStatus(),
      loadDocumentsList(),
      loadCaseRecords(),
      loadDailyAnalytics()
    ]);
    showToast('All-India PDF Intelligence data refreshed', 'info');
  });

  await Promise.all([
    loadStatesAndMapData(),
    loadJobsStatus(),
    loadDocumentsList(),
    loadCaseRecords(),
    loadDailyAnalytics()
  ]);
});
