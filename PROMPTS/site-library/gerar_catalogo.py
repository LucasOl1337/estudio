"""Gera PROMPTS/site-library/CATALOGO/ a partir de cases.json. Stdlib only."""

from __future__ import annotations

import ast
import html
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

SITE_LIB = Path(__file__).resolve().parent
REPO_ROOT = SITE_LIB.parents[1]
CASES_PATH = SITE_LIB / "cases.json"
TITULOS_PT_PATH = SITE_LIB / "titulos-pt.json"
CATALOGO = SITE_LIB / "CATALOGO"
VENDOR_IMAGES = REPO_ROOT / "vendor" / "awesome-gpt-image-2" / "data" / "images"
TOKENS_PATH = Path(r"C:\Users\user\.claude\skills\asiimov\tokens.css")

CATEGORY_SLUGS = (
    ("UI & Interfaces", "01-ui-interfaces"),
    ("Charts & Infographics", "02-charts-infographics"),
    ("Posters & Typography", "03-posters-typography"),
    ("Products & E-commerce", "04-products-ecommerce"),
    ("Brand & Logos", "05-brand-logos"),
    ("Architecture & Spaces", "06-architecture-space"),
    ("Photography & Realism", "07-photography-realism"),
    ("Illustration & Art", "08-illustration-art"),
    ("Characters & People", "09-characters-people"),
    ("Scenes & Storytelling", "10-scenes-storytelling"),
    ("History & Classical Themes", "11-history-classical"),
    ("Documents & Publishing", "12-documents-publishing"),
    ("Other Use Cases", "13-other-use-cases"),
)
SLUG_BY_CATEGORY = dict(CATEGORY_SLUGS)
MD_IMAGE_PREFIX = "../../../../vendor/awesome-gpt-image-2/data/images/"
HTML_IMAGE_PREFIX = "../../../vendor/awesome-gpt-image-2/data/images/"


def write_text(path: Path, text: str) -> None:
    if not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def parse_maybe_literal(value):
    if isinstance(value, str):
        try:
            return ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return value
    return value


def parse_list(value, *, field: str, case_id: int) -> list[str]:
    parsed = parse_maybe_literal(value)
    if parsed is None:
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    raise SystemExit(f"case {case_id}: {field} nao e lista: {type(parsed).__name__}")


def parse_semantics(value, *, case_id: int) -> dict:
    parsed = parse_maybe_literal(value)
    if not isinstance(parsed, dict):
        raise SystemExit(f"case {case_id}: semantics nao e objeto")
    return parsed


def md_fence(prompt: str) -> str:
    runs = re.findall(r"`+", prompt)
    longest = max((len(run) for run in runs), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}text\n{prompt}\n{ticks}"


