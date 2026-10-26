import { getState, setState } from '../state.js';
import { getConfig, getSecrets, saveSecret, saveSettings } from '../services/api.js';
import { SORA_RETIREMENT_MESSAGE, seedanceProviderLabel, seedanceService } from '../services/video-model-routing.js';
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
  const byteplus = secrets.providers?.byteplus || {};
  const otherProviders = getOtherProviders();
  const otherProvidersHtml = renderOtherProviders(otherProviders);

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
          <span class="text-slate-400">${dot(c.models?.image?.flux1_schnell || c.models?.image?.flux1_schnell_fp8)} FLUX.1 Schnell ${c.models?.image?.flux1_schnell_backend === 'gguf' ? 'Q4' : 'FP8'}</span>
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
        <div class="flex items-center justify-between">
          <span class="text-slate-400">${dot(c.atlasConfigured)} Atlas</span>
          <span class="text-slate-500">${c.atlasConfigured ? `key saved${c.atlasProvider ? ` (${escapeHtml(c.atlasProvider)})` : ''}` : 'no key'}</span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-slate-400">${dot(c.seedanceConfigured)} Seedance · ${seedanceProviderLabel(c)}</span>
          <span class="text-slate-500">${c.seedanceConfigured ? `key saved${c.seedanceProvider ? ` (${escapeHtml(c.seedanceProvider)})` : ''}` : 'no key'}</span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-slate-400">${dot(c.modelslabConfigured)} ModelsLab</span>
          <span class="text-slate-500">${c.modelslabConfigured ? `key saved${c.modelslabProvider ? ` (${escapeHtml(c.modelslabProvider)})` : ''}` : 'no key'}</span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-slate-400">${dot(c.stabilityConfigured)} Stability</span>
          <span class="text-slate-500">${c.stabilityConfigured ? `key saved${c.stabilityProvider ? ` (${escapeHtml(c.stabilityProvider)})` : ''}` : 'no key'}</span>
        </div>
      </div>
    </section>

    <section class="space-y-3">
      <h3 class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Gemini API key (cloud images + Gemini Omni video)</h3>
      <p class="text-[11px] text-slate-500">Stored locally on this machine (data/secrets.json, chmod 600). One key powers the Image tab's Gemini engine and the Gemini and Gemini Omni choices on the Video tab.</p>
      <div class="flex gap-2">
        <input id="geminiKeyInput" type="password" autocomplete="off" placeholder="${gem.configured ? 'Saved ' + escapeAttr(gem.hint || '') : 'AIza…'}"
          class="flex-1 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
        <button id="saveGeminiKey" type="button" class="px-3 py-2 rounded-xl bg-violet-500/20 hover:bg-violet-500/30 border border-violet-500/30 text-violet-300 text-xs font-medium transition">Save</button>
      </div>
      ${gem.configured ? `<button id="clearGeminiKey" type="button" class="text-[11px] text-red-400/70 hover:text-red-400 transition">Remove saved key</button>` : ''}
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <div class="space-y-1.5">
          <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Gemini Image model</label>
          <input id="geminiModelInput" type="text" value="${escapeAttr(c.geminiModel || '')}" placeholder="gemini-nano-banana-2.1"
            class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
        </div>
        <div class="space-y-1.5">
          <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Google video model</label>
          <input id="veoVideoModelInput" type="text" value="${escapeAttr(c.veoVideoModel || '')}" placeholder="gemini-omni-1.1-flash"
            class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
        </div>
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
          <input id="xaiImageModelInput" type="text" value="${escapeAttr(c.xaiImageModel || '')}" placeholder="grok-imagine-image-2.0"
            class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
        </div>
        <div class="space-y-1.5">
          <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Grok video model</label>
          <input id="xaiVideoModelInput" type="text" value="${escapeAttr(c.xaiVideoModel || '')}" placeholder="grok-imagine-video-1.5"
            class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
        </div>
      </div>
      <a href="https://console.x.ai/team/60586ab6-ba7f-4fcc-a2c8-1425021c6f1b/api-keys" target="_blank" rel="noopener" class="text-[11px] text-violet-400/80 hover:text-violet-300 transition inline-block">Open xAI API keys ↗</a>
    </section>

    <section class="space-y-3">
      <h3 class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Seedance video provider</h3>
      <label for="seedanceServiceInput" class="block text-[11px] text-slate-400">Use the provider that issued your API key</label>
      <select id="seedanceServiceInput" class="w-full rounded-xl border border-white/10 bg-slate-900 px-3 py-2 text-sm text-slate-100">
        <option value="seevio" ${seedanceService(c) === 'seevio' ? 'selected' : ''}>Seevio (Seedance2.ai)</option>
        <option value="byteplus" ${seedanceService(c) === 'byteplus' ? 'selected' : ''}>BytePlus ModelArk</option>
      </select>
      <p class="text-[11px] text-slate-500">Video generation uses the selected provider's key and model. Seedance Still always uses Seevio.</p>
      <div class="space-y-1.5">
        <label for="byteplusKeyInput" class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">BytePlus ModelArk API key</label>
        <div class="flex gap-2">
          <input id="byteplusKeyInput" type="password" autocomplete="off" placeholder="${byteplus.configured ? 'Saved ' + escapeAttr(byteplus.hint || '') : 'Paste your BytePlus ModelArk key'}"
            class="flex-1 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
          <button id="saveByteplusKey" type="button" class="px-3 py-2 rounded-xl bg-violet-500/20 hover:bg-violet-500/30 border border-violet-500/30 text-violet-300 text-xs font-medium transition">Save</button>
        </div>
        ${byteplus.configured ? '<button id="clearByteplusKey" type="button" class="text-[11px] text-red-400/70 hover:text-red-400 transition">Remove saved BytePlus key</button>' : ''}
        <a href="https://ai.byteplus.com/ark/region:ap-southeast-1/apiKey" target="_blank" rel="noopener" class="text-[11px] text-violet-400/80 hover:text-violet-300 transition inline-block">Open BytePlus ModelArk API keys ↗</a>
      </div>
      <div class="space-y-1.5">
        <label for="byteplusVideoModelInput" class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">BytePlus video model</label>
        <input id="byteplusVideoModelInput" type="text" value="${escapeAttr(c.byteplusVideoModel || '')}" placeholder="dreamina-seedance-2-5-260628"
          class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
      </div>
      <div class="space-y-1.5">
        <label for="seedanceVideoModelInput" class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Seevio video model</label>
        <input id="seedanceVideoModelInput" type="text" value="${escapeAttr(c.seedanceVideoModel || '')}" placeholder="seedance-2-5"
          class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
        <p class="text-[11px] text-slate-500">${c.seevioConfigured ? 'Seevio key saved.' : 'Add a Seevio key under Other API keys as seedance.'} This model also supplies Seedance Still.</p>
      </div>
    </section>

    <section class="space-y-3">
      <div class="flex items-center justify-between gap-3">
        <h3 class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Other API keys</h3>
        <span class="text-[11px] text-slate-500">${otherProviders.length ? `${otherProviders.length} saved` : 'none saved'}</span>
      </div>
      <p class="text-[11px] text-slate-500">Stored locally for supported providers and future helper scripts. Use <code class="text-slate-400">atlas</code> for Atlas Cloud; use <code class="text-slate-400">seedance</code> for Seedance2.ai; use <code class="text-slate-400">sdxl</code>, <code class="text-slate-400">modelslab</code>, <code class="text-slate-400">stable-diffusion-api</code>, <code class="text-slate-400">free-api</code>, <code class="text-slate-400">vrije-api</code>, or <code class="text-slate-400">wan2.6-t2v</code> for ModelsLab / Stable Diffusion API; use <code class="text-slate-400">stability</code> for Stability AI; use <code class="text-slate-400">elevenlabs</code> for ElevenLabs soundtracks.</p>
      <div class="space-y-2">
        <input id="customProviderInput" type="text" autocomplete="off" placeholder="Provider name, e.g. seedance"
          class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
        <div class="flex gap-2">
          <input id="customKeyInput" type="password" autocomplete="off" placeholder="API key"
            class="flex-1 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
          <button id="saveCustomKey" type="button" class="px-3 py-2 rounded-xl bg-white/10 hover:bg-white/15 border border-white/10 text-slate-200 text-xs font-medium transition">Save</button>
        </div>
      </div>
      ${c.modelslabConfigured ? `
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <div class="space-y-1.5">
            <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">ModelsLab image model</label>
            <input id="modelslabImageModelInput" type="text" value="${escapeAttr(c.modelslabImageModel || '')}" placeholder="sdxl"
              class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
          </div>
          <div class="space-y-1.5">
            <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">ModelsLab video model</label>
            <input id="modelslabVideoModelInput" type="text" value="${escapeAttr(c.modelslabVideoModel || '')}" placeholder="wan2.2"
              class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
          </div>
        </div>
      ` : ''}
      ${c.atlasConfigured ? `
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <div class="space-y-1.5">
            <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Atlas image model</label>
            <input id="atlasImageModelInput" type="text" value="${escapeAttr(c.atlasImageModel || '')}" placeholder="bytedance/seedream-v5.0-pro/text-to-image"
              class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
          </div>
          <div class="space-y-1.5">
            <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Atlas video model</label>
            <input id="atlasVideoModelInput" type="text" value="${escapeAttr(c.atlasVideoModel || '')}" placeholder="alibaba/wan-3.0/text-to-video"
              class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
          </div>
        </div>
      ` : ''}
      ${c.soraConfigured ? `
        <div class="space-y-1.5">
          <p class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Sora · retired</p>
          <p class="text-[11px] text-slate-500">${escapeHtml(SORA_RETIREMENT_MESSAGE)} Your saved key does not enable video generation.</p>
        </div>
      ` : ''}
      ${c.stabilityConfigured ? `
        <div class="space-y-1.5">
          <label class="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Stability image model</label>
          <input id="stabilityImageModelInput" type="text" value="${escapeAttr(c.stabilityImageModel || '')}" placeholder="core"
            class="w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-violet-500/50 focus:ring-1 focus:ring-violet-500/30" />
          <p class="text-[10px] text-slate-600">Use <code class="text-slate-400">core</code>, <code class="text-slate-400">sd3</code>, or <code class="text-slate-400">ultra</code>.</p>
        </div>
      ` : ''}
      <div class="space-y-2">${otherProvidersHtml}</div>
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
  document.getElementById('saveByteplusKey')?.addEventListener('click', handleSaveByteplusKey);
  document.getElementById('clearByteplusKey')?.addEventListener('click', handleClearByteplusKey);
  document.getElementById('seedanceServiceInput')?.addEventListener('change', handleSaveSeedanceService);
  document.getElementById('byteplusVideoModelInput')?.addEventListener('change', handleSaveByteplusVideoModel);
  document.getElementById('saveCustomKey')?.addEventListener('click', handleSaveCustomKey);
  document.querySelectorAll('[data-clear-secret]').forEach((button) => {
    button.addEventListener('click', handleClearCustomKey);
  });
  document.getElementById('saveComfyUrl')?.addEventListener('click', handleSaveComfyUrl);
  document.getElementById('refreshConfig')?.addEventListener('click', refresh);
  document.getElementById('resetComfyUrl')?.addEventListener('click', handleResetComfyUrl);
  document.getElementById('geminiModelInput')?.addEventListener('change', handleSaveGeminiModel);
  document.getElementById('xaiImageModelInput')?.addEventListener('change', handleSaveXaiImageModel);
  document.getElementById('xaiVideoModelInput')?.addEventListener('change', handleSaveXaiVideoModel);
  document.getElementById('atlasImageModelInput')?.addEventListener('change', handleSaveAtlasImageModel);
  document.getElementById('atlasVideoModelInput')?.addEventListener('change', handleSaveAtlasVideoModel);
  document.getElementById('seedanceVideoModelInput')?.addEventListener('change', handleSaveSeedanceVideoModel);
  document.getElementById('veoVideoModelInput')?.addEventListener('change', handleSaveVeoVideoModel);
  document.getElementById('stabilityImageModelInput')?.addEventListener('change', handleSaveStabilityImageModel);
  document.getElementById('modelslabImageModelInput')?.addEventListener('change', handleSaveModelslabImageModel);
  document.getElementById('modelslabVideoModelInput')?.addEventListener('change', handleSaveModelslabVideoModel);
}

