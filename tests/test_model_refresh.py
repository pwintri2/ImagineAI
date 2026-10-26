import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class ModelRefreshTests(unittest.TestCase):
    def test_saved_previous_defaults_upgrade_without_rewriting_on_read(self):
        previous = {
            "geminiModel": "gemini-3.1-flash-image",
            "veoVideoModel": "veo-3.1-generate-preview",
            "xaiImageModel": "grok-imagine-image-quality",
            "xaiVideoModel": "grok-imagine-video",
            "atlasImageModel": "seedream-3.0",
            "atlasImageEditModel": "bytedance/seedream-v4.5/edit",
            "atlasVideoModel": "alibaba/wan-2.7/text-to-video",
            "seedanceVideoModel": "seedance-2-0",
            "defaultImageEngine": "atlas",
        }
        expected = {
            "geminiModel": server.DEFAULT_GEMINI_MODEL,
            "veoVideoModel": server.DEFAULT_VEO_VIDEO_MODEL,
            "xaiImageModel": server.DEFAULT_XAI_IMAGE_MODEL,
            "xaiVideoModel": server.DEFAULT_XAI_VIDEO_MODEL,
            "atlasImageModel": server.DEFAULT_ATLAS_IMAGE_MODEL,
            "atlasImageEditModel": server.DEFAULT_ATLAS_IMAGE_EDIT_MODEL,
            "atlasVideoModel": server.DEFAULT_ATLAS_VIDEO_MODEL,
            "seedanceVideoModel": server.DEFAULT_SEEDANCE_VIDEO_MODEL,
            "defaultImageEngine": "atlas",
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            original = json.dumps(previous)
            path.write_text(original)
            with patch.object(server, "SETTINGS_FILE", path):
                settings = server.load_settings()
            self.assertEqual({name: settings[name] for name in expected}, expected)
            self.assertEqual(path.read_text(), original)

    def test_custom_models_and_other_preferences_are_preserved(self):
        settings = {
            "geminiModel": "custom-image-model", "veoVideoModel": "custom-video-model",
            "atlasImageModel": "custom/image", "atlasImageEditModel": "custom/edit",
            "atlasVideoModel": "custom/video", "xaiImageModel": "custom-xai-image",
            "xaiVideoModel": "custom-xai-video", "seedanceVideoModel": "seedance-2-0-fast",
            "modelslabVideoModel": "wan2.2", "comfyUrl": "http://localhost:8188",
        }
        self.assertEqual(server.migrate_model_settings(settings), settings)

    def test_retired_google_previews_preserve_pro_image_tier_and_upgrade_video(self):
        for model in ("veo-2.0-generate-001", "veo-3.0-fast-generate-preview",
                      "veo-3.1-fast-generate-preview", "gemini-omni-flash-preview"):
            with self.subTest(model=model):
                result = server.migrate_model_settings({
                    "geminiModel": "gemini-3-pro-image-preview", "veoVideoModel": model,
                })
                self.assertEqual(result["geminiModel"], "gemini-3-pro-image")
                self.assertEqual(result["veoVideoModel"], server.DEFAULT_VEO_VIDEO_MODEL)

    def test_migration_respects_environment_selected_default(self):
        with patch.object(server, "DEFAULT_XAI_IMAGE_MODEL", "private-image-deployment"):
            self.assertEqual(server.migrate_model_settings({
                "xaiImageModel": "grok-imagine-image-quality",
            })["xaiImageModel"], "private-image-deployment")

    def test_settings_save_returns_and_persists_current_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            with patch.object(server, "SETTINGS_FILE", path), patch.object(server, "ensure_dirs"):
                result = server.save_settings({"xaiVideoModel": "grok-imagine-video"})
                self.assertEqual(result["xaiVideoModel"], server.DEFAULT_XAI_VIDEO_MODEL)
                self.assertEqual(json.loads(path.read_text()), result)
                self.assertEqual(server.load_settings(), result)

    def test_retired_sora_job_rejected_before_merging_or_generation(self):
        for model in ("sora", "sora2", "sora-2", "sora-2-pro", "sora-2-2025-12-08"):
            with self.subTest(model=model), patch.object(server, "load_settings", return_value={}), \
                    patch.object(server, "merge_start_images_to_data_url") as merge, \
                    patch.object(server, "sora_generate_video") as generate:
                job_id = server.make_job("video")
                try:
                    server.run_video_job(job_id, {
                        "model": model, "prompt": "a sailboat", "mergeStartImages": True,
                        "startImages": ["image-one", "image-two"],
                    })
                    job = server.get_job(job_id)
                    self.assertEqual(job["status"], "error")
                    self.assertEqual(job["error"], server.SORA_RETIREMENT_MESSAGE)
                    merge.assert_not_called()
                    generate.assert_not_called()
                finally:
                    with server.JOBS_LOCK:
                        server.JOBS.pop(job_id, None)

    def test_retired_sora_http_submission_returns_gone_without_a_job(self):
        handler = object.__new__(server.Handler)
        handler.path = "/api/generate/video"
        with patch.object(handler, "_read_json", return_value={"model": "sora", "prompt": "a sailboat"}), \
                patch.object(handler, "_json") as response, patch.object(server, "start_job") as start:
            handler.do_POST()
        response.assert_called_once_with(410, {"error": server.SORA_RETIREMENT_MESSAGE})
        start.assert_not_called()

    def test_current_xai_image_model_uses_existing_generation_contract(self):
        with patch.object(server, "xai_request_json", return_value={"data": [{"b64_json": "aW1hZ2U="}]}) as request, \
                patch.object(server, "save_output_bytes", return_value=("/image.jpg", Path("/image.jpg"), "image/jpeg")):
            server.xai_generate_image("a sailboat", "wide", 2, server.DEFAULT_XAI_IMAGE_MODEL, "test-key")
        self.assertEqual(request.call_args.args[0], "/images/generations")
        payload = request.call_args.args[2]
        self.assertEqual(payload["model"], "grok-imagine-image-2.0")
        self.assertEqual(payload["n"], 2)
        self.assertEqual(payload["aspect_ratio"], "16:9")
        self.assertEqual(payload["response_format"], "b64_json")


if __name__ == "__main__":
    unittest.main()
