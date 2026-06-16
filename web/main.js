import {
  getState, setState, loadPrefs, loadHistory, loadVideoHistory,
  saveHistoryEntry, saveVideoHistoryEntry,
} from './state.js';
import { getConfig } from './services/api.js';
import { generateImage } from './services/image-gen.js';
import { generateVideo } from './services/video-gen.js';
import * as PromptView from './ui/prompt-view.js';
import * as GalleryView from './ui/gallery-view.js';
import * as VideoPromptView from './ui/video-prompt-view.js';
import * as VideoGalleryView from './ui/video-gallery-view.js';
import * as HistoryView from './ui/history-view.js';
import * as SettingsView from './ui/settings-view.js';
import * as TabsView from './ui/tabs-view.js';
import { showToast } from './ui/toast-view.js';

document.addEventListener('DOMContentLoaded', async () => {
  loadPrefs();
  loadHistory();
  loadVideoHistory();

  PromptView.init();
  GalleryView.init();
  VideoPromptView.init();
  VideoGalleryView.init();
  TabsView.init(() => {});
  HistoryView.init();
  SettingsView.init(onConfigChange);

  // Delegate on the stable section wrappers: the prompt panels re-render their
  // innerHTML (replacing the buttons) when ComfyUI availability changes, which
  // would orphan a handler bound directly to the button.
  document.getElementById('image-section')?.addEventListener('click', (e) => {
    if (e.target.closest('#generateBtn')) handleGenerateImage();
  });
  document.getElementById('video-section')?.addEventListener('click', (e) => {
    if (e.target.closest('#videoGenerateBtn')) handleGenerateVideo();
  });
  // ⌘/Ctrl+Enter to generate from either prompt box
  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' || !(e.metaKey || e.ctrlKey)) return;
    if (TabsView.getActiveTab() === 'video') handleGenerateVideo();
    else handleGenerateImage();
  });

  await refreshConfig(true);
  // Keep checking in the background so a late-starting ComfyUI (it shares the
  // GPU and may be mid-model-load at launch) self-heals to "ready" without the
  // user touching anything.
  setInterval(() => refreshConfig(false), 7000);
});

let configInFlight = false;
let lastAvailKey = '';

function availabilityKey(config) {
  return JSON.stringify({
    reach: !!config.comfyReachable,
    img: config.models?.image || {},
    vid: config.models?.video || {},
    gem: !!config.geminiConfigured,
  });
}

async function refreshConfig(force) {
  if (configInFlight) return;
  configInFlight = true;
  try {
    const config = await getConfig();
    applyConfig(config, force);
  } catch (e) {
    setStatus(false, 'reconnecting…');
  } finally {
    configInFlight = false;
  }
}

// `force` re-renders even if nothing changed (used for explicit user actions);
// otherwise we only re-render the prompt panels when availability actually
// changes, so a background poll never wipes text you're typing.
function applyConfig(config, force) {
  setState({ config });
  reconcileEngine(config);
  updateStatus(config);
  const key = availabilityKey(config);
  if (force || key !== lastAvailKey) {
    lastAvailKey = key;
    PromptView.captureDraft();
    VideoPromptView.captureDraft();
    PromptView.render();
    VideoPromptView.render();
  }
}

// Called by the Settings panel after the user saves/recHecks.
function onConfigChange(config) {
  applyConfig(config, true);
}

// Pick a usable default engine/model if the saved one is unavailable.
function reconcileEngine(config) {
  const s = getState();
  const localImg = !!(config.comfyReachable && config.models?.image?.zimage_turbo);
  const gemini = !!config.geminiConfigured;
  let engine = s.imageEngine;
  if (engine === 'local' && !localImg && gemini) engine = 'gemini';
  if (engine === 'gemini' && !gemini && localImg) engine = 'local';
  if (engine !== s.imageEngine) setState({ imageEngine: engine });

  let vModel = s.videoModel;
  const v = config.models?.video || {};
  if (!v[vModel]) {
    if (v.wan22_14b) vModel = 'wan22_14b';
    else if (v.wan22_ti2v_5b) vModel = 'wan22_ti2v_5b';
    else if (v.wan21_1_3b) vModel = 'wan21_1_3b';
    else vModel = '';
  }
  if (vModel !== s.videoModel) setState({ videoModel: vModel });
}

function updateStatus(config) {
  const localImg = !!(config.comfyReachable && config.models?.image?.zimage_turbo);
  if (localImg) setStatus(true, 'ComfyUI ready');
  else if (config.geminiConfigured) setStatus(true, 'Gemini ready');
  else if (config.comfyReachable) setStatus(true, 'ComfyUI (no Z-Image)');
  else setStatus(false, 'ComfyUI offline');
}

