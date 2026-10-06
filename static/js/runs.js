const SCRAPER_POLL_INTERVAL_MS = 2500;
let activeJobStartMs = null;
let lastOutputAtMs = null;
let lastOutputText = null;
let currentJobStatus = 'idle';
let scraperCourtOptions = [];
let scraperStates = [];

function formatElapsed(milliseconds) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return hours > 0
    ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

function updateActivityDisplay() {
  if (currentJobStatus !== 'running' || activeJobStartMs === null) return;

  document.getElementById('scraper-elapsed').textContent = formatElapsed(Date.now() - activeJobStartMs);
  const quietForMs = lastOutputAtMs === null ? null : Date.now() - lastOutputAtMs;
  const detail = document.getElementById('scraper-activity-detail');
  const lastOutput = document.getElementById('scraper-last-output');

  if (quietForMs !== null && quietForMs >= 8000) {
    detail.textContent = 'Waiting for eCourts to respond. The scraper process is still running; it has not stopped.';
    lastOutput.textContent = `No new output for ${formatElapsed(quietForMs)}. eCourts may take a little while between requests.`;
  } else {
    detail.textContent = 'Contacting eCourts and checking cause lists. Some requests take a little while.';
    lastOutput.textContent = quietForMs === null
      ? 'Waiting for the first scraper update...'
      : `Scraper output received ${formatElapsed(quietForMs)} ago.`;
  }
}

function setScraperState(status, isRunning) {
  const badge = document.getElementById('scraper-status-badge');
  const jobState = document.getElementById('live-job-state');
  const label = status || 'idle';
  currentJobStatus = label;
  badge.textContent = label.toUpperCase();
  jobState.textContent = label.toUpperCase();

  const color = label === 'running'
    ? 'var(--accent-emerald)'
    : label === 'failed'
      ? 'var(--accent-rose)'
      : 'var(--text-secondary)';
  badge.style.color = color;
  jobState.style.color = color;
  document.getElementById('start-scraper-btn').disabled = Boolean(isRunning);

  const activity = document.getElementById('scraper-activity');
  activity.hidden = !isRunning;
  if (isRunning) {
    document.getElementById('scraper-activity-title').textContent = 'Scraper is running';
    updateActivityDisplay();
  } else if (label === 'completed') {
    document.getElementById('scraper-activity-title').textContent = 'Scrape complete';
  } else if (label === 'failed') {
    document.getElementById('scraper-activity-title').textContent = 'Scrape failed';
  }
}

function populateScraperCourts(courts, states) {
  scraperCourtOptions = courts;
  scraperStates = states;
  const stateInput = document.getElementById('state-code');
  const benchInput = document.getElementById('court-code');
  const aliasesByCode = new Map(states.map(state => [
    state.state_code,
    state.aliases || []
  ]));
  const suggestions = document.getElementById('state-suggestions');
  const optionsList = document.getElementById('state-options-list');

  suggestions.replaceChildren();
  optionsList.replaceChildren();
  states.forEach(state => {
    const option = document.createElement('option');
    option.value = state.state_name;
    option.label = `State code ${state.state_code}`;
    suggestions.appendChild(option);

    (aliasesByCode.get(state.state_code) || []).forEach(alias => {
      const aliasOption = document.createElement('option');
      aliasOption.value = alias;
      aliasOption.label = `State code ${state.state_code}`;
      suggestions.appendChild(aliasOption);
    });

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'scraper-state-option';
    const codeLabel = document.createElement('span');
    codeLabel.textContent = `State code ${state.state_code}: `;
    button.append(codeLabel, document.createTextNode(state.state_name));
    const aliases = aliasesByCode.get(state.state_code) || [];
    if (aliases.length) {
      button.append(document.createTextNode(` (${aliases.join(', ')})`));
    }
    button.addEventListener('click', () => {
      stateInput.value = state.state_name;
      updateBenchChoices();
      document.getElementById('available-states').open = false;
    });
    optionsList.appendChild(button);
  });

  function updateBenchChoices() {
    const enteredState = stateInput.value.trim().toLocaleLowerCase();
    const state = states.find(item =>
      item.state_code === stateInput.value.trim()
      || item.state_name.toLocaleLowerCase() === enteredState
      || (aliasesByCode.get(item.state_code) || []).some(alias => alias.toLocaleLowerCase() === enteredState)
    );
    const benchesSection = document.getElementById('available-benches');
    const benchList = document.getElementById('bench-options-list');
    benchList.replaceChildren();
    benchInput.value = '';
    stateInput.dataset.resolvedCode = state ? state.state_code : '';

    if (!state) {
      benchesSection.hidden = true;
      benchInput.disabled = true;
      benchInput.placeholder = 'Choose a state first';
      document.getElementById('start-scraper-btn').disabled = true;
      document.getElementById('scraper-code-preview').textContent =
        enteredState ? 'Enter a state name, alias, or state code from the available list.' : 'Choose a High Court state to see its numbered benches.';
      return;
    }

    const benches = courts.filter(court => court.state_code === state.state_code);
    document.getElementById('bench-list-title').textContent =
      `High Courts and benches for ${state.state_name} (state code ${state.state_code})`;
    benches.forEach((bench, index) => {
      const item = document.createElement('li');
      item.append(
        document.createTextNode(`${bench.court_name} — court code `)
      );
      const code = document.createElement('code');
      code.textContent = bench.court_code;
      item.append(code);
      benchList.appendChild(item);
    });
    benchesSection.hidden = benches.length === 0;
    benchInput.disabled = benches.length === 0;
    benchInput.max = String(benches.length);
    benchInput.placeholder = `Enter 1 to ${benches.length}`;
    document.getElementById('start-scraper-btn').disabled = benches.length === 0;
    document.getElementById('scraper-code-preview').textContent =
      `Selected state code: ${state.state_code}. Enter the numbered bench from the list below.`;
  }

  stateInput.disabled = states.length === 0;
  stateInput.value = states.some(state => state.state_code === '1')
    ? '1'
    : (states[0]?.state_name || '');
  stateInput.addEventListener('input', updateBenchChoices);
  benchInput.addEventListener('input', updateScraperCodePreview);
  updateBenchChoices();
}

