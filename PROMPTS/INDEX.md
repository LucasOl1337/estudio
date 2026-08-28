# ImageGenSource / PROMPTS

Industrial prompt library extracted **100%** from
[awesome-gpt-image-2/docs/templates.md](https://github.com/freestylefly/awesome-gpt-image-2/blob/main/docs/templates.md).

Machine index: [`catalog.json`](./catalog.json)

## Layout

```
PROMPTS/
  INDEX.md
  catalog.json
  extract_prompts_v2.py
  _source/templates.md
  01-ui-interfaces/
    01-standard.zh.txt
    01-standard.en.txt
    01-standard.meta.json
    ...
```

- `*.zh.txt` — verbatim from upstream (Chinese or original EN)
- `*.en.txt` — English fill-in for our queue; slots keep `[brackets]`
- `*.meta.json` — id, kind (`text`|`json`|`pitfalls`), `queue_ready`

## Categories

| slug | EN | ZH | items |
|------|----|----|-------|
| `01-ui-interfaces` | UI & Interfaces | UI与界面 | 5 |
| `02-charts-infographics` | Charts & Infographics | 图表与信息可视化 | 4 |
| `03-posters-typography` | Posters & Typography | 海报与排版 | 11 |
| `04-products-ecommerce` | Products & E-commerce | 商品与电商 | 4 |
| `05-brand-logos` | Brand & Logos | 品牌与标志 | 7 |
| `06-architecture-space` | Architecture & Spaces | 建筑与空间 | 3 |
| `07-photography-realism` | Photography & Realism | 摄影与写实 | 4 |
| `08-illustration-art` | Illustration & Art | 插画与艺术 | 3 |
| `09-characters-people` | Characters & People | 人物与角色 | 5 |
| `10-scenes-storytelling` | Scenes & Storytelling | 场景与叙事 | 3 |
| `11-history-classical` | History & Classical Themes | 历史与古风题材 | 3 |
| `12-documents-publishing` | Documents & Publishing | 文档与出版物 | 4 |
| `13-other-use-cases` | Other Use Cases | 其他应用场景 | 4 |

**Stats:** 13 categories · 60 items · 47 queueable · 13 pitfall guides

## Queue usage

1. Read `catalog.json`
2. Filter `queue_ready == true`
3. Load `files.en` (or `files.zh`)
4. Fill `[slots]`
5. Real people → image **edit** with reference (Codex gpt-image-2 or xAI `/images/edits`)

## Re-extract

```bash
python extract_prompts_v2.py
```
