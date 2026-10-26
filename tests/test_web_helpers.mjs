import test from 'node:test';
import assert from 'node:assert/strict';

import { friendlyError } from '../web/services/friendly-error.js';
import { ENGINES, isSeedanceStillAvailable } from '../web/services/image-gen.js';
import { VIDEO_MODELS, generateVideo } from '../web/services/video-gen.js';
import {
  isVideoModelAvailable,
  reconcileVideoModel,
  seedanceService,
  seedanceVideoTitle,
  supportsVideoStartImage,
  videoAspectForModel,
  videoDurationLimits,
  videoSecondsForModel,
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
import { videoMp4SaveTarget } from '../web/ui/video-gallery-view.js';
import { supportsNegativePrompt, supportsSeed } from '../web/ui/video-prompt-view.js';

function config(overrides = {}) {
  return {
    comfyReachable: true,
    models: { video: { wan22_14b: true } },
    geminiConfigured: false,
    xaiConfigured: false,
    atlasConfigured: false,
    soraConfigured: false,
    seedanceConfigured: false,
    seedanceService: 'seevio',
    seevioConfigured: false,
    byteplusConfigured: false,
    modelslabConfigured: false,
    ...overrides,
  };
}

test('a saved Sora key never makes the retired API available', () => {
  const current = config({ soraConfigured: true });
  assert.equal(isVideoModelAvailable('sora', current), false);
  assert.equal(reconcileVideoModel('sora', current), 'wan22_14b');
  assert.equal(isVideoModelAvailable('sora', config({
    soraConfigured: true,
    soraAvailable: true,
    soraRetired: false,
  })), false);
});

test('Gemini, Gemini Omni, and Director selections use their cloud-provider availability', () => {
  const current = config({ geminiConfigured: true });
  assert.equal(reconcileVideoModel('gemini', current), 'gemini');
  assert.equal(reconcileVideoModel('veo', current), 'veo');
  assert.equal(reconcileVideoModel('director', current), 'director');
});

test('Gemini and Gemini Omni remain separate saved video model choices', () => {
  assert.equal(ENGINES.gemini.title, 'Gemini Image');
  assert.equal(VIDEO_MODELS.gemini.id, 'gemini');
  assert.equal(VIDEO_MODELS.gemini.title, 'Gemini');
  assert.equal(VIDEO_MODELS.veo.id, 'veo');
  assert.equal(VIDEO_MODELS.veo.title, 'Gemini Omni');
  assert.notEqual(VIDEO_MODELS.gemini.id, VIDEO_MODELS.veo.id);
});

test('current cloud models expose only supported advanced fields', () => {
  assert.equal(supportsSeed('gemini', {}), false);
  assert.equal(supportsSeed('veo', { veoVideoModel: 'gemini-omni-1.1-flash' }), false);
  assert.equal(supportsNegativePrompt('veo', {}), true);
  assert.equal(supportsSeed('seedance', {}), false);
  assert.equal(supportsNegativePrompt('atlas', {}), false);
  assert.equal(supportsNegativePrompt('atlas', { atlasVideoModel: 'alibaba/wan-3.0-prime/text-to-video' }), false);
  assert.equal(supportsSeed('atlas', {}), true);
  assert.equal(supportsNegativePrompt('atlas', { atlasVideoModel: 'alibaba/wan-2.7/text-to-video' }), true);
  assert.equal(supportsSeed('seedance', { seedanceVideoModel: 'seedance-2-0' }), true);
  assert.equal(supportsSeed('seedance', { seedanceService: 'byteplus', seedanceVideoModel: 'seedance-2-0' }), false);
  assert.equal(supportsSeed('veo', { veoVideoModel: 'veo-3.1-generate-001' }), true);
});

test('Seedance video provider availability never enables Seevio stills through a BytePlus key', () => {
  const byteplus = config({
    seedanceService: 'byteplus',
    seedanceConfigured: true,
    byteplusConfigured: true,
    seevioConfigured: false,
  });
  assert.equal(isVideoModelAvailable('seedance', byteplus), true);
  assert.equal(isSeedanceStillAvailable(byteplus), false);
  const seevioOnly = config({
    seedanceService: 'byteplus',
    seedanceConfigured: false,
    byteplusConfigured: false,
    seevioConfigured: true,
  });
  assert.equal(isVideoModelAvailable('seedance', seevioOnly), false);
  assert.equal(isSeedanceStillAvailable(seevioOnly), true);
});

test('Seedance provider labels and start-frame support follow the selected service', () => {
  assert.equal(seedanceService({}), 'seevio');
  assert.equal(seedanceVideoTitle({}), 'Seedance · Seevio');
  assert.equal(seedanceVideoTitle({ seedanceService: 'byteplus' }), 'Seedance · BytePlus ModelArk');
  assert.equal(supportsVideoStartImage('seedance', { seedanceService: 'byteplus' }), true);
  assert.equal(supportsVideoStartImage('seedance', { seedanceService: 'seevio' }), false);
  assert.equal(supportsVideoStartImage('seedance', {}), false);
  assert.equal(supportsVideoStartImage('atlas', {}), true);
});

test('Seedance requests retain the start image and defer provider model selection to saved settings', async (t) => {
  let submitted;
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    if (url === '/api/generate/video') {
      submitted = JSON.parse(options.body);
      return Response.json({ jobId: 'seedance-test' });
    }
    assert.equal(url, '/api/jobs/seedance-test');
    return Response.json({ status: 'done', results: [], meta: { modelTitle: 'Seedance · BytePlus ModelArk' } });
  });
  const result = await generateVideo({
    model: 'seedance',
    prompt: 'A paper boat',
    aspect: 'wide',
    seconds: 5,
    startImage: { dataUrl: 'data:image/png;base64,test', name: 'start.png' },
  });
  assert.equal(submitted.startImage, 'data:image/png;base64,test');
  assert.equal(submitted.model, 'seedance');
  assert.equal(Object.hasOwn(submitted, 'seedanceVideoModel'), false);
  assert.equal(Object.hasOwn(submitted, 'byteplusVideoModel'), false);
  assert.equal(Object.hasOwn(submitted, 'seedanceService'), false);
  assert.equal(result.modelTitle, 'Seedance · BytePlus ModelArk');
});

