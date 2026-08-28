"""Extract 100% of docs/templates.md into ImageGenSource/PROMPTS.

Writes per-item:
  NN-slug.zh.txt   verbatim upstream body
  NN-slug.en.txt   English (verbatim if already EN, else translated)
  NN-slug.meta.json
Plus catalog.json + INDEX.md + _source/templates.md
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

SRC = Path(
    r"C:\Users\user\Desktop\ImageGenSource\vendor\awesome-gpt-image-2\docs\templates.md"
)
OUT = Path(r"C:\Users\user\Desktop\ImageGenSource\PROMPTS")

CATEGORIES = [
    ("01-ui-interfaces", "UI与界面", "UI & Interfaces", "tpl-ui"),
    ("02-charts-infographics", "图表与信息可视化", "Charts & Infographics", "tpl-infographic"),
    ("03-posters-typography", "海报与排版", "Posters & Typography", "tpl-poster"),
    ("04-products-ecommerce", "商品与电商", "Products & E-commerce", "tpl-product"),
    ("05-brand-logos", "品牌与标志", "Brand & Logos", "tpl-brand"),
    ("06-architecture-space", "建筑与空间", "Architecture & Spaces", "tpl-architecture"),
    ("07-photography-realism", "摄影与写实", "Photography & Realism", "tpl-photo"),
    ("08-illustration-art", "插画与艺术", "Illustration & Art", "tpl-illustration"),
    ("09-characters-people", "人物与角色", "Characters & People", "tpl-character"),
    ("10-scenes-storytelling", "场景与叙事", "Scenes & Storytelling", "tpl-scene"),
    ("11-history-classical", "历史与古风题材", "History & Classical Themes", "tpl-history"),
    ("12-documents-publishing", "文档与出版物", "Documents & Publishing", "tpl-document"),
    ("13-other-use-cases", "其他应用场景", "Other Use Cases", "tpl-other"),
]

TITLE_EN = {
    "常规模板": "Standard template",
    "JSON 进阶模板（推荐给 Agent 调用）": "JSON advanced template (recommended for agents)",
    "截图生成模板": "Screenshot generation template",
    "直播界面模板": "Live-stream UI template",
    "尺度缩放科学信息图模板": "Scientific scale diagram template",
    "运动商业 Campaign 模板": "Sports campaign poster template",
    "概念字体海报模板": "Conceptual typography poster template",
    "多风格签名选择海报模板": "Multi-style signature selection poster template",
    "单款签名提取模板": "Single signature extraction template",
    "签名练习拆解图模板": "Signature practice breakdown template",
    "中文版：概念字体海报模板": "Conceptual typography poster template (Chinese version)",
    "水墨双重曝光人物海报模板": "Ink double-exposure portrait poster template",
    "自然科普海报模板": "Nature science poster template",
    "个人化美妆推荐报告模板": "Personalized beauty recommendation report template",
    "完整品牌身份包模板": "Full brand identity package template",
    "品牌触点系统视觉板模板": "Brand touchpoint system board template",
    "品牌包络产品广告模板": "Brand-wrapped product ad template",
    "品牌人格漫画信息图模板": "Brand personality comic infographic template",
    "街头意外瞬间写实摄影模板": "Street accident candid photography template",
    "动作分解参考表模板": "Action breakdown reference sheet template",
    "参考图转 3D 收藏玩具模板": "Reference-to-3D collectible toy template",
    "企业画册系统模板": "Corporate brochure system template",
    "概念产品研发拆解板模板": "Concept product R&D breakdown board template",
    "避坑指南": "Pitfalls guide",
}

SLUG = {
    "常规模板": "standard",
    "JSON 进阶模板（推荐给 Agent 调用）": "json-advanced",
    "截图生成模板": "screenshot",
    "直播界面模板": "livestream-ui",
    "尺度缩放科学信息图模板": "scientific-scale-diagram",
    "运动商业 Campaign 模板": "sports-campaign",
    "概念字体海报模板": "conceptual-typography",
    "多风格签名选择海报模板": "multi-style-signature-poster",
    "单款签名提取模板": "single-signature-extract",
    "签名练习拆解图模板": "signature-practice-breakdown",
    "中文版：概念字体海报模板": "conceptual-typography-zh",
    "水墨双重曝光人物海报模板": "ink-double-exposure",
    "自然科普海报模板": "nature-science-poster",
    "个人化美妆推荐报告模板": "personalized-beauty-report",
    "完整品牌身份包模板": "full-brand-identity-package",
    "品牌触点系统视觉板模板": "brand-touchpoint-board",
    "品牌包络产品广告模板": "brand-wrapped-product-ad",
    "品牌人格漫画信息图模板": "brand-personality-comic-infographic",
    "街头意外瞬间写实摄影模板": "street-accident-moment",
    "动作分解参考表模板": "action-breakdown-sheet",
    "参考图转 3D 收藏玩具模板": "ref-to-3d-collectible-toy",
    "企业画册系统模板": "corporate-brochure-system",
    "概念产品研发拆解板模板": "concept-product-rd-breakdown",
    "避坑指南": "pitfalls",
}


def mostly_en(s: str) -> bool:
    cjk = len(re.findall(r"[\u4e00-\u9fff]", s))
    latin = len(re.findall(r"[A-Za-z]", s))
    return latin >= max(cjk * 2, 1) and cjk < 50


def parse(md: str) -> list[dict]:
    """Parse templates.md.

    Upstream has broken fences in the poster section (a ```text never closed
    before the next **title** / next ```text). We recover by treating a new
    **title** or a new opening fence as an implicit close of the previous body.
    """
    cat_by_zh = {zh: (slug, en, a) for slug, zh, en, a in CATEGORIES}
    text = md.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    categories: list[dict] = []
    cur = None
    i = 0
    n = len(lines)

    def add_item(title: str, lang: str, body: str) -> None:
        assert cur is not None
        kind = "json" if lang == "json" else "text"
        if title == "避坑指南":
            kind = "pitfalls"
        # Drop accidental nested **titles** that leaked into body text only
        body = body.strip("\n")
        cur["items"].append(
            {
                "title_zh": title,
                "title_en": TITLE_EN.get(title, title),
                "slug": SLUG.get(title, "item"),
                "kind": kind,
                "body_zh": body,
            }
        )

    def read_fence_body(start: int) -> tuple[str, int]:
        """Read fence body starting AFTER the opening ``` line. Return (body, next_i).

        Stops on:
        - closing ``` alone
        - a new **Title** line (implicit close; do not consume the title line)
        - a new opening ```lang line (implicit close; do not consume it)
        - a ### category heading
        """
        body_lines: list[str] = []
        j = start
        while j < n:
            L = lines[j]
            if re.match(r"^```\s*$", L):
                return "\n".join(body_lines).strip("\n"), j + 1
            if re.match(r"^```\w+\s*$", L):
                # new opening fence without close — end previous body
                return "\n".join(body_lines).strip("\n"), j
            if re.match(r"^\*\*.+\*\*\s*$", L):
                return "\n".join(body_lines).strip("\n"), j
            if re.match(r"^### ", L):
                return "\n".join(body_lines).strip("\n"), j
            body_lines.append(L)
            j += 1
        return "\n".join(body_lines).strip("\n"), j

    while i < n:
        line = lines[i]
        m_cat = re.match(r"^### (.+)$", line)
        if m_cat:
            zh = m_cat.group(1).strip()
            if zh in cat_by_zh:
                slug, en, a = cat_by_zh[zh]
                cur = {
                    "slug": slug,
                    "title_zh": zh,
                    "title_en": en,
                    "anchor": a,
                    "items": [],
                }
                categories.append(cur)
            i += 1
            continue

        if cur is None:
            i += 1
            continue

        m_sub = re.match(r"^\*\*(.+?)\*\*\s*$", line)
        if not m_sub:
            i += 1
            continue

        title = m_sub.group(1).strip()
        i += 1
        while i < n and (lines[i].strip() == "" or lines[i].startswith(">")):
            i += 1

        m_fence = re.match(r"^```(\w+)?\s*$", lines[i] if i < n else "")
        if m_fence:
            lang = (m_fence.group(1) or "text").lower()
            i += 1
            body, i = read_fence_body(i)
            add_item(title, lang, body)
            continue

        if title == "避坑指南":
            bullets: list[str] = []
            while i < n:
                L = lines[i]
                if re.match(r"^### ", L) or re.match(r"^\*\*.+\*\*\s*$", L):
                    break
                if re.match(r"^```", L):
                    break
                if L.startswith("- ") or L.startswith("* ") or (
                    bullets and (L.startswith("  ") or L.startswith("\t") or L.strip() == "")
                ):
                    if L.strip():
                        bullets.append(L)
                    i += 1
                    continue
                break
            body = "\n".join(bullets).strip()
            if body:
                add_item("避坑指南", "text", body)
            continue

        # Title without body — skip
        continue

    return categories