function updateScraperCodePreview() {
  const stateInput = document.getElementById('state-code');
  const benchInput = document.getElementById('court-code');
  const benchNumber = Number(benchInput.value);
  const stateCode = stateInput.dataset.resolvedCode;
  const preview = document.getElementById('scraper-code-preview');
  const benches = scraperCourtOptions.filter(court => court.state_code === stateCode);
  if (stateCode && Number.isInteger(benchNumber) && benchNumber >= 1 && benchNumber <= benches.length) {
    const selectedBench = benches[benchNumber - 1];
    preview.textContent = `Ready to scrape: ${selectedBench.state_name} (state code ${stateCode}), bench ${benchNumber} — ${selectedBench.court_name} (court code ${selectedBench.court_code}).`;
  } else if (stateCode) {
    preview.textContent = `Selected state code: ${stateCode}. Enter a bench number from 1 to ${benches.length}.`;
  }
}

async function loadScraperCourts() {
  try {
    const result = await API.get('/api/scraper/options');
    populateScraperCourts(result.courts || [], result.states || []);
    if (!result.courts || result.courts.length === 0 || !result.states || result.states.length === 0) {
      document.getElementById('scraper-code-preview').textContent = 'No High Courts are available in the scraper catalogue.';
    }
  } catch (error) {
    document.getElementById('state-code').disabled = true;
    document.getElementById('court-code').disabled = true;
    document.getElementById('start-scraper-btn').disabled = true;
    document.getElementById('scraper-code-preview').textContent = `Could not load High Court options: ${error.message}`;
    document.getElementById('scraper-message').textContent = 'High Court options failed to load. Refresh the page to try again.';
  }
}

async function refreshScraperStatus() {
  try {
    const result = await API.get('/api/scraper/status');
    const job = result.live_job || {};
    const outputText = (job.log_lines || []).join('\n');
    if (job.is_running && job.started_at) {
      const startMs = new Date(job.started_at.replace(' ', 'T')).getTime();
      if (Number.isFinite(startMs) && activeJobStartMs !== startMs) {
        activeJobStartMs = startMs;
        lastOutputAtMs = null;
        lastOutputText = null;
      }
      const outputLines = job.log_lines || [];
      const latestOutput = outputLines.length ? outputLines[outputLines.length - 1] : null;
      if (latestOutput && latestOutput !== lastOutputText) {
        lastOutputText = latestOutput;
        lastOutputAtMs = Date.now();
      }
    }
    setScraperState(job.status, job.is_running);

    document.getElementById('live-job-details').textContent = job.court_info
      ? `${job.court_info} | Started: ${job.started_at || '—'}${job.finished_at ? ` | Finished: ${job.finished_at} | Duration: ${formatElapsed((job.duration_seconds || 0) * 1000)}` : ''}`
      : 'No scraper has been started in this app process.';
    document.getElementById('scraper-log').textContent = outputText || 'No scraper output yet.';
    const log = document.getElementById('scraper-log');
    log.scrollTop = log.scrollHeight;

    const message = document.getElementById('scraper-message');
    if (job.error) {
      message.textContent = `SCRAPE FAILED: ${job.error}`;
    } else if (job.status === 'completed') {
      message.textContent = `SCRAPE SUCCESSFUL${job.duration_seconds !== null && job.duration_seconds !== undefined ? ` — finished in ${formatElapsed(job.duration_seconds * 1000)}` : ''}.`;
    } else if (job.is_running) {
      message.textContent = 'Scraper is running. This page updates automatically.';
    }

  } catch (error) {
    document.getElementById('scraper-status-badge').textContent = 'STATUS UNAVAILABLE';
    document.getElementById('live-job-state').textContent = 'UNAVAILABLE';
    document.getElementById('scraper-message').textContent = `Could not load scraper status: ${error.message}`;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initSidebar('runs');
  const form = document.getElementById('scraper-form');
  loadScraperCourts();

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = document.getElementById('start-scraper-btn');
    const message = document.getElementById('scraper-message');
    button.disabled = true;
    message.textContent = 'Requesting scraper start...';

    try {
      const stateInput = document.getElementById('state-code');
      const courtInput = document.getElementById('court-code');
      const stateCode = stateInput.dataset.resolvedCode;
      const benchIndex = Number(courtInput.value);
      const benches = scraperCourtOptions.filter(court => court.state_code === stateCode);
      if (!stateCode) throw new Error('Enter a valid High Court name or state code.');
      if (!Number.isInteger(benchIndex) || benchIndex < 1 || benchIndex > benches.length) {
        throw new Error(`Enter a bench number from 1 to ${benches.length}.`);
      }

      await API.post('/api/scraper/trigger', {
        state_code: stateCode,
        court_code: benches[benchIndex - 1].court_code,
        days: Number(document.getElementById('scrape-days').value)
      });
      message.textContent = 'Scraper started. Live output will appear below.';
      await refreshScraperStatus();
    } catch (error) {
      message.textContent = `Could not start scraper: ${error.message}`;
      button.disabled = false;
    }
  });

  refreshScraperStatus();
  window.setInterval(refreshScraperStatus, SCRAPER_POLL_INTERVAL_MS);
  window.setInterval(updateActivityDisplay, 1000);
});