def load_cases() -> list[dict]:
    raw = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    records = raw["cases"]
    if len(records) != 517:
        raise SystemExit(f"esperados 517 cases, obtidos {len(records)}")
    titulos_pt = json.loads(TITULOS_PT_PATH.read_text(encoding="utf-8"))
    sem_traducao: list[str] = []
    loaded = []
    for record in records:
        case_id = int(record["id"])
        category = record["category"]
        if category not in SLUG_BY_CATEGORY:
            raise SystemExit(f"categoria desconhecida: {category!r} (case {case_id})")
        styles = parse_list(record.get("styles"), field="styles", case_id=case_id)
        scenes = parse_list(record.get("scenes"), field="scenes", case_id=case_id)
        parse_maybe_literal(record.get("featured"))
        semantics = parse_semantics(record.get("semantics"), case_id=case_id)
        purpose = semantics.get("primary_purpose")
        topology = semantics.get("output_topology")
        if not purpose:
            raise SystemExit(f"case {case_id} sem semantics.primary_purpose")
        if not topology:
            raise SystemExit(f"case {case_id} sem semantics.output_topology")
        image_field = record.get("image") or ""
        basename = Path(image_field).name if image_field else ""
        image_path = VENDOR_IMAGES / basename if basename else None
        has_image = bool(basename) and image_path is not None and image_path.is_file()
        title_zh = record["title"]
        title_pt = titulos_pt.get(title_zh)
        if not title_pt:
            sem_traducao.append(title_zh)
        loaded.append(
            {
                "id": case_id,
                "title": title_pt or title_zh,
                "title_zh": title_zh,
                "category": category,
                "slug": SLUG_BY_CATEGORY[category],
                "styles": styles,
                "scenes": scenes,
                "purpose": str(purpose),
                "topology": str(topology),
                "prompt": record["prompt"],
                "source_label": record.get("sourceLabel") or "",
                "source_url": record.get("sourceUrl") or "",
                "github_url": record.get("githubUrl") or "",
                "basename": basename,
                "has_image": has_image,
            }
        )
    if sem_traducao:
        faltantes = ", ".join(sorted(set(sem_traducao))[:10])
        raise SystemExit(
            f"{len(set(sem_traducao))} titulo(s) sem traducao em titulos-pt.json: {faltantes}"
        )
    loaded.sort(key=lambda item: item["id"])
    ids = [item["id"] for item in loaded]
    if len(set(ids)) != len(ids):
        raise SystemExit("ids duplicados em cases.json")
    return loaded


def render_fonte(case: dict) -> str:
    label = case["source_label"] or "fonte"
    if case["source_url"]:
        fonte = f"[{label}]({case['source_url']})"
    else:
        fonte = label
    parts = [f"Fonte: {fonte}"]
    if case["github_url"]:
        parts.append(f"[case no GitHub]({case['github_url']})")
    return "- " + " · ".join(parts)


def render_styles_scenes(case: dict) -> str | None:
    bits = []
    if case["styles"]:
        bits.append("Styles: " + ", ".join(case["styles"]))
    if case["scenes"]:
        bits.append("Scenes: " + ", ".join(case["scenes"]))
    if not bits:
        return None
    return "- " + " · ".join(bits)


def render_case_md(case: dict) -> str:
    lines = [
        f'<a id="case-{case["id"]}"></a>',
        f'### case-{case["id"]} — {case["title"]}',
        "",
    ]
    if case["has_image"]:
        lines.append(
            f'![case {case["id"]}]({MD_IMAGE_PREFIX}{case["basename"]})'
        )
    else:
        lines.append("(sem imagem local)")
    lines.extend(
        [
            "",
            f'- Propósito: `{case["purpose"]}` · Topologia: `{case["topology"]}`',
            f'- Título original: {case["title_zh"]}',
        ]
    )
    meta = render_styles_scenes(case)
    if meta:
        lines.append(meta)
    lines.append(render_fonte(case))
    lines.extend(
        [
            "",
            "<details><summary>Prompt completo</summary>",
            "",
            md_fence(case["prompt"]),
            "",
            "</details>",
        ]
    )
    return "\n".join(lines)


def write_indice(cases: list[dict], by_category: dict, by_purpose: dict, by_topology: dict) -> None:
    lines = [
        "> GERADO por gerar_catalogo.py — não editar à mão.",
        "",
        "# Catálogo da fonte",
        "",
        f"{len(cases)} cases.",
        "",
        "[navegador.html](navegador.html)",
        "",
        "## Categorias",
        "",
        "| Categoria | Cases | Índice |",
        "| --- | ---: | --- |",
    ]
    for name, slug in CATEGORY_SLUGS:
        n = len(by_category[slug])
        lines.append(f"| {name} | {n} | [{slug}/INDEX.md]({slug}/INDEX.md) |")
    lines.extend(
        [
            "",
            "## Propósitos",
            "",
            "| Propósito | Cases | Índice |",
            "| --- | ---: | --- |",
        ]
    )
    for purpose in sorted(by_purpose):
        n = len(by_purpose[purpose])
        lines.append(
            f"| `{purpose}` | {n} | [POR-PROPOSITO/{purpose}.md](POR-PROPOSITO/{purpose}.md) |"
        )
    lines.extend(
        [
            "",
            "## Topologias",
            "",
            "| Topologia | Cases |",
            "| --- | ---: |",
        ]
    )
    for topology in sorted(by_topology):
        lines.append(f"| `{topology}` | {len(by_topology[topology])} |")
    lines.append("")
    write_text(CATALOGO / "00-INDICE.md", "\n".join(lines))


