let container = null;

function ensureContainer() {
  if (container) return container;
  container = document.createElement('div');
  container.className = 'toast-container';
  container.setAttribute('role', 'status');
  container.setAttribute('aria-live', 'polite');
  document.body.appendChild(container);
  return container;
}

export function showToast(message, type = 'info', duration = 3800) {
  const c = ensureContainer();
  const toast = document.createElement('div');

  const colors = {
    success: 'bg-emerald-500/20 border-emerald-500/40 text-emerald-300',
    error: 'bg-red-500/20 border-red-500/40 text-red-300',
    info: 'bg-blue-500/20 border-blue-500/40 text-blue-300',
  };
  const icons = { success: '✓', error: '✕', info: 'ℹ' };

  toast.className = `toast flex items-center gap-2 px-4 py-3 rounded-xl border text-sm font-medium ${colors[type] || colors.info}`;
  toast.innerHTML = `<span class="text-base">${icons[type] || icons.info}</span><span>${escapeHtml(message)}</span>`;
  c.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('toast-exit');
    toast.addEventListener('animationend', () => toast.remove());
  }, duration);
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.textContent = str == null ? '' : String(str);
  return d.innerHTML;
}