# ---------------------------------------------------------------------------
# English: prefer full structural translation. For long Chinese prompts, use a
# faithful EN rewrite keeping every [slot] and section. Short standards use
# compact fill-ins. Bodies already EN stay as-is.
# ---------------------------------------------------------------------------

def en_for(cat_slug: str, title_zh: str, kind: str, body_zh: str) -> str:
    if mostly_en(body_zh) and title_zh != "避坑指南":
        return body_zh

    # Generic section-preserving translation helper for long Chinese docs:
    # We ship curated full EN for every known title; fallback marks pending.
    key = (cat_slug, title_zh, kind)
    table = EN_TABLE
    if key in table:
        return table[key]
    # title-only key
    key2 = (title_zh, kind)
    if key2 in table:
        return table[key2]
    return "[EN translation pending — Chinese original in .zh.txt]\n\n" + body_zh


def _std_ui() -> str:
    return """Generate a [platform, e.g. iOS / Android / Web] UI screen for a [product type].
Core features: [feature A], [feature B], [feature C].
Visual style: [minimal / tech / skeuomorphic], primary color [color], accent [color].
Layout: [top nav / two-column / card feed], clear information hierarchy, generous whitespace.
Output: high-fidelity UI screenshot, readable text, aspect ratio [9:16 / 16:9]."""


