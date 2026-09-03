//! Single-instance handoff and loopback port selection.
//!
//! `7420` is the preferred local HTTP port. It is not a lock. If that port
//! is taken by another Estúdio, this process focuses that window and exits.
//! If something else holds `7420`, Estúdio binds any free loopback port and
//! writes the live address to a discovery file so clients can still find it.
//!
//! Discovery (in order):
//! 1. `GET http://127.0.0.1:7420/api/instance` (or `/api/meta`)
//! 2. `%LOCALAPPDATA%\Estudio\instance.json` on Windows,
//!    `~/.local/share/estudio/instance.json` on other platforms
//!    (override with `ESTUDIO_INSTANCE_DIR`)

use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::time::Duration;

pub const PREFERRED_PORT: u16 = 7420;
pub const APP_ID: &str = "estudio";
pub const WINDOW_TITLE: &str = "Estúdio — Fábrica de imagem";

const PROBE_TIMEOUT: Duration = Duration::from_millis(350);

pub struct InstanceLock {
    dir: PathBuf,
}

pub struct ExistingStudio {
    pub port: u16,
    pub can_focus_http: bool,
}

pub fn instance_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("ESTUDIO_INSTANCE_DIR") {
        if !dir.trim().is_empty() {
            return PathBuf::from(dir);
        }
    }
    if let Ok(dir) = std::env::var("LOCALAPPDATA") {
        if !dir.trim().is_empty() {
            return PathBuf::from(dir).join("Estudio");
        }
    }
    if let Ok(dir) = std::env::var("XDG_DATA_HOME") {
        if !dir.trim().is_empty() {
            return PathBuf::from(dir).join("estudio");
        }
    }
    if let Ok(home) = std::env::var("HOME") {
        if !home.trim().is_empty() {
            return PathBuf::from(home).join(".local/share/estudio");
        }
    }
    std::env::temp_dir().join("estudio")
}

fn lock_path(dir: &Path) -> PathBuf {
    dir.join("instance.lock")
}

fn json_path(dir: &Path) -> PathBuf {
    dir.join("instance.json")
}

impl InstanceLock {
    pub fn claim() -> Option<Self> {
        let dir = instance_dir();
        fs::create_dir_all(&dir).ok()?;
        match OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(lock_path(&dir))
        {
            Ok(mut file) => {
                let _ = writeln!(file, "{}", std::process::id());
                Some(Self { dir })
            }
            Err(_) => None,
        }
    }

    pub fn write_port(&self, port: u16) -> std::io::Result<()> {
        let payload = format!(
            "{{\"app\":\"{APP_ID}\",\"port\":{port},\"pid\":{}}}",
            std::process::id()
        );
        fs::write(json_path(&self.dir), payload)
    }
}

impl Drop for InstanceLock {
    fn drop(&mut self) {
        let _ = fs::remove_file(json_path(&self.dir));
        let _ = fs::remove_file(lock_path(&self.dir));
    }
}

pub fn clear_stale_lock() {
    let dir = instance_dir();
    let _ = fs::remove_file(json_path(&dir));
    let _ = fs::remove_file(lock_path(&dir));
}

pub fn lock_holder_alive() -> bool {
    let text = match fs::read_to_string(lock_path(&instance_dir())) {
        Ok(text) => text,
        Err(_) => return false,
    };
    let Ok(pid) = text.trim().parse::<u32>() else {
        return false;
    };
    process_is_alive(pid)
}

fn process_is_alive(pid: u32) -> bool {
    if pid == 0 {
        return false;
    }
    #[cfg(windows)]
    {
        win::pid_alive(pid)
    }
    #[cfg(unix)]
    {
        Path::new(&format!("/proc/{pid}")).exists()
    }
    #[cfg(not(any(windows, unix)))]
    {
        let _ = pid;
        false
    }
}

pub fn read_instance_port() -> Option<u16> {
    let text = fs::read_to_string(json_path(&instance_dir())).ok()?;
    if json_str_field(&text, "app").as_deref() != Some(APP_ID) {
        return None;
    }
    json_u16_field(&text, "port")
}

/// Bind the preferred loopback port, or any free loopback port if it is busy.
pub fn bind_loopback(preferred: u16) -> std::io::Result<(TcpListener, u16)> {
    match TcpListener::bind(("127.0.0.1", preferred)) {
        Ok(listener) => Ok((listener, preferred)),
        Err(_) => {
            let listener = TcpListener::bind("127.0.0.1:0")?;
            let port = listener.local_addr()?.port();
            Ok((listener, port))
        }
    }
}

