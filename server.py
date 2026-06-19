#!/usr/bin/env python3
"""ImagineAI — a Grok-style image & video studio wired to a local ComfyUI.

Local-first: image generation runs on ComfyUI's Z-Image Turbo and video on the
Wan 2.1 / Wan 2.2 text-to-video models — the exact same models DreamweaverComfy
uses. An optional Google Gemini API key (saved locally) provides a cloud image
fallback for when the GPU is busy.

No third-party Python packages required — standard library only.

Run:
    python3 server.py            # serves on http://127.0.0.1:8799
    python3 server.py --port 8799 --open
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import random
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
DATA_DIR = Path(os.environ.get("IMAGINEAI_DATA_DIR", str(APP_DIR / "data")))
OUTPUTS_DIR = DATA_DIR / "outputs"
SECRETS_FILE = DATA_DIR / "secrets.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULT_COMFY_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")
DEFAULT_GEMINI_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_XAI_IMAGE_MODEL = os.environ.get("XAI_IMAGE_MODEL", "grok-imagine-image-quality")
DEFAULT_XAI_VIDEO_MODEL = os.environ.get("XAI_VIDEO_MODEL", "grok-imagine-video")
XAI_BASE = os.environ.get("XAI_BASE_URL", "https://api.x.ai/v1").rstrip("/")
DEFAULT_ATLAS_IMAGE_MODEL = os.environ.get("ATLAS_IMAGE_MODEL", os.environ.get("ATLASCLOUD_IMAGE_MODEL", "seedream-3.0"))
DEFAULT_ATLAS_VIDEO_MODEL = os.environ.get(
    "ATLAS_VIDEO_MODEL",
    os.environ.get("ATLASCLOUD_VIDEO_MODEL", "alibaba/wan-2.7/text-to-video"),
)
DEFAULT_ATLAS_I2V_MODEL = os.environ.get(
    "ATLAS_I2V_MODEL",
    os.environ.get("ATLASCLOUD_I2V_MODEL", "alibaba/wan-2.7/image-to-video"),
)
DEFAULT_ATLAS_WAN27_RESOLUTION = os.environ.get("ATLAS_WAN27_RESOLUTION", "1080P")
DEFAULT_ATLAS_WAN27_AUDIO = os.environ.get("ATLAS_WAN27_AUDIO", "")
DEFAULT_ATLAS_WAN27_PROMPT_EXTEND = os.environ.get("ATLAS_WAN27_PROMPT_EXTEND", "true").strip().lower() not in ("0", "false", "no", "off")
DEFAULT_ATLAS_WAN27_SEED = os.environ.get("ATLAS_WAN27_SEED", "-1")
ATLAS_BASE = os.environ.get("ATLAS_BASE_URL", os.environ.get("ATLASCLOUD_BASE_URL", "https://api.atlascloud.ai/api/v1")).rstrip("/")
DEFAULT_STABILITY_IMAGE_MODEL = os.environ.get("STABILITY_IMAGE_MODEL", "core")
STABILITY_BASE = os.environ.get("STABILITY_BASE_URL", "https://api.stability.ai").rstrip("/")
DEFAULT_MODELSLAB_IMAGE_MODEL = os.environ.get("MODELSLAB_IMAGE_MODEL", "sdxl")
DEFAULT_MODELSLAB_VIDEO_MODEL = os.environ.get("MODELSLAB_VIDEO_MODEL", "wan2.2")
MODELSLAB_BASE = os.environ.get("MODELSLAB_BASE_URL", "https://modelslab.com").rstrip("/")

# ComfyUI's Python (has PyAV) — used to transcode H.264 mp4 -> VP9 webm so the
# Linux webkit2gtk webview, which usually lacks an H.264 decoder, can play video
# inline. Best-effort: if unavailable we fall back to serving the mp4.
COMFY_PYTHON = os.environ.get("COMFY_PYTHON", "/home/pwintri2/ComfyUI/.venv/bin/python")
COMFY_INPUT_DIR = Path(os.environ.get("COMFYUI_INPUT_DIR", "/home/pwintri2/ComfyUI/input"))

COMFY_IMAGE_TIMEOUT = float(os.environ.get("IMAGINEAI_IMAGE_TIMEOUT", "600"))
COMFY_VIDEO_TIMEOUT = float(os.environ.get("IMAGINEAI_VIDEO_TIMEOUT", "3600"))
COMFY_MISSING_HISTORY_GRACE = float(os.environ.get("IMAGINEAI_MISSING_HISTORY_GRACE", "25"))
XAI_VIDEO_TIMEOUT = float(os.environ.get("IMAGINEAI_XAI_VIDEO_TIMEOUT", "1200"))
XAI_MAX_SECONDS_PER_REQUEST = 15
XAI_MAX_STITCHED_SECONDS = 30
MODELSLAB_MAX_STITCHED_SECONDS = 30
ATLAS_MAX_SECONDS_PER_REQUEST = 10
ATLAS_WAN27_MAX_SECONDS_PER_REQUEST = 15
ATLAS_MAX_STITCHED_SECONDS = 30
ATLAS_IMAGE_TIMEOUT = float(os.environ.get("IMAGINEAI_ATLAS_IMAGE_TIMEOUT", "600"))
ATLAS_VIDEO_TIMEOUT = float(os.environ.get("IMAGINEAI_ATLAS_VIDEO_TIMEOUT", "1200"))

# Wan video shares the GPU with Z-Image; only one heavy ComfyUI job at a time.
COMFY_LOCK = threading.Lock()

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
SETTINGS_LOCK = threading.Lock()
SECRETS_LOCK = threading.Lock()

KNOWN_SECRET_PROVIDERS = ("gemini", "xai")
SECRET_ENV_KEYS = {"gemini": "GEMINI_API_KEY", "xai": "XAI_API_KEY"}
ATLAS_SECRET_PROVIDERS = ("atlas", "atlascloud", "atlas-cloud")
STABILITY_SECRET_PROVIDERS = ("stability", "stability-ai")
MODELSLAB_SECRET_PROVIDERS = (
    "modelslab",
    "models-lab",
    "stable-diffusion-api",
    "sdxl",
    "modelslab-free",
    "modelslab-free-api",
    "models-lab-free",
    "models-lab-free-api",
    "free-api",
    "freeapi",
    "vrije-api",
    "vrijeapi",
)

DEFAULT_NEGATIVE_IMAGE = ""
DEFAULT_NEGATIVE_VIDEO = (
    "oversaturated, overexposed, static image, blurry details, subtitles, "
    "watermark, painting, still frame, grey cast, worst quality, low quality, "
    "jpeg artifacts, ugly, malformed hands, bad face, deformed limbs, fused "
    "fingers, motionless, cluttered background, extra legs, crowded background, "
    "walking backwards, nude, NSFW"
)

ASPECT_TO_SIZE = {
    "square": (1024, 1024),
    "landscape": (1216, 832),
    "portrait": (832, 1216),
    "wide": (1280, 720),
    "tall": (720, 1280),
}
TI2V_ASPECT_TO_SIZE = {
    "square": (768, 768),
    "landscape": (1024, 768),
    "portrait": (768, 1024),
    "wide": (1280, 704),
    "tall": (704, 1280),
}
# Aspect ratio string Gemini understands (best-effort; older models ignore it).
ASPECT_TO_GEMINI = {
    "square": "1:1",
    "landscape": "4:3",
    "portrait": "3:4",
    "wide": "16:9",
    "tall": "9:16",
}
ASPECT_TO_XAI = ASPECT_TO_GEMINI
ASPECT_TO_STABILITY = {
    "square": "1:1",
    "landscape": "3:2",
    "portrait": "2:3",
    "wide": "16:9",
    "tall": "9:16",
}
ASPECT_TO_MODELSLAB_IMAGE_SIZE = {
    "square": (768, 768),
    "landscape": (1024, 768),
    "portrait": (768, 1024),
    "wide": (1024, 576),
    "tall": (576, 1024),
}
ASPECT_TO_MODELSLAB_VIDEO_SIZE = {
    "square": (512, 512),
    "landscape": (512, 384),
    "portrait": (384, 512),
    "wide": (512, 288),
    "tall": (288, 512),
}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def clamp_int(value: object, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(float(value))  # tolerate "8", 8.0, etc.
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def clamp_float(value: object, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def now() -> float:
    return time.time()


def safe_prefix(folder: str, prompt: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", prompt.lower())[:5]
    slug = "_".join(words) or "imagineai"
    stamp = time.strftime("%Y%m%d_%H%M%S")
    return f"{folder}/{stamp}_{slug}"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------- #
# Settings + secrets (persisted locally; secrets file is chmod 600)
# --------------------------------------------------------------------------- #
def load_settings() -> dict[str, Any]:
    defaults = {
        "comfyUrl": DEFAULT_COMFY_URL,
        "geminiModel": DEFAULT_GEMINI_MODEL,
        "xaiImageModel": DEFAULT_XAI_IMAGE_MODEL,
        "xaiVideoModel": DEFAULT_XAI_VIDEO_MODEL,
        "atlasImageModel": DEFAULT_ATLAS_IMAGE_MODEL,
        "atlasVideoModel": DEFAULT_ATLAS_VIDEO_MODEL,
        "stabilityImageModel": DEFAULT_STABILITY_IMAGE_MODEL,
        "modelslabImageModel": DEFAULT_MODELSLAB_IMAGE_MODEL,
        "modelslabVideoModel": DEFAULT_MODELSLAB_VIDEO_MODEL,
        "defaultImageEngine": "local",
    }
    allowed = set(defaults)
    with SETTINGS_LOCK:
        if SETTINGS_FILE.exists():
            try:
                stored = json.loads(SETTINGS_FILE.read_text("utf-8"))
                if isinstance(stored, dict):
                    defaults.update({k: v for k, v in stored.items() if k in allowed and v is not None})
            except (json.JSONDecodeError, OSError):
                pass
    legacy_atlas_video_models = {
        "kling",
        "kling-v2",
        "kling-v2.0",
        "kling-v1.6-t2v-standard",
        "kling-v1.6-i2v-standard",
        "kwaivgi/kling-v1.6-t2v-standard",
        "kwaivgi/kling-v1.6-i2v-standard",
        "kwaivgi/kling-v2.5-turbo-pro/text-to-video",
        "kwaivgi/kling-v2.5-turbo-pro/image-to-video",
    }
    if str(defaults.get("atlasVideoModel") or "").strip().lower() in legacy_atlas_video_models:
        defaults["atlasVideoModel"] = DEFAULT_ATLAS_VIDEO_MODEL
    return defaults


def valid_http_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    current = load_settings()
    for key in ("comfyUrl", "geminiModel", "xaiImageModel", "xaiVideoModel", "atlasImageModel", "atlasVideoModel", "stabilityImageModel",
                "modelslabImageModel", "modelslabVideoModel", "defaultImageEngine"):
        if key in patch and isinstance(patch[key], str) and patch[key].strip():
            value = patch[key].strip()
            if key == "comfyUrl":
                value = value.rstrip("/")
                if not valid_http_url(value):
                    raise ValueError("ComfyUI URL must be an http(s):// address.")
            current[key] = value
    with SETTINGS_LOCK:
        ensure_dirs()
        SETTINGS_FILE.write_text(json.dumps(current, indent=2), "utf-8")
    return current


def comfy_url() -> str:
    return str(load_settings().get("comfyUrl") or DEFAULT_COMFY_URL).rstrip("/")


def load_secrets() -> dict[str, str]:
    with SECRETS_LOCK:
        if SECRETS_FILE.exists():
            try:
                data = json.loads(SECRETS_FILE.read_text("utf-8"))
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items() if v}
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def normalize_secret_provider(provider: str) -> str:
    normalized = re.sub(r"\s+", "-", provider.strip().lower())
    normalized = re.sub(r"[^a-z0-9_.:-]+", "-", normalized).strip("-._:")
    if not normalized:
        raise ValueError("Provider name is required.")
    if len(normalized) > 64:
        raise ValueError("Provider name is too long.")
    return normalized


def secret_status(value: str, source: str) -> dict[str, str | bool]:
    return {
        "configured": bool(value),
        "hint": (f"…{value[-4:]}" if value and source == "file" else ("environment" if value else "")),
        "source": source if value else "",
    }


def save_secret(provider: str, key: str) -> None:
    provider = normalize_secret_provider(provider)
    key = key.strip()
    with SECRETS_LOCK:
        ensure_dirs()
        data = {}
        if SECRETS_FILE.exists():
            try:
                data = json.loads(SECRETS_FILE.read_text("utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
        if not isinstance(data, dict):
            data = {}
        if key:
            data[provider] = key
        else:
            data.pop(provider, None)
        SECRETS_FILE.write_text(json.dumps(data, indent=2), "utf-8")
        try:
            os.chmod(SECRETS_FILE, 0o600)
        except OSError:
            pass


def gemini_key() -> str:
    return load_secrets().get("gemini") or os.environ.get("GEMINI_API_KEY", "")


def xai_key() -> str:
    return load_secrets().get("xai") or os.environ.get("XAI_API_KEY", "")


def atlas_key() -> tuple[str, str]:
    for env_key in ("ATLAS_API_KEY", "ATLASCLOUD_API_KEY"):
        if os.environ.get(env_key):
            return os.environ.get(env_key, ""), env_key
    secrets = load_secrets()
    for provider in ATLAS_SECRET_PROVIDERS:
        if secrets.get(provider):
            return secrets[provider], provider
    return "", "env"


def stability_key() -> tuple[str, str]:
    secrets = load_secrets()
    for provider in STABILITY_SECRET_PROVIDERS:
        if secrets.get(provider):
            return secrets[provider], provider
    return os.environ.get("STABILITY_API_KEY", ""), "env"


def modelslab_key() -> tuple[str, str]:
    secrets = load_secrets()
    for provider in MODELSLAB_SECRET_PROVIDERS:
        if secrets.get(provider):
            return secrets[provider], provider
    return os.environ.get("MODELSLAB_API_KEY", ""), "env"


# --------------------------------------------------------------------------- #
# ComfyUI bridge
# --------------------------------------------------------------------------- #
class ComfyUnavailable(RuntimeError):
    pass


def comfy_request(path: str, payload: dict[str, Any] | None = None,
                  method: str = "GET", timeout: float = 30) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{comfy_url()}{path}", data=body, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.URLError as exc:
        raise ComfyUnavailable(
            f"ComfyUI is not reachable at {comfy_url()}. Start ComfyUI and try again."
        ) from exc
    return json.loads(raw.decode("utf-8") or "{}")


def comfy_get_bytes(path: str, timeout: float = 60) -> tuple[bytes, str]:
    req = urllib.request.Request(f"{comfy_url()}{path}")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "application/octet-stream")


def queue_comfy_prompt(graph: dict[str, Any], client_id: str) -> str:
    prompt_id = f"imagineai-{int(now())}-{uuid.uuid4().hex[:8]}"
    response = comfy_request(
        "/prompt",
        {"prompt": graph, "prompt_id": prompt_id, "client_id": client_id},
        method="POST",
        timeout=30,
    )
    if response.get("node_errors"):
        raise RuntimeError(json.dumps(response["node_errors"], ensure_ascii=False))
    return prompt_id


def queue_contains_prompt(queue: dict[str, Any], prompt_id: str) -> bool:
    for bucket in ("queue_running", "queue_pending"):
        for item in queue.get(bucket, []) or []:
            if isinstance(item, list) and prompt_id in (str(part) for part in item):
                return True
    return False


def wait_for_history(prompt_id: str, timeout: float, on_state=None) -> dict[str, Any]:
    deadline = now() + timeout
    missing_since: float | None = None
    while now() < deadline:
        history = comfy_request(f"/history/{urllib.parse.quote(prompt_id)}", timeout=30)
        item = history.get(prompt_id)
        if isinstance(item, dict):
            return item
        try:
            queue = comfy_request("/queue", timeout=10)
        except ComfyUnavailable:
            queue = {}
        if queue_contains_prompt(queue, prompt_id):
            missing_since = None
            if on_state:
                on_state("running")
        else:
            if missing_since is None:
                missing_since = now()
            elif now() - missing_since >= COMFY_MISSING_HISTORY_GRACE:
                raise RuntimeError(f"ComfyUI dropped prompt {prompt_id} without a result.")
        time.sleep(1.5)
    try:
        comfy_request("/interrupt", {}, method="POST", timeout=5)
    except Exception:
        pass
    raise TimeoutError(f"ComfyUI job timed out: {prompt_id}")


def extract_error(history_item: dict[str, Any]) -> Any:
    status = history_item.get("status")
    if isinstance(status, dict) and status.get("status_str") == "error":
        messages = status.get("messages")
        if isinstance(messages, list):
            for message in messages:
                if isinstance(message, list) and message and message[0] == "execution_error":
                    return message[1] if len(message) > 1 else message
        return status
    return None


def extract_entries(history_item: dict[str, Any], media: str) -> list[dict[str, Any]]:
    outputs = history_item.get("outputs", {})
    if not isinstance(outputs, dict):
        return []
    keys = ("videos", "gifs", "files", "images") if media == "video" else ("images",)
    entries: list[dict[str, Any]] = []
    for output in outputs.values():
        if not isinstance(output, dict):
            continue
        for key in keys:
            values = output.get(key)
            if not isinstance(values, list):
                continue
            for entry in values:
                if not isinstance(entry, dict) or not entry.get("filename"):
                    continue
                filename = str(entry["filename"]).lower()
                is_video = filename.endswith((".mp4", ".webm", ".gif", ".mov"))
                if media == "video" and (key != "images" or is_video):
                    entries.append(dict(entry))
                elif media == "image" and not is_video:
                    entries.append(dict(entry))
    return entries


def entry_to_media_url(entry: dict[str, Any]) -> str:
    params = urllib.parse.urlencode({
        "filename": entry.get("filename", ""),
        "subfolder": entry.get("subfolder", ""),
        "type": entry.get("type", "output"),
    })
    return f"/api/comfy-view?{params}"


def detect_models() -> dict[str, Any]:
    """Ask ComfyUI which of our known model files are installed."""
    info: dict[str, Any] = {"reachable": False, "image": {}, "video": {}}
    try:
        unets = comfy_request("/object_info/UNETLoader", timeout=8)
        clips = comfy_request("/object_info/CLIPLoader", timeout=8)
        vaes = comfy_request("/object_info/VAELoader", timeout=8)
    except Exception:
        return info
    info["reachable"] = True

    def listed(node: dict[str, Any], key: str) -> set[str]:
        try:
            options = node[list(node)[0]]["input"]["required"][key][0]
            return {str(opt) for opt in options}
        except (KeyError, IndexError, TypeError):
            return set()

    unet_names = listed(unets, "unet_name")
    clip_names = listed(clips, "clip_name")
    vae_names = listed(vaes, "vae_name")

    info["image"]["zimage_turbo"] = (
        "z_image_turbo_bf16.safetensors" in unet_names
        and "qwen_3_4b.safetensors" in clip_names
        and "ae.safetensors" in vae_names
    )
    info["video"]["wan22_14b"] = (
        "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors" in unet_names
        and "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors" in unet_names
        and "umt5_xxl_fp8_e4m3fn_scaled.safetensors" in clip_names
        and "wan_2.1_vae.safetensors" in vae_names
    )
    info["video"]["wan22_ti2v_5b"] = (
        "wan2.2_ti2v_5B_fp16.safetensors" in unet_names
        and "umt5_xxl_fp8_e4m3fn_scaled.safetensors" in clip_names
        and "wan2.2_vae.safetensors" in vae_names
    )
    info["video"]["wan21_1_3b"] = (
        "Wan2.1/wan2.1_t2v_1.3B_fp16.safetensors" in unet_names
        and "umt5_xxl_fp8_e4m3fn_scaled.safetensors" in clip_names
        and "wan_2.1_vae.safetensors" in vae_names
    )
    return info


# --------------------------------------------------------------------------- #
# Graph builders — verbatim from the working ComfyUI helper pages
# --------------------------------------------------------------------------- #
def build_zimage_graph(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    prompt = str(data.get("prompt", "")).strip()
    negative = str(data.get("negative_prompt", DEFAULT_NEGATIVE_IMAGE)).strip()
    width = clamp_int(data.get("width"), 768, 256, 2048)
    height = clamp_int(data.get("height"), 768, 256, 2048)
    width -= width % 16
    height -= height % 16
    seed = clamp_int(data.get("seed"), random.randint(0, 2**32 - 1), 0, 2**63 - 1)
    steps = clamp_int(data.get("steps"), 8, 1, 30)
    cfg = clamp_float(data.get("cfg"), 1.0, 0.0, 12.0)
    batch_size = clamp_int(data.get("batch_size"), 1, 1, 4)
    source_image = str(data.get("source_image") or "").strip()
    image_strength = clamp_float(data.get("image_strength"), 0.65, 0.05, 1.0)

    graph: dict[str, dict[str, Any]] = {
        "30": {"class_type": "CLIPLoader",
               "inputs": {"clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"}},
        "29": {"class_type": "VAELoader", "inputs": {"vae_name": "ae.safetensors"}},
        "28": {"class_type": "UNETLoader",
               "inputs": {"unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"}},
        "11": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["28", 0], "shift": 3.0}},
        "27": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["30", 0], "text": prompt}},
        "13": {"class_type": "EmptySD3LatentImage",
               "inputs": {"width": width, "height": height, "batch_size": batch_size}},
        "3": {"class_type": "KSampler",
              "inputs": {"model": ["11", 0], "positive": ["27", 0], "negative": ["33", 0],
                         "latent_image": ["13", 0], "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "res_multistep", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["29", 0]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": safe_prefix("imagineai", prompt)}},
    }
    if negative:
        graph["33"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["30", 0], "text": negative}}
    else:
        graph["33"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["27", 0]}}
    if source_image:
        graph["34"] = {"class_type": "LoadImage", "inputs": {"image": source_image}}
        graph["35"] = {"class_type": "ImageScale",
                       "inputs": {"image": ["34", 0], "upscale_method": "bicubic",
                                  "width": width, "height": height, "crop": "center"}}
        graph["36"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["35", 0], "vae": ["29", 0]}}
        graph["3"]["inputs"]["latent_image"] = ["36", 0]
        graph["3"]["inputs"]["denoise"] = image_strength
        graph.pop("13", None)
        if batch_size > 1:
            graph["37"] = {"class_type": "RepeatLatentBatch",
                           "inputs": {"samples": ["36", 0], "amount": batch_size}}
            graph["3"]["inputs"]["latent_image"] = ["37", 0]
    return graph


def wan_frames(seconds: float, fps: float) -> int:
    base = max(1, int(round(seconds * fps)))
    return base + ((1 - base) % 4)  # Wan needs frames ≡ 1 (mod 4)


def build_wan21_graph(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    prompt = str(data.get("prompt", "")).strip()
    negative = str(data.get("negative_prompt", DEFAULT_NEGATIVE_VIDEO)).strip()
    seconds = clamp_float(data.get("seconds"), 4.0, 1.0, 120.0)
    fps = clamp_float(data.get("fps"), 8.0, 1.0, 24.0)
    width = clamp_int(data.get("width"), 480, 16, 16384)
    height = clamp_int(data.get("height"), 320, 16, 16384)
    width = max(16, width - (width % 16))
    height = max(16, height - (height % 16))
    frames = clamp_int(data.get("frames"), wan_frames(seconds, fps), 1, 16384)
    frames = frames + ((1 - frames) % 4)
    seed = clamp_int(data.get("seed"), random.randint(0, 2**32 - 1), 0, 2**63 - 1)
    steps = clamp_int(data.get("steps"), 8, 1, 40)
    cfg = clamp_float(data.get("cfg"), 5.0, 0.0, 20.0)
    return {
        "38": {"class_type": "CLIPLoader",
               "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "37": {"class_type": "UNETLoader",
               "inputs": {"unet_name": "Wan2.1/wan2.1_t2v_1.3B_fp16.safetensors", "weight_dtype": "default"}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["38", 0], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["38", 0], "text": negative}},
        "40": {"class_type": "EmptyHunyuanLatentVideo",
               "inputs": {"width": width, "height": height, "length": frames, "batch_size": 1}},
        "3": {"class_type": "KSampler",
              "inputs": {"model": ["37", 0], "positive": ["6", 0], "negative": ["7", 0],
                         "latent_image": ["40", 0], "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "uni_pc", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
        "114": {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "fps": fps}},
        "116": {"class_type": "SaveVideo",
                "inputs": {"video": ["114", 0], "filename_prefix": safe_prefix("imagineai_wan21", prompt),
                           "format": "mp4", "codec": "h264"}},
    }


def build_wan22_graph(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    prompt = str(data.get("prompt", "")).strip()
    negative = str(data.get("negative_prompt", DEFAULT_NEGATIVE_VIDEO)).strip()
    seconds = clamp_float(data.get("seconds"), 2.0, 1.0, 120.0)
    fps = clamp_float(data.get("fps"), 16.0, 1.0, 24.0)
    width = clamp_int(data.get("width"), 512, 16, 16384)
    height = clamp_int(data.get("height"), 512, 16, 16384)
    width = max(16, width - (width % 16))
    height = max(16, height - (height % 16))
    frames = clamp_int(data.get("frames"), wan_frames(seconds, fps), 1, 16384)
    frames = frames + ((1 - frames) % 4)
    seed = clamp_int(data.get("seed"), random.randint(0, 2**32 - 1), 0, 2**63 - 1)
    steps = clamp_int(data.get("steps"), 4, 1, 40)
    cfg = clamp_float(data.get("cfg"), 1.0, 0.0, 20.0)
    return {
        "71": {"class_type": "CLIPLoader",
               "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "73": {"class_type": "VAELoader", "inputs": {"vae_name": "wan_2.1_vae.safetensors"}},
        "75": {"class_type": "UNETLoader",
               "inputs": {"unet_name": "wan2.2_t2v_high_noise_14B_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "76": {"class_type": "UNETLoader",
               "inputs": {"unet_name": "wan2.2_t2v_low_noise_14B_fp8_scaled.safetensors", "weight_dtype": "default"}},
        "83": {"class_type": "LoraLoaderModelOnly",
               "inputs": {"model": ["75", 0], "lora_name": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_high_noise.safetensors",
                          "strength_model": 1.0}},
        "85": {"class_type": "LoraLoaderModelOnly",
               "inputs": {"model": ["76", 0], "lora_name": "wan2.2_t2v_lightx2v_4steps_lora_v1.1_low_noise.safetensors",
                          "strength_model": 1.0}},
        "82": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["83", 0], "shift": 5.0}},
        "86": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["85", 0], "shift": 5.0}},
        "89": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["71", 0], "text": prompt}},
        "72": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["71", 0], "text": negative}},
        "74": {"class_type": "EmptyHunyuanLatentVideo",
               "inputs": {"width": width, "height": height, "length": frames, "batch_size": 1}},
        "81": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["82", 0], "positive": ["89", 0], "negative": ["72", 0],
                          "latent_image": ["74", 0], "add_noise": "enable", "noise_seed": seed,
                          "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
                          "start_at_step": 0, "end_at_step": 2, "return_with_leftover_noise": "enable"}},
        "78": {"class_type": "KSamplerAdvanced",
               "inputs": {"model": ["86", 0], "positive": ["89", 0], "negative": ["72", 0],
                          "latent_image": ["81", 0], "add_noise": "disable", "noise_seed": seed,
                          "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "simple",
                          "start_at_step": 2, "end_at_step": 4, "return_with_leftover_noise": "disable"}},
        "87": {"class_type": "VAEDecode", "inputs": {"samples": ["78", 0], "vae": ["73", 0]}},
        "114": {"class_type": "CreateVideo", "inputs": {"images": ["87", 0], "fps": fps}},
        "116": {"class_type": "SaveVideo",
                "inputs": {"video": ["114", 0], "filename_prefix": safe_prefix("imagineai_wan22", prompt),
                           "format": "mp4", "codec": "h264"}},
    }


def build_wan22_ti2v_graph(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    prompt = str(data.get("prompt", "")).strip()
    negative = str(data.get("negative_prompt", DEFAULT_NEGATIVE_VIDEO)).strip()
    seconds = clamp_float(data.get("seconds"), 2.0, 1.0, 120.0)
    fps = clamp_float(data.get("fps"), 16.0, 1.0, 24.0)
    width = clamp_int(data.get("width"), 768, 32, 16384)
    height = clamp_int(data.get("height"), 768, 32, 16384)
    width = max(32, width - (width % 32))
    height = max(32, height - (height % 32))
    frames = clamp_int(data.get("frames"), wan_frames(seconds, fps), 1, 16384)
    frames = frames + ((1 - frames) % 4)
    seed = clamp_int(data.get("seed"), random.randint(0, 2**32 - 1), 0, 2**63 - 1)
    steps = clamp_int(data.get("steps"), 30, 1, 60)
    cfg = clamp_float(data.get("cfg"), 5.0, 0.0, 20.0)
    start_image = str(data.get("start_image") or "").strip()

    graph: dict[str, dict[str, Any]] = {
        "38": {"class_type": "CLIPLoader",
               "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "39": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "37": {"class_type": "UNETLoader",
               "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors", "weight_dtype": "default"}},
        "48": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["37", 0], "shift": 8.0}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["38", 0], "text": prompt}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["38", 0], "text": negative}},
        "55": {"class_type": "Wan22ImageToVideoLatent",
               "inputs": {"vae": ["39", 0], "width": width, "height": height, "length": frames, "batch_size": 1}},
        "3": {"class_type": "KSampler",
              "inputs": {"model": ["48", 0], "positive": ["6", 0], "negative": ["7", 0],
                         "latent_image": ["55", 0], "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "uni_pc", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["39", 0]}},
        "114": {"class_type": "CreateVideo", "inputs": {"images": ["8", 0], "fps": fps}},
        "116": {"class_type": "SaveVideo",
                "inputs": {"video": ["114", 0], "filename_prefix": safe_prefix("imagineai_wan22_ti2v", prompt),
                           "format": "mp4", "codec": "h264"}},
    }
    if start_image:
        graph["57"] = {"class_type": "LoadImage", "inputs": {"image": start_image}}
        graph["55"]["inputs"]["start_image"] = ["57", 0]
    return graph


def decode_image_data_url(data_url: object) -> tuple[str, bytes]:
    if not isinstance(data_url, str) or not data_url.strip():
        raise ValueError("Start image must be a PNG, JPG, or WebP image.")
    match = re.match(r"^data:image/(png|jpe?g|webp);base64,(.+)$", data_url, re.I | re.S)
    if not match:
        raise ValueError("Start image must be a PNG, JPG, or WebP image.")

    ext = "jpg" if match.group(1).lower() in ("jpg", "jpeg") else match.group(1).lower()
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Start image could not be read.") from exc

    if len(raw) > 24 * 1024 * 1024:
        raise ValueError("Start image is too large. Use an image under 24 MB.")
    return ext, raw


def save_uploaded_image_for_comfy(data_url: object, original_name: object = "", prefix: str = "upload") -> str:
    if not isinstance(data_url, str) or not data_url.strip():
        return ""

    ext, raw = decode_image_data_url(data_url)

    words = re.findall(r"[A-Za-z0-9]+", str(original_name or prefix or "upload"))[:4]
    slug = "_".join(words) or prefix or "upload"
    safe_prefix_value = re.sub(r"[^A-Za-z0-9_]+", "_", prefix or "upload").strip("_") or "upload"
    upload_dir = COMFY_INPUT_DIR / "imagineai"
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{safe_prefix_value}_{int(now())}_{uuid.uuid4().hex[:8]}_{slug}.{ext}"
    (upload_dir / filename).write_bytes(raw)
    return f"imagineai/{filename}"


def save_start_image_for_comfy(data_url: object, original_name: object = "") -> str:
    return save_uploaded_image_for_comfy(data_url, original_name, "i2v")


def save_source_image_for_comfy(data_url: object, original_name: object = "") -> str:
    return save_uploaded_image_for_comfy(data_url, original_name, "img2img")


def image_data_url_for_provider(data_url: object) -> tuple[str, str, bytes]:
    ext, raw = decode_image_data_url(data_url)
    mime = "image/jpeg" if ext == "jpg" else f"image/{ext}"
    b64 = base64.b64encode(raw).decode("ascii")
    return mime, b64, raw


def output_url(name: str) -> str:
    return f"/api/local-media?name={urllib.parse.quote(name)}"


def media_ext_from_content_type(content_type: str, fallback: str) -> str:
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    if ctype == "image/png":
        return ".png"
    if ctype in ("image/jpeg", "image/jpg"):
        return ".jpg"
    if ctype == "image/webp":
        return ".webp"
    if ctype == "image/gif":
        return ".gif"
    if ctype == "video/webm":
        return ".webm"
    if ctype in ("video/mp4", "application/mp4"):
        return ".mp4"
    return fallback if fallback.startswith(".") else f".{fallback}"


def save_output_bytes(prefix: str, raw: bytes, ext: str) -> tuple[str, Path, str]:
    ensure_dirs()
    safe_ext = ext if re.fullmatch(r"\.[A-Za-z0-9]+", ext) else ".bin"
    name = f"{prefix}_{int(now())}_{uuid.uuid4().hex[:8]}{safe_ext.lower()}"
    path = OUTPUTS_DIR / name
    path.write_bytes(raw)
    return output_url(name), path, name


def download_url_to_output(url: str, prefix: str, fallback_ext: str,
                           timeout: float = 240) -> tuple[str, Path, str]:
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "ImagineAI/1.0")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            ext = media_ext_from_content_type(response.headers.get("Content-Type", ""), fallback_ext)
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise RuntimeError(
                "The provider returned a media URL that is not downloadable yet. "
                "Please retry; if it repeats, the provider may still be processing the file."
            ) from exc
        raise
    return save_output_bytes(prefix, raw, ext)


def safe_download_name(value: object, fallback: str) -> str:
    name = str(value or "").strip()
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = fallback
    return name[:160] or fallback


def content_disposition_attachment(filename: str) -> str:
    safe = filename.replace("\\", "_").replace('"', "_")
    return f'attachment; filename="{safe}"'


# --------------------------------------------------------------------------- #
# Gemini cloud image fallback
# --------------------------------------------------------------------------- #
def gemini_generate_image(prompt: str, aspect: str, model: str, key: str,
                          source_image: object = "") -> list[str]:
    """Returns a list of local /api/local-media URLs for generated images."""
    url = f"{GEMINI_BASE}/models/{urllib.parse.quote(model)}:generateContent"
    ratio = ASPECT_TO_GEMINI.get(aspect, "1:1")
    source_parts: list[dict[str, Any]] = []
    if isinstance(source_image, str) and source_image.strip():
        mime, b64, raw = image_data_url_for_provider(source_image)
        if len(raw) > 20 * 1024 * 1024:
            raise ValueError("Gemini image edits need an uploaded image under 20 MB.")
        source_parts = [
            {"inlineData": {"mimeType": mime, "data": b64}},
            {"inline_data": {"mime_type": mime, "data": b64}},
        ]

    def post(payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("x-goog-api-key", key)
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

    def base_payload(source_part: dict[str, Any] | None = None) -> dict[str, Any]:
        parts = [{"text": prompt}]
        if source_part:
            parts.append(source_part)
        return {"contents": [{"parts": parts}]}

    bases = [base_payload(part) for part in source_parts] or [base_payload()]
    # The exact aspect-ratio nesting changed across Gemini API revisions; try the
    # richest payload first and fall back to simpler ones on a 400 so the cloud
    # fallback still returns an image whatever version the key is wired to.
    variants: list[dict[str, Any]] = []
    for base in bases:
        variants.extend([
            {**base, "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": ratio}}},
            {**base, "generationConfig": {"responseModalities": ["IMAGE"], "aspectRatio": ratio}},
            {**base, "generationConfig": {"responseModalities": ["IMAGE"]}},
            base,
        ])
    data: dict[str, Any] | None = None
    last_error: RuntimeError | None = None
    for payload in variants:
        try:
            data = post(payload)
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            last_error = RuntimeError(f"Gemini API error {exc.code}: {detail}")
            if exc.code == 400:
                continue  # payload shape rejected — try a simpler one
            raise last_error from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Gemini API: {exc.reason}") from exc
    if data is None:
        raise last_error or RuntimeError("Gemini request failed.")

    urls: list[str] = []
    for candidate in data.get("candidates", []) or []:
        parts = (candidate.get("content") or {}).get("parts") or []
        for part in parts:
            inline = part.get("inlineData") or part.get("inline_data")
            if not inline or not inline.get("data"):
                continue
            mime = inline.get("mimeType") or inline.get("mime_type") or "image/png"
            ext = ".png" if "png" in mime else (".jpg" if "jpeg" in mime else ".png")
            raw = base64.b64decode(inline["data"])
            name = f"gemini_{int(now())}_{uuid.uuid4().hex[:8]}{ext}"
            (OUTPUTS_DIR / name).write_bytes(raw)
            urls.append(f"/api/local-media?name={urllib.parse.quote(name)}")
    if not urls:
        feedback = data.get("promptFeedback") or {}
        block = feedback.get("blockReason")
        raise RuntimeError(
            f"Gemini returned no image (blocked: {block})." if block
            else "Gemini returned no image data. Try a different prompt or model."
        )
    return urls


# --------------------------------------------------------------------------- #
# xAI / Grok Imagine cloud image + video
# --------------------------------------------------------------------------- #
def xai_request_json(path: str, key: str, payload: dict[str, Any] | None = None,
                     method: str = "GET", timeout: float = 120) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{XAI_BASE}{path}", data=body, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8") or "{}"
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        message = detail[:500]
        try:
            parsed = json.loads(detail)
            err = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(err, dict):
                message = str(err.get("message") or err.get("code") or message)
            elif isinstance(err, str):
                message = err
        except (json.JSONDecodeError, TypeError):
            pass
        raise RuntimeError(f"xAI API error {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach xAI API: {exc.reason}") from exc
    return json.loads(raw)


def xai_generate_image(prompt: str, aspect: str, count: int, model: str, key: str,
                       source_image: object = "") -> list[str]:
    has_source_image = isinstance(source_image, str) and bool(source_image.strip())
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
    }
    path = "/images/generations"
    if has_source_image:
        decode_image_data_url(source_image)
        payload["image"] = {"url": source_image, "type": "image_url"}
        path = "/images/edits"
    else:
        payload["n"] = clamp_int(count, 1, 1, 10)
        payload["response_format"] = "b64_json"
        payload["aspect_ratio"] = ASPECT_TO_XAI.get(aspect, "1:1")
    data = xai_request_json(path, key, payload, method="POST", timeout=240)
    urls: list[str] = []
    for item in data.get("data", []) or []:
        if not isinstance(item, dict):
            continue
        b64 = item.get("b64_json")
        if isinstance(b64, str) and b64.strip():
            if b64.startswith("data:") and "," in b64:
                b64 = b64.split(",", 1)[1]
            try:
                raw = base64.b64decode(b64, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise RuntimeError("xAI returned image data that could not be decoded.") from exc
            url, _, _ = save_output_bytes("xai_image", raw, ".jpg")
            urls.append(url)
            continue
        remote_url = item.get("url")
        if isinstance(remote_url, str) and remote_url.strip():
            url, _, _ = download_url_to_output(remote_url, "xai_image", ".jpg")
            urls.append(url)
    if not urls:
        raise RuntimeError("xAI returned no image data. Try a different prompt or model.")
    return urls


def xai_public_video_result(result: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in result.items() if k != "mp4Path"}
    return out


def xai_generate_video_clip(prompt: str, aspect: str, duration: int, model: str, key: str,
                            start_image: object = "", on_progress=None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": ASPECT_TO_XAI.get(aspect, "16:9"),
        "resolution": "720p",
    }
    if isinstance(start_image, str) and start_image.strip():
        decode_image_data_url(start_image)
        payload["image"] = {"url": start_image}

    started = xai_request_json("/videos/generations", key, payload, method="POST", timeout=120)
    request_id = str(started.get("request_id") or "").strip()
    if not request_id:
        raise RuntimeError("xAI did not return a video request_id.")

    deadline = now() + XAI_VIDEO_TIMEOUT
    while now() < deadline:
        data = xai_request_json(f"/videos/{urllib.parse.quote(request_id)}", key, timeout=120)
        status = str(data.get("status") or "").lower()
        progress = data.get("progress")
        if on_progress:
            on_progress(status or "running", progress)
        if status == "done":
            video = data.get("video") if isinstance(data.get("video"), dict) else {}
            remote_url = str(video.get("url") or "").strip()
            if not remote_url:
                raise RuntimeError("xAI video finished without a video URL.")
            mp4_url, mp4_path, _ = download_url_to_output(remote_url, "xai_video", ".mp4", timeout=600)
            webm_url = transcode_mp4_path_to_webm(mp4_path)
            return {"url": webm_url or mp4_url, "type": "video", "mp4Url": mp4_url, "mp4Path": str(mp4_path)}
        if status in ("failed", "expired"):
            err = data.get("error") if isinstance(data.get("error"), dict) else {}
            message = err.get("message") or f"xAI video request {status}."
            code = err.get("code")
            raise RuntimeError(f"xAI video failed [{code}]: {message}" if code else str(message))
        time.sleep(5)
    raise TimeoutError("xAI video generation timed out.")


def segment_prompt(prompt: str, index: int, total: int) -> str:
    if total <= 1:
        return prompt
    return (
        f"{prompt}\n\n"
        f"Segment {index} of {total}: keep the same setting, subjects, style, camera language, and motion continuity."
    )


def xai_generate_video(prompt: str, aspect: str, seconds: object, model: str, key: str,
                       start_image: object = "", on_progress=None) -> dict[str, Any]:
    duration = clamp_int(seconds, 5, 1, XAI_MAX_STITCHED_SECONDS)
    if duration <= XAI_MAX_SECONDS_PER_REQUEST:
        return xai_public_video_result(
            xai_generate_video_clip(prompt, aspect, duration, model, key, start_image, on_progress)
        )

    remaining = duration
    segment_lengths: list[int] = []
    while remaining > 0:
        segment = min(XAI_MAX_SECONDS_PER_REQUEST, remaining)
        segment_lengths.append(segment)
        remaining -= segment

    clips: list[dict[str, Any]] = []
    total = len(segment_lengths)
    for index, segment in enumerate(segment_lengths, start=1):
        def segment_progress(status: str, progress: object, idx=index, total_segments=total) -> None:
            if on_progress:
                on_progress(f"segment {idx}/{total_segments}: {status}", progress)

        clips.append(xai_generate_video_clip(
            segment_prompt(prompt, index, total),
            aspect,
            segment,
            model,
            key,
            start_image if index == 1 else "",
            on_progress=segment_progress,
        ))

    paths = [Path(str(clip.get("mp4Path") or "")) for clip in clips if clip.get("mp4Path")]
    combined_url = concat_mp4_paths_to_webm(paths)
    if not combined_url:
        raise RuntimeError("Grok generated the video segments, but ImagineAI could not stitch them into one file.")
    return {
        "url": combined_url,
        "type": "video",
        "segments": [xai_public_video_result(clip) for clip in clips],
    }


# --------------------------------------------------------------------------- #
# Atlas Cloud image generation
# --------------------------------------------------------------------------- #
class AtlasHTTPError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"Atlas API error {code}: {message}")
        self.code = code
        self.message = message


class AtlasModelAccessError(RuntimeError):
    def __init__(self, model_id: str, message: str) -> None:
        super().__init__(message)
        self.model_id = model_id


def atlas_request_json(path: str, key: str, payload: dict[str, Any] | None = None,
                       method: str = "GET", timeout: float = 120) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{ATLAS_BASE}{path}", data=body, method=method)
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("User-Agent", "ImagineAI/1.0")
    if payload is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8") or "{}"
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        message = detail[:500]
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict):
                err = parsed.get("error")
                if isinstance(err, dict):
                    message = str(err.get("message") or err.get("code") or message)
                else:
                    message = str(parsed.get("message") or parsed.get("msg") or parsed.get("detail") or err or message)
        except (json.JSONDecodeError, TypeError):
            pass
        raise AtlasHTTPError(exc.code, message) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Atlas API: {exc.reason}") from exc
    return json.loads(raw)


def atlas_data(data: dict[str, Any]) -> dict[str, Any]:
    nested = data.get("data")
    return nested if isinstance(nested, dict) else data


def atlas_prediction_id(data: dict[str, Any]) -> str:
    body = atlas_data(data)
    request_id = str(body.get("id") or body.get("request_id") or body.get("prediction_id") or "").strip()
    if not request_id:
        raise RuntimeError("Atlas did not return a prediction id.")
    return request_id


def atlas_extract_outputs(data: dict[str, Any]) -> list[str]:
    body = atlas_data(data)
    urls: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        if isinstance(value, dict):
            for key in ("url", "output", "image", "image_url", "src"):
                if value.get(key):
                    add(value.get(key))
            return
        candidate = str(value or "").strip()
        if not candidate or candidate in seen:
            return
        seen.add(candidate)
        urls.append(candidate)

    outputs = body.get("outputs") or body.get("output") or body.get("urls") or body.get("url")
    if isinstance(outputs, list):
        for item in outputs:
            add(item)
    elif isinstance(outputs, dict):
        for item in outputs.values():
            add(item)
    else:
        add(outputs)
    return urls


def atlas_poll_result(request_id: str, key: str, on_progress=None,
                      timeout: float | None = None, interval: float = 2) -> dict[str, Any]:
    deadline = now() + (timeout if timeout is not None else ATLAS_IMAGE_TIMEOUT)
    use_result_endpoint = False
    last_status = "running"
    while now() < deadline:
        path = "/model/result/" if use_result_endpoint else "/model/prediction/"
        try:
            data = atlas_request_json(f"{path}{urllib.parse.quote(request_id)}", key, timeout=120)
        except AtlasHTTPError as exc:
            if exc.code == 404 and not use_result_endpoint:
                use_result_endpoint = True
                continue
            raise
        body = atlas_data(data)
        status = str(body.get("status") or "").lower()
        last_status = status or last_status
        if on_progress:
            on_progress(last_status)
        if status in ("completed", "succeeded", "success", "done") or (not status and atlas_extract_outputs(data)):
            if atlas_extract_outputs(data):
                return data
            raise RuntimeError("Atlas image finished without an output URL.")
        if status in ("failed", "failure", "error", "cancelled", "canceled"):
            raise RuntimeError(str(body.get("error") or body.get("message") or f"Atlas request {status}."))
        time.sleep(interval)
    raise TimeoutError("Atlas generation timed out.")


def atlas_generate_image(prompt: str, aspect: str, count: int, model: str, key: str, on_progress=None) -> list[str]:
    requested = clamp_int(count, 1, 1, 4)
    model_id = model or DEFAULT_ATLAS_IMAGE_MODEL
    urls: list[str] = []
    for index in range(requested):
        payload = {
            "model": model_id,
            "prompt": prompt,
        }
        if requested > 1 and on_progress:
            on_progress(f"submitting {index + 1}/{requested}")
        started = atlas_request_json("/model/generateImage", key, payload, method="POST", timeout=120)
        request_id = atlas_prediction_id(started)
        result = atlas_poll_result(request_id, key, on_progress=on_progress, timeout=ATLAS_IMAGE_TIMEOUT, interval=2)
        for remote in atlas_extract_outputs(result):
            if remote.startswith("data:") and "," in remote:
                header, b64 = remote.split(",", 1)
                ext = ".jpg" if "jpeg" in header or "jpg" in header else ".png"
                try:
                    raw = base64.b64decode(b64, validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise RuntimeError("Atlas returned image data that could not be decoded.") from exc
                url, _, _ = save_output_bytes("atlas_image", raw, ext)
            elif remote.startswith(("http://", "https://")):
                url, _, _ = download_url_to_output(remote, "atlas_image", ".png", timeout=600)
            else:
                continue
            urls.append(url)
            break
    if not urls:
        raise RuntimeError("Atlas returned no image data. Try a different prompt or model.")
    return urls[:requested]


def atlas_upload_media(data_url: object, key: str, original_name: object = "") -> str:
    ext, raw = decode_image_data_url(data_url)
    mime = "image/jpeg" if ext == "jpg" else f"image/{ext}"
    fallback_name = f"start.{ext}"
    filename = safe_download_name(original_name, fallback_name)
    if "." not in filename:
        filename = f"{filename}.{ext}"
    boundary = f"----ImagineAIAtlas{uuid.uuid4().hex}"
    chunks = [
        f"--{boundary}\r\n".encode("utf-8"),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"),
        f"Content-Type: {mime}\r\n\r\n".encode("utf-8"),
        raw,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    req = urllib.request.Request(f"{ATLAS_BASE}/model/uploadMedia", data=b"".join(chunks), method="POST")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=240) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise AtlasHTTPError(exc.code, detail[:500]) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not upload media to Atlas: {exc.reason}") from exc
    body = atlas_data(data)
    url = str(body.get("url") or body.get("image_url") or body.get("media_url") or "").strip()
    if not url:
        raise RuntimeError("Atlas media upload did not return a URL.")
    return url


def atlas_video_model_id(model: str, has_start_image: bool) -> str:
    raw = (model or "").strip() or DEFAULT_ATLAS_VIDEO_MODEL
    legacy_aliases = {
        "kling": DEFAULT_ATLAS_I2V_MODEL if has_start_image else DEFAULT_ATLAS_VIDEO_MODEL,
        "kling-v2.0": DEFAULT_ATLAS_I2V_MODEL if has_start_image else DEFAULT_ATLAS_VIDEO_MODEL,
        "kling-v2": DEFAULT_ATLAS_I2V_MODEL if has_start_image else DEFAULT_ATLAS_VIDEO_MODEL,
        "wan-2.7": DEFAULT_ATLAS_I2V_MODEL if has_start_image else DEFAULT_ATLAS_VIDEO_MODEL,
        "wan2.7": DEFAULT_ATLAS_I2V_MODEL if has_start_image else DEFAULT_ATLAS_VIDEO_MODEL,
        "wan 2.7": DEFAULT_ATLAS_I2V_MODEL if has_start_image else DEFAULT_ATLAS_VIDEO_MODEL,
        "alibaba/wan-2.7": DEFAULT_ATLAS_I2V_MODEL if has_start_image else DEFAULT_ATLAS_VIDEO_MODEL,
    }
    model_id = legacy_aliases.get(raw.lower(), raw)
    if has_start_image and model_id == DEFAULT_ATLAS_VIDEO_MODEL:
        return DEFAULT_ATLAS_I2V_MODEL
    if has_start_image and model_id.endswith("/text-to-video"):
        return f"{model_id.rsplit('/', 1)[0]}/image-to-video"
    if not has_start_image and model_id.endswith("/image-to-video"):
        return f"{model_id.rsplit('/', 1)[0]}/text-to-video"
    return model_id


def atlas_video_aspect(aspect: str) -> str:
    return {"wide": "16:9", "tall": "9:16", "square": "1:1"}.get(aspect, "")


def atlas_wan27_ratio(aspect: str) -> str:
    return ASPECT_TO_GEMINI.get(aspect, "16:9")


def atlas_wan27_resolution() -> str:
    value = str(DEFAULT_ATLAS_WAN27_RESOLUTION or "1080P").strip().upper()
    return value if value in ("720P", "1080P", "1080P-SR", "1440P-SR") else "1080P"


def atlas_wan27_negative_prompt() -> str:
    return str(DEFAULT_NEGATIVE_VIDEO or "")[:500]


def atlas_wan27_seed() -> int:
    return clamp_int(DEFAULT_ATLAS_WAN27_SEED, -1, -1, 2147483647)


def atlas_is_wan27_model(model_id: str) -> bool:
    return "/wan-2.7/" in (model_id or "").lower()


def atlas_public_video_result(result: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in result.items() if k != "mp4Path"}


def atlas_video_segment_lengths(seconds: object, model_id: str = "") -> list[int]:
    if atlas_is_wan27_model(model_id):
        remaining = clamp_int(seconds, 5, 2, ATLAS_MAX_STITCHED_SECONDS)
        segments: list[int] = []
        while remaining > 0:
            segment = min(ATLAS_WAN27_MAX_SECONDS_PER_REQUEST, remaining)
            if remaining - segment == 1:
                segment -= 1
            segments.append(segment)
            remaining -= segment
        return segments

    remaining = clamp_int(seconds, 5, 1, ATLAS_MAX_STITCHED_SECONDS)
    segments: list[int] = []
    while remaining > 0:
        if remaining > ATLAS_MAX_SECONDS_PER_REQUEST:
            segment = ATLAS_MAX_SECONDS_PER_REQUEST
        else:
            segment = 10 if remaining >= 8 else 5
        segments.append(segment)
        remaining -= segment
    return segments


def atlas_generate_video_clip(prompt: str, aspect: str, seconds: object, model: str, key: str,
                              start_image: object = "", start_image_name: object = "", on_progress=None) -> dict[str, Any]:
    has_start_image = isinstance(start_image, str) and bool(start_image.strip())
    model_id = atlas_video_model_id(model, has_start_image)
    payload: dict[str, Any] = {
        "model": model_id,
        "prompt": prompt,
    }
    payload["duration"] = atlas_video_segment_lengths(seconds, model_id)[0]
    if atlas_is_wan27_model(model_id):
        payload.update({
            "negative_prompt": atlas_wan27_negative_prompt(),
            "resolution": atlas_wan27_resolution(),
            "ratio": atlas_wan27_ratio(aspect),
            "prompt_extend": DEFAULT_ATLAS_WAN27_PROMPT_EXTEND,
            "seed": atlas_wan27_seed(),
        })
        audio = str(DEFAULT_ATLAS_WAN27_AUDIO or "").strip()
        if audio:
            payload["audio"] = audio
    else:
        aspect_ratio = atlas_video_aspect(aspect)
        if aspect_ratio and not has_start_image:
            payload["aspect_ratio"] = aspect_ratio
    if has_start_image:
        if on_progress:
            on_progress("uploading image")
        payload["image"] = atlas_upload_media(start_image, key, start_image_name)
    try:
        started = atlas_request_json("/model/generateVideo", key, payload, method="POST", timeout=120)
    except AtlasHTTPError as exc:
        if exc.code == 403:
            reason = str(exc.message or "").strip()
            if "coding plan" in reason.lower() and "not support" in reason.lower():
                detail = (
                    f"Atlas returned 403 for {model_id}: this Atlas Coding Plan token does not support video generation. "
                    "There is no Atlas video model this token can use here; add a full Atlas Cloud API key/plan, "
                    "or use ModelsLab, xAI, or local Wan for video."
                )
            else:
                detail = (
                    f"Atlas rejected video generation with 403 for model {model_id}. "
                    "Check Atlas credits/model access, or try another Atlas video model in Settings."
                )
            if reason:
                detail = f"{detail} Atlas said: {reason}"
            raise AtlasModelAccessError(
                model_id,
                detail,
            ) from exc
        raise
    request_id = atlas_prediction_id(started)
    result = atlas_poll_result(request_id, key, on_progress=on_progress, timeout=ATLAS_VIDEO_TIMEOUT, interval=5)
    outputs = atlas_extract_outputs(result)
    remote_url = next((url for url in outputs if url.startswith(("http://", "https://"))), "")
    if not remote_url:
        raise RuntimeError("Atlas video finished without a downloadable video URL.")
    mp4_url, mp4_path, _ = download_url_to_output(remote_url, "atlas_video", ".mp4", timeout=900)
    webm_url = transcode_mp4_path_to_webm(mp4_path)
    return {"url": webm_url or mp4_url, "type": "video", "mp4Url": mp4_url, "mp4Path": str(mp4_path), "model": model_id}


def atlas_generate_video_with_model(prompt: str, aspect: str, seconds: object, model_id: str, key: str,
                                    start_image: object = "", start_image_name: object = "", on_progress=None) -> dict[str, Any]:
    segment_lengths = atlas_video_segment_lengths(seconds, model_id)
    if len(segment_lengths) == 1:
        return atlas_public_video_result(
            atlas_generate_video_clip(prompt, aspect, segment_lengths[0], model_id, key, start_image, start_image_name, on_progress)
        )

    clips: list[dict[str, Any]] = []
    total = len(segment_lengths)
    for index, segment in enumerate(segment_lengths, start=1):
        def segment_progress(status: str, idx=index, total_segments=total) -> None:
            if on_progress:
                on_progress(f"segment {idx}/{total_segments}: {status}")

        clips.append(atlas_generate_video_clip(
            segment_prompt(prompt, index, total),
            aspect,
            segment,
            model_id,
            key,
            start_image if index == 1 else "",
            start_image_name if index == 1 else "",
            on_progress=segment_progress,
        ))

    paths = [Path(str(clip.get("mp4Path") or "")) for clip in clips if clip.get("mp4Path")]
    combined_url = concat_mp4_paths_to_webm(paths)
    if not combined_url:
        raise RuntimeError("Atlas generated the video segments, but ImagineAI could not stitch them into one file.")
    return {
        "url": combined_url,
        "type": "video",
        "model": clips[0].get("model") or model_id,
        "segments": [atlas_public_video_result(clip) for clip in clips],
    }


def atlas_generate_video(prompt: str, aspect: str, seconds: object, model: str, key: str,
                         start_image: object = "", start_image_name: object = "", on_progress=None) -> dict[str, Any]:
    has_start_image = isinstance(start_image, str) and bool(start_image.strip())
    model_id = atlas_video_model_id(model, has_start_image)
    return atlas_generate_video_with_model(
        prompt, aspect, seconds, model_id, key,
        start_image=start_image,
        start_image_name=start_image_name,
        on_progress=on_progress,
    )


# --------------------------------------------------------------------------- #
# Stability / SDXL-compatible cloud image generation
# --------------------------------------------------------------------------- #
def multipart_form_data(fields: dict[str, object]) -> tuple[bytes, str]:
    boundary = f"----ImagineAI{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        if value is None or value == "":
            continue
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def stability_endpoint(model: str) -> tuple[str, str]:
    normalized = model.strip().lower().replace("_", "-") or "core"
    aliases = {
        "stable-image-core": "core",
        "stable-core": "core",
        "sdxl": "core",
        "stable-diffusion-xl": "core",
        "stable-image-ultra": "ultra",
        "sd3": "sd3",
        "sd3.5": "sd3",
        "stable-diffusion-3.5": "sd3",
        "stable-diffusion-3": "sd3",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"core", "sd3", "ultra"}:
        normalized = "core"
    titles = {
        "core": "Stable Image Core",
        "sd3": "Stable Diffusion 3.5",
        "ultra": "Stable Image Ultra",
    }
    return f"/v2beta/stable-image/generate/{normalized}", titles[normalized]


def stability_request_image(path: str, key: str, fields: dict[str, object], timeout: float = 240) -> bytes:
    body, content_type = multipart_form_data(fields)
    req = urllib.request.Request(f"{STABILITY_BASE}{path}", data=body, method="POST")
    token = key.strip()
    if token.lower().startswith("bearer "):
        token = token.split(None, 1)[1].strip()
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "image/*")
    req.add_header("Content-Type", content_type)
    req.add_header("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 ImagineAI/1.0")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            finish = response.headers.get("finish-reason", "")
            if finish and finish.upper() != "SUCCESS":
                raise RuntimeError(f"Stability finished with {finish}.")
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        message = detail[:500]
        try:
            parsed = json.loads(detail)
            errors = parsed.get("errors") if isinstance(parsed, dict) else None
            if isinstance(errors, list) and errors:
                message = "; ".join(str(e) for e in errors[:3])
            elif isinstance(parsed, dict) and parsed.get("message"):
                message = str(parsed["message"])
        except (json.JSONDecodeError, TypeError):
            if "<html" in detail.lower() or "<!doctype html" in detail.lower():
                message = (
                    "Stability returned an HTML block page. "
                    "Restart ImagineAI so the updated request headers are used, then try again."
                )
        if exc.code == 401:
            message = (
                "Stability rejected the API key. Use a Stability Platform API key from "
                "https://platform.stability.ai/account/keys, not a model name or another provider's SDXL key."
            )
        raise RuntimeError(f"Stability API error {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Stability API: {exc.reason}") from exc


def stability_generate_image(prompt: str, aspect: str, count: int, model: str, key: str) -> tuple[list[str], str]:
    path, title = stability_endpoint(model)
    fields = {
        "prompt": prompt,
        "aspect_ratio": ASPECT_TO_STABILITY.get(aspect, "1:1"),
        "output_format": "png",
    }
    urls: list[str] = []
    for _ in range(clamp_int(count, 1, 1, 4)):
        raw = stability_request_image(path, key, fields)
        url, _, _ = save_output_bytes("stability_image", raw, ".png")
        urls.append(url)
    return urls, title


# --------------------------------------------------------------------------- #
# ModelsLab image + video generation
# --------------------------------------------------------------------------- #
class ModelsLabHTTPError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"ModelsLab API error {code}: {message}")
        self.code = code
        self.message = message


def modelslab_payload_is_result(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    status = str(data.get("status") or "").lower()
    if status in ("error", "failed", "failure"):
        return False
    has_url = any(bool(data.get(key)) for key in ("output", "proxy_links", "future_links"))
    has_request_id = bool(data.get("id") or data.get("request_id"))
    return status in ("success", "processing", "queued", "pending") and (has_url or has_request_id)


def modelslab_request_json(path: str, payload: dict[str, Any], timeout: float = 120) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"{MODELSLAB_BASE}{path}", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "ImagineAI/1.0")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        message = detail[:500]
        try:
            parsed = json.loads(detail)
            if isinstance(parsed, dict):
                if modelslab_payload_is_result(parsed):
                    return parsed
                message = str(parsed.get("message") or parsed.get("messege")
                              or parsed.get("error") or parsed.get("errors") or message)
        except (json.JSONDecodeError, TypeError):
            pass
        if exc.code == 403 and message.lower() in ("forbidden", "403 forbidden"):
            message = "Feature not available on your current ModelsLab plan."
        raise ModelsLabHTTPError(exc.code, message) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach ModelsLab API: {exc.reason}") from exc


def modelslab_error(data: dict[str, Any]) -> str:
    message = (
        data.get("message") or data.get("messege") or data.get("error")
        or data.get("errors") or data.get("tip") or "ModelsLab request failed."
    )
    if isinstance(message, list):
        message = "; ".join(str(item) for item in message)
    if isinstance(message, dict):
        message = message.get("message") or message.get("error") or json.dumps(message, ensure_ascii=False)
    return str(message)


def modelslab_plan_error(feature: str) -> RuntimeError:
    return RuntimeError(
        f"ModelsLab says {feature} is not available on your current plan. "
        "Try the ModelsLab dashboard/playground with the same key, or upgrade/enable that feature."
    )


def modelslab_extract_urls(data: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        candidate = str(value or "").strip()
        if not candidate or not candidate.startswith(("http://", "https://")) or candidate in seen:
            return
        seen.add(candidate)
        urls.append(candidate)

    for key in ("output", "proxy_links", "future_links"):
        values = data.get(key)
        if isinstance(values, list):
            for value in values:
                add(value)
        elif isinstance(values, dict):
            for value in values.values():
                add(value)
        elif isinstance(values, str):
            add(values)
    return urls


def modelslab_fetch_image(request_id: object, key: str) -> dict[str, Any]:
    request_id_path = urllib.parse.quote(str(request_id))
    return modelslab_request_json(f"/api/v6/images/fetch/{request_id_path}", {"key": key}, timeout=120)


def modelslab_fetch_realtime_image(request_id: object, key: str) -> dict[str, Any]:
    return modelslab_request_json(f"/api/v6/realtime/fetch/{urllib.parse.quote(str(request_id))}", {"key": key}, timeout=120)


def modelslab_wait_for_image(data: dict[str, Any], key: str, realtime: bool = False) -> dict[str, Any]:
    status = str(data.get("status") or "").lower()
    if status == "success" and modelslab_extract_urls(data):
        return data
    if status in ("error", "failed", "failure"):
        raise RuntimeError(modelslab_error(data))
    request_id = data.get("id") or data.get("request_id")
    if not request_id:
        raise RuntimeError(modelslab_error(data))
    deadline = now() + COMFY_IMAGE_TIMEOUT
    while now() < deadline:
        time.sleep(4)
        fetched = modelslab_fetch_realtime_image(request_id, key) if realtime else modelslab_fetch_image(request_id, key)
        status = str(fetched.get("status") or "").lower()
        if status == "success" and modelslab_extract_urls(fetched):
            return fetched
        if status in ("error", "failed", "failure"):
            raise RuntimeError(modelslab_error(fetched))
    raise TimeoutError("ModelsLab image generation timed out.")


def modelslab_generate_image(prompt: str, aspect: str, count: int, model: str, key: str) -> tuple[list[str], str]:
    width, height = ASPECT_TO_MODELSLAB_IMAGE_SIZE.get(aspect, (768, 768))
    model_id = model or DEFAULT_MODELSLAB_IMAGE_MODEL
    requested = clamp_int(count, 1, 1, 4)

    def download_results(data: dict[str, Any], prefix: str) -> list[str]:
        urls: list[str] = []
        for remote_url in modelslab_extract_urls(data)[:requested]:
            url, _, _ = download_url_to_output(remote_url, prefix, ".png", timeout=300)
            urls.append(url)
        if not urls:
            raise RuntimeError("ModelsLab returned no image URL.")
        return urls

    def realtime_image() -> tuple[list[str], str]:
        rt_width, rt_height = ASPECT_TO_MODELSLAB_VIDEO_SIZE.get(aspect, (512, 512))
        rt_payload = {
            "key": key,
            "prompt": prompt,
            "negative_prompt": DEFAULT_NEGATIVE_IMAGE,
            "width": rt_width,
            "height": rt_height,
            "samples": requested,
            "safety_checker": False,
            "seed": None,
            "instant_response": False,
            "base64": False,
            "webhook": None,
            "track_id": None,
        }
        rt_data = modelslab_wait_for_image(
            modelslab_request_json("/api/v6/realtime/text2img", rt_payload, timeout=240),
            key,
            realtime=True,
        )
        return download_results(rt_data, "modelslab_realtime_image"), "realtime"

    if model_id.strip().lower() in ("realtime", "fast", "real-time"):
        return realtime_image()

    payload = {
        "key": key,
        "prompt": prompt,
        "model_id": model_id,
        "negative_prompt": DEFAULT_NEGATIVE_IMAGE,
        "width": width,
        "height": height,
        "samples": requested,
        "num_inference_steps": 25,
        "guidance_scale": 7.5,
        "safety_checker": False,
        "base64": False,
        "temp": False,
        "webhook": None,
        "track_id": None,
    }
    try:
        data = modelslab_wait_for_image(
            modelslab_request_json("/api/v6/images/text2img", payload, timeout=240),
            key,
        )
        return download_results(data, "modelslab_image"), model_id
    except ModelsLabHTTPError as exc:
        if exc.code != 403:
            raise
        urls, fallback = realtime_image()
        return urls, f"{fallback} (fallback from {model_id})"


def modelslab_fetch_video(request_id: object, key: str) -> dict[str, Any]:
    return modelslab_request_json(f"/api/v6/video/fetch/{urllib.parse.quote(str(request_id))}", {"key": key}, timeout=120)


def modelslab_public_video_result(result: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in result.items() if k != "mp4Path"}


def modelslab_generate_video_clip(prompt: str, aspect: str, seconds: object, model: str, key: str,
                                  on_progress=None) -> dict[str, Any]:
    width, height = ASPECT_TO_MODELSLAB_VIDEO_SIZE.get(aspect, (512, 512))
    duration = clamp_int(seconds, 2, 1, 5)
    fps = 16
    frames = max(16, min(25, duration * fps))
    payload = {
        "key": key,
        "model_id": model or DEFAULT_MODELSLAB_VIDEO_MODEL,
        "prompt": prompt,
        "negative_prompt": DEFAULT_NEGATIVE_VIDEO,
        "height": height,
        "width": width,
        "num_frames": frames,
        "num_inference_steps": 20,
        "guidance_scale": 7,
        "fps": fps,
        "output_type": "mp4",
        "instant_response": False,
        "temp": False,
        "webhook": None,
        "track_id": None,
    }
    try:
        data = modelslab_request_json("/api/v6/video/text2video", payload, timeout=240)
    except ModelsLabHTTPError as exc:
        if exc.code == 403:
            raise modelslab_plan_error("text-to-video") from exc
        raise
    status = str(data.get("status") or "").lower()
    if status == "success" and modelslab_extract_urls(data):
        remote_url = modelslab_extract_urls(data)[0]
    else:
        if status in ("error", "failed", "failure"):
            raise RuntimeError(modelslab_error(data))
        request_id = data.get("id") or data.get("request_id")
        if not request_id:
            raise RuntimeError(modelslab_error(data))
        deadline = now() + XAI_VIDEO_TIMEOUT
        remote_url = ""
        while now() < deadline:
            if on_progress:
                on_progress("processing", data.get("eta"))
            time.sleep(5)
            data = modelslab_fetch_video(request_id, key)
            status = str(data.get("status") or "").lower()
            if status == "success" and modelslab_extract_urls(data):
                remote_url = modelslab_extract_urls(data)[0]
                break
            if status in ("error", "failed", "failure"):
                raise RuntimeError(modelslab_error(data))
        if not remote_url:
            raise TimeoutError("ModelsLab video generation timed out.")
    mp4_url, mp4_path, _ = download_url_to_output(remote_url, "modelslab_video", ".mp4", timeout=600)
    webm_url = transcode_mp4_path_to_webm(mp4_path)
    return {"url": webm_url or mp4_url, "type": "video", "mp4Url": mp4_url, "mp4Path": str(mp4_path)}


def modelslab_generate_video(prompt: str, aspect: str, seconds: object, model: str, key: str,
                             on_progress=None) -> dict[str, Any]:
    duration = clamp_int(seconds, 2, 1, MODELSLAB_MAX_STITCHED_SECONDS)
    if duration <= 5:
        return modelslab_public_video_result(
            modelslab_generate_video_clip(prompt, aspect, duration, model, key, on_progress)
        )

    remaining = duration
    segment_lengths: list[int] = []
    while remaining > 0:
        segment = min(5, remaining)
        segment_lengths.append(segment)
        remaining -= segment

    clips: list[dict[str, Any]] = []
    total = len(segment_lengths)
    for index, segment in enumerate(segment_lengths, start=1):
        def segment_progress(status: str, progress: object, idx=index, total_segments=total) -> None:
            if on_progress:
                on_progress(f"segment {idx}/{total_segments}: {status}", progress)

        clips.append(modelslab_generate_video_clip(
            segment_prompt(prompt, index, total),
            aspect,
            segment,
            model,
            key,
            on_progress=segment_progress,
        ))

    paths = [Path(str(clip.get("mp4Path") or "")) for clip in clips if clip.get("mp4Path")]
    combined_url = concat_mp4_paths_to_webm(paths)
    if not combined_url:
        raise RuntimeError("ModelsLab generated the video segments, but ImagineAI could not stitch them into one file.")
    return {
        "url": combined_url,
        "type": "video",
        "segments": [modelslab_public_video_result(clip) for clip in clips],
    }


# --------------------------------------------------------------------------- #
# Job runners
# --------------------------------------------------------------------------- #
def make_job(kind: str) -> str:
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id, "kind": kind, "status": "queued",
            "createdAt": now(), "updatedAt": now(), "results": [], "error": None, "meta": {},
        }
    return job_id


def update_job(job_id: str, **values: Any) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job:
            job.update(values)
            job["updatedAt"] = now()


def get_job(job_id: str) -> dict[str, Any] | None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        return dict(job) if job else None


def run_image_job(job_id: str, payload: dict[str, Any]) -> None:
    prompt = str(payload.get("prompt", "")).strip()
    engine = str(payload.get("engine") or "local").lower()
    aspect = str(payload.get("aspect") or "square")
    count = clamp_int(payload.get("count"), 1, 1, 4)
    source_image = payload.get("sourceImage") or ""
    source_image_name = payload.get("sourceImageName") or ""
    settings = load_settings()
    try:
        if engine == "gemini":
            update_job(job_id, status="running", meta={"engine": "gemini"})
            key = gemini_key()
            if not key:
                raise RuntimeError("No Gemini API key saved. Add one in Settings.")
            model = str(payload.get("geminiModel") or settings.get("geminiModel") or DEFAULT_GEMINI_MODEL)
            urls: list[str] = []
            for _ in range(count):
                if len(urls) >= count:
                    break
                urls.extend(gemini_generate_image(prompt, aspect, model, key, source_image=source_image))
            urls = urls[:count]  # never return more than requested
            update_job(job_id, status="done",
                       results=[{"url": u, "type": "image"} for u in urls],
                       meta={"engine": "gemini", "modelTitle": model})
            return

        if engine == "xai":
            model = str(payload.get("xaiImageModel") or settings.get("xaiImageModel") or DEFAULT_XAI_IMAGE_MODEL)
            update_job(job_id, status="running", meta={"engine": "xai", "modelTitle": model})
            key = xai_key()
            if not key:
                raise RuntimeError("No xAI API key saved. Add one in Settings.")
            urls = xai_generate_image(prompt, aspect, count, model, key, source_image=source_image)[:count]
            update_job(job_id, status="done",
                       results=[{"url": u, "type": "image"} for u in urls],
                       meta={"engine": "xai", "modelTitle": "Grok Imagine", "model": model})
            return

        if engine in ("atlas", "atlascloud", "atlas-cloud"):
            if isinstance(source_image, str) and source_image.strip():
                raise RuntimeError("Atlas image reference uploads are not wired for this image engine yet. Use Z-Image, Gemini, or Grok Imagine for image edits.")
            model = str(payload.get("atlasImageModel") or settings.get("atlasImageModel") or DEFAULT_ATLAS_IMAGE_MODEL)
            key, provider = atlas_key()
            update_job(job_id, status="running", meta={"engine": "atlas", "modelTitle": model, "provider": provider})
            if not key:
                raise RuntimeError("No Atlas API key saved. Add one in Settings as atlas or atlascloud.")

            def on_atlas_progress(status: str) -> None:
                update_job(job_id, status="running",
                           meta={"engine": "atlas", "modelTitle": model, "atlasStatus": status,
                                 "provider": provider})

            urls = atlas_generate_image(prompt, aspect, count, model, key, on_progress=on_atlas_progress)
            update_job(job_id, status="done",
                       results=[{"url": u, "type": "image"} for u in urls],
                       meta={"engine": "atlas", "modelTitle": f"Atlas {model}",
                             "model": model, "provider": provider})
            return

        if engine in ("sdxl", "stability", "stability-ai"):
            if isinstance(source_image, str) and source_image.strip():
                raise RuntimeError("SDXL reference uploads are not wired for this image engine yet. Use Z-Image, Gemini, or Grok Imagine for image edits.")
            key, provider = modelslab_key()
            if key:
                model = str(payload.get("modelslabImageModel") or settings.get("modelslabImageModel")
                            or DEFAULT_MODELSLAB_IMAGE_MODEL)
                update_job(job_id, status="running", meta={"engine": "modelslab", "modelTitle": model})
                urls, title = modelslab_generate_image(prompt, aspect, count, model, key)
                update_job(job_id, status="done",
                           results=[{"url": u, "type": "image"} for u in urls],
                           meta={"engine": "modelslab", "modelTitle": f"ModelsLab {title}",
                                 "model": model, "provider": provider})
                return

            model = str(payload.get("stabilityImageModel") or settings.get("stabilityImageModel")
                        or DEFAULT_STABILITY_IMAGE_MODEL)
            key, provider = stability_key()
            update_job(job_id, status="running", meta={"engine": "sdxl", "modelTitle": model})
            if not key:
                raise RuntimeError("No SDXL provider key saved. Add a ModelsLab key as sdxl/modelslab or a Stability key as stability.")
            urls, title = stability_generate_image(prompt, aspect, count, model, key)
            update_job(job_id, status="done",
                       results=[{"url": u, "type": "image"} for u in urls],
                       meta={"engine": "sdxl", "modelTitle": title, "model": model, "provider": provider})
            return

        if engine in ("modelslab", "models-lab", "stable-diffusion-api"):
            if isinstance(source_image, str) and source_image.strip():
                raise RuntimeError("ModelsLab reference uploads are not wired for this image engine yet. Use Z-Image, Gemini, or Grok Imagine for image edits.")
            model = str(payload.get("modelslabImageModel") or settings.get("modelslabImageModel")
                        or DEFAULT_MODELSLAB_IMAGE_MODEL)
            key, provider = modelslab_key()
            update_job(job_id, status="running", meta={"engine": "modelslab", "modelTitle": model})
            if not key:
                raise RuntimeError("No ModelsLab API key saved. Add one in Settings as modelslab or sdxl.")
            urls, title = modelslab_generate_image(prompt, aspect, count, model, key)
            update_job(job_id, status="done",
                       results=[{"url": u, "type": "image"} for u in urls],
                       meta={"engine": "modelslab", "modelTitle": f"ModelsLab {title}",
                             "model": model, "provider": provider})
            return

        # local Z-Image Turbo
        width, height = ASPECT_TO_SIZE.get(aspect, (1024, 1024))
        comfy_source_image = save_source_image_for_comfy(source_image, source_image_name)
        graph = build_zimage_graph({
            "prompt": prompt,
            "negative_prompt": payload.get("negativePrompt", DEFAULT_NEGATIVE_IMAGE),
            "width": width, "height": height, "batch_size": count,
            "steps": payload.get("steps", 8), "cfg": payload.get("cfg", 1.0),
            "seed": payload.get("seed"),
            "source_image": comfy_source_image,
            "image_strength": payload.get("imageStrength", 0.65),
        })
        update_job(job_id, status="running", meta={"engine": "local", "modelTitle": "Z-Image Turbo"})
        with COMFY_LOCK:
            prompt_id = queue_comfy_prompt(graph, "imagineai-image")
            history = wait_for_history(prompt_id, COMFY_IMAGE_TIMEOUT,
                                       on_state=lambda s: update_job(job_id, status=s))
        err = extract_error(history)
        if err:
            raise RuntimeError(json.dumps(err, ensure_ascii=False))
        entries = extract_entries(history, "image")
        if not entries:
            raise RuntimeError("ComfyUI returned no image.")
        update_job(job_id, status="done",
                   results=[{"url": entry_to_media_url(e), "type": "image"} for e in entries],
                   meta={"engine": "local", "modelTitle": "Z-Image Turbo"})
    except Exception as exc:  # noqa: BLE001
        update_job(job_id, status="error", error=str(exc))


def run_video_job(job_id: str, payload: dict[str, Any]) -> None:
    prompt = str(payload.get("prompt", "")).strip()
    model = str(payload.get("model") or "wan22_14b")
    aspect = str(payload.get("aspect") or "wide")
    base_w, base_h = ASPECT_TO_SIZE.get(aspect, (1280, 720))
    settings = load_settings()
    try:
        if model in ("sdxl", "modelslab", "models-lab", "stable-diffusion-api"):
            modelslab_model = str(payload.get("modelslabVideoModel") or settings.get("modelslabVideoModel")
                                  or DEFAULT_MODELSLAB_VIDEO_MODEL)
            update_job(job_id, status="running",
                       meta={"engine": "modelslab", "modelTitle": "ModelsLab Video", "model": modelslab_model})
            key, provider = modelslab_key()
            if not key:
                raise RuntimeError("No ModelsLab API key saved. Add one in Settings as modelslab or sdxl.")

            def on_modelslab_progress(status: str, progress: object) -> None:
                update_job(job_id, status="running",
                           meta={"engine": "modelslab", "modelTitle": "ModelsLab Video",
                                 "model": modelslab_model, "modelslabStatus": status, "progress": progress,
                                 "provider": provider})

            result = modelslab_generate_video(
                prompt, aspect, payload.get("seconds"), modelslab_model, key,
                on_progress=on_modelslab_progress,
            )
            update_job(job_id, status="done", results=[result],
                       meta={"engine": "modelslab", "modelTitle": "ModelsLab Video", "model": modelslab_model,
                             "provider": provider})
            return

        if model in ("stability", "stability-ai"):
            raise RuntimeError("Stability image keys are available for images only here; use ModelsLab, xAI, or local Wan for video.")

        if model in ("atlas", "atlascloud", "atlas-cloud"):
            atlas_model = str(payload.get("atlasVideoModel") or settings.get("atlasVideoModel")
                              or DEFAULT_ATLAS_VIDEO_MODEL)
            key, provider = atlas_key()
            update_job(job_id, status="running",
                       meta={"engine": "atlas", "modelTitle": "Atlas Video", "model": atlas_model,
                             "provider": provider})
            if not key:
                raise RuntimeError("No Atlas API key saved. Add one in Settings as atlas or atlascloud.")

            def on_atlas_progress(status: str) -> None:
                update_job(job_id, status="running",
                           meta={"engine": "atlas", "modelTitle": "Atlas Video",
                                 "model": atlas_model, "atlasStatus": status, "provider": provider})

            result = atlas_generate_video(
                prompt, aspect, payload.get("seconds"), atlas_model, key,
                start_image=payload.get("startImage") or "",
                start_image_name=payload.get("startImageName") or "",
                on_progress=on_atlas_progress,
            )
            actual_atlas_model = str(result.get("model") or atlas_model)
            done_meta = {"engine": "atlas", "modelTitle": "Atlas Video", "model": actual_atlas_model,
                         "provider": provider}
            update_job(job_id, status="done", results=[result],
                       meta=done_meta)
            return

        if model == "xai":
            xai_model = str(payload.get("xaiVideoModel") or settings.get("xaiVideoModel") or DEFAULT_XAI_VIDEO_MODEL)
            update_job(job_id, status="running",
                       meta={"engine": "xai", "modelTitle": "Grok Imagine Video", "model": xai_model})
            key = xai_key()
            if not key:
                raise RuntimeError("No xAI API key saved. Add one in Settings.")

            def on_xai_progress(status: str, progress: object) -> None:
                update_job(job_id, status="running",
                           meta={"engine": "xai", "modelTitle": "Grok Imagine Video",
                                 "model": xai_model, "xaiStatus": status, "progress": progress})

            result = xai_generate_video(
                prompt, aspect, payload.get("seconds"), xai_model, key,
                payload.get("startImage"), on_progress=on_xai_progress,
            )
            update_job(job_id, status="done", results=[result],
                       meta={"engine": "xai", "modelTitle": "Grok Imagine Video", "model": xai_model})
            return

        common = {
            "prompt": prompt,
            "negative_prompt": payload.get("negativePrompt", DEFAULT_NEGATIVE_VIDEO),
            "seconds": payload.get("seconds"),
            "fps": payload.get("fps"),
            "seed": payload.get("seed"),
            "steps": payload.get("steps"),
            "cfg": payload.get("cfg"),
        }
        if model == "wan21_1_3b":
            # 1.3B is small — keep frames modest
            common.update({"width": payload.get("width", min(base_w, 480)),
                           "height": payload.get("height", min(base_h, 320))})
            graph = build_wan21_graph(common)
            title = "Wan 2.1 1.3B"
        elif model == "wan22_ti2v_5b":
            ti_w, ti_h = TI2V_ASPECT_TO_SIZE.get(aspect, (1280, 704))
            start_image = save_start_image_for_comfy(payload.get("startImage"), payload.get("startImageName"))
            common.update({"width": payload.get("width", ti_w),
                           "height": payload.get("height", ti_h),
                           "start_image": start_image})
            graph = build_wan22_ti2v_graph(common)
            title = "Wan 2.2 TI2V 5B"
        else:
            model = "wan22_14b"
            common.update({"width": payload.get("width", min(base_w, 768)),
                           "height": payload.get("height", min(base_h, 768))})
            graph = build_wan22_graph(common)
            title = "Wan 2.2 14B"
        update_job(job_id, status="running", meta={"engine": "local", "modelTitle": title, "model": model})
        with COMFY_LOCK:
            prompt_id = queue_comfy_prompt(graph, "imagineai-video")
            history = wait_for_history(prompt_id, COMFY_VIDEO_TIMEOUT,
                                       on_state=lambda s: update_job(job_id, status=s))
        err = extract_error(history)
        if err:
            raise RuntimeError(json.dumps(err, ensure_ascii=False))
        entries = extract_entries(history, "video")
        if not entries:
            raise RuntimeError("ComfyUI returned no video.")
        mp4_url = entry_to_media_url(entries[0])
        # The webview often can't decode H.264; transcode to VP9 webm for inline
        # playback, keep the mp4 for download. Falls back to mp4 if transcode fails.
        webm_url = transcode_entry_to_webm(entries[0])
        update_job(job_id, status="done",
                   results=[{"url": webm_url or mp4_url, "type": "video", "mp4Url": mp4_url}],
                   meta={"engine": "local", "modelTitle": title, "model": model})
    except Exception as exc:  # noqa: BLE001
        update_job(job_id, status="error", error=str(exc))


_TRANSCODE_SRC = r"""
import sys, av
src, dst = sys.argv[1], sys.argv[2]
inp = av.open(src)
ivs = inp.streams.video[0]
out = av.open(dst, 'w')
ovs = out.add_stream('libvpx-vp9', rate=ivs.average_rate or 16)
ovs.width = ivs.width
ovs.height = ivs.height
ovs.pix_fmt = 'yuv420p'
ovs.options = {'crf': '34', 'b:v': '0', 'deadline': 'realtime', 'cpu-used': '8', 'row-mt': '1'}
for frame in inp.decode(ivs):
    for pkt in ovs.encode(frame):
        out.mux(pkt)
