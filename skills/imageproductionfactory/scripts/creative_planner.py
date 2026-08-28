"""Compile a reviewed intent and item-specific creative plan into provider prompts.

This module is deliberately pure: callers pass contracts and library metadata,
and receive either a complete queue or explicit validation errors.  Raw site
cases and raw catalog templates never cross this seam into provider prompts.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any


PLAN_REQUIRED_FIELDS = (
    "id",
    "title",
    "template_id",
    "case_ids",
    "purpose",
    "output_topology",
    "text_policy",
    "scene",
    "action",
    "composition",
    "camera",
    "lighting",
    "styling",
    "palette",
    "mood",
    "style_direction",
    "aspect_ratio",
    "avoid",
)

POSITIVE_PLAN_FIELDS = (
    "title", "scene", "action", "composition", "camera", "lighting",
    "styling", "palette", "mood", "style_direction", "text_content",
)

MULTI_OUTPUT_TERMS = (
    "collage", "contact sheet", "character sheet", "moodboard", "mood board",
    "grid", "multi-panel", "multiple panels", "multiple versions", "multiple views",
    "2x2", "2 x 2", "3x3", "3 x 3", "diptych", "triptych", "split screen",
    "split-screen", "board of", "sheet of", "prancha", "grade", "mosaico",
    "várias versões", "varias versoes", "múltiplos painéis", "multiplos paineis",
    "拼贴", "网格", "多面板", "设定表", "九宫格", "複数ビュー",
)

TOPOLOGY_INSTRUCTIONS = {
    "single-frame": (
        "Generate exactly one standalone image with one continuous scene and one final composition. "
        "Do not create a collage, contact sheet, grid, split screen, moodboard, character sheet, "
        "comparison board, multiple panels, or multiple versions inside the canvas."
    ),
    "poster-canvas": "Generate exactly one finished poster or cover canvas with one controlled visual hierarchy.",
    "ui-screen": "Generate exactly one coherent interface or screenshot canvas.",
    "document-page": "Generate exactly one coherent publication or document page.",
    "multi-panel": "Generate one intentionally structured multi-panel board using only the panels specified in this item.",
    "sequence": "Generate one deliberate chronological sequence using only the frames specified in this item.",
}

TEXT_INSTRUCTIONS = {
    "forbidden": (
        "Include no written language: no words, letters, captions, labels, logos, signs, UI, "
        "watermarks, signatures, or decorative pseudo-text."
    ),
    "optional": "Do not add text unless exact text is supplied in TEXT CONTENT below.",
    "required": "Render only the exact text supplied in TEXT CONTENT; add no extra wording.",
}


class CreativePlanError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _contains_term(text: str, term: str) -> bool:
    needle = _fold(term).strip()
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", _fold(text)) is not None


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", _fold(value), flags=re.I)
    return re.sub(r"-+", "-", result).strip("-") or "image"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _as_string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        return None
    return [item.strip() for item in value]


def _case_ids(value: Any) -> list[int] | None:
    if not isinstance(value, list) or not value:
        return None
    result: list[int] = []
    for item in value:
        if isinstance(item, bool):
            return None
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            return None
    return result


def _compatible_text(template_policy: str, requested_policy: str) -> bool:
    if requested_policy == "forbidden":
        return template_policy != "required"
    if requested_policy == "required":
        return template_policy != "forbidden"
    return True


def _validate_item(
    index: int,
    item: dict,
    intent: dict,
    templates: dict[str, dict],
    cases: dict[int, dict],
    catalog_ids: set[str],
) -> list[str]:
    label = f"creative_plan[{index}]"
    errors: list[str] = []
    missing = [field for field in PLAN_REQUIRED_FIELDS if field not in item]
    if missing:
        errors.append(f"{label} missing fields: {', '.join(missing)}")
        return errors
    for field in PLAN_REQUIRED_FIELDS:
        if field in {"case_ids", "avoid"}:
            continue
        if not _text(item.get(field)):
            errors.append(f"{label}.{field} must be non-empty")

    item_id = _text(item.get("id"))
    if item_id != _slug(item_id):
        errors.append(f"{label}.id must already be a lowercase hyphen slug")
    if item.get("purpose") != intent["output_purpose"]:
        errors.append(f"{label}.purpose must equal intent.output_purpose")
    if item.get("output_topology") != intent["output_topology"]:
        errors.append(f"{label}.output_topology must equal intent.output_topology")
    if item.get("text_policy") != intent["text_policy"]:
        errors.append(f"{label}.text_policy must equal intent.text_policy")

    template_id = _text(item.get("template_id"))
    if template_id not in catalog_ids:
        errors.append(f"{label}.template_id is not in intent.catalog_include: {template_id}")
    template = templates.get(template_id)
    if not template:
        errors.append(f"{label}.template_id missing from template semantics: {template_id}")
    else:
        if intent["output_purpose"] not in template.get("compatible_purposes", []):
            errors.append(
                f"{label} template {template_id} is incompatible with purpose {intent['output_purpose']}"
            )
        if template.get("output_topology") != intent["output_topology"]:
            errors.append(
                f"{label} template {template_id} topology={template.get('output_topology')} "
                f"but intent requires {intent['output_topology']}"
            )
        if not _compatible_text(str(template.get("text_policy")), intent["text_policy"]):
            errors.append(
                f"{label} template {template_id} text_policy={template.get('text_policy')} "
                f"but intent requires {intent['text_policy']}"
            )
        target_kinds = template.get("target_kinds") or []
        if intent["target_kind"] not in target_kinds and "mixed" not in target_kinds:
            errors.append(
                f"{label} template {template_id} does not support target_kind={intent['target_kind']}"
            )
        if template.get("raw_template_allowed_in_provider_prompt") is not False:
            errors.append(f"{label} template {template_id} is not protected from raw prompt reuse")

    selected_case_ids = _case_ids(item.get("case_ids"))
    if selected_case_ids is None:
        errors.append(f"{label}.case_ids must contain 1-3 integer case IDs")
    else:
        if len(selected_case_ids) > 3:
            errors.append(f"{label}.case_ids may contain at most 3 references")
        for case_id in selected_case_ids:
            case = cases.get(case_id)
            if not case:
                errors.append(f"{label} references unknown case {case_id}")
                continue
            sem = case.get("semantics") or {}
            purposes = [sem.get("primary_purpose"), *(sem.get("secondary_purposes") or [])]
            if intent["output_purpose"] not in purposes:
                errors.append(
                    f"{label} case {case_id} is incompatible with purpose {intent['output_purpose']}"
                )
            if sem.get("output_topology") != intent["output_topology"]:
                errors.append(
                    f"{label} case {case_id} topology={sem.get('output_topology')} "
                    f"but intent requires {intent['output_topology']}"
                )
            if intent["target_kind"] not in (sem.get("target_kinds") or []) and "mixed" not in (
                sem.get("target_kinds") or []
            ):
                errors.append(
                    f"{label} case {case_id} does not support target_kind={intent['target_kind']}"
                )
            if not _compatible_text(str(sem.get("text_policy")), intent["text_policy"]):
                errors.append(
                    f"{label} case {case_id} text_policy={sem.get('text_policy')} "
                    f"but intent requires {intent['text_policy']}"
                )

    avoid = _as_string_list(item.get("avoid"))
    if avoid is None:
        errors.append(f"{label}.avoid must be a non-empty array of strings")
    if intent["text_policy"] == "required" and not _text(item.get("text_content")):
        errors.append(f"{label}.text_content is required by text_policy=required")
    if intent["text_policy"] == "forbidden" and _text(item.get("text_content")):
        errors.append(f"{label}.text_content must be empty when text_policy=forbidden")

    positive = " ".join(_text(item.get(field)) for field in POSITIVE_PLAN_FIELDS)
    for term in intent.get("must_not_infer") or []:
        if _contains_term(positive, str(term)):
            errors.append(f"{label} positively asserts forbidden inference '{term}'")
    if intent["output_topology"] == "single-frame":
        for term in MULTI_OUTPUT_TERMS:
            if _contains_term(positive, term):
                errors.append(f"{label} contains multi-output term '{term}' for single-frame intent")
    return errors


def _compose_prompt(
    item: dict,
    index: int,
    total: int,
    intent: dict,
    brief: dict,
    template: dict,
) -> str:
    explicit = "; ".join(str(value) for value in intent.get("explicit_facts") or [])
    allowed = "; ".join(str(value) for value in intent.get("allowed_transformations") or [])
    avoid = "; ".join(item["avoid"])
    case_ids = ", ".join(str(value) for value in item["case_ids"])
    text_content = _text(item.get("text_content")) or "none"
    brand = _text(brief.get("brand")) if intent.get("allow_brand") else "not authorized"
    topology_instruction = TOPOLOGY_INSTRUCTIONS[intent["output_topology"]]
    text_instruction = TEXT_INSTRUCTIONS[intent["text_policy"]]
    return (
        "CREATE THE IMAGE NOW\n"
        f"OUTPUT ITEM: {index} of {total} — {item['title']}\n"
        f"TRACE: purpose={intent['output_purpose']}; template={item['template_id']}; "
        f"inspiration_cases={case_ids}\n\n"
        "SEMANTIC CONTRACT\n"
        f"Original request: {intent['user_request']}\n"
        f"Requested artifact: {intent['requested_output']}\n"
        f"Target kind: {intent['target_kind']}\n"
        f"Subject role in this image: {intent['subject_role']}\n"
        f"Explicit facts: {explicit or 'none beyond the request and visible reference anchors'}\n"
        f"Allowed visual transformations: {allowed or 'none beyond the requested artifact'}\n"
        f"Permissions: profession={'authorized' if intent['allow_profession'] else 'not authorized'}; "
        f"business={'authorized' if intent['allow_business'] else 'not authorized'}; "
        f"brand={'authorized' if intent['allow_brand'] else 'not authorized'}\n"
        "Unsupported interpretation policy: do not assign any unverified claim or role, and do not "
        "introduce narrative elements that are not supported by the explicit facts.\n"
        "The artifact's visual style describes the requested image, not the subject's biography, profession, business, or brand.\n\n"
        "REFERENCE AND SUBJECT LOCK\n"
        f"Display name: {brief.get('display_name') or brief.get('target')}\n"
        f"Subject: {brief.get('subject_description')}\n"
        f"Identity/product lock: {brief.get('identity_lock')}\n"
        f"Brand: {brand}\n"
        "Use the attached real references as the identity/product source of truth.\n\n"
        "ITEM-SPECIFIC CREATIVE DIRECTION\n"
        f"Scene: {item['scene']}\n"
        f"Action or pose: {item['action']}\n"
        f"Composition: {item['composition']}\n"
        f"Camera and optics: {item['camera']}\n"
        f"Lighting: {item['lighting']}\n"
        f"Styling and materials: {item['styling']}\n"
        f"Palette: {item['palette']}\n"
        f"Mood: {item['mood']}\n"
        f"Style direction: {item['style_direction']}\n"
        f"Safe template capability: {template.get('visual_recipe')}\n"
        "The case IDs above are visual references only. Do not copy their example subjects, identities, roles, copy, products, props, or locations.\n\n"
        "OUTPUT CONTRACT\n"
        f"{topology_instruction}\n"
        f"Aspect ratio: {item['aspect_ratio']}.\n"
        f"Text policy: {intent['text_policy']}. {text_instruction}\n"
        f"TEXT CONTENT: {text_content}\n"
        f"Avoid: {avoid}.\n"
        "Return the finished image, not a process explanation."
    )


def compile_creative_plan(
    *,
    intent: dict,
    brief: dict,
    catalog_items: list[dict],
    template_semantics: list[dict],
    cases: list[dict],
    purpose_ids: set[str],
    topology_ids: set[str],
) -> dict:
    """Validate and compile the complete creative plan through one interface."""
    errors: list[str] = []
    purpose = intent.get("output_purpose")
    topology = intent.get("output_topology")
    text_policy = intent.get("text_policy")
    output_count = intent.get("output_count")
    if purpose not in purpose_ids:
        errors.append(f"Unknown intent.output_purpose: {purpose}")
    if topology not in topology_ids:
        errors.append(f"Unknown intent.output_topology: {topology}")
    if text_policy not in TEXT_INSTRUCTIONS:
        errors.append(f"Unknown intent.text_policy: {text_policy}")
    if isinstance(output_count, bool) or not isinstance(output_count, int) or not 1 <= output_count <= 20:
        errors.append("intent.output_count must be an integer from 1 to 20")

    plan = brief.get("creative_plan")
    if not isinstance(plan, list) or not plan:
        errors.append("brief.creative_plan must be a non-empty array")
        plan = []
    if isinstance(output_count, int) and len(plan) != output_count:
        errors.append(
            f"brief.creative_plan has {len(plan)} items but intent.output_count is {output_count}"
        )

    catalog_map = {item["id"]: item for item in catalog_items}
    template_map = {item["id"]: item for item in template_semantics}
    case_map = {int(item["id"]): item for item in cases}
    include = set(intent.get("catalog_include") or [])
    if not include:
        errors.append("intent.catalog_include must select at least one semantic template")
    missing_catalog = include - set(catalog_map)
    if missing_catalog:
        errors.append("catalog_include IDs not found: " + ", ".join(sorted(missing_catalog)))

    for index, item in enumerate(plan):
        if not isinstance(item, dict):
            errors.append(f"creative_plan[{index}] must be an object")
            continue
        errors.extend(_validate_item(index, item, intent, template_map, case_map, include))

    ids = [_text(item.get("id")) for item in plan if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        errors.append("creative_plan item IDs must be unique")
    used_templates = {
        _text(item.get("template_id")) for item in plan if isinstance(item, dict) and item.get("template_id")
    }
    unused_templates = include - used_templates
    if unused_templates:
        errors.append("catalog_include contains unused template IDs: " + ", ".join(sorted(unused_templates)))
    scenes = [_fold(_text(item.get("scene"))) for item in plan if isinstance(item, dict)]
    if len(scenes) != len(set(scenes)):
        errors.append("every creative_plan item must have a distinct scene")
    if errors:
        raise CreativePlanError(errors)

    queue: list[dict] = []
    prompt_hashes: dict[str, str] = {}
    for index, item in enumerate(plan, 1):
        template = template_map[item["template_id"]]
        prompt = _compose_prompt(item, index, len(plan), intent, brief, template)
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        prompt_hashes[item["id"]] = digest
        queue.append({
            **catalog_map[item["template_id"]],
            "id": item["id"],
            "safe_id": item["id"],
            "template_id": item["template_id"],
            "title_en": item["title"],
            "purpose": item["purpose"],
            "output_topology": item["output_topology"],
            "text_policy": item["text_policy"],
            "case_ids": item["case_ids"],
            "prompt": prompt,
            "prompt_sha256": digest,
        })
    if len(set(prompt_hashes.values())) != len(prompt_hashes):
        raise CreativePlanError(["creative_plan compiled duplicate provider prompts"])
    return {
        "items": queue,
        "diagnostics": {
            "schema_version": 1,
            "output_count": len(queue),
            "distinct_scenes": len(set(scenes)),
            "purpose": purpose,
            "output_topology": topology,
            "text_policy": text_policy,
            "template_ids": sorted(used_templates),
            "case_ids": sorted({case_id for item in plan for case_id in item["case_ids"]}),
            "prompt_sha256": prompt_hashes,
            "raw_case_prompts_in_provider_payload": False,
            "raw_catalog_templates_in_provider_payload": False,
            "must_not_infer_literals_in_provider_payload": False,
        },
    }


def render_plan_schema() -> dict:
    """Return the required plan fields for inspect/help surfaces."""
    return {
        "required_fields": list(PLAN_REQUIRED_FIELDS),
        "topologies": sorted(TOPOLOGY_INSTRUCTIONS),
        "text_policies": sorted(TEXT_INSTRUCTIONS),
        "case_ids": "1-3 purpose/topology-compatible inspiration cases per output",
    }
