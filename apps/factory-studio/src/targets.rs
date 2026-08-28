use serde::Serialize;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use walkdir::WalkDir;

const IMAGE_EXTS: &[&str] = &["png", "jpg", "jpeg", "webp", "gif"];
const SKIP_DIRS: &[&str] = &[
    "producoes",
    "prompts",
    "fila_grok",
    "fila_codex",
    "saidas_perfil",
    "saidas_codex",
    "teste_templates",
    "vendor",
    "node_modules",
    ".git",
    "arquivo",
    "_arquivo",
];

#[derive(Serialize)]
pub struct Photo {
    pub rel: String,
    pub bytes: u64,
}

#[derive(Serialize)]
pub struct RunInfo {
    pub focus: String,
    pub images: usize,
    pub grok: usize,
    pub codex: usize,
    pub missing: usize,
    pub updated: String,
}

#[derive(Serialize)]
pub struct Target {
    pub name: String,
    pub photos: Vec<Photo>,
    pub runs: Vec<RunInfo>,
}

pub fn list_targets(root: &Path) -> Vec<Target> {
    let alvos = root.join("ALVOS");
    let mut out = Vec::new();
    let Ok(entries) = fs::read_dir(&alvos) else {
        return out;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let name = entry.file_name().to_string_lossy().to_string();
        if name.eq_ignore_ascii_case("prompts") {
            continue;
        }
        out.push(read_target(&path, &name));
    }
    out.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase()));
    out
}

fn read_target(dir: &Path, name: &str) -> Target {
    Target {
        name: name.to_string(),
        photos: discover_photos(dir),
        runs: list_runs(dir),
    }
}

pub fn discover_photos(target: &Path) -> Vec<Photo> {
    let mut photos = Vec::new();
    for entry in WalkDir::new(target).into_iter().filter_map(|e| e.ok()) {
        let path = entry.path();
        if !path.is_file() {
            continue;
        }
        if !is_ref_image(path, target) || !is_decodable_image(path) {
            continue;
        }
        let rel = path
            .strip_prefix(target)
            .unwrap_or(path)
            .to_string_lossy()
            .replace('\\', "/");
        let bytes = path.metadata().map(|m| m.len()).unwrap_or(0);
        photos.push(Photo { rel, bytes });
    }
    photos.sort_by(|a, b| a.rel.cmp(&b.rel));
    photos
}

fn is_ref_image(path: &Path, target: &Path) -> bool {
    let ext = path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    if !IMAGE_EXTS.contains(&ext.as_str()) {
        return false;
    }
    let Ok(rel) = path.strip_prefix(target) else {
        return false;
    };
    rel.components().any(|c| {
        SKIP_DIRS
            .iter()
            .any(|skip| c.as_os_str().to_string_lossy().eq_ignore_ascii_case(skip))
    }) == false
}

fn is_decodable_image(path: &Path) -> bool {
    let Ok(mut file) = fs::File::open(path) else {
        return false;
    };
    let mut buf = [0u8; 16];
    let Ok(n) = file.read(&mut buf) else {
        return false;
    };
    if n < 8 {
        return false;
    }
    matches!(&buf[..8], [0x89, b'P', b'N', b'G', ..] | [0xFF, 0xD8, ..] | [b'G', b'I', b'F', b'8', ..])
        || (n >= 12 && &buf[8..12] == b"WEBP")
}

fn list_runs(target: &Path) -> Vec<RunInfo> {
    let prod = target.join("PRODUCOES");
    let mut runs = Vec::new();
    let Ok(entries) = fs::read_dir(&prod) else {
        return runs;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let focus = entry.file_name().to_string_lossy().to_string();
        let mut grok = 0usize;
        let mut codex = 0usize;
        let mut missing = 0usize;
        let mut latest: Option<std::time::SystemTime> = path.metadata().ok().and_then(|m| m.modified().ok());
        for (queue, is_grok) in [("FILA_GROK", true), ("FILA_CODEX", false)] {
            let Ok(files) = fs::read_dir(path.join(queue)) else {
                continue;
            };
            for file in files.flatten() {
                let p = file.path();
                let ext = p
                    .extension()
                    .and_then(|e| e.to_str())
                    .unwrap_or("")
                    .to_ascii_lowercase();
                if !IMAGE_EXTS.contains(&ext.as_str()) {
                    continue;
                }
                if is_decodable_image(&p) {
                    if is_grok {
                        grok += 1;
                    } else {
                        codex += 1;
                    }
                    if let Ok(modified) = p.metadata().and_then(|m| m.modified()) {
                        latest = Some(match latest {
                            Some(prev) => prev.max(modified),
                            None => modified,
                        });
                    }
                } else {
                    missing += 1;
                }
            }
        }
        if grok + codex + missing == 0 {
            continue;
        }
        runs.push(RunInfo {
            focus,
            images: grok + codex,
            grok,
            codex,
            missing,
            updated: format_time(latest),
        });
    }
    runs.sort_by(|a, b| b.updated.cmp(&a.updated).then(b.images.cmp(&a.images)));
    runs
}

