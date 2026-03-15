/**
 * Cold Lead — Frontend App v1.1
 *
 * Handles:
 *  - Search form submission
 *  - SSE streaming for real-time scraping progress
 *  - Results table rendering
 *  - Download JSON / XLSX & copy to clipboard
 *  - Persistent job history
 */

// ─── DOM Elements ────────────────────────────────────────────
const searchInput     = document.getElementById('search-input');
const searchBtn       = document.getElementById('search-btn');
const maxScrollsInput = document.getElementById('max-scrolls');
const scrollsValue    = document.getElementById('scrolls-value');

const progressSection = document.getElementById('progress-section');
const progressTitle   = document.getElementById('progress-title');
const progressBar     = document.getElementById('progress-bar');
const pulseDot        = document.getElementById('pulse-dot');
const logContainer    = document.getElementById('log-container');

const statsSection    = document.getElementById('stats-section');
const statFound       = document.getElementById('stat-found');
const statExtracted   = document.getElementById('stat-extracted');
const statPhone       = document.getElementById('stat-phone');
const statNoPhone     = document.getElementById('stat-no-phone');

const resultsSection  = document.getElementById('results-section');
const resultsBody     = document.getElementById('results-body');
const downloadBtn     = document.getElementById('download-btn');
const xlsxBtn         = document.getElementById('xlsx-btn');
const copyBtn         = document.getElementById('copy-btn');

const historySection  = document.getElementById('history-section');
const historyList     = document.getElementById('history-list');
const historyCount    = document.getElementById('history-count');
const historyEmpty    = document.getElementById('history-empty');

let currentJobId = null;
let currentResults = [];

// ─── Init ────────────────────────────────────────────────────
loadHistory();

// ─── Range slider live value ─────────────────────────────────
maxScrollsInput.addEventListener('input', () => {
  scrollsValue.textContent = maxScrollsInput.value;
});

// ─── Search ──────────────────────────────────────────────────
searchBtn.addEventListener('click', startScrape);
searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') startScrape();
});

async function startScrape() {
  const query = searchInput.value.trim();
  if (!query) {
    searchInput.focus();
    showToast('Type a search query first!', true);
    return;
  }

  // Reset UI
  searchBtn.disabled = true;
  searchBtn.classList.add('loading');
  logContainer.innerHTML = '';
  resultsBody.innerHTML = '';
  currentResults = [];

  progressSection.classList.remove('hidden');
  statsSection.classList.add('hidden');
  resultsSection.classList.add('hidden');
  progressTitle.textContent = 'Starting...';
  progressBar.style.width = '0%';
  progressBar.classList.add('indeterminate');
  pulseDot.className = 'pulse-dot';

  try {
    const res = await fetch('/api/scrape', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query,
        max_scrolls: parseInt(maxScrollsInput.value),
        headless: true,
      }),
    });

    if (!res.ok) throw new Error('Failed to start scraping');

    const data = await res.json();
    currentJobId = data.job_id;

    // Start SSE stream
    connectSSE(currentJobId);

  } catch (err) {
    showToast('Failed to start scraping: ' + err.message, true);
    resetSearchBtn();
  }
}

// ─── SSE Stream ──────────────────────────────────────────────
function connectSSE(jobId) {
  const evtSource = new EventSource(`/api/scrape/${jobId}/stream`);

  evtSource.addEventListener('log', (e) => {
    const log = JSON.parse(e.data);
    addLogEntry(log);
  });

  evtSource.addEventListener('status', (e) => {
    const status = JSON.parse(e.data);
    updateStats(status);

    if (status.status === 'running') {
      progressTitle.textContent = 'Scraping...';
    }
  });

  evtSource.addEventListener('complete', (e) => {
    const result = JSON.parse(e.data);
    evtSource.close();

    progressBar.classList.remove('indeterminate');

    if (result.status === 'done') {
      progressTitle.textContent = 'Done! 🎉';
      progressBar.style.width = '100%';
      pulseDot.classList.add('done');
      updateStats(result);
      loadResults(jobId);
    } else {
      progressTitle.textContent = 'Error ❌';
      pulseDot.classList.add('error');
      showToast('Scraping failed: ' + (result.error || 'Unknown error'), true);
    }

    resetSearchBtn();
    // Refresh history to show the new job
    loadHistory();
  });

  evtSource.onerror = () => {
    evtSource.close();
    progressTitle.textContent = 'Connection lost';
    pulseDot.classList.add('error');
    resetSearchBtn();
  };
}

// ─── Log entries ─────────────────────────────────────────────
function addLogEntry(log) {
  const div = document.createElement('div');
  div.className = 'log-entry' + (log.level === 'error' ? ' error' : '');
  div.innerHTML = `
    <span class="log-time">${log.time}</span>
    <span class="log-message">${escapeHtml(log.message)}</span>
  `;
  logContainer.appendChild(div);
  logContainer.scrollTop = logContainer.scrollHeight;
}

// ─── Stats ───────────────────────────────────────────────────
function updateStats(data) {
  statsSection.classList.remove('hidden');
  animateNumber(statFound, data.total_found || 0);
  animateNumber(statExtracted, data.total_extracted || 0);
  animateNumber(statPhone, data.total_with_phone || 0);
  animateNumber(statNoPhone, data.total_without_phone || 0);
}

function animateNumber(el, target) {
  const current = parseInt(el.textContent) || 0;
  if (current === target) return;

  const duration = 400;
  const start = performance.now();

  function tick(now) {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = Math.round(current + (target - current) * eased);
    if (progress < 1) requestAnimationFrame(tick);
  }

  requestAnimationFrame(tick);
}

