import base64
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402


MODEL = "gemini-omni-1.1-flash"
IMAGE = "data:image/png;base64," + base64.b64encode(b"fake-png").decode("ascii")


def video_response(**content):
    return {"status": "completed", "model": MODEL, "steps": [
        {"type": "thought", "content": [{"type": "video", "data": "ignore-me"}]},
        {"type": "model_output", "content": [{"type": "video", "mime_type": "video/mp4", **content}]},
    ]}


class GoogleCurrentTests(unittest.TestCase):
    def test_google_download_keeps_key_out_of_urls_and_cross_host_redirects(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"mp4-bytes"
        opener = MagicMock()
        opener.open.return_value = response
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(server, "OUTPUTS_DIR", Path(tmp)), \
             patch("urllib.request.build_opener", return_value=opener) as build:
            _, path = server.veo_download_video(
                f"{server.GEMINI_API_BASE}/files/clip:download?alt=media&key=old-key", "test-key")
            self.assertEqual(path.read_bytes(), b"mp4-bytes")
        request = opener.open.call_args.args[0]
        self.assertNotIn("key=", request.full_url)
        self.assertEqual(request.get_header("X-goog-api-key"), "test-key")
        redirect_handler = build.call_args.args[0]
        redirected = redirect_handler.redirect_request(
            request, None, 302, "Found", {}, "https://cdn.example.test/signed-video")
        self.assertIsNone(redirected.get_header("X-goog-api-key"))

    def test_omni_routes_to_interactions_and_preserves_first_frame_duration_and_exclusions(self):
        requests = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            requests.append((path, payload, method, timeout))
            return video_response(data=base64.b64encode(b"mp4-bytes").decode("ascii"))

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(server, "OUTPUTS_DIR", Path(tmp)), \
             patch.object(server, "DEFAULT_VEO_VIDEO_MODEL", MODEL), \
             patch.object(server, "DEFAULT_VEO_RESOLUTION", "1080p"), \
             patch.object(server, "veo_request_json", side_effect=fake_request), \
             patch.object(server, "transcode_mp4_path_to_webm", return_value=None):
            result = server.veo_generate_video_clip(
                "A kite flies", "tall", 6, "", "test-key",
                start_image=IMAGE, negative_prompt="blurred details", seed=123,
            )
            self.assertEqual(Path(result["mp4Path"]).read_bytes(), b"mp4-bytes")

        path, payload, method, timeout = requests[0]
        self.assertEqual(path, "interactions")
        self.assertEqual(method, "POST")
        self.assertEqual(timeout, server.VEO_VIDEO_TIMEOUT)
        self.assertEqual(payload["model"], MODEL)
        self.assertEqual(payload["input"][0], {
            "type": "image", "mime_type": "image/png", "data": IMAGE.split(",")[1],
        })
        self.assertIn("<FIRST_FRAME>", payload["input"][1]["text"])
        self.assertIn("blurred details", payload["input"][1]["text"])
        self.assertEqual(payload["response_format"], {
            "type": "video", "delivery": "uri", "aspect_ratio": "9:16",
            "duration": "6s", "resolution": "1080p",
        })
        self.assertNotIn("seed", json.dumps(payload))
        self.assertNotIn("negativePrompt", payload)
        self.assertEqual(result["model"], MODEL)

    def test_omni_uri_delivery_waits_for_active_file_before_download(self):
        replies = [video_response(uri="https://generativelanguage.googleapis.com/v1beta/files/clip-1:download?alt=media"),
                   {"state": "PROCESSING"}, {"state": "ACTIVE"}]
        with patch.object(server, "veo_request_json", side_effect=replies) as request, \
             patch.object(server, "veo_download_video", return_value=("/clip.mp4", Path("/tmp/clip.mp4"))) as download, \
             patch.object(server, "transcode_mp4_path_to_webm", return_value="/clip.webm"), \
             patch.object(server.time, "sleep"):
            result = server.veo_generate_video_clip("A kite flies", "wide", 8, MODEL, "test-key")

        self.assertEqual([call.args[0] for call in request.call_args_list],
                         ["interactions", "files/clip-1", "files/clip-1"])
        download.assert_called_once_with(
            f"{server.GEMINI_API_BASE}/files/clip-1:download?alt=media", "test-key")
        self.assertEqual(result["url"], "/clip.webm")

    def test_omni_relative_file_uri_and_transient_poll_error(self):
        with patch.object(server, "veo_request_json", side_effect=[
                 server.VeoHTTPError(503, "try later"), {"state": "ACTIVE"}]), \
             patch.object(server, "veo_download_video", return_value=("/clip.mp4", Path("/tmp/clip.mp4"))) as download, \
             patch.object(server.time, "sleep"):
            server.omni_download_video("files/clip_1", "test-key", server.now() + 60)
        download.assert_called_once_with(
            f"{server.GEMINI_API_BASE}/files/clip_1:download?alt=media", "test-key")

    def test_omni_failed_file_does_not_download(self):
        with patch.object(server, "veo_request_json", return_value={
                 "state": "FAILED", "error": {"message": "render failed"}}), \
             patch.object(server, "veo_download_video") as download:
            with self.assertRaisesRegex(RuntimeError, "render failed"):
                server.omni_download_video("files/clip-1", "test-key", server.now() + 60)
        download.assert_not_called()

    def test_omni_does_not_return_thought_media_or_succeed_without_output(self):
        with patch.object(server, "veo_request_json", return_value={
                 "status": "completed", "steps": [{"type": "thought", "content": [
                     {"type": "video", "data": "ignored"}]}]}):
            with self.assertRaisesRegex(RuntimeError, "returned no video"):
                server.veo_generate_video_clip("A kite flies", "wide", 8, MODEL, "test-key")

    def test_omni_rejects_malformed_inline_media(self):
        with patch.object(server, "veo_request_json", return_value=video_response(data="!invalid!")):
            with self.assertRaisesRegex(RuntimeError, "invalid video data"):
                server.veo_generate_video_clip("A kite flies", "wide", 8, MODEL, "test-key")

    def test_omni_surfaces_provider_failure(self):
        with patch.object(server, "veo_request_json", return_value={
                 "status": "failed", "error": {"message": "video generation failed"}}):
            with self.assertRaisesRegex(RuntimeError, "video generation failed"):
                server.veo_generate_video_clip("A kite flies", "wide", 8, MODEL, "test-key")

    def test_omni_unfinished_sync_response_is_not_retried(self):
        with patch.object(server, "veo_request_json", return_value={
                 "status": "in_progress", "id": "accepted-job"}) as request:
            with self.assertRaisesRegex(TimeoutError, "accepted-job"):
                server.veo_generate_video_clip("A kite flies", "wide", 8, MODEL, "test-key")
        self.assertEqual(request.call_count, 1)

    def test_google_transport_errors_do_not_trigger_a_second_paid_generation(self):
        for reason, expected in ((TimeoutError("timed out"), TimeoutError),
                                 ("connection reset", ConnectionError)):
            with self.subTest(reason=reason), \
                 patch("urllib.request.urlopen", side_effect=urllib.error.URLError(reason)):
                with self.assertRaises(expected):
                    server.veo_request_json("interactions", "test-key", {"model": MODEL}, method="POST")

        with patch.object(server, "veo_generate_video_clip", side_effect=[
                 {"mp4Path": "/tmp/first.mp4"}, ConnectionError("connection reset")]) as generate, \
             patch.object(server, "extract_last_frame_to_data_url", return_value=IMAGE):
            with self.assertRaises(ConnectionError):
                server.veo_generate_video("A story", "wide", 16, MODEL, "test-key")
        self.assertEqual(generate.call_count, 2)


if __name__ == "__main__":
    unittest.main()
