import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class SeedanceTests(unittest.TestCase):
    def test_seedance_key_uses_saved_alias(self):
        with patch.object(server, "load_secrets", return_value={"seedance": "seedance-secret"}), \
             patch.dict(os.environ, {"SEEDANCE_API_KEY": "", "SEEDANCE2_API_KEY": "", "SEEDANCE2AI_API_KEY": ""}):
            self.assertEqual(server.seedance_key(), ("seedance-secret", "seedance"))

    def test_seedance_env_key_takes_precedence(self):
        with patch.object(server, "load_secrets", return_value={"seedance": "saved-secret"}), \
             patch.dict(os.environ, {"SEEDANCE_API_KEY": "env-secret", "SEEDANCE2_API_KEY": "", "SEEDANCE2AI_API_KEY": ""}):
            self.assertEqual(server.seedance_key(), ("env-secret", "SEEDANCE_API_KEY"))

    def test_seedance_start_video_task_payload_matches_public_api(self):
        calls = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            calls.append((path, key, payload, method, timeout))
            return {"taskId": "task-1"}

        with patch.object(server, "seedance_request_json", side_effect=fake_request):
            task_id = server.seedance_start_video_task(
                "a cat surfing",
                "wide",
                30,
                "seedance-2-0",
                "secret",
                return_last_frame=True,
                generate_audio=False,
            )

        self.assertEqual(task_id, "task-1")
        self.assertEqual(calls[0][0], "/v1/videos/generations")
        self.assertEqual(calls[0][1], "secret")
        self.assertEqual(calls[0][3], "POST")
        self.assertEqual(calls[0][2], {
            "model": "seedance-2-0",
            "input": {
                "prompt": "a cat surfing",
                "generation_type": "text-to-video",
                "duration": 15,
                "aspect_ratio": "16:9",
                "resolution": "720p",
                "generate_audio": False,
                "watermark": False,
                "web_search": False,
                "return_last_frame": True,
                "seed": -1,
            },
        })

    def test_seedance_generate_video_downloads_completed_result(self):
        calls = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            calls.append((path, method))
            if path == "/v1/videos/generations":
                return {"taskId": "task-1"}
            if path == "/v1/tasks/task-1":
                return {
                    "id": "task-1",
                    "status": "completed",
                    "data": {"results": ["https://cdn.example.test/video.mp4"]},
                }
            raise AssertionError(f"Unexpected path {path}")

        with patch.object(server, "seedance_request_json", side_effect=fake_request), \
             patch.object(server, "download_url_to_output", return_value=("/api/local-media?name=seedance.mp4", Path("seedance.mp4"), "seedance.mp4")), \
             patch.object(server, "transcode_mp4_path_to_webm", return_value="/api/local-media?name=seedance.webm"):
            result = server.seedance_generate_video("a cat surfing", "wide", 5, "seedance-2-0", "secret")

        self.assertEqual(result["url"], "/api/local-media?name=seedance.webm")
        self.assertEqual(result["mp4Url"], "/api/local-media?name=seedance.mp4")
        self.assertEqual(calls, [("/v1/videos/generations", "POST"), ("/v1/tasks/task-1", "GET")])

    def test_seedance_image_uses_last_frame_url(self):
        polls = []

        def fake_start(prompt, aspect, seconds, model, key, return_last_frame=False, generate_audio=True):
            self.assertEqual(seconds, server.SEEDANCE_STILL_SECONDS)
            self.assertTrue(return_last_frame)
            self.assertFalse(generate_audio)
            return "task-1"

        def fake_poll(task_id, key, on_progress=None, timeout=server.SEEDANCE_VIDEO_TIMEOUT, interval=10):
            polls.append((task_id, key))
            return {
                "id": task_id,
                "status": "completed",
                "data": {"results": ["https://cdn.example.test/video.mp4"], "last_frame_url": "https://cdn.example.test/frame.png"},
            }

        with patch.object(server, "seedance_start_video_task", side_effect=fake_start), \
             patch.object(server, "seedance_poll_result", side_effect=fake_poll), \
             patch.object(server, "download_url_to_output", return_value=("/api/local-media?name=frame.png", Path("frame.png"), "frame.png")) as download:
            urls = server.seedance_generate_image("a poster frame", "square", 1, "seedance-2-0", "secret")

        self.assertEqual(urls, ["/api/local-media?name=frame.png"])
        self.assertEqual(polls, [("task-1", "secret")])
        download.assert_called_once_with("https://cdn.example.test/frame.png", "seedance_image", ".png", timeout=600)

    def test_long_seedance_video_is_stitched_from_valid_segments(self):
        calls = []

        def fake_clip(prompt, aspect, seconds, model, key, on_progress=None):
            calls.append((prompt, aspect, seconds, model, key))
            index = len(calls)
            return {
                "url": f"/api/local-media?name=seedance-segment{index}.webm",
                "type": "video",
                "mp4Url": f"/api/local-media?name=seedance-segment{index}.mp4",
                "mp4Path": f"/tmp/seedance-segment{index}.mp4",
                "model": model,
            }

        with patch.object(server, "seedance_generate_video_clip", side_effect=fake_clip), \
             patch.object(server, "concat_mp4_paths_to_webm", return_value="/api/local-media?name=seedance-stitched.webm"):
            result = server.seedance_generate_video("a long scene", "wide", 30, "seedance-2-0", "secret")

        self.assertEqual(result["url"], "/api/local-media?name=seedance-stitched.webm")
        self.assertEqual(len(result["segments"]), 2)
        self.assertNotIn("mp4Path", result["segments"][0])
        self.assertEqual([call[2] for call in calls], [15, 15])
        self.assertIn("Segment 1 of 2", calls[0][0])

    def test_seedance_segment_lengths_keep_provider_minimum(self):
        self.assertEqual(server.seedance_video_segment_lengths(16), [12, 4])
        self.assertEqual(server.seedance_video_segment_lengths(19), [15, 4])
        self.assertEqual(server.seedance_video_segment_lengths(20), [15, 5])


if __name__ == "__main__":
    unittest.main()
