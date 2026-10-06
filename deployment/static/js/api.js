/**
 * eCourts Judicial Intelligence - API Client & Common Utilities
 */

const API = {
  async get(endpoint, params = {}) {
    const url = new URL(endpoint, window.location.origin);
    Object.keys(params).forEach(key => {
      if (params[key] !== null && params[key] !== undefined && params[key] !== '') {
        url.searchParams.append(key, params[key]);
      }
    });

    try {
      const res = await fetch(url.toString(), {
        headers: {
          'Accept': 'application/json'
        }
      });

      const json = await res.json();
      if (!res.ok || json.success === false) {
        throw new Error(json.error || `HTTP error ${res.status}`);
      }
      return json;
    } catch (err) {
      console.error(`[API Error] GET ${endpoint}:`, err);
      throw err;
    }
  },

  async post(endpoint, data = {}) {
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify(data)
      });
      const json = await res.json();
      if (!res.ok || json.success === false) {
        throw new Error(json.error || `HTTP error ${res.status}`);
      }
      return json;
    } catch (err) {
      console.error(`[API Error] POST ${endpoint}:`, err);
      throw err;
    }
  }
};

// Formatting Utilities
function formatNumber(num) {
  if (num === null || num === undefined) return '0';
  return Number(num).toLocaleString('en-IN');
}

function formatDate(dateStr) {
  if (!dateStr) return '—';
  try {
    const parts = dateStr.split('-');
    if (parts.length === 3) {
      const year = parseInt(parts[0], 10);
      const month = parseInt(parts[1], 10) - 1;
      const day = parseInt(parts[2], 10);
      const d = new Date(year, month, day);
      return d.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
    }
    return dateStr;
  } catch (e) {
    return dateStr;
  }
}

function formatFileSize(bytes) {
  if (!bytes || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

function escapeHTML(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// Toast Notifications
function showToast(message, type = 'info') {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    container.className = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = 'toast';

  let iconName = 'info';
  let badgeClass = 'text-primary';
  if (type === 'success') {
    iconName = 'check-circle-2';
    badgeClass = 'text-emerald';
  } else if (type === 'error') {
    iconName = 'alert-triangle';
    badgeClass = 'text-rose';
  }

  toast.innerHTML = `
    <i data-lucide="${iconName}" style="width: 16px; height: 16px; flex-shrink: 0;" class="${badgeClass}"></i>
    <span style="flex: 1;">${escapeHTML(message)}</span>
  `;

  container.appendChild(toast);
  renderIcons();

  setTimeout(() => {
    toast.style.transition = 'opacity 200ms ease, transform 200ms ease';
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(8px)';
    setTimeout(() => toast.remove(), 220);
  }, 3500);
}

// Sidebar & Layout Handler
function initSidebar(activePage = 'dashboard') {
  // Highlight active link
  document.querySelectorAll('.sidebar-nav .nav-item').forEach(el => {
    if (el.dataset.page === activePage) {
      el.classList.add('active');
    } else {
      el.classList.remove('active');
    }
  });

  // Mobile menu toggle
  const toggleBtn = document.getElementById('mobile-nav-toggle');
  const sidebar = document.querySelector('.app-sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');

  if (toggleBtn && sidebar) {
    toggleBtn.addEventListener('click', () => {
      sidebar.classList.toggle('open');
      if (backdrop) backdrop.classList.toggle('active');
    });
  }

  if (backdrop && sidebar) {
    backdrop.addEventListener('click', () => {
      sidebar.classList.remove('open');
      backdrop.classList.remove('active');
    });
  }
}

// Render Lucide Icons safely
function renderIcons() {
  if (window.lucide && typeof window.lucide.createIcons === 'function') {
    window.lucide.createIcons();
  }
}

document.addEventListener('DOMContentLoaded', () => {
  renderIcons();
});
