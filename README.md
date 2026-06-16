# ImagineAI

ImagineAI is a local-first image and video studio for people who want a clean,
fast creative cockpit without sending every prompt to a cloud service by
default. It serves a lightweight web UI from `server.py`, talks to your local
ComfyUI install, and keeps settings, keys, and generated media on your machine.

The current app can generate still images with Z-Image Turbo, make text-to-video
clips with Wan 2.1 / Wan 2.2, and optionally fall back to Google Gemini for
cloud image generation when your GPU is busy.

## Highlights

- Local image generation through ComfyUI's Z-Image Turbo workflow.
- Local video generation through Wan 2.2 14B, Wan 2.2 TI2V 5B, or Wan 2.1 1.3B.
- Optional start-image upload for the Wan 2.2 TI2V flow.
- Optional Gemini image fallback with a locally stored API key.
- Browser UI plus Tauri desktop packaging.
- Local history, background jobs, media proxying, and ComfyUI model detection.
- No third-party Python packages required for the server.

## Requirements

- Python 3.
- Node.js and npm for the Tauri desktop workflow.
- A running ComfyUI instance, expected at `http://127.0.0.1:8188` by default.
- The ComfyUI model files used by the bundled Z-Image and Wan workflows.
- Optional: a Gemini API key for the cloud image engine.

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

## Settings And Keys

Open Settings in the app to configure:

- ComfyUI URL.
- Default image engine.
- Gemini image model.
- Gemini API key.

Secrets are stored locally in `data/secrets.json` with restrictive permissions
where supported. That file is ignored by git. You can also provide the Gemini
key with `GEMINI_API_KEY`.

## Environment

| Variable | Default | Purpose |
| --- | --- | --- |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | ComfyUI base URL |
| `GEMINI_API_KEY` | empty | Gemini key for cloud image generation |
| `GEMINI_IMAGE_MODEL` | `gemini-2.5-flash-image` | Gemini image model |
| `IMAGINEAI_HOST` | `127.0.0.1` | HTTP bind host |
| `IMAGINEAI_PORT` | `8799` | HTTP port |
| `IMAGINEAI_DATA_DIR` | `./data` | Local settings, secrets, and outputs |

## Project Layout

```text
imagineai/
├── server.py              # HTTP server, jobs, ComfyUI bridge, cloud fallback
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
