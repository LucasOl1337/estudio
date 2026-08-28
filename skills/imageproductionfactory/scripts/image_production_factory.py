"""Image Production Factory — intent-first Grok + Codex queue runner.

Commands:
  inspect --target NAME --focus FOCUS [--root PATH]
  init    --target NAME --focus FOCUS [--root PATH]
  run     --target NAME --focus FOCUS [--providers both|grok|codex] [--dry-run]
  full-library --target NAME --focus FOCUS [--batch all|N] [--providers both|grok|codex] [--dry-run]
  selected-library --target NAME --focus FOCUS --case-ids ID,ID,... [--providers both|grok|codex] [--dry-run]
  full-templates --target NAME --focus FOCUS [--batch all|N] [--providers both|grok|codex] [--dry-run]
  verify  --target NAME --focus FOCUS [--root PATH]
  verify-selected-library --target NAME --focus FOCUS [--providers both|grok|codex]

No secrets are written. OAuth tokens are read from the active local 9Router DB.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
import traceback
import unicodedata
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from creative_planner import (
    CreativePlanError,
    compile_creative_plan,
    render_plan_schema,
)

DEFAULT_ROOT = Path(__file__).resolve().parents[3]
APPDATA = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
DB = APPDATA / "9router" / "db" / "data.sqlite"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
CODEX_UA = "codex_cli_rs/0.0.0 (ImageProductionFactory)"
CODEX_INSTRUCTIONS = (
    "Fulfill the request by using the image_generation tool. Treat the attached references, "
    "semantic contract, item-specific creative direction, output topology, and text policy as controlling. "
    "Generate only the requested output item; never add alternative versions or unrelated example content."
)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
BATCH_SIZE = 20
PROMPT_LIMIT = 8000
EXCLUDED_DIRS = {
    "prompts", "fila_grok", "fila_codex", "saidas_perfil", "saidas_codex",
    "teste_templates", "producoes", "vendor", "node_modules", ".git",
}


def slugify(value: str) -> str:
    s = value.strip().lower()
    s = re.sub(r"[^a-z0-9\u00c0-\u024f]+", "-", s, flags=re.I)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "producao"


def resolve_target(root: Path, target: str) -> Path:
    if not root.is_dir():
        raise SystemExit(f"ImageGenSource root not found: {root}")
    wanted = target.strip().casefold()
    alvos = root / "ALVOS"
    search_root = alvos if alvos.is_dir() else root
    candidates = [p for p in search_root.iterdir() if p.is_dir() and p.name.casefold() == wanted]
    if not candidates:
        names = sorted(
            p.name for p in search_root.iterdir()
            if p.is_dir() and p.name.casefold() != "prompts"
        )
        raise SystemExit(
            f"Target '{target}' not found under {search_root}. Available: {', '.join(names)}"
        )
    return candidates[0].resolve()


def run_dir(target_dir: Path, focus: str) -> Path:
    return target_dir / "PRODUCOES" / slugify(focus)


def is_source_image(path: Path, target_dir: Path) -> bool:
    try:
        rel = path.resolve().relative_to(target_dir.resolve())
    except ValueError:
        return False
    if path.suffix.lower() not in IMAGE_EXTS or not path.is_file():
        return False
    parts = {p.casefold() for p in rel.parts[:-1]}
    if parts & EXCLUDED_DIRS:
        return False
    return is_decodable_image(path)


def is_decodable_image(path: Path) -> bool:
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return False
    if len(head) < 8:
        return False
    if head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8") or head.startswith(b"GIF8"):
        return True
    return len(head) >= 12 and head[8:12] == b"WEBP"


def ref_score(path: Path) -> tuple[int, int, str]:
    text = str(path).casefold()
    name = path.name.casefold()
    score = 0
    for key, weight in [
        ("rosto", 100), ("face", 100), ("pessoa", 80), ("person", 80),
        ("reference", 70), ("referencia", 70), ("hero", 60), ("corpo", 40),
        ("body", 40), ("screenshot", 35), ("produto", 35), ("product", 35),
        ("logo", 30), ("style", 5), ("estilo", 5),
    ]:
        if key in text:
            score += weight
    if re.match(r"^0?1[-_]", name):
        score += 30
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return (-score, -size, str(path).casefold())


def discover_references(target_dir: Path) -> list[Path]:
    refs = [p for p in target_dir.rglob("*") if is_source_image(p, target_dir)]
    refs.sort(key=ref_score)
    return refs


def catalog_path(root: Path) -> Path:
    return root / "PROMPTS" / "catalog.json"


def load_catalog(root: Path) -> tuple[dict, list[dict]]:
    path = catalog_path(root)
    if not path.is_file():
        raise SystemExit(f"Prompt catalog not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    items: list[dict] = []
    for category in data.get("categories", []):
        for item in category.get("items", []):
            if item.get("queue_ready"):
                items.append({**item, "category": category["slug"]})
    return data, items


def creative_library_path(root: Path) -> Path:
    return root / "PROMPTS" / "site-library"


def load_creative_library(root: Path) -> dict:
    base = creative_library_path(root)
    required = {
        "manifest": base / "manifest.json",
        "taxonomy": base / "taxonomy.json",
        "templates": base / "template-semantics.json",
        "cases": base / "cases.json",
    }
    missing = [str(path) for path in required.values() if not path.is_file()]
    if missing:
        raise SystemExit(
            "Purpose library is incomplete. Rebuild PROMPTS/site-library first. Missing: "
            + ", ".join(missing)
        )
    manifest = json.loads(required["manifest"].read_text(encoding="utf-8"))
    case_payload = json.loads(required["cases"].read_text(encoding="utf-8"))
    cases = case_payload.get("cases")
    if not isinstance(cases, list):
        raise SystemExit(f"Purpose library cases must be a JSON array: {required['cases']}")
    manifest_count = (manifest.get("counts") or {}).get("cases")
    payload_count = case_payload.get("total_cases")
    actual_count = len(cases)
    if (
        not isinstance(manifest_count, int)
        or isinstance(manifest_count, bool)
        or not isinstance(payload_count, int)
        or isinstance(payload_count, bool)
        or manifest_count != payload_count
        or payload_count != actual_count
    ):
        raise SystemExit(
            "Purpose library case count mismatch: "
            f"manifest={manifest_count!r}, cases.json={payload_count!r}, actual={actual_count}"
        )
    case_ids = [case.get("id") for case in cases]
    if any(
        not isinstance(case_id, int) or isinstance(case_id, bool) or case_id <= 0
        for case_id in case_ids
    ):
        raise SystemExit("Purpose library case IDs must be positive integers")
    if len(case_ids) != len(set(case_ids)):
        raise SystemExit("Purpose library contains duplicate case IDs")
    source = manifest.get("source") or {}
    snapshot = {
        "repository": source.get("repository"),
        "commit": source.get("commit"),
        "case_count": actual_count,
        "max_case_id": max(case_ids, default=None),
        "missing_ids": (
            sorted(set(range(1, max(case_ids) + 1)) - set(case_ids))
            if case_ids
            else []
        ),
        "manifest_sha256": sha256_bytes(required["manifest"].read_bytes()),
        "cases_index_sha256": sha256_bytes(required["cases"].read_bytes()),
    }
    return {
        "path": str(base),
        "manifest": manifest,
        "snapshot": snapshot,
        "taxonomy": json.loads(required["taxonomy"].read_text(encoding="utf-8")),
        "templates": json.loads(required["templates"].read_text(encoding="utf-8"))["templates"],
        "cases": cases,
    }


def mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp", ".gif": "image/gif",
    }.get(ext, "image/png")


def data_url(path: Path) -> str:
    return f"data:{mime_for(path)};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def safe_reference(target_dir: Path, value: str) -> Path:
    raw = Path(value)
    path = raw if raw.is_absolute() else target_dir / raw
    path = path.resolve()
    try:
        path.relative_to(target_dir.resolve())
    except ValueError:
        raise ValueError(f"Reference escapes target folder: {value}")
    if not is_source_image(path, target_dir):
        raise ValueError(f"Invalid/generated/missing reference: {value}")
    return path


def brief_path(target_dir: Path, focus: str) -> Path:
    return run_dir(target_dir, focus) / "production-brief.json"


def intent_path(target_dir: Path, focus: str) -> Path:
    return run_dir(target_dir, focus) / "intent-contract.json"


def load_intent(target_dir: Path, focus: str) -> dict:
    path = intent_path(target_dir, focus)
    if not path.is_file():
        raise SystemExit(
            f"Intent contract not found: {path}. The agent must create and review intent-contract.json before init."
        )
    intent = json.loads(path.read_text(encoding="utf-8"))
    required = [
        "schema_version", "target", "focus", "target_kind", "user_request",
        "requested_output", "subject_role", "output_purpose", "output_topology",
        "output_count", "text_policy", "must_not_infer", "allow_brand",
        "allow_business", "allow_profession", "allow_full_catalog",
        "catalog_include", "catalog_exclude", "reviewed",
    ]
    missing = [key for key in required if key not in intent]
    if missing:
        raise SystemExit(f"Intent contract missing required fields: {', '.join(missing)}")
    empty = [
        key for key in (
            "target", "focus", "target_kind", "user_request", "requested_output", "subject_role",
        )
        if not str(intent[key]).strip()
    ]
    if empty:
        raise SystemExit(f"Intent contract has empty required fields: {', '.join(empty)}")
    if intent["schema_version"] != 2:
        raise SystemExit("Intent schema_version must be 2")
    for key in ("allow_brand", "allow_business", "allow_profession", "allow_full_catalog", "reviewed"):
        if not isinstance(intent[key], bool):
            raise SystemExit(f"Intent {key} must be true or false")
    for key in ("must_not_infer", "catalog_include", "catalog_exclude"):
        if not isinstance(intent[key], list) or not all(isinstance(value, str) for value in intent[key]):
            raise SystemExit(f"Intent {key} must be a JSON array of strings")
    for key in ("explicit_facts", "allowed_transformations"):
        if key in intent and (
            not isinstance(intent[key], list)
            or not all(isinstance(value, str) for value in intent[key])
        ):
            raise SystemExit(f"Intent {key} must be a JSON array of strings")
    if str(intent["target"]).casefold() != target_dir.name.casefold():
        raise SystemExit(
            f"Intent target mismatch: contract={intent['target']} folder={target_dir.name}"
        )
    if str(intent["focus"]).strip().casefold() != focus.strip().casefold():
        raise SystemExit(f"Intent focus mismatch: contract={intent['focus']} command={focus}")
    if intent["target_kind"] not in {
        "person", "product", "project", "brand", "interface", "place",
        "character", "concept", "mixed",
    }:
        raise SystemExit(
            "Intent target_kind must be person, product, project, brand, interface, place, "
            "character, concept, or mixed"
        )
    if isinstance(intent["output_count"], bool) or not isinstance(intent["output_count"], int):
        raise SystemExit("Intent output_count must be an integer")
    if not 1 <= intent["output_count"] <= 20:
        raise SystemExit("Intent output_count must be between 1 and 20")
    if intent["text_policy"] not in {"forbidden", "optional", "required"}:
        raise SystemExit("Intent text_policy must be forbidden, optional, or required")
    if intent.get("reviewed") is not True:
        raise SystemExit("Intent contract must set reviewed=true after agent semantic review")
    return intent


def default_brief(target_dir: Path, focus: str, refs: list[Path], intent: dict) -> dict:
    target = target_dir.name
    rels = [str(p.relative_to(target_dir)).replace("\\", "/") for p in refs[:3]]
    display = target.replace("_", " ").replace("-", " ").title()
    is_person = intent["target_kind"] == "person"
    requested = str(intent["requested_output"])
    subject_role = str(intent["subject_role"])
    allow_brand = intent["allow_brand"]
    return {
        "schema_version": 2,
        "target": target,
        "display_name": display,
        "focus": focus,
        "target_kind": intent["target_kind"],
        "output_purpose": intent["output_purpose"],
        "output_topology": intent["output_topology"],
        "output_count": intent["output_count"],
        "text_policy": intent["text_policy"],
        "intent_contract": "intent-contract.json",
        "allow_brand": allow_brand,
        "allow_business": intent["allow_business"],
        "allow_profession": intent["allow_profession"],
        "brand": display if allow_brand else "",
        "identity_lock": (
            f"Use the attached real references for {display}. Preserve the exact visible identity. "
            f"The subject role is: {subject_role}. Never infer a profession, business, service, or brand "
            "that the intent contract does not explicitly authorize. Never replace the subject with a generic substitute."
            if is_person else
            f"Use the attached real references for {display}. Preserve the exact visible identity, product geometry, "
            "interface, palette, materials, and brand anchors. Never replace the subject with a generic substitute."
        ),
        "subject_description": f"{display}, {subject_role}. Requested output: {requested}",
        "audience": str(intent.get("audience") or "general audience"),
        "palette": "derive the palette from the real references",
        "hero_product": f"{display} as {subject_role}" if is_person else f"the real {display} subject/product",
        "scene_direction": requested,
        "brand_keywords": ["recognizable", "coherent", "reference-faithful"],
        "references": rels,
        "providers": ["grok", "codex"],
        "creative_plan": [],
        "catalog_include": list(intent["catalog_include"]),
        "catalog_exclude": list(intent["catalog_exclude"]),
    }


def load_brief(target_dir: Path, focus: str) -> dict:
    path = brief_path(target_dir, focus)
    if not path.is_file():
        raise SystemExit(f"Brief not found: {path}. Run init, inspect references, then refine it.")
    brief = json.loads(path.read_text(encoding="utf-8"))
    required = [
        "schema_version", "target", "display_name", "focus", "identity_lock", "references",
        "output_purpose", "output_topology", "output_count", "text_policy", "creative_plan",
    ]
    missing = [k for k in required if k not in brief]
    if missing:
        raise SystemExit(f"Brief missing required fields: {', '.join(missing)}")
    empty = [key for key in ("target", "display_name", "focus", "identity_lock") if not brief.get(key)]
    if empty:
        raise SystemExit(f"Brief has empty required fields: {', '.join(empty)}")
    if brief["schema_version"] != 2:
        raise SystemExit("Brief schema_version must be 2")
    return brief


def semantic_text_fields(brief: dict) -> dict[str, str]:
    fields = {}
    for key in (
        "brand", "identity_lock", "subject_description", "audience", "hero_product",
        "scene_direction", "brand_keywords", "copy",
    ):
        value = brief.get(key)
        fields[key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value or "")
    return fields


def folded(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def contains_term(text: str, term: str) -> bool:
    needle = folded(term).strip()
    if not needle:
        return False
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", folded(text)) is not None


def intent_violations(brief: dict, intent: dict) -> list[str]:
    violations: list[str] = []
    if brief.get("target_kind") != intent.get("target_kind"):
        violations.append(
            f"target_kind mismatch: brief={brief.get('target_kind')} intent={intent.get('target_kind')}"
        )
    for key in ("allow_brand", "allow_business", "allow_profession"):
        if key in brief and brief[key] != intent.get(key):
            violations.append(
                f"{key} mismatch: brief={brief[key]} intent={intent.get(key)}"
            )
    for key in ("output_purpose", "output_topology", "output_count", "text_policy"):
        if brief.get(key) != intent.get(key):
            violations.append(
                f"{key} mismatch: brief={brief.get(key)} intent={intent.get(key)}"
            )
    if intent.get("target_kind") == "person" and not intent.get("allow_brand", False) and brief.get("brand"):
        violations.append(f"brand is not authorized for this person: {brief.get('brand')}")
    intent_include = list(intent.get("catalog_include") or [])
    brief_include = list(brief.get("catalog_include") or [])
    if intent.get("target_kind") == "person" and not intent_include and not intent.get("allow_full_catalog", False):
        violations.append(
            "person intent requires explicit catalog_include; set allow_full_catalog=true only when the user requests it"
        )
    if intent.get("target_kind") == "person" and intent.get("allow_full_catalog", False):
        denied = [
            label for label, key in (
                ("profession", "allow_profession"),
                ("business", "allow_business"),
                ("brand", "allow_brand"),
            )
            if not intent.get(key, False)
        ]
        if denied:
            violations.append(
                "full catalog for a person conflicts with unauthorized roles "
                f"({', '.join(denied)}); use explicit catalog_include instead"
            )
    if intent_include != brief_include:
        violations.append("brief.catalog_include must exactly match intent.catalog_include")
    if not intent.get("allow_brand", False):
        brand_items = [item_id for item_id in intent_include if str(item_id).startswith("05-brand-logos/")]
        if brand_items:
            violations.append(
                "catalog items require allow_brand=true: " + ", ".join(brand_items)
            )
    intent_exclude = list(intent.get("catalog_exclude") or [])
    brief_exclude = list(brief.get("catalog_exclude") or [])
    if intent_exclude != brief_exclude:
        violations.append("brief.catalog_exclude must exactly match intent.catalog_exclude")
    fields = semantic_text_fields(brief)
    for term in intent.get("must_not_infer") or []:
        for field, text in fields.items():
            if contains_term(text, str(term)):
                violations.append(f"forbidden inference '{term}' in brief.{field}")
    return violations


def queue_items(root: Path, brief: dict, intent: dict) -> tuple[list[dict], dict]:
    _, catalog_items = load_catalog(root)
    library = load_creative_library(root)
    purpose_ids = {item["id"] for item in library["taxonomy"]["purposes"]}
    topology_ids = set(library["taxonomy"]["topologies"])
    try:
        compilation = compile_creative_plan(
            intent=intent,
            brief=brief,
            catalog_items=catalog_items,
            template_semantics=library["templates"],
            cases=library["cases"],
            purpose_ids=purpose_ids,
            topology_ids=topology_ids,
        )
    except CreativePlanError as exc:
        raise SystemExit("Creative plan violation: " + "; ".join(exc.errors)) from exc
    return compilation["items"], compilation["diagnostics"]


def oauth(provider: str) -> dict:
    if not DB.is_file():
        raise RuntimeError(f"9Router DB not found: {DB}")
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    row = con.execute(
        "select data from providerConnections where provider=? and isActive=1", (provider,)
    ).fetchone()
    if not row:
        raise RuntimeError(f"No active {provider} OAuth connection in 9Router")
    data = json.loads(row[0])
    token = data.get("accessToken") or ""
    if not token:
        raise RuntimeError(f"Empty {provider} OAuth access token")
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        claims = json.loads(base64.urlsafe_b64decode(part))
        exp = claims.get("exp", 0)
        if exp and time.time() > exp + 30:
            raise RuntimeError(f"{provider} OAuth token expired")
    except RuntimeError:
        raise
    except Exception:
        pass
    return data


def download(url: str, dest: Path) -> None:
    r = httpx.get(url, headers={"User-Agent": UA, "Accept": "image/*,*/*;q=0.8"}, timeout=120, follow_redirects=True)
    r.raise_for_status()
    dest.write_bytes(r.content)


GROK_ALLOWED_ASPECT_RATIOS = (
    "1:1",
    "3:4",
    "4:3",
    "9:16",
    "16:9",
    "2:3",
    "3:2",
    "9:19.5",
    "19.5:9",
    "9:20",
    "20:9",
    "1:2",
    "2:1",
    "21:9",
    "5:2",
    "auto",
)
GROK_ASPECT_RATIO_LARGE_DISTORTION_THRESHOLD = 1.5


def grok_aspect_ratio(requested: str) -> str:
    if requested in GROK_ALLOWED_ASPECT_RATIOS:
        return requested
    match = re.fullmatch(r"(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)", requested.strip())
    if not match:
        raise ValueError(f"Grok aspect_ratio is not parseable: {requested!r}")
    left, right = float(match.group(1)), float(match.group(2))
    if left <= 0 or right <= 0:
        raise ValueError(f"Grok aspect_ratio has non-positive sides: {requested!r}")
    wanted = left / right
    portrait = left < right
    landscape = left > right
    best_name = None
    best_diff = None
    for candidate in GROK_ALLOWED_ASPECT_RATIOS:
        if candidate == "auto":
            continue
        c_left, c_right = (float(part) for part in candidate.split(":"))
        if portrait and not c_left < c_right:
            continue
        if landscape and not c_left > c_right:
            continue
        if not portrait and not landscape and c_left != c_right:
            continue
        diff = abs((c_left / c_right) - wanted)
        if best_diff is None or diff < best_diff:
            best_name, best_diff = candidate, diff
    if best_name is None:
        raise ValueError(f"Grok aspect_ratio has no same-orientation candidate: {requested!r}")
    return best_name


def grok_aspect_ratio_large_distortion(requested: str, sent: str) -> bool:
    try:
        wanted_left, wanted_right = (float(part) for part in requested.split(":"))
        sent_left, sent_right = (float(part) for part in sent.split(":"))
        wanted = wanted_left / wanted_right
        got = sent_left / sent_right
    except (ValueError, ZeroDivisionError):
        return False
    if wanted <= 0 or got <= 0:
        return False
    stretch = max(wanted, got) / min(wanted, got)
    return stretch > GROK_ASPECT_RATIO_LARGE_DISTORTION_THRESHOLD


def grok_generate(
    prompt: str,
    token: str,
    refs: list[Path],
    dest: Path,
    aspect_ratio: str = "1:1",
) -> dict:
    t0 = time.time()
    requested = aspect_ratio or "1:1"
    audit: dict[str, Any] = {"aspect_ratio_requested": requested}
    try:
        sent = grok_aspect_ratio(requested)
        audit["aspect_ratio_sent"] = sent
        audit["aspect_ratio_large_distortion"] = grok_aspect_ratio_large_distortion(
            requested, sent
        )
        fields = [{"url": data_url(p), "type": "image_url"} for p in refs[:3]]
        payload: dict[str, Any] = {
            "model": "grok-imagine-image-quality",
            "prompt": prompt,
            "aspect_ratio": sent,
        }
        endpoint = "https://api.x.ai/v1/images/generations"
        if len(fields) == 1:
            endpoint = "https://api.x.ai/v1/images/edits"
            payload["image"] = fields[0]
        elif fields:
            endpoint = "https://api.x.ai/v1/images/edits"
            payload["images"] = fields
        r = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": UA},
            json=payload, timeout=180,
        )
        if r.status_code >= 400:
            return {
                "ok": False,
                "code": r.status_code,
                "error": r.text[:500],
                "sec": round(time.time()-t0, 1),
                **audit,
            }
        url = r.json()["data"][0]["url"]
        download(url, dest)
        return {
            "ok": True,
            "path": str(dest),
            "bytes": dest.stat().st_size,
            "sec": round(time.time()-t0, 1),
            **audit,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "sec": round(time.time()-t0, 1),
            **audit,
        }


def extract_image_b64(value: Any) -> str | None:
    found = None
    if isinstance(value, dict):
        if value.get("type") == "image_generation_call" and isinstance(value.get("result"), str):
            found = value["result"]
        if isinstance(value.get("partial_image_b64"), str):
            found = value["partial_image_b64"]
        for child in value.values():
            nested = extract_image_b64(child)
            if nested:
                found = nested
    elif isinstance(value, list):
        for child in value:
            nested = extract_image_b64(child)
            if nested:
                found = nested
    return found


def codex_request_instructions(prompt: str) -> str:
    return f"{CODEX_INSTRUCTIONS}\n\n{prompt}"


def iter_sse(response):
    event = None
    data_lines: list[str] = []

    def flush():
        nonlocal event, data_lines
        if not data_lines:
            event = None
            return None
        raw = "\n".join(data_lines).strip()
        ev = event
        event, data_lines = None, []
        if not raw or raw == "[DONE]":
            return None
        obj = json.loads(raw)
        if isinstance(obj, dict) and ev and "type" not in obj:
            obj["type"] = ev
        return obj

    for line in response.iter_lines():
        line = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
        if line == "":
            obj = flush()
            if obj is not None:
                yield obj
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    obj = flush()
    if obj is not None:
        yield obj


def codex_generate(
    prompt: str,
    token: str,
    account_id: str | None,
    refs: list[Path],
    dest: Path,
    aspect_ratio: str = "1:1",
) -> dict:
    t0 = time.time()
    headers = {
        "User-Agent": CODEX_UA, "originator": "codex_cli_rs", "Accept": "text/event-stream",
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    }
    if account_id:
        headers["ChatGPT-Account-ID"] = account_id
    content: list[dict] = [{"type": "input_text", "text": prompt}]
    content += [{"type": "input_image", "image_url": data_url(p)} for p in refs[:3]]
    left, right = (int(value) for value in aspect_ratio.split(":"))
    size = "1024x1024" if left == right else ("1536x1024" if left > right else "1024x1536")
    payload = {
        "model": "gpt-5.5", "store": False,
        "instructions": codex_request_instructions(prompt),
        "input": [{"type": "message", "role": "user", "content": content}],
        "tools": [{
            "type": "image_generation", "model": "gpt-image-2", "size": size,
            "quality": "high", "output_format": "png", "background": "opaque", "partial_images": 1,
        }],
        "stream": True,
    }
    image_b64 = None
    deadline_capped = False
    deadline = t0 + 240
    # A wall-clock check inside the SSE loop cannot run while the socket read is
    # blocked. Keep the per-read timeout bounded as the second half of the cap.
    timeout = httpx.Timeout(240, connect=30, read=120, write=60, pool=30)
    try:
        with httpx.Client(headers=headers, timeout=timeout) as client:
            with client.stream("POST", "https://chatgpt.com/backend-api/codex/responses", json=payload) as r:
                if r.status_code >= 400:
                    r.read()
                    return {"ok": False, "code": r.status_code, "error": r.text[:500], "sec": round(time.time()-t0, 1)}
                for obj in iter_sse(r):
                    found = extract_image_b64(obj)
                    if found:
                        image_b64 = found
                    if time.time() >= deadline:
                        deadline_capped = True
                        break
    except httpx.ReadTimeout:
        deadline_capped = True
        if not image_b64:
            return {
                "ok": False,
                "error": "Codex stream produced no image before the 120s read timeout",
                "sec": round(time.time()-t0, 1),
                "deadline_capped": True,
            }
    if not image_b64:
        return {"ok": False, "error": "no image result in Codex stream", "sec": round(time.time()-t0, 1)}
    dest.write_bytes(base64.b64decode(image_b64))
    return {
        "ok": True,
        "path": str(dest),
        "bytes": dest.stat().st_size,
        "sec": round(time.time()-t0, 1),
        "size": size,
        "aspect_ratio": aspect_ratio,
        "deadline_capped": deadline_capped,
    }


def account_id(data: dict) -> str | None:
    value = (data.get("providerSpecificData") or {}).get("chatgptAccountId")
    if value:
        return str(value)
    token = data.get("accessToken") or ""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        claims = json.loads(base64.urlsafe_b64decode(part))
        return (claims.get("https://api.openai.com/auth") or {}).get("chatgpt_account_id")
    except Exception:
        return None


def load_report(path: Path) -> dict:
    if not path.is_file():
        return {"schema_version": 2, "results": {}}
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("schema_version") != 2:
        raise SystemExit(f"Provider report schema_version must be 2: {path}")
    if not isinstance(report.get("results"), dict):
        raise SystemExit(f"Provider report results must be a JSON object: {path}")
    return report


def save_report(path: Path, report: dict) -> None:
    payload = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def run_provider(provider: str, out: Path, items: list[dict], refs: list[Path], dry_run: bool) -> dict:
    ext = ".jpg" if provider == "grok" else ".png"
    queue_dir = out / ("FILA_GROK" if provider == "grok" else "FILA_CODEX")
    prompt_dir = queue_dir / "_prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    report_path = queue_dir / "REPORT.json"
    report = load_report(report_path)
    results = report.setdefault("results", {})
    report.update({
        "schema_version": 2,
        "provider": provider, "reference_paths": [str(p) for p in refs],
        "model": "grok-imagine-image-quality" if provider == "grok" else "gpt-image-2-high",
    })
    for item in items:
        (prompt_dir / f"{item['safe_id']}.txt").write_bytes(item["prompt"].encode("utf-8"))
    if dry_run:
        return {"provider": provider, "prompts": len(items), "path": str(prompt_dir)}

    auth = oauth("xai" if provider == "grok" else "codex")
    token = auth["accessToken"]
    acct = account_id(auth) if provider == "codex" else None
    ok_n = fail_n = skip_n = 0
    for index, item in enumerate(items, 1):
        dest = queue_dir / f"{item['safe_id']}{ext}"
        prev = results.get(item["id"])
        item_refs = refs if item.get("use_target_reference", True) else []
        item_reference_paths = [str(path) for path in item_refs]
        item_reference_sha256 = [sha256_bytes(path.read_bytes()) for path in item_refs]
        current_prompt_hash = sha256_bytes(item["prompt"].encode("utf-8"))
        if item.get("prompt_sha256") != current_prompt_hash:
            raise RuntimeError(f"Current prompt hash is stale for {item['id']}")
        current_output_hash = sha256_bytes(dest.read_bytes()) if valid_image(dest) else None
        if (
            current_output_hash is not None
            and prev
            and prev.get("ok") is True
            and prev.get("prompt_sha256") == current_prompt_hash
            and prev.get("reference_sha256") == item_reference_sha256
            and prev.get("output_sha256") == current_output_hash
        ):
            skip_n += 1
            print(f"[{provider} {index:02d}/{len(items)}] SKIP {item['id']}", flush=True)
            continue
        print(f"[{provider} {index:02d}/{len(items)}] GEN {item['id']} ...", flush=True)
        try:
            result = (
                grok_generate(
                    item["prompt"], token, item_refs, dest, item.get("aspect_ratio") or "1:1"
                )
                if provider == "grok"
                else codex_generate(
                    item["prompt"], token, acct, item_refs, dest, item.get("aspect_ratio") or "1:1"
                )
            )
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-500:]}
        if result.get("ok"):
            metadata = image_metadata(dest)
            if metadata is None:
                result = {
                    **result,
                    "ok": False,
                    "error": "Provider did not produce a decodable supported image",
                }
            else:
                result["output_sha256"] = sha256_bytes(dest.read_bytes())
                result["image"] = metadata
        results[item["id"]] = {
            **result,
            "category": item["category"],
            "title_en": item.get("title_en"),
            "template_id": item.get("template_id"),
            "case_ids": item.get("case_ids") or [],
            "purpose": item.get("purpose"),
            "output_topology": item.get("output_topology"),
            "text_policy": item.get("text_policy"),
            "prompt_sha256": current_prompt_hash,
            "reference_paths": item_reference_paths,
            "reference_sha256": item_reference_sha256,
        }
        save_report(report_path, report)
        if result.get("ok"):
            ok_n += 1
            print(f"  OK {result.get('bytes')} bytes {result.get('sec')}s", flush=True)
        else:
            fail_n += 1
            print(f"  FAIL {result.get('code')} {str(result.get('error'))[:160]}", flush=True)
            if result.get("code") in (401, 403):
                break
            if result.get("code") == 429:
                time.sleep(30)
        time.sleep(0.6 if provider == "grok" else 1.0)
    total_ok = sum(1 for v in results.values() if v.get("ok"))
    total_fail = sum(1 for v in results.values() if not v.get("ok"))
    report["summary"] = {
        "ok": total_ok, "fail": total_fail, "generated_this_run": ok_n,
        "failed_this_run": fail_n, "skip": skip_n, "total_queue": len(items),
        "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    save_report(report_path, report)
    return report["summary"]


SOURCE_FAITHFUL_PERSON_DIRECTIVE = """SOURCE-FAITHFUL PERSON SUBSTITUTION FOR {target}
Use the attached reference image only as the authoritative visual identity for {target}.
Execute the SOURCE PROMPT with exactly one allowed semantic change: whenever it requests a visible central human, celebrity, public figure, athlete, model, actor, host, or fictional human character, render that person's identity as reference-grounded {target}. Any visible display name, account name, handle, character label, or title that directly identifies that replaced central person must also become {target}; this identity-label substitution is the only allowed copy change. Preserve every other source requirement unchanged, including the artifact, subject matter, brands, products, interfaces, places, objects, events, supporting characters, all non-identity visible copy, statistics, composition, number of panels or subjects, artistic style, camera, lighting, materials, aspect ratio, and constraints. Do not turn a product, brand, interface, place, object, event, or information system into {target}. Do not add {target} where the source does not request a visible person. Do not invent facts about {target}; requested clothing, pose, action, setting, and styling are fictional visual staging only.

