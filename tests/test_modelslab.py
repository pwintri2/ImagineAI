import io
import os
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class ModelsLabTests(unittest.TestCase):
    def test_fetch_image_uses_current_path_endpoint(self):
        calls = []

        def fake_request(path, payload, timeout=120):
            calls.append((path, payload, timeout))
            return {"status": "success", "output": ["https://example.test/out.png"]}

        with patch.object(server, "modelslab_request_json", side_effect=fake_request):
            result = server.modelslab_fetch_image("abc 123", "secret")

        self.assertEqual(result["status"], "success")
        self.assertEqual(calls, [
            ("/api/v6/images/fetch/abc%20123", {"key": "secret"}, 120),
        ])

    def test_extract_urls_accepts_proxy_link_maps_and_future_links(self):
        data = {
            "output": ["https://example.test/a.png"],
            "proxy_links": {"0": "https://cdn.example.test/a.png"},
            "future_links": ["https://future.example.test/a.png", "not-a-url"],
        }

        self.assertEqual(server.modelslab_extract_urls(data), [
            "https://example.test/a.png",
            "https://cdn.example.test/a.png",
            "https://future.example.test/a.png",
        ])

    def test_http_400_processing_payload_is_treated_as_async_result(self):
        err = urllib.error.HTTPError(
            url="https://modelslab.com/api/v6/images/text2img",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"status":"processing","id":123,"eta":10}'),
        )

        with patch("urllib.request.urlopen", side_effect=err):
            result = server.modelslab_request_json("/api/v6/images/text2img", {"key": "secret"})

        self.assertEqual(result["status"], "processing")
        self.assertEqual(result["id"], 123)

    def test_free_api_alias_is_usable_as_modelslab_key(self):
        with patch.object(server, "load_secrets", return_value={"free-api": "free-secret"}), \
             patch.dict(os.environ, {"MODELSLAB_API_KEY": ""}):
            self.assertEqual(server.modelslab_key(), ("free-secret", "free-api"))

    def test_wan26_alias_is_usable_as_modelslab_key(self):
        with patch.object(server, "load_secrets", return_value={"wan2.6-t2v": "wan26-secret"}), \
             patch.dict(os.environ, {"MODELSLAB_API_KEY": ""}):
            self.assertEqual(server.modelslab_key(), ("wan26-secret", "wan2.6-t2v"))

    def test_video_payload_uses_modelslab_minimum_fps(self):
        calls = []

        def fake_request(path, payload, timeout=120):
            calls.append((path, payload, timeout))
            return {"status": "success", "output": ["https://example.test/video.mp4"]}

        with patch.object(server, "modelslab_request_json", side_effect=fake_request), \
             patch.object(server, "download_url_to_output", return_value=("/api/local-media?name=video.mp4", Path("video.mp4"), "video.mp4")), \
             patch.object(server, "transcode_mp4_path_to_webm", return_value=None):
            result = server.modelslab_generate_video("a wave", "wide", 1, "wan2.2", "secret")

        self.assertEqual(result["url"], "/api/local-media?name=video.mp4")
        self.assertEqual(calls[0][0], "/api/v6/video/text2video")
        self.assertEqual(calls[0][1]["fps"], 16)
        self.assertGreaterEqual(calls[0][1]["num_frames"], 16)

    def test_long_modelslab_video_is_stitched_from_segments(self):
        calls = []

        def fake_clip(prompt, aspect, seconds, model, key, on_progress=None):
            calls.append((prompt, aspect, seconds, model, key))
            index = len(calls)
            return {
                "url": f"/api/local-media?name=segment{index}.webm",
                "type": "video",
                "mp4Url": f"/api/local-media?name=segment{index}.mp4",
                "mp4Path": f"/tmp/segment{index}.mp4",
            }

        with patch.object(server, "modelslab_generate_video_clip", side_effect=fake_clip), \
             patch.object(server, "concat_mp4_paths_to_webm", return_value="/api/local-media?name=stitched.webm"):
            result = server.modelslab_generate_video("a wave", "wide", 12, "wan2.2", "secret")

        self.assertEqual(result["url"], "/api/local-media?name=stitched.webm")
        self.assertEqual(len(result["segments"]), 3)
        self.assertNotIn("mp4Path", result["segments"][0])
        self.assertEqual([call[2] for call in calls], [5, 5, 2])
        self.assertIn("Segment 1 of 3", calls[0][0])

    def test_wan26_video_choice_uses_modelslab_model_id(self):
        calls = []
        job_id = server.make_job("video")

        def fake_generate(prompt, aspect, seconds, model, key, on_progress=None):
            calls.append((prompt, aspect, seconds, model, key))
            return {"url": "/api/local-media?name=wan26.mp4", "type": "video"}

        with patch.object(server, "modelslab_key", return_value=("secret", "modelslab")), \
             patch.object(server, "modelslab_generate_video", side_effect=fake_generate):
            server.run_video_job(job_id, {
                "prompt": "a glass city at sunrise",
                "aspect": "wide",
                "seconds": 6,
                "model": "wan2.6-t2v",
            })

        self.assertEqual(calls, [("a glass city at sunrise", "wide", 6, "wan2.6-t2v", "secret")])
        job = server.get_job(job_id)
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["meta"]["modelTitle"], "wan2.6-t2v")
        self.assertEqual(job["meta"]["model"], "wan2.6-t2v")


if __name__ == "__main__":
    unittest.main()
