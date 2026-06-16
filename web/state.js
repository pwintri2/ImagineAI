// Central app state + localStorage-backed history.

const IMAGE_HISTORY_KEY = 'imagineai_image_history';
const VIDEO_HISTORY_KEY = 'imagineai_video_history';
const PREFS_KEY = 'imagineai_prefs';

const defaultPrefs = {
  imageEngine: 'local',   // 'local' | 'gemini'
  aspectRatio: 'square',
  imageCount: 1,
  steps: 8,
  videoModel: 'wan22_14b',
  videoAspect: 'wide',
  videoSeconds: 2,
};

const state = {
  // config from the backend (/api/config)
  config: {
    comfyReachable: false,
    models: { image: {}, video: {} },
    geminiConfigured: false,
    geminiModel: '',
    comfyUrl: '',
  },
  // user preferences (persisted)
  ...structuredClone(defaultPrefs),

  isGenerating: false,
  isGeneratingVideo: false,
  history: [],
  videoHistory: [],
};

const listeners = new Set();

export function getState() { return state; }

export function setState(updates) {
  Object.assign(state, updates);
  persistPrefs();
  listeners.forEach((fn) => fn(state));
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function persistPrefs() {
  const prefs = {};
  for (const key of Object.keys(defaultPrefs)) prefs[key] = state[key];
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch (e) {
    console.warn('Could not persist prefs:', e);
  }
}

export function loadPrefs() {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) Object.assign(state, defaultPrefs, JSON.parse(raw));
  } catch (e) {
    console.warn('Could not load prefs:', e);
  }
}

function readHistory(key) {
  try {
    const raw = localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function loadHistory() { state.history = readHistory(IMAGE_HISTORY_KEY); }
export function loadVideoHistory() { state.videoHistory = readHistory(VIDEO_HISTORY_KEY); }

export function saveHistoryEntry(entry) {
  state.history.unshift(entry);
  if (state.history.length > 50) state.history = state.history.slice(0, 50);
  try { localStorage.setItem(IMAGE_HISTORY_KEY, JSON.stringify(state.history)); } catch (e) { console.warn(e); }
  listeners.forEach((fn) => fn(state));
}

export function saveVideoHistoryEntry(entry) {
  state.videoHistory.unshift(entry);
  if (state.videoHistory.length > 30) state.videoHistory = state.videoHistory.slice(0, 30);
  try { localStorage.setItem(VIDEO_HISTORY_KEY, JSON.stringify(state.videoHistory)); } catch (e) { console.warn(e); }
  listeners.forEach((fn) => fn(state));
}

export function clearHistory() {
  state.history = [];
  try { localStorage.removeItem(IMAGE_HISTORY_KEY); } catch (e) { console.warn(e); }
  listeners.forEach((fn) => fn(state));
}

export function clearVideoHistory() {
  state.videoHistory = [];
  try { localStorage.removeItem(VIDEO_HISTORY_KEY); } catch (e) { console.warn(e); }
  listeners.forEach((fn) => fn(state));
}
