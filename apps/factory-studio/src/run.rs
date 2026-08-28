use crate::paths::{factory_script, resolve_python};
use serde::Deserialize;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::{broadcast, Mutex};

#[derive(Clone, Deserialize)]
pub struct RunRequest {
    pub target: String,
    pub mode: String,
    pub focus: String,
    pub providers: String,
    pub copy_language: String,
    pub dry_run: bool,
    pub case_ids: Vec<i64>,
}

pub struct RunHandle {
    pub child: Mutex<Option<Child>>,
    pub pid: Mutex<Option<u32>>,
    pub log: broadcast::Sender<String>,
    pub status: Mutex<RunStatus>,
}

#[derive(Clone, Default, serde::Serialize)]
pub struct RunStatus {
    pub running: bool,
    pub dry_run: bool,
    pub command: String,
    pub target: String,
    pub focus: String,
    pub started_at: String,
    pub pid: Option<u32>,
}

impl RunHandle {
    pub fn new() -> Arc<Self> {
        let (log, _) = broadcast::channel(512);
        Arc::new(Self {
            child: Mutex::new(None),
            pid: Mutex::new(None),
            log,
            status: Mutex::new(RunStatus::default()),
        })
    }
}

pub async fn start_run(
    root: PathBuf,
    req: RunRequest,
    handle: Arc<RunHandle>,
) -> Result<(), String> {
    {
        let status = handle.status.lock().await;
        if status.running {
            return Err("Já existe uma corrida no ar.".into());
        }
    }
    if req.target.trim().is_empty() {
        return Err("Escolha um alvo.".into());
    }
    let focus = if req.focus.trim().is_empty() {
        "estudio-v1".into()
    } else {
        slug(&req.focus)
    };
    let providers = match req.providers.as_str() {
        "grok" | "codex" | "both" => req.providers.clone(),
        _ => "codex".into(),
    };
    let python = resolve_python();
    let script = factory_script(&root);
    let mut args = vec![
        "-u".to_string(),
        script.to_string_lossy().to_string(),
        req.mode.clone(),
        "--target".into(),
        req.target.clone(),
        "--focus".into(),
        focus.clone(),
        "--root".into(),
        root.to_string_lossy().to_string(),
        "--providers".into(),
        providers,
    ];
    match req.mode.as_str() {
        "full-library" | "full-templates" | "selected-library" => {
            if !req.copy_language.is_empty() {
                args.push("--copy-language".into());
                args.push(req.copy_language.clone());
            }
        }
        _ => return Err("Modo desconhecido.".into()),
    }
    if req.mode == "full-library" || req.mode == "full-templates" {
        args.push("--batch".into());
        args.push("all".into());
    }
    if req.mode == "selected-library" {
        if req.case_ids.is_empty() {
            return Err("Escolha de 1 a 20 casos.".into());
        }
        if req.case_ids.len() > 20 {
            return Err("No máximo 20 casos por disparo.".into());
        }
        args.push("--case-ids".into());
        args.push(
            req.case_ids
                .iter()
                .map(|n| n.to_string())
                .collect::<Vec<_>>()
                .join(","),
        );
    }
    if req.dry_run {
        args.push("--dry-run".into());
    }

    let mut cmd = Command::new(&python);
    cmd.args(&args)
        .current_dir(&root)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true)
        .env("PYTHONUNBUFFERED", "1");
    #[cfg(windows)]
    {
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    let display = format!(
        "{} {}",
        python.display(),
        args.iter()
            .map(|a| if a.contains(' ') {
                format!("\"{a}\"")
            } else {
                a.clone()
            })
            .collect::<Vec<_>>()
            .join(" ")
    );
    let mut child = cmd.spawn().map_err(|e| format!("Não arrancou: {e}"))?;
    let stdout = child.stdout.take();
    let stderr = child.stderr.take();
    let pid = child.id();
    *handle.pid.lock().await = pid;
    *handle.child.lock().await = Some(child);
    *handle.status.lock().await = RunStatus {
        running: true,
        dry_run: req.dry_run,
        command: display.clone(),
        target: req.target.clone(),
        focus: focus.clone(),
        started_at: chrono::Local::now().format("%H:%M:%S").to_string(),
        pid,
    };
    let _ = handle.log.send(format!(">> {display}"));
    let _ = handle.log.send(">> média Codex: 1 a 2 min por imagem. A primeira é a mais lenta.".into());

    let log = handle.log.clone();
    if let Some(out) = stdout {
        tokio::spawn(pump(out, log.clone()));
    }
    if let Some(err) = stderr {
        tokio::spawn(pump(err, log.clone()));
    }

    let waiter = handle.clone();
    tokio::spawn(async move {
        let child = {
            let mut guard = waiter.child.lock().await;
            guard.take()
        };
        let code = if let Some(mut child) = child {
            child.wait().await.ok().and_then(|s| s.code())
        } else {
            None
        };
        let line = match code {
            Some(0) => "<< terminou ok".to_string(),
            Some(c) => format!("<< saiu com código {c}"),
            None => "<< processo encerrado".to_string(),
        };
        let _ = waiter.log.send(line);
        let mut status = waiter.status.lock().await;
        status.running = false;
        status.pid = None;
        *waiter.pid.lock().await = None;
    });
    Ok(())
}

async fn pump<R: tokio::io::AsyncRead + Unpin>(reader: R, log: broadcast::Sender<String>) {
    let mut lines = BufReader::new(reader).lines();
    while let Ok(Some(line)) = lines.next_line().await {
        let _ = log.send(line);
    }
}

pub async fn stop_run(handle: Arc<RunHandle>) -> Result<(), String> {
    let pid = {
        let from_pid = *handle.pid.lock().await;
        if from_pid.is_some() {
            from_pid
        } else {
            handle.status.lock().await.pid
        }
    };
    let Some(pid) = pid else {
        return Err("Nada rodando.".into());
    };
    let mut kill = tokio::process::Command::new("taskkill");
    kill.args(["/PID", &pid.to_string(), "/T", "/F"]);
    #[cfg(windows)]
    {
        kill.creation_flags(0x0800_0000);
    }
    let _ = kill.status().await;
    let _ = handle.log.send("<< parado pelo estúdio".into());
    handle.status.lock().await.running = false;
    Ok(())
}

fn slug(value: &str) -> String {
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
    let s = s.trim_matches('-').to_string();
    if s.is_empty() {
        "estudio-v1".into()
    } else {
        s
    }
}
