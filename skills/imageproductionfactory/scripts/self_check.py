"""High-signal offline checks for Image Production Factory v2."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
ROOT = Path(
    os.environ.get("IMAGEGENSOURCE_ROOT", Path(__file__).resolve().parents[3])
).resolve()
sys.path.insert(0, str(SCRIPT_DIR))

import image_production_factory as factory  # noqa: E402
from creative_planner import CreativePlanError, compile_creative_plan  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def live_inputs() -> tuple[dict, dict, list[dict], dict]:
    intent = read_json(SKILL_DIR / "templates" / "intent-contract.example.json")
    intent["reviewed"] = True
    brief = read_json(SKILL_DIR / "templates" / "production-brief.example.json")
    _, catalog_items = factory.load_catalog(ROOT)
    library = factory.load_creative_library(ROOT)
    return intent, brief, catalog_items, library


def compile_example(
    intent: dict | None = None,
    brief: dict | None = None,
) -> dict:
    base_intent, base_brief, catalog_items, library = live_inputs()
    intent = intent or base_intent
    brief = brief or base_brief
    return compile_creative_plan(
        intent=intent,
        brief=brief,
        catalog_items=catalog_items,
        template_semantics=library["templates"],
        cases=library["cases"],
        purpose_ids={item["id"] for item in library["taxonomy"]["purposes"]},
        topology_ids=set(library["taxonomy"]["topologies"]),
    )


def expect_plan_error(intent: dict, brief: dict, needle: str) -> None:
    try:
        compile_example(intent, brief)
    except CreativePlanError as exc:
        message = "; ".join(exc.errors).casefold()
        assert needle.casefold() in message, message
    else:
        raise AssertionError(f"Expected CreativePlanError containing {needle!r}")


def check_contract_templates() -> None:
    intent, brief, _, _ = live_inputs()
    assert intent["schema_version"] == 2
    assert brief["schema_version"] == 2
    for key in ("output_purpose", "output_topology", "output_count", "text_policy"):
        assert brief[key] == intent[key], key
    assert len(brief["creative_plan"]) == intent["output_count"]
    assert intent["catalog_include"] == brief["catalog_include"]
    assert intent["target_kind"] != "person" or intent["catalog_include"]


def check_reference_discovery_excludes_outputs() -> None:
    with tempfile.TemporaryDirectory(prefix="image-factory-check-") as temp:
        target = Path(temp) / "TARGET"
        source = target / "ORIGINALSOURCE"
        generated = target / "PRODUCOES" / "old" / "FILA_CODEX"
        source.mkdir(parents=True)
        generated.mkdir(parents=True)
        (source / "01-face.png").write_bytes(b"source")
        (generated / "generated.png").write_bytes(b"generated")
        refs = factory.discover_references(target)
        assert [path.name for path in refs] == ["01-face.png"], refs


def check_full_purpose_library() -> None:
    library = factory.load_creative_library(ROOT)
    counts = library["manifest"]["counts"]
    assert counts["cases"] == len(library["cases"])
    assert counts["queue_templates"] == len(library["templates"])
    assert len({case["id"] for case in library["cases"]}) == counts["cases"]
    assert len({item["id"] for item in library["templates"]}) == counts["queue_templates"]
    upstream_styles = read_json(
        ROOT / "PROMPTS" / "site-library" / "upstream-style-library.json"
    )
    assert len(upstream_styles["templates"]) == 22
    assert len(upstream_styles["styles"]) == 19
    assert len(upstream_styles["scenes"]) == 10
    assert all(case["semantics"]["execution_role"] == "inspiration-only" for case in library["cases"])
    assert all(item["raw_template_allowed_in_provider_prompt"] is False for item in library["templates"])
    assert all(value > 0 for value in library["manifest"]["purpose_template_counts"].values())

    index = read_json(ROOT / "PROMPTS" / "site-library" / "purpose-index.json")["purposes"]
    assert set(index) == {item["id"] for item in library["taxonomy"]["purposes"]}
    assert "07-photography-realism/01-standard" in index["editorial-portrait"]["template_ids"]
    assert "05-brand-logos/03-brand-touchpoint-board" in index["product-hero"]["template_ids"]
    purpose_files = list((ROOT / "PROMPTS" / "site-library" / "purposes").glob("*.json"))
    assert len(purpose_files) == 17


def check_semantic_compilation() -> None:
    intent, brief, _, library = live_inputs()
    result = compile_example(intent, brief)
    items = result["items"]
    diagnostics = result["diagnostics"]
    assert len(items) == 3
    assert len({item["prompt_sha256"] for item in items}) == 3
    assert diagnostics["distinct_scenes"] == 3
    assert diagnostics["raw_case_prompts_in_provider_payload"] is False
    assert diagnostics["raw_catalog_templates_in_provider_payload"] is False
    assert diagnostics["must_not_infer_literals_in_provider_payload"] is False

    raw_template = (
        ROOT / "PROMPTS" / "07-photography-realism" / "01-standard.en.txt"
    ).read_text(encoding="utf-8").strip()
    case_map = {int(case["id"]): case for case in library["cases"]}
    for item in items:
        prompt = item["prompt"]
        positive = prompt.split("OUTPUT CONTRACT", 1)[0].casefold()
        assert raw_template not in prompt
        assert "barista" not in positive
        assert "denim apron" not in positive
        assert "character sheet" not in positive
        assert all(term.casefold() not in prompt.casefold() for term in intent["must_not_infer"])
        assert "generate exactly one standalone image" in prompt.casefold()
        assert "do not create a collage" in prompt.casefold()
        for case_id in item["case_ids"]:
            raw_case = case_map[int(case_id)]["prompt"].strip()
            assert raw_case not in prompt


def check_guardrails_reject_bad_plans() -> None:
    intent, brief, catalog_items, library = live_inputs()

    duplicated = copy.deepcopy(brief)
    duplicated["creative_plan"][1]["scene"] = duplicated["creative_plan"][0]["scene"]
    expect_plan_error(intent, duplicated, "distinct scene")

    inferred = copy.deepcopy(brief)
    inferred["creative_plan"][0]["scene"] = "a photographer presenting her photography business"
    expect_plan_error(intent, inferred, "forbidden inference")

    incompatible = next(
        item for item in library["templates"]
        if item["output_topology"] != "single-frame"
        and item["id"] in {catalog["id"] for catalog in catalog_items}
    )
    incompatible_intent = copy.deepcopy(intent)
    incompatible_intent["catalog_include"] = [incompatible["id"]]
    incompatible_brief = copy.deepcopy(brief)
    incompatible_brief["catalog_include"] = [incompatible["id"]]
    for item in incompatible_brief["creative_plan"]:
        item["template_id"] = incompatible["id"]
    expect_plan_error(incompatible_intent, incompatible_brief, "topology")


def check_provider_prompt_parity() -> None:
    result = compile_example()
    items = result["items"]
    with tempfile.TemporaryDirectory(prefix="image-factory-provider-check-") as temp:
        out = Path(temp)
        factory.run_provider("grok", out, items, [], True)
        factory.run_provider("codex", out, items, [], True)
        for item in items:
            grok = (out / "FILA_GROK" / "_prompts" / f"{item['safe_id']}.txt").read_text(
                encoding="utf-8"
            )
            codex = (out / "FILA_CODEX" / "_prompts" / f"{item['safe_id']}.txt").read_text(
                encoding="utf-8"
            )
            assert grok == codex == item["prompt"]


def check_source_faithful_full_library() -> None:
    items, manifest = factory.full_library_items(ROOT, "LUCAS")
    source_cases = {
        int(case["id"]): case
        for case in factory.load_creative_library(ROOT)["cases"]
    }
    expected_count = factory.load_creative_library(ROOT)["snapshot"]["case_count"]
    assert manifest["schema_version"] == 2
    assert len(items) == manifest["selection"]["count"] == expected_count
    assert manifest["library_snapshot"]["case_count"] == expected_count
    assert manifest["batches"]["size"] == factory.BATCH_SIZE
    assert manifest["batches"]["count"] == (
        expected_count + factory.BATCH_SIZE - 1
    ) // factory.BATCH_SIZE
    assert len({item["id"] for item in items}) == expected_count
    assert len({item["prompt_sha256"] for item in items}) == expected_count
    for position, (item, record) in enumerate(
        zip(items, manifest["cases"], strict=True), start=1
    ):
        case_id = int(record["case_id"])
        source = source_cases[case_id]
        source_prompt = str(source["prompt"])
        assert item["case_ids"] == [case_id]
        if record.get("source_prompt_compacted"):
            compacted = factory.compact_external_whitespace(source_prompt)
            assert item["prompt"] == record["only_added_prefix"] + compacted + record["only_added_suffix"]
            assert record["source_non_whitespace_preserved"] is True
        else:
            assert item["prompt"] == record["only_added_prefix"] + source_prompt + record["only_added_suffix"]
        assert factory.sha256_bytes(item["prompt"].encode("utf-8")) == item["prompt_sha256"]
        assert record["source_prompt_preserved_verbatim"] is (not record.get("source_prompt_compacted"))
        assert record["batch"] == (position - 1) // 20 + 1
        reference_expected = factory.source_uses_target_reference(source)
        assert item["use_target_reference"] is reference_expected
        assert record["use_target_reference"] is reference_expected
        assert record["human_subject_detected"] is factory.source_has_human_subject(source)
        if reference_expected:
            assert "SOURCE-FAITHFUL PERSON SUBSTITUTION" in item["prompt"] or record["target_theme_placeholder"]
        else:
            assert "SOURCE-FAITHFUL EXECUTION — NO TARGET SUBSTITUTION" in item["prompt"]
            assert "Do not add LUCAS" in item["prompt"]

    # Text that merely mentions a creator in social copy is not a request to
    # render that creator; an explicitly depicted celebrity is.
    assert items[1]["case_ids"] == [2]
    assert items[1]["use_target_reference"] is False
    assert items[3]["case_ids"] == [4]
    assert items[3]["use_target_reference"] is True


def check_semantic_review_gate() -> None:
    items = compile_example()["items"]
    bindings = {
        item["id"]: {
            "prompt_sha256": item["prompt_sha256"],
            "reference_sha256": [],
            "output_sha256": f"{index:064x}",
        }
        for index, item in enumerate(items, start=1)
    }
    empty = factory.visual_review_status(
        {"schema_version": 2, "reviewed": False, "providers": {}},
        "grok",
        items,
        bindings=bindings,
    )
    assert empty["complete"] is False
    assert empty["missing_items"] == [item["id"] for item in items]

    entries = {
        item["id"]: {
            **bindings[item["id"]],
            "accepted": True,
            "identity_fidelity": "pass",
            "topology": "pass",
            "text": "pass",
            "intent_alignment": "pass",
            "notes": "Inspected against the source reference and item contract.",
        }
        for item in items
    }
    complete = factory.visual_review_status(
        {"schema_version": 2, "reviewed": True, "providers": {"grok": entries}},
        "grok",
        items,
        bindings=bindings,
        identity_required_ids={item["id"] for item in items},
    )
    assert complete["complete"] is True, complete

    identity_not_checked = copy.deepcopy(entries)
    identity_not_checked[items[0]["id"]]["identity_fidelity"] = "not-applicable"
    identity_invalid = factory.visual_review_status(
        {
            "schema_version": 2,
            "reviewed": True,
            "providers": {"grok": identity_not_checked},
        },
        "grok",
        items,
        bindings=bindings,
        identity_required_ids={item["id"] for item in items},
    )
    assert identity_invalid["complete"] is False
    assert identity_invalid["invalid_items"]

    text_not_checked = copy.deepcopy(entries)
    text_not_checked[items[0]["id"]]["text"] = "not-applicable"
    text_invalid = factory.visual_review_status(
        {
            "schema_version": 2,
            "reviewed": True,
            "providers": {"grok": text_not_checked},
        },
        "grok",
        items,
        bindings=bindings,
        identity_required_ids={item["id"] for item in items},
    )
    assert text_invalid["complete"] is False
    assert text_invalid["invalid_items"]

    broken_entries = copy.deepcopy(entries)
    broken_entries[items[0]["id"]]["topology"] = "fail"
    contradictory = factory.visual_review_status(
        {"schema_version": 2, "reviewed": True, "providers": {"grok": broken_entries}},
        "grok",
        items,
        bindings=bindings,
        identity_required_ids={item["id"] for item in items},
    )
    assert contradictory["complete"] is False
    assert contradictory["invalid_items"]


def main() -> None:
    checks = [
        check_contract_templates,
        check_reference_discovery_excludes_outputs,
        check_full_purpose_library,
        check_semantic_compilation,
        check_guardrails_reject_bad_plans,
        check_provider_prompt_parity,
        check_source_faithful_full_library,
        check_semantic_review_gate,
    ]
    for check in checks:
        check()
        print(f"PASS {check.__name__}")
    print(json.dumps({"ok": True, "checks": len(checks)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
