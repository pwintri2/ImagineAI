import test from 'node:test';
import assert from 'node:assert/strict';

import { friendlyError } from '../web/services/friendly-error.js';
import { ENGINES } from '../web/services/image-gen.js';
import { VIDEO_MODELS } from '../web/services/video-gen.js';
import {
  isVideoModelAvailable,
  reconcileVideoModel,
} from '../web/services/video-model-routing.js';
import {
  editionFromSearch,
  videoMediaType,
  videoPlaybackCandidates,
} from '../web/services/video-playback.js';
import {
  historyVideoFileBase,
  historyVideoMp4Url,
  historyVideoSaveTarget,
} from '../web/ui/history-view.js';

function config(overrides = {}) {
  return {
    comfyReachable: true,
    models: { video: { wan22_14b: true } },
    geminiConfigured: false,
    xaiConfigured: false,
    atlasConfigured: false,
    soraConfigured: false,
    seedanceConfigured: false,
    modelslabConfigured: false,
    ...overrides,
  };
}

test('a configured Sora selection survives a background config refresh', () => {
  const current = config({ soraConfigured: true });
  assert.equal(isVideoModelAvailable('sora', current), true);
  assert.equal(reconcileVideoModel('sora', current), 'sora');
});

test('Gemini, Veo, and Director selections use their cloud-provider availability', () => {
  const current = config({ geminiConfigured: true });
  assert.equal(reconcileVideoModel('gemini', current), 'gemini');
  assert.equal(reconcileVideoModel('veo', current), 'veo');
  assert.equal(reconcileVideoModel('director', current), 'director');
});

test('Gemini and Veo are separate video model choices', () => {
  assert.equal(ENGINES.gemini.title, 'Gemini Image');
  assert.equal(VIDEO_MODELS.gemini.id, 'gemini');
  assert.equal(VIDEO_MODELS.gemini.title, 'Gemini');
  assert.equal(VIDEO_MODELS.veo.id, 'veo');
  assert.equal(VIDEO_MODELS.veo.title, 'Veo');
  assert.notEqual(VIDEO_MODELS.gemini.id, VIDEO_MODELS.veo.id);
});

test('macOS playback prefers the native MP4 before the WebM preview', () => {
  const video = {
    url: '/api/local-media?name=preview.webm',
    mp4Url: '/api/local-media?name=master.mp4',
  };
  assert.equal(editionFromSearch('?edition=macos'), 'macos');
  assert.deepEqual(videoPlaybackCandidates(video, 'macos'), [video.mp4Url, video.url]);
  assert.deepEqual(videoPlaybackCandidates(video, 'linux'), [video.url, video.mp4Url]);
  assert.equal(videoMediaType(video.mp4Url), 'video/mp4');
  assert.equal(videoMediaType(video.url), 'video/webm');
});

test('playback candidates de-duplicate a direct MP4 result', () => {
  const url = '/api/local-media?name=sora.mp4';
  assert.deepEqual(videoPlaybackCandidates({ url, mp4Url: url }, 'macos'), [url]);
});

test('history video save uses the MP4 master when available', () => {
  const video = {
    url: '/api/local-media?name=preview.webm',
    mp4Url: '/api/local-media?name=master.mp4',
  };
  assert.equal(historyVideoMp4Url(video), video.mp4Url);
  assert.equal(historyVideoMp4Url({ url: '/api/local-media?name=only.mp4' }), '/api/local-media?name=only.mp4');
  assert.equal(historyVideoMp4Url({ url: '/api/local-media?name=preview.webm' }), '');
  assert.deepEqual(historyVideoSaveTarget(video), {
    url: video.mp4Url,
    label: 'Save MP4',
    fallbackExt: '.mp4',
    convertMp4: false,
  });
  assert.deepEqual(historyVideoSaveTarget({ url: '/api/local-media?name=preview.webm' }), {
    url: '/api/local-media?name=preview.webm',
    label: 'Save MP4',
    fallbackExt: '.webm',
    convertMp4: true,
  });
});

test('history video save names files from the prompt', () => {
  assert.equal(
    historyVideoFileBase({ prompt: 'A Quiet Canal at Dawn!' }),
    'a-quiet-canal-at-dawn',
  );
  assert.equal(historyVideoFileBase({ prompt: '' }, 'fallback-video'), 'fallback-video');
});

test('Sora is a fallback when it is the only configured video engine', () => {
  const current = config({
    comfyReachable: false,
    models: { video: {} },
    soraConfigured: true,
  });
  assert.equal(reconcileVideoModel('wan22_14b', current), 'sora');
});

test('local Wan OOM retains the actionable VRAM guidance', () => {
  const message = friendlyError(new Error('CUDA out of memory'), {
    usesLocalGpu: true,
    providerLabel: 'Wan 2.2 14B',
  });
  assert.match(message, /Free VRAM/);
  assert.match(message, /Wan 2\.2 TI2V 5B/);
});

test('Sora OOM is identified as cloud-side and never recommends Wan', () => {
  const message = friendlyError(new Error('Sora video failed: out of memory'), {
    usesLocalGpu: false,
    providerLabel: 'Sora (OpenAI)',
  });
  assert.match(message, /Sora \(OpenAI\).*cloud-side/);
  assert.match(message, /did not use your computer's GPU/);
  assert.doesNotMatch(message, /Wan|Free VRAM|ComfyUI/);
});

test('image and video timeouts get request-specific guidance', () => {
  const image = friendlyError(new Error('request timed out'), { kind: 'image' });
  const video = friendlyError(new Error('request timed out'), { kind: 'video' });

  assert.match(image, /fewer images|another engine/);
  assert.doesNotMatch(image, /shorter video/);
  assert.match(video, /shorter video|another model/);
});
