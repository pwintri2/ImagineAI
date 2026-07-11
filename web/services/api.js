// Thin client for the ImagineAI backend.

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

async function getJson(path) {
  return readJson(await fetch(path));
}

async function postJson(path, body) {
  return readJson(await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  }));
}

export const getConfig = () => getJson('/api/config');
export const getSettings = () => getJson('/api/settings');
export const saveSettings = (patch) => postJson('/api/settings', patch);
export const getSecrets = () => getJson('/api/secrets');
export const saveSecret = (provider, key) => postJson('/api/secrets', { provider, key });
export const getGpu = () => getJson('/api/gpu');
export const freeGpu = () => postJson('/api/gpu/free', {});

export const startImageJob = (payload) => postJson('/api/generate/image', payload);
export const startVideoJob = (payload) => postJson('/api/generate/video', payload);
export const cancelJob = (jobId) => postJson(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, {});

async function getJob(jobId) {
  return readJson(await fetch(`/api/jobs/${encodeURIComponent(jobId)}`));
}

/**
 * Poll a job until it finishes. Calls onTick({status, elapsed, meta}) each poll.
 * Resolves with the final job object (status 'done' or 'cancelled'); rejects on error/timeout.
 */
export async function pollJob(jobId, { onTick, intervalMs = 1500, timeoutMs = 60 * 60 * 1000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    let job;
    try {
      job = await getJob(jobId);
    } catch (e) {
      // transient network hiccup — keep trying until the deadline
      if (Date.now() > deadline) throw e;
      await sleep(intervalMs);
      continue;
    }
    if (onTick) onTick(job);
    if (job.status === 'done' || job.status === 'cancelled') return job;
    if (job.status === 'error') throw new Error(job.error || 'Generation failed');
    if (Date.now() > deadline) throw new Error('Timed out waiting for the job');
    await sleep(intervalMs);
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
