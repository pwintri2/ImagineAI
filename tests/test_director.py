import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class DirectorPlanningTests(unittest.TestCase):
    def test_scene_tier_classification(self):
        self.assertEqual(server.director_scene_tier("a sunny meadow with butterflies"), 0)
        self.assertEqual(server.director_scene_tier("two knights fight a battle with swords"), 1)
        self.assertEqual(server.director_scene_tier("een ridder met een zwaard in een gevecht"), 1)
        self.assertEqual(server.director_scene_tier("artistic nude figure study in chiaroscuro"), 2)
        self.assertEqual(server.director_scene_tier("gruesome gore in an abandoned asylum"), 2)

    def test_pick_engine_respects_tier_preferences(self):
        available = {"local": {}, "atlas": {}, "xai": {}, "veo": {}}
        self.assertEqual(server.director_pick_engine(0, available), "veo")
        self.assertEqual(server.director_pick_engine(1, available), "xai")
        # Free tier prefers Atlas' cloud Wan for speed; local Wan is the fallback.
        self.assertEqual(server.director_pick_engine(2, available), "atlas")
        self.assertEqual(server.director_pick_engine(2, {"veo": {}, "local": {}}), "local")
        with self.assertRaisesRegex(RuntimeError, "chain-capable"):
            server.director_pick_engine(0, {})

    def test_segment_seconds_never_leaves_tiny_tail(self):
        self.assertEqual(server.director_segment_seconds("atlas", 18), 14)  # tail becomes 4
        self.assertEqual(server.director_segment_seconds("atlas", 15), 15)
        self.assertEqual(server.director_segment_seconds("veo", 10), 6)     # veo snaps to 4/6/8
        self.assertEqual(server.director_segment_seconds("veo", 8), 8)
        self.assertEqual(server.director_segment_seconds("local", 7), 7)
        for engine in ("veo", "atlas", "xai", "local"):
            remaining = 180
            steps = 0
            while remaining > 0 and steps < 100:
                seg = server.director_segment_seconds(engine, remaining)
                self.assertGreater(seg, 0)
                remaining -= seg
                steps += 1
            self.assertEqual(remaining, 0)

    def test_plan_scenes_parses_fenced_json(self):
        def fake_request(path, key, payload=None, method="GET", timeout=120):
            return {"candidates": [{"content": {"parts": [{"text":
                '```json\n[{"prompt": "Scene one", "sensitivity": "free"},'
                ' {"prompt": "Scene two", "sensitivity": "safe"}]\n```'}]}}]}

        with patch.object(server, "veo_request_json", side_effect=fake_request):
            scenes = server.director_plan_scenes("idea", 2, 60, "secret")
        self.assertEqual(scenes, [{"prompt": "Scene one", "tier": 2},
                                  {"prompt": "Scene two", "tier": 0}])

    def test_plan_scenes_returns_none_without_key_or_on_garbage(self):
        self.assertIsNone(server.director_plan_scenes("idea", 2, 60, ""))
        with patch.object(server, "veo_request_json",
                          return_value={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}):
            self.assertIsNone(server.director_plan_scenes("idea", 2, 60, "secret"))


