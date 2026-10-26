import base64
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402


PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(b"fake-png").decode("ascii")


class ImageUploadTests(unittest.TestCase):
    def test_flux_gguf_sizes_fit_local_fp32_profile(self):
        self.assertEqual(server.FLUX_GGUF_ASPECT_TO_SIZE, {
            "square": (512, 512),
            "landscape": (576, 432),
            "portrait": (432, 576),
            "wide": (640, 368),
            "tall": (368, 640),
        })
        for width, height in server.FLUX_GGUF_ASPECT_TO_SIZE.values():
            self.assertEqual(width % 16, 0)
            self.assertEqual(height % 16, 0)
            self.assertLessEqual(width * height, 512 * 512)

    def test_zimage_graph_uses_source_image_latent(self):
        graph = server.build_zimage_graph({
            "prompt": "make it cinematic",
            "width": 1024,
            "height": 1024,
            "batch_size": 2,
            "source_image": "imagineai/source.png",
            "image_strength": 0.4,
        })

        self.assertNotIn("13", graph)
        self.assertEqual(graph["34"], {"class_type": "LoadImage", "inputs": {"image": "imagineai/source.png"}})
        self.assertEqual(graph["35"]["class_type"], "ImageScale")
        self.assertEqual(graph["36"]["class_type"], "VAEEncode")
        self.assertEqual(graph["37"]["class_type"], "RepeatLatentBatch")
        self.assertEqual(graph["3"]["inputs"]["latent_image"], ["37", 0])
        self.assertEqual(graph["3"]["inputs"]["denoise"], 0.4)

    def test_flux_schnell_graph_uses_fp8_checkpoint(self):
        graph = server.build_flux_schnell_graph({
            "prompt": "a tiny glass greenhouse on mars",
            "width": 1216,
            "height": 832,
            "batch_size": 2,
            "steps": 4,
            "seed": 123,
        })

        self.assertEqual(graph["1"]["class_type"], "CheckpointLoaderSimple")
        self.assertEqual(graph["1"]["inputs"]["ckpt_name"], server.FLUX_SCHNELL_FP8_CHECKPOINT)
        self.assertEqual(graph["2"]["class_type"], "ModelSamplingFlux")
        self.assertEqual(graph["3"]["inputs"]["text"], "a tiny glass greenhouse on mars")
        self.assertEqual(graph["5"]["inputs"], {"width": 1216, "height": 832, "batch_size": 2})
        self.assertEqual(graph["6"]["inputs"]["cfg"], 1.0)
        self.assertEqual(graph["6"]["inputs"]["steps"], 4)
        self.assertEqual(graph["6"]["inputs"]["sampler_name"], "euler")

    def test_flux_schnell_graph_uses_gguf_components(self):
        graph = server.build_flux_schnell_graph({
            "prompt": "a tiny glass greenhouse on mars",
            "width": 768,
            "height": 768,
            "batch_size": 2,
            "steps": 4,
            "seed": 123,
            "backend": "gguf",
        })

        self.assertEqual(graph["1"], {
            "class_type": "UnetLoaderGGUF",
            "inputs": {"unet_name": server.FLUX_SCHNELL_GGUF_UNET},
        })
        self.assertEqual(graph["2"]["class_type"], "DualCLIPLoaderGGUF")
        self.assertEqual(graph["13"], {
            "class_type": "ModelComputeDtype",
            "inputs": {"model": ["1", 0], "dtype": "fp32"},
        })
        self.assertEqual(graph["2"]["inputs"], {
            "clip_name1": server.FLUX_SCHNELL_GGUF_T5,
            "clip_name2": server.FLUX_SCHNELL_CLIP_L,
            "type": "flux",
        })
        self.assertEqual(graph["3"]["inputs"]["vae_name"], server.FLUX_SCHNELL_VAE)
        self.assertEqual(graph["5"]["class_type"], "EmptySD3LatentImage")
        self.assertEqual(graph["5"]["inputs"], {"width": 768, "height": 768, "batch_size": 2})
        self.assertEqual(graph["6"]["inputs"]["noise_seed"], 123)
        self.assertEqual(graph["7"]["inputs"]["model"], ["13", 0])
        self.assertEqual(graph["9"]["inputs"]["model"], ["13", 0])
        self.assertEqual(graph["9"]["inputs"]["steps"], 4)
        self.assertEqual(graph["10"]["class_type"], "SamplerCustomAdvanced")
        self.assertEqual(graph["12"]["class_type"], "SaveImage")

    def test_detect_models_prefers_complete_gguf_flux_install(self):
        def node_info(node, key, options):
            return {node: {"input": {"required": {key: [options]}}}}

        responses = {
            "/object_info/UNETLoader": node_info(
                "UNETLoader", "unet_name", ["z_image_turbo_bf16.safetensors"],
            ),
            "/object_info/CLIPLoader": node_info(
                "CLIPLoader", "clip_name", ["qwen_3_4b.safetensors"],
            ),
            "/object_info/VAELoader": node_info(
                "VAELoader", "vae_name", [server.FLUX_SCHNELL_VAE],
            ),
            "/object_info/CheckpointLoaderSimple": node_info(
                "CheckpointLoaderSimple", "ckpt_name", [server.FLUX_SCHNELL_FP8_CHECKPOINT],
            ),
            "/object_info/UnetLoaderGGUF": node_info(
                "UnetLoaderGGUF", "unet_name", [server.FLUX_SCHNELL_GGUF_UNET],
            ),
            "/object_info/DualCLIPLoaderGGUF": node_info(
                "DualCLIPLoaderGGUF",
                "clip_name1",
                [server.FLUX_SCHNELL_GGUF_T5, server.FLUX_SCHNELL_CLIP_L],
            ),
        }

        with patch.object(server, "comfy_request", side_effect=lambda path, **_: responses[path]):
            models = server.detect_models()

        self.assertTrue(models["reachable"])
        self.assertTrue(models["image"]["flux1_schnell"])
        self.assertTrue(models["image"]["flux1_schnell_fp8"])
        self.assertEqual(models["image"]["flux1_schnell_backend"], "gguf")

    def test_xai_image_upload_uses_edit_endpoint(self):
        calls = []

        def fake_request(path, key, payload=None, method="GET", timeout=120):
            calls.append((path, key, payload, method, timeout))
            return {"data": [{"b64_json": base64.b64encode(b"edited").decode("ascii")}]}

        with patch.object(server, "xai_request_json", side_effect=fake_request), \
             patch.object(server, "save_output_bytes", return_value=("/api/local-media?name=xai.jpg", Path("xai.jpg"), "xai.jpg")):
            urls = server.xai_generate_image(
                "turn this into a pencil sketch",
                "square",
                1,
                "grok-imagine-image-quality",
                "secret",
                source_image=PNG_DATA_URL,
            )

        self.assertEqual(urls, ["/api/local-media?name=xai.jpg"])
        path, _, payload, method, _ = calls[0]
        self.assertEqual(path, "/images/edits")
        self.assertEqual(method, "POST")
        self.assertEqual(payload["image"], {"url": PNG_DATA_URL, "type": "image_url"})
        self.assertNotIn("aspect_ratio", payload)
        self.assertNotIn("response_format", payload)
        self.assertNotIn("n", payload)

    def test_gemini_image_upload_sends_inline_image_part(self):
        bodies = []
        output_b64 = base64.b64encode(b"edited").decode("ascii")

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps({
                    "candidates": [{
                        "content": {
                            "parts": [{
                                "inlineData": {"mimeType": "image/png", "data": output_b64},
                            }],
                        },
                    }],
                }).encode("utf-8")

        def fake_urlopen(req, timeout=120):
            bodies.append(json.loads(req.data.decode("utf-8")))
            return FakeResponse()

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(server, "OUTPUTS_DIR", Path(tmp)), \
             patch("urllib.request.urlopen", side_effect=fake_urlopen):
            urls = server.gemini_generate_image(
                "make the background neon",
                "wide",
                "gemini-2.5-flash-image",
                "secret",
                source_image=PNG_DATA_URL,
            )

        self.assertEqual(len(urls), 1)
        parts = bodies[0]["contents"][0]["parts"]
        self.assertEqual(parts[0], {"text": "make the background neon"})
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "image/png")
        self.assertEqual(parts[1]["inlineData"]["data"], base64.b64encode(b"fake-png").decode("ascii"))


if __name__ == "__main__":
    unittest.main()