function getOtherProviders() {
  if (Array.isArray(secrets.customProviders)) return secrets.customProviders.filter((item) => item.provider !== 'byteplus');
  return Object.entries(secrets.providers || {})
    .filter(([provider]) => !['gemini', 'xai', 'byteplus'].includes(provider))
    .map(([provider, meta]) => ({ provider, ...(meta || {}) }));
}

function renderOtherProviders(providers) {
  if (!providers.length) {
    return '<p class="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-[11px] text-slate-500">No extra API keys saved yet.</p>';
  }
  return providers.map((item) => {
    const provider = String(item.provider || '');
    const hint = item.hint ? `Saved ${escapeHtml(item.hint)}` : 'Saved';
    return `
      <div class="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
        <div class="min-w-0">
          <p class="truncate text-sm text-slate-200">${escapeHtml(provider)}</p>
          <p class="text-[11px] text-slate-500">${hint}</p>
        </div>
        <button type="button" data-clear-secret="${escapeAttr(provider)}" class="shrink-0 text-[11px] text-red-400/70 hover:text-red-400 transition">Remove</button>
      </div>
    `;
  }).join('');
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

async function handleSaveByteplusKey() {
  const input = document.getElementById('byteplusKeyInput');
  const key = input?.value?.trim();
  if (!key) { showToast('Paste your BytePlus ModelArk key first', 'info'); return; }
  try {
    secrets = await saveSecret('byteplus', key);
    if (input) input.value = '';
    showToast('BytePlus ModelArk key saved', 'success');
    await refresh();
  } catch (e) { showToast(e.message || 'Could not save BytePlus key', 'error'); }
}

async function handleClearByteplusKey() {
  try {
    secrets = await saveSecret('byteplus', '');
    showToast('BytePlus key removed', 'info');
    await refresh();
  } catch (e) { showToast(e.message || 'Could not remove BytePlus key', 'error'); }
}

async function handleSaveSeedanceService(e) {
  try {
    await saveSettings({ seedanceService: e.target.value });
    showToast('Seedance provider saved', 'success');
    await refresh();
  } catch (err) {
    showToast(err.message || 'Could not save provider', 'error');
    render();
  }
}

async function handleSaveByteplusVideoModel(e) {
  const model = e.target.value.trim();
  if (!model) return;
  try {
    await saveSettings({ byteplusVideoModel: model });
    showToast('BytePlus video model saved', 'success');
    await refresh();
  } catch (err) { showToast(err.message || 'Could not save model', 'error'); }
}

async function handleSaveCustomKey() {
  const providerInput = document.getElementById('customProviderInput');
  const keyInput = document.getElementById('customKeyInput');
  const provider = providerInput?.value?.trim();
  const key = keyInput?.value?.trim();
  if (!provider) { showToast('Enter a provider name first', 'info'); return; }
  if (!key) { showToast('Paste a key first', 'info'); return; }
  if (['gemini', 'xai', 'byteplus'].includes(provider.toLowerCase())) {
    showToast('Use the dedicated field above for that provider', 'info');
    return;
  }
  try {
    secrets = await saveSecret(provider, key);
    showToast('API key saved', 'success');
    if (providerInput) providerInput.value = '';
    if (keyInput) keyInput.value = '';
    await refresh();
  } catch (e) { showToast(e.message || 'Could not save key', 'error'); }
}

async function handleClearCustomKey(e) {
  const provider = e.currentTarget?.dataset?.clearSecret;
  if (!provider) return;
  try {
    secrets = await saveSecret(provider, '');
    showToast('API key removed', 'info');
    await refresh();
  } catch (err) { showToast(err.message || 'Could not remove key', 'error'); }
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

async function handleSaveAtlasImageModel(e) {
  const model = e.target.value.trim();
  if (!model) return;
  try {
    await saveSettings({ atlasImageModel: model });
    showToast('Atlas image model saved', 'success');
    await refresh();
  } catch (err) { showToast(err.message || 'Could not save', 'error'); }
}

async function handleSaveAtlasVideoModel(e) {
  const model = e.target.value.trim();
  if (!model) return;
  try {
    await saveSettings({ atlasVideoModel: model });
    showToast('Atlas video model saved', 'success');
    await refresh();
  } catch (err) { showToast(err.message || 'Could not save', 'error'); }
}

async function handleSaveSeedanceVideoModel(e) {
  const model = e.target.value.trim();
  if (!model) return;
  try {
    await saveSettings({ seedanceVideoModel: model });
    showToast('Seevio video model saved', 'success');
    await refresh();
  } catch (err) { showToast(err.message || 'Could not save', 'error'); }
}

async function handleSaveVeoVideoModel(e) {
  const model = e.target.value.trim();
  if (!model) return;
  try {
    await saveSettings({ veoVideoModel: model });
    showToast('Google video model saved', 'success');
    await refresh();
  } catch (err) { showToast(err.message || 'Could not save', 'error'); }
}

async function handleSaveStabilityImageModel(e) {
  const model = e.target.value.trim();
  if (!model) return;
  try {
    await saveSettings({ stabilityImageModel: model });
    showToast('SDXL/Stability model saved', 'success');
    await refresh();
  } catch (err) { showToast(err.message || 'Could not save', 'error'); }
}

async function handleSaveModelslabImageModel(e) {
  const model = e.target.value.trim();
  if (!model) return;
  try {
    await saveSettings({ modelslabImageModel: model });
    showToast('ModelsLab image model saved', 'success');
    await refresh();
  } catch (err) { showToast(err.message || 'Could not save', 'error'); }
}

async function handleSaveModelslabVideoModel(e) {
  const model = e.target.value.trim();
  if (!model) return;
  try {
    await saveSettings({ modelslabVideoModel: model });
    showToast('ModelsLab video model saved', 'success');
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
function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : String(s); return d.innerHTML; }
