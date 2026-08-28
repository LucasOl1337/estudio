# Purpose-first GPT-Image2 Library

Complete local index of **517 site cases**, **22 upstream templates**, **19 style tags**, **10 scene tags**, **47 queue templates**, and **17 user-purpose categories**.

Raw site cases are inspiration only. Runtime prompts must be recomposed from a reviewed intent and one item-specific creative plan.

## Purpose categories

| purpose | Portuguese label | cases | templates | default topology |
|---|---|---:|---:|---|
| `profile-portrait` | Retrato de perfil | 4 | 3 | single-frame |
| `editorial-portrait` | Retrato editorial criativo | 68 | 3 | single-frame |
| `lifestyle-photography` | Fotografia lifestyle e documental | 66 | 5 | single-frame |
| `product-hero` | Foto hero de produto | 8 | 6 | single-frame |
| `product-commerce` | Comércio e apresentação de produto | 37 | 3 | single-frame, multi-panel, document-page |
| `campaign-key-visual` | Campanha e peça principal | 86 | 21 | poster-canvas, single-frame |
| `social-cover` | Capa e conteúdo social | 52 | 14 | poster-canvas, ui-screen |
| `interface-design` | Interface e mockup de produto | 64 | 4 | ui-screen |
| `information-explainer` | Explicação visual e infográfico | 53 | 3 | multi-panel, document-page |
| `brand-system` | Sistema de marca | 28 | 6 | multi-panel, document-page, single-frame |
| `publishing-layout` | Publicação e documento | 10 | 3 | document-page, multi-panel |
| `character-development` | Desenvolvimento de personagem | 26 | 4 | multi-panel, single-frame |
| `narrative-scene` | Cena narrativa | 25 | 7 | single-frame, sequence, multi-panel |
| `space-visualization` | Visualização de espaço | 19 | 2 | single-frame, document-page |
| `artistic-exploration` | Exploração artística | 55 | 2 | single-frame, poster-canvas |
| `historical-cultural` | Tema histórico e cultural | 16 | 2 | single-frame, sequence, poster-canvas |
| `concept-development` | Desenvolvimento de conceito | 30 | 6 | multi-panel, document-page |

## Query

```powershell
python .\tools\prompt_library.py search --library .\site-library --query "retratos criativos" --purpose editorial-portrait --topology single-frame --target-kind person --limit 8
```

Use `--include-prompt` only when adapting selected references; it can print long attributed source prompts.