pub fn looks_like_estudio(body: &str) -> bool {
    if json_str_field(body, "app").as_deref() == Some(APP_ID) {
        return true;
    }
    json_str_field(body, "factory")
        .map(|factory| factory.contains("image_production_factory"))
        .unwrap_or(false)
        && body.contains("\"cases\"")
}

fn json_field_after<'a>(body: &'a str, key: &str) -> Option<&'a str> {
    let needle = format!("\"{key}\"");
    let mut search = body;
    while let Some(idx) = search.find(&needle) {
        let after = &search[idx + needle.len()..];
        if after.starts_with(|c: char| c.is_ascii_alphanumeric() || c == '_' || c == '-') {
            search = &search[idx + 1..];
            continue;
        }
        let after = after.trim_start().strip_prefix(':')?.trim_start();
        return Some(after);
    }
    None
}

fn json_str_field(body: &str, key: &str) -> Option<String> {
    let after = json_field_after(body, key)?.strip_prefix('"')?;
    let end = after.find('"')?;
    Some(after[..end].replace("\\\\", "\\"))
}

fn json_u16_field(body: &str, key: &str) -> Option<u16> {
    let after = json_field_after(body, key)?;
    let digits: String = after.chars().take_while(|c| c.is_ascii_digit()).collect();
    digits.parse().ok()
}

pub fn probe_studio(port: u16) -> Option<ExistingStudio> {
    if let Some(found) = probe_path(port, "/api/instance") {
        return Some(found);
    }
    probe_path(port, "/api/meta")
}

fn probe_path(port: u16, path: &str) -> Option<ExistingStudio> {
    let raw = http_exchange(port, "GET", path)?;
    let body = http_body(&raw)?;
    if !looks_like_estudio(body) {
        return None;
    }
    Some(ExistingStudio {
        port,
        can_focus_http: json_str_field(body, "app").as_deref() == Some(APP_ID),
    })
}

pub fn find_existing_studio() -> Option<ExistingStudio> {
    let mut ports = Vec::new();
    if let Some(port) = read_instance_port() {
        ports.push(port);
    }
    if !ports.contains(&PREFERRED_PORT) {
        ports.push(PREFERRED_PORT);
    }
    ports.into_iter().find_map(probe_studio)
}

pub fn activate_existing(existing: &ExistingStudio) -> bool {
    let mut ok = false;
    if existing.can_focus_http {
        if let Some(raw) = http_exchange(existing.port, "POST", "/api/focus") {
            ok = raw.contains("200") || raw.contains("\"ok\"");
        }
    }
    ok |= focus_window_by_title(WINDOW_TITLE);
    ok
}

/// If another Estúdio is already serving, focus it and return true.
pub fn hand_off_to_existing() -> bool {
    let Some(existing) = find_existing_studio() else {
        return false;
    };
    let _ = activate_existing(&existing);
    true
}

pub fn focus_window_by_title(title: &str) -> bool {
    #[cfg(windows)]
    {
        win::focus_by_title(title)
    }
    #[cfg(not(windows))]
    {
        let _ = title;
        false
    }
}

pub fn show_error_dialog(message: &str) {
    #[cfg(windows)]
    {
        win::error_dialog(WINDOW_TITLE, message);
    }
    #[cfg(not(windows))]
    {
        eprintln!("{message}");
    }
}

fn http_exchange(port: u16, method: &str, path: &str) -> Option<String> {
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let mut stream = TcpStream::connect_timeout(&addr, PROBE_TIMEOUT).ok()?;
    stream.set_read_timeout(Some(PROBE_TIMEOUT)).ok()?;
    stream.set_write_timeout(Some(PROBE_TIMEOUT)).ok()?;
    let request = format!(
        "{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
    );
    stream.write_all(request.as_bytes()).ok()?;
    let mut buf = Vec::new();
    stream.read_to_end(&mut buf).ok()?;
    String::from_utf8(buf).ok()
}

fn http_body(response: &str) -> Option<&str> {
    response
        .split("\r\n\r\n")
        .nth(1)
        .or_else(|| response.split("\n\n").nth(1))
}

#[cfg(windows)]
mod win {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;

    #[link(name = "user32")]
    extern "system" {
        fn FindWindowW(class: *const u16, name: *const u16) -> isize;
        fn SetForegroundWindow(hwnd: isize) -> i32;
        fn ShowWindow(hwnd: isize, cmd: i32) -> i32;
        fn IsIconic(hwnd: isize) -> i32;
        fn MessageBoxW(hwnd: isize, text: *const u16, caption: *const u16, ty: u32) -> i32;
    }