def build_en_table() -> dict:
    t: dict = {}

    # ---- UI ----
    t[("01-ui-interfaces", "常规模板", "text")] = _std_ui()
    t[("01-ui-interfaces", "截图生成模板", "text")] = """Generate a [platform, e.g. X / Douyin / Xiaohongshu / WeChat Moments] content screenshot, [dark / light] mode.
Overall ratio: [9:16 / 3:4 / 1:1], phone-screenshot style.

Core content:
- Account info: [avatar description / username / verification badge]
- Body text: [exact copy, including any specified language]
- Engagement stats: [likes / comments / reposts / saves]

UI chrome:
- Top: [status bar / navigation]
- Bottom: [tab bar / action row / comment input]
Constraints: high-fidelity platform chrome, readable text, no gibberish labels."""
    t[("01-ui-interfaces", "直播界面模板", "text")] = """Generate a live-stream interface screenshot for [platform, e.g. Douyin / Kuaishou / Bilibili].
Host area: [host description / camera framing].
Overlay chrome: viewer count, gift/combo effects, scrolling comments, product card [product name + price].
Style: [dark / light], accent [color], mobile [9:16].
Constraints: readable live UI labels, no fake unreadable text, clear hierarchy of host vs overlays."""
    t[("01-ui-interfaces", "避坑指南", "pitfalls")] = """- Do not give vague instructions: lock "platform + ratio + layout" or the model will layout randomly.
- Force text lock: require "text must be fully readable; show the specified copy" to avoid gibberish buttons.
- Screenshot platforms differ: X has blue check + repost/quote; Douyin has music disc + like animation; Xiaohongshu has dual-column waterfall. Specify the platform first.
- Live UI: define the scene first (selling / chat / gaming) before chrome details."""

    # ---- charts ----
    t[("02-charts-infographics", "常规模板", "text")] = """Generate an infographic on [topic: specific, not vague — e.g. "daily health guide for seniors" not "health"], target readers [audience: age, role, interests].
Structure: [3–5 modules], information flow [left-to-right / top-to-bottom / hub-and-spoke].
Visual system: color groups, short labels, icons/arrows, clean spacing.
Constraints: no long paragraphs inside the image; short labels only.
Output: clean educational infographic, aspect [ratio]."""
    t[("02-charts-infographics", "尺度缩放科学信息图模板", "text")] = """Generate a scientific scale diagram for [topic].
Use [6–8] scale frames from micro to macro; each frame has a short unit/magnification label and distinct detail.
Style: premium science poster, clean white/light background, disciplined labels.
Constraints: frames must not look identical; avoid generic magnifying-glass layouts.
Output: labeled multi-scale science plate."""
    t[("02-charts-infographics", "避坑指南", "pitfalls")] = """- Force module count and chart types; unlimited modules become clutter.
- Keep labels short; never paste long body copy into the image.
- Scale diagrams need distinct detail per frame and explicit units."""

    # ---- posters: long ones get full EN ----
    t[("03-posters-typography", "常规模板", "text")] = """Design a [event / product / film] poster themed [theme word].
Hero visual: [main element], headline: [title], subhead: [subtitle].
Layout: [centered / left-aligned / diagonal], style: [retro / futuristic / minimal].
Colors: [primary + secondary], mood: [emotion keywords].
Output: high-resolution poster ready for social distribution."""
    t[("03-posters-typography", "运动商业 Campaign 模板", "text")] = """Design a [sport / fitness category] commercial campaign poster.
Subject: [athlete / model / product prop], pose: [seated / sprint / swing / strength move].
Hero prop: [racket / dumbbell / sneaker / jersey], exaggerated scale or diagonal composition as visual anchor.
Layout: [single strong hero / triptych / data-doodle poster].
Big title: "[main title]", support copy: "[short line / data / spirit slogan]".
Visual style: premium sports-brand ad, strong light, reflective floor, clean composition, branded palette [primary+secondary].
Constraints: clear subject, readable type, unified color, no noisy collage, no wrong sports gear.
Output: 1:1 or 4:5 sports commercial visual for social."""

    # EN conceptual typography already in ZH file when English — mostly_en handles.
    # Chinese version of conceptual typography:
    t[("03-posters-typography", "中文版：概念字体海报模板", "text")] = """Create ONE finished premium conceptual typography poster for the exact title:

"[title / word / short phrase]"

Single poster only. No moodboard, no grid layout, no presentation board, no mockup, no caption text, no process sheet, no sample labels.

The title must be the dominant visual structure: huge, readable, powerful, spelled exactly. Do not translate, shorten, replace, or misspell it. Do not add other large readable text.

Deeply interpret the title's meaning, mood, cultural aura, symbolic associations, psychological tension, and visual rhythm. Turn that into one strong visual metaphor.

Typography is the hero. Design custom letterforms whose weight, width, contrast, spacing, rhythm, distortion, negative space, edge quality, and ink texture express the title's temperament. The type must feel intentionally designed, not a default font.

If the title points to a well-known person, make a large editorial portrait or half-body figure a major presence (about 40%–70% of the composition). The figure must interact with the type: overlap letters, emerge from them, be framed by them, cast shadows on them, break through them, or hide partially behind them.

For abstract or non-person titles, use a human figure, landscape, object, or atmosphere only when it strengthens meaning. It must interact with the type and deepen the concept, not decorate it.

Use a restrained 4–6 color system matched to the theme: dominant background, primary type color, figure/landscape tone, emotional accent, muted support, subtle paper/ink texture tone.

Composition: high-end editorial poster, museum-grade graphic design, dramatic scale, strong hierarchy, few elements, intelligent whitespace, bold flat color areas, sharp cropping, silkscreen / lithograph / risograph grain, paper fibers, subtle ink imperfections, refined visual tension.

Avoid: generic word art, glossy 3D type, random icons, stock realism, cluttered collage, excessive grunge, tourist clichés, official logos, copied slogans, copied campaign aesthetics, unrelated text, misspelled type."""

    t[("03-posters-typography", "多风格签名选择海报模板", "text")] = """You are a high-end signature design system + style-persona visual system.

Input:
Name: [full name / nickname]

Task:
From the name alone, automatically generate one 9:16 vertical multi-style signature selection poster.
Goal: translate the name into 6 signature schemes with distinct stroke energy, temperament, and force.

Hidden analysis (do not print):
1. Analyze glyph structure: density, horizontal/vertical balance, center of gravity, ligature space, cursive room.
2. Infer temperament: cool, bold, restrained, commercial, literary, relaxed, sharp, premium.
3. For each signature, define writing behavior first: entry, joins, rhythm, structural distortion, exit.

Layout:
- Pure white or very light gray gradient background, whitespace ≥ 40%
- Top large title: [Name] · Signature Style Choices
- Subtitle: Different strokes, different aura
- Middle: 2-column × 3-row card grid
- Bottom small line: Pick one as your signature.

Card rules:
- Uniform size, spacing, alignment
- Soft corner radius 8–16px
- Hairline border or borderless
- Very light shadow
- White micro-variation / light gray / rice-paper or frosted texture
- Premium magazine layout, not heavy UI chrome

Six signatures:
1. Minimal rational — brand-like, restrained strokes, clear whitespace
2. Wild tension — strong ligatures, speed, stretched exits
3. Relaxed casual — handwriting feel, open, friendly
4. Eastern running script — flying white, ink feel, rhythmic rise/fall
5. Sharp structure — geometric cuts, fracture, cool restraint
6. Experimental — partly illegible, restructured forms

Constraints: no extra decorative icons, no photo collage, no watermark; name identity readable across styles.
Output: one finished 9:16 poster."""

    t[("03-posters-typography", "单款签名提取模板", "text")] = """From the signature at [position / number / style name] in the input image, extract its core stroke energy and generate a pure signature plate.

Requirements:
- Keep only the signature; no poster card, title, subtitle, or caption
- Preserve entry stroke, joins, structural slant, flying white, and exit rhythm from the original
- Background pure white or very light warm white
- Signature centered, large enough, clean edge whitespace
- Ink deep black / ink black with natural brush tips, light ink marks, real handwriting pressure
- Output high-res pure signature suitable for practice, collection, or secondary design"""

    t[("03-posters-typography", "签名练习拆解图模板", "text")] = """Based on the input [signature image / signature style], generate a signature practice breakdown sheet.

Goal:
Help the user practice this signature with a black pen on paper by breaking every stroke path, order, force, and rhythm.

Frame structure:
- Vertical teaching plate or horizontal practice board
- Top: final signature sample
- Middle: 8–12 steps decomposing key strokes
- Each step shows current stroke, motion-direction arrows, entry point, pause point, exit point
- Bottom: full continuous path plus 3–5 practice tips

Breakdown rules:
- Every stroke must map to the original signature
- Mark stroke order with clear numbers
- Show pressure changes (thick/thin) and speed cues
- Keep teaching-notebook feel: white paper, black handwriting lines, red or blue teaching arrows, clear numbering

Visual style:
White paper background, black handwriting lines, red or blue teaching arrows, clear numbering, workbook texture.

Avoid:
Do not only show the finished signature; do not skip key strokes; do not turn steps into random doodles; do not generate unrelated calligraphy copybooks."""

    t[("03-posters-typography", "水墨双重曝光人物海报模板", "text")] = """Generate an ink double-exposure portrait poster of [person / character / brand founder / athlete].
Aspect: 9:16 vertical, premium film-poster composition.
Subject structure:
- Upper zone: enlarged head, facial contour, or half-body silhouette as the strongest identity anchor
- Mid-lower zone: full or half body of the same person, pose [standing / action / gaze to camera]
- Inside the silhouette: fuse [key scene], [symbol], [narrative beat], [environment texture] into a double-exposure narrative
Visual links: mist, ink bleed, flying-white edges, negative space connecting the two layers
Mood: poetic, quiet, museum-quality; text minimal or none unless required
Constraints: no cheap fantasy collage, no overloaded scenery; face must stay readable
Output: single finished premium poster"""

    t[("03-posters-typography", "自然科普海报模板", "text")] = """You are a premium nature-science poster system for rare animals, insects, reptiles, mammals, or other niche organisms in an Apple-keynote visual language.

Overall direction:
Generate one 9:16 vertical premium science poster — minimal, pure white, clean, modern, Apple product-launch poster language. Background pure white or ultra-light gray gradient with large whitespace. Feel: premium, restrained, high visual impact, scientific display.

Core design principles:
1. Hero organism is the absolute visual center, product-photography level, ultra-sharp, soft shadows
2. Minimal copy; short scientific name / common name labels only
3. Disciplined whitespace; no dense encyclopedia blocks
4. Soft shadows, no heavy advertising language
5. Layout can include small callout plates for size, habitat, or one key fact — short labels only

Subject: [organism / species]
Optional label: "[Latin or short scientific name]"
Optional facts: [1–3 short facts]
Constraints: no ad slogans, no cluttered icons, no fake micro-text
Output: one finished nature-science poster"""

    t[("03-posters-typography", "避坑指南", "pitfalls")] = """- Do not be lazy: state exactly what the hero visual is; "make a poster" alone fails.
- Hard-code headline and subhead or the model invents nonsense type.
- Sports campaigns: lock structure first (single hero / triptych / data doodle) before subject and copy.
- Props are composition skeleton: specify angle, scale, and role of racket/dumbbell/shoe.
- Typography posters: type is the hero; no default word-art; restrained palette; exact spelling.
- Ask for one finished poster, not a moodboard or process sheet."""

    # ---- products ----
    t[("04-products-ecommerce", "常规模板", "text")] = """Generate an e-commerce hero image for [product name], selling points [point1], [point2].
Show material [material], scene [scene], lighting [lighting].
Layout blocks: hero product, benefit labels, supporting props (only if they help recognition).
Constraints: no random props that weaken product ID; packaging text accurate and minimal.
Output: commercial product visual for detail page / ad."""
    t[("04-products-ecommerce", "个人化美妆推荐报告模板", "text")] = """You are a professional beauty advisor + face analysis system + brand visual design system.
Goal: from [user selfie] and [lipstick brand], generate a vertical lipstick recommendation report infographic with analysis + recommendation + swatch + scene advice.

Input parameters:
User image: [user selfie]
Brand: [Dior / YSL / Armani / Chanel / TF / other]
Style preference (optional): [commute / soft / presence / atmosphere / brightening-first]
Recommendation count: [3–5]

Report hierarchy:
1. Face/skin tone diagnosis (short, non-medical)
2. Recommended shades with swatches
3. Scene suggestions (day / night / event)
4. Product cards with short labels and ratings

Constraints: no medical claims; no dense unreadable notes; keep recommendation logic simple and scannable.
Output: shopping-assistant style vertical report visual."""
    t[("04-products-ecommerce", "避坑指南", "pitfalls")] = """- Separate hero product, benefit labels, and props; props must not steal recognition.
- Constrain packaging claims and text accuracy.
- Beauty reports: avoid medicalization; keep labels scannable."""

    # ---- brand ----
    t[("05-brand-logos", "常规模板", "text")] = """Design a brand visual system for [brand name].
Positioning: [positioning], palette: [colors], typography: [type direction], logo usage rules, key touchpoints.
Output: coherent brand board with aligned applications."""
    t[("05-brand-logos", "完整品牌身份包模板", "text")] = """You are a top brand-agency creative director. Deliver a full brand identity system for [business / product] covering logo, palette, type, tone of voice, and application touchpoints.

Input:
Business name: [name]
One-line description: [description]
Industry: [industry]
Audience: [detailed]
Competitors: [3–5]
Brand personality: [5 keywords]
Desired feelings: [trust / excitement / luxury / closeness / power / other]
Liked visual identities: [3 refs]
Disliked visual identities: [3 refs]

Output board panels:
- Logo / monogram system
- Color chips with usage
- Typography samples
- Tone-of-voice examples (short)
- Business card, avatar, app icon
- 1–2 application mockups

Constraints: one palette, one type logic, brand name spelled exactly; no unrelated logo variants.
Output: single aligned identity package board."""
    t[("05-brand-logos", "品牌触点系统视觉板模板", "text")] = """Generate a premium brand touchpoint system board for [brand name] — not a single poster, but a full application set.

Brand positioning: [industry / lifestyle / product category]
Core temperament: [keyword1], [keyword2], [keyword3]
Hero scene: [core product / service / experience] on [material surface / spatial scene], light [light], lens [lens].

Touchpoints must include:
- Main product hero shot
- Packaging box / tote / cup / label / sticker / seal
- Digital: website hero, social avatar, story frame
- Physical: business card, conference badge (as fits brand)

Shared palette and typography across all mockups; clean arrangement.
Constraints: max touchpoints for readability; no mixed unrelated campaign styles.
Output: multi-touchpoint rollout board."""
    t[("05-brand-logos", "品牌包络产品广告模板", "text")] = """Input: [product image], [brand identity], [output format]

PHASE 1 / ANCHOR: in 2 lines describe [brand identity] including palette, materials, light, and mood.
PHASE 2 / INJECT: place [product] into this brand world; product obeys brand temperament and environment language.
PHASE 3 / FORMAT: specify [output format] e.g. hero image, square ad, vertical story, or e-commerce header.
PHASE 4 / SIGNAL: short slogan "[slogan]" and brand marks secondary but consistent.

Constraints: no clashing styles; packaging/brand text accurate.
Output: one premium brand-wrapped product ad."""
    t[("05-brand-logos", "品牌人格漫画信息图模板", "text")] = """From the uploaded [logo / brand visual], generate a 4:5 vertical comic infographic: "What This Brand Feels Like".
Goal: turn the brand into a perceivable personality character and explain how it speaks, acts, sells, answers competition, and handles criticism.
Core rule: all colors, costume, pose, tone, and graphic elements come from the logo and brand keywords.
Hero: a brand-personified character whose outfit, expression, and pose embody [brand temperament].
Around it: 6–8 comic panels, each with a short label + simple scene.
Constraints: short labels only; no long paragraphs; character consistency across panels.
Output: one comic-infographic plate."""
    t[("05-brand-logos", "避坑指南", "pitfalls")] = """- Subtract: define brand keywords before visual output for unity. A dragon on the Great Wall with lightning is illustration, not a logo.
- Force pure white background when you need easy cutout later.
- Strategy before logo: without audience, competitors, and emotional goals, logos become pretty shapes with no fit.
- One palette + one type logic across the whole board; keep brand text exact."""

    # ---- architecture ----
    t[("06-architecture-space", "常规模板", "text")] = """Generate a design visualization of [space type], functional purpose [use].
Viewpoint: [eye-level / aerial / section], scale, materials [materials], lighting [lighting].
For maps: landmarks, labels, border treatment, accuracy level.
Constraints: believable perspective unless explicitly conceptual; lock label language.
Output: architecture / interior / spatial concept image."""
    t[("06-architecture-space", "避坑指南", "pitfalls")] = """- Define viewpoint, scale, material, light, and function before style adjectives.
- Avoid impossible perspectives unless the brief is conceptual.
- On maps, lock relative placement and label language."""

    # ---- photo ----
    t[("07-photography-realism", "常规模板", "text")] = """Shoot subject: [person / object / street scene], location [place].
Camera style: [35mm / 85mm], [shallow / deep] depth of field, [documentary / cinematic].
Light: [natural / neon night / backlight], mood: [emotion words].
Detail: [skin texture / material / grain].
Output: hyper-realistic photography-style image."""
    t[("07-photography-realism", "街头意外瞬间写实摄影模板", "text")] = """Generate a vertical phone documentary photo of [accident / everyday moment] on [street / outdoor place].
Subject: [object / person action / scene traces], real material states e.g. [liquid spread / scattered ice / crumpled paper / dust].
Environment: [ground material / walls / street elements], keep natural clutter and life traces.
Light: [harsh noon / overcast / night street lamps], shadows match real direction; may include [person shadow / sign shadow / tree shadow].
Lens: handheld phone angle, slight high or low angle, natural composition like a candid capture.
Look: raw unedited photo, natural color, real texture, high detail.
Negatives: no illustration, anime, CGI, studio light, over-clean, over-composed, fake liquids, floating objects, brand text, watermarks, poster design feel.
Output: one believable everyday documentary photo."""
    t[("07-photography-realism", "避坑指南", "pitfalls")] = """- Add believable imperfections: skin pores, freckles, light film grain — perfect skin reads fake.
- Speak in camera params: f/1.4, 50mm, Sony A7R IV beat vague "shallow DOF / half-body".
- Write imperfect specifics: rough stone, scattered ice, natural shadows, slight handheld feel."""

    # ---- illustration ----
    t[("08-illustration-art", "常规模板", "text")] = """Create an illustration on [subject], protagonist [character / subject].
Composition, palette, brush/material [watercolor / ink / digital paint], mood, finish level.
If using a reference: state which identity anchors to preserve.
Constraints: not style-only; composition required; lock character identity when referenced.
Output: finished illustration."""
    t[("08-illustration-art", "避坑指南", "pitfalls")] = """- Do not write style alone without composition and subject.
- When using references, lock face / hair / costume anchors explicitly."""

    # ---- characters ----
    t[("09-characters-people", "常规模板", "text")] = """Design a character sheet for [role / identity].
Look: [age / hair / costume / props], personality: [keywords].
Pose: [standing / action], expression: [emotion].
World: [era / faction / job], signature element: [element].
Output: main view + unified character design plate."""
    t[("09-characters-people", "动作分解参考表模板", "text")] = """Generate an action-breakdown reference sheet for [character / person].
Style: [B&W line / 3D grayscale / comic storyboard / teaching plate], clean background, technical reference feel.
Layout: 4×4 grid, 16 equal panels, thin dividers, number 1–16 top-left of each cell.
Character consistency: same character in every panel — same face, costume, proportions, hairstyle.
Per-cell structure:
- Top: action title
- Center: full-body pose
- Bottom: 3–4 lines of action notes
- Overlay: direction arrows, rotation arrows, or motion paths
Action sequence: [full step list from base stance to end pose]
Constraints: no complex backgrounds, no extra characters, no noisy color, no identity drift.
Output: clear sheet usable for animation / dance / game action reference."""
    t[("09-characters-people", "参考图转 3D 收藏玩具模板", "text")] = """Convert the input photo into a premium 3D collectible toy.
Identity lock: keep original face identity, main hairstyle, expression temperament, and costume recognition points.
Proportion: chibi/large-head designer-toy proportions, slightly exaggerated features, still premium.
Materials: matte vinyl / resin / collectible figure finish, detailed skin and costume materials.
Light & BG: soft studio light, clean background [black / white / brand color], subject centered, crisp silhouette.
Look: ultra-sharp, real material response, 8K render, premium designer-toy aesthetic.
Constraints: do not change identity, no cheap plastic, no multi-character, no complex BG, no text watermark.
Output: one complete premium collectible figure render."""
    t[("09-characters-people", "避坑指南", "pitfalls")] = """- Decompose facial features instead of "beautiful person".
- Name fabric/materials to ground the costume.
- Action sheets must lock grid count, numbering, and per-cell structure.
- Toys: lock identity anchors before chibi proportions and materials.
- Long action sequences drift identity — restate same face/costume/proportion before the step list."""

    # ---- scenes ----
    t[("10-scenes-storytelling", "常规模板", "text")] = """Generate a story scene on [story theme], set at [time + place].
Who / conflict / emotion / camera framing.
Scene details serve the narrative, not decoration.
Constraints: no generic fantasy background; keep story cues visible.
Output: single narrative frame / storyboard still."""
    t[("10-scenes-storytelling", "避坑指南", "pitfalls")] = """- Define who, where, when, conflict, emotion, camera before style words.
- Avoid generic fantasy BGs; make narrative cues readable in-frame."""

    # ---- history ----
    t[("11-history-classical", "常规模板", "text")] = """Generate a [dynasty / classical setting] themed image on [theme].
Clothing system, object references, layout format [scroll / album page / poster], cultural mood.
Constraints: do not mix dynasties when accuracy matters; no random modern props.
Output: historical / classical plate."""
    t[("11-history-classical", "避坑指南", "pitfalls")] = """- Specify dynasty/clothing system and object references.
- No modern props (phones, backpacks) unless the brief is anachronistic on purpose."""

    # ---- documents ----
    t[("12-documents-publishing", "常规模板", "text")] = """Produce a [document type, e.g. menu / magazine spread / newspaper layout].
Page size, columns, hierarchy, figure system, short readable labels.
Constraints: no tiny dense text; charts/captions align to the page grid.
Output: publication-ready page plate."""
    t[("12-documents-publishing", "企业画册系统模板", "text")] = """Generate an enterprise commercial brochure visual system themed around [brand name]'s [industry / product / solution] brochure.

Overall style: premium, professional, high visual impact; avoid Word-doc layout feel and generic PPT feel. Choose [dark tech aesthetic / white minimal business / premium industrial / art-direction brand brochure].

Brochure content includes:
1. Cover and back cover
2. Company intro and brand philosophy
3. Core products and technical strengths
4. Application scenarios and solutions
5. Client cases and partnership paths
6. Contact / closing page

Layout: clear type hierarchy, image figures, short body blocks, consistent grid and margins.
Constraints: readable headings, no wall of micro-type, consistent visual system across pages.
Output: corporate brochure system plates (cover + key inner spreads as one board or multi-panel)."""
    t[("12-documents-publishing", "避坑指南", "pitfalls")] = """- Define page size, columns, TOC/figure system, type hierarchy first.
- Avoid dense tiny text; keep charts and captions on the grid."""

    # ---- other ----
    t[("13-other-use-cases", "常规模板", "text")] = """Task goal: [type of content to generate].
Define artifact type, components, labels, material logic, final presentation format.
Use clear callouts and a controlled technical style.
Constraints: do not leave the task boundary vague; keep labels short and relations visible.
Output: special-case visual system plate."""
    t[("13-other-use-cases", "概念产品研发拆解板模板", "text")] = """Generate a full concept product R&D breakdown board for [product / furniture / installation] — not a single finished render.

Core concept:
Translate [inspiration source, e.g. crumpled paper / shell / origami / mechanical structure] into [product type].
Design philosophy: [one sentence on function + emotion, e.g. "controlled chaos turned into high-comfort seating"].

Board structure:
- Center: high-quality hero render of final form, materials, proportions
- Left: observation and form analysis — inspiration images, contour extraction, structure lines, crease/texture/force notes
- Right: exploded components with short callouts [part names]
- Bottom: material chips, finish notes, scale references

Material logic: [materials]; controlled technical line style; short labels.
Constraints: short labels, component relationships visible, no unspecified mixed tasks.
Output: one R&D / exploded-view board."""
    t[("13-other-use-cases", "避坑指南", "pitfalls")] = """- Define artifact type, components, labels, materials, presentation format before decoration.
- Keep labels short; make component relationships obvious."""

    return t