fn format_time(ts: Option<std::time::SystemTime>) -> String {
    let Some(ts) = ts else {
        return String::new();
    };
    chrono::DateTime::<chrono::Local>::from(ts)
        .format("%Y-%m-%d %H:%M")
        .to_string()
}

pub fn slug_target(raw: &str) -> Result<String, String> {
    let name: String = raw
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '_' })
        .collect();
    let name = name.trim_matches('_').to_string();
    if name.is_empty() {
        return Err("Nome vazio.".into());
    }
    Ok(name)
}

pub fn create_target(root: &Path, name: &str) -> Result<PathBuf, String> {
    let slug = slug_target(name)?;
    let dir = root.join("ALVOS").join(&slug);
    if dir.exists() {
        return Err(format!("Alvo {slug} já existe."));
    }
    fs::create_dir_all(dir.join(format!("PESSOA_{slug}"))).map_err(|e| e.to_string())?;
    Ok(dir)
}

pub fn save_photos(target: &Path, files: Vec<(String, Vec<u8>)>) -> Result<usize, String> {
    let slug = target
        .file_name()
        .unwrap_or_default()
        .to_string_lossy()
        .to_string();
    let dest = target.join(format!("PESSOA_{slug}"));
    fs::create_dir_all(&dest).map_err(|e| e.to_string())?;
    let mut n = 0;
    for (filename, bytes) in files {
        let safe = PathBuf::from(&filename)
            .file_name()
            .map(|s| s.to_string_lossy().to_string())
            .unwrap_or_else(|| format!("foto-{n}.png"));
        fs::write(dest.join(safe), bytes).map_err(|e| e.to_string())?;
        n += 1;
    }
    Ok(n)
}

pub fn gallery(target: &Path, focus: &str) -> Vec<GalleryItem> {
    let run = target.join("PRODUCOES").join(focus);
    let mut items = Vec::new();
    for (queue, ext) in [("FILA_GROK", "jpg"), ("FILA_CODEX", "png")] {
        let dir = run.join(queue);
        let Ok(files) = fs::read_dir(&dir) else {
            continue;
        };
        for file in files.flatten() {
            let path = file.path();
            if path.extension().and_then(|e| e.to_str()) != Some(ext) {
                continue;
            }
            if !is_decodable_image(&path) {
                continue;
            }
            items.push(GalleryItem {
                file: path.file_name().unwrap().to_string_lossy().to_string(),
                provider: if queue == "FILA_GROK" {
                    "grok"
                } else {
                    "codex"
                }
                .into(),
                url: format!(
                    "/api/media/{}/{}/{}/{}",
                    target.file_name().unwrap().to_string_lossy(),
                    focus,
                    queue,
                    path.file_name().unwrap().to_string_lossy()
                ),
            });
        }
    }
    items.sort_by(|a, b| a.file.cmp(&b.file).then(a.provider.cmp(&b.provider)));
    items
}

#[derive(Serialize)]
pub struct GalleryItem {
    pub file: String,
    pub provider: String,
    pub url: String,
}

