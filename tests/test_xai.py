import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class XaiTests(unittest.TestCase):
    def test_long_xai_video_returns_segments_when_stitching_is_unavailable(self):
        calls = []

        def fake_clip(prompt, aspect, duration, model, key, start_image="", on_progress=None):
            calls.append((prompt, aspect, duration, model, key, start_image))
            index = len(calls)
            return {
                "url": f"/api/local-media?name=xai-segment{index}.webm",
                "type": "video",
                "mp4Url": f"/api/local-media?name=xai-segment{index}.mp4",
                "mp4Path": f"/tmp/xai-segment{index}.mp4",
            }

        with patch.object(server, "xai_generate_video_clip", side_effect=fake_clip), \
             patch.object(server, "concat_mp4_paths_to_webm", return_value=None):
            result = server.xai_generate_video(
                "a long camera move", "wide", 20, "grok-imagine-video", "secret",
                start_image="data:image/png;base64,abc",
            )

        self.assertEqual(result["stitchStatus"], "segments")
        self.assertEqual(result["url"], "/api/local-media?name=xai-segment1.webm")
        self.assertEqual(len(result["segments"]), 2)
        self.assertNotIn("mp4Path", result["segments"][0])
        self.assertEqual([call[2] for call in calls], [15, 5])
        self.assertEqual(calls[0][5], "data:image/png;base64,abc")
        self.assertEqual(calls[1][5], "")


if __name__ == "__main__":
    unittest.main()
