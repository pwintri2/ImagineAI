import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class VideoPlaybackTests(unittest.TestCase):
    def test_ensure_local_video_mp4_converts_legacy_webm(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            source = output_dir / "old-preview.webm"
            source.write_bytes(b"webm preview")

            def fake_run(cmd, **kwargs):
                Path(cmd[-1]).write_bytes(b"converted mp4")
                return subprocess.CompletedProcess(cmd, 0, b"", b"")

            with patch.object(server, "OUTPUTS_DIR", output_dir), \
                 patch.object(server, "ffmpeg_executable", return_value="/usr/bin/ffmpeg"), \
                 patch.object(server.subprocess, "run", side_effect=fake_run) as run:
                result = server.ensure_local_video_mp4("/api/local-media?name=old-preview.webm")
                result_again = server.ensure_local_video_mp4("/api/local-media?name=old-preview.webm")

            self.assertEqual(result["mp4Url"], "/api/local-media?name=converted_old-preview.mp4")
            self.assertTrue(result["converted"])
            self.assertEqual(result_again["mp4Url"], result["mp4Url"])
            run.assert_called_once()
            self.assertTrue((output_dir / "converted_old-preview.mp4").is_file())

    def test_ensure_local_video_mp4_returns_existing_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "master.mp4").write_bytes(b"mp4")
            with patch.object(server, "OUTPUTS_DIR", output_dir), \
                 patch.object(server, "ffmpeg_executable") as ffmpeg:
                result = server.ensure_local_video_mp4("/api/local-media?name=master.mp4")
            self.assertEqual(result, {"mp4Url": "/api/local-media?name=master.mp4", "converted": False})
            ffmpeg.assert_not_called()

    def test_single_local_stitched_block_persists_mp4_for_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "outputs"
            output_dir.mkdir()
            temp_clip = Path(tmp) / "block.mp4"

            def fake_block(*args, **kwargs):
                temp_clip.write_bytes(b"fake mp4 with audio")
                return temp_clip, ""

            job_id = server.make_job("video")
            with patch.object(server, "OUTPUTS_DIR", output_dir), \
                 patch.object(server, "COMFY_INPUT_DIR", Path(tmp) / "input"), \
                 patch.object(server, "detect_models", return_value={"video": {}}), \
                 patch.object(server, "job_cancel_requested", return_value=False), \
                 patch.object(server, "run_local_video_block", side_effect=fake_block), \
                 patch.object(server, "transcode_mp4_path_to_webm",
                              return_value="/api/local-media?name=preview.webm"):
                server.render_local_stitched_video(
                    job_id, {}, "wan21_1_3b", "wide", "a quiet scene", 1, "Wan 2.1 1.3B"
                )

            job = server.get_job(job_id)
            self.assertEqual(job["status"], "done")
            result = job["results"][0]
            self.assertEqual(result["url"], "/api/local-media?name=preview.webm")
            self.assertRegex(result["mp4Url"], r"^/api/local-media\?name=local_video_.*\.mp4$")
            mp4_name = urllib.parse.parse_qs(
                urllib.parse.urlparse(result["mp4Url"]).query
            )["name"][0]
            self.assertTrue((output_dir / mp4_name).is_file())
            self.assertFalse(temp_clip.exists())

    def test_local_media_supports_head_and_byte_ranges_for_webkit(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            body = b"0123456789abcdef"
            (output_dir / "sample.mp4").write_bytes(body)
            with patch.object(server, "OUTPUTS_DIR", output_dir):
                httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                url = f"http://127.0.0.1:{httpd.server_port}/api/local-media?name=sample.mp4"
                try:
                    with urllib.request.urlopen(
                        urllib.request.Request(url, method="HEAD"), timeout=5
                    ) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.headers["Content-Length"], str(len(body)))
                        self.assertEqual(response.headers["Accept-Ranges"], "bytes")
                        self.assertEqual(response.read(), b"")

                    request = urllib.request.Request(url, headers={"Range": "bytes=2-5"})
                    with urllib.request.urlopen(request, timeout=5) as response:
                        self.assertEqual(response.status, 206)
                        self.assertEqual(response.headers["Content-Range"], "bytes 2-5/16")
                        self.assertEqual(response.read(), body[2:6])
                finally:
                    httpd.shutdown()
                    httpd.server_close()
                    thread.join(timeout=5)

    @unittest.skipUnless(server.ffmpeg_executable(), "ffmpeg is required")
    def test_ffmpeg_webm_stitch_is_vp9_profile_zero_yuv420p(self):
        ffmpeg = server.ffmpeg_executable()
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            clips = []
            for index, color in enumerate(("red", "blue")):
                clip = output_dir / f"clip-{index}.mp4"
                subprocess.run(
                    [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                     "-f", "lavfi", "-i", f"color=c={color}:s=64x64:d=1.2:r=30",
                     "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
                clips.append(clip)

            with patch.object(server, "OUTPUTS_DIR", output_dir), \
                 patch.object(server, "COMFY_PYTHON", str(output_dir / "missing-python")), \
                 patch.object(server, "STITCH_OVERLAP_SECONDS", 0.2):
                url = server.concat_mp4_paths_to_webm(clips)
                result_path = server.local_media_path_from_url(url)

            self.assertIsNotNone(result_path)
            self.assertEqual(result_path.suffix, ".webm")
            probe = subprocess.run(
                [ffmpeg, "-hide_banner", "-i", str(result_path), "-f", "null", "-"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            details = f"{probe.stdout}\n{probe.stderr}"
            self.assertIn("Video: vp9 (Profile 0)", details)
            self.assertIn("yuv420p", details)
            self.assertNotIn("yuv444p", details)


if __name__ == "__main__":
    unittest.main()
