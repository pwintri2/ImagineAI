# ImagineAI

ImagineAI is a local-first image and video studio for people who want a clean,
fast creative cockpit without sending every prompt to a cloud service by
default. It serves a lightweight web UI from `server.py`, talks to your local
ComfyUI install, and keeps settings, keys, and generated media on your machine.

The current app can generate and edit still images with Z-Image Turbo, make
text-to-video or image-to-video clips with Wan 2.1 / Wan 2.2, and optionally use
cloud providers when your GPU is busy: Google Gemini for images, and Atlas Cloud
or xAI Grok Imagine for images and videos.

## Highlights

- Local image generation through ComfyUI's Z-Image Turbo workflow.
- Local video generation through Wan 2.2 14B, Wan 2.2 TI2V 5B, or Wan 2.1 1.3B.
- Optional reference-image upload for image edits with local Z-Image, Gemini, or
  xAI Grok Imagine.
- Optional start-image upload for Wan 2.2 TI2V, Grok Imagine, or Atlas video.
- Optional Gemini image fallback with a locally stored API key.
- Optional xAI Grok Imagine image and video generation with a locally stored API
  key.
- Optional Atlas Cloud image and video generation with a locally stored `atlas`
  key.
- Optional ModelsLab SDXL image and text-to-video generation with a locally
  stored `sdxl` or `modelslab` key.
- Optional Stability image generation with a locally stored `stability` or
  `stability-ai` key.
- Grok, Atlas, and ModelsLab video durations up to 30 seconds in the UI; longer
  cloud videos are generated as multiple provider segments and stitched locally.
- Browser UI plus Tauri desktop packaging.
- Local history, background jobs, media proxying, and ComfyUI model detection.
- No third-party Python packages required for the server.

## Requirements

- Python 3.
- Node.js and npm for the Tauri desktop workflow.
- A running ComfyUI instance, expected at `http://127.0.0.1:8188` by default.
- The ComfyUI model files used by the bundled Z-Image and Wan workflows.
- Optional: a Gemini API key for the cloud image engine.
- Optional: an xAI API key for Grok Imagine image and video generation.
- Optional: an Atlas Cloud API key for image and video generation, saved as
  `atlas`, `atlascloud`, or `atlas-cloud`.
- Optional: a ModelsLab API key saved as `sdxl`, `modelslab`, `free-api`, or
  `vrije-api`.
- Optional: a Stability AI API key saved as `stability` or `stability-ai`.

## Quick Start

```bash
cd ~/imagineai
./start.sh
```

Then open:

```text
http://127.0.0.1:8799
```

You can also run the server directly:

```bash
python3 server.py --port 8799 --open
```

## Desktop App

Install the JavaScript tooling once:

```bash
npm install
```

Run the Tauri shell in development:

```bash
npm run desktop:dev
```

Build a desktop package:

```bash
npm run desktop:build
```

The Tauri build step prepares `desktop-dist/` from the web app. Build output and
generated packages are ignored by git.

## Image And Video Uploads

The Image tab accepts an optional reference image. Reference-image edits are
wired for:

- Local Z-Image Turbo through ComfyUI.
- Gemini image generation/editing.
- xAI Grok Imagine image editing.

Atlas, ModelsLab, and Stability still run text-to-image in the Image tab; if a
reference image is selected, the UI asks you to switch to a supported edit
engine.

The Video tab accepts an optional start image. Start images are wired for:

- Wan 2.2 TI2V 5B through ComfyUI.
- xAI Grok Imagine image-to-video.
- Atlas Cloud image-to-video.

ModelsLab video remains text-to-video only in this app.

## Settings And Keys

Open Settings in the app to configure:

- ComfyUI URL.
- Default image engine.
- Gemini image model.
- Gemini API key.
- xAI image/video models.
- xAI API key.
- Atlas image/video models.
- Other named API keys for future providers or local helper scripts.
- ModelsLab image/video models when a ModelsLab key is saved.
- Stability image model (`core`, `sd3`, or `ultra`) when a Stability key is
  saved.

Secrets are stored locally in `data/secrets.json` with restrictive permissions
where supported. That file is ignored by git. You can also provide the Gemini
key with `GEMINI_API_KEY`. You can provide the xAI key with `XAI_API_KEY`.
You can provide the Atlas key with `ATLAS_API_KEY` or `ATLASCLOUD_API_KEY`, or
save it in Settings as `atlas`, `atlascloud`, or `atlas-cloud`. Atlas
environment variables take precedence over saved keys, which is useful when
switching from an Atlas Coding Plan token to a full Atlas Cloud API key.
You can provide the ModelsLab key with `MODELSLAB_API_KEY`, or save it in
Settings as `sdxl`, `modelslab`, `free-api`, or `vrije-api`. You can provide
the Stability key with `STABILITY_API_KEY`, or save it in Settings as
`stability` or `stability-ai`.
Other saved keys are shown as masked status hints. Supported provider aliases
such as ModelsLab and Stability are used by the built-in generators; unknown
provider names are kept for future integrations.