pub fn write_gallery_html(
    target: &Path,
    focus: &str,
    cases: &[crate::library::Case],
) -> Result<PathBuf, String> {
    let run = target.join("PRODUCOES").join(focus);
    fs::create_dir_all(&run).map_err(|e| e.to_string())?;
    let mut by_stem: std::collections::BTreeMap<String, (Option<String>, Option<String>)> =
        std::collections::BTreeMap::new();
    for (queue, ext, is_grok) in [("FILA_GROK", "jpg", true), ("FILA_CODEX", "png", false)] {
        let dir = run.join(queue);
        let Ok(files) = fs::read_dir(&dir) else {
            continue;
        };
        for file in files.flatten() {
            let path = file.path();
            if path.extension().and_then(|e| e.to_str()) != Some(ext) {
                continue;
            }
            if !is_decodable_image(&path) {
                continue;
            }
            let name = path.file_name().unwrap().to_string_lossy().to_string();
            let stem = path.file_stem().unwrap().to_string_lossy().to_string();
            let rel = format!("{queue}/{name}");
            let entry = by_stem.entry(stem).or_insert((None, None));
            if is_grok {
                entry.0 = Some(rel);
            } else {
                entry.1 = Some(rel);
            }
        }
    }

    let mut by_id: std::collections::HashMap<i64, &crate::library::Case> = std::collections::HashMap::new();
    for case in cases {
        by_id.insert(case.id, case);
    }

    let mut groups: std::collections::BTreeMap<String, Vec<String>> = std::collections::BTreeMap::new();
    let mut n_img = 0usize;
    for (stem, (grok, codex)) in &by_stem {
        if grok.is_some() {
            n_img += 1;
        }
        if codex.is_some() {
            n_img += 1;
        }
        let id = case_id_from_stem(stem);
        let (cat, title, cid) = if let Some(id) = id {
            if let Some(c) = by_id.get(&id) {
                (c.category.clone(), c.title_pt.clone(), Some(id))
            } else {
                ("Outros".into(), stem.clone(), Some(id))
            }
        } else {
            ("Templates".into(), stem.clone(), None)
        };
        let cid_html = cid
            .map(|n| format!("<span class=\"cid\">{n}</span>"))
            .unwrap_or_default();
        let card = format!(
            "<article class=\"case\"><div class=\"head\">{cid}{title}</div><div class=\"pair\">{g}{c}</div></article>",
            cid = cid_html,
            title = format!("<span class=\"t\">{}</span>", esc(&title)),
            g = pane("Grok", grok.as_deref()),
            c = pane("Codex", codex.as_deref()),
        );
        groups.entry(cat).or_default().push(card);
    }

    let target_name = target.file_name().unwrap().to_string_lossy();
    let mut nav = String::new();
    let mut sections = String::new();
    for (cat, cards) in &groups {
        let slug = slugify(cat);
        nav.push_str(&format!(
            "<a href=\"#{slug}\">{} <b>{}</b></a>",
            esc(cat),
            cards.len()
        ));
        sections.push_str(&format!(
            "<section class=\"cat\" id=\"{slug}\"><h2>{}</h2><p class=\"catdesc\">{} casos</p><div class=\"grid2\">{}</div></section>",
            esc(cat),
            cards.len(),
            cards.join("")
        ));
    }

    let html = format!(
        r#"<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Galeria — {target} / {focus}</title>
<style>
:root {{ --asi-accent:#f0500a; --asi-graphite:#16181a; --asi-bg:#eceded; --asi-surface-1:#e2e3e4; --asi-surface-2:#d3d5d6; --asi-surface-3:#f8f9f9; --asi-ink:#16181a; --asi-ink-2:#45484b; --asi-ink-3:#565a5d; --asi-border:#c3c6c8; --asi-border-strong:#8b8f92; --asi-font-display:"Barlow Condensed","Arial Narrow",sans-serif; --asi-font-body:Inter,"Segoe UI",system-ui,sans-serif; --asi-font-mono:Consolas,monospace; --asi-radius:4px; --asi-radius-lg:8px; }}
@media (prefers-color-scheme: dark) {{ :root {{ --asi-bg:#131417; --asi-surface-1:#1b1c20; --asi-surface-2:#25262b; --asi-surface-3:#2f3036; --asi-ink:#f2f3f3; --asi-ink-2:#c3c6c8; --asi-ink-3:#9ba0a4; --asi-border:#2f3036; --asi-border-strong:#454750; }} }}
* {{ box-sizing:border-box; margin:0; }}
body {{ background:var(--asi-bg); color:var(--asi-ink); font-family:var(--asi-font-body); padding:24px 16px 64px; }}
.wrap {{ max-width:1280px; margin:0 auto; }}
h1 {{ font-family:var(--asi-font-display); text-transform:uppercase; font-size:2rem; }}
h1 .mark {{ background:var(--asi-accent); color:var(--asi-graphite); padding:0 10px; border-radius:var(--asi-radius); }}
.legend {{ display:flex; gap:16px; flex-wrap:wrap; margin-top:10px; color:var(--asi-ink-3); font-size:.85rem; }}
nav.cats {{ position:sticky; top:0; z-index:5; background:var(--asi-bg); border-bottom:1px solid var(--asi-border); padding:8px 0; margin:12px 0; display:flex; gap:6px; flex-wrap:wrap; }}
nav.cats a {{ font-size:.74rem; text-decoration:none; color:var(--asi-ink-2); border:1px solid var(--asi-border); border-radius:var(--asi-radius); padding:2px 8px; background:var(--asi-surface-1); }}
.grid2 {{ display:grid; gap:18px; grid-template-columns:repeat(auto-fill,minmax(520px,1fr)); }}
.case {{ background:var(--asi-surface-3); border:1px solid var(--asi-border); border-radius:var(--asi-radius-lg); overflow:hidden; }}
.case .head {{ padding:10px 12px; display:flex; gap:10px; align-items:baseline; flex-wrap:wrap; }}
.cid {{ font-family:var(--asi-font-mono); font-size:.7rem; background:var(--asi-accent); color:var(--asi-graphite); padding:1px 7px; border-radius:var(--asi-radius); font-weight:700; }}
.t {{ font-weight:600; }}
.pair {{ display:grid; grid-template-columns:1fr 1fr; }}
.pane + .pane {{ border-left:1px solid var(--asi-border); }}
.pane .lbl {{ font-family:var(--asi-font-mono); font-size:.68rem; text-transform:uppercase; padding:5px 10px; background:var(--asi-surface-1); border-bottom:1px solid var(--asi-border); }}
.pane img {{ width:100%; height:340px; object-fit:contain; background:var(--asi-surface-2); display:block; }}
.vazio {{ height:340px; display:grid; place-items:center; background:var(--asi-surface-2); color:var(--asi-ink-3); font-size:.8rem; }}
h2 {{ font-family:var(--asi-font-display); text-transform:uppercase; border-left:4px solid var(--asi-accent); padding-left:10px; margin:28px 0 12px; }}
.catdesc {{ color:var(--asi-ink-3); font-size:.9rem; margin:0 0 12px 14px; }}
@media (max-width:640px) {{ .pair {{ grid-template-columns:1fr; }} }}
</style>
</head>
<body>
<div class="wrap">
<header><h1><span class="mark">Galeria</span> {target} · {focus}</h1>
<div class="legend"><span><b>{cases}</b> casos</span><span><b>{imgs}</b> imagens</span><span>página atualizada a cada nova peça</span></div></header>
<nav class="cats">{nav}</nav>
{sections}
</div>
</body>
</html>
"#,
        target = esc(&target_name),
        focus = esc(focus),
        cases = by_stem.len(),
        imgs = n_img,
        nav = nav,
        sections = sections,
    );

    let out = run.join("GALERIA.html");
    fs::write(&out, html).map_err(|e| e.to_string())?;
    Ok(out)
}

pub fn open_in_browser(path: &Path) -> Result<(), String> {
    std::process::Command::new("cmd")
        .args(["/C", "start", "", &path.display().to_string()])
        .spawn()
        .map(|_| ())
        .map_err(|e| e.to_string())
}

fn pane(label: &str, rel: Option<&str>) -> String {
    match rel {
        Some(rel) => format!(
            "<div class=\"pane\"><div class=\"lbl\">{label}</div><a href=\"{href}\" target=\"_blank\"><img loading=\"lazy\" src=\"{href}\" alt=\"{label}\"></a></div>",
            href = esc(rel)
        ),
        None => format!(
            "<div class=\"pane\"><div class=\"lbl\">{label}</div><div class=\"vazio\">ainda não gerado</div></div>"
        ),
    }
}

fn case_id_from_stem(stem: &str) -> Option<i64> {
    let rest = stem.strip_prefix("case-")?;
    let digits: String = rest.chars().take_while(|c| c.is_ascii_digit()).collect();
    digits.parse().ok()
}

fn slugify(value: &str) -> String {
    let s: String = value
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() {
                c.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect();
    s.trim_matches('-').to_string()
}

fn esc(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}