for pkt in ovs.encode():
    out.mux(pkt)
out.close()
inp.close()
"""

_CONCAT_WEBM_SRC = r"""
import sys, av
dst, *srcs = sys.argv[1:]
if not srcs:
    raise SystemExit(2)
out = None
ovs = None
try:
    for src in srcs:
        inp = av.open(src)
        ivs = inp.streams.video[0]
        if out is None:
            out = av.open(dst, 'w')
            ovs = out.add_stream('libvpx-vp9', rate=ivs.average_rate or 16)
            ovs.width = ivs.width
            ovs.height = ivs.height
            ovs.pix_fmt = 'yuv420p'
            ovs.options = {'crf': '34', 'b:v': '0', 'deadline': 'realtime', 'cpu-used': '8', 'row-mt': '1'}
        for frame in inp.decode(ivs):
            frame = frame.reformat(width=ovs.width, height=ovs.height, format='yuv420p')
            frame.pts = None
            for pkt in ovs.encode(frame):
                out.mux(pkt)
        inp.close()
    for pkt in ovs.encode():
        out.mux(pkt)
finally:
    if out is not None:
        out.close()
"""


def transcode_mp4_path_to_webm(src_path: Path) -> str | None:
    """Re-encode a local mp4 to VP9 webm via ComfyUI's PyAV environment."""
    if not Path(COMFY_PYTHON).exists():
        return None
    name = f"video_{int(now())}_{uuid.uuid4().hex[:8]}.webm"
    out_path = OUTPUTS_DIR / name
    try:
        result = subprocess.run(
            [COMFY_PYTHON, "-c", _TRANSCODE_SRC, str(src_path), str(out_path)],
            capture_output=True, timeout=300,
        )
        if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            return None
        return output_url(name)
    except Exception:
        return None