    const SW_RESTORE: i32 = 9;
    const MB_OK: u32 = 0x0000_0000;
    const MB_ICONERROR: u32 = 0x0000_0010;

    fn wide(text: &str) -> Vec<u16> {
        OsStr::new(text)
            .encode_wide()
            .chain(std::iter::once(0))
            .collect()
    }

    pub fn focus_by_title(title: &str) -> bool {
        let title = wide(title);
        unsafe {
            let hwnd = FindWindowW(std::ptr::null(), title.as_ptr());
            if hwnd == 0 {
                return false;
            }
            if IsIconic(hwnd) != 0 {
                ShowWindow(hwnd, SW_RESTORE);
            }
            SetForegroundWindow(hwnd) != 0
        }
    }

    pub fn error_dialog(title: &str, message: &str) {
        let title = wide(title);
        let message = wide(message);
        unsafe {
            MessageBoxW(0, message.as_ptr(), title.as_ptr(), MB_OK | MB_ICONERROR);
        }
    }

    #[link(name = "kernel32")]
    extern "system" {
        fn OpenProcess(access: u32, inherit: i32, pid: u32) -> isize;
        fn CloseHandle(handle: isize) -> i32;
        fn GetExitCodeProcess(handle: isize, code: *mut u32) -> i32;
    }

    const PROCESS_QUERY_LIMITED_INFORMATION: u32 = 0x1000;
    const STILL_ACTIVE: u32 = 259;

    pub fn pid_alive(pid: u32) -> bool {
        unsafe {
            let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
            if handle == 0 {
                return false;
            }
            let mut code = 0u32;
            let ok = GetExitCodeProcess(handle, &mut code);
            CloseHandle(handle);
            ok != 0 && code == STILL_ACTIVE
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use std::net::TcpListener;
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::thread;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn unique_dir() -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!("estudio-instance-test-{nanos}"))
    }

