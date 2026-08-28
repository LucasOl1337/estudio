from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]
RUNNER = SKILL_DIR / "scripts" / "image_production_factory.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def create_library(root: Path, case_ids: list[int]) -> None:
    library = root / "PROMPTS" / "site-library"
    cases = [
        {
            "id": case_id,
            "title": f"Fixture case {case_id}",
            "prompt": f"Create fixture image {case_id}.",
            "category": "Fixture",
            "semantics": {
                "primary_purpose": "fixture-purpose",
                "output_topology": "single-frame",
                "text_policy": "forbidden",
                "target_kinds": [],
            },
        }
        for case_id in case_ids
    ]
    write_json(
        library / "manifest.json",
        {
            "schema_version": 1,
            "source": {
                "repository": "https://example.test/library",
                "commit": "fixture-commit",
            },
            "counts": {"cases": len(cases)},
        },
    )
    write_json(library / "cases.json", {"total_cases": len(cases), "cases": cases})
    write_json(library / "taxonomy.json", {"purposes": [], "topologies": []})
    write_json(library / "template-semantics.json", {"templates": []})


def create_template_catalog(root: Path, template_count: int) -> None:
    template_items = []
    semantics = []
    for index in range(1, template_count + 1):
        template_id = f"fixture/{index:02d}"
        filename = f"template-{index:02d}.txt"
        template_items.append(
            {
                "id": template_id,
                "title_en": f"Fixture template {index}",
                "queue_ready": True,
                "files": {"en": filename},
            }
        )
        semantics.append(
            {
                "id": template_id,
                "primary_purpose": "fixture-purpose",
                "output_topology": "single-frame",
                "text_policy": "forbidden",
            }
        )
        template_path = root / "PROMPTS" / "fixture" / filename
        template_path.parent.mkdir(parents=True, exist_ok=True)
        template_path.write_text(f"Create fixture template {index}.", encoding="utf-8")
    write_json(
        root / "PROMPTS" / "catalog.json",
        {
            "categories": [
                {"slug": "fixture", "title": "Fixture", "items": template_items}
            ],
            "stats": {"prompts_queueable": template_count},
        },
    )
    write_json(
        root / "PROMPTS" / "site-library" / "template-semantics.json",
        {"templates": semantics},
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNNER), *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


