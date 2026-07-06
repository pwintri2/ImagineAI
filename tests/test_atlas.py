import io
import os
import sys
import unittest
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class AtlasTests(unittest.TestCase):
    def test_atlas_key_uses_other_api_key_alias(self):
        with patch.object(server, "load_secrets", return_value={"atlas": "atlas-secret"}), \
             patch.dict(os.environ, {"ATLAS_API_KEY": "", "ATLASCLOUD_API_KEY": ""}):
            self.assertEqual(server.atlas_key(), ("atlas-secret", "atlas"))

    def test_atlas_env_key_overrides_saved_key(self):
        with patch.object(server, "load_secrets", return_value={"atlas": "saved-coding-plan-key"}), \
             patch.dict(os.environ, {"ATLAS_API_KEY": "", "ATLASCLOUD_API_KEY": "full-api-key"}):
            self.assertEqual(server.atlas_key(), ("full-api-key", "ATLASCLOUD_API_KEY"))

    def test_legacy_atlas_video_model_setting_is_normalized(self):
        for legacy_model in ("kling-v2.0", "kwaivgi/kling-v1.6-t2v-standard"):
            with self.subTest(legacy_model=legacy_model), tempfile.TemporaryDirectory() as tmp:
                settings_file = Path(tmp) / "settings.json"
                settings_file.write_text(f'{{"atlasVideoModel":"{legacy_model}"}}', "utf-8")
                with patch.object(server, "SETTINGS_FILE", settings_file):
                    self.assertEqual(server.load_settings()["atlasVideoModel"], "alibaba/wan-2.7/text-to-video")

    def test_atlas_generate_image_submits_polls_and_downloads(self):
        calls = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            calls.append((path, payload, method))
            if path == "/model/generateImage":
                return {"data": {"id": "pred-1"}}
            if path == "/model/prediction/pred-1":
                return {"data": {"status": "completed", "outputs": ["https://example.test/image.png"]}}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "atlas_request_json", side_effect=fake_request), \
             patch.object(server, "download_url_to_output", return_value=("/api/local-media?name=atlas.png", Path("atlas.png"), "atlas.png")):
            urls = server.atlas_generate_image("a mountain", "square", 1, "seedream-3.0", "secret")

        self.assertEqual(urls, ["/api/local-media?name=atlas.png"])
        self.assertEqual(calls[0], ("/model/generateImage", {"model": "seedream-3.0", "prompt": "a mountain"}, "POST"))
        self.assertEqual(calls[1], ("/model/prediction/pred-1", None, "GET"))

    def test_atlas_poll_falls_back_to_result_endpoint(self):
        calls = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            calls.append(path)
            if path == "/model/prediction/pred-1":
                raise server.AtlasHTTPError(404, "not found")
            if path == "/model/result/pred-1":
                return {"status": "completed", "outputs": ["https://example.test/image.png"]}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "atlas_request_json", side_effect=fake_request):
            result = server.atlas_poll_result("pred-1", "secret")

        self.assertEqual(server.atlas_extract_outputs(result), ["https://example.test/image.png"])
        self.assertEqual(calls, ["/model/prediction/pred-1", "/model/result/pred-1"])

    def test_atlas_generate_video_submits_polls_and_downloads(self):
        calls = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            calls.append((path, payload, method))
            if path == "/model/generateVideo":
                return {"data": {"id": "vid-1"}}
            if path == "/model/prediction/vid-1":
                return {"data": {"status": "completed", "outputs": ["https://example.test/video.mp4"]}}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "atlas_request_json", side_effect=fake_request), \
             patch.object(server, "download_url_to_output", return_value=("/api/local-media?name=atlas.mp4", Path("atlas.mp4"), "atlas.mp4")), \
             patch.object(server, "transcode_mp4_path_to_webm", return_value="/api/local-media?name=atlas.webm"):
            result = server.atlas_generate_video("a rocket launch", "wide", 5, "kling-v2.0", "secret")

        self.assertEqual(result["url"], "/api/local-media?name=atlas.webm")
        self.assertEqual(result["mp4Url"], "/api/local-media?name=atlas.mp4")
        self.assertEqual(calls[0], ("/model/generateVideo", {
            "model": "alibaba/wan-2.7/text-to-video",
            "prompt": "a rocket launch",
            "duration": 5,
            "negative_prompt": server.DEFAULT_NEGATIVE_VIDEO[:500],
            "resolution": "1080P",
            "ratio": "16:9",
            "prompt_extend": True,
            "seed": -1,
        }, "POST"))
        self.assertEqual(calls[1], ("/model/prediction/vid-1", None, "GET"))

    def test_atlas_generate_video_uses_uploaded_start_image(self):
        payloads = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "/model/generateVideo":
                payloads.append(payload)
                return {"data": {"id": "vid-1"}}
            if path == "/model/prediction/vid-1":
                return {"data": {"status": "completed", "outputs": ["https://example.test/video.mp4"]}}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "atlas_upload_media", return_value="https://upload.example.test/start.png"), \
             patch.object(server, "atlas_request_json", side_effect=fake_request), \
             patch.object(server, "download_url_to_output", return_value=("/api/local-media?name=atlas.mp4", Path("atlas.mp4"), "atlas.mp4")), \
             patch.object(server, "transcode_mp4_path_to_webm", return_value=None):
            result = server.atlas_generate_video(
                "make the image move", "wide", 5, "kling-v2.0", "secret", start_image="data:image/png;base64,abc"
            )

        self.assertEqual(result["url"], "/api/local-media?name=atlas.mp4")
        self.assertEqual(payloads, [{
            "model": "alibaba/wan-2.7/image-to-video",
            "prompt": "make the image move",
            "duration": 5,
            "negative_prompt": server.DEFAULT_NEGATIVE_VIDEO[:500],
            "resolution": "1080P",
            "ratio": "16:9",
            "prompt_extend": True,
            "seed": -1,
            "image": "https://upload.example.test/start.png",
        }])

    def test_atlas_generate_video_defaults_to_standard_model(self):
        payloads = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "/model/generateVideo":
                payloads.append(payload)
                return {"data": {"id": "vid-1"}}
            if path == "/model/prediction/vid-1":
                return {"data": {"status": "completed", "outputs": ["https://example.test/video.mp4"]}}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "atlas_request_json", side_effect=fake_request), \
             patch.object(server, "download_url_to_output", return_value=("/api/local-media?name=atlas.mp4", Path("atlas.mp4"), "atlas.mp4")), \
             patch.object(server, "transcode_mp4_path_to_webm", return_value=None):
            server.atlas_generate_video("a rocket launch", "tall", 10, "", "secret")

        self.assertEqual(payloads, [{
            "model": "alibaba/wan-2.7/text-to-video",
            "prompt": "a rocket launch",
            "duration": 10,
            "negative_prompt": server.DEFAULT_NEGATIVE_VIDEO[:500],
            "resolution": "1080P",
            "ratio": "9:16",
            "prompt_extend": True,
            "seed": -1,
        }])

    def test_atlas_wan27_403_does_not_fall_back_to_kling(self):
        payloads = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "/model/generateVideo":
                payloads.append(payload)
                raise server.AtlasHTTPError(403, "invalid token for coding plan, this model not support coding plan")
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "atlas_request_json", side_effect=fake_request):
            with self.assertRaisesRegex(server.AtlasModelAccessError, "Coding Plan token does not support video generation"):
                server.atlas_generate_video("a rocket launch", "wide", 5, "", "secret")

        self.assertEqual(payloads, [{
            "model": "alibaba/wan-2.7/text-to-video",
            "prompt": "a rocket launch",
            "duration": 5,
            "negative_prompt": server.DEFAULT_NEGATIVE_VIDEO[:500],
            "resolution": "1080P",
            "ratio": "16:9",
            "prompt_extend": True,
            "seed": -1,
        }])

    def test_atlas_wan27_optional_schema_fields_can_be_configured(self):
        payloads = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "/model/generateVideo":
                payloads.append(payload)
                return {"data": {"id": "vid-1"}}
            if path == "/model/prediction/vid-1":
                return {"data": {"status": "completed", "outputs": ["https://example.test/video.mp4"]}}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "DEFAULT_ATLAS_WAN27_AUDIO", "https://example.test/sound.mp3"), \
             patch.object(server, "DEFAULT_ATLAS_WAN27_RESOLUTION", "1440P-SR"), \
             patch.object(server, "DEFAULT_ATLAS_WAN27_PROMPT_EXTEND", False), \
             patch.object(server, "DEFAULT_ATLAS_WAN27_SEED", "123"), \
             patch.object(server, "atlas_request_json", side_effect=fake_request), \
             patch.object(server, "download_url_to_output", return_value=("/api/local-media?name=atlas.mp4", Path("atlas.mp4"), "atlas.mp4")), \
             patch.object(server, "transcode_mp4_path_to_webm", return_value=None):
            server.atlas_generate_video("a rocket launch", "landscape", 5, "", "secret")

        self.assertEqual(payloads[0]["audio"], "https://example.test/sound.mp3")
        self.assertEqual(payloads[0]["resolution"], "1440P-SR")
        self.assertEqual(payloads[0]["ratio"], "4:3")
        self.assertEqual(payloads[0]["prompt_extend"], False)
        self.assertEqual(payloads[0]["seed"], 123)

    def test_atlas_wan27_copyright_flag_retries_without_prompt_extend(self):
        submits = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "/model/generateVideo":
                submits.append(dict(payload))
                return {"data": {"id": f"vid-{len(submits)}"}}
            if path == "/model/prediction/vid-1":
                return {"data": {"status": "failed", "error": (
                    "The request failed because the output video may be related to copyright restrictions"
                )}}
            if path == "/model/prediction/vid-2":
                return {"data": {"status": "completed", "outputs": ["https://example.test/video.mp4"]}}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "ATLAS_MODERATION_RETRIES", 2), \
             patch.object(server, "atlas_request_json", side_effect=fake_request), \
             patch.object(server, "download_url_to_output", return_value=("/api/local-media?name=atlas.mp4", Path("atlas.mp4"), "atlas.mp4")), \
             patch.object(server, "transcode_mp4_path_to_webm", return_value=None):
            result = server.atlas_generate_video("a rocket launch", "wide", 5, "", "secret")

        self.assertEqual(result["url"], "/api/local-media?name=atlas.mp4")
        self.assertEqual(len(submits), 2)
        self.assertEqual(submits[0]["prompt_extend"], True)
        self.assertEqual(submits[0]["seed"], -1)
        self.assertEqual(submits[1]["prompt_extend"], False)
        self.assertGreaterEqual(submits[1]["seed"], 0)
        self.assertEqual(submits[1]["prompt"], "a rocket launch")

    def test_atlas_video_non_moderation_failure_does_not_retry(self):
        submits = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "/model/generateVideo":
                submits.append(dict(payload))
                return {"data": {"id": "vid-1"}}
            if path == "/model/prediction/vid-1":
                return {"data": {"status": "failed", "error": "internal error"}}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "atlas_request_json", side_effect=fake_request):
            with self.assertRaisesRegex(RuntimeError, "internal error"):
                server.atlas_generate_video("a rocket launch", "wide", 5, "", "secret")

        self.assertEqual(len(submits), 1)

    def test_atlas_wan27_copyright_flag_gives_clear_error_after_retries(self):
        submits = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "/model/generateVideo":
                submits.append(dict(payload))
                return {"data": {"id": f"vid-{len(submits)}"}}
            if path.startswith("/model/prediction/vid-"):
                return {"data": {"status": "failed", "error": (
                    "The request failed because the output video may be related to copyright restrictions"
                )}}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "ATLAS_MODERATION_RETRIES", 2), \
             patch.object(server, "atlas_request_json", side_effect=fake_request):
            with self.assertRaisesRegex(RuntimeError, "content filter blocked this video"):
                server.atlas_generate_video("a rocket launch", "wide", 5, "", "secret")

        self.assertEqual(len(submits), 3)
        self.assertEqual(submits[0]["prompt_extend"], True)
        self.assertEqual([p["prompt_extend"] for p in submits[1:]], [False, False])

    def test_atlas_input_prompt_moderation_does_not_retry(self):
        submits = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "/model/generateVideo":
                submits.append(dict(payload))
                return {"data": {"id": "vid-1"}}
            if path == "/model/prediction/vid-1":
                return {"data": {"status": "failed", "error": "Input data may contain inappropriate content."}}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "ATLAS_MODERATION_RETRIES", 2), \
             patch.object(server, "atlas_request_json", side_effect=fake_request):
            with self.assertRaisesRegex(RuntimeError, "Input data may contain inappropriate content"):
                server.atlas_generate_video("a rocket launch", "wide", 5, "", "secret")

        self.assertEqual(len(submits), 1)

    def test_atlas_poll_http_error_is_not_treated_as_moderation(self):
        submits = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "/model/generateVideo":
                submits.append(dict(payload))
                return {"data": {"id": "vid-1"}}
            if path == "/model/prediction/vid-1":
                raise server.AtlasHTTPError(500, "output moderation service unavailable")
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "ATLAS_MODERATION_RETRIES", 2), \
             patch.object(server, "atlas_request_json", side_effect=fake_request):
            with self.assertRaises(server.AtlasHTTPError):
                server.atlas_generate_video("a rocket launch", "wide", 5, "", "secret")

        self.assertEqual(len(submits), 1)

    def test_atlas_non_wan27_model_fails_fast_on_moderation(self):
        submits = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "/model/generateVideo":
                submits.append(dict(payload))
                return {"data": {"id": "vid-1"}}
            if path == "/model/prediction/vid-1":
                return {"data": {"status": "failed", "error": (
                    "The request failed because the output video may be related to copyright restrictions"
                )}}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "ATLAS_MODERATION_RETRIES", 2), \
             patch.object(server, "atlas_request_json", side_effect=fake_request):
            with self.assertRaisesRegex(RuntimeError, "content filter blocked this video"):
                server.atlas_generate_video(
                    "a rocket launch", "wide", 5, "kwaivgi/kling-v2.5-turbo-pro/text-to-video", "secret"
                )

        self.assertEqual(len(submits), 1)
        self.assertNotIn("prompt_extend", submits[0])

    def test_atlas_wan27_pinned_seed_survives_moderation_retry(self):
        submits = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "/model/generateVideo":
                submits.append(dict(payload))
                return {"data": {"id": f"vid-{len(submits)}"}}
            if path.startswith("/model/prediction/vid-"):
                return {"data": {"status": "failed", "error": (
                    "The request failed because the output video may be related to copyright restrictions"
                )}}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "ATLAS_MODERATION_RETRIES", 2), \
             patch.object(server, "DEFAULT_ATLAS_WAN27_SEED", "123"), \
             patch.object(server, "atlas_request_json", side_effect=fake_request):
            with self.assertRaisesRegex(RuntimeError, "content filter blocked this video"):
                server.atlas_generate_video("a rocket launch", "wide", 5, "", "secret")

        # A pinned seed leaves only the prompt_extend toggle to vary, so exactly one retry.
        self.assertEqual(len(submits), 2)
        self.assertEqual([p["seed"] for p in submits], [123, 123])
        self.assertEqual([p["prompt_extend"] for p in submits], [True, False])

    def test_atlas_upload_media_sends_browser_user_agent(self):
        captured = {}

        class FakeResponse:
            def read(self):
                # Real Atlas uploadMedia response shape: the URL lives in download_url.
                return (b'{"code":200,"message":"success","data":{"type":"image",'
                        b'"download_url":"https://upload.example.test/start.png",'
                        b'"filename":"start.png","size":70}}')

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        def fake_urlopen(req, timeout=0):
            captured["req"] = req
            return FakeResponse()

        with patch.object(server.urllib.request, "urlopen", side_effect=fake_urlopen):
            url = server.atlas_upload_media("data:image/png;base64,aGVsbG8=", "secret", "start.png")

        self.assertEqual(url, "https://upload.example.test/start.png")
        # Cloudflare bans urllib's default UA with 403 "error code: 1010".
        self.assertIn("Mozilla/5.0", captured["req"].get_header("User-agent") or "")

    def test_atlas_upload_media_explains_cloudflare_block(self):
        def fake_urlopen(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", None, io.BytesIO(b"error code: 1010"))

        with patch.object(server.urllib.request, "urlopen", side_effect=fake_urlopen):
            with self.assertRaisesRegex(server.AtlasHTTPError, "Cloudflare"):
                server.atlas_upload_media("data:image/png;base64,aGVsbG8=", "secret", "start.png")

    def test_long_atlas_video_is_stitched_from_segments(self):
        calls = []

        def fake_clip(prompt, aspect, seconds, model, key, start_image="", start_image_name="", on_progress=None):
            calls.append((prompt, aspect, seconds, model, key, start_image, start_image_name))
            index = len(calls)
            return {
                "url": f"/api/local-media?name=atlas-segment{index}.webm",
                "type": "video",
                "mp4Url": f"/api/local-media?name=atlas-segment{index}.mp4",
                "mp4Path": f"/tmp/atlas-segment{index}.mp4",
            }

        with patch.object(server, "atlas_generate_video_clip", side_effect=fake_clip), \
             patch.object(server, "concat_mp4_paths_to_webm", return_value="/api/local-media?name=atlas-stitched.webm"):
            result = server.atlas_generate_video(
                "a long camera move", "wide", 30, "kling-v2.0", "secret",
                start_image="data:image/png;base64,abc", start_image_name="start.png",
        )

        self.assertEqual(result["url"], "/api/local-media?name=atlas-stitched.webm")
        self.assertEqual(len(result["segments"]), 2)
        self.assertNotIn("mp4Path", result["segments"][0])
        self.assertEqual([call[2] for call in calls], [15, 15])
        self.assertIn("Segment 1 of 2", calls[0][0])
        self.assertEqual(calls[0][5], "data:image/png;base64,abc")
        self.assertEqual(calls[0][6], "start.png")
        self.assertEqual([call[5] for call in calls[1:]], [""])


if __name__ == "__main__":
    unittest.main()