For ModelsLab images, ImagineAI first tries the high-quality
`/api/v6/images/text2img` endpoint. If ModelsLab returns 403 because that
feature is not available on the current plan, it automatically falls back to
`/api/v6/realtime/text2img`. ModelsLab video 403s are reported as plan/feature
access errors because there is no equivalent text-to-video fallback in the app.
Atlas Coding Plan tokens can list video models, but Atlas returns 403 for video
generation with those tokens. Use a full Atlas Cloud API key/plan for Atlas
video, or use ModelsLab, xAI, or local Wan for video.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | ComfyUI base URL |
| `GEMINI_API_KEY` | empty | Gemini key for cloud image generation |
| `GEMINI_IMAGE_MODEL` | `gemini-2.5-flash-image` | Gemini image model |
| `XAI_API_KEY` | empty | xAI key for Grok Imagine image/video |
| `XAI_IMAGE_MODEL` | `grok-imagine-image-quality` | xAI image model |
| `XAI_VIDEO_MODEL` | `grok-imagine-video` | xAI video model |
| `XAI_BASE_URL` | `https://api.x.ai/v1` | xAI API base URL |
| `ATLAS_API_KEY` / `ATLASCLOUD_API_KEY` | empty | Atlas Cloud key for image/video generation |
| `ATLAS_IMAGE_MODEL` / `ATLASCLOUD_IMAGE_MODEL` | `seedream-3.0` | Atlas Cloud image model |
| `ATLAS_VIDEO_MODEL` / `ATLASCLOUD_VIDEO_MODEL` | `alibaba/wan-2.7/text-to-video` | Atlas Cloud text-to-video model |
| `ATLAS_I2V_MODEL` / `ATLASCLOUD_I2V_MODEL` | `alibaba/wan-2.7/image-to-video` | Atlas Cloud image-to-video model used when a start image is attached |
| `ATLAS_WAN27_RESOLUTION` | `1080P` | Atlas Wan 2.7 resolution (`720P`, `1080P`, `1080P-SR`, or `1440P-SR`) |
| `ATLAS_WAN27_AUDIO` | empty | Optional Wan 2.7 soundtrack URL (`wav` or `mp3`) |
| `ATLAS_WAN27_PROMPT_EXTEND` | `true` | Enables Atlas prompt enhancement for Wan 2.7 |
| `ATLAS_WAN27_SEED` | `-1` | Wan 2.7 seed, with `-1` for random |
| `ATLAS_BASE_URL` / `ATLASCLOUD_BASE_URL` | `https://api.atlascloud.ai/api/v1` | Atlas Cloud API base URL |
| `STABILITY_API_KEY` | empty | Stability/SDXL key for cloud image generation |
| `STABILITY_IMAGE_MODEL` | `core` | Stability image model: `core`, `sd3`, or `ultra` |
| `STABILITY_BASE_URL` | `https://api.stability.ai` | Stability API base URL |
| `MODELSLAB_API_KEY` | empty | ModelsLab key for SDXL image/video generation |
| `MODELSLAB_IMAGE_MODEL` | `sdxl` | ModelsLab image model ID |
| `MODELSLAB_VIDEO_MODEL` | `wan2.2` | ModelsLab text-to-video model ID |
| `MODELSLAB_BASE_URL` | `https://modelslab.com` | ModelsLab API base URL |
| `IMAGINEAI_HOST` | `127.0.0.1` | HTTP bind host |
| `IMAGINEAI_PORT` | `8799` | HTTP port |
| `IMAGINEAI_DATA_DIR` | `./data` | Local settings, secrets, and outputs |
| `IMAGINEAI_XAI_VIDEO_TIMEOUT` | `1200` | xAI video polling timeout in seconds |

## Project Layout

```text
imagineai/
├── server.py              # HTTP server, jobs, ComfyUI bridge, cloud fallbacks
├── start.sh               # local launcher
├── web/                   # browser UI
│   ├── services/          # API clients and generation wrappers
│   └── ui/                # prompt, gallery, history, settings, tabs
├── src-tauri/             # desktop shell
├── scripts/               # launch/build helpers
└── data/                  # ignored local settings, secrets, outputs
```

## Safety Notes

- `data/secrets.json`, `data/settings.json`, generated outputs, build artifacts,
  `node_modules/`, and Python caches are ignored.
- The server proxies ComfyUI media through same-origin local endpoints.
- Heavy ComfyUI jobs run behind a process-wide lock so image and video jobs do
  not fight over the same GPU at the same time.

## License

MIT. See [LICENSE](LICENSE).