class FullLibraryCliTests(unittest.TestCase):
    def test_full_library_derives_count_and_batches_from_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="image-factory-library-") as temporary:
            root = Path(temporary)
            create_library(root, [1, *range(5, 25)])
            target = root / "TARGET"
            target.mkdir()
            (target / "01-reference.png").write_bytes(b"fixture reference")
            (target / "SOURCE-ADAPTATION.md").write_text(
                "Use only facts supplied for this target.", encoding="utf-8"
            )

            completed = run_cli(
                "full-library",
                "--target",
                target.name,
                "--focus",
                "fixture",
                "--root",
                str(root),
                "--batch",
                "all",
                "--providers",
                "grok",
                "--dry-run",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["catalog_items"], 21)
            self.assertEqual(report["selected_items"], 21)
            manifest = json.loads(
                (target / "PRODUCOES" / "fixture" / "FULL_LIBRARY_MANIFEST.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["library_snapshot"]["case_count"], 21)
            self.assertEqual(manifest["selection"]["count"], 21)
            self.assertEqual(manifest["batches"]["count"], 2)
            self.assertEqual([case["batch"] for case in manifest["cases"]][-1], 2)
            self.assertEqual(manifest["library_snapshot"]["missing_ids"], [2, 3, 4])
            self.assertTrue(
                all(not case["use_target_reference"] for case in manifest["cases"])
            )

            selected = run_cli(
                "selected-library",
                "--target",
                target.name,
                "--focus",
                "selected",
                "--root",
                str(root),
                "--case-ids",
                "21,1",
                "--providers",
                "grok",
                "--dry-run",
            )
            self.assertEqual(selected.returncode, 0, selected.stderr)
            selected_manifest = json.loads(
                (
                    target
                    / "PRODUCOES"
                    / "selected"
                    / "SELECTED_LIBRARY_MANIFEST.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(selected_manifest["selection"]["case_ids"], [21, 1])
            self.assertEqual(
                [case["case_id"] for case in selected_manifest["cases"]], [21, 1]
            )

    def test_full_library_rejects_manifest_payload_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="image-factory-mismatch-") as temporary:
            root = Path(temporary)
            create_library(root, [1, 3])
            manifest_path = root / "PROMPTS" / "site-library" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["counts"]["cases"] = 3
            write_json(manifest_path, manifest)
            target = root / "TARGET"
            target.mkdir()
            (target / "01-reference.png").write_bytes(b"fixture reference")

            completed = run_cli(
                "full-library",
                "--target",
                target.name,
                "--focus",
                "fixture",
                "--root",
                str(root),
                "--providers",
                "grok",
                "--dry-run",
            )

            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("Purpose library case count mismatch", completed.stderr)

    def test_full_templates_derives_count_and_batches_from_catalog(self) -> None:
        with tempfile.TemporaryDirectory(prefix="image-factory-templates-") as temporary:
            root = Path(temporary)
            create_library(root, [])
            create_template_catalog(root, 48)
            target = root / "TARGET"
            target.mkdir()
            (target / "01-reference.png").write_bytes(b"fixture reference")

            completed = run_cli(
                "full-templates",
                "--target",
                target.name,
                "--focus",
                "fixture",
                "--root",
                str(root),
                "--batch",
                "all",
                "--providers",
                "grok",
                "--dry-run",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads(completed.stdout)
            self.assertEqual(report["catalog_items"], 48)
            manifest = json.loads(
                (target / "PRODUCOES" / "fixture" / "FULL_TEMPLATES_MANIFEST.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["catalog_snapshot"]["template_count"], 48)
            self.assertEqual(manifest["selection"]["count"], 48)
            self.assertEqual(manifest["batches"]["count"], 3)
            self.assertEqual(len(manifest["batches"]["template_ids"][-1]), 8)


class VerifyCliTests(unittest.TestCase):
    def test_verify_accepts_hash_bound_decodable_artifact(self) -> None:
        with tempfile.TemporaryDirectory(prefix=".factory-verify-", dir=REPO_ROOT / "ALVOS") as temporary:
            target = Path(temporary)
            focus = "integrity"
            production = target / "PRODUCOES" / focus
            intent = json.loads(
                (SKILL_DIR / "templates" / "intent-contract.example.json").read_text(
                    encoding="utf-8"
                )
            )
            brief = json.loads(
                (SKILL_DIR / "templates" / "production-brief.example.json").read_text(
                    encoding="utf-8"
                )
            )
            intent.update(
                {
                    "target": target.name,
                    "focus": focus,
                    "output_count": 1,
                    "reviewed": True,
                }
            )
            brief.update(
                {
                    "target": target.name,
                    "display_name": target.name,
                    "focus": focus,
                    "output_count": 1,
                    "references": ["primary.png"],
                    "providers": ["grok"],
                    "creative_plan": brief["creative_plan"][:1],
                }
            )
            production.mkdir(parents=True)
            write_json(production / "intent-contract.json", intent)
            write_json(production / "production-brief.json", brief)
            reference = target / "primary.png"
            Image.new("RGB", (16, 16), (20, 40, 60)).save(reference)

            dry_run = run_cli(
                "run",
                "--target",
                target.name,
                "--focus",
                focus,
                "--root",
                str(REPO_ROOT),
                "--providers",
                "grok",
                "--dry-run",
            )
            self.assertEqual(dry_run.returncode, 0, dry_run.stderr)

            item_id = "window-light-closeup"
            queue = production / "FILA_GROK"
            prompt = queue / "_prompts" / f"{item_id}.txt"
            output = queue / f"{item_id}.jpg"
            Image.new("RGB", (24, 24), (90, 30, 10)).save(output, format="JPEG")
            prompt_hash = sha256(prompt)
            reference_hashes = [sha256(reference)]
            output_hash = sha256(output)
            write_json(
                queue / "REPORT.json",
                {
                    "schema_version": 2,
                    "provider": "grok",
                    "results": {
                        item_id: {
                            "ok": True,
                            "prompt_sha256": prompt_hash,
                            "reference_sha256": reference_hashes,
                            "output_sha256": output_hash,
                        }
                    },
                },
            )
            write_json(
                production / "VISUAL_REVIEW.json",
                {
                    "schema_version": 2,
                    "reviewed": True,
                    "providers": {
                        "grok": {
                            item_id: {
                                "prompt_sha256": prompt_hash,
                                "reference_sha256": reference_hashes,
                                "output_sha256": output_hash,
                                "accepted": True,
                                "identity_fidelity": "pass",
                                "topology": "pass",
                                "text": "pass",
                                "intent_alignment": "pass",
                                "notes": "Inspected against the exact prompt, reference and output.",
                            }
                        }
                    },
                },
            )

            verified = run_cli(
                "verify",
                "--target",
                target.name,
                "--focus",
                focus,
                "--root",
                str(REPO_ROOT),
            )
            self.assertEqual(verified.returncode, 0, verified.stderr)

            reference_bytes = reference.read_bytes()
            Image.new("RGB", (16, 16), (70, 50, 30)).save(reference)
            changed_reference = run_cli(
                "verify",
                "--target",
                target.name,
                "--focus",
                focus,
                "--root",
                str(REPO_ROOT),
            )
            self.assertEqual(changed_reference.returncode, 2, changed_reference.stderr)
            changed_reference_report = json.loads(changed_reference.stdout)
            self.assertEqual(
                changed_reference_report["providers"]["grok"]["reference_mismatch"],
                [item_id],
            )
            reference.write_bytes(reference_bytes)

            prompt_bytes = prompt.read_bytes()
            prompt.write_bytes(prompt_bytes + b"\nTAMPERED")
            changed_prompt = run_cli(
                "verify",
                "--target",
                target.name,
                "--focus",
                focus,
                "--root",
                str(REPO_ROOT),
            )
            self.assertEqual(changed_prompt.returncode, 2, changed_prompt.stderr)
            changed_prompt_report = json.loads(changed_prompt.stdout)
            self.assertEqual(
                changed_prompt_report["providers"]["grok"]["prompt_mismatch"], [item_id]
            )
            prompt.write_bytes(prompt_bytes)

            Image.new("RGB", (24, 24), (10, 80, 120)).save(output, format="JPEG")
            tampered = run_cli(
                "verify",
                "--target",
                target.name,
                "--focus",
                focus,
                "--root",
                str(REPO_ROOT),
            )
            self.assertEqual(tampered.returncode, 2, tampered.stderr)
            tampered_report = json.loads(tampered.stdout)
            self.assertEqual(
                tampered_report["providers"]["grok"]["output_mismatch"], [item_id]
            )
            self.assertIn(
                f"{item_id}: stale output_sha256",
                tampered_report["providers"]["grok"]["semantic_review"]["invalid_items"],
            )

            output.write_bytes(b"\x89PNG\r\n\x1a\n" + b"not-an-image" * 800)
            garbage_hash = sha256(output)
            report = json.loads((queue / "REPORT.json").read_text(encoding="utf-8"))
            report["results"][item_id]["output_sha256"] = garbage_hash
            write_json(queue / "REPORT.json", report)
            review = json.loads(
                (production / "VISUAL_REVIEW.json").read_text(encoding="utf-8")
            )
            review["providers"]["grok"][item_id]["output_sha256"] = garbage_hash
            write_json(production / "VISUAL_REVIEW.json", review)

            forged = run_cli(
                "verify",
                "--target",
                target.name,
                "--focus",
                focus,
                "--root",
                str(REPO_ROOT),
            )
            self.assertEqual(forged.returncode, 2, forged.stderr)
            forged_report = json.loads(forged.stdout)
            self.assertEqual(
                forged_report["providers"]["grok"]["invalid_files"], [str(output)]
            )

            (queue / "REPORT.json").unlink()
            missing_report = run_cli(
                "verify",
                "--target",
                target.name,
                "--focus",
                focus,
                "--root",
                str(REPO_ROOT),
            )
            self.assertEqual(missing_report.returncode, 2, missing_report.stderr)
            missing_report_payload = json.loads(missing_report.stdout)
            self.assertEqual(
                missing_report_payload["providers"]["grok"]["missing_report_entries"],
                [item_id],
            )


if __name__ == "__main__":
    unittest.main()