test('Gemini Omni accepts landscape or portrait video without changing other providers', () => {
  assert.equal(videoAspectForModel('veo', 'square', {}), 'wide');
  assert.equal(videoAspectForModel('gemini', 'portrait', {}), 'tall');
  assert.equal(videoAspectForModel('veo', 'tall', {}), 'tall');
  assert.equal(videoAspectForModel('atlas', 'square', {}), 'square');
  assert.equal(videoAspectForModel('veo', 'square', { veoVideoModel: 'veo-custom' }), 'square');
});

test('Seedance duration starts at four seconds and permits native thirty-second clips', () => {
  assert.deepEqual(videoDurationLimits('seedance'), { min: 4, max: 30, step: 1 });
  assert.equal(videoSecondsForModel('seedance', 3), 4);
  assert.equal(videoSecondsForModel('seedance', 4), 4);
  assert.equal(videoSecondsForModel('seedance', 5), 5);
  assert.equal(videoSecondsForModel('seedance', 30), 30);
  assert.equal(videoSecondsForModel('seedance', 31), 30);
  assert.equal(videoSecondsForModel('seedance', ''), 4);
});

test('Google durations match even totals from four-second through sixty-second clips', () => {
  for (const model of ['gemini', 'veo']) {
    assert.deepEqual(videoDurationLimits(model), { min: 4, max: 60, step: 2 });
    assert.equal(videoSecondsForModel(model, 1), 4);
    assert.equal(videoSecondsForModel(model, 4), 4);
    assert.equal(videoSecondsForModel(model, 5), 4);
    assert.equal(videoSecondsForModel(model, 6), 6);
    assert.equal(videoSecondsForModel(model, 9), 8);
    assert.equal(videoSecondsForModel(model, 10), 10);
    assert.equal(videoSecondsForModel(model, '59'), 58);
    assert.equal(videoSecondsForModel(model, 60), 60);
    assert.equal(videoSecondsForModel(model, 61), 60);
    assert.equal(videoSecondsForModel(model, undefined), 4);
  }
});

test('other video engines keep their existing duration ranges and one-second increments', () => {
  for (const [model, max] of [['atlas', 60], ['xai', 60], ['director', 180], ['wan22_14b', 120], ['stable-diffusion-api', 120]]) {
    assert.deepEqual(videoDurationLimits(model), { min: 1, max, step: 1 });
    assert.equal(videoSecondsForModel(model, 1), 1);
    assert.equal(videoSecondsForModel(model, 5), 5);
    assert.equal(videoSecondsForModel(model, max), max);
    assert.equal(videoSecondsForModel(model, max + 1), max);
  }
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
  assert.equal(historyVideoMp4Url({ mp4Url: '/api/local-media?name=mislabelled.webm' }), '');
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
  assert.deepEqual(historyVideoSaveTarget({
    mp4Url: '/api/local-media?name=mislabelled.webm',
    url: '/api/local-media?name=preview.webm',
  }), {
    url: '/api/local-media?name=mislabelled.webm',
    label: 'Save MP4',
    fallbackExt: '.webm',
    convertMp4: true,
  });
  assert.deepEqual(historyVideoSaveTarget({ url: '/api/local-media?name=legacy.mov' }), {
    url: '/api/local-media?name=legacy.mov',
    label: 'Save MP4',
    fallbackExt: '.mov',
    convertMp4: true,
  });
  assert.deepEqual(historyVideoSaveTarget({ url: '/api/local-media?id=legacy' }), {
    url: '/api/local-media?id=legacy',
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

test('current video save uses or creates an MP4 instead of downloading a WebM', () => {
  assert.deepEqual(videoMp4SaveTarget({
    url: '/api/local-media?name=preview.webm',
    mp4Url: '/api/local-media?name=master.mp4',
  }), {
    url: '/api/local-media?name=master.mp4',
    convertMp4: false,
  });
  assert.deepEqual(videoMp4SaveTarget({ url: '/api/local-media?name=legacy.webm' }), {
    url: '/api/local-media?name=legacy.webm',
    convertMp4: true,
  });
  assert.deepEqual(videoMp4SaveTarget({ url: '/api/local-media?name=direct.mp4' }), {
    url: '/api/local-media?name=direct.mp4',
    convertMp4: false,
  });
  assert.deepEqual(videoMp4SaveTarget({
    mp4Url: '/api/local-media?name=mislabelled.webm',
    url: '/api/local-media?name=preview.webm',
  }), {
    url: '/api/local-media?name=mislabelled.webm',
    convertMp4: true,
  });
  assert.equal(videoMp4SaveTarget({}), null);
});

test('retired Sora is never a fallback even when it is the only saved video credential', () => {
  const current = config({
    comfyReachable: false,
    models: { video: {} },
    soraConfigured: true,
  });
  assert.equal(reconcileVideoModel('wan22_14b', current), '');
  assert.equal(reconcileVideoModel('sora', current), '');
});

test('a retired Sora selection falls back to an available cloud provider', () => {
  const current = config({
    comfyReachable: false,
    models: { video: {} },
    soraConfigured: true,
    seedanceConfigured: true,
  });
  assert.equal(reconcileVideoModel('sora', current), 'seedance');
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
