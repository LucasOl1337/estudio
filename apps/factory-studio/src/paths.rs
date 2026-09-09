use std::ffi::OsString;
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
    path.join("ALVOS").is_dir() && path.join("PROMPTS/site-library/cases.json").is_file()
}

fn skills_root_from(
    repo: Option<OsString>,
    root: Option<OsString>,
    home: Option<OsString>,
) -> PathBuf {
    if let Some(value) = repo {
        return PathBuf::from(value).join("skills");
    }
    if let Some(value) = root {
        return PathBuf::from(value);
    }
    PathBuf::from(home.unwrap_or_else(|| OsString::from("."))).join(".agents/skills")
}

pub fn factory_script(_root: &Path) -> PathBuf {
    let skills_root = skills_root_from(
        std::env::var_os("LUCASOL_SKILLS_REPO"),
        std::env::var_os("LUCASOL_SKILLS_ROOT"),
        std::env::var_os("USERPROFILE").or_else(|| std::env::var_os("HOME")),
    );
    skills_root.join("imageproductionfactory/scripts/image_production_factory.py")
}

pub fn alvos_dir(root: &Path) -> PathBuf {
    root.join("ALVOS")
}

pub fn resolve_python() -> PathBuf {
    if let Ok(custom) = std::env::var("FACTORY_PYTHON") {
        return PathBuf::from(custom);
    }
    let hermes =
        PathBuf::from(r"C:\Users\user\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe");
    if hermes.is_file() {
        return hermes;
    }
    PathBuf::from("python")
}

#[cfg(test)]
mod tests {
    use super::skills_root_from;
    use std::{ffi::OsString, path::PathBuf};

    #[test]
    fn prefere_o_repositorio_canonico() {
        assert_eq!(
            skills_root_from(
                Some(OsString::from("/hub")),
                Some(OsString::from("/installed")),
                Some(OsString::from("/home"))
            ),
            PathBuf::from("/hub/skills")
        );
    }

    #[test]
    fn cai_no_hub_instalado() {
        assert_eq!(
            skills_root_from(None, None, Some(OsString::from("/home"))),
            PathBuf::from("/home/.agents/skills")
        );
    }
}
