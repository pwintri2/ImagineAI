import { startVideoJob, pollJob } from './api.js';

export const VIDEO_MODELS = {
  xai: {
    id: 'xai', title: 'Grok Imagine', subtitle: 'Cloud · xAI',
    note: 'xAI text-to-video and image-to-video · uses your xAI quota', defaultSeconds: 5,
  },
  sdxl: {
    id: 'sdxl', title: 'ModelsLab Video', subtitle: 'Cloud · ModelsLab',
    note: 'Text-to-video through ModelsLab · uses your ModelsLab quota', defaultSeconds: 2,
  },
  wan22_14b: {
    id: 'wan22_14b', title: 'Wan 2.2 14B', subtitle: 'Highest quality',
    note: 'Dual-model + 4-step LoRA · slower, sharper', defaultSeconds: 2,
  },
  wan22_ti2v_5b: {
    id: 'wan22_ti2v_5b', title: 'Wan 2.2 TI2V 5B', subtitle: 'Text + image',
    note: 'Hybrid text/image-to-video · lighter 5B model', defaultSeconds: 2,
  },
  wan21_1_3b: {
    id: 'wan21_1_3b', title: 'Wan 2.1 1.3B', subtitle: 'Light & quick',
    note: 'Small model · faster, lower detail', defaultSeconds: 4,
  },
};

/**
 * Generate a video. Returns { results: [{url,type}], meta, prompt }.
 * onProgress(job) is called on each poll tick.
 */
export async function generateVideo({ prompt, model, aspect, seconds, startImage }, onProgress) {
  const { jobId } = await startVideoJob({
    prompt,
    model,
    aspect,
    seconds,
    startImage: startImage?.dataUrl || '',
    startImageName: startImage?.name || '',
  });
  const job = await pollJob(jobId, { onTick: onProgress });
  return {
    results: job.results || [],
    meta: job.meta || {},
    modelTitle: job.meta?.modelTitle || VIDEO_MODELS[model]?.title || model,
    prompt,
  };
}