class DirectorGenerationTests(unittest.TestCase):
    def _run(self, prompt, seconds, available, scenes=None, atlas_fail_first=False):
        atlas_calls = []
        xai_calls = []

        def fake_atlas_clip(text, aspect, dur, model, key, start_image="", start_image_name="",
                            on_progress=None, negative_prompt="", seed=None, seed_pinned=False):
            if atlas_fail_first and not atlas_calls:
                atlas_calls.append(("failed", dur, bool(start_image)))
                raise RuntimeError("content filter blocked this video")
            atlas_calls.append((text, dur, bool(start_image)))
            index = len(atlas_calls)
            return {"mp4Path": f"/tmp/dir-atlas-{index}.mp4", "url": f"/a{index}.webm", "type": "video"}

        def fake_xai_clip(text, aspect, dur, model, key, images=None, on_progress=None):
            xai_calls.append((text, dur, bool(images)))
            index = len(xai_calls)
            return {"mp4Path": f"/tmp/dir-xai-{index}.mp4", "url": f"/x{index}.webm", "type": "video"}

        with patch.object(server, "director_available_engines", return_value=available), \
             patch.object(server, "director_plan_scenes", return_value=scenes), \
             patch.object(server, "gemini_key", return_value="gem-key"), \
             patch.object(server, "atlas_generate_video_clip", side_effect=fake_atlas_clip), \
             patch.object(server, "xai_generate_video_clip", side_effect=fake_xai_clip), \
             patch.object(server, "extract_last_frame_to_data_url",
                          return_value="data:image/png;base64,frame"), \
             patch.object(server.Path, "exists", return_value=True), \
             patch.object(server, "job_cancel_requested", return_value=False), \
             patch.object(server, "load_settings", return_value={
                 "atlasVideoModel": "alibaba/wan-2.7/text-to-video",
                 "xaiVideoModel": "grok-imagine-video",
                 "veoVideoModel": "veo-3.1-generate-preview"}), \
             patch.object(server, "transcode_mp4_path_to_webm", return_value="/film.webm"), \
             patch.object(server, "stitch_video_paths",
                          return_value={"url": "/film.webm", "mp4Url": "/film.mp4"}):
            result = server.director_generate_video("job-1", {}, prompt, "wide", seconds)
        return result, atlas_calls, xai_calls

    def test_safe_prompt_uses_quality_engine_and_reaches_total(self):
        result, atlas_calls, xai_calls = self._run(
            "a peaceful garden timelapse", 30, {"atlas": {"key": "k"}})
        self.assertEqual(result["url"], "/film.webm")
        self.assertEqual(result["mp4Url"], "/film.mp4")
        self.assertEqual(sum(c[1] for c in atlas_calls), 30)
        self.assertEqual(len(xai_calls), 0)
        # Scene 2+ chain from the carried frame.
        self.assertFalse(atlas_calls[0][2])
        self.assertTrue(all(c[2] for c in atlas_calls[1:]))
        self.assertEqual(len(result["scenes"]), len(atlas_calls))
        self.assertTrue(all(s["engine"] == "atlas" for s in result["scenes"]))

    def test_mild_prompt_prefers_grok(self):
        result, atlas_calls, xai_calls = self._run(
            "a sword fight on a castle wall", 30,
            {"atlas": {"key": "k"}, "xai": {"key": "k"}})
        self.assertGreater(len(xai_calls), 0)
        self.assertEqual(len(atlas_calls), 0)
        self.assertTrue(all(s["tier"] == "mild" for s in result["scenes"]))

    def test_failed_engine_falls_through_to_alternative(self):
        result, atlas_calls, xai_calls = self._run(
            "a peaceful garden", 15, {"atlas": {"key": "k"}, "xai": {"key": "k"}},
            atlas_fail_first=True)
        # Atlas (preferred for safe without veo... atlas first) fails once, xai takes over.
        self.assertEqual(atlas_calls[0][0], "failed")
        self.assertGreater(len(xai_calls), 0)
        # A single-scene film reuses the clip's own public url instead of re-transcoding.
        self.assertEqual(result["url"], "/x1.webm")

    def test_planned_scene_tiers_route_engines(self):
        scenes = [
            {"prompt": "A quiet street at dawn", "tier": 0},
            {"prompt": "A tense sword duel on the rooftop", "tier": 1},
        ]
        result, atlas_calls, xai_calls = self._run(
            "city story", 24, {"atlas": {"key": "k"}, "xai": {"key": "k"}}, scenes=scenes)
        engines = [s["engine"] for s in result["scenes"]]
        self.assertIn("atlas", engines)  # safe scene → atlas (no veo configured)
        self.assertIn("xai", engines)    # mild scene → grok

    def test_heuristic_escalates_planned_tier(self):
        # The keyword heuristic acts as a floor: a scene the planner labels
        # "mild" but that contains free-tier content still routes to Wan.
        scenes = [{"prompt": "A brutal gore-drenched hallway", "tier": 1}]
        result, atlas_calls, xai_calls = self._run(
            "corridor", 12, {"atlas": {"key": "k"}, "xai": {"key": "k"}}, scenes=scenes)
        self.assertTrue(all(s["tier"] == "free" for s in result["scenes"]))
        self.assertEqual(len(xai_calls), 0)  # free tier avoids Grok when Wan-family exists


if __name__ == "__main__":
    unittest.main()