def concat_mp4_paths_to_webm(src_paths: list[Path]) -> str | None:
    """Stitch local mp4 clips into one VP9 webm via ComfyUI's PyAV environment."""
    paths = [p for p in src_paths if p.exists() and p.is_file()]
    if len(paths) < 2 or not Path(COMFY_PYTHON).exists():
        return None
    name = f"video_{int(now())}_{uuid.uuid4().hex[:8]}.webm"
    out_path = OUTPUTS_DIR / name
    try:
        result = subprocess.run(
            [COMFY_PYTHON, "-c", _CONCAT_WEBM_SRC, str(out_path), *[str(p) for p in paths]],
            capture_output=True, timeout=900,
        )
        if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            return None
        return output_url(name)
    except Exception:
        return None


def transcode_entry_to_webm(entry: dict[str, Any]) -> str | None:
    """Fetch the mp4 ComfyUI produced and re-encode it to VP9 webm via ComfyUI's
    PyAV. Returns a /api/local-media URL, or None if transcoding isn't possible."""
    if not Path(COMFY_PYTHON).exists():
        return None
    params = urllib.parse.urlencode({
        "filename": entry.get("filename", ""),
        "subfolder": entry.get("subfolder", ""),
        "type": entry.get("type", "output"),
    })
    try:
        mp4_bytes, _ = comfy_get_bytes(f"/view?{params}", timeout=120)
    except Exception:
        return None
    tmp_mp4 = OUTPUTS_DIR / f".src_{uuid.uuid4().hex[:8]}.mp4"
    try:
        tmp_mp4.write_bytes(mp4_bytes)
        return transcode_mp4_path_to_webm(tmp_mp4)
    except Exception:
        return None
    finally:
        try:
            tmp_mp4.unlink(missing_ok=True)
        except OSError:
            pass