def write_category_indexes(by_category: dict) -> None:
    name_by_slug = {slug: name for name, slug in CATEGORY_SLUGS}
    for slug, group in by_category.items():
        name = name_by_slug[slug]
        blocks = [render_case_md(case) for case in group]
        body = "\n\n".join(blocks)
        text = (
            f"# {name}\n\n"
            f"{len(group)} cases. [Índice](../00-INDICE.md)\n\n"
            f"{body}\n"
        )
        write_text(CATALOGO / slug / "INDEX.md", text)


def write_purpose_indexes(by_purpose: dict) -> None:
    for purpose, group in by_purpose.items():
        lines = [
            f"# {purpose}",
            "",
            f"{len(group)} cases. [Índice](../00-INDICE.md)",
            "",
        ]
        for case in group:
            lines.append(
                f'- [case-{case["id"]}](../{case["slug"]}/INDEX.md#case-{case["id"]})'
                f' — {case["title"]} — {case["category"]}'
            )
        lines.append("")
        write_text(CATALOGO / "POR-PROPOSITO" / f"{purpose}.md", "\n".join(lines))


def option_html(value: str, label: str) -> str:
    return (
        f'<option value="{html.escape(value, quote=True)}">'
        f"{html.escape(label)}</option>"
    )


def build_navegador(cases: list[dict], purposes: list[str], topologies: list[str]) -> str:
    tokens = TOKENS_PATH.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    payload = []
    for case in cases:
        payload.append(
            {
                "id": case["id"],
                "title": case["title"],
                "titleZh": case["title_zh"],
                "categoria": case["category"],
                "purpose": case["purpose"],
                "topology": case["topology"],
                "styles": case["styles"],
                "scenes": case["scenes"],
                "prompt": case["prompt"],
                "image": HTML_IMAGE_PREFIX + case["basename"],
                "sourceUrl": case["source_url"],
                "sourceLabel": case["source_label"],
            }
        )
    data_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    data_json = data_json.replace("<", r"\u003c")
    cat_options = "\n".join(
        option_html(name, name) for name, _slug in CATEGORY_SLUGS
    )
    purpose_options = "\n".join(option_html(p, p) for p in purposes)
    topology_options = "\n".join(option_html(t, t) for t in topologies)
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ImageGenSource — Catálogo da fonte</title>
<style>
{tokens}

*, *::before, *::after {{ box-sizing: border-box; }}
html, body {{ margin: 0; }}
body {{
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}}
.bar {{
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: calc(var(--asi-space) * 2);
  padding: calc(var(--asi-space) * 2) calc(var(--asi-space) * 3);
  border-bottom: var(--asi-rule) solid var(--asi-border);
  background: var(--asi-surface-1);
}}
.bar h1 {{
  margin: 0;
  font-family: var(--asi-font-display);
  font-size: 1.375rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}}
