"""Build and query the purpose-first GPT-Image2 case library.

The upstream site stores cases by visual category.  This module adds a second,
user-intent-oriented index without changing the upstream checkout.  Raw case
prompts are retained as attributed inspiration; they are never marked as safe
runtime templates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
PROMPTS_ROOT = SCRIPT.parents[1] if SCRIPT.parent.name == "tools" else None
WORKSPACE_ROOT = PROMPTS_ROOT.parent if PROMPTS_ROOT else None

DEFAULT_UPSTREAM = (
    WORKSPACE_ROOT / "vendor" / "awesome-gpt-image-2"
    if WORKSPACE_ROOT
    else Path()
)
DEFAULT_CASES = DEFAULT_UPSTREAM / "data" / "cases.json"
DEFAULT_STYLE_LIBRARY = DEFAULT_UPSTREAM / "data" / "style-library.json"
DEFAULT_TEMPLATE_CATALOG = PROMPTS_ROOT / "catalog.json" if PROMPTS_ROOT else Path()
DEFAULT_TAXONOMY = SCRIPT.with_name("purpose-taxonomy.json")
DEFAULT_OUTPUT = PROMPTS_ROOT / "site-library" if PROMPTS_ROOT else SCRIPT.parent.parent / "data"

CATEGORY_DEFAULTS = {
    "UI & Interfaces": "interface-design",
    "Charts & Infographics": "information-explainer",
    "Posters & Typography": "campaign-key-visual",
    "Products & E-commerce": "product-commerce",
    "Brand & Logos": "brand-system",
    "Architecture & Spaces": "space-visualization",
    "Photography & Realism": "lifestyle-photography",
    "Illustration & Art": "artistic-exploration",
    "Characters & People": "character-development",
    "Scenes & Storytelling": "narrative-scene",
    "History & Classical Themes": "historical-cultural",
    "Documents & Publishing": "publishing-layout",
    "Other Use Cases": "concept-development",
}

MEDIUM_BY_CATEGORY = {
    "UI & Interfaces": "ui-design",
    "Charts & Infographics": "diagram-design",
    "Posters & Typography": "graphic-design",
    "Products & E-commerce": "commercial-design",
    "Brand & Logos": "brand-design",
    "Architecture & Spaces": "spatial-visualization",
    "Photography & Realism": "photography",
    "Illustration & Art": "illustration",
    "Characters & People": "character-design",
    "Scenes & Storytelling": "narrative-imaging",
    "History & Classical Themes": "historical-imaging",
    "Documents & Publishing": "publishing-design",
    "Other Use Cases": "mixed-design",
}

MULTI_PANEL_TERMS = [
    "contact sheet", "character sheet", "pose sheet", "reference sheet", "model sheet",
    "moodboard", "mood board", "story board", "design board", "brand board", "visual board",
    "collage", "grid", "multi-panel", "multipanel", "multiple panels", "multiple views",
    "four panels", "five panels", "six panels", "2x2", "2 x 2", "3x3", "3 x 3",
    "split screen", "split-screen", "diptych", "triptych", "quadriptych", "comparison board",
    "breakdown board", "exploded board", "turnaround", "主视图 +", "设定表", "参考表",
    "动作分解", "九宫格", "拼贴", "网格", "多视图", "多面板", "视觉板", "拆解板",
    "設定資料", "コラージュ", "グリッド", "複数ビュー",
]

SEQUENCE_TERMS = [
    "storyboard", "comic strip", "comic sequence", "sequential frames", "frame-by-frame",
    "before and after", "before/after", "step-by-step", "timeline sequence", "分镜", "连环画",
    "漫画条", "连续画面", "前后对比", "步骤图", "ストーリーボード",
]

TEXT_REQUIRED_TERMS = [
    "headline", "subtitle", "typography", "title text", "exact text", "copywriting",
    "caption", "labels", "labelled", "labeled", "logo reads", "text reads", "visible wording",
    "font", "typeface", "banner reading", "interface text", "标题", "副标题", "排版",
    "文字", "标签", "文案", "字体", "標題", "テキスト", "キャプション",
]

TEXT_FORBIDDEN_TERMS = [
    "no text", "without text", "no typography", "no letters", "no readable text",
    "no logo", "文字なし", "テキストなし", "无文字", "不要文字", "无可读文字",
    "不含文字", "禁止文字", "文字を入れない",
]

REFERENCE_REQUIRED_TERMS = [
    "uploaded image", "input image", "reference image", "attached image", "provided photo",
    "preserve the original", "keep the exact", "100% preserve", "based on the reference",
    "use the reference", "上传的", "参考图", "原图", "保持原有", "完整保留", "基于输入",
    "添付画像", "参照画像", "元画像",
]

PERSON_TERMS = [
    "portrait", "person", "people", "woman", "man", "girl", "boy", "face", "model",
    "athlete", "character", "人物", "人像", "肖像", "女性", "男性", "女孩", "男孩",
    "角色", "顔", "女性", "男性", "ポートレート",
]

PRODUCT_TERMS = [
    "product", "packaging", "bottle", "box", "device", "furniture", "cosmetic", "perfume",
    "shoe", "watch", "food", "drink", "商品", "产品", "包装", "瓶", "家具", "化妆品",
    "香水", "食品", "饮料", "製品", "商品",
]

PROFILE_TERMS = [
    "headshot", "profile portrait", "professional portrait", "corporate portrait", "linkedin",
    "speaker card", "id photo", "passport photo", "证件照", "职业肖像", "商务头像",
]

PORTRAIT_TERMS = [
    "portrait", "fashion shoot", "beauty shoot", "editorial photo", "editorial portrait",
    "creative portrait", "studio portrait", "人像", "写真", "肖像", "棚拍", "ポートレート",
]

PRODUCT_HERO_TERMS = [
    "product hero", "hero shot", "packshot", "product photography", "studio product",
    "still life", "isolated product", "商品主图", "产品摄影", "静物摄影", "产品主视觉",
]

SOCIAL_TERMS = [
    "thumbnail", "youtube", "instagram", "tiktok", "xiaohongshu", "livestream cover",
    "stream thumbnail", "social post", "社媒", "缩略图", "直播封面", "小红书", "视频封面",
]

ROLE_LITERAL_TERMS = [
    "barista", "doctor", "lawyer", "photographer", "chef", "nurse", "police officer",
    "teacher", "business owner", "designer", "engineer", "waiter", "waitress", "咖啡师",
    "医生", "律师", "摄影师", "厨师", "护士", "警察", "教师", "设计师", "工程师",
]

CATEGORY_RECIPES = {
    "UI & Interfaces": "platform-faithful interface hierarchy, readable controls, realistic screen chrome",
    "Charts & Infographics": "structured information hierarchy, concise modules, clear flow and disciplined spacing",
    "Posters & Typography": "strong focal hierarchy, deliberate negative space, controlled campaign composition",
    "Products & E-commerce": "product-first composition, material fidelity, commercial lighting and clear selling hierarchy",
    "Brand & Logos": "coherent identity system, consistent palette, typography logic and disciplined applications",
    "Architecture & Spaces": "credible perspective, spatial function, material realism and intentional environmental light",
    "Photography & Realism": "believable photographic optics, natural texture, motivated light and grounded imperfections",
    "Illustration & Art": "intentional composition, coherent material or brush language, controlled palette and rendering depth",
    "Characters & People": "stable identity anchors, deliberate pose and consistent clothing or character details",
    "Scenes & Storytelling": "visible narrative cue, emotional staging, grounded environment and intentional camera framing",
    "History & Classical Themes": "period-aware materials, clothing and cultural composition with coherent atmosphere",
    "Documents & Publishing": "publication grid, readable hierarchy, aligned figures and restrained page rhythm",
    "Other Use Cases": "clear artifact definition, controlled technical presentation and visible component relationships",
}

COMPATIBLE_PURPOSES_BY_CATEGORY = {
    "UI & Interfaces": ["interface-design", "social-cover"],
    "Charts & Infographics": ["information-explainer", "concept-development"],
    "Posters & Typography": ["campaign-key-visual", "social-cover"],
    "Products & E-commerce": ["product-hero", "product-commerce", "campaign-key-visual"],
    "Brand & Logos": ["brand-system", "campaign-key-visual"],
    "Architecture & Spaces": ["space-visualization"],
    "Photography & Realism": [
        "profile-portrait", "editorial-portrait", "lifestyle-photography", "product-hero"
    ],
    "Illustration & Art": ["artistic-exploration", "campaign-key-visual", "narrative-scene"],
    "Characters & People": ["character-development"],
    "Scenes & Storytelling": ["narrative-scene", "lifestyle-photography"],
    "History & Classical Themes": ["historical-cultural", "narrative-scene"],
    "Documents & Publishing": ["publishing-layout"],
    "Other Use Cases": ["concept-development"],
}

SPECIFIC_TEMPLATE_COMPATIBILITY = {
    "07-photography-realism/03-street-accident-moment": [
        "editorial-portrait", "lifestyle-photography"
    ],
    "09-characters-people/03-ref-to-3d-collectible-toy": ["character-development"],
}

SPECIFIC_TEMPLATE_RECIPES = {
    "07-photography-realism/01-standard": "standalone realistic photograph; explicit lens, camera distance, motivated light, natural texture and one decisive moment",
    "07-photography-realism/02-json-advanced": "standalone cinematic photograph; shallow depth of field, motivated rim light, wet-window reflections and subtle film grain; omit every example person, occupation, prop and venue",
    "07-photography-realism/03-street-accident-moment": "standalone candid phone photograph; plausible action, grounded street context, natural motion blur and unstaged light",
    "09-characters-people/01-standard": "unified character design sheet with a main view and supporting pose or detail views",
    "09-characters-people/02-action-breakdown-sheet": "multi-panel action reference sheet with consistent identity and readable motion progression",
    "09-characters-people/03-ref-to-3d-collectible-toy": "single premium collectible figure presentation preserving identity anchors and material detail",
    "09-characters-people/04-json-advanced": "single stylized character concept with coherent attire, pose, environment and rendering language; omit every example identity and weapon",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _contains(text: str, phrase: str) -> bool:
    haystack = _fold(text)
    needle = _fold(phrase).strip()
    if not needle:
        return False
    if re.fullmatch(r"[a-z0-9&+-]{1,3}", needle):
        return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None
    return needle in haystack


def _has_any(text: str, terms: list[str]) -> bool:
    return any(_contains(text, term) for term in terms)


def _language(text: str) -> str:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    kana = len(re.findall(r"[\u3040-\u30ff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if kana > 20:
        return "ja" if latin < kana else "mixed"
    if cjk > 20:
        return "zh" if latin < cjk else "mixed"
    return "en" if latin else "unknown"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _taxonomy_maps(taxonomy: dict) -> tuple[dict[str, dict], dict[str, list[str]]]:
    purposes = {item["id"]: item for item in taxonomy["purposes"]}
    aliases = {item["id"]: list(item.get("aliases") or []) for item in taxonomy["purposes"]}
    return purposes, aliases


def _infer_topology(text: str, category: str) -> str:
    if _has_any(text, SEQUENCE_TERMS):
        return "sequence"
    if _has_any(text, MULTI_PANEL_TERMS):
        return "multi-panel"
    if category == "UI & Interfaces":
        return "ui-screen"
    if category in {"Documents & Publishing", "Charts & Infographics"}:
        return "document-page"
    if category == "Posters & Typography":
        return "poster-canvas"
    return "single-frame"


def _infer_text_policy(text: str, category: str) -> str:
    if _has_any(text, TEXT_FORBIDDEN_TERMS):
        scrubbed = _fold(text)
        for term in TEXT_FORBIDDEN_TERMS:
            scrubbed = scrubbed.replace(_fold(term), " ")
        if not _has_any(scrubbed, TEXT_REQUIRED_TERMS):
            return "forbidden"
    if _has_any(text, TEXT_REQUIRED_TERMS):
        return "required"
    if category in {
        "UI & Interfaces", "Charts & Infographics", "Posters & Typography",
        "Brand & Logos", "Documents & Publishing",
    }:
        return "required"
    if category == "Photography & Realism":
        return "forbidden"
    return "optional"


def _infer_reference_mode(text: str) -> str:
    return "required" if _has_any(text, REFERENCE_REQUIRED_TERMS) else "optional"


def _infer_target_kinds(text: str, category: str) -> list[str]:
    kinds: list[str] = []
    if _has_any(text, PERSON_TERMS) or category == "Characters & People":
        kinds.append("person")
    if _has_any(text, PRODUCT_TERMS) or category == "Products & E-commerce":
        kinds.append("product")
    if category == "Brand & Logos":
        kinds.append("brand")
    if category == "UI & Interfaces":
        kinds.append("interface")
    if category == "Architecture & Spaces":
        kinds.append("place")
    if category in {"Charts & Infographics", "Documents & Publishing", "Other Use Cases"}:
        kinds.append("project")
    return list(dict.fromkeys(kinds or ["mixed"]))


def _purpose_scores(title: str, prompt: str, category: str, taxonomy: dict) -> dict[str, int]:
    purposes, aliases = _taxonomy_maps(taxonomy)
    scores = {purpose_id: 0 for purpose_id in purposes}
    default = CATEGORY_DEFAULTS.get(category, "concept-development")
    scores[default] += 60
    for purpose_id, purpose in purposes.items():
        if category in purpose.get("category_priors", []):
            scores[purpose_id] += 20
        for alias in aliases[purpose_id]:
            if _contains(title, alias):
                scores[purpose_id] += 30
            elif _contains(prompt, alias):
                scores[purpose_id] += 9

    joined = f"{title}\n{prompt}"
    if _has_any(joined, PROFILE_TERMS):
        scores["profile-portrait"] += 90
    if _has_any(joined, PORTRAIT_TERMS):
        scores["editorial-portrait"] += 65
    if _has_any(joined, PRODUCT_HERO_TERMS):
        scores["product-hero"] += 90
    if _has_any(joined, SOCIAL_TERMS):
        scores["social-cover"] += 90
    if _has_any(joined, SEQUENCE_TERMS):
        scores["narrative-scene"] += 55
    return scores


def _infer_purposes(title: str, prompt: str, category: str, taxonomy: dict) -> tuple[str, list[str]]:
    scores = _purpose_scores(title, prompt, category, taxonomy)
    ranked = sorted(scores, key=lambda item: (-scores[item], item))
    primary = ranked[0]
    threshold = max(20, scores[primary] - 35)
    secondary = [item for item in ranked[1:] if scores[item] >= threshold][:3]
    return primary, secondary


def _risk_flags(text: str, topology: str, text_policy: str) -> list[str]:
    flags = ["example-literals"]
    if topology in {"multi-panel", "sequence"}:
        flags.append("multi-output-canvas")
    if text_policy == "required":
        flags.append("text-rendering")
    if _has_any(text, ROLE_LITERAL_TERMS):
        flags.append("literal-role")
    if _has_any(text, ["dall-e", "midjourney", "stable diffusion", "flux", "nano banana"]):
        flags.append("model-specific")
    if _has_any(text, ["logo", "brand", "trademark", "品牌", "商标"]):
        flags.append("brand-literal")
    return flags


def _semantics(title: str, prompt: str, category: str, taxonomy: dict) -> dict:
    full_text = f"{title}\n{prompt}"
    topology = _infer_topology(full_text, category)
    text_policy = _infer_text_policy(full_text, category)
    primary, secondary = _infer_purposes(title, prompt, category, taxonomy)
    return {
        "primary_purpose": primary,
        "secondary_purposes": secondary,
        "output_topology": topology,
        "text_policy": text_policy,
        "reference_mode": _infer_reference_mode(full_text),
        "target_kinds": _infer_target_kinds(full_text, category),
        "medium": MEDIUM_BY_CATEGORY.get(category, "mixed-design"),
        "prompt_language": _language(prompt),
        "risk_flags": _risk_flags(full_text, topology, text_policy),
        "execution_role": "inspiration-only",
    }


def _template_recipe(item_id: str, category: str) -> str:
    return SPECIFIC_TEMPLATE_RECIPES.get(item_id, CATEGORY_RECIPES.get(category, "coherent visual direction"))


class PromptLibraryBuilder:
    """Deep module that turns upstream cases and templates into one validated library."""

    def __init__(
        self,
        cases_path: Path,
        style_library_path: Path,
        template_catalog_path: Path,
        taxonomy_path: Path,
    ) -> None:
        self.cases_path = cases_path.resolve()
        self.style_library_path = style_library_path.resolve()
        self.template_catalog_path = template_catalog_path.resolve()
        self.taxonomy_path = taxonomy_path.resolve()

    def build(self, output_dir: Path) -> dict:
        source = _read_json(self.cases_path)
        style_library = _read_json(self.style_library_path)
        template_catalog = _read_json(self.template_catalog_path)
        taxonomy = _read_json(self.taxonomy_path)
        purpose_ids = {item["id"] for item in taxonomy["purposes"]}

        enriched_cases = []
        for case in source.get("cases", []):
            prompt = str(case.get("prompt") or "").strip()
            semantics = _semantics(
                str(case.get("title") or f"Case {case.get('id')}"),
                prompt,
                str(case.get("category") or "Other Use Cases"),
                taxonomy,
            )
            enriched_cases.append({**case, "prompt": prompt, "semantics": semantics})

        template_semantics: list[dict] = []
        prompt_root = self.template_catalog_path.parent
        for category in template_catalog.get("categories", []):
            category_name = str(category.get("title_en") or category.get("slug"))
            for item in category.get("items", []):
                if not item.get("queue_ready"):
                    continue
                prompt_path = prompt_root / category["slug"] / item["files"]["en"]
                body = prompt_path.read_text(encoding="utf-8").strip()
                semantic = _semantics(str(item.get("title_en") or item["id"]), body, category_name, taxonomy)
                configured_purposes = SPECIFIC_TEMPLATE_COMPATIBILITY.get(
                    item["id"],
                    COMPATIBLE_PURPOSES_BY_CATEGORY.get(
                        category_name,
                        [semantic["primary_purpose"]],
                    ),
                )
                compatible_purposes = list(dict.fromkeys([
                    semantic["primary_purpose"],
                    *semantic["secondary_purposes"],
                    *configured_purposes,
                ]))
                semantic.update({
                    "id": item["id"],
                    "category": category["slug"],
                    "category_name": category_name,
                    "title_en": item.get("title_en", ""),
                    "kind": item.get("kind", "text"),
                    "source_file": str(prompt_path.relative_to(prompt_root)).replace("\\", "/"),
                    "visual_recipe": _template_recipe(item["id"], category_name),
                    "compatible_purposes": compatible_purposes,
                    "adaptation_mode": "semantic-recompose",
                    "raw_template_allowed_in_provider_prompt": False,
                })
                template_semantics.append(semantic)

        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        purpose_dir = output_dir / "purposes"
        if purpose_dir.exists():
            shutil.rmtree(purpose_dir)

        purpose_index: dict[str, dict[str, list[Any]]] = {
            purpose_id: {"case_ids": [], "template_ids": []} for purpose_id in sorted(purpose_ids)
        }
        for case in enriched_cases:
            sem = case["semantics"]
            for purpose_id in [sem["primary_purpose"], *sem["secondary_purposes"]]:
                purpose_index[purpose_id]["case_ids"].append(case["id"])
        for template in template_semantics:
            for purpose_id in template["compatible_purposes"]:
                purpose_index[purpose_id]["template_ids"].append(template["id"])

        for values in purpose_index.values():
            values["case_ids"] = sorted(set(values["case_ids"]), reverse=True)
            values["template_ids"] = sorted(set(values["template_ids"]))

        manifest = {
            "schema_version": 1,
            "source": {
                "repository": source.get("repository"),
                "commit": _git_commit(self.cases_path.parents[1]),
                "cases_file": str(self.cases_path),
                "cases_sha256": _sha256(self.cases_path),
                "style_library_file": str(self.style_library_path),
                "style_library_sha256": _sha256(self.style_library_path),
                "template_catalog_file": str(self.template_catalog_path),
                "template_catalog_sha256": _sha256(self.template_catalog_path),
            },
            "counts": {
                "cases": len(enriched_cases),
                "upstream_templates": len(style_library.get("templates", [])),
                "upstream_styles": len(style_library.get("styles", [])),
                "upstream_scenes": len(style_library.get("scenes", [])),
                "queue_templates": len(template_semantics),
                "upstream_categories": len(source.get("categories", [])),
                "purposes": len(purpose_ids),
            },
            "purpose_counts": {
                purpose_id: len(values["case_ids"]) for purpose_id, values in purpose_index.items()
            },
            "purpose_template_counts": {
                purpose_id: len(values["template_ids"]) for purpose_id, values in purpose_index.items()
            },
            "topology_counts": dict(Counter(case["semantics"]["output_topology"] for case in enriched_cases)),
            "text_policy_counts": dict(Counter(case["semantics"]["text_policy"] for case in enriched_cases)),
            "invariants": {
                "raw_cases_are_inspiration_only": True,
                "runtime_templates_are_semantically_recomposed": True,
                "templates_are_indexed_by_all_compatible_purposes": True,
                "every_case_has_primary_purpose": True,
                "every_case_has_output_topology": True,
            },
        }

        case_payload = {
            "schema_version": 1,
            "source": source.get("repository"),
            "total_cases": len(enriched_cases),
            "cases": enriched_cases,
        }
        _write_json(output_dir / "manifest.json", manifest)
        _write_json(output_dir / "taxonomy.json", taxonomy)
        _write_json(output_dir / "cases.json", case_payload)
        _write_json(output_dir / "upstream-style-library.json", style_library)
        _write_json(output_dir / "template-semantics.json", {
            "schema_version": 1,
            "templates": template_semantics,
        })
        _write_json(output_dir / "purpose-index.json", {
            "schema_version": 1,
            "purposes": purpose_index,
        })
        for purpose_id, values in purpose_index.items():
            _write_json(output_dir / "purposes" / f"{purpose_id}.json", {
                "schema_version": 1,
                "purpose": purpose_id,
                **values,
            })
        (output_dir / "INDEX.md").write_text(
            self._render_index(manifest, taxonomy), encoding="utf-8"
        )

        PurposeLibrary(output_dir).validate()
        return manifest

    @staticmethod
    def _render_index(manifest: dict, taxonomy: dict) -> str:
        counts = manifest["counts"]
        lines = [
            "# Purpose-first GPT-Image2 Library",
            "",
            f"Complete local index of **{counts['cases']} site cases**, "
            f"**{counts['upstream_templates']} upstream templates**, "
            f"**{counts['upstream_styles']} style tags**, "
            f"**{counts['upstream_scenes']} scene tags**, "
            f"**{counts['queue_templates']} queue templates**, and "
            f"**{counts['purposes']} user-purpose categories**.",
            "",
            "Raw site cases are inspiration only. Runtime prompts must be recomposed from a reviewed intent and one item-specific creative plan.",
            "",
            "## Purpose categories",
            "",
            "| purpose | Portuguese label | cases | templates | default topology |",
            "|---|---|---:|---:|---|",
        ]
        purpose_counts = manifest["purpose_counts"]
        template_counts = manifest["purpose_template_counts"]
        for purpose in taxonomy["purposes"]:
            lines.append(
                f"| `{purpose['id']}` | {purpose['label_pt']} | {purpose_counts[purpose['id']]} | "
                f"{template_counts[purpose['id']]} | "
                f"{', '.join(purpose['default_topologies'])} |"
            )
        lines += [
            "",
            "## Query",
            "",
            "```powershell",
            'python .\\tools\\prompt_library.py search --library .\\site-library --query "retratos criativos" --purpose editorial-portrait --topology single-frame --target-kind person --limit 8',
            "```",
            "",
            "Use `--include-prompt` only when adapting selected references; it can print long attributed source prompts.",
            "",
        ]
        return "\n".join(lines)


class PurposeLibrary:
    """Read/query interface shared by the local repository and installed skill."""

    def __init__(self, library_dir: Path) -> None:
        self.library_dir = library_dir.resolve()
        self.manifest = _read_json(self.library_dir / "manifest.json")
        self.taxonomy = _read_json(self.library_dir / "taxonomy.json")
        self.case_payload = _read_json(self.library_dir / "cases.json")
        self.upstream_style_payload = _read_json(
            self.library_dir / "upstream-style-library.json"
        )
        self.template_payload = _read_json(self.library_dir / "template-semantics.json")
        self.purpose_index_payload = _read_json(self.library_dir / "purpose-index.json")
        self.purposes, self.aliases = _taxonomy_maps(self.taxonomy)

    def search(
        self,
        query: str = "",
        purpose: str | None = None,
        topology: str | None = None,
        target_kind: str | None = None,
        text_policy: str | None = None,
        limit: int = 10,
        include_prompt: bool = False,
    ) -> list[dict]:
        if purpose and purpose not in self.purposes:
            raise ValueError(f"Unknown purpose: {purpose}")
        if topology and topology not in self.taxonomy["topologies"]:
            raise ValueError(f"Unknown topology: {topology}")
        inferred = purpose or self._infer_query_purpose(query)
        query_terms = [term for term in re.findall(r"[\w\u3400-\u9fff-]+", _fold(query)) if len(term) > 1]
        ranked: list[tuple[int, dict]] = []
        for case in self.case_payload["cases"]:
            sem = case["semantics"]
            if purpose and purpose not in [sem["primary_purpose"], *sem["secondary_purposes"]]:
                continue
            if topology and sem["output_topology"] != topology:
                continue
            if target_kind and target_kind not in sem["target_kinds"] and "mixed" not in sem["target_kinds"]:
                continue
            if text_policy and sem["text_policy"] != text_policy:
                continue
            score = 0
            if inferred == sem["primary_purpose"]:
                score += 120
            elif inferred in sem["secondary_purposes"]:
                score += 70
            searchable = _fold(" ".join([
                str(case.get("title") or ""), str(case.get("prompt") or ""),
                str(case.get("category") or ""), " ".join(case.get("styles") or []),
                " ".join(case.get("scenes") or []), sem["primary_purpose"],
                " ".join(sem["secondary_purposes"]),
            ]))
            title = _fold(str(case.get("title") or ""))
            for term in query_terms:
                if term in title:
                    score += 16
                elif term in searchable:
                    score += 3
            if sem["output_topology"] == "single-frame":
                score += 2
            ranked.append((score, case))
        ranked.sort(key=lambda pair: (-pair[0], -int(pair[1]["id"])))
        return [self._search_result(case, score, include_prompt) for score, case in ranked[: max(1, limit)]]

    def show(self, case_id: int) -> dict:
        for case in self.case_payload["cases"]:
            if int(case["id"]) == int(case_id):
                return case
        raise KeyError(f"Case not found: {case_id}")

    def stats(self) -> dict:
        return self.manifest

    def validate(self) -> dict:
        cases = self.case_payload.get("cases") or []
        templates = self.template_payload.get("templates") or []
        purpose_ids = set(self.purposes)
        topology_ids = set(self.taxonomy["topologies"])
        errors: list[str] = []
        ids = [case.get("id") for case in cases]
        if len(ids) != len(set(ids)):
            errors.append("duplicate case IDs")
        if len(cases) != self.manifest["counts"]["cases"]:
            errors.append("case count differs from manifest")
        for key, count_key in (
            ("templates", "upstream_templates"),
            ("styles", "upstream_styles"),
            ("scenes", "upstream_scenes"),
        ):
            if len(self.upstream_style_payload.get(key) or []) != self.manifest["counts"][count_key]:
                errors.append(f"upstream {key} count differs from manifest")
        for case in cases:
            sem = case.get("semantics") or {}
            if not str(case.get("prompt") or "").strip():
                errors.append(f"case {case.get('id')} has empty prompt")
            if sem.get("primary_purpose") not in purpose_ids:
                errors.append(f"case {case.get('id')} has invalid primary purpose")
            if sem.get("output_topology") not in topology_ids:
                errors.append(f"case {case.get('id')} has invalid topology")
            if sem.get("execution_role") != "inspiration-only":
                errors.append(f"case {case.get('id')} is not inspiration-only")
        template_ids = [item.get("id") for item in templates]
        if len(template_ids) != len(set(template_ids)):
            errors.append("duplicate template IDs")
        for item in templates:
            if item.get("raw_template_allowed_in_provider_prompt") is not False:
                errors.append(f"template {item.get('id')} permits raw provider prompt")
            compatible = item.get("compatible_purposes") or []
            if not compatible or not set(compatible) <= purpose_ids:
                errors.append(f"template {item.get('id')} has invalid compatible purposes")
            if item.get("primary_purpose") not in compatible:
                errors.append(f"template {item.get('id')} omits its primary compatible purpose")
        indexed = self.purpose_index_payload.get("purposes") or {}
        for purpose_id in purpose_ids:
            if purpose_id not in indexed:
                errors.append(f"purpose index is missing {purpose_id}")
                continue
            expected_cases = {
                case["id"] for case in cases
                if purpose_id in [
                    case["semantics"]["primary_purpose"],
                    *(case["semantics"].get("secondary_purposes") or []),
                ]
            }
            expected_templates = {
                item["id"] for item in templates
                if purpose_id in (item.get("compatible_purposes") or [])
            }
            if set(indexed[purpose_id].get("case_ids") or []) != expected_cases:
                errors.append(f"purpose index has incorrect cases for {purpose_id}")
            if set(indexed[purpose_id].get("template_ids") or []) != expected_templates:
                errors.append(f"purpose index has incorrect templates for {purpose_id}")
        if errors:
            raise ValueError("; ".join(errors[:30]))
        return {
            "ok": True,
            "cases": len(cases),
            "templates": len(templates),
            "purposes": len(purpose_ids),
        }

    def _infer_query_purpose(self, query: str) -> str | None:
        scores: Counter[str] = Counter()
        for purpose_id, aliases in self.aliases.items():
            for alias in aliases:
                if _contains(query, alias):
                    scores[purpose_id] += max(1, len(_fold(alias).split()))
        return scores.most_common(1)[0][0] if scores else None

    @staticmethod
    def _search_result(case: dict, score: int, include_prompt: bool) -> dict:
        result = {
            "id": case["id"],
            "title": case.get("title"),
            "category": case.get("category"),
            "styles": case.get("styles") or [],
            "scenes": case.get("scenes") or [],
            "semantics": case["semantics"],
            "image": case.get("image"),
            "source_label": case.get("sourceLabel"),
            "source_url": case.get("sourceUrl"),
            "github_url": case.get("githubUrl"),
            "score": score,
        }
        if include_prompt:
            result["prompt"] = case.get("prompt")
        return result


def _default_library() -> Path:
    installed_data = SCRIPT.parent.parent / "data"
    if (installed_data / "manifest.json").is_file():
        return installed_data
    return DEFAULT_OUTPUT


def _sync_skill(output: Path, skill_dir: Path) -> None:
    data_dir = skill_dir / "data"
    references_dir = skill_dir / "references"
    scripts_dir = skill_dir / "scripts"
    data_dir.mkdir(parents=True, exist_ok=True)
    references_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "manifest.json",
        "taxonomy.json",
        "cases.json",
        "upstream-style-library.json",
        "template-semantics.json",
        "purpose-index.json",
    ):
        shutil.copy2(output / name, data_dir / name)
    purpose_dest = data_dir / "purposes"
    if purpose_dest.exists():
        shutil.rmtree(purpose_dest)
    shutil.copytree(output / "purposes", purpose_dest)
    purpose_reference = (output / "INDEX.md").read_text(encoding="utf-8").replace(
        r"python .\tools\prompt_library.py search --library .\site-library",
        r"python .\scripts\query_style_library.py search --library .\data",
    )
    (references_dir / "purpose-library.md").write_text(
        purpose_reference,
        encoding="utf-8",
    )
    shutil.copy2(SCRIPT, scripts_dir / "query_style_library.py")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prompt_library")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    build.add_argument("--style-library", type=Path, default=DEFAULT_STYLE_LIBRARY)
    build.add_argument("--template-catalog", type=Path, default=DEFAULT_TEMPLATE_CATALOG)
    build.add_argument("--taxonomy", type=Path, default=DEFAULT_TAXONOMY)
    build.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    build.add_argument("--skill-dir", type=Path)

    for command in ("search", "show", "stats", "validate"):
        item = sub.add_parser(command)
        item.add_argument("--library", type=Path, default=_default_library())
        if command == "search":
            item.add_argument("--query", default="")
            item.add_argument("--purpose")
            item.add_argument("--topology")
            item.add_argument("--target-kind")
            item.add_argument("--text-policy", choices=("forbidden", "optional", "required"))
            item.add_argument("--limit", type=int, default=10)
            item.add_argument("--include-prompt", action="store_true")
        if command == "show":
            item.add_argument("--case", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    if args.command == "build":
        builder = PromptLibraryBuilder(args.cases, args.style_library, args.template_catalog, args.taxonomy)
        manifest = builder.build(args.output)
        if args.skill_dir:
            _sync_skill(args.output.resolve(), args.skill_dir.resolve())
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return
    library = PurposeLibrary(args.library)
    if args.command == "search":
        result = library.search(
            query=args.query,
            purpose=args.purpose,
            topology=args.topology,
            target_kind=args.target_kind,
            text_policy=args.text_policy,
            limit=args.limit,
            include_prompt=args.include_prompt,
        )
    elif args.command == "show":
        result = library.show(args.case)
    elif args.command == "stats":
        result = library.stats()
    else:
        result = library.validate()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
