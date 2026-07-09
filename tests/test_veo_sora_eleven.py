import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class VeoTests(unittest.TestCase):
    def test_veo_segment_lengths_only_use_valid_durations(self):
        self.assertEqual(server.veo_video_segment_lengths(8), [8])
        self.assertEqual(server.veo_video_segment_lengths(4), [4])
        self.assertEqual(server.veo_video_segment_lengths(10), [6, 4])
        self.assertEqual(server.veo_video_segment_lengths(9), [8])  # odd totals round down
        segments = server.veo_video_segment_lengths(60)
        self.assertEqual(sum(segments), 60)
        self.assertTrue(all(s in (4, 6, 8) for s in segments))

    def test_veo_clip_payload_and_download(self):
        calls = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            calls.append((path, payload, method))
            if path.endswith(":predictLongRunning"):
                return {"name": "models/veo-3.1-generate-preview/operations/op-1"}
            return {"done": True, "response": {"generateVideoResponse": {
                "generatedSamples": [{"video": {"uri": "https://example.test/video?x=1"}}]}}}

        with patch.object(server, "veo_request_json", side_effect=fake_request), \
             patch.object(server, "veo_download_video",
                          return_value=("/api/local-media?name=veo.mp4", Path("/tmp/veo.mp4"))), \
             patch.object(server, "transcode_mp4_path_to_webm", return_value="/api/local-media?name=veo.webm"):
            result = server.veo_generate_video_clip(
                "a red kite over dunes", "tall", 8, "", "secret",
                negative_prompt="blurry", seed=42)

        self.assertEqual(result["url"], "/api/local-media?name=veo.webm")
        self.assertEqual(result["mp4Url"], "/api/local-media?name=veo.mp4")
        start_path, payload, method = calls[0]
        self.assertIn("veo-3.1-generate-preview:predictLongRunning", start_path)
        self.assertEqual(method, "POST")
        self.assertEqual(payload["instances"][0], {"prompt": "a red kite over dunes"})
        self.assertEqual(payload["parameters"]["aspectRatio"], "9:16")
        self.assertEqual(payload["parameters"]["durationSeconds"], "8")
        self.assertEqual(payload["parameters"]["negativePrompt"], "blurry")
        self.assertEqual(payload["parameters"]["seed"], 42)
        self.assertEqual(calls[1][0], "models/veo-3.1-generate-preview/operations/op-1")

    def test_veo_clip_retries_without_extras_on_400(self):
        calls = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            calls.append((path, payload))
            if path.endswith(":predictLongRunning"):
                if "negativePrompt" in (payload or {}).get("parameters", {}):
                    raise server.VeoHTTPError(400, "Unknown field negativePrompt")
                return {"name": "models/m/operations/op-1"}
            return {"done": True, "response": {"generateVideoResponse": {
                "generatedSamples": [{"video": {"uri": "https://example.test/v"}}]}}}

        with patch.object(server, "veo_request_json", side_effect=fake_request), \
             patch.object(server, "veo_download_video",
                          return_value=("/api/local-media?name=veo.mp4", Path("/tmp/veo.mp4"))), \
             patch.object(server, "transcode_mp4_path_to_webm", return_value=None):
            result = server.veo_generate_video_clip("a kite", "wide", 8, "", "secret",
                                                    negative_prompt="blurry")

        self.assertEqual(result["url"], "/api/local-media?name=veo.mp4")
        self.assertNotIn("negativePrompt", calls[1][1]["parameters"])

    def test_long_veo_video_chains_and_stitches(self):
        clip_calls = []

        def fake_clip(prompt, aspect, duration, model, key, start_image="", on_progress=None,
                      negative_prompt="", seed=None):
            clip_calls.append((duration, bool(start_image), prompt))
            index = len(clip_calls)
            return {"url": f"/x{index}.webm", "type": "video",
                    "mp4Url": f"/x{index}.mp4", "mp4Path": f"/tmp/veo-{index}.mp4",
                    "model": "veo-3.1-generate-preview"}

        with patch.object(server, "veo_generate_video_clip", side_effect=fake_clip), \
             patch.object(server, "extract_last_frame_to_data_url",
                          return_value="data:image/png;base64,frame"), \
             patch.object(server, "stitch_video_paths",
                          return_value={"url": "/stitched.webm", "mp4Url": "/stitched.mp4"}):
            result = server.veo_generate_video("a story", "wide", 16, "", "secret")

        self.assertEqual(result["url"], "/stitched.webm")
        self.assertEqual(result["mp4Url"], "/stitched.mp4")
        self.assertEqual([c[0] for c in clip_calls], [8, 8])
        self.assertFalse(clip_calls[0][1])
        self.assertTrue(clip_calls[1][1])  # chained from the previous last frame
        self.assertIn("final frame of the previous segment", clip_calls[1][2])
        self.assertNotIn("mp4Path", result)


