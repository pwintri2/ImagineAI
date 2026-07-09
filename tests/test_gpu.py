import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class FakeCompleted:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


class GpuStatsTests(unittest.TestCase):
    def test_nvidia_smi_is_preferred(self):
        with patch.object(server.subprocess, "run",
                          return_value=FakeCompleted("3210, 8151\n")):
            stats = server.gpu_memory_stats()
        self.assertEqual(stats, {"available": True, "usedMb": 3210, "totalMb": 8151,
                                 "source": "nvidia-smi"})

    def test_falls_back_to_comfy_system_stats(self):
        mb = 1024 * 1024
        with patch.object(server.subprocess, "run", side_effect=FileNotFoundError), \
             patch.object(server, "comfy_request",
                          return_value={"devices": [{"vram_total": 8151 * mb, "vram_free": 6000 * mb}]}):
            stats = server.gpu_memory_stats()
        self.assertTrue(stats["available"])
        self.assertEqual(stats["source"], "comfyui")
        self.assertEqual(stats["totalMb"], 8151)
        self.assertEqual(stats["usedMb"], 8151 - 6000)

    def test_unavailable_when_nothing_answers(self):
        with patch.object(server.subprocess, "run", side_effect=FileNotFoundError), \
             patch.object(server, "comfy_request", side_effect=RuntimeError("down")):
            self.assertEqual(server.gpu_memory_stats(), {"available": False})


class FreeGpuTests(unittest.TestCase):
    def test_refuses_while_a_job_is_running(self):
        job_id = server.make_job("video")
        server.update_job(job_id, status="running")
        try:
            with self.assertRaisesRegex(RuntimeError, "still running"):
                server.free_gpu_memory()
        finally:
            server.update_job(job_id, status="done")

    def test_refuses_while_comfy_queue_is_busy(self):
        with patch.dict(server.JOBS, {}, clear=True), \
             patch.object(server, "comfy_request",
                          return_value={"queue_running": [["x"]], "queue_pending": []}):
            with self.assertRaisesRegex(RuntimeError, "still running"):
                server.free_gpu_memory()

    def test_unloads_comfy_and_ollama_when_idle(self):
        calls = []

        def fake_comfy(path, payload=None, method="GET", timeout=30):
            calls.append((path, method))
            if path == "/queue":
                return {"queue_running": [], "queue_pending": []}
            return {}

        with patch.dict(server.JOBS, {}, clear=True), \
             patch.object(server, "comfy_request", side_effect=fake_comfy), \
             patch.object(server, "ollama_loaded_models", return_value=["llama3", "phi4"]), \
             patch.object(server, "ollama_unload_model", return_value=True) as unload, \
             patch.object(server, "gpu_memory_stats",
                          return_value={"available": True, "usedMb": 100, "totalMb": 8151}):
            result = server.free_gpu_memory()

        self.assertIn(("/free", "POST"), calls)
        self.assertEqual(unload.call_count, 2)
        self.assertIn("ComfyUI models unloaded", result["freed"][0])
        self.assertIn("llama3", result["freed"][1])
        self.assertEqual(result["usedMb"], 100)

    def test_reports_when_nothing_was_loaded(self):
        with patch.dict(server.JOBS, {}, clear=True), \
             patch.object(server, "comfy_request", side_effect=RuntimeError("comfy down")), \
             patch.object(server, "ollama_loaded_models", return_value=[]), \
             patch.object(server, "gpu_memory_stats", return_value={"available": False}):
            result = server.free_gpu_memory()
        self.assertIn("already empty", result["message"])


if __name__ == "__main__":
    unittest.main()