SOURCE PROMPT — PRESERVE VERBATIM EXCEPT FOR THE VISIBLE PERSON IDENTITY SUBSTITUTION ABOVE:
"""

SOURCE_FAITHFUL_UNCHANGED_DIRECTIVE = """SOURCE-FAITHFUL EXECUTION — NO TARGET SUBSTITUTION
The SOURCE PROMPT does not request a visible target person or explicit target placeholder. Execute it exactly as written. Do not add {target}, do not reinterpret its subject as {target}, and do not use a target reference image. Preserve the artifact, subject matter, brands, products, interfaces, places, objects, events, people, visible copy, statistics, composition, artistic style, camera, lighting, materials, aspect ratio, and constraints.

SOURCE PROMPT — PRESERVE VERBATIM:
"""

SOURCE_FAITHFUL_TEMPLATE_DIRECTIVE = """SOURCE-FAITHFUL TEMPLATE INSTANTIATION FOR {target}
Use the attached reference images as the authoritative visual source for {target}.
Instantiate every bracketed placeholder in the SOURCE TEMPLATE below with a concrete choice appropriate to {target}. Keep the template's requested artifact, topology, hierarchy, visual mechanism, camera, lighting, materials, aspect ratio, and constraints. Make {target} the central game, product, brand, interface, place, or character according to the template. Use the exact visible name {target} when copy is required. Do not leave placeholders visible. Do not invent statistics, prices, awards, biographies, partnerships, or business claims. If a template requires a person, use a reference-grounded visible {target} player character or avatar from the references; never invent or retain a real human, celebrity, public figure, athlete, or external brand.