class SoraTests(unittest.TestCase):
    def test_sora_plan_segments(self):
        self.assertEqual(server.sora_plan_segments(8), (8, []))
        self.assertEqual(server.sora_plan_segments(4), (4, []))
        self.assertEqual(server.sora_plan_segments(30), (12, [16]))
        first, chunks = server.sora_plan_segments(60)
        self.assertEqual(first + sum(chunks), 60)
        self.assertLessEqual(len(chunks), 6)

    def test_sora_single_request_flow(self):
        calls = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            calls.append((path, payload, method))
            if path == "videos":
                return {"id": "video_1", "status": "queued"}
            return {"id": "video_1", "status": "completed", "progress": 100}

        with patch.object(server, "sora_request_json", side_effect=fake_request), \
             patch.object(server, "sora_download_video",
                          return_value=("/api/local-media?name=sora.mp4", Path("/tmp/sora.mp4"))), \
             patch.object(server, "probe_video_duration", return_value=8.0), \
             patch.object(server, "transcode_mp4_path_to_webm", return_value="/api/local-media?name=sora.webm"):
            result = server.sora_generate_video("a fox in snow", "wide", 8, "", "secret")

        self.assertEqual(result["url"], "/api/local-media?name=sora.webm")
        self.assertEqual(result["mp4Url"], "/api/local-media?name=sora.mp4")
        self.assertEqual(calls[0][0], "videos")
        self.assertEqual(calls[0][1]["seconds"], "8")
        self.assertEqual(calls[0][1]["size"], "1280x720")

    def test_sora_extensions_full_video_download(self):
        requests = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            requests.append((path, payload))
            if path == "videos":
                return {"id": "video_1"}
            if path == "videos/extensions":
                return {"id": f"video_{len([r for r in requests if r[0] == 'videos/extensions']) + 1}"}
            return {"id": "x", "status": "completed", "progress": 100}

        downloads = []

        def fake_download(video_id, key):
            downloads.append(video_id)
            return f"/api/local-media?name={video_id}.mp4", Path(f"/tmp/{video_id}.mp4")

        # The final extension holds the whole 24s video -> one download, no stitching.
        with patch.object(server, "sora_request_json", side_effect=fake_request), \
             patch.object(server, "sora_download_video", side_effect=fake_download), \
             patch.object(server, "probe_video_duration", return_value=24.0), \
             patch.object(server, "transcode_mp4_path_to_webm", return_value=None):
            result = server.sora_generate_video("a fox", "tall", 24, "sora-2", "secret")

        self.assertEqual(downloads, ["video_2"])
        self.assertEqual(result["mp4Url"], "/api/local-media?name=video_2.mp4")
        ext = next(p for path, p in requests if path == "videos/extensions")
        self.assertEqual(ext["video"], {"id": "video_1"})
        self.assertEqual(ext["seconds"], "12")

    def test_sora_extensions_fall_back_to_stitching_when_partial(self):
        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "videos":
                return {"id": "video_1"}
            if path == "videos/extensions":
                return {"id": "video_2"}
            return {"id": "x", "status": "completed", "progress": 100}

        downloads = []

        def fake_download(video_id, key):
            downloads.append(video_id)
            return f"/x-{video_id}.mp4", Path(f"/tmp/{video_id}.mp4")

        with patch.object(server, "sora_request_json", side_effect=fake_request), \
             patch.object(server, "sora_download_video", side_effect=fake_download), \
             patch.object(server, "probe_video_duration", return_value=12.0), \
             patch.object(server, "stitch_video_paths",
                          return_value={"url": "/stitched.webm", "mp4Url": "/stitched.mp4"}) as stitched:
            result = server.sora_generate_video("a fox", "wide", 24, "sora-2", "secret")

        self.assertEqual(result["url"], "/stitched.webm")
        self.assertEqual(downloads, ["video_2", "video_1"])  # final first, then the earlier stage
        paths = stitched.call_args[0][0]
        self.assertEqual([p.name for p in paths], ["video_1.mp4", "video_2.mp4"])  # stitched in order

    def test_sora_failed_job_raises_with_provider_message(self):
        def fake_request(path, key, payload=None, method="GET", timeout=120):
            if path == "videos":
                return {"id": "video_1"}
            return {"id": "video_1", "status": "failed",
                    "error": {"code": "moderation_blocked", "message": "Content policy."}}

        with patch.object(server, "sora_request_json", side_effect=fake_request):
            with self.assertRaisesRegex(RuntimeError, "moderation_blocked"):
                server.sora_generate_video("a fox", "wide", 8, "sora-2", "secret")