    fn with_instance_dir<T>(f: impl FnOnce() -> T) -> T {
        static ENV_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());
        let _guard = ENV_LOCK.lock().unwrap_or_else(|err| err.into_inner());
        let dir = unique_dir();
        fs::create_dir_all(&dir).unwrap();
        let previous = std::env::var("ESTUDIO_INSTANCE_DIR").ok();
        std::env::set_var("ESTUDIO_INSTANCE_DIR", &dir);
        let result = f();
        match previous {
            Some(value) => std::env::set_var("ESTUDIO_INSTANCE_DIR", value),
            None => std::env::remove_var("ESTUDIO_INSTANCE_DIR"),
        }
        let _ = fs::remove_dir_all(&dir);
        result
    }

    fn spawn_http(
        responder: impl Fn(&str) -> (u16, String) + Send + 'static,
    ) -> (
        u16,
        Arc<AtomicBool>,
        Arc<AtomicUsize>,
        thread::JoinHandle<()>,
    ) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let stop = Arc::new(AtomicBool::new(false));
        let hits = Arc::new(AtomicUsize::new(0));
        let stop_t = stop.clone();
        let hits_t = hits.clone();
        listener.set_nonblocking(true).unwrap();
        let handle = thread::spawn(move || {
            while !stop_t.load(Ordering::Relaxed) {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        hits_t.fetch_add(1, Ordering::Relaxed);
                        let mut buf = [0u8; 1024];
                        let _ = stream.set_read_timeout(Some(Duration::from_millis(200)));
                        let n = stream.read(&mut buf).unwrap_or(0);
                        let req = String::from_utf8_lossy(&buf[..n]);
                        let line = req.lines().next().unwrap_or("");
                        let (status, body) = responder(line);
                        let reason = if status == 200 { "OK" } else { "ERR" };
                        let response = format!(
                            "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                            body.len()
                        );
                        let _ = stream.write_all(response.as_bytes());
                    }
                    Err(err) if err.kind() == std::io::ErrorKind::WouldBlock => {
                        thread::sleep(Duration::from_millis(10));
                    }
                    Err(_) => break,
                }
            }
        });
        (port, stop, hits, handle)
    }

    #[test]
    fn preferred_port_used_when_free() {
        let probe = TcpListener::bind("127.0.0.1:0").unwrap();
        let preferred = probe.local_addr().unwrap().port();
        drop(probe);
        let (listener, port) = bind_loopback(preferred).unwrap();
        assert_eq!(port, preferred);
        drop(listener);
    }

    #[test]
    fn falls_back_when_preferred_is_taken() {
        let holder = TcpListener::bind("127.0.0.1:0").unwrap();
        let preferred = holder.local_addr().unwrap().port();
        let (listener, port) = bind_loopback(preferred).unwrap();
        assert_ne!(port, preferred);
        assert_ne!(port, 0);
        assert!(listener.local_addr().unwrap().port() == port);
        drop(listener);
        drop(holder);
    }

    #[test]
    fn foreign_process_on_7420_does_not_count_as_estudio() {
        let holder = TcpListener::bind(("127.0.0.1", PREFERRED_PORT));
        let _holder = match holder {
            Ok(listener) => listener,
            Err(_) => TcpListener::bind("127.0.0.1:0").unwrap(),
        };
        let occupied = _holder.local_addr().unwrap().port();
        let (other_port, stop, _, thread) = spawn_http(|_| (200, r#"{"status":"faktory"}"#.into()));
        assert!(probe_studio(other_port).is_none());
        let (listener, port) = bind_loopback(occupied).unwrap();
        assert_ne!(port, occupied);
        drop(listener);
        stop.store(true, Ordering::Relaxed);
        let _ = thread.join();
    }

    #[test]
    fn identifies_estudio_and_ignores_other_http() {
        assert!(looks_like_estudio(r#"{"app":"estudio","port":7421}"#));
        assert!(looks_like_estudio(
            r#"{"factory":"C:\\repo\\skills\\imageproductionfactory\\scripts\\image_production_factory.py","cases":517,"templates":47}"#
        ));
        assert!(!looks_like_estudio(
            r#"{"ok":true,"name":"something-else"}"#
        ));
        assert!(!looks_like_estudio(r#"{"cases":3}"#));
        assert!(looks_like_estudio(
            r#"{"application":"other","app":"estudio","port":9}"#
        ));
    }

    #[test]
    fn probe_finds_estudio_and_skips_foreign_occupant() {
        let studio_body = r#"{"app":"estudio","port":1,"cases":517,"factory":"skills/imageproductionfactory/scripts/image_production_factory.py"}"#.to_string();
        let (studio_port, studio_stop, _, studio_thread) = spawn_http({
            let studio_body = studio_body.clone();
            move |line: &str| {
                if line.contains("/api/instance") || line.contains("/api/meta") {
                    (200, studio_body.clone())
                } else if line.contains("/api/focus") {
                    (200, "{\"ok\":true}".into())
                } else {
                    (404, "{}".into())
                }
            }
        });
        assert!(probe_studio(studio_port).is_some());

        let (other_port, other_stop, _, other_thread) =
            spawn_http(|_| (200, "{\"hello\":\"world\"}".into()));
        assert!(probe_studio(other_port).is_none());

        studio_stop.store(true, Ordering::Relaxed);
        other_stop.store(true, Ordering::Relaxed);
        let _ = studio_thread.join();
        let _ = other_thread.join();
    }

    #[test]
    fn second_launch_hands_off_via_discovery_file() {
        with_instance_dir(|| {
            let focuses = Arc::new(AtomicUsize::new(0));
            let focuses_h = focuses.clone();
            let (port, stop, _, thread) = spawn_http(move |line: &str| {
                if line.contains("POST /api/focus") {
                    focuses_h.fetch_add(1, Ordering::Relaxed);
                    return (200, "{\"ok\":true}".into());
                }
                (
                    200,
                    r#"{"app":"estudio","port":1,"factory":"image_production_factory.py","cases":1}"#.into(),
                )
            });
            fs::write(
                json_path(&instance_dir()),
                format!(r#"{{"app":"estudio","port":{port},"pid":1}}"#),
            )
            .unwrap();

            assert!(hand_off_to_existing());
            assert!(focuses.load(Ordering::Relaxed) >= 1);

            stop.store(true, Ordering::Relaxed);
            let _ = thread.join();
        });
    }

    #[test]
    fn lock_claim_is_exclusive_until_drop() {
        with_instance_dir(|| {
            let first = InstanceLock::claim().expect("first claim");
            assert!(InstanceLock::claim().is_none());
            first.write_port(7421).unwrap();
            assert_eq!(read_instance_port(), Some(7421));
            drop(first);
            let second = InstanceLock::claim().expect("claim after drop");
            drop(second);
        });
    }

    #[test]
    fn stale_lock_can_be_cleared() {
        with_instance_dir(|| {
            let lock = InstanceLock::claim().unwrap();
            std::mem::forget(lock);
            assert!(InstanceLock::claim().is_none());
            assert!(lock_holder_alive());
            clear_stale_lock();
            assert!(!lock_holder_alive());
            assert!(InstanceLock::claim().is_some());
        });
    }
}
