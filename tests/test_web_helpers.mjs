import test from 'node:test';
import assert from 'node:assert/strict';

import { friendlyError } from '../web/services/friendly-error.js';
import {
  isVideoModelAvailable,
  reconcileVideoModel,
} from '../web/services/video-model-routing.js';

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

test('Veo and Director selections use their cloud-provider availability', () => {
  const current = config({ geminiConfigured: true });
  assert.equal(reconcileVideoModel('veo', current), 'veo');
  assert.equal(reconcileVideoModel('director', current), 'director');
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
