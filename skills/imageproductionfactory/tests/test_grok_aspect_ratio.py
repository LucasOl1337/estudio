from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import image_production_factory as factory  # noqa: E402


INVALID_TO_NEAREST = {
    "4:5": "3:4",
    "19:28": "2:3",
    "7:3": "21:9",
    "9:13": "2:3",
    "3:1": "5:2",
    "1:5": "9:20",
    "1:4": "9:20",
}


def orientation(value: str) -> str:
    left, right = (float(part) for part in value.split(":"))
    if left < right:
        return "portrait"
    if left > right:
        return "landscape"
    return "square"


class GrokAspectRatioTest(unittest.TestCase):
    def test_invalid_ratios_map_to_nearest_allowed_same_orientation(self) -> None:
        allowed = set(factory.GROK_ALLOWED_ASPECT_RATIOS)
        for requested, expected in INVALID_TO_NEAREST.items():
            sent = factory.grok_aspect_ratio(requested)
            self.assertEqual(sent, expected, requested)
            self.assertIn(sent, allowed)
            self.assertEqual(orientation(sent), orientation(requested), requested)

    def test_already_allowed_ratios_pass_unchanged(self) -> None:
        for allowed in factory.GROK_ALLOWED_ASPECT_RATIOS:
            self.assertEqual(factory.grok_aspect_ratio(allowed), allowed)

    def test_library_cases_snap_only_invalid_ratios(self) -> None:
        cases = factory.load_creative_library(REPO_ROOT)["cases"]
        self.assertEqual(len(cases), 517)
        allowed = set(factory.GROK_ALLOWED_ASPECT_RATIOS)
        valid = 0
        invalid = 0
        invalid_values: set[str] = set()
        large_distortion: list[tuple[object, str, str]] = []
        for case in cases:
            requested = factory.source_aspect_ratio(str(case.get("prompt") or ""))
            sent = factory.grok_aspect_ratio(requested)
            self.assertIn(sent, allowed)
            flagged = factory.grok_aspect_ratio_large_distortion(requested, sent)
            if flagged:
                large_distortion.append((case.get("id"), requested, sent))
            if requested in allowed:
                self.assertEqual(sent, requested, f"case {case.get('id')} {requested}")
                self.assertFalse(flagged, f"case {case.get('id')} {requested}")
                valid += 1
            else:
                self.assertEqual(orientation(sent), orientation(requested), requested)
                invalid += 1
                invalid_values.add(requested)
                if requested in {"1:5", "1:4"}:
                    self.assertTrue(flagged, requested)
                elif requested == "4:5":
                    self.assertFalse(flagged, requested)
        self.assertEqual(valid, 502)
        self.assertEqual(invalid, 15)
        self.assertEqual(invalid_values, set(INVALID_TO_NEAREST))
        self.assertEqual({requested for _, requested, _ in large_distortion}, {"1:5", "1:4"})

    def test_large_distortion_marks_extreme_snaps_only(self) -> None:
        threshold = factory.GROK_ASPECT_RATIO_LARGE_DISTORTION_THRESHOLD
        self.assertIsInstance(threshold, (int, float))
        self.assertGreater(threshold, 1)
        self.assertTrue(
            factory.grok_aspect_ratio_large_distortion("1:5", factory.grok_aspect_ratio("1:5"))
        )
        self.assertTrue(
            factory.grok_aspect_ratio_large_distortion("1:4", factory.grok_aspect_ratio("1:4"))
        )
        self.assertFalse(
            factory.grok_aspect_ratio_large_distortion("4:5", factory.grok_aspect_ratio("4:5"))
        )
        for allowed in factory.GROK_ALLOWED_ASPECT_RATIOS:
            self.assertFalse(
                factory.grok_aspect_ratio_large_distortion(
                    allowed, factory.grok_aspect_ratio(allowed)
                ),
                allowed,
            )

    def test_grok_generate_sends_snapped_ratio_and_records_audit(self) -> None:
        captured: dict[str, object] = {}

        def fake_post(*_args, **kwargs):
            captured["payload"] = kwargs["json"]
            response = Mock()
            response.status_code = 422
            response.text = "aspect_ratio unknown variant"
            return response

        dest = Path("unused.jpg")
        with patch.object(factory.httpx, "post", side_effect=fake_post):
            result = factory.grok_generate("prompt", "token", [], dest, "19:28")
        self.assertEqual(captured["payload"]["aspect_ratio"], "2:3")
        self.assertEqual(result["aspect_ratio_requested"], "19:28")
        self.assertEqual(result["aspect_ratio_sent"], "2:3")
        self.assertFalse(result["aspect_ratio_large_distortion"])
        self.assertFalse(result["ok"])

    def test_grok_generate_marks_large_distortion_on_extreme_snap(self) -> None:
        response = Mock()
        response.status_code = 422
        response.text = "aspect_ratio unknown variant"
        dest = Path("unused.jpg")
        with patch.object(factory.httpx, "post", return_value=response):
            result = factory.grok_generate("prompt", "token", [], dest, "1:5")
        self.assertEqual(result["aspect_ratio_requested"], "1:5")
        self.assertEqual(result["aspect_ratio_sent"], "9:20")
        self.assertTrue(result["aspect_ratio_large_distortion"])
        self.assertFalse(result["ok"])

    def test_grok_generate_keeps_audit_when_httpx_times_out(self) -> None:
        dest = Path("unused.jpg")
        with patch.object(
            factory.httpx, "post", side_effect=factory.httpx.TimeoutException("timed out")
        ):
            result = factory.grok_generate("prompt", "token", [], dest, "19:28")
        self.assertFalse(result["ok"])
        self.assertIn("TimeoutException", result["error"])
        self.assertEqual(result["aspect_ratio_requested"], "19:28")
        self.assertEqual(result["aspect_ratio_sent"], "2:3")
        self.assertFalse(result["aspect_ratio_large_distortion"])

    def test_grok_generate_keeps_audit_when_ratio_is_unparseable(self) -> None:
        dest = Path("unused.jpg")
        result = factory.grok_generate("prompt", "token", [], dest, "not-a-ratio")
        self.assertFalse(result["ok"])
        self.assertIn("ValueError", result["error"])
        self.assertEqual(result["aspect_ratio_requested"], "not-a-ratio")
        self.assertNotIn("aspect_ratio_sent", result)
        self.assertNotIn("aspect_ratio_large_distortion", result)

    def test_grok_generate_keeps_audit_when_json_is_invalid(self) -> None:
        response = Mock()
        response.status_code = 200
        response.json.side_effect = ValueError("No JSON object could be decoded")
        dest = Path("unused.jpg")
        with patch.object(factory.httpx, "post", return_value=response):
            result = factory.grok_generate("prompt", "token", [], dest, "1:1")
        self.assertFalse(result["ok"])
        self.assertIn("ValueError", result["error"])
        self.assertEqual(result["aspect_ratio_requested"], "1:1")
        self.assertEqual(result["aspect_ratio_sent"], "1:1")
        self.assertFalse(result["aspect_ratio_large_distortion"])

    def test_grok_generate_keeps_audit_when_download_fails(self) -> None:
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"data": [{"url": "https://example.invalid/x.jpg"}]}
        dest = Path("unused.jpg")
        with patch.object(factory.httpx, "post", return_value=response):
            with patch.object(factory, "download", side_effect=OSError("download failed")):
                result = factory.grok_generate("prompt", "token", [], dest, "4:5")
        self.assertFalse(result["ok"])
        self.assertIn("OSError", result["error"])
        self.assertEqual(result["aspect_ratio_requested"], "4:5")
        self.assertEqual(result["aspect_ratio_sent"], "3:4")
        self.assertFalse(result["aspect_ratio_large_distortion"])


if __name__ == "__main__":
    unittest.main()
