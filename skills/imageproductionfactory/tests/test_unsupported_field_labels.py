from __future__ import annotations

import sys
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import image_production_factory as factory  # noqa: E402

AFFECTED_CASE_IDS = {8, 222, 296, 469}
PORTUGUESE = "Brazilian Portuguese (pt-BR)"
ENGLISH = "English"
PT_NOT_PROVIDED = "Não informado"
PT_NOT_ASSESSED = "Não avaliado"
EN_NOT_PROVIDED = "Not provided"
EN_NOT_ASSESSED = "Not assessed"


def compile_library(copy_language: str) -> dict[int, str]:
    items, _ = factory.full_library_items(REPO_ROOT, "LUCAS", copy_language=copy_language)
    prompts = {}
    for item in items:
        case_id = item["case_ids"][0]
        prompts[case_id] = item["prompt"]
    return prompts


class UnsupportedFieldLabelsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pt_prompts = compile_library(PORTUGUESE)
        cls.en_prompts = compile_library(ENGLISH)
        if len(cls.pt_prompts) != 517 or len(cls.en_prompts) != 517:
            raise AssertionError(
                f"expected 517 cases, got pt={len(cls.pt_prompts)} en={len(cls.en_prompts)}"
            )

    def test_portuguese_replaces_english_literals_on_affected_cases(self) -> None:
        for case_id in AFFECTED_CASE_IDS:
            prompt = self.pt_prompts[case_id]
            self.assertNotIn(EN_NOT_PROVIDED, prompt, case_id)
            self.assertNotIn(EN_NOT_ASSESSED, prompt, case_id)
            self.assertIn(PT_NOT_PROVIDED, prompt, case_id)
            self.assertIn(PT_NOT_ASSESSED, prompt, case_id)

    def test_english_keeps_original_literals_on_affected_cases(self) -> None:
        for case_id in AFFECTED_CASE_IDS:
            prompt = self.en_prompts[case_id]
            self.assertIn(EN_NOT_PROVIDED, prompt, case_id)
            self.assertIn(EN_NOT_ASSESSED, prompt, case_id)
            self.assertNotIn(PT_NOT_PROVIDED, prompt, case_id)
            self.assertNotIn(PT_NOT_ASSESSED, prompt, case_id)

    def test_other_cases_do_not_receive_missing_field_labels(self) -> None:
        other_ids = set(self.pt_prompts) - AFFECTED_CASE_IDS
        self.assertEqual(len(other_ids), 513)
        labels = (EN_NOT_PROVIDED, EN_NOT_ASSESSED, PT_NOT_PROVIDED, PT_NOT_ASSESSED)
        for case_id in other_ids:
            for prompt in (self.pt_prompts[case_id], self.en_prompts[case_id]):
                for label in labels:
                    self.assertNotIn(label, prompt, (case_id, label))

    def test_labels_derive_from_copy_language(self) -> None:
        self.assertEqual(
            factory.unsupported_field_labels(PORTUGUESE),
            (PT_NOT_PROVIDED, PT_NOT_ASSESSED),
        )
        self.assertEqual(
            factory.unsupported_field_labels("Portuguese"),
            (PT_NOT_PROVIDED, PT_NOT_ASSESSED),
        )
        self.assertEqual(
            factory.unsupported_field_labels(ENGLISH),
            (EN_NOT_PROVIDED, EN_NOT_ASSESSED),
        )
        self.assertEqual(
            factory.unsupported_field_labels(""),
            (EN_NOT_PROVIDED, EN_NOT_ASSESSED),
        )


if __name__ == "__main__":
    unittest.main()
