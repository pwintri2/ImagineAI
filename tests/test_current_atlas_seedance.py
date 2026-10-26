import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class CurrentAtlasSeedanceTests(unittest.TestCase):
    def test_atlas_video_env_family_and_i2v_override_precedence(self):
        model_env_keys = ("ATLAS_VIDEO_MODEL", "ATLASCLOUD_VIDEO_MODEL",
                          "ATLAS_I2V_MODEL", "ATLASCLOUD_I2V_MODEL")
        cases = (
            ({"ATLAS_VIDEO_MODEL": "alibaba/wan-2.7/text-to-video"}, "alibaba/wan-2.7/image-to-video"),
            ({"ATLASCLOUD_VIDEO_MODEL": "alibaba/wan-3.0-prime/text-to-video"}, "alibaba/wan-3.0-prime/image-to-video"),
            ({"ATLAS_VIDEO_MODEL": "alibaba/wan-2.7/text-to-video",
              "ATLASCLOUD_I2V_MODEL": "custom/cloud-image-to-video"}, "custom/cloud-image-to-video"),
            ({"ATLAS_VIDEO_MODEL": "alibaba/wan-2.7/text-to-video",
              "ATLASCLOUD_I2V_MODEL": "custom/cloud-image-to-video",
              "ATLAS_I2V_MODEL": "custom/primary-image-to-video"}, "custom/primary-image-to-video"),
        )
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                env = {key: value for key, value in os.environ.items() if key not in model_env_keys}
                env.update(overrides)
                completed = subprocess.run(
                    [sys.executable, "-c", "import json, server; print(json.dumps(server.atlas_video_model_id('', True)))"],
                    cwd=ROOT, env=env, check=True, capture_output=True, text=True,
                )
                self.assertEqual(json.loads(completed.stdout), expected)

    def atlas_video_payload(self, model, seconds=30, start_image="", **kwargs):
        with patch.object(server, "atlas_request_json", return_value={"data": {"id": "vid-1"}}) as submit, \
             patch.object(server, "atlas_poll_result", return_value={"outputs": ["https://example.test/video.mp4"]}), \
             patch.object(server, "atlas_upload_media", return_value="https://example.test/first.png"), \
             patch.object(server, "download_url_to_output", return_value=("/video.mp4", Path("/tmp/video.mp4"), "video.mp4")), \
             patch.object(server, "transcode_mp4_path_to_webm", return_value=None):
            server.atlas_generate_video_clip("a mountain", "wide", seconds, model, "secret",
                                             start_image=start_image, **kwargs)
        return submit.call_args.args[2]

    def test_wan30_text_payload_uses_its_own_schema(self):
        payload = self.atlas_video_payload("alibaba/wan-3.0/text-to-video", seed=42)
        self.assertEqual(payload, {
            "model": "alibaba/wan-3.0/text-to-video", "prompt": "a mountain",
            "duration": 30, "resolution": "1080p", "audio": True,
            "seed": 42, "ratio": "16:9",
        })

    def test_wan30_image_payload_omits_ratio_and_legacy_options(self):
        payload = self.atlas_video_payload("alibaba/wan-3.0/text-to-video", start_image="data:image/png;base64,AA==")
        self.assertEqual(payload["model"], "alibaba/wan-3.0/image-to-video")
        self.assertEqual(payload["image"], "https://example.test/first.png")
        for field in ("ratio", "aspect_ratio", "negative_prompt", "prompt_extend"):
            self.assertNotIn(field, payload)

    def test_wan30_native_and_stitched_durations_avoid_one_second_segments(self):
        for model in ("alibaba/wan-3.0/text-to-video", "alibaba/wan-3.0-prime/text-to-video"):
            self.assertEqual(server.atlas_video_segment_lengths(30, model), [30])
            self.assertEqual(server.atlas_video_segment_lengths(31, model), [29, 2])
            self.assertEqual(server.atlas_video_segment_lengths(60, model), [30, 30])
        self.assertEqual(server.atlas_video_segment_lengths(30, "alibaba/wan-2.7/text-to-video"), [15, 15])

    def test_explicit_wan27_alias_is_preserved(self):
        self.assertEqual(server.atlas_video_model_id("wan2.7", False), "alibaba/wan-2.7/text-to-video")
        self.assertEqual(server.atlas_video_model_id("wan3.0", True), "alibaba/wan-3.0/image-to-video")

    def test_wan30_settings_are_model_specific(self):
        with patch.object(server, "DEFAULT_ATLAS_WAN30_RESOLUTION", "720P"), \
             patch.object(server, "DEFAULT_ATLAS_WAN30_AUDIO", False), \
             patch.object(server, "DEFAULT_ATLAS_WAN30_SEED", "77"), \
             patch.object(server, "DEFAULT_ATLAS_WAN27_SEED", "12"):
            payload = self.atlas_video_payload("alibaba/wan-3.0/text-to-video")
        self.assertEqual((payload["resolution"], payload["audio"], payload["seed"]), ("720p", False, 77))

    def test_seedream5_generation_and_edit_presets_match_schema(self):
        for source, model in (
            ("", "bytedance/seedream-v5.0-pro/text-to-image"),
            ("data:image/png;base64,AA==", "bytedance/seedream-v5.0-pro/edit"),
        ):
            with self.subTest(model=model), \
                 patch.object(server, "atlas_request_json", return_value={"data": {"id": "img-1"}}) as submit, \
                 patch.object(server, "atlas_poll_result", return_value={"outputs": ["https://example.test/image.png"]}), \
                 patch.object(server, "atlas_upload_media", return_value="https://example.test/ref.png"), \
                 patch.object(server, "download_url_to_output", return_value=("/image.png", Path("/tmp/image.png"), "image.png")):
                server.atlas_generate_image("a mountain", "wide", 1, model, "secret", source_image=source)
            payload = submit.call_args.args[2]
            self.assertEqual(payload["size"], "2816*1584")
            self.assertEqual(payload["output_format"], "png")
            if source:
                self.assertEqual(payload["images"], ["https://example.test/ref.png"])
            else:
                self.assertNotIn("images", payload)

    def test_seedream5_rejects_excess_references_before_upload(self):
        with patch.object(server, "atlas_upload_media") as upload:
            with self.assertRaisesRegex(ValueError, "at most 10"):
                server.atlas_generate_image("combine", "wide", 1, "bytedance/seedream-v5.0-pro/edit", "secret",
                                             source_image=["data:image/png;base64,AA=="] * 11)
        upload.assert_not_called()

    def test_seedance25_accepts_thirty_seconds_without_seed(self):
        with patch.object(server, "seedance_request_json", return_value={"taskId": "task-1"}) as submit:
            server.seedance_start_video_task("a mountain", "wide", 30, "seedance-2-5", "secret",
                                             seed=42, return_last_frame=True)
        payload = submit.call_args.args[2]
        self.assertEqual(payload["model"], "seedance-2-5")
        self.assertEqual(payload["input"]["duration"], 30)
        self.assertTrue(payload["input"]["return_last_frame"])
        self.assertNotIn("seed", payload["input"])
        self.assertEqual(server.seedance_video_segment_lengths(30, "seedance-2-5"), [30])

    def test_seedance25_avoids_unsupported_4k_resolution(self):
        with patch.object(server, "DEFAULT_SEEDANCE_RESOLUTION", "4k"), \
             patch.object(server, "seedance_request_json", return_value={"taskId": "task-1"}) as submit:
            server.seedance_start_video_task("a mountain", "wide", 5, "seedance-2-5", "secret")
        self.assertEqual(submit.call_args.args[2]["input"]["resolution"], "720p")


if __name__ == "__main__":
    unittest.main()
