use std::path::{Path, PathBuf};

pub fn detect_root() -> PathBuf {
    let mut candidates = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.clone());
        candidates.extend(cwd.ancestors().map(|p| p.to_path_buf()));
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.to_path_buf());
            candidates.extend(dir.ancestors().map(|p| p.to_path_buf()));
        }
    }
    candidates.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")));
    candidates.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."));
    for raw in candidates {
        let path = raw.canonicalize().unwrap_or(raw);
        if is_repo_root(&path) {
            return path;
        }
    }
    panic!("ImageGenSource root not found. Run from the repo or set IMAGEGEN_ROOT.");
}

pub fn is_repo_root(path: &Path) -> bool {
    path.join("ALVOS").is_dir()
        && path
            .join("skills/imageproductionfactory/scripts/image_production_factory.py")
            .is_file()
        && path.join("PROMPTS/site-library/cases.json").is_file()
}

pub fn factory_script(root: &Path) -> PathBuf {
    root.join("skills/imageproductionfactory/scripts/image_production_factory.py")
}

pub fn alvos_dir(root: &Path) -> PathBuf {
    root.join("ALVOS")
}

pub fn resolve_python() -> PathBuf {
    if let Ok(custom) = std::env::var("FACTORY_PYTHON") {
        return PathBuf::from(custom);
    }
    let hermes = PathBuf::from(r"C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe");
    if hermes.is_file() {
        return hermes;
    }
    PathBuf::from("python")
}