.count {{
  font-variant-numeric: tabular-nums;
  color: var(--asi-ink-2);
  white-space: nowrap;
}}
.filters {{
  display: flex;
  flex-wrap: wrap;
  gap: var(--asi-space);
  align-items: flex-end;
  padding: calc(var(--asi-space) * 2) calc(var(--asi-space) * 3);
  border-bottom: var(--asi-rule) solid var(--asi-border);
  background: var(--asi-bg);
}}
.filters label {{
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 0.75rem;
  color: var(--asi-ink-2);
}}
.filters select,
.filters input[type="search"] {{
  font-family: var(--asi-font-body);
  font-size: 0.875rem;
  color: var(--asi-ink);
  background: var(--asi-field);
  border: var(--asi-rule) solid var(--asi-border);
  border-radius: var(--asi-radius);
  padding: 6px 8px;
  min-width: 12rem;
}}
.filters select.is-active {{
  background: var(--asi-accent);
  color: var(--asi-graphite);
  border-color: var(--asi-accent);
}}
#btn-clear {{
  font-family: var(--asi-font-body);
  font-size: 0.875rem;
  color: var(--asi-ink);
  background: var(--asi-surface-1);
  border: var(--asi-rule) solid var(--asi-border);
  border-radius: var(--asi-radius);
  padding: 6px 12px;
  cursor: pointer;
}}
#btn-clear:hover {{
  border-color: var(--asi-accent);
  background: var(--asi-accent-wash);
  color: var(--asi-ink);
}}
.grid {{
  flex: 1;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: calc(var(--asi-space) * 2);
  padding: calc(var(--asi-space) * 3);
}}
.card {{
  display: flex;
  flex-direction: column;
  background: var(--asi-surface-1);
  border: var(--asi-rule) solid var(--asi-border);
  border-radius: var(--asi-radius);
  cursor: pointer;
  overflow: hidden;
  text-align: left;
  font: inherit;
  color: inherit;
  padding: 0;
}}
.card:hover {{
  background: var(--asi-accent-wash-strong);
  border-color: var(--asi-accent);
}}
.thumb,
.noimg {{
  width: 100%;
  aspect-ratio: 1;
  background: var(--asi-surface-2);
}}
.thumb {{
  object-fit: cover;
  display: block;
}}
.noimg {{
  display: none;
  align-items: center;
  justify-content: center;
  color: var(--asi-ink-3);
  font-size: 0.8125rem;
}}
.card-body {{
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--asi-space);
}}
.card-id {{
  font-family: var(--asi-font-mono);
  font-size: 0.75rem;
  color: var(--asi-ink-3);
}}
.card-title {{
  font-size: 0.875rem;
  color: var(--asi-ink);
}}
.tag {{
  display: inline-block;
  align-self: flex-start;
  border: var(--asi-rule) solid var(--asi-border);
  background: var(--asi-surface-3);
  color: var(--asi-ink-2);
  border-radius: var(--asi-radius);
  padding: 2px 6px;
  font-size: 0.6875rem;
}}
.empty {{
  grid-column: 1 / -1;
  color: var(--asi-ink-2);
}}
.empty button {{
  font-family: var(--asi-font-body);
  color: var(--asi-accent-ink);
  background: transparent;
  border: 0;
  padding: 0;
  cursor: pointer;
  text-decoration: underline;
}}
.modal-root {{
  position: fixed;
  inset: 0;
  display: none;
  align-items: center;
  justify-content: center;
  padding: calc(var(--asi-space) * 3);
  background: color-mix(in srgb, var(--asi-graphite) 55%, transparent);
  z-index: 10;
}}
.modal-root.open {{ display: flex; }}
.modal {{
  width: min(52rem, 100%);
  max-height: calc(100vh - 48px);
  overflow: auto;
  background: var(--asi-surface-3);
  border: var(--asi-rule) solid var(--asi-border-strong);
  border-radius: var(--asi-radius);
  padding: calc(var(--asi-space) * 3);
}}
.modal-head {{
  display: flex;
  justify-content: space-between;
  gap: var(--asi-space);
  align-items: flex-start;
}}
.modal h2 {{
  margin: 0;
  font-family: var(--asi-font-display);
  letter-spacing: 0.02em;
  text-transform: uppercase;
  font-size: 1.25rem;
}}
#btn-close {{
  font-family: var(--asi-font-body);
  font-size: 1rem;
  color: var(--asi-ink);
  background: var(--asi-surface-1);
  border: var(--asi-rule) solid var(--asi-border);
  border-radius: var(--asi-radius);
  width: 2rem;
  height: 2rem;
  cursor: pointer;
}}
.modal img {{
  max-width: 100%;
  height: auto;
  display: block;
  margin: calc(var(--asi-space) * 2) 0;
  border: var(--asi-rule) solid var(--asi-border);
  border-radius: var(--asi-radius);
}}
.modal .noimg {{
  aspect-ratio: auto;
  min-height: 4rem;
  margin: calc(var(--asi-space) * 2) 0;
}}
.facts {{
  margin: 0 0 calc(var(--asi-space) * 2);
  padding: 0;
  list-style: none;
  color: var(--asi-ink-2);
  font-size: 0.875rem;
}}
.modal pre {{
  font-family: var(--asi-font-mono);
  font-size: 0.8125rem;
  background: var(--asi-surface-1);
  border: var(--asi-rule) solid var(--asi-border);
  border-radius: var(--asi-radius);
  padding: var(--asi-space);
  max-height: 16rem;
  overflow: auto;
  white-space: pre-wrap;
}}
#btn-copy {{
  font-family: var(--asi-font-body);
  font-size: 0.875rem;
  background: var(--asi-accent);
  color: var(--asi-graphite);
  border: var(--asi-rule) solid var(--asi-accent);
  border-radius: var(--asi-radius);
  padding: 8px 12px;
  cursor: pointer;
  margin-top: var(--asi-space);
}}
.modal a {{ color: var(--asi-accent-ink); }}
footer {{
  border-top: var(--asi-rule) solid var(--asi-border);
  padding: var(--asi-space) calc(var(--asi-space) * 3);
  color: var(--asi-ink-3);
  font-size: 0.75rem;
}}
</style>
</head>
<body>
<header class="bar">
  <h1>ImageGenSource — Catálogo da fonte</h1>
  <p class="count"><span id="visible-count">0</span> / <span id="total-count">0</span></p>
