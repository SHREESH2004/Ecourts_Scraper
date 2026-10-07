/**
 * PDF Viewer Logic - eCourts Judicial Intelligence
 * Streams PDF via browser native viewer and displays metadata inspector
 */

async function initPdfViewer() {
  initSidebar('pdfs');

  const params = new URLSearchParams(window.location.search);
  const fileParam = params.get('file');
  const idParam = params.get('id');

  if (!fileParam && !idParam) {
    showToast('No PDF specified. Redirecting to PDF Library...', 'error');
    setTimeout(() => {
      window.location.href = '/pdfs.html';
    }, 1500);
    return;
  }

  try {
    const res = await API.get('/api/pdf/metadata', { file: fileParam, id: idParam });
    const doc = res.data;

    const streamUrl = `/api/pdf/${encodeURIComponent(doc.filename)}?id=${encodeURIComponent(doc.id)}`;
    const downloadUrl = `${streamUrl}&download=1`;

    // 1. Set top bar elements
    document.getElementById('top-filename-display').textContent = doc.filename;
    document.title = `${doc.filename} - eCourts Document Viewer`;

    document.getElementById('top-new-tab-btn').href = streamUrl;
    document.getElementById('top-download-btn').href = downloadUrl;

    // 2. Load PDF into native iframe
    const iframe = document.getElementById('pdf-frame');
    iframe.src = streamUrl;

    // 3. Populate metadata inspector
    document.getElementById('meta-filename').textContent = doc.filename;
    document.getElementById('meta-judge-link').textContent = doc.judge_name || '—';
    document.getElementById('meta-judge-link').href = `/judge.html?name=${encodeURIComponent(doc.judge_name)}`;
    document.getElementById('meta-date').textContent = formatDate(doc.cause_list_date);
    document.getElementById('meta-state').textContent = doc.state_name;
    document.getElementById('meta-district').textContent = doc.district_code;
    document.getElementById('meta-court').textContent = doc.court_name;
    document.getElementById('meta-filesize').textContent = doc.file_size ? formatFileSize(doc.file_size) : '—';
    document.getElementById('meta-reference').textContent = doc.reference_name || '—';

    // Storage/source badge
    const badge = document.getElementById('detail-storage-badge');
    if (doc.has_file) {
      badge.className = 'badge badge-mono badge-emerald';
      badge.textContent = doc.file_source === 'court_source'
        ? 'Court-hosted PDF'
        : doc.file_source === 'supabase_storage'
          ? 'Supabase Storage'
          : 'Legacy local PDF';
    } else {
      badge.className = 'badge badge-mono badge-amber';
      badge.textContent = 'Metadata Only';
      document.getElementById('pdf-frame').style.display = 'none';
      document.getElementById('pdf-fallback').style.display = 'block';
    }

    // 4. Populate action buttons
    document.getElementById('pane-download-btn').href = downloadUrl;
    document.getElementById('pane-new-tab-btn').href = streamUrl;
    document.getElementById('pane-judge-dossier-btn').href = `/judge.html?name=${encodeURIComponent(doc.judge_name)}`;
    document.getElementById('fallback-download-btn').href = downloadUrl;

    // Copy link handler
    document.getElementById('copy-link-btn').addEventListener('click', () => {
      navigator.clipboard.writeText(window.location.href).then(() => {
        showToast('Document viewer URL copied to clipboard', 'success');
      }).catch(() => {
        showToast('Failed to copy URL', 'error');
      });
    });

    renderIcons();
  } catch (err) {
    console.error('Failed to load PDF metadata:', err);
    showToast(`Error opening PDF: ${err.message}`, 'error');
    document.getElementById('top-filename-display').textContent = 'Document Not Found';
    document.getElementById('pdf-frame').style.display = 'none';
    document.getElementById('pdf-fallback').style.display = 'block';
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initPdfViewer();
});