def start_job(kind: str, payload: dict[str, Any]) -> str:
    job_id = make_job(kind)
    runner = run_image_job if kind == "image" else run_video_job
    threading.Thread(target=runner, args=(job_id, payload), daemon=True).start()
    return job_id


# --------------------------------------------------------------------------- #
# HTTP layer
# --------------------------------------------------------------------------- #
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".ico": "image/x-icon",
    ".webm": "video/webm", ".mp4": "video/mp4", ".mov": "video/quicktime",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "ImagineAI/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter logs
        if os.environ.get("IMAGINEAI_VERBOSE"):
            super().log_message(fmt, *args)

    # -- response helpers --
    def _send(self, code: int, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def _send_media(self, body: bytes, content_type: str, extra: dict[str, str] | None = None) -> None:
        headers = {"Accept-Ranges": "bytes", **(extra or {})}
        range_header = self.headers.get("Range", "")
        if not range_header.startswith("bytes="):
            return self._send(200, body, content_type, headers)

        total = len(body)
        try:
            spec = range_header.removeprefix("bytes=").split(",", 1)[0].strip()
            start_s, _, end_s = spec.partition("-")
            if start_s:
                start = int(start_s)
                end = int(end_s) if end_s else total - 1
            else:
                suffix = int(end_s)
                start = max(0, total - suffix)
                end = total - 1
            if start < 0 or end < start or start >= total:
                raise ValueError
            end = min(end, total - 1)
        except (TypeError, ValueError):
            return self._send(416, b"", content_type, {"Content-Range": f"bytes */{total}", **headers})

        chunk = body[start:end + 1]
        return self._send(206, chunk, content_type, {
            **headers,
            "Content-Range": f"bytes {start}-{end}/{total}",
        })

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (ValueError, TypeError):
            length = 0
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return {}

    # -- routing --
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        try:
            if path == "/api/config":
                return self._json(200, self.api_config())
            if path == "/api/settings":
                return self._json(200, load_settings())
            if path == "/api/secrets":
                return self._json(200, self.api_secrets())
            if path.startswith("/api/jobs/"):
                return self.api_job(path.rsplit("/", 1)[-1])
            if path == "/api/comfy-view":
                return self.api_comfy_view(parsed.query)
            if path == "/api/local-media":
                return self.api_local_media(parsed.query)
            return self.serve_static(path)
        except ComfyUnavailable as exc:
            return self._json(503, {"error": str(exc)})
        except BrokenPipeError:
            return
        except Exception as exc:  # noqa: BLE001
            return self._json(500, {"error": str(exc)})

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        try:
            data = self._read_json()
            if path == "/api/settings":
                try:
                    return self._json(200, save_settings(data))
                except ValueError as exc:
                    return self._json(400, {"error": str(exc)})
            if path == "/api/secrets":
                provider = str(data.get("provider") or "gemini").lower()
                try:
                    save_secret(provider, str(data.get("key") or ""))
                except ValueError as exc:
                    return self._json(400, {"error": str(exc)})
                return self._json(200, self.api_secrets())
            if path == "/api/generate/image":
                if not str(data.get("prompt") or "").strip():
                    return self._json(400, {"error": "Prompt is required."})
                return self._json(200, {"jobId": start_job("image", data)})
            if path == "/api/generate/video":
                if not str(data.get("prompt") or "").strip():
                    return self._json(400, {"error": "Prompt is required."})
                return self._json(200, {"jobId": start_job("video", data)})
            return self._json(404, {"error": "Unknown endpoint"})
        except Exception as exc:  # noqa: BLE001
            return self._json(500, {"error": str(exc)})

    # -- API implementations --
    def api_config(self) -> dict[str, Any]:
        settings = load_settings()
        models = detect_models()
        atlas_value, atlas_provider = atlas_key()
        stability_value, stability_provider = stability_key()
        modelslab_value, modelslab_provider = modelslab_key()
        return {
            "comfyUrl": settings["comfyUrl"],
            "comfyReachable": models["reachable"],
            "models": models,
            "geminiConfigured": bool(gemini_key()),
            "geminiModel": settings["geminiModel"],
            "xaiConfigured": bool(xai_key()),
            "xaiImageModel": settings["xaiImageModel"],
            "xaiVideoModel": settings["xaiVideoModel"],
            "atlasConfigured": bool(atlas_value),
            "atlasProvider": atlas_provider if atlas_value else "",
            "atlasImageModel": settings["atlasImageModel"],
            "atlasVideoModel": settings["atlasVideoModel"],
            "sdxlConfigured": bool(stability_value or modelslab_value),
            "stabilityConfigured": bool(stability_value),
            "stabilityProvider": stability_provider if stability_value else "",
            "stabilityImageModel": settings["stabilityImageModel"],
            "modelslabConfigured": bool(modelslab_value),
            "modelslabProvider": modelslab_provider if modelslab_value else "",
            "modelslabImageModel": settings["modelslabImageModel"],
            "modelslabVideoModel": settings["modelslabVideoModel"],
            "defaultImageEngine": settings["defaultImageEngine"],
        }

    def api_secrets(self) -> dict[str, Any]:
        secrets = load_secrets()
        out = {}
        custom = []
        for provider in KNOWN_SECRET_PROVIDERS:
            env_value = os.environ.get(SECRET_ENV_KEYS[provider], "")
            if secrets.get(provider):
                out[provider] = secret_status(secrets[provider], "file")
            else:
                out[provider] = secret_status(env_value, "env")
        for provider in sorted(k for k in secrets if k not in KNOWN_SECRET_PROVIDERS):
            status = secret_status(secrets[provider], "file")
            out[provider] = status
            custom.append({"provider": provider, **status})
        return {"providers": out, "customProviders": custom}

    def api_job(self, job_id: str) -> None:
        job = get_job(job_id)
        if not job:
            return self._json(404, {"error": "Unknown job"})
        return self._json(200, {
            "id": job["id"], "status": job["status"], "kind": job["kind"],
            "results": job["results"], "error": job["error"], "meta": job.get("meta", {}),
            "elapsed": round(job["updatedAt"] - job["createdAt"], 1),
        })

    def api_comfy_view(self, query: str) -> None:
        params = urllib.parse.parse_qs(query)
        filename = params.get("filename", [""])[0]
        fwd = urllib.parse.urlencode({
            "filename": filename,
            "subfolder": params.get("subfolder", [""])[0],
            "type": params.get("type", ["output"])[0] or "output",
        })
        try:
            blob, ctype = comfy_get_bytes(f"/view?{fwd}", timeout=120)
        except Exception as exc:  # noqa: BLE001
            return self._json(502, {"error": f"Could not fetch media from ComfyUI: {exc}"})
        extra: dict[str, str] = {}
        download_name = params.get("downloadName", [""])[0]
        if download_name:
            extra["Content-Disposition"] = content_disposition_attachment(
                safe_download_name(download_name, Path(filename).name or "imagineai-media")
            )
        self._send_media(blob, ctype, extra)

    def api_local_media(self, query: str) -> None:
        params = urllib.parse.parse_qs(query)
        name = params.get("name", [""])[0]
        safe = Path(name).name  # strip any path components
        target = OUTPUTS_DIR / safe
        if not safe or not target.exists() or not target.is_file():
            return self._json(404, {"error": "Not found"})
        ctype = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        extra: dict[str, str] = {}
        download_name = params.get("downloadName", [""])[0]
        if download_name:
            extra["Content-Disposition"] = content_disposition_attachment(
                safe_download_name(download_name, target.name)
            )
        self._send_media(target.read_bytes(), ctype, extra)

    def serve_static(self, path: str) -> None:
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        target = (WEB_DIR / rel).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
            # SPA-style fallback to index for unknown non-API paths
            target = WEB_DIR / "index.html"
            if not target.is_file():
                return self._json(404, {"error": "Not found"})
        ctype = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)


def main() -> None:
    parser = argparse.ArgumentParser(description="ImagineAI — ComfyUI image & video studio")
    parser.add_argument("--host", default=os.environ.get("IMAGINEAI_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("IMAGINEAI_PORT", "8799")))
    parser.add_argument("--open", action="store_true", help="open the browser on start")
    args = parser.parse_args()

    ensure_dirs()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"ImagineAI running at {url}")
    print(
        f"  ComfyUI: {comfy_url()}   "
        f"Gemini: {'on' if gemini_key() else 'off'}   "
        f"xAI/Grok: {'on' if xai_key() else 'off'}"
    )
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