</header>
<section class="filters">
  <label>Categoria
    <select id="filter-category">
      <option value="">Todas</option>
      {cat_options}
    </select>
  </label>
  <label>Propósito
    <select id="filter-purpose">
      <option value="">Todos</option>
      {purpose_options}
    </select>
  </label>
  <label>Topologia
    <select id="filter-topology">
      <option value="">Todas</option>
      {topology_options}
    </select>
  </label>
  <label>Busca
    <input id="filter-query" type="search" placeholder="título ou prompt">
  </label>
  <button type="button" id="btn-clear">Limpar filtros</button>
</section>
<main id="grid" class="grid"></main>
<div id="modal-root" class="modal-root">
  <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
    <div class="modal-head">
      <h2 id="modal-title"></h2>
      <button type="button" id="btn-close" aria-label="Fechar">×</button>
    </div>
    <img id="modal-image" alt="">
    <div id="modal-noimg" class="noimg">sem imagem</div>
    <ul class="facts" id="modal-facts"></ul>
    <pre id="modal-prompt"></pre>
    <button type="button" id="btn-copy">Copiar prompt</button>
    <p id="modal-source"></p>
  </div>
</div>
<footer>Gerado por gerar_catalogo.py — fonte: cases.json (517 cases)</footer>
<script type="application/json" id="catalog-data">{data_json}</script>
<script>
(function () {{
  const CASES = JSON.parse(document.getElementById("catalog-data").textContent);
  const grid = document.getElementById("grid");
  const visibleCount = document.getElementById("visible-count");
  const totalCount = document.getElementById("total-count");
  const filterCategory = document.getElementById("filter-category");
  const filterPurpose = document.getElementById("filter-purpose");
  const filterTopology = document.getElementById("filter-topology");
  const filterQuery = document.getElementById("filter-query");
  const btnClear = document.getElementById("btn-clear");
  const modalRoot = document.getElementById("modal-root");
  const modalTitle = document.getElementById("modal-title");
  const modalImage = document.getElementById("modal-image");
  const modalNoimg = document.getElementById("modal-noimg");
  const modalFacts = document.getElementById("modal-facts");
  const modalPrompt = document.getElementById("modal-prompt");
  const modalSource = document.getElementById("modal-source");
  const btnCopy = document.getElementById("btn-copy");
  const btnClose = document.getElementById("btn-close");
  let currentPrompt = "";

  totalCount.textContent = String(CASES.length);

  function markActive(select) {{
    if (select.value) select.classList.add("is-active");
    else select.classList.remove("is-active");
  }}

  function matches(item) {{
    if (filterCategory.value && item.categoria !== filterCategory.value) return false;
    if (filterPurpose.value && item.purpose !== filterPurpose.value) return false;
    if (filterTopology.value && item.topology !== filterTopology.value) return false;
    const q = filterQuery.value.trim().toLowerCase();
    if (q) {{
      const hay = (item.title + "\\n" + item.titleZh + "\\n" + item.prompt).toLowerCase();
      if (!hay.includes(q)) return false;
    }}
    return true;
  }}

  function hideBrokenImage(img, fallback) {{
    img.addEventListener("error", function () {{
      img.style.display = "none";
      fallback.style.display = "flex";
    }});
  }}

  function openModal(item) {{
    modalTitle.textContent = "case-" + item.id + " — " + item.title;
    currentPrompt = item.prompt;
    modalPrompt.textContent = item.prompt;
    modalImage.alt = "case " + item.id;
    modalImage.src = item.image;
    modalImage.style.display = "block";
    modalNoimg.style.display = "none";
    hideBrokenImage(modalImage, modalNoimg);
    const facts = [
      "id: case-" + item.id,
      "título original: " + item.titleZh,
      "categoria: " + item.categoria,
      "propósito: " + item.purpose,
      "topologia: " + item.topology,
      "styles: " + (item.styles.length ? item.styles.join(", ") : "—"),
      "scenes: " + (item.scenes.length ? item.scenes.join(", ") : "—")
    ];
    modalFacts.replaceChildren();
    facts.forEach(function (line) {{
      const li = document.createElement("li");
      li.textContent = line;
      modalFacts.appendChild(li);
    }});
    modalSource.replaceChildren();
    if (item.sourceUrl) {{
      const a = document.createElement("a");
      a.href = item.sourceUrl;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.textContent = item.sourceLabel || "fonte";
      modalSource.appendChild(a);
    }} else if (item.sourceLabel) {{
      modalSource.textContent = item.sourceLabel;
    }}
    btnCopy.textContent = "Copiar prompt";
    modalRoot.classList.add("open");
  }}

  function closeModal() {{
    modalRoot.classList.remove("open");
  }}

  function render() {{
    markActive(filterCategory);
    markActive(filterPurpose);
    markActive(filterTopology);
    const visible = CASES.filter(matches);
    visibleCount.textContent = String(visible.length);
    grid.replaceChildren();
    if (!visible.length) {{
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.append("Nenhum case corresponde aos filtros. ");
      const again = document.createElement("button");
      again.type = "button";
      again.textContent = "Limpar filtros";
      again.addEventListener("click", clearFilters);
      empty.appendChild(again);
      grid.appendChild(empty);
      return;
    }}
    visible.forEach(function (item) {{
      const card = document.createElement("button");
      card.type = "button";
      card.className = "card";
      const img = document.createElement("img");
      img.className = "thumb";
      img.loading = "lazy";
      img.alt = "case " + item.id;
      img.src = item.image;
      const noimg = document.createElement("div");
      noimg.className = "noimg";
      noimg.textContent = "sem imagem";
      hideBrokenImage(img, noimg);
      const body = document.createElement("div");
      body.className = "card-body";
      const idEl = document.createElement("span");
      idEl.className = "card-id";
      idEl.textContent = "case-" + item.id;
      const titleEl = document.createElement("span");
      titleEl.className = "card-title";
      titleEl.textContent = item.title;
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = item.categoria;
      body.append(idEl, titleEl, tag);
      card.append(img, noimg, body);
      card.addEventListener("click", function () {{ openModal(item); }});
      grid.appendChild(card);
    }});
  }}

  function clearFilters() {{
    filterCategory.value = "";
    filterPurpose.value = "";
    filterTopology.value = "";
    filterQuery.value = "";
    render();
  }}

  function copyPrompt() {{
    const done = function () {{ btnCopy.textContent = "Copiado"; }};
    const fallback = function () {{
      const range = document.createRange();
      range.selectNodeContents(modalPrompt);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
      try {{ document.execCommand("copy"); done(); }} catch (err) {{}}
    }};
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(currentPrompt).then(done).catch(fallback);
    }} else {{
      fallback();
    }}
  }}

  filterCategory.addEventListener("change", render);
  filterPurpose.addEventListener("change", render);
  filterTopology.addEventListener("change", render);
  filterQuery.addEventListener("input", render);
  btnClear.addEventListener("click", clearFilters);
  btnCopy.addEventListener("click", copyPrompt);
  btnClose.addEventListener("click", closeModal);
  modalRoot.addEventListener("click", function (event) {{
    if (event.target === modalRoot) closeModal();
  }});
  document.addEventListener("keydown", function (event) {{
    if (event.key === "Escape") closeModal();
  }});
  render();
}})();
</script>
</body>
</html>
"""


def print_summary(cases: list[dict], by_category: dict, by_purpose: dict, missing: list[dict]) -> None:
    name_by_slug = {slug: name for name, slug in CATEGORY_SLUGS}
    print(f"cases: {len(cases)}")
    print("por categoria:")
    for _name, slug in CATEGORY_SLUGS:
        print(f"  {name_by_slug[slug]}: {len(by_category[slug])}")
    print("por proposito:")
    for purpose in sorted(by_purpose):
        print(f"  {purpose}: {len(by_purpose[purpose])}")
    print(f"imagens faltantes: {len(missing)}")
    for case in missing:
        print(f"  case-{case['id']}: {case['basename'] or '(sem campo image)'}")


def main() -> None:
    if not TOKENS_PATH.is_file():
        raise SystemExit(f"tokens.css ausente: {TOKENS_PATH}")
    cases = load_cases()
    by_category = defaultdict(list)
    by_purpose = defaultdict(list)
    by_topology = defaultdict(list)
    for case in cases:
        by_category[case["slug"]].append(case)
        by_purpose[case["purpose"]].append(case)
        by_topology[case["topology"]].append(case)
    if len(by_category) != 13:
        raise SystemExit(f"esperadas 13 categorias, obtidas {len(by_category)}")
    if len(by_purpose) != 17:
        raise SystemExit(
            f"esperados 17 propositos, obtidos {len(by_purpose)}: {sorted(by_purpose)}"
        )
    if len(by_topology) != 6:
        raise SystemExit(
            f"esperadas 6 topologias, obtidas {len(by_topology)}: {sorted(by_topology)}"
        )
    cat_sum = sum(len(group) for group in by_category.values())
    if cat_sum != 517:
        raise SystemExit(f"soma por categoria {cat_sum} != 517")
    missing = [case for case in cases if not case["has_image"]]
    if CATALOGO.exists():
        shutil.rmtree(CATALOGO)
    CATALOGO.mkdir(parents=True)
    write_indice(cases, by_category, by_purpose, by_topology)
    write_category_indexes(by_category)
    write_purpose_indexes(by_purpose)
    write_text(
        CATALOGO / "navegador.html",
        build_navegador(cases, sorted(by_purpose), sorted(by_topology)),
    )
    print_summary(cases, by_category, by_purpose, missing)


if __name__ == "__main__":
    main()
