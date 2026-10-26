"""Small, independent client for BytePlus ModelArk video generation.

Contract verified against the BytePlus Create/Retrieve video generation task
API and Dreamina Seedance 2.5 tutorial (October 2026):
https://docs.byteplus.com/en/docs/modelark/create-video-generation-task-api
https://docs.byteplus.com/en/docs/modelark/get-video-generation-task-api
https://docs.byteplus.com/en/docs/modelark/seedance-2-5

Seedance 2.5 accepts 4–30 whole seconds (or -1 for automatic duration),
480p/720p/1080p, generated audio, and return_last_frame. It does not accept a
seed. First/last frame inputs accept public image URLs or image data URLs and
require an adaptive aspect ratio. This module never reads stored credentials,
downloads outputs, or retries task creation.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_BASE = "https://ark.ap-southeast.bytepluses.com/api/v3"
DEFAULT_VIDEO_MODEL = "dreamina-seedance-2-5-260628"
MIN_SECONDS = 4
MAX_SECONDS = 30
TASKS_PATH = "/contents/generations/tasks"
ASPECT_RATIOS = {
    "square": "1:1", "landscape": "4:3", "portrait": "3:4",
    "wide": "16:9", "tall": "9:16",
}


class BytePlusHTTPError(RuntimeError):
    """HTTP failure retaining both HTTP status and the provider error code."""

    def __init__(self, code: int, message: str, error_code: str = "") -> None:
        self.code = code
        self.message = message
        self.error_code = error_code
        detail = f"{error_code}: {message}" if error_code else message
        super().__init__(f"BytePlus API error {code}: {detail}")


class BytePlusTransportError(RuntimeError):
    """Network failure; a POST may have been accepted before the failure."""

    def __init__(self, message: str, submission_unknown: bool = False) -> None:
        self.submission_unknown = submission_unknown
        super().__init__(message)


class BytePlusTaskError(RuntimeError):
    def __init__(self, task_id: str, status: str, message: str, error_code: str = "") -> None:
        self.task_id = task_id
        self.status = status
        self.message = message
        self.error_code = error_code
        detail = f"{error_code}: {message}" if error_code else message
        super().__init__(f"BytePlus task {task_id} {status}: {detail}")


def _error_details(data: Any, fallback: str) -> tuple[str, str]:
    if not isinstance(data, dict):
        return "", fallback
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or ""), str(error.get("message") or fallback)
    if isinstance(error, str) and error.strip():
        return "", error
    return str(data.get("code") or ""), str(data.get("message") or fallback)


def friendly_error(error: Exception) -> str:
    """Add a specific next step only when the provider identifies the cause.

    See https://docs.byteplus.com/en/docs/modelark/error-codes. A generic 403
    can mean several things and is deliberately never labelled a balance issue.
    """
    code = str(getattr(error, "error_code", "")).lower()
    message = str(getattr(error, "message", error)).lower()
    hint = ""
    if (code == "accountoverdueerror" or "overdue balance" in message
            or "insufficient balance" in message or "insufficient credit" in message):
        hint = "Check the balance and billing activation in BytePlus Billing Center."
    elif code == "modelnotopen" or "not activated" in message:
        hint = "Activate the requested Seedance model in BytePlus ModelArk Activation Management."
    elif code.startswith("authenticationerror") or "invalid api key" in message:
        hint = "Check the BytePlus ModelArk API key in Settings; use a key from ModelArk API Keys."
    elif code == "invalidendpointormodel.modelidaccessdisabled":
        hint = "This account requires a custom ModelArk endpoint ID instead of a model ID."
    elif code in ("accessdenied", "invalidendpointormodel.notfound"):
        hint = "Check the ModelArk project, model or endpoint ID, and the API key's permissions."
    elif code == "quotaexceeded" and "free trial" in message:
        hint = "The free trial quota is exhausted; check model activation in BytePlus ModelArk."
    return f"{error} {hint}" if hint else str(error)


def request_json(base: str, key: str, path: str, payload: dict[str, Any] | None = None,
                 method: str = "GET", timeout: float = 120) -> dict[str, Any]:
    """Make exactly one request, preserving actionable provider errors."""
    if not key or not key.strip():
        raise ValueError("A BytePlus ModelArk API key is required.")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    method = method.upper()
    request = urllib.request.Request(
        f"{base.rstrip('/')}/{path.lstrip('/')}", data=body, method=method,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8", "replace")
        finally:
            exc.close()
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            data = None
        error_code, message = _error_details(data, raw[:500] or exc.reason)
        # Provider error text must never expose an accidentally echoed API key.
        raise BytePlusHTTPError(exc.code, message.replace(key, "[redacted]"),
                                error_code.replace(key, "[redacted]")) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        detail = str(getattr(exc, "reason", exc)).replace(key, "[redacted]")
        message = f"Could not reach BytePlus ModelArk: {detail}"
        if method == "POST":
            message += (". Submission status is unknown; check the ModelArk console "
                        "before submitting again to avoid a duplicate task.")
        raise BytePlusTransportError(message, submission_unknown=method == "POST") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("BytePlus returned an invalid JSON response.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("BytePlus returned an unexpected response format.")
    return data


def start_task(base: str, key: str, prompt: str, aspect: str, seconds: object,
               model: str = DEFAULT_VIDEO_MODEL, *, resolution: str = "720p",
               generate_audio: bool = True, return_last_frame: bool = False,
               first_frame_url: str = "", last_frame_url: str = "") -> str:
    """Create one Seedance 2.5 video task, without retrying a billable POST."""
    try:
        duration = int(str(seconds))
    except (TypeError, ValueError) as exc:
        raise ValueError("BytePlus video duration must be a whole number of seconds.") from exc
    if duration != -1 and not MIN_SECONDS <= duration <= MAX_SECONDS:
        raise ValueError("BytePlus Seedance 2.5 duration must be 4–30 seconds or -1.")
    resolution = resolution.strip().lower()
    if resolution not in ("480p", "720p", "1080p"):
        raise ValueError("BytePlus Seedance 2.5 resolution must be 480p, 720p or 1080p.")
    if last_frame_url and not first_frame_url:
        raise ValueError("A BytePlus last-frame image requires a first-frame image.")
    ratio = ASPECT_RATIOS.get(aspect, aspect or "16:9")
    if first_frame_url:
        ratio = "adaptive"
    if ratio not in ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"):
        raise ValueError("Unsupported BytePlus video aspect ratio.")
    content = [{"type": "text", "text": prompt}]
    for source, role in ((first_frame_url, "first_frame"), (last_frame_url, "last_frame")):
        if source:
            content.append({"type": "image_url", "image_url": {"url": source}, "role": role})
    payload = {
        "model": model or DEFAULT_VIDEO_MODEL,
        "content": content,
        "duration": duration,
        "ratio": ratio,
        "resolution": resolution,
        "generate_audio": bool(generate_audio),
        "return_last_frame": bool(return_last_frame),
        "watermark": False,
    }
    data = request_json(base, key, TASKS_PATH, payload, method="POST", timeout=120)
    task_id = str(data.get("id") or "").strip()
    if not task_id:
        raise RuntimeError("BytePlus did not return a task ID. Check the ModelArk console "
                           "before submitting again to avoid a duplicate task.")
    return task_id


def poll_result(base: str, key: str, task_id: str, *, on_progress=None,
                timeout: float = 2400, interval: float = 10) -> dict[str, Any]:
    """Poll one existing task. Only transient GET failures are retried."""
    if not str(task_id).strip():
        raise ValueError("A BytePlus task ID is required.")
    deadline = time.monotonic() + max(0, timeout)
    path = f"{TASKS_PATH}/{urllib.parse.quote(str(task_id), safe='')}"
    last_error = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"BytePlus task {task_id} is still pending or its status is unavailable. "
                "Polling timed out; the task may continue in ModelArk. Check its status "
                "before submitting again."
            ) from last_error
        try:
            data = request_json(base, key, path, timeout=min(120, remaining))
        except BytePlusHTTPError as exc:
            if exc.code not in (408, 425, 429) and not 500 <= exc.code <= 599:
                raise
            last_error = exc
        except BytePlusTransportError as exc:
            last_error = exc
        else:
            status = str(data.get("status") or "").strip().lower()
            if on_progress:
                on_progress(status or "pending", None)
            if status == "succeeded":
                content = data.get("content")
                content = content if isinstance(content, dict) else {}
                result = {
                    "id": str(data.get("id") or task_id),
                    "status": status,
                    "video_url": str(content.get("video_url") or "").strip(),
                    "last_frame_url": str(content.get("last_frame_url") or "").strip(),
                    "model": str(data.get("model") or ""),
                }
                if not result["video_url"] and not result["last_frame_url"]:
                    raise RuntimeError(f"BytePlus task {task_id} succeeded without a result URL.")
                return result
            if status in ("failed", "cancelled", "canceled", "expired"):
                error_code, message = _error_details(data, f"Generation {status}.")
                raise BytePlusTaskError(task_id, status, message, error_code)
            if status not in ("queued", "running"):
                raise RuntimeError(f"BytePlus task {task_id} returned an unexpected status: {status or '(empty)'}.")
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(max(0.1, interval), remaining))
