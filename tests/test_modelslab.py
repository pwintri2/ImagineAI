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


if __name__ == "__main__":
    unittest.main()
