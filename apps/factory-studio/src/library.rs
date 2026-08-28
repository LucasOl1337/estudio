use serde::Serialize;
use serde_json::Value;
use std::collections::HashMap;
use std::path::Path;

#[derive(Clone, Serialize)]
pub struct Purpose {
    pub id: String,
    pub label_pt: String,
    pub count: usize,
}

#[derive(Clone, Serialize)]
pub struct Category {
    pub name: String,
    pub count: usize,
}

#[derive(Clone, Serialize)]
pub struct Case {
    pub id: i64,
    pub title_pt: String,
    pub category: String,
    pub purpose: String,
    pub has_thumb: bool,
}

#[derive(Clone, Serialize)]
pub struct Template {
    pub id: String,
    pub category: String,
    pub title: String,
}

#[derive(Clone, Serialize)]
pub struct Library {
    pub purposes: Vec<Purpose>,
    pub categories: Vec<Category>,
    pub cases: Vec<Case>,
    pub templates: Vec<Template>,
}

pub fn load_library(root: &Path) -> Library {
    let site = root.join("PROMPTS/site-library");
    let cases_json: Value = read_json(&site.join("cases.json"));
    let titles: HashMap<String, String> = read_json(&site.join("titulos-pt.json"));
    let taxonomy: Value = read_json(&site.join("taxonomy.json"));
    let purpose_index: Value = read_json(&site.join("purpose-index.json"));
    let catalog: Value = read_json(&root.join("PROMPTS/catalog.json"));

    let mut purpose_of: HashMap<i64, String> = HashMap::new();
    if let Some(purposes) = purpose_index.get("purposes").and_then(|v| v.as_object()) {
        for (pid, payload) in purposes {
            if let Some(ids) = payload.get("case_ids").and_then(|v| v.as_array()) {
                for id in ids {
                    if let Some(n) = id.as_i64() {
                        purpose_of.entry(n).or_insert_with(|| pid.clone());
                    }
                }
            }
        }
    }

    let thumbs = root.join("vendor/awesome-gpt-image-2/data/images");
    let mut cases = Vec::new();
    let mut cat_count: HashMap<String, usize> = HashMap::new();
    let mut purpose_count: HashMap<String, usize> = HashMap::new();
    if let Some(arr) = cases_json.get("cases").and_then(|v| v.as_array()) {
        for item in arr {
            let id = item.get("id").and_then(|v| v.as_i64()).unwrap_or(0);
            let zh = item.get("title").and_then(|v| v.as_str()).unwrap_or("");
            let category = item
                .get("category")
                .and_then(|v| v.as_str())
                .unwrap_or("Other")
                .to_string();
            let purpose = purpose_of
                .get(&id)
                .cloned()
                .or_else(|| {
                    item.pointer("/semantics/primary_purpose")
                        .and_then(|v| v.as_str())
                        .map(|s| s.to_string())
                })
                .unwrap_or_else(|| "other".into());
            let title_pt = titles.get(zh).cloned().unwrap_or_else(|| zh.to_string());
            let has_thumb = thumbs.join(format!("case{id}.jpg")).is_file();
            *cat_count.entry(category.clone()).or_insert(0) += 1;
            *purpose_count.entry(purpose.clone()).or_insert(0) += 1;
            cases.push(Case {
                id,
                title_pt,
                category,
                purpose,
                has_thumb,
            });
        }
    }
    cases.sort_by_key(|c| c.id);

    let mut purposes = Vec::new();
    if let Some(arr) = taxonomy.get("purposes").and_then(|v| v.as_array()) {
        for item in arr {
            let id = item.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string();
            if id.is_empty() {
                continue;
            }
            purposes.push(Purpose {
                count: *purpose_count.get(&id).unwrap_or(&0),
                label_pt: item
                    .get("label_pt")
                    .and_then(|v| v.as_str())
                    .unwrap_or(&id)
                    .to_string(),
                id,
            });
        }
    }

    let mut categories: Vec<Category> = cat_count
        .into_iter()
        .map(|(name, count)| Category { name, count })
        .collect();
    categories.sort_by(|a, b| a.name.cmp(&b.name));

    let mut templates = Vec::new();
    if let Some(cats) = catalog.get("categories").and_then(|v| v.as_array()) {
        for cat in cats {
            let slug = cat.get("slug").and_then(|v| v.as_str()).unwrap_or("");
            if let Some(items) = cat.get("items").and_then(|v| v.as_array()) {
                for item in items {
                    if item.get("queue_ready").and_then(|v| v.as_bool()) != Some(true) {
                        continue;
                    }
                    templates.push(Template {
                        id: item.get("id").and_then(|v| v.as_str()).unwrap_or("").into(),
                        category: slug.to_string(),
                        title: item
                            .get("title_en")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string(),
                    });
                }
            }
        }
    }

    Library {
        purposes,
        categories,
        cases,
        templates,
    }
}

fn read_json<T: serde::de::DeserializeOwned>(path: &Path) -> T {
    let text = std::fs::read_to_string(path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("parse {}: {e}", path.display()))
}
