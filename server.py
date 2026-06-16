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

# ComfyUI's Python (has PyAV) — used to transcode H.264 mp4 -> VP9 webm so the
# Linux webkit2gtk webview, which usually lacks an H.264 decoder, can play video
# inline. Best-effort: if unavailable we fall back to serving the mp4.
COMFY_PYTHON = os.environ.get("COMFY_PYTHON", "/home/pwintri2/ComfyUI/.venv/bin/python")
COMFY_INPUT_DIR = Path(os.environ.get("COMFYUI_INPUT_DIR", "/home/pwintri2/ComfyUI/input"))

COMFY_IMAGE_TIMEOUT = float(os.environ.get("IMAGINEAI_IMAGE_TIMEOUT", "600"))
COMFY_VIDEO_TIMEOUT = float(os.environ.get("IMAGINEAI_VIDEO_TIMEOUT", "3600"))
COMFY_MISSING_HISTORY_GRACE = float(os.environ.get("IMAGINEAI_MISSING_HISTORY_GRACE", "25"))

# Wan video shares the GPU with Z-Image; only one heavy ComfyUI job at a time.
COMFY_LOCK = threading.Lock()

JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
SETTINGS_LOCK = threading.Lock()
SECRETS_LOCK = threading.Lock()

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
    return defaults


def valid_http_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    current = load_settings()
    for key in ("comfyUrl", "geminiModel", "defaultImageEngine"):
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


def save_secret(provider: str, key: str) -> None:
    provider = provider.strip().lower()
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
        if key.strip():
            data[provider] = key.strip()
        else:
            data.pop(provider, None)
        SECRETS_FILE.write_text(json.dumps(data, indent=2), "utf-8")
        try:
            os.chmod(SECRETS_FILE, 0o600)
        except OSError:
            pass


def gemini_key() -> str:
    return load_secrets().get("gemini") or os.environ.get("GEMINI_API_KEY", "")


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


def save_start_image_for_comfy(data_url: object, original_name: object = "") -> str:
    if not isinstance(data_url, str) or not data_url.strip():
        return ""

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

    words = re.findall(r"[A-Za-z0-9]+", str(original_name or "start"))[:4]
    slug = "_".join(words) or "start"
    upload_dir = COMFY_INPUT_DIR / "imagineai"
    upload_dir.mkdir(parents=True, exist_ok=True)
    filename = f"i2v_{int(now())}_{uuid.uuid4().hex[:8]}_{slug}.{ext}"
    (upload_dir / filename).write_bytes(raw)
    return f"imagineai/{filename}"


# --------------------------------------------------------------------------- #
# Gemini cloud image fallback
# --------------------------------------------------------------------------- #
def gemini_generate_image(prompt: str, aspect: str, model: str, key: str) -> list[str]:
    """Returns a list of local /api/local-media URLs for generated images."""
    url = f"{GEMINI_BASE}/models/{urllib.parse.quote(model)}:generateContent"
    ratio = ASPECT_TO_GEMINI.get(aspect, "1:1")

    def post(payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("x-goog-api-key", key)
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.loads(response.read().decode("utf-8") or "{}")

    base = {"contents": [{"parts": [{"text": prompt}]}]}
    # The exact aspect-ratio nesting changed across Gemini API revisions; try the
    # richest payload first and fall back to simpler ones on a 400 so the cloud
    # fallback still returns an image whatever version the key is wired to.
    variants = [
        {**base, "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": ratio}}},
        {**base, "generationConfig": {"responseModalities": ["IMAGE"], "aspectRatio": ratio}},
        {**base, "generationConfig": {"responseModalities": ["IMAGE"]}},
        base,
    ]
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
                urls.extend(gemini_generate_image(prompt, aspect, model, key))
            urls = urls[:count]  # never return more than requested
            update_job(job_id, status="done",
                       results=[{"url": u, "type": "image"} for u in urls],
                       meta={"engine": "gemini", "modelTitle": model})
            return

        # local Z-Image Turbo
        width, height = ASPECT_TO_SIZE.get(aspect, (1024, 1024))
        graph = build_zimage_graph({
            "prompt": prompt,
            "negative_prompt": payload.get("negativePrompt", DEFAULT_NEGATIVE_IMAGE),
            "width": width, "height": height, "batch_size": count,
            "steps": payload.get("steps", 8), "cfg": payload.get("cfg", 1.0),
            "seed": payload.get("seed"),
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
    try:
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
    name = f"video_{int(now())}_{uuid.uuid4().hex[:8]}.webm"
    out_path = OUTPUTS_DIR / name
    tmp_mp4 = OUTPUTS_DIR / f".src_{uuid.uuid4().hex[:8]}.mp4"
    try:
        tmp_mp4.write_bytes(mp4_bytes)
        result = subprocess.run(
            [COMFY_PYTHON, "-c", _TRANSCODE_SRC, str(tmp_mp4), str(out_path)],
            capture_output=True, timeout=300,
        )
        if result.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
            return None
        return f"/api/local-media?name={urllib.parse.quote(name)}"
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
    ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon",
    ".webm": "video/webm", ".mp4": "video/mp4",
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
                save_secret(provider, str(data.get("key") or ""))
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
        return {
            "comfyUrl": settings["comfyUrl"],
            "comfyReachable": models["reachable"],
            "models": models,
            "geminiConfigured": bool(gemini_key()),
            "geminiModel": settings["geminiModel"],
            "defaultImageEngine": settings["defaultImageEngine"],
        }

    def api_secrets(self) -> dict[str, Any]:
        secrets = load_secrets()
        out = {}
        for provider in ("gemini",):
            value = secrets.get(provider) or ("env" if os.environ.get("GEMINI_API_KEY") and provider == "gemini" else "")
            out[provider] = {
                "configured": bool(value),
                "hint": (f"…{value[-4:]}" if value and value != "env" else ("environment" if value == "env" else "")),
                "source": "env" if value == "env" else ("file" if value else ""),
            }
        return {"providers": out}

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
        fwd = urllib.parse.urlencode({
            "filename": params.get("filename", [""])[0],
            "subfolder": params.get("subfolder", [""])[0],
            "type": params.get("type", ["output"])[0] or "output",
        })
        try:
            blob, ctype = comfy_get_bytes(f"/view?{fwd}", timeout=120)
        except Exception as exc:  # noqa: BLE001
            return self._json(502, {"error": f"Could not fetch media from ComfyUI: {exc}"})
        self._send(200, blob, ctype)

    def api_local_media(self, query: str) -> None:
        name = urllib.parse.parse_qs(query).get("name", [""])[0]
        safe = Path(name).name  # strip any path components
        target = OUTPUTS_DIR / safe
        if not safe or not target.exists() or not target.is_file():
            return self._json(404, {"error": "Not found"})
        ctype = CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, target.read_bytes(), ctype)

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
    print(f"  ComfyUI: {comfy_url()}   Gemini fallback: {'on' if gemini_key() else 'off (add a key in Settings)'}")
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
