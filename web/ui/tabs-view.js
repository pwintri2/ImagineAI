let activeTab = 'image';
let onTabChange = null;

export function init(callback) {
  onTabChange = callback;
  const tabBar = document.getElementById('tabBar');
  if (!tabBar) return;
  tabBar.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-tab]');
    if (!btn || btn.dataset.tab === activeTab) return;
    switchTab(btn.dataset.tab);
  });
}

function switchTab(tab) {
  activeTab = tab;
  document.querySelectorAll('[data-tab]').forEach((btn) => {
    const isActive = btn.dataset.tab === tab;
    btn.classList.toggle('tab-active', isActive);
    btn.classList.toggle('border-transparent', !isActive);
    btn.classList.toggle('text-slate-400', !isActive);
    btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
  });
  document.getElementById('image-section')?.classList.toggle('hidden', tab !== 'image');
  document.getElementById('video-section')?.classList.toggle('hidden', tab !== 'video');
  if (onTabChange) onTabChange(tab);
}

export function getActiveTab() { return activeTab; }
