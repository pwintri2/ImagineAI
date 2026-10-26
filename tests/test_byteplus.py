import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import byteplus  # noqa: E402


class BytePlusTests(unittest.TestCase):
    def test_create_uses_modelark_schema_and_never_sends_seevio_input_or_seed(self):
        with patch.object(byteplus, "request_json", return_value={"id": "cgt-1"}) as request:
            task_id = byteplus.start_task(byteplus.DEFAULT_BASE, "secret", "a fox", "wide", 30,
                                          generate_audio=False, return_last_frame=True)
        self.assertEqual(task_id, "cgt-1")
        request.assert_called_once_with(byteplus.DEFAULT_BASE, "secret", byteplus.TASKS_PATH, {
            "model": "dreamina-seedance-2-5-260628",
            "content": [{"type": "text", "text": "a fox"}],
            "duration": 30, "ratio": "16:9", "resolution": "720p",
            "generate_audio": False, "return_last_frame": True, "watermark": False,
        }, method="POST", timeout=120)

    def test_frame_inputs_force_adaptive_ratio_and_preserve_data_url(self):
        first = "data:image/png;base64,dGVzdA=="
        last = "https://example.test/last.png"
        with patch.object(byteplus, "request_json", return_value={"id": "cgt-1"}) as request:
            byteplus.start_task(byteplus.DEFAULT_BASE, "secret", "a fox", "tall", 4,
                                first_frame_url=first, last_frame_url=last)
        payload = request.call_args.args[3]
        self.assertEqual(payload["ratio"], "adaptive")
        self.assertEqual(payload["content"][1:], [
            {"type": "image_url", "image_url": {"url": first}, "role": "first_frame"},
            {"type": "image_url", "image_url": {"url": last}, "role": "last_frame"},
        ])

    def test_invalid_inputs_fail_before_a_billable_request(self):
        for options in ({"seconds": 3}, {"seconds": 31}, {"seconds": 4.5},
                        {"seconds": "invalid"}, {"resolution": "4k"},
                        {"last_frame_url": "https://example.test/last.png"}):
            with self.subTest(options=options), patch.object(byteplus, "request_json") as request:
                args = {"seconds": 5, **options}
                with self.assertRaises(ValueError):
                    byteplus.start_task(byteplus.DEFAULT_BASE, "secret", "a fox", "wide", **args)
                request.assert_not_called()

    def test_automatic_duration_is_supported(self):
        with patch.object(byteplus, "request_json", return_value={"id": "cgt-1"}) as request:
            byteplus.start_task(byteplus.DEFAULT_BASE, "secret", "a fox", "square", -1)
        self.assertEqual(request.call_args.args[3]["duration"], -1)

    def test_request_adds_bearer_auth_and_json_body(self):
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"id":"cgt-1"}'
        with patch.object(byteplus.urllib.request, "urlopen", return_value=response) as urlopen:
            result = byteplus.request_json(byteplus.DEFAULT_BASE + "/", "secret", byteplus.TASKS_PATH,
                                           {"model": byteplus.DEFAULT_VIDEO_MODEL}, method="POST")
        self.assertEqual(result, {"id": "cgt-1"})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, byteplus.DEFAULT_BASE + byteplus.TASKS_PATH)
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(request.data), {"model": byteplus.DEFAULT_VIDEO_MODEL})

    def test_http_error_preserves_billing_code_and_redacts_key(self):
        error = urllib.error.HTTPError("https://example.test", 403, "Forbidden", {}, io.BytesIO(
            b'{"error":{"code":"AccountOverdueError","message":"Payment required for secret"}}'))
        with patch.object(byteplus.urllib.request, "urlopen", side_effect=error), \
             self.assertRaises(byteplus.BytePlusHTTPError) as caught:
            byteplus.request_json(byteplus.DEFAULT_BASE, "secret", byteplus.TASKS_PATH)
        self.assertEqual(caught.exception.code, 403)
        self.assertEqual(caught.exception.error_code, "AccountOverdueError")
        self.assertEqual(caught.exception.message, "Payment required for [redacted]")
        self.assertNotIn("secret", str(caught.exception))

    def test_actionable_hints_follow_provider_error_not_status(self):
        cases = (
            (403, "AccountOverdueError", "overdue balance", "Billing Center"),
            (401, "AuthenticationError", "invalid key", "ModelArk API key"),
            (404, "ModelNotOpen", "model not open", "Activate the requested Seedance"),
            (403, "AccessDenied", "access denied", "permissions"),
        )
        for status, code, message, hint in cases:
            with self.subTest(code=code):
                result = byteplus.friendly_error(byteplus.BytePlusHTTPError(status, message, code))
                self.assertIn(hint, result)
                self.assertIn(message, result)
        generic = byteplus.BytePlusHTTPError(403, "Forbidden")
        self.assertEqual(byteplus.friendly_error(generic), str(generic))
        self.assertNotIn("Billing", byteplus.friendly_error(generic))

    def test_create_network_timeout_is_never_retried(self):
        with patch.object(byteplus.urllib.request, "urlopen", side_effect=TimeoutError("timed out")) as request, \
             self.assertRaises(byteplus.BytePlusTransportError) as caught:
            byteplus.start_task(byteplus.DEFAULT_BASE, "secret", "a fox", "wide", 5)
        request.assert_called_once()
        self.assertTrue(caught.exception.submission_unknown)
        self.assertIn("before submitting again", str(caught.exception))

    def test_missing_task_id_is_not_retried(self):
        with patch.object(byteplus, "request_json", return_value={}) as request, \
             self.assertRaisesRegex(RuntimeError, "before submitting again"):
            byteplus.start_task(byteplus.DEFAULT_BASE, "secret", "a fox", "wide", 5)
        request.assert_called_once()

    def test_poll_normalizes_success_and_notifies_progress(self):
        result = {"id": "cgt-1", "status": "succeeded", "model": byteplus.DEFAULT_VIDEO_MODEL,
                  "content": {"video_url": "https://example.test/video.mp4",
                              "last_frame_url": "https://example.test/frame.jpeg"}}
        progress = Mock()
        with patch.object(byteplus, "request_json", side_effect=[{"status": "queued"}, result]) as request, \
             patch.object(byteplus.time, "sleep"):
            data = byteplus.poll_result(byteplus.DEFAULT_BASE, "secret", "cgt-1", on_progress=progress)
        self.assertEqual(data, {"id": "cgt-1", "status": "succeeded", "model": byteplus.DEFAULT_VIDEO_MODEL,
                                "video_url": "https://example.test/video.mp4",
                                "last_frame_url": "https://example.test/frame.jpeg"})
        self.assertEqual([call.args for call in progress.call_args_list], [("queued", None), ("succeeded", None)])
        self.assertTrue(all(call.args[2] == byteplus.TASKS_PATH + "/cgt-1" for call in request.call_args_list))

    def test_poll_retries_only_transient_get_failures(self):
        result = {"status": "succeeded", "content": {"video_url": "https://example.test/video.mp4"}}
        errors = [byteplus.BytePlusHTTPError(429, "rate limit"),
                  byteplus.BytePlusHTTPError(503, "unavailable"),
                  byteplus.BytePlusTransportError("connection reset")]
        with patch.object(byteplus, "request_json", side_effect=errors + [result]) as request, \
             patch.object(byteplus.time, "sleep"):
            data = byteplus.poll_result(byteplus.DEFAULT_BASE, "secret", "cgt-1")
        self.assertEqual(data["video_url"], "https://example.test/video.mp4")
        self.assertEqual(request.call_count, 4)
        self.assertTrue(all(call.kwargs.get("method", "GET") == "GET" for call in request.call_args_list))

    def test_poll_does_not_retry_auth_or_access_errors(self):
        for status in (400, 401, 403, 404):
            with self.subTest(status=status), \
                 patch.object(byteplus, "request_json", side_effect=byteplus.BytePlusHTTPError(status, "denied")) as request, \
                 self.assertRaises(byteplus.BytePlusHTTPError):
                byteplus.poll_result(byteplus.DEFAULT_BASE, "secret", "cgt-1")
            request.assert_called_once()

    def test_terminal_task_failures_preserve_error_code(self):
        for status in ("failed", "expired", "cancelled"):
            result = {"status": status, "error": {"code": "AccessDenied", "message": "Model not activated"}}
            with self.subTest(status=status), patch.object(byteplus, "request_json", return_value=result) as request, \
                 self.assertRaises(byteplus.BytePlusTaskError) as caught:
                byteplus.poll_result(byteplus.DEFAULT_BASE, "secret", "cgt-1")
            request.assert_called_once()
            self.assertEqual(caught.exception.status, status)
            self.assertEqual(caught.exception.task_id, "cgt-1")
            self.assertEqual(caught.exception.error_code, "AccessDenied")
            self.assertIn("Model not activated", str(caught.exception))

    def test_success_without_result_url_is_reported(self):
        with patch.object(byteplus, "request_json", return_value={"status": "succeeded"}), \
             self.assertRaisesRegex(RuntimeError, "without a result URL"):
            byteplus.poll_result(byteplus.DEFAULT_BASE, "secret", "cgt-1")

    def test_poll_timeout_retains_task_id_and_never_resubmits(self):
        with patch.object(byteplus.time, "monotonic", side_effect=[0, 0, 3, 5]), \
             patch.object(byteplus.time, "sleep"), \
             patch.object(byteplus, "request_json", return_value={"status": "running"}) as request, \
             self.assertRaisesRegex(TimeoutError, "cgt-1.*still pending"):
            byteplus.poll_result(byteplus.DEFAULT_BASE, "secret", "cgt-1", timeout=5)
        request.assert_called_once()
        self.assertEqual(request.call_args.kwargs["timeout"], 5)

    def test_task_id_is_escaped_in_poll_path(self):
        with patch.object(byteplus, "request_json", return_value={
            "status": "succeeded", "content": {"last_frame_url": "https://example.test/frame.jpeg"}
        }) as request:
            byteplus.poll_result(byteplus.DEFAULT_BASE, "secret", "cgt/1?x=2")
        self.assertEqual(request.call_args.args[2], byteplus.TASKS_PATH + "/cgt%2F1%3Fx%3D2")


if __name__ == "__main__":
    unittest.main()
