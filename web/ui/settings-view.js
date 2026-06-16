import { getState, setState } from '../state.js';
import { getConfig, getSecrets, saveSecret, saveSettings } from '../services/api.js';
import { showToast } from './toast-view.js';

let panelEl, bodyEl, isOpen = false;
let secrets = { providers: {} };
let onConfigChange = null;

export function init(configChangeCallback) {
  onConfigChange = configChangeCallback;
  panelEl = document.getElementById('settings-panel');
  bodyEl = document.getElementById('settingsBody');
  document.getElementById('settingsToggle')?.addEventListener('click', toggle);
  document.getElementById('closeSettingsBtn')?.addEventListener('click', close);
  document.getElementById('settingsOverlay')?.addEventListener('click', close);
}

export async function open() {
  isOpen = true;
  panelEl?.classList.remove('hidden');
  animate();
  render();
  try {
    secrets = await getSecrets();
    render();
  } catch (e) {
    console.warn('Could not load secrets:', e);
  }
}

function close() { isOpen = false; panelEl?.classList.add('hidden'); }
function toggle() { isOpen ? close() : open(); }

function animate() {
  const inner = panelEl?.querySelector('.relative');
  if (!inner) return;
  inner.classList.remove('slide-in-right');
  void inner.offsetWidth;
  inner.classList.add('slide-in-right');
}

function render() {
  if (!bodyEl) return;
  const s = getState();
  const c = s.config;
  const gem = secrets.providers?.gemini || {};
  const xai = secrets.providers?.xai || {};

  const dot = (ok) => `<span class="w-2 h-2 rounded-full ${ok ? 'bg-emerald-400' : 'bg-slate-600'} inline-block"></span>`;

  bodyEl.innerHTML = `
    <section class="space-y-3">
      <h3 class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Status</h3>
      <div class="rounded-xl border border-white/10 bg-white/[0.03] p-3 space-y-2 text-xs">
        <div class="flex items-center justify-between">
          <span class="text-slate-400">${dot(c.comfyReachable)} ComfyUI</span>
          <span class="text-slate-500">${c.comfyReachable ? 'connected' : 'not reachable'}</span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-slate-400">${dot(c.models?.image?.zimage_turbo)} Z-Image Turbo</span>
          <span class="text-slate-500">image</span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-slate-400">${dot(c.models?.video?.wan22_14b)} Wan 2.2 14B</span>
          <span class="text-slate-500">video</span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-slate-400">${dot(c.models?.video?.wan21_1_3b)} Wan 2.1 1.3B</span>
          <span class="text-slate-500">video</span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-slate-400">${dot(c.geminiConfigured)} Gemini fallback</span>
          <span class="text-slate-500">${c.geminiConfigured ? 'key saved' : 'no key'}</span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-slate-400">${dot(c.xaiConfigured)} Grok Imagine</span>
          <span class="text-slate-500">${c.xaiConfigured ? 'key saved' : 'no key'}</span>
        </div>
      </div>
    </section>

    <section class="space-y-3">
      <h3 class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Gemini API key (cloud image fallback)</h3>
      <p class="text-[11px] text-slate-500">Stored locally on this machine (data/secrets.json, chmod 600). Used only for the Image tab's cloud engine.</p>
      <div class="flex gap-2">
        <input id="geminiKeyInput" type="password" autocomplete="off" placeholder="${gem.configured ? 'Saved ' + escapeAttr(gem.hint || '') : 'AIza…'}"
          class="flex-1 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
        <button id="saveGeminiKey" type="button" class="px-3 py-2 rounded-xl bg-violet-500/20 hover:bg-violet-500/30 border border-violet-500/30 text-violet-300 text-xs font-medium transition">Save</button>
      </div>
      ${gem.configured ? `<button id="clearGeminiKey" type="button" class="text-[11px] text-red-400/70 hover:text-red-400 transition">Remove saved key</button>` : ''}
      <div class="space-y-1.5">
        <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Gemini image model</label>
        <input id="geminiModelInput" type="text" value="${escapeAttr(c.geminiModel || '')}" placeholder="gemini-2.5-flash-image"
          class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
      </div>
      <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noopener" class="text-[11px] text-violet-400/80 hover:text-violet-300 transition inline-block">Get a Google AI Studio key ↗</a>
    </section>

    <section class="space-y-3">
      <h3 class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">xAI API key (Grok image + video)</h3>
      <p class="text-[11px] text-slate-500">Stored locally on this machine (data/secrets.json, chmod 600). Used for the Image tab's Grok engine and the Video tab's Grok Imagine model.</p>
      <div class="flex gap-2">
        <input id="xaiKeyInput" type="password" autocomplete="off" placeholder="${xai.configured ? 'Saved ' + escapeAttr(xai.hint || '') : 'xai-…'}"
          class="flex-1 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
        <button id="saveXaiKey" type="button" class="px-3 py-2 rounded-xl bg-violet-500/20 hover:bg-violet-500/30 border border-violet-500/30 text-violet-300 text-xs font-medium transition">Save</button>
      </div>
      ${xai.configured ? `<button id="clearXaiKey" type="button" class="text-[11px] text-red-400/70 hover:text-red-400 transition">Remove saved key</button>` : ''}
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <div class="space-y-1.5">
          <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Grok image model</label>
          <input id="xaiImageModelInput" type="text" value="${escapeAttr(c.xaiImageModel || '')}" placeholder="grok-imagine-image-quality"
            class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
        </div>
        <div class="space-y-1.5">
          <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Grok video model</label>
          <input id="xaiVideoModelInput" type="text" value="${escapeAttr(c.xaiVideoModel || '')}" placeholder="grok-imagine-video"
            class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
        </div>
      </div>
      <a href="https://console.x.ai/team/60586ab6-ba7f-4fcc-a2c8-1425021c6f1b/api-keys" target="_blank" rel="noopener" class="text-[11px] text-violet-400/80 hover:text-violet-300 transition inline-block">Open xAI API keys ↗</a>
    </section>

    <section class="space-y-3">
      <h3 class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">ComfyUI server</h3>
      <div class="flex gap-2">
        <input id="comfyUrlInput" type="url" value="${escapeAttr(c.comfyUrl || '')}" placeholder="http://127.0.0.1:8188"
          class="flex-1 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
        <button id="saveComfyUrl" type="button" class="px-3 py-2 rounded-xl bg-white/10 hover:bg-white/15 border border-white/10 text-slate-200 text-xs font-medium transition">Save</button>
      </div>
      <p class="text-[11px] text-slate-500">This is your local <strong>ComfyUI</strong> address — almost always <code class="text-slate-400">http://127.0.0.1:8188</code>. It is <em>not</em> this app's port.</p>
      <div class="flex items-center gap-3">
        <button id="refreshConfig" type="button" class="text-[11px] text-slate-400 hover:text-slate-200 transition">↻ Re-check connection</button>
        <button id="resetComfyUrl" type="button" class="text-[11px] text-violet-400/80 hover:text-violet-300 transition">Reset to default</button>
      </div>
    </section>
  `;

  document.getElementById('saveGeminiKey')?.addEventListener('click', handleSaveGeminiKey);
  document.getElementById('clearGeminiKey')?.addEventListener('click', handleClearGeminiKey);
  document.getElementById('saveXaiKey')?.addEventListener('click', handleSaveXaiKey);
  document.getElementById('clearXaiKey')?.addEventListener('click', handleClearXaiKey);
  document.getElementById('saveComfyUrl')?.addEventListener('click', handleSaveComfyUrl);
  document.getElementById('refreshConfig')?.addEventListener('click', refresh);
  document.getElementById('resetComfyUrl')?.addEventListener('click', handleResetComfyUrl);
  document.getElementById('geminiModelInput')?.addEventListener('change', handleSaveGeminiModel);
  document.getElementById('xaiImageModelInput')?.addEventListener('change', handleSaveXaiImageModel);
  document.getElementById('xaiVideoModelInput')?.addEventListener('change', handleSaveXaiVideoModel);
}