SOURCE TEMPLATE — PRESERVE ITS STRUCTURE AND INSTANTIATE ITS PLACEHOLDERS:
"""


def target_source_adaptation(target: Path) -> tuple[str, str, Path | None, Path | None]:
    path = target / "SOURCE-ADAPTATION.md"
    if not path.is_file():
        return "", "", None, None
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit(f"Target source adaptation is empty: {path}")
    compact_path = target / "SOURCE-ADAPTATION-COMPACT.txt"
    compact = compact_path.read_text(encoding="utf-8").strip() if compact_path.is_file() else text
    if not compact:
        raise SystemExit(f"Compact target source adaptation is empty: {compact_path}")
    return text, compact, path, (compact_path if compact_path.is_file() else path)


def target_case_overrides(target: Path) -> tuple[dict[str, str], Path | None]:
    path = target / "SOURCE-CASE-OVERRIDES.json"
    if not path.is_file():
        return {}, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Target case overrides must be a JSON object: {path}")
    overrides: dict[str, str] = {}
    for raw_id, raw_text in payload.items():
        case_id = str(int(raw_id))
        text = str(raw_text).strip()
        if not text:
            raise SystemExit(f"Target case override {case_id} is empty: {path}")
        overrides[case_id] = text
    return overrides, path


def adaptation_prefix(text: str) -> str:
    return ("\nTARGET-SPECIFIC ADAPTATION — CONTROLLING:\n" + text + "\n") if text else ""


def adaptation_suffix(text: str, base_chars: int = 0) -> str:
    if not text:
        return ""
    full = (
        "\n\nFINAL TARGET OVERRIDE: The TARGET-SPECIFIC ADAPTATION above controls "
        "over every conflicting source literal. Before rendering, remove every "
        "external name, face, brand, team, place, product, event, headline, and "
        "central copy. Use only the target brand, closed roster, arenas, and "
        "verified facts listed in that adaptation. Fill every person slot with "
        "a closed-roster character. Preserve only the source visual mechanism.\n"
    )
    short = (
        "\n\nFINAL OVERRIDE: Apply the TARGET-SPECIFIC ADAPTATION above over all "
        "conflicting source literals; preserve only the source visual mechanism.\n"
    )
    return full if base_chars + len(full) <= 7900 else short


def compact_external_whitespace(value: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    pending_space = False
    for char in value:
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            if pending_space and out and not out[-1].isspace():
                out.append(" ")
            pending_space = False
            out.append(char)
            in_string = True
        elif char.isspace():
            pending_space = True
        else:
            if pending_space and out and not out[-1].isspace():
                out.append(" ")
            pending_space = False
            out.append(char)
    return "".join(out).strip()


def compact_case_prompt(
    target_name: str,
    compact_adaptation: str,
    case_id: int,
    source_prompt: str,
    placeholder_rule: str,
    human_subject_detected: bool,
    target_theme_placeholder: bool,
    case_override: str = "",
    copy_language: str = "",
) -> tuple[str, str, str]:
    compact_source = compact_external_whitespace(source_prompt)
    prefix = (
        source_faithful_case_directive(
            target_name, human_subject_detected, target_theme_placeholder
        )
        + adaptation_prefix(compact_adaptation)
        + placeholder_rule
        + f"SOURCE CASE ID: {case_id}\n"
    )
    suffix = source_faithful_case_suffix(
        target_name, human_subject_detected, target_theme_placeholder, copy_language
    )
    suffix += adaptation_suffix(
        compact_adaptation, len(prefix) + len(compact_source) + len(suffix)
    )
    if case_override:
        suffix += "CASE-SPECIFIC FINAL OVERRIDE — CONTROLLING:\n" + case_override + "\n"
    suffix += copy_language_directive(
        target_name,
        copy_language,
        PROMPT_LIMIT - (len(prefix) + len(compact_source) + len(suffix)),
    )
    prompt = prefix + compact_source + suffix
    if len(prompt) > PROMPT_LIMIT:
        raise SystemExit(
            f"Case {case_id} exceeds Grok's {PROMPT_LIMIT}-character prompt limit after lossless whitespace compaction: {len(prompt)}"
        )
    return prompt, prefix, suffix


def source_aspect_ratio(prompt: str) -> str:
    for match in re.finditer(r"(?<!\d)(\d{1,2})\s*[:：x×]\s*(\d{1,2})(?!\d)", prompt, re.I):
        left, right = int(match.group(1)), int(match.group(2))
        if 1 <= left <= 32 and 1 <= right <= 32:
            divisor = math.gcd(left, right)
            return f"{left // divisor}:{right // divisor}"
    return "1:1"


HUMAN_SUBJECT_TERMS = re.compile(
    r"\b(person|people|human|man|woman|boy|girl|portrait|selfie|character|actor|"
    r"player|athlete|model|founder|host|streamer|face|momotaro)\b|"
    r"人物|人像|角色|肖像|自拍|男人|女人|男孩|女孩|男子|女子|模特|球员|运动员|演员|"
    r"主播|脸|面部|剪影|太郎|特朗普|马斯克",
    re.I,
)


def source_has_human_subject(source: dict[str, Any]) -> bool:
    semantics = source.get("semantics") or {}
    if "person" in (semantics.get("target_kinds") or []):
        return True
    return bool(HUMAN_SUBJECT_TERMS.search(str(source.get("prompt") or "")))


TARGET_THEME_PLACEHOLDER = re.compile(r"【\s*主题\s*】|\[\s*主题\s*\]|\{\s*主题\s*\}")


def source_uses_target_reference(source: dict[str, Any]) -> bool:
    prompt = str(source.get("prompt") or "")
    return source_has_human_subject(source) or bool(TARGET_THEME_PLACEHOLDER.search(prompt))


def source_faithful_case_directive(
    target_name: str, human_subject: bool, target_theme_placeholder: bool
) -> str:
    if human_subject:
        return SOURCE_FAITHFUL_PERSON_DIRECTIVE.format(target=target_name)
    if target_theme_placeholder:
        return (
            f"SOURCE-FAITHFUL EXPLICIT THEME SUBSTITUTION FOR {target_name}\n"
            f"Use the attached reference image only when the instantiated {target_name} theme requires a visible person. "
            f"Instantiate only the SOURCE PROMPT's explicit theme placeholder as {target_name}; preserve every other source requirement verbatim. "
            f"Do not replace or rename any other person, brand, product, interface, place, object, event, visible copy, statistic, composition, style, camera, lighting, material, aspect ratio, or constraint. "
            f"Do not invent facts about {target_name}.\n\n"
            "SOURCE PROMPT — PRESERVE VERBATIM EXCEPT FOR ITS EXPLICIT THEME PLACEHOLDER:\n"
        )
    return SOURCE_FAITHFUL_UNCHANGED_DIRECTIVE.format(target=target_name)


COPY_LANGUAGE_DIRECTIVE = """
VISIBLE COPY LANGUAGE — {language}: every piece of text rendered inside the image must be written in {language}. This covers headlines, subheads, body copy, labels, captions, badges, ribbons, buttons, UI strings, chart and axis labels, signage, packaging copy, handwriting, stamps, and watermarks. Translate the source's wording into {language} while keeping its meaning, tone, and marketing intent. Keep the source's typography, hierarchy, size relationships, composition, and design unchanged; only the language of the words changes. Proper names, brand names, product names, and {target} stay as written. Do not render Chinese, Japanese, Korean, or any other non-{language} script anywhere in the designed copy — headlines, labels, captions, badges, and UI included. The single exception is incidental background signage physically present in a real-world photographic location; any such sign must stay small, out of focus, and must never carry the piece's message. When a translated string runs longer than the original, adjust tracking or line breaks instead of the layout.
"""


COPY_LANGUAGE_DIRECTIVE_SHORT = """
VISIBLE COPY LANGUAGE — {language}: render every visible text element in the image in {language}, translating the source wording while keeping its typography, hierarchy, composition, and layout unchanged. Proper names, brand names, and {target} stay as written. Do not render Chinese, Japanese, or Korean script.
"""

COPY_LANGUAGE_DIRECTIVE_MINIMAL = """
VISIBLE COPY LANGUAGE: all visible text in {language}, same typography and layout. No CJK script.
"""


COPY_LANGUAGE_VARIANTS = (
    COPY_LANGUAGE_DIRECTIVE,
    COPY_LANGUAGE_DIRECTIVE_SHORT,
    COPY_LANGUAGE_DIRECTIVE_MINIMAL,
)


def copy_language_directive(target_name: str, copy_language: str, budget: int | None = None) -> str:
    if not copy_language:
        return ""
    variants = COPY_LANGUAGE_VARIANTS
    for template in variants:
        text = template.format(language=copy_language, target=target_name)
        if budget is None or len(text) <= budget:
            return text
    return ""


def unsupported_field_labels(copy_language: str) -> tuple[str, str]:
    language = copy_language.casefold()
    if "portug" in language or "pt-br" in language or "pt_br" in language:
        return "Não informado", "Não avaliado"
    return "Not provided", "Not assessed"


def has_copy_language_directive(text: str, target_name: str, copy_language: str) -> bool:
    if not copy_language:
        return False
    return any(
        template.format(language=copy_language, target=target_name) in text
        for template in COPY_LANGUAGE_VARIANTS
    )


def source_faithful_case_suffix(
    target_name: str,
    human_subject: bool,
    target_theme_placeholder: bool,
    copy_language: str = "",
) -> str:
    if target_theme_placeholder:
        not_provided, not_assessed = unsupported_field_labels(copy_language)
        return (
            f"\n\nFINAL SOURCE-FIDELITY CHECK: instantiate only the explicit theme placeholder as {target_name}. "
            "Keep every other source literal and visual requirement unchanged. "
            f"Any requested factual field not visibly supported by the reference must display exactly '{not_provided}'; "
            f"any unsupported score or rating must display exactly '{not_assessed}'.\n"
        )
    if human_subject:
        return (
            f"\n\nFINAL SOURCE-FIDELITY CHECK: change only the requested visible central person identity to reference-grounded {target_name}. "
            f"Change a visible name, handle, or label only when it directly identifies that replaced central person, and set it to {target_name}. "
            "Do not change or rename any other source subject, supporting person, brand, product, interface, place, object, event, non-identity visible copy, statistic, composition, style, or constraint.\n"
        )
    return (
        f"\n\nFINAL SOURCE-FIDELITY CHECK: execute the source unchanged. Do not add {target_name} or any target-derived element.\n"
    )


def full_library_items(
    root: Path,
    target_name: str,
    target_adaptation: str = "",
    compact_adaptation: str = "",
    case_overrides: dict[str, str] | None = None,
    selected_case_ids: list[int] | None = None,
    copy_language: str = "",
) -> tuple[list[dict], dict[str, Any]]:
    library = load_creative_library(root)
    all_source_cases = sorted(library["cases"], key=lambda value: int(value["id"]))
    source_map = {int(source["id"]): source for source in all_source_cases}
    if selected_case_ids is None:
        source_cases = all_source_cases
    else:
        missing = [case_id for case_id in selected_case_ids if case_id not in source_map]
        if missing:
            raise SystemExit(
                "Unknown source case IDs: " + ", ".join(str(value) for value in missing)
            )
        source_cases = [source_map[case_id] for case_id in selected_case_ids]
    items: list[dict] = []
    manifest_cases: list[dict] = []
    case_overrides = case_overrides or {}
    for source in source_cases:
        case_id = int(source["id"])
        semantics = source.get("semantics") or {}
        purpose = semantics.get("primary_purpose") or "source-case"
        source_prompt = str(source.get("prompt") or "")
        if not source_prompt.strip():
            raise SystemExit(f"Source case {case_id} has no prompt")
        target_theme_placeholder = bool(TARGET_THEME_PLACEHOLDER.search(source_prompt))
        human_subject_detected = source_has_human_subject(source)
        if target_theme_placeholder:
            not_provided, not_assessed = unsupported_field_labels(copy_language)
            placeholder_rule = (
                f"TARGET PLACEHOLDER RULE: instantiate only the source's explicit theme placeholder as {target_name}, using the attached reference; preserve the rest of the source prompt. Any requested factual field that is not visibly supported by the reference must read '{not_provided}'; any score or rating without supplied evidence must read '{not_assessed}'.\n"
            )
        else:
            placeholder_rule = ""
        technical_prefix = (
            source_faithful_case_directive(
                target_name, human_subject_detected, target_theme_placeholder
            )
            + adaptation_prefix(target_adaptation)
            + placeholder_rule
            + f"SOURCE CASE ID: {case_id}\n"
        )
        technical_suffix = source_faithful_case_suffix(
            target_name, human_subject_detected, target_theme_placeholder, copy_language
        )
        technical_suffix += adaptation_suffix(
            target_adaptation,
            len(technical_prefix) + len(source_prompt) + len(technical_suffix),
        )
        case_override = case_overrides.get(str(case_id), "")
        if case_override:
            technical_suffix += (
                "CASE-SPECIFIC FINAL OVERRIDE — CONTROLLING:\n"
                + case_override
                + "\n"
            )
        technical_suffix += copy_language_directive(target_name, copy_language)
        prompt = technical_prefix + source_prompt + technical_suffix
        source_prompt_compacted = False
        if len(prompt) > PROMPT_LIMIT:
            prompt, technical_prefix, technical_suffix = compact_case_prompt(
                target_name,
                compact_adaptation or target_adaptation,
                case_id,
                source_prompt,
                placeholder_rule,
                human_subject_detected,
                target_theme_placeholder,
                case_override,
                copy_language,
            )
            source_prompt_compacted = True
        item_id = f"case-{case_id:03d}-{slugify(str(purpose))}"
        prompt_hash = sha256_bytes(prompt.encode("utf-8"))
        source_hash = sha256_bytes(source_prompt.encode("utf-8"))
        use_target_reference = source_uses_target_reference(source)
        item = {
            "id": item_id,
            "safe_id": item_id,
            "category": source.get("category") or "site-case",
            "title_en": source.get("title") or f"Case {case_id}",
            "template_id": "source-faithful-case-v1",
            "case_ids": [case_id],
            "purpose": purpose,
            "output_topology": semantics.get("output_topology") or "single-image",
            "text_policy": semantics.get("text_policy") or "source-controlled",
            "target_kinds": list(semantics.get("target_kinds") or []),
            "use_target_reference": use_target_reference,
            "aspect_ratio": source_aspect_ratio(source_prompt),
            "prompt": prompt,
            "prompt_sha256": prompt_hash,
        }
        items.append(item)
        manifest_cases.append(
            {
                "case_id": case_id,
                "item_id": item_id,
                "title": source.get("title"),
                "category": source.get("category"),
                "source_url": source.get("sourceUrl"),
                "source_label": source.get("sourceLabel"),
                "copy_language_applied": has_copy_language_directive(
                    technical_suffix, target_name, copy_language
                ),
                "source_prompt_sha256": source_hash,
                "compiled_prompt_sha256": prompt_hash,
                "source_prompt_preserved_verbatim": source_prompt in prompt,
                "source_prompt_compacted": source_prompt_compacted,
                "case_specific_override": case_override or None,
                "source_non_whitespace_preserved": (
                    re.sub(r"\s+", "", source_prompt)
                    == re.sub(r"\s+", "", compact_external_whitespace(source_prompt))
                ),
                "only_added_prefix": technical_prefix,
                "only_added_suffix": technical_suffix,
                "target_kinds": item["target_kinds"],
                "human_subject_detected": human_subject_detected,
                "target_theme_placeholder": target_theme_placeholder,
                "use_target_reference": item["use_target_reference"],
                "aspect_ratio": item["aspect_ratio"],
                "batch": (len(items) - 1) // BATCH_SIZE + 1,
            }
        )
    selected_ids = [int(value["id"]) for value in source_cases]
    batch_case_ids = [
        selected_ids[index : index + BATCH_SIZE]
        for index in range(0, len(selected_ids), BATCH_SIZE)
    ]
    manifest = {
        "schema_version": 2,
        "mode": "source-faithful-full-library",
        "library_snapshot": library["snapshot"],
        "selection": {
            "case_ids": selected_ids,
            "count": len(selected_ids),
        },
        "batches": {
            "size": BATCH_SIZE,
            "count": len(batch_case_ids),
            "case_ids": batch_case_ids,
        },
        "identity_rule": f"Preserve every source prompt; replace only a requested visible central person identity, or an explicit target placeholder, with reference-grounded {target_name}.",
        "source_prompt_policy": "The authoritative source prompt is preserved verbatim between fixed target-adaptation blocks when under 8000 characters; over-limit prompts preserve every non-whitespace character and quoted-string content through whitespace compaction plus a compact target contract.",
        "cases": manifest_cases,
    }
    return items, manifest


def full_library_cmd(args) -> None:
    root = Path(args.root).resolve()
    target = resolve_target(root, args.target)
    refs = discover_references(target)[:3]
    if not refs:
        raise SystemExit(f"No source reference image found under {target}")
    target_adaptation, compact_adaptation, adaptation_path, compact_path = target_source_adaptation(target)
    case_overrides, overrides_path = target_case_overrides(target)
    items, manifest = full_library_items(
        root,
        target.name,
        target_adaptation,
        compact_adaptation,
        case_overrides,
        None,
        getattr(args, "copy_language", ""),
    )
    out = run_dir(target, args.focus)
    out.mkdir(parents=True, exist_ok=True)
    manifest["target"] = str(target)
    manifest["focus"] = args.focus
    manifest["copy_language"] = getattr(args, "copy_language", "")
    manifest["reference_paths"] = [str(path) for path in refs]
    manifest["target_adaptation_path"] = str(adaptation_path) if adaptation_path else None
    manifest["target_adaptation_sha256"] = (
        sha256_bytes(target_adaptation.encode("utf-8")) if target_adaptation else None
    )
    manifest["compact_adaptation_path"] = str(compact_path) if compact_path else None
    manifest["compact_adaptation_sha256"] = (
        sha256_bytes(compact_adaptation.encode("utf-8")) if compact_adaptation else None
    )
    manifest["case_overrides_path"] = str(overrides_path) if overrides_path else None
    manifest["case_overrides_sha256"] = (
        sha256_bytes(overrides_path.read_bytes()) if overrides_path else None
    )
    manifest["case_override_count"] = len(case_overrides)
    (out / "FULL_LIBRARY_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    batches = manifest["batches"]
    if args.batch == "all":
        selected = items
        selected_batches = list(range(1, batches["count"] + 1))
    else:
        try:
            batch_number = int(args.batch)
        except ValueError as exc:
            raise SystemExit("--batch must be 'all' or an integer") from exc
        if not 1 <= batch_number <= batches["count"]:
            raise SystemExit(f"--batch must be between 1 and {batches['count']}")
        start = (batch_number - 1) * batches["size"]
        selected = items[start : start + batches["size"]]
        selected_batches = [batch_number]
    providers = ("grok", "codex") if args.providers == "both" else (args.providers,)
    summaries: dict[str, Any] = {}
    for provider in providers:
        summaries[provider] = run_provider(provider, out, selected, refs, args.dry_run)
    report = {
        "mode": manifest["mode"],
        "run_dir": str(out),
        "catalog_items": manifest["library_snapshot"]["case_count"],
        "selected_items": len(selected),
        "selected_batches": selected_batches,
        "providers": list(providers),
        "dry_run": args.dry_run,
        "summaries": summaries,
    }
    report_name = "FULL_LIBRARY_DRY_RUN.json" if args.dry_run else "FULL_LIBRARY_RUN.json"
    (out / report_name).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


def parse_selected_case_ids(value: str) -> list[int]:
    tokens = [token for token in re.split(r"[,\s]+", str(value).strip()) if token]
    if not tokens:
        raise SystemExit("--case-ids must contain 1-20 explicit source case IDs")
    try:
        case_ids = [int(token) for token in tokens]
    except ValueError as exc:
        raise SystemExit("--case-ids must contain only comma- or space-separated integers") from exc
    if len(case_ids) != len(set(case_ids)):
        raise SystemExit("--case-ids must not contain duplicates")
    if not 1 <= len(case_ids) <= 20:
        raise SystemExit("--case-ids must contain between 1 and 20 IDs")
    return case_ids


def selected_library_context(
    root: Path, target: Path, case_ids: list[int], copy_language: str = ""
) -> tuple[list[dict], dict, dict]:
    target_adaptation, compact_adaptation, adaptation_path, compact_path = target_source_adaptation(target)
    case_overrides, overrides_path = target_case_overrides(target)
    all_items, full_manifest = full_library_items(
        root,
        target.name,
        target_adaptation,
        compact_adaptation,
        case_overrides,
        case_ids,
        copy_language,
    )
    manifest = {
        **full_manifest,
        "copy_language": copy_language,
        "mode": "source-faithful-selected-library",
        "selection_policy": "The host explicitly selected these authoritative site cases for the requested artifact. Each source prompt remains preserved under the same source-faithful adaptation contract as full-library mode.",
    }
    metadata = {
        "target_adaptation": target_adaptation,
        "compact_adaptation": compact_adaptation,
        "adaptation_path": adaptation_path,
        "compact_path": compact_path,
        "case_overrides": case_overrides,
        "overrides_path": overrides_path,
    }
    return all_items, manifest, metadata


def selected_library_cmd(args) -> None:
    root = Path(args.root).resolve()
    target = resolve_target(root, args.target)
    refs = discover_references(target)[:3]
    if not refs:
        raise SystemExit(f"No source reference image found under {target}")
    case_ids = parse_selected_case_ids(args.case_ids)
    selected, manifest, metadata = selected_library_context(
        root, target, case_ids, args.copy_language
    )
    out = run_dir(target, args.focus)
    out.mkdir(parents=True, exist_ok=True)
    manifest["target"] = str(target)
    manifest["focus"] = args.focus
    manifest["reference_paths"] = [str(path) for path in refs]
    manifest["target_adaptation_path"] = str(metadata["adaptation_path"]) if metadata["adaptation_path"] else None
    manifest["target_adaptation_sha256"] = (
        sha256_bytes(metadata["target_adaptation"].encode("utf-8"))
        if metadata["target_adaptation"] else None
    )
    manifest["compact_adaptation_path"] = str(metadata["compact_path"]) if metadata["compact_path"] else None
    manifest["compact_adaptation_sha256"] = (
        sha256_bytes(metadata["compact_adaptation"].encode("utf-8"))
        if metadata["compact_adaptation"] else None
    )
    manifest["case_overrides_path"] = str(metadata["overrides_path"]) if metadata["overrides_path"] else None
    manifest["case_overrides_sha256"] = (
        sha256_bytes(metadata["overrides_path"].read_bytes()) if metadata["overrides_path"] else None
    )
    manifest["case_override_count"] = len(metadata["case_overrides"])
    (out / "SELECTED_LIBRARY_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    providers = ("grok", "codex") if args.providers == "both" else (args.providers,)
    summaries: dict[str, Any] = {}
    for provider in providers:
        summaries[provider] = run_provider(provider, out, selected, refs, args.dry_run)
    report = {
        "mode": manifest["mode"],
        "run_dir": str(out),
        "selected_items": manifest["selection"]["count"],
        "selected_case_ids": manifest["selection"]["case_ids"],
        "providers": list(providers),
        "dry_run": args.dry_run,
        "all_source_prompts_preserved": all(
            item["source_prompt_preserved_verbatim"] or item["source_non_whitespace_preserved"]
            for item in manifest["cases"]
        ),
        "compiled_prompt_sha256": {
            item["id"]: item["prompt_sha256"] for item in selected
        },
        "summaries": summaries,
    }
    report_name = "SELECTED_LIBRARY_DRY_RUN.json" if args.dry_run else "SELECTED_LIBRARY_RUN.json"
    (out / report_name).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


def verify_selected_library_cmd(args) -> None:
    root = Path(args.root).resolve()
    target = resolve_target(root, args.target)
    out = run_dir(target, args.focus)
    manifest_path = out / "SELECTED_LIBRARY_MANIFEST.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Selected-library manifest not found: {manifest_path}")
    stored_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if stored_manifest.get("schema_version") != 2:
        raise SystemExit(f"Selected-library manifest schema_version must be 2: {manifest_path}")
    case_ids = [
        int(value)
        for value in (stored_manifest.get("selection") or {}).get("case_ids") or []
    ]
    if not case_ids:
        raise SystemExit(f"Selected-library manifest has no selection.case_ids: {manifest_path}")
    items, current_manifest, _ = selected_library_context(
        root, target, case_ids, str(stored_manifest.get("copy_language") or "")
    )
    stored_reference_paths = stored_manifest.get("reference_paths") or []
    if not isinstance(stored_reference_paths, list) or not stored_reference_paths:
        raise SystemExit(f"Selected-library manifest has no reference_paths: {manifest_path}")
    refs = [safe_reference(target, str(value)) for value in stored_reference_paths]
    review_path = out / "VISUAL_REVIEW.json"
    review = (
        json.loads(review_path.read_text(encoding="utf-8"))
        if review_path.is_file()
        else {"schema_version": 2, "reviewed": False, "providers": {}}
    )
    providers = ("grok", "codex") if args.providers == "both" else (args.providers,)
    provider_paths = {"grok": ("FILA_GROK", ".jpg"), "codex": ("FILA_CODEX", ".png")}
    result: dict[str, Any] = {
        "mode": "source-faithful-selected-library",
        "target": str(target),
        "focus": args.focus,
        "expected": len(items),
        "selected_case_ids": case_ids,
        "manifest": str(manifest_path),
        "visual_review": str(review_path),
        "library_snapshot_matches": (
            stored_manifest.get("library_snapshot")
            == current_manifest.get("library_snapshot")
        ),
        "source_prompts_preserved": all(
            entry["source_prompt_preserved_verbatim"] or entry["source_non_whitespace_preserved"]
            for entry in current_manifest["cases"]
        ),
        "providers": {},
    }
    for provider in providers:
        folder, ext = provider_paths[provider]
        queue_dir = out / folder
        provider_result = verify_provider_integrity(
            provider, queue_dir, ext, items, refs
        )
        identity_required_ids = {
            item["id"]
            for item in items
            if item.get("use_target_reference")
            and {"person", "character"}.intersection(item.get("target_kinds") or [])
        }
        semantic = visual_review_status(
            review,
            provider,
            items,
            bindings=provider_result["bindings"],
            identity_required_ids=identity_required_ids,
        )
        result["providers"][provider] = {
            **provider_result,
            "semantic_review": semantic,
            "complete": provider_result["mechanical_complete"] and semantic["complete"],
        }
    result["mechanical_complete"] = all(
        value["mechanical_complete"] for value in result["providers"].values()
    )
    result["semantic_complete"] = all(
        value["semantic_review"]["complete"] for value in result["providers"].values()
    )
    result["complete"] = (
        result["library_snapshot_matches"]
        and result["source_prompts_preserved"]
        and result["mechanical_complete"]
        and result["semantic_complete"]
    )
    (out / "SELECTED_LIBRARY_VERIFY_REPORT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["complete"]:
        raise SystemExit(2)


def full_template_items(
    root: Path, target_name: str, target_adaptation: str = "", copy_language: str = ""
) -> tuple[list[dict], dict[str, Any]]:
    catalog, source_templates = load_catalog(root)
    library = load_creative_library(root)
    semantic_map = {item["id"]: item for item in library["templates"]}
    items: list[dict] = []
    manifest_templates: list[dict] = []
    for source in source_templates:
        template_id = str(source["id"])
        semantics = semantic_map.get(template_id)
        if not semantics:
            raise SystemExit(f"Template semantics missing for {template_id}")
        relative_file = source.get("files", {}).get("en")
        if not relative_file:
            raise SystemExit(f"English source file missing for {template_id}")
        source_path = root / "PROMPTS" / source["category"] / relative_file
        if not source_path.is_file():
            raise SystemExit(f"Template source not found: {source_path}")
        source_prompt = source_path.read_text(encoding="utf-8")
        if not source_prompt.strip():
            raise SystemExit(f"Template {template_id} has no prompt")
        technical_prefix = (
            SOURCE_FAITHFUL_TEMPLATE_DIRECTIVE.format(target=target_name)
            + adaptation_prefix(target_adaptation)
            + f"SOURCE TEMPLATE ID: {template_id}\n"
        )
        technical_suffix = adaptation_suffix(
            target_adaptation, len(technical_prefix) + len(source_prompt)
        )
        technical_suffix += copy_language_directive(
            target_name,
            copy_language,
            PROMPT_LIMIT
            - (len(technical_prefix) + len(source_prompt) + len(technical_suffix)),
        )
        prompt = technical_prefix + source_prompt + technical_suffix
        item_id = f"template-{len(items) + 1:02d}-{slugify(template_id)}"
        prompt_hash = sha256_bytes(prompt.encode("utf-8"))
        source_hash = sha256_bytes(source_prompt.encode("utf-8"))
        item = {
            "id": item_id,
            "safe_id": item_id,
            "category": source["category"],
            "title_en": source.get("title_en") or template_id,
            "template_id": template_id,
            "case_ids": [],
            "purpose": semantics.get("primary_purpose") or "template-instantiation",
            "output_topology": semantics.get("output_topology") or "single-frame",
            "text_policy": semantics.get("text_policy") or "source-controlled",
            "aspect_ratio": source_aspect_ratio(source_prompt),
            "prompt": prompt,
            "prompt_sha256": prompt_hash,
        }
        items.append(item)
        manifest_templates.append({
            "template_id": template_id,
            "item_id": item_id,
            "title_en": source.get("title_en"),
            "category": source["category"],
            "source_path": str(source_path),
            "source_prompt_sha256": source_hash,
            "compiled_prompt_sha256": prompt_hash,
            "source_prompt_preserved_verbatim": source_prompt in prompt,
            "only_added_prefix": technical_prefix,
            "only_added_suffix": technical_suffix,
            "aspect_ratio": item["aspect_ratio"],
            "batch": (len(items) - 1) // BATCH_SIZE + 1,
        })
    template_ids = [item["id"] for item in source_templates]
    declared_count = (catalog.get("stats") or {}).get("prompts_queueable")
    if (
        not isinstance(declared_count, int)
        or isinstance(declared_count, bool)
        or declared_count != len(source_templates)
    ):
        raise SystemExit(
            "Template catalog count mismatch: "
            f"catalog={declared_count!r}, actual={len(source_templates)}"
        )
    if len(template_ids) != len(set(template_ids)):
        raise SystemExit("Template catalog contains duplicate queue template IDs")
    batch_template_ids = [
        template_ids[index : index + BATCH_SIZE]
        for index in range(0, len(template_ids), BATCH_SIZE)
    ]
    manifest = {
        "schema_version": 2,
        "mode": "source-faithful-full-templates",
        "catalog_snapshot": {
            "template_count": len(items),
            "catalog_sha256": sha256_bytes(catalog_path(root).read_bytes()),
        },
        "selection": {
            "template_ids": template_ids,
            "count": len(template_ids),
        },
        "batches": {
            "size": BATCH_SIZE,
            "count": len(batch_template_ids),
            "template_ids": batch_template_ids,
        },
        "instantiation_rule": f"Instantiate every placeholder for {target_name} using only reference-grounded visual facts and neutral copy.",
        "source_prompt_policy": "The authoritative English queue-template prompt is preserved verbatim between fixed target-instantiation prefix and suffix blocks.",
        "templates": manifest_templates,
    }
    return items, manifest


def full_templates_cmd(args) -> None:
    root = Path(args.root).resolve()
    target = resolve_target(root, args.target)
    refs = discover_references(target)[:3]
    if not refs:
        raise SystemExit(f"No source reference image found under {target}")
    target_adaptation, compact_adaptation, adaptation_path, compact_path = target_source_adaptation(target)
    items, manifest = full_template_items(
        root, target.name, target_adaptation, getattr(args, "copy_language", "")
    )
    manifest["copy_language"] = getattr(args, "copy_language", "")
    out = run_dir(target, args.focus)
    out.mkdir(parents=True, exist_ok=True)
    manifest["target"] = str(target)
    manifest["focus"] = args.focus
    manifest["reference_paths"] = [str(path) for path in refs]
    manifest["target_adaptation_path"] = str(adaptation_path) if adaptation_path else None
    manifest["target_adaptation_sha256"] = (
        sha256_bytes(target_adaptation.encode("utf-8")) if target_adaptation else None
    )
    manifest["compact_adaptation_path"] = str(compact_path) if compact_path else None
    manifest["compact_adaptation_sha256"] = (
        sha256_bytes(compact_adaptation.encode("utf-8")) if compact_adaptation else None
    )
    (out / "FULL_TEMPLATES_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    batches = manifest["batches"]
    if args.batch == "all":
        selected = items
        selected_batches = list(range(1, batches["count"] + 1))
    else:
        try:
            batch_number = int(args.batch)
        except ValueError as exc:
            raise SystemExit("--batch must be 'all' or an integer") from exc
        if not 1 <= batch_number <= batches["count"]:
            raise SystemExit(f"--batch must be between 1 and {batches['count']}")
        start = (batch_number - 1) * batches["size"]
        selected = items[start : start + batches["size"]]
        selected_batches = [batch_number]
    providers = ("grok", "codex") if args.providers == "both" else (args.providers,)
    summaries: dict[str, Any] = {}
    for provider in providers:
        summaries[provider] = run_provider(provider, out, selected, refs, args.dry_run)
    report = {
        "mode": manifest["mode"],
        "run_dir": str(out),
        "catalog_items": manifest["catalog_snapshot"]["template_count"],
        "selected_items": len(selected),
        "selected_batches": selected_batches,
        "providers": list(providers),
        "dry_run": args.dry_run,
        "summaries": summaries,
    }
    report_name = "FULL_TEMPLATES_DRY_RUN.json" if args.dry_run else "FULL_TEMPLATES_RUN.json"
    (out / report_name).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


def inspect_cmd(args) -> None:
    root = Path(args.root).resolve()
    target = resolve_target(root, args.target)
    refs = discover_references(target)
    _, items = load_catalog(root)
    library = load_creative_library(root)
    semantic_map = {item["id"]: item for item in library["templates"]}
    intent = intent_path(target, args.focus)
    brief = brief_path(target, args.focus)
    result = {
        "root": str(root), "target": str(target), "focus": args.focus,
        "catalog": str(catalog_path(root)), "queueable": len(items),
        "purpose_library": library["path"],
        "library_counts": library["manifest"]["counts"],
        "available_purposes": [
            {
                "id": purpose["id"],
                "label_pt": purpose["label_pt"],
                "default_topologies": purpose["default_topologies"],
                "target_kinds": purpose["target_kinds"],
            }
            for purpose in library["taxonomy"]["purposes"]
        ],
        "creative_plan_schema": render_plan_schema(),
        "catalog_items": [
            {
                "id": item["id"],
                "category": item["category"],
                "title_en": item.get("title_en", ""),
                "kind": item.get("kind", "text"),
                "primary_purpose": semantic_map[item["id"]]["primary_purpose"],
                "compatible_purposes": semantic_map[item["id"]]["compatible_purposes"],
                "output_topology": semantic_map[item["id"]]["output_topology"],
                "text_policy": semantic_map[item["id"]]["text_policy"],
                "target_kinds": semantic_map[item["id"]]["target_kinds"],
                "adaptation_mode": semantic_map[item["id"]]["adaptation_mode"],
            }
            for item in items
        ],
        "candidate_references": [
            {"path": str(p.relative_to(target)).replace("\\", "/"), "bytes": p.stat().st_size}
            for p in refs[:20]
        ],
        "intent_contract": str(intent),
        "intent_exists": intent.is_file(),
        "brief": str(brief),
        "brief_exists": brief.is_file(),
        "run_dir": str(run_dir(target, args.focus)),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def init_cmd(args) -> None:
    root = Path(args.root).resolve()
    target = resolve_target(root, args.target)
    refs = discover_references(target)
    if not refs:
        raise SystemExit(f"No source reference images found under {target}")
    intent = load_intent(target, args.focus)
    path = brief_path(target, args.focus)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not args.force:
        print(json.dumps({"status": "exists", "brief": str(path)}, ensure_ascii=False, indent=2))
        return
    brief = default_brief(target, args.focus, refs, intent)
    path.write_text(json.dumps(brief, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "created", "brief": str(path), "references": brief["references"]}, ensure_ascii=False, indent=2))


def run_cmd(args) -> None:
    root = Path(args.root).resolve()
    target = resolve_target(root, args.target)
    intent = load_intent(target, args.focus)
    brief = load_brief(target, args.focus)
    violations = intent_violations(brief, intent)
    if violations:
        raise SystemExit("Intent contract violation: " + "; ".join(violations))
    refs = [safe_reference(target, v) for v in brief.get("references", [])[:3]]
    if not refs:
        raise SystemExit("Brief has no valid references")
    out = run_dir(target, args.focus)
    out.mkdir(parents=True, exist_ok=True)
    items, plan_diagnostics = queue_items(root, brief, intent)
    dry = {
        "target": str(target), "focus": args.focus, "queue": len(items),
        "references": [str(p) for p in refs],
        "creative_plan": plan_diagnostics,
    }
    if args.dry_run:
        for provider in ("grok", "codex") if args.providers == "both" else (args.providers,):
            run_provider(provider, out, items, refs, True)
        (out / "DRY_RUN_REPORT.json").write_text(json.dumps(dry, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(dry, ensure_ascii=False, indent=2))
        return
    summaries = {}
    providers = ("grok", "codex") if args.providers == "both" else (args.providers,)
    for provider in providers:
        summaries[provider] = run_provider(provider, out, items, refs, False)
    print(json.dumps({"run_dir": str(out), "summaries": summaries}, ensure_ascii=False, indent=2))


def image_metadata(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            width, height = image.size
            image_format = image.format
        if (
            width <= 0
            or height <= 0
            or image_format not in {"PNG", "JPEG", "WEBP", "GIF"}
        ):
            return None
        return {
            "format": image_format,
            "width": width,
            "height": height,
            "bytes": path.stat().st_size,
        }
    except (
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
    ):
        return None


def valid_image(path: Path) -> bool:
    return image_metadata(path) is not None


def verify_provider_integrity(
    provider: str,
    queue_dir: Path,
    extension: str,
    items: list[dict],
    references: list[Path],
) -> dict[str, Any]:
    report_path = queue_dir / "REPORT.json"
    report = load_report(report_path)
    provider_mismatch = report_path.is_file() and report.get("provider") != provider
    entries = report["results"]
    missing_files: list[str] = []
    invalid_files: list[str] = []
    missing_report_entries: list[str] = []
    failed_ids: list[str] = []
    prompt_mismatch: list[str] = []
    reference_mismatch: list[str] = []
    output_mismatch: list[str] = []
    bindings: dict[str, dict[str, Any]] = {}
    valid_items = 0

    for item in items:
        item_id = item["id"]
        prompt_path = queue_dir / "_prompts" / f"{item['safe_id']}.txt"
        output_path = queue_dir / f"{item['safe_id']}{extension}"
        entry = entries.get(item_id)
        item_references = references if item.get("use_target_reference", True) else []
        current_prompt_hash = sha256_bytes(item["prompt"].encode("utf-8"))
        current_reference_hashes = [sha256_bytes(path.read_bytes()) for path in item_references]

        prompt_ok = (
            item.get("prompt_sha256") == current_prompt_hash
            and prompt_path.is_file()
            and sha256_bytes(prompt_path.read_bytes()) == current_prompt_hash
            and isinstance(entry, dict)
            and entry.get("prompt_sha256") == current_prompt_hash
        )
        if not prompt_ok:
            prompt_mismatch.append(item_id)

        if not output_path.is_file():
            missing_files.append(str(output_path))
            current_output_hash = None
        elif image_metadata(output_path) is None:
            invalid_files.append(str(output_path))
            current_output_hash = None
        else:
            current_output_hash = sha256_bytes(output_path.read_bytes())

        if not isinstance(entry, dict):
            missing_report_entries.append(item_id)
        else:
            if entry.get("ok") is not True:
                failed_ids.append(item_id)
            if entry.get("reference_sha256") != current_reference_hashes:
                reference_mismatch.append(item_id)
            if current_output_hash is None or entry.get("output_sha256") != current_output_hash:
                output_mismatch.append(item_id)

        if current_output_hash is not None:
            bindings[item_id] = {
                "prompt_sha256": current_prompt_hash,
                "reference_sha256": current_reference_hashes,
                "output_sha256": current_output_hash,
            }

        if (
            isinstance(entry, dict)
            and entry.get("ok") is True
            and prompt_ok
            and entry.get("reference_sha256") == current_reference_hashes
            and current_output_hash is not None
            and entry.get("output_sha256") == current_output_hash
        ):
            valid_items += 1

    mechanical_complete = (
        valid_items == len(items)
        and not missing_files
        and not invalid_files
        and not missing_report_entries
        and not failed_ids
        and not prompt_mismatch
        and not reference_mismatch
        and not output_mismatch
        and not provider_mismatch
    )
    return {
        "folder": str(queue_dir),
        "files": sum(
            1 for item in items if (queue_dir / f"{item['safe_id']}{extension}").is_file()
        ),
        "verified_items": valid_items,
        "failed_ids": failed_ids,
        "provider_mismatch": provider_mismatch,
        "missing_report_entries": missing_report_entries,
        "prompt_mismatch": prompt_mismatch,
        "reference_mismatch": reference_mismatch,
        "output_mismatch": output_mismatch,
        "missing_files": missing_files,
        "invalid_files": invalid_files,
        "bindings": bindings,
        "mechanical_complete": mechanical_complete,
    }


def visual_review_status(
    review: dict,
    provider: str,
    items: list[dict],
    *,
    bindings: dict[str, dict[str, Any]],
    identity_required_ids: set[str] | None = None,
) -> dict:
    provider_reviews = (review.get("providers") or {}).get(provider) or {}
    identity_required_ids = identity_required_ids or set()
    expected_ids = [item["id"] for item in items]
    item_map = {item["id"]: item for item in items}
    missing = [item_id for item_id in expected_ids if item_id not in provider_reviews]
    invalid: list[str] = []
    if review.get("schema_version") != 2:
        invalid.append("review: schema_version must be 2")
    rejected: list[str] = []
    for item_id in expected_ids:
        entry = provider_reviews.get(item_id)
        if not isinstance(entry, dict):
            continue
        required = {
            "prompt_sha256", "reference_sha256", "output_sha256", "accepted",
            "identity_fidelity", "topology", "text", "intent_alignment", "notes",
        }
        absent = sorted(required - set(entry))
        if absent:
            invalid.append(f"{item_id}: missing {', '.join(absent)}")
            continue
        if not isinstance(entry["accepted"], bool):
            invalid.append(f"{item_id}: accepted must be true or false")
        if entry["identity_fidelity"] not in {"pass", "fail", "not-applicable"}:
            invalid.append(f"{item_id}: invalid identity_fidelity")
        if entry["topology"] not in {"pass", "fail"}:
            invalid.append(f"{item_id}: invalid topology")
        if entry["text"] not in {"pass", "fail", "not-applicable"}:
            invalid.append(f"{item_id}: invalid text")
        if entry["intent_alignment"] not in {"pass", "fail"}:
            invalid.append(f"{item_id}: invalid intent_alignment")
        if not isinstance(entry["notes"], str):
            invalid.append(f"{item_id}: notes must be a string")
        binding = bindings.get(item_id)
        if binding is None:
            invalid.append(f"{item_id}: no current artifact binding")
        else:
            for field in ("prompt_sha256", "reference_sha256", "output_sha256"):
                if entry.get(field) != binding[field]:
                    invalid.append(f"{item_id}: stale {field}")
        status_values = [
            entry.get("identity_fidelity"), entry.get("topology"),
            entry.get("text"), entry.get("intent_alignment"),
        ]
        if entry.get("accepted") is True and "fail" in status_values:
            invalid.append(f"{item_id}: accepted=true conflicts with a failed criterion")
        if (
            entry.get("accepted") is True
            and item_id in identity_required_ids
            and entry.get("identity_fidelity") != "pass"
        ):
            invalid.append(f"{item_id}: accepted identity-critical output requires identity_fidelity=pass")
        if (
            entry.get("accepted") is True
            and item_map[item_id].get("text_policy") in {"forbidden", "required"}
            and entry.get("text") != "pass"
        ):
            invalid.append(
                f"{item_id}: accepted {item_map[item_id].get('text_policy')} text policy requires text=pass"
            )
        if entry.get("accepted") is not True:
            rejected.append(item_id)
    reviewed = (
        review.get("schema_version") == 2
        and review.get("reviewed") is True
        and not missing
        and not invalid
    )
    return {
        "reviewed": reviewed,
        "missing_items": missing,
        "invalid_items": invalid,
        "rejected_items": rejected,
        "complete": reviewed and not rejected,
    }


def verify_cmd(args) -> None:
    root = Path(args.root).resolve()
    target = resolve_target(root, args.target)
    intent = load_intent(target, args.focus)
    brief = load_brief(target, args.focus)
    violations = intent_violations(brief, intent)
    if violations:
        raise SystemExit("Intent contract violation: " + "; ".join(violations))
    items, plan_diagnostics = queue_items(root, brief, intent)
    refs = [safe_reference(target, value) for value in brief.get("references", [])[:3]]
    if not refs:
        raise SystemExit("Brief has no valid references")
    out = run_dir(target, args.focus)
    review_path = out / "VISUAL_REVIEW.json"
    visual_review = (
        json.loads(review_path.read_text(encoding="utf-8"))
        if review_path.is_file()
        else {"schema_version": 2, "reviewed": False, "providers": {}}
    )
    requested_providers = brief.get("providers") or ["grok", "codex"]
    if (
        not isinstance(requested_providers, list)
        or not requested_providers
        or any(provider not in {"grok", "codex"} for provider in requested_providers)
    ):
        raise SystemExit("brief.providers must contain grok, codex, or both")
    provider_paths = {
        "grok": ("FILA_GROK", ".jpg"),
        "codex": ("FILA_CODEX", ".png"),
    }
    result: dict[str, Any] = {
        "target": str(target),
        "focus": args.focus,
        "expected": len(items),
        "creative_plan": plan_diagnostics,
        "visual_review": str(review_path),
        "providers": {},
    }
    for provider in requested_providers:
        folder, ext = provider_paths[provider]
        queue_dir = out / folder
        provider_result = verify_provider_integrity(
            provider, queue_dir, ext, items, refs
        )
        identity_required_ids = (
            {item["id"] for item in items}
            if intent["target_kind"] in {"person", "character"}
            else set()
        )
        semantic = visual_review_status(
            visual_review,
            provider,
            items,
            bindings=provider_result["bindings"],
            identity_required_ids=identity_required_ids,
        )
        result["providers"][provider] = {
            **provider_result,
            "semantic_review": semantic,
            "complete": provider_result["mechanical_complete"] and semantic["complete"],
        }
    result["mechanical_complete"] = all(
        value["mechanical_complete"] for value in result["providers"].values()
    )
    result["semantic_complete"] = all(
        value["semantic_review"]["complete"] for value in result["providers"].values()
    )
    result["complete"] = result["mechanical_complete"] and result["semantic_complete"]
    (out / "VERIFY_REPORT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["complete"]:
        raise SystemExit(2)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="image_production_factory")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("inspect", "init", "run", "verify"):
        q = sub.add_parser(name)
        q.add_argument("--target", required=True)
        q.add_argument("--focus", required=True)
        q.add_argument("--root", default=str(DEFAULT_ROOT))
        if name == "init":
            q.add_argument("--force", action="store_true")
        if name == "run":
            q.add_argument("--providers", choices=("both", "grok", "codex"), default="both")
            q.add_argument("--dry-run", action="store_true")
    for name, default_focus in (
        ("full-library", "biblioteca-fonte-fiel-v6"),
        ("full-templates", "templates-fonte-fieis-v2"),
    ):
        full = sub.add_parser(name)
        full.add_argument("--target", required=True)
        full.add_argument("--focus", default=default_focus)
        full.add_argument("--root", default=str(DEFAULT_ROOT))
        full.add_argument("--batch", default="all")
        full.add_argument("--providers", choices=("both", "grok", "codex"), default="both")
        full.add_argument("--copy-language", default="Brazilian Portuguese (pt-BR)")
        full.add_argument("--dry-run", action="store_true")
    selected = sub.add_parser("selected-library")
    selected.add_argument("--target", required=True)
    selected.add_argument("--focus", default="biblioteca-fonte-fiel-selecionada-v1")
    selected.add_argument("--root", default=str(DEFAULT_ROOT))
    selected.add_argument("--case-ids", required=True)
    selected.add_argument("--providers", choices=("both", "grok", "codex"), default="both")
    selected.add_argument("--copy-language", default="Brazilian Portuguese (pt-BR)")
    selected.add_argument("--dry-run", action="store_true")
    selected_verify = sub.add_parser("verify-selected-library")
    selected_verify.add_argument("--target", required=True)
    selected_verify.add_argument("--focus", required=True)
    selected_verify.add_argument("--root", default=str(DEFAULT_ROOT))
    selected_verify.add_argument("--providers", choices=("both", "grok", "codex"), default="both")
    return p


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    {
        "inspect": inspect_cmd,
        "init": init_cmd,
        "run": run_cmd,
        "full-library": full_library_cmd,
        "selected-library": selected_library_cmd,
        "full-templates": full_templates_cmd,
        "verify": verify_cmd,
        "verify-selected-library": verify_selected_library_cmd,
    }[args.command](args)


if __name__ == "__main__":
    main(sys.argv[1:])