function setStatus(ok, label) {
  const wrap = document.getElementById('engineStatus');
  const dot = document.getElementById('statusDot');
  const text = document.getElementById('statusLabel');
  if (wrap) wrap.classList.remove('hidden');
  if (dot) dot.className = `w-2 h-2 rounded-full ${ok ? 'bg-emerald-400' : 'bg-red-400'}`;
  if (text) text.textContent = label;
}

async function handleGenerateImage() {
  const prompt = PromptView.getPrompt();
  if (!prompt) { showToast('Describe what you want to see', 'info'); PromptView.focusPrompt(); return; }

  const s = getState();
  if (s.isGenerating) return;
  const engine = s.imageEngine;
  const localImg = !!(s.config.comfyReachable && s.config.models?.image?.zimage_turbo);
  if (engine === 'local' && !localImg) { showToast('ComfyUI / Z-Image not available. Add a Gemini key or start ComfyUI.', 'error'); return; }
  if (engine === 'gemini' && !s.config.geminiConfigured) { showToast('No Gemini key saved — open Settings to add one.', 'error'); return; }

  setState({ isGenerating: true });
  PromptView.setGenerating(true);
  const count = engine === 'gemini' ? Math.min(s.imageCount, 4) : s.imageCount;
  GalleryView.renderLoading(count, { label: engine === 'gemini' ? 'Asking Gemini…' : 'Rendering on your GPU…' });
  const started = Date.now();

  try {
    const { results, modelTitle } = await generateImage(
      { prompt, engine, aspect: s.aspectRatio, count, steps: s.steps },
      (job) => GalleryView.updateStatus(progressLabel(job, started, engine === 'gemini' ? 'Gemini is painting' : 'Z-Image rendering')),
    );
    if (!results.length) throw new Error('No images were returned.');
    GalleryView.renderResults(results);
    showToast('Image created!', 'success');
    saveHistoryEntry({ prompt, modelTitle, images: results, createdAt: Date.now() });
  } catch (err) {
    console.error('Image generation failed:', err);
    GalleryView.renderError(friendlyError(err));
    showToast(friendlyError(err), 'error');
  } finally {
    setState({ isGenerating: false });
    PromptView.setGenerating(false);
  }
}

async function handleGenerateVideo() {
  const prompt = VideoPromptView.getPrompt();
  if (!prompt) { showToast('Describe the scene you want', 'info'); VideoPromptView.focusPrompt(); return; }

  const s = getState();
  if (s.isGeneratingVideo) return;
  const model = s.videoModel;
  const available = !!(s.config.comfyReachable && s.config.models?.video?.[model]);
  if (!available) { showToast('That video model is not available in ComfyUI.', 'error'); return; }
  const startImage = VideoPromptView.getStartImage();
  if (startImage && model !== 'wan22_ti2v_5b') {
    showToast('Start images work with Wan 2.2 TI2V 5B. Select that model first.', 'info');
    return;
  }

  setState({ isGeneratingVideo: true });
  VideoPromptView.setGenerating(true);
  VideoGalleryView.renderLoading({ modelTitle: videoModelTitle(model) });
  const started = Date.now();

  try {
    const { results, modelTitle } = await generateVideo(
      { prompt, model, aspect: s.videoAspect, seconds: s.videoSeconds, startImage },
      (job) => VideoGalleryView.updateStatus(progressLabel(job, started, 'Wan is generating frames')),
    );
    if (!results.length) throw new Error('No video was returned.');
    VideoGalleryView.renderResults(results, { modelTitle });
    showToast('Video created!', 'success');
    saveVideoHistoryEntry({ prompt, modelTitle, videos: results, createdAt: Date.now() });
  } catch (err) {
    console.error('Video generation failed:', err);
    VideoGalleryView.renderError(friendlyError(err));
    showToast(friendlyError(err), 'error');
  } finally {
    setState({ isGeneratingVideo: false });
    VideoPromptView.setGenerating(false);
  }
}

function videoModelTitle(model) {
  if (model === 'wan22_ti2v_5b') return 'Wan 2.2 TI2V 5B';
  if (model === 'wan22_14b') return 'Wan 2.2 14B';
  return 'Wan 2.1 1.3B';
}

function progressLabel(job, started, base) {
  const secs = Math.max(0, Math.round((Date.now() - started) / 1000));
  const state = job.status === 'queued' ? 'queued' : 'running';
  return `${base}… ${secs}s (${state})`;
}

function friendlyError(err) {
  const msg = err?.message || String(err);
  if (/timed out/i.test(msg)) return 'Generation timed out. Try a shorter video or fewer steps.';
  if (/not reachable|offline|ComfyUI is not/i.test(msg)) return 'ComfyUI is not reachable. Start it or check the URL in Settings.';
  return msg.length > 240 ? msg.slice(0, 240) + '…' : msg;
}