class ElevenLabsTests(unittest.TestCase):
    def test_music_endpoint_is_preferred(self):
        calls = []

        def fake_bytes(path, key, payload, timeout=server.ELEVENLABS_TIMEOUT):
            calls.append((path, payload))
            return b"mp3-bytes"

        with patch.object(server, "elevenlabs_request_bytes", side_effect=fake_bytes):
            path = server.elevenlabs_generate_soundtrack("calm piano", 45.0, "secret")
        try:
            self.assertTrue(str(calls[0][0]).startswith("music"))
            self.assertEqual(calls[0][1]["music_length_ms"], 45000)
            self.assertEqual(path.read_bytes(), b"mp3-bytes")
        finally:
            path.unlink(missing_ok=True)

    def test_falls_back_to_sound_effects_when_music_is_gated(self):
        calls = []

        def fake_bytes(path, key, payload, timeout=server.ELEVENLABS_TIMEOUT):
            calls.append((path, payload))
            if str(path).startswith("music"):
                raise server.ElevenLabsHTTPError(401, "missing_permissions")
            return b"sfx-bytes"

        with patch.object(server, "elevenlabs_request_bytes", side_effect=fake_bytes):
            path = server.elevenlabs_generate_soundtrack("ocean waves", 45.0, "secret")
        try:
            self.assertTrue(str(calls[1][0]).startswith("sound-generation"))
            self.assertEqual(calls[1][1]["duration_seconds"], 30.0)
            self.assertTrue(calls[1][1]["loop"])  # tiled to length by the muxer
        finally:
            path.unlink(missing_ok=True)

    def test_apply_soundtrack_without_key_warns_and_keeps_video(self):
        result = {"url": "/v.webm", "type": "video", "mp4Url": "/api/local-media?name=v.mp4"}
        with patch.object(server, "elevenlabs_key", return_value=("", "env")):
            out = server.apply_soundtrack(result, {"soundtrack": "epic strings"})
        self.assertEqual(out["url"], "/v.webm")
        self.assertIn("No ElevenLabs API key", out["soundtrackWarning"])

    def test_apply_soundtrack_failure_never_sinks_the_job(self):
        result = {"url": "/v.webm", "type": "video", "mp4Path": __file__}
        with patch.object(server, "elevenlabs_key", return_value=("secret", "elevenlabs")), \
             patch.object(server, "probe_video_duration", return_value=10.0), \
             patch.object(server, "elevenlabs_generate_soundtrack",
                          side_effect=RuntimeError("quota exceeded")):
            out = server.apply_soundtrack(result, {"soundtrack": "epic strings"})
        self.assertEqual(out["url"], "/v.webm")
        self.assertIn("quota exceeded", out["soundtrackWarning"])
        self.assertNotIn("mp4Path", out)

    def test_apply_soundtrack_mixes_and_updates_urls(self):
        result = {"url": "/v.webm", "type": "video", "mp4Path": __file__}
        with patch.object(server, "elevenlabs_key", return_value=("secret", "elevenlabs")), \
             patch.object(server, "probe_video_duration", return_value=10.0), \
             patch.object(server, "elevenlabs_generate_soundtrack",
                          return_value=Path("/tmp/imagineai-test-track.mp3")), \
             patch.object(server, "mux_soundtrack_into_mp4",
                          return_value=("/api/local-media?name=mixed.mp4", Path("/tmp/mixed.mp4"))), \
             patch.object(server, "transcode_mp4_path_to_webm",
                          return_value="/api/local-media?name=mixed.webm"):
            out = server.apply_soundtrack(result, {"soundtrack": "epic strings"})
        self.assertEqual(out["url"], "/api/local-media?name=mixed.webm")
        self.assertEqual(out["mp4Url"], "/api/local-media?name=mixed.mp4")
        self.assertNotIn("mp4Path", out)

    def test_local_media_path_rejects_traversal(self):
        self.assertIsNone(server.local_media_path_from_url("/api/local-media?name=../secrets.json"))
        self.assertIsNone(server.local_media_path_from_url("https://evil.test/x"))
        self.assertIsNone(server.local_media_path_from_url(None))


if __name__ == "__main__":
    unittest.main()
