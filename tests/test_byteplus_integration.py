import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


class BytePlusIntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for name, value in (("DATA_DIR", root), ("OUTPUTS_DIR", root / "outputs"),
                            ("SETTINGS_FILE", root / "settings.json"),
                            ("SECRETS_FILE", root / "secrets.json")):
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_keys_stay_with_their_provider_and_unknown_labels_are_not_guessed(self):
        server.save_secret("seedance", "seevio-key")
        server.save_secret("seedance-2-5", "unclassified-key")
        self.assertEqual(server.seedance_key(), ("seevio-key", "seedance"))
        self.assertEqual(server.byteplus_key()[0], "")
        server.save_secret("byteplus", "ark-key")
        self.assertEqual(server.byteplus_key(), ("ark-key", "byteplus"))
        with patch.dict(os.environ, {"ARK_API_KEY": "env-ark"}):
            self.assertEqual(server.byteplus_key(), ("env-ark", "ARK_API_KEY"))

    def test_service_setting_is_validated_and_models_are_separate(self):
        saved = server.save_settings({"seedanceService": "byteplus",
                                      "byteplusVideoModel": "ep-private",
                                      "seedanceVideoModel": "seedance-2-0-fast"})
        self.assertEqual(saved["byteplusVideoModel"], "ep-private")
        self.assertEqual(saved["seedanceVideoModel"], "seedance-2-0-fast")
        with self.assertRaises(ValueError):
            server.save_settings({"seedanceService": "unknown"})
        self.assertEqual(server.load_settings()["seedanceService"], "byteplus")

    def test_video_config_does_not_treat_seevio_key_as_byteplus_ready(self):
        server.save_secret("seedance", "seevio-key")
        server.save_settings({"seedanceService": "byteplus"})
        handler = server.Handler.__new__(server.Handler)
        with patch.object(server, "detect_models", return_value={"reachable": False}):
            config = handler.api_config()
        self.assertFalse(config["seedanceConfigured"])
        self.assertTrue(config["seevioConfigured"])
        self.assertFalse(config["byteplusConfigured"])
        self.assertEqual(config["seedanceService"], "byteplus")
        self.assertNotIn("seevio-key", json.dumps(config))

    def test_selected_byteplus_job_ignores_seevio_model_override(self):
        server.save_secret("byteplus", "ark-key")
        server.save_secret("seedance", "seevio-key")
        server.save_settings({"seedanceService": "byteplus", "byteplusVideoModel": "ep-private"})
        job_id = server.make_job("video")
        with patch.object(server, "byteplus_generate_video", return_value={"url": "/video.mp4"}) as generate, \
             patch.object(server, "seedance_generate_video") as seevio:
            server.run_video_job(job_id, {"model": "seedance", "prompt": "test", "seconds": 8,
                                         "seedanceVideoModel": "seedance-2-5", "startImage": "frame-data"})
        seevio.assert_not_called()
        self.assertEqual(generate.call_args.args, ("test", "wide", 8, "ep-private", "ark-key"))
        self.assertEqual(generate.call_args.kwargs["start_image"], "frame-data")
        job = server.get_job(job_id)
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["meta"]["seedanceService"], "byteplus")

    def test_missing_byteplus_key_fails_without_using_seevio(self):
        server.save_secret("seedance", "seevio-key")
        server.save_settings({"seedanceService": "byteplus"})
        job_id = server.make_job("video")
        with patch.object(server, "byteplus_generate_video") as generate, \
             patch.object(server, "seedance_generate_video") as seevio:
            server.run_video_job(job_id, {"model": "seedance", "prompt": "test"})
        generate.assert_not_called()
        seevio.assert_not_called()
        self.assertIn("No BytePlus ModelArk API key", server.get_job(job_id)["error"])

    def test_seevio_selection_does_not_use_byteplus(self):
        server.save_secret("seedance", "seevio-key")
        server.save_secret("byteplus", "ark-key")
        server.save_settings({"seedanceService": "seevio"})
        job_id = server.make_job("video")
        with patch.object(server, "byteplus_generate_video") as byteplus, \
             patch.object(server, "seedance_generate_video", return_value={"url": "/video.mp4"}) as generate:
            server.run_video_job(job_id, {"model": "seedance", "prompt": "test", "seconds": 8})
        byteplus.assert_not_called()
        self.assertEqual(generate.call_args.args[-1], "seevio-key")
        self.assertEqual(server.get_job(job_id)["meta"]["seedanceService"], "seevio")

    def test_byteplus_wrapper_downloads_and_normalizes_uploaded_frame(self):
        frame = "data:image/png;base64,aGVsbG8="
        with patch.object(server.byteplus, "start_task", return_value="task-one") as create, \
             patch.object(server.byteplus, "poll_result", return_value={"video_url": "https://cdn.example/video.mp4"}), \
             patch.object(server, "download_url_to_output", return_value=("/out.mp4", Path("/out.mp4"), "out.mp4")) as download, \
             patch.object(server, "transcode_mp4_path_to_webm", return_value=None):
            result = server.byteplus_generate_video("test", "tall", 8, "ep-custom", "key", start_image=frame)
        self.assertEqual(create.call_args.args, (server.BYTEPLUS_BASE, "key", "test", "9:16", 8, "ep-custom"))
        self.assertEqual(create.call_args.kwargs["first_frame_url"], frame)
        self.assertNotIn("seed", create.call_args.kwargs)
        download.assert_called_once()
        self.assertEqual(result["byteplusTaskId"], "task-one")
        self.assertEqual(result["mp4Url"], "/out.mp4")
        self.assertNotIn("mp4Path", result)

    def test_provider_error_has_actionable_hint_without_retry(self):
        failure = server.byteplus.BytePlusHTTPError(403, "Model not activated", "ModelNotOpen")
        with patch.object(server.byteplus, "start_task", side_effect=failure) as create:
            with self.assertRaisesRegex(RuntimeError, "Activate.*Seedance"):
                server.byteplus_generate_video("test", "wide", 8, "model", "key")
        create.assert_called_once()


if __name__ == "__main__":
    unittest.main()
