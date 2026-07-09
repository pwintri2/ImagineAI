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

    def test_atlas_image_edit_model_resolution(self):
        # Legacy text-to-image default has no edit sibling -> edit default.
        self.assertEqual(server.atlas_image_edit_model("seedream-3.0"), server.DEFAULT_ATLAS_IMAGE_EDIT_MODEL)
        # An explicit edit model is used as-is.
        self.assertEqual(server.atlas_image_edit_model("alibaba/qwen-image/edit"), "alibaba/qwen-image/edit")
        # A settings override wins over the built-in default.
        self.assertEqual(
            server.atlas_image_edit_model("seedream-3.0", {"atlasImageEditModel": "google/nano-banana/edit"}),
            "google/nano-banana/edit",
        )

    def test_atlas_generate_image_with_reference_uploads_once_and_uses_images_array(self):
        submits = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "/model/generateImage":
                submits.append(dict(payload))
                return {"data": {"id": f"img-{len(submits)}"}}
            if path.startswith("/model/prediction/img-"):
                return {"data": {"status": "completed", "outputs": ["https://example.test/image.png"]}}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "atlas_upload_media", return_value="https://upload.example.test/ref.png") as upload, \
             patch.object(server, "atlas_request_json", side_effect=fake_request), \
             patch.object(server, "download_url_to_output", return_value=("/api/local-media?name=atlas.png", Path("atlas.png"), "atlas.png")):
            urls = server.atlas_generate_image(
                "make it a watercolor", "wide", 2, "bytedance/seedream-v4.5/edit", "secret",
                source_image="data:image/png;base64,aGVsbG8=", source_image_name="ref.png",
            )

        self.assertEqual(len(urls), 2)
        upload.assert_called_once()
        self.assertEqual(len(submits), 2)
        for payload in submits:
            self.assertEqual(payload["model"], "bytedance/seedream-v4.5/edit")
            self.assertEqual(payload["images"], ["https://upload.example.test/ref.png"])
            self.assertEqual(payload["size"], "2848*1600")

    def test_atlas_generate_image_without_reference_keeps_plain_payload(self):
        submits = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "/model/generateImage":
                submits.append(dict(payload))
                return {"data": {"id": "img-1"}}
            if path == "/model/prediction/img-1":
                return {"data": {"status": "completed", "outputs": ["https://example.test/image.png"]}}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "atlas_request_json", side_effect=fake_request), \
             patch.object(server, "download_url_to_output", return_value=("/api/local-media?name=atlas.png", Path("atlas.png"), "atlas.png")):
            server.atlas_generate_image("a mountain", "wide", 1, "seedream-3.0", "secret")

        self.assertEqual(submits, [{"model": "seedream-3.0", "prompt": "a mountain"}])

    def test_atlas_generate_image_accepts_multiple_reference_images(self):
        submits = []
        uploads = []

        def fake_upload(data_url, key, name=""):
            uploads.append(data_url)
            return f"https://upload.example.test/{len(uploads)}.png"

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "/model/generateImage":
                submits.append(dict(payload))
                return {"data": {"id": "img-1"}}
            if path == "/model/prediction/img-1":
                return {"data": {"status": "completed", "outputs": ["https://example.test/image.png"]}}
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "atlas_upload_media", side_effect=fake_upload), \
             patch.object(server, "atlas_request_json", side_effect=fake_request), \
             patch.object(server, "download_url_to_output", return_value=("/api/local-media?name=atlas.png", Path("atlas.png"), "atlas.png")):
            server.atlas_generate_image(
                "combine them", "square", 1, "bytedance/seedream-v4.5/edit", "secret",
                source_image=["data:image/png;base64,aaa=", "data:image/png;base64,bbb="],
            )

        self.assertEqual(len(uploads), 2)
        self.assertEqual(submits[0]["images"],
                         ["https://upload.example.test/1.png", "https://upload.example.test/2.png"])
        self.assertEqual(submits[0]["size"], "2048*2048")

    def test_merge_start_images_requires_atlas_key(self):
        with patch.object(server, "atlas_key", return_value=("", "")):
            with self.assertRaisesRegex(RuntimeError, "no Atlas API key"):
                server.merge_start_images_to_data_url("a scene", "wide", ["data:image/png;base64,a", "data:image/png;base64,b"])

    def test_merge_start_images_returns_data_url_of_saved_output(self):
        png = b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "atlas_image_1_ab.jpg"
            out.write_bytes(png)
            with patch.object(server, "atlas_key", return_value=("secret", "atlas")), \
                 patch.object(server, "OUTPUTS_DIR", Path(tmp)), \
                 patch.object(server, "atlas_generate_image",
                              return_value=["/api/local-media?name=atlas_image_1_ab.jpg"]) as gen:
                data_url = server.merge_start_images_to_data_url(
                    "a castle by the sea", "wide",
                    ["data:image/png;base64,a", "data:image/png;base64,b"],
                )

        self.assertTrue(data_url.startswith("data:image/png;base64,"))
        args, kwargs = gen.call_args
        self.assertEqual(kwargs["source_image"], ["data:image/png;base64,a", "data:image/png;base64,b"])
        self.assertIn("Combine these 2 pictures", args[0])
        self.assertIn("a castle by the sea", args[0])

    def test_video_job_merges_start_images_before_engine(self):
        received = {}
        job_id = server.make_job("video")

        def fake_xai(prompt, aspect, seconds, model, key, start_image="", on_progress=None):
            received["start_image"] = start_image
            return {"url": "/api/local-media?name=xai.webm", "type": "video"}

        with patch.object(server, "merge_start_images_to_data_url",
                          return_value="data:image/png;base64,MERGED") as merge, \
             patch.object(server, "xai_key", return_value="xai-secret"), \
             patch.object(server, "xai_generate_video", side_effect=fake_xai):
            server.run_video_job(job_id, {
                "prompt": "two dogs on the moon",
                "model": "xai",
                "aspect": "wide",
                "seconds": 5,
                "startImages": ["data:image/png;base64,a", "data:image/png;base64,b"],
                "mergeStartImages": True,
            })

        merge.assert_called_once()
        self.assertEqual(received["start_image"], ["data:image/png;base64,MERGED"])
        self.assertEqual(server.get_job(job_id)["status"], "done")

    def test_video_job_merge_switch_ignored_for_single_image(self):
        job_id = server.make_job("video")

        def fake_xai(prompt, aspect, seconds, model, key, start_image="", on_progress=None):
            return {"url": "/api/local-media?name=xai.webm", "type": "video"}

        with patch.object(server, "merge_start_images_to_data_url") as merge, \
             patch.object(server, "xai_key", return_value="xai-secret"), \
             patch.object(server, "xai_generate_video", side_effect=fake_xai):
            server.run_video_job(job_id, {
                "prompt": "a dog", "model": "xai", "aspect": "wide", "seconds": 5,
                "startImages": ["data:image/png;base64,a"],
                "mergeStartImages": True,
            })

        merge.assert_not_called()
        self.assertEqual(server.get_job(job_id)["status"], "done")

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

        def fake_clip(prompt, aspect, seconds, model, key, start_image="", start_image_name="", on_progress=None,
                      negative_prompt="", seed=None, seed_pinned=False):
            calls.append((prompt, aspect, seconds, model, key, start_image, start_image_name,
                          negative_prompt, seed, seed_pinned))
            index = len(calls)
            return {
                "url": f"/api/local-media?name=atlas-segment{index}.webm",
                "type": "video",
                "mp4Url": f"/api/local-media?name=atlas-segment{index}.mp4",
                "mp4Path": f"/tmp/atlas-segment{index}.mp4",
            }

        with patch.object(server, "atlas_generate_video_clip", side_effect=fake_clip), \
             patch.object(server, "extract_last_frame_to_data_url",
                          return_value="data:image/png;base64,lastframe") as extract, \
             patch.object(server, "concat_mp4_paths_to_webm", return_value="/api/local-media?name=atlas-stitched.webm"):
            result = server.atlas_generate_video(
                "a long camera move", "wide", 30, "kling-v2.0", "secret",
                start_image="data:image/png;base64,abc", start_image_name="start.png",
                negative_prompt="blurry, watermark", seed=99,
        )

        self.assertEqual(result["url"], "/api/local-media?name=atlas-stitched.webm")
        self.assertEqual(len(result["segments"]), 2)
        self.assertNotIn("mp4Path", result["segments"][0])
        self.assertEqual([call[2] for call in calls], [15, 15])
        self.assertIn("Segment 1 of 2", calls[0][0])
        self.assertEqual(calls[0][5], "data:image/png;base64,abc")
        self.assertEqual(calls[0][6], "start.png")
        # Segment 2 chains from segment 1's last frame instead of running blind.
        extract.assert_called_once_with(Path("/tmp/atlas-segment1.mp4"))
        self.assertEqual(calls[1][5], "data:image/png;base64,lastframe")
        self.assertIn("final frame of the previous segment", calls[1][0])
        # Client negative prompt and pinned seed reach every segment unchanged.
        self.assertEqual([call[7] for call in calls], ["blurry, watermark"] * 2)
        self.assertEqual([call[8] for call in calls], [99, 99])
        self.assertEqual([call[9] for call in calls], [True, True])

    def test_chained_atlas_segments_stay_in_the_same_model_family(self):
        calls = []

        def fake_clip(prompt, aspect, seconds, model, key, start_image="", start_image_name="", on_progress=None,
                      negative_prompt="", seed=None, seed_pinned=False):
            calls.append((model, bool(start_image), seconds))
            index = len(calls)
            return {"url": f"/x{index}.webm", "type": "video", "mp4Path": f"/tmp/atlas-fam{index}.mp4"}

        # An env-overridden i2v model of another family must NOT hijack chained
        # continuations: they flip only the t2v suffix within the same family.
        with patch.object(server, "DEFAULT_ATLAS_I2V_MODEL", "kwaivgi/kling-v2.1/image-to-video"), \
             patch.object(server, "atlas_generate_video_clip", side_effect=fake_clip), \
             patch.object(server, "extract_last_frame_to_data_url", return_value="data:image/png;base64,f"), \
             patch.object(server, "concat_mp4_paths_to_webm", return_value="/stitched.webm"):
            server.atlas_generate_video("a story", "wide", 30, "", "secret")

        self.assertEqual(calls[0], (server.DEFAULT_ATLAS_VIDEO_MODEL, False, 15))
        self.assertEqual(calls[1], ("alibaba/wan-2.7/image-to-video", True, 15))

    def test_env_pinned_seed_stays_pinned_across_segments(self):
        seeds = []

        def fake_clip(prompt, aspect, seconds, model, key, start_image="", start_image_name="", on_progress=None,
                      negative_prompt="", seed=None, seed_pinned=False):
            seeds.append((seed, seed_pinned))
            index = len(seeds)
            return {"url": f"/x{index}.webm", "type": "video", "mp4Path": f"/tmp/atlas-env{index}.mp4"}

        with patch.object(server, "DEFAULT_ATLAS_WAN27_SEED", "123"), \
             patch.object(server, "atlas_generate_video_clip", side_effect=fake_clip), \
             patch.object(server, "extract_last_frame_to_data_url", return_value=""), \
             patch.object(server, "concat_mp4_paths_to_webm", return_value="/stitched.webm"):
            server.atlas_generate_video("a story", "wide", 30, "", "secret")

        self.assertEqual(seeds, [(123, True), (123, True)])

    def test_chained_segment_falls_back_to_unchained_on_handoff_failure(self):
        calls = []

        def fake_clip(prompt, aspect, seconds, model, key, start_image="", start_image_name="", on_progress=None,
                      negative_prompt="", seed=None, seed_pinned=False):
            calls.append((start_image, prompt))
            if start_image:
                raise server.AtlasHTTPError(403, "upload blocked by Cloudflare")
            index = len(calls)
            return {"url": f"/x{index}.webm", "type": "video", "mp4Path": f"/tmp/atlas-fb{index}.mp4"}

        with patch.object(server, "atlas_generate_video_clip", side_effect=fake_clip), \
             patch.object(server, "extract_last_frame_to_data_url", return_value="data:image/png;base64,f"), \
             patch.object(server, "concat_mp4_paths_to_webm", return_value="/stitched.webm"):
            result = server.atlas_generate_video("a story", "wide", 30, "", "secret")

        # Segment 2: chained attempt raised, unchained retry succeeded.
        self.assertEqual(result["url"], "/stitched.webm")
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1][0], "data:image/png;base64,f")
        self.assertEqual(calls[2][0], "")
        self.assertNotIn("final frame of the previous segment", calls[2][1])

    def test_long_atlas_video_shares_one_random_seed_across_segments(self):
        seeds = []

        def fake_clip(prompt, aspect, seconds, model, key, start_image="", start_image_name="", on_progress=None,
                      negative_prompt="", seed=None, seed_pinned=False):
            seeds.append((seed, seed_pinned))
            index = len(seeds)
            return {"url": f"/x{index}.webm", "type": "video", "mp4Path": f"/tmp/atlas-x{index}.mp4"}

        with patch.object(server, "atlas_generate_video_clip", side_effect=fake_clip), \
             patch.object(server, "extract_last_frame_to_data_url", return_value=""), \
             patch.object(server, "concat_mp4_paths_to_webm", return_value="/stitched.webm"):
            server.atlas_generate_video("a long camera move", "wide", 30, "", "secret")

        self.assertEqual(len(seeds), 2)
        self.assertEqual(seeds[0], seeds[1])
        self.assertGreaterEqual(seeds[0][0], 0)
        self.assertFalse(seeds[0][1])  # shared for consistency, not pinned by the client

    def test_long_atlas_video_returns_segments_when_stitching_is_unavailable(self):
        def fake_clip(prompt, aspect, seconds, model, key, start_image="", start_image_name="", on_progress=None,
                      negative_prompt="", seed=None, seed_pinned=False):
            index = 1 if seconds == 15 and start_image else 2
            return {
                "url": f"/api/local-media?name=atlas-segment{index}.webm",
                "type": "video",
                "mp4Url": f"/api/local-media?name=atlas-segment{index}.mp4",
                "mp4Path": f"/tmp/atlas-segment{index}.mp4",
                "model": "alibaba/wan-2.7/image-to-video",
            }

        with patch.object(server, "atlas_generate_video_clip", side_effect=fake_clip), \
             patch.object(server, "concat_mp4_paths_to_webm", return_value=None):
            result = server.atlas_generate_video(
                "a long camera move", "wide", 30, "kling-v2.0", "secret",
                start_image="data:image/png;base64,abc", start_image_name="start.png",
            )

        self.assertEqual(result["stitchStatus"], "segments")
        self.assertEqual(result["url"], "/api/local-media?name=atlas-segment1.webm")
        self.assertEqual(result["model"], "alibaba/wan-2.7/image-to-video")
        self.assertEqual(len(result["segments"]), 2)
        self.assertNotIn("mp4Path", result["segments"][0])


if __name__ == "__main__":
    unittest.main()