EN_TABLE: dict = {}


def write_tree(categories: list[dict]) -> dict:
    # wipe previous category dirs and catalogs but keep extract scripts
    keep = {
        "extract_prompts.py",
        "extract_prompts_v2.py",
        "_parsed.json",
        "tools",
        "site-library",
    }
    if OUT.exists():
        for child in OUT.iterdir():
            if child.name in keep:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    OUT.mkdir(parents=True, exist_ok=True)

    catalog = {
        "source": "https://github.com/freestylefly/awesome-gpt-image-2/blob/main/docs/templates.md",
        "source_local": str(SRC),
        "skill": "gpt-image-2-style-library",
        "note": (
            "100% industrial templates from docs/templates.md. "
            "*.zh.txt = verbatim upstream; *.en.txt = English fill-in for queue "
            "(slots keep [brackets]). kind=text|json|pitfalls."
        ),
        "categories": [],
        "stats": {},
    }

    total_items = 0
    total_prompts = 0
    pending = []

    for cat in categories:
        cat_dir = OUT / cat["slug"]
        cat_dir.mkdir(parents=True, exist_ok=True)
        cat_entry = {
            "slug": cat["slug"],
            "title_zh": cat["title_zh"],
            "title_en": cat["title_en"],
            "anchor": cat["anchor"],
            "items": [],
        }
        seen: dict[str, int] = {}
        for idx, item in enumerate(cat["items"], 1):
            base = item["slug"]
            seen[base] = seen.get(base, 0) + 1
            file_slug = base if seen[base] == 1 else f"{base}-{seen[base]}"
            stem = f"{idx:02d}-{file_slug}"
            body_zh = item["body_zh"]
            body_en = en_for(cat["slug"], item["title_zh"], item["kind"], body_zh)
            if body_en.startswith("[EN translation pending"):
                pending.append(f"{cat['slug']}/{stem}")

            (cat_dir / f"{stem}.zh.txt").write_text(body_zh + "\n", encoding="utf-8")
            (cat_dir / f"{stem}.en.txt").write_text(body_en + "\n", encoding="utf-8")
            meta = {
                "id": f"{cat['slug']}/{stem}",
                "category": cat["slug"],
                "title_zh": item["title_zh"],
                "title_en": item["title_en"],
                "kind": item["kind"],
                "chars_zh": len(body_zh),
                "chars_en": len(body_en),
                "files": {"zh": f"{stem}.zh.txt", "en": f"{stem}.en.txt"},
                "queue_ready": item["kind"] in ("text", "json"),
            }
            (cat_dir / f"{stem}.meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            cat_entry["items"].append(meta)
            total_items += 1
            if item["kind"] in ("text", "json"):
                total_prompts += 1

        readme = [
            f"# {cat['title_en']} / {cat['title_zh']}",
            "",
            f"Upstream anchor: `{cat['anchor']}`",
            "",
            "| file | kind | title_en | chars_zh |",
            "|------|------|----------|----------|",
        ]
        for m in cat_entry["items"]:
            readme.append(
                f"| `{m['files']['en']}` | {m['kind']} | {m['title_en']} | {m['chars_zh']} |"
            )
        readme.append("")
        (cat_dir / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
        catalog["categories"].append(cat_entry)

    catalog["stats"] = {
        "categories": len(categories),
        "items_total": total_items,
        "prompts_queueable": total_prompts,
        "pitfalls": total_items - total_prompts,
        "en_pending": pending,
    }
    (OUT / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    index = [
        "# ImageGenSource / PROMPTS",
        "",
        "Industrial prompt library extracted **100%** from",
        "[awesome-gpt-image-2/docs/templates.md](https://github.com/freestylefly/awesome-gpt-image-2/blob/main/docs/templates.md).",
        "",
        "Machine index: [`catalog.json`](./catalog.json)",
        "",
        "## Layout",
        "",
        "```",
        "PROMPTS/",
        "  INDEX.md",
        "  catalog.json",
        "  extract_prompts_v2.py",
        "  _source/templates.md",
        "  01-ui-interfaces/",
        "    01-standard.zh.txt",
        "    01-standard.en.txt",
        "    01-standard.meta.json",
        "    ...",
        "```",
        "",
        "- `*.zh.txt` — verbatim from upstream (Chinese or original EN)",
        "- `*.en.txt` — English fill-in for our queue; slots keep `[brackets]`",
        "- `*.meta.json` — id, kind (`text`|`json`|`pitfalls`), `queue_ready`",
        "",
        "## Categories",
        "",
        "| slug | EN | ZH | items |",
        "|------|----|----|-------|",
    ]
    for c in catalog["categories"]:
        index.append(
            f"| `{c['slug']}` | {c['title_en']} | {c['title_zh']} | {len(c['items'])} |"
        )
    index += [
        "",
        f"**Stats:** {catalog['stats']['categories']} categories · "
        f"{catalog['stats']['items_total']} items · "
        f"{catalog['stats']['prompts_queueable']} queueable · "
        f"{catalog['stats']['pitfalls']} pitfall guides",
        "",
        "## Queue usage",
        "",
        "1. Read `catalog.json`",
        "2. Filter `queue_ready == true`",
        "3. Load `files.en` (or `files.zh`)",
        "4. Fill `[slots]`",
        "5. Real people → image **edit** with reference (Codex gpt-image-2 or xAI `/images/edits`)",
        "",
        "## Re-extract",
        "",
        "```bash",
        "python extract_prompts_v2.py",
        "```",
        "",
    ]
    (OUT / "INDEX.md").write_text("\n".join(index), encoding="utf-8")

    raw = OUT / "_source"
    raw.mkdir(exist_ok=True)
    shutil.copy2(SRC, raw / "templates.md")
    (raw / "SOURCE.txt").write_text(
        "https://github.com/freestylefly/awesome-gpt-image-2/blob/main/docs/templates.md\n",
        encoding="utf-8",
    )
    return catalog


def main() -> None:
    global EN_TABLE
    EN_TABLE = build_en_table()
    md = SRC.read_text(encoding="utf-8")
    cats = parse(md)
    print("parsed categories", len(cats))
    for c in cats:
        print(
            f"  {c['slug']}: {len(c['items'])} —",
            ", ".join(f"{i['slug']}({i['kind']})" for i in c["items"]),
        )
    got = {c["slug"] for c in cats}
    expect = {s for s, *_ in CATEGORIES}
    if got != expect:
        raise SystemExit(f"category mismatch missing={expect-got} extra={got-expect}")

    # expect 中文版 conceptual
    titles = [i["title_zh"] for c in cats for i in c["items"]]
    if "中文版：概念字体海报模板" not in titles:
        raise SystemExit("missing 中文版：概念字体海报模板 — parser incomplete")

    catalog = write_tree(cats)
    print("stats", catalog["stats"])
    if catalog["stats"]["en_pending"]:
        print("EN PENDING:")
        for p in catalog["stats"]["en_pending"]:
            print(" ", p)
    print("OUT", OUT)


if __name__ == "__main__":
    main()