async function handleSaveGeminiKey() {
  const input = document.getElementById('geminiKeyInput');
  const key = input?.value?.trim();
  if (!key) { showToast('Paste a key first', 'info'); return; }
  try {
    secrets = await saveSecret('gemini', key);
    showToast('Gemini key saved', 'success');
    if (input) input.value = '';
    await refresh();
  } catch (e) { showToast(e.message || 'Could not save key', 'error'); }
}

async function handleClearGeminiKey() {
  try {
    secrets = await saveSecret('gemini', '');
    showToast('Key removed', 'info');
    await refresh();
  } catch (e) { showToast(e.message || 'Could not remove key', 'error'); }
}

async function handleSaveXaiKey() {
  const input = document.getElementById('xaiKeyInput');
  const key = input?.value?.trim();
  if (!key) { showToast('Paste a key first', 'info'); return; }
  try {
    secrets = await saveSecret('xai', key);
    showToast('xAI key saved', 'success');
    if (input) input.value = '';
    await refresh();
  } catch (e) { showToast(e.message || 'Could not save key', 'error'); }
}

async function handleClearXaiKey() {
  try {
    secrets = await saveSecret('xai', '');
    showToast('xAI key removed', 'info');
    await refresh();
  } catch (e) { showToast(e.message || 'Could not remove key', 'error'); }
}

async function handleSaveGeminiModel(e) {
  const model = e.target.value.trim();
  if (!model) return;
  try {
    await saveSettings({ geminiModel: model });
    showToast('Model saved', 'success');
    await refresh();
  } catch (err) { showToast(err.message || 'Could not save', 'error'); }
}

async function handleSaveXaiImageModel(e) {
  const model = e.target.value.trim();
  if (!model) return;
  try {
    await saveSettings({ xaiImageModel: model });
    showToast('Grok image model saved', 'success');
    await refresh();
  } catch (err) { showToast(err.message || 'Could not save', 'error'); }
}

async function handleSaveXaiVideoModel(e) {
  const model = e.target.value.trim();
  if (!model) return;
  try {
    await saveSettings({ xaiVideoModel: model });
    showToast('Grok video model saved', 'success');
    await refresh();
  } catch (err) { showToast(err.message || 'Could not save', 'error'); }
}

async function handleSaveComfyUrl() {
  const url = document.getElementById('comfyUrlInput')?.value?.trim();
  if (!url) { showToast('Enter a URL', 'info'); return; }
  try {
    await saveSettings({ comfyUrl: url });
    showToast('ComfyUI URL saved', 'success');
    await refresh();
  } catch (e) { showToast(e.message || 'Could not save', 'error'); }
}

async function handleResetComfyUrl() {
  const input = document.getElementById('comfyUrlInput');
  if (input) input.value = 'http://127.0.0.1:8188';
  try {
    await saveSettings({ comfyUrl: 'http://127.0.0.1:8188' });
    showToast('ComfyUI URL reset to default', 'success');
    await refresh();
  } catch (e) { showToast(e.message || 'Could not reset', 'error'); }
}

async function refresh() {
  try {
    const config = await getConfig();
    setState({ config });
    secrets = await getSecrets();
    render();
    onConfigChange?.(config);
  } catch (e) {
    showToast('Could not reach the ImagineAI server', 'error');
  }
}

function escapeAttr(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML.replace(/"/g, '&quot;'); }