// ─── Results ─────────────────────────────────────────────────
async function loadResults(jobId) {
  try {
    const res = await fetch(`/api/scrape/${jobId}/results`);
    const data = await res.json();
    currentResults = data.results || [];
    currentJobId = jobId;

    // Update stats from loaded data
    updateStats({
      total_found: data.total_found || 0,
      total_extracted: data.total_extracted || 0,
      total_with_phone: data.total_with_phone || 0,
      total_without_phone: data.total_without_phone || 0,
    });

    renderResults(currentResults);
    resultsSection.classList.remove('hidden');
    statsSection.classList.remove('hidden');

    // Scroll to results
    resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (err) {
    showToast('Failed to load results', true);
  }
}

function renderResults(results) {
  resultsBody.innerHTML = '';

  results.forEach((item, i) => {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td>${escapeHtml(item.name || '—')}</td>
      <td>${escapeHtml(item.phone || '—')}</td>
      <td>${escapeHtml(item.address || '—')}</td>
      <td>${item.rating ? `<span class="rating-badge">★ ${escapeHtml(item.rating)}</span>` : '—'}</td>
      <td>${item.website
        ? `<a href="${escapeHtml(item.website)}" target="_blank" rel="noopener" class="website-link">${truncateUrl(item.website)}</a>`
        : '—'
      }</td>
    `;
    tr.style.animation = `fadeInUp 0.3s ease-out ${i * 0.03}s both`;
    resultsBody.appendChild(tr);
  });
}

// ─── Download JSON ───────────────────────────────────────────
downloadBtn.addEventListener('click', () => {
  if (!currentJobId) return;
  window.open(`/api/scrape/${currentJobId}/download`, '_blank');
});

// ─── Download XLSX ───────────────────────────────────────────
xlsxBtn.addEventListener('click', () => {
  if (!currentJobId) return;
  window.open(`/api/scrape/${currentJobId}/xlsx`, '_blank');
});

// ─── Copy phones ─────────────────────────────────────────────
copyBtn.addEventListener('click', () => {
  if (!currentResults.length) return;

  const phones = currentResults
    .map(r => r.phone)
    .filter(Boolean)
    .join('\n');

  navigator.clipboard.writeText(phones).then(() => {
    showToast(`${currentResults.filter(r => r.phone).length} phones copied!`);
  }).catch(() => {
    showToast('Failed to copy', true);
  });
});

// ─── History ─────────────────────────────────────────────────
async function loadHistory() {
  try {
    const res = await fetch('/api/jobs');
    const jobs = await res.json();
    renderHistory(jobs);
  } catch (err) {
    console.error('Failed to load history:', err);
  }
}

function renderHistory(jobs) {
  historyList.innerHTML = '';

  if (!jobs.length) {
    historyList.innerHTML = '<p class="history-empty">No scraping jobs yet. Run your first search above!</p>';
    historyCount.textContent = '0 jobs';
    return;
  }

  historyCount.textContent = `${jobs.length} job${jobs.length !== 1 ? 's' : ''}`;

  jobs.forEach((job, i) => {
    const card = document.createElement('div');
    card.className = 'history-card';
    card.style.animation = `fadeInUp 0.3s ease-out ${i * 0.05}s both`;

    const statusClass = job.status === 'error' ? 'error' : (job.status === 'running' ? 'running' : '');
    const date = new Date(job.created_at);
    const dateStr = date.toLocaleDateString('pt-BR', {
      day: '2-digit', month: '2-digit', year: '2-digit',
      hour: '2-digit', minute: '2-digit',
    });

    card.innerHTML = `
      <div class="history-card-info">
        <div class="history-query">${escapeHtml(job.query)}</div>
        <div class="history-meta">
          <span class="history-status">
            <span class="history-status-dot ${statusClass}"></span>
            ${job.status}
          </span>
          <span>${dateStr}</span>
          <span>📞 ${job.total_with_phone || 0} leads</span>
        </div>
      </div>
      <div class="history-card-actions">
        ${job.status === 'done' ? `
          <button class="btn-sm" data-action="view" data-id="${job.id}" title="View results">📋 View</button>
          <button class="btn-sm" data-action="json" data-id="${job.id}" title="Download JSON">⬇ JSON</button>
          <button class="btn-sm xlsx" data-action="xlsx" data-id="${job.id}" title="Download XLSX">📊 XLSX</button>
        ` : ''}
      </div>
    `;

    // Event delegation for action buttons
    card.querySelectorAll('.btn-sm').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const action = btn.dataset.action;
        const id = btn.dataset.id;

        if (action === 'view') {
          loadResults(id);
          progressSection.classList.add('hidden');
        } else if (action === 'json') {
          window.open(`/api/scrape/${id}/download`, '_blank');
        } else if (action === 'xlsx') {
          window.open(`/api/scrape/${id}/xlsx`, '_blank');
        }
      });
    });

    // Click card to view results
    card.addEventListener('click', () => {
      if (job.status === 'done') {
        loadResults(job.id);
        progressSection.classList.add('hidden');
      }
    });

    historyList.appendChild(card);
  });
}

// ─── Helpers ─────────────────────────────────────────────────
function resetSearchBtn() {
  searchBtn.disabled = false;
  searchBtn.classList.remove('loading');
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function truncateUrl(url) {
  try {
    const u = new URL(url);
    return u.hostname.replace('www.', '');
  } catch {
    return url.substring(0, 30) + '...';
  }
}

function showToast(message, isError = false) {
  document.querySelectorAll('.toast').forEach(t => t.remove());

  const toast = document.createElement('div');
  toast.className = 'toast' + (isError ? ' error' : '');
  toast.textContent = message;
  document.body.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s';
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}
