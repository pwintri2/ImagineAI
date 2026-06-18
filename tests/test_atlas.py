import os
import sys
import unittest
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
        self.assertEqual(calls[0], ("/model/generateVideo", {"model": "kling-v2.0", "prompt": "a rocket launch"}, "POST"))
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
            "model": "kling-v2.0",
            "prompt": "make the image move",
            "image_url": "https://upload.example.test/start.png",
        }])


if __name__ == "__main__":
    unittest.main()
