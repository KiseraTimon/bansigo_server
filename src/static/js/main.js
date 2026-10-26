// src/static/js/main.js

/**
 * Global JavaScript utilities for BansiGo platform:
 * - Dark/Light theme switching & persistence
 * - Toast message notifications
 * - Formatting helpers
 */

(function () {
  // 1. Theme Initialization
  function initTheme() {
    const savedTheme = localStorage.getItem('bansigo-theme');
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = savedTheme || (prefersDark ? 'dark' : 'light');
    applyTheme(theme);
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-bs-theme', theme);
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('bansigo-theme', theme);

    const themeToggleBtn = document.getElementById('themeToggleBtn');
    if (themeToggleBtn) {
      const icon = themeToggleBtn.querySelector('i');
      if (icon) {
        icon.className = theme === 'dark' ? 'ri-sun-line text-warning' : 'ri-moon-line text-secondary';
      }
    }
  }

  window.toggleTheme = function () {
    const currentTheme = document.documentElement.getAttribute('data-bs-theme') || 'light';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    applyTheme(newTheme);
  };

  // 2. Global Toast Notification
  window.showToast = function (message, type = 'info') {
    let toast = document.getElementById('bansiToast');
    if (!toast) {
      toast = document.createElement('div');
      toast.id = 'bansiToast';
      toast.className = 'bansi-toast';
      document.body.appendChild(toast);
    }

    const icons = {
      success: 'ri-checkbox-circle-fill text-success fs-5',
      error: 'ri-error-warning-fill text-danger fs-5',
      warning: 'ri-alert-fill text-warning fs-5',
      info: 'ri-information-fill text-primary fs-5',
    };

    toast.innerHTML = `
      <i class="${icons[type] || icons.info}"></i>
      <div class="flex-grow-1 small">${message}</div>
      <button type="button" class="btn-close ms-2" onclick="this.parentElement.classList.remove('show')" aria-label="Close"></button>
    `;

    toast.classList.add('show');
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
      toast.classList.remove('show');
    }, 4500);
  };

  // 3. Currency and Number Formatting
  window.formatCurrency = function (amount) {
    const num = parseFloat(amount) || 0;
    return 'KES ' + num.toLocaleString('en-KE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };

  document.addEventListener('DOMContentLoaded', initTheme);
})();
