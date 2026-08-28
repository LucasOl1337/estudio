mod library;
mod paths;
mod run;
mod targets;

use axum::body::Body;
use axum::extract::{Multipart, Path, State};
use axum::http::{header, StatusCode};
use axum::response::sse::{Event, KeepAlive, Sse};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use futures_util::StreamExt;
use library::Library;
use paths::{alvos_dir, detect_root, factory_script, resolve_python};
use run::{start_run, stop_run, RunHandle, RunRequest};
use serde_json::json;
use std::convert::Infallible;
use std::path::PathBuf;
use std::sync::Arc;
use targets::{create_target, gallery, list_targets, open_in_browser, save_photos, write_gallery_html};
use tokio::net::TcpListener;
use tokio_stream::wrappers::BroadcastStream;
use tower_http::cors::CorsLayer;

struct AppState {
    root: PathBuf,
    library: Library,
    run: Arc<RunHandle>,
    static_dir: PathBuf,
}

fn main() {
    let root = if let Ok(from_env) = std::env::var("IMAGEGEN_ROOT") {
        PathBuf::from(from_env)
    } else {
        detect_root()
    };
    let shown_root = root.clone();
    std::thread::spawn(move || {
        let rt = tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("tokio");
        rt.block_on(serve(root));
    });
    wait_for_server();
    println!("Estúdio (Rust) — janela nativa");
    println!("repo {}", shown_root.display());
    open_window();
}

async fn serve(root: PathBuf) {
    let library = library::load_library(&root);
    let static_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("static");
    let state = Arc::new(AppState {
        root: root.clone(),
        library,
        run: RunHandle::new(),
        static_dir,
    });

    let app = Router::new()
        .route("/", get(index))
        .route("/app.css", get(css))
        .route("/app.js", get(js))
        .route("/favicon.ico", get(favicon))
        .route("/favicon.png", get(favicon_png))
        .route("/api/meta", get(meta))
        .route("/api/targets", get(get_targets).post(post_target))
        .route("/api/targets/{name}/photos", post(post_photos))
        .route("/api/library", get(get_library))
        .route("/api/thumbs/{id}", get(thumb))
        .route("/api/runs/{target}/{focus}", get(get_gallery))
        .route("/api/runs/{target}/{focus}/open", post(open_gallery))
        .route("/api/media/{target}/{focus}/{queue}/{file}", get(media))
        .route("/api/photo/{target}/{*rel}", get(photo))
        .route("/api/run", post(post_run))
        .route("/api/run/stop", post(post_stop))
        .route("/api/run/status", get(get_status))
        .route("/api/run/log", get(sse_log))
        .layer(CorsLayer::permissive())
        .with_state(state);

    let listener = TcpListener::bind("127.0.0.1:7420").await.expect("bind 7420");
    axum::serve(listener, app).await.expect("serve");
}

fn wait_for_server() {
    for _ in 0..80 {
        if std::net::TcpStream::connect("127.0.0.1:7420").is_ok() {
            return;
        }
        std::thread::sleep(std::time::Duration::from_millis(50));
    }
    panic!("servidor local não subiu em 127.0.0.1:7420");
}

fn open_window() {
    use tao::event::{Event, WindowEvent};
    use tao::event_loop::{ControlFlow, EventLoop};
    use tao::window::WindowBuilder;
    use wry::WebViewBuilder;

    let event_loop = EventLoop::new();
    let icon = load_window_icon();
    let window = WindowBuilder::new()
        .with_title("Estúdio — Fábrica de imagem")
        .with_inner_size(tao::dpi::LogicalSize::new(1280.0, 860.0))
        .with_window_icon(icon)
        .build(&event_loop)
        .expect("janela");
    let _webview = WebViewBuilder::new()
        .with_url("http://127.0.0.1:7420/")
        .build(&window)
        .expect("webview");
    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        if let Event::WindowEvent {
            event: WindowEvent::CloseRequested,
            ..
        } = event
        {
            *control_flow = ControlFlow::Exit;
        }
    });
}

async fn index(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    file_or_status(&state.static_dir.join("index.html"), "text/html; charset=utf-8")
}

async fn css(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    file_or_status(&state.static_dir.join("app.css"), "text/css; charset=utf-8")
}

async fn js(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    file_or_status(
        &state.static_dir.join("app.js"),
        "application/javascript; charset=utf-8",
    )
}

async fn favicon(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    file_or_status(&state.static_dir.join("favicon.ico"), "image/x-icon")
}

async fn favicon_png(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    file_or_status(&state.static_dir.join("favicon.png"), "image/png")
}

fn load_window_icon() -> Option<tao::window::Icon> {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("assets/icon.png");
    let img = image::open(path).ok()?.into_rgba8();
    let (w, h) = img.dimensions();
    tao::window::Icon::from_rgba(img.into_raw(), w, h).ok()
}

fn file_or_status(path: &std::path::Path, mime: &'static str) -> Response {
    match std::fs::read(path) {
        Ok(bytes) => Response::builder()
            .header(header::CONTENT_TYPE, mime)
            .body(Body::from(bytes))
            .unwrap(),
        Err(_) => (StatusCode::NOT_FOUND, "missing static file").into_response(),
    }
}

async fn meta(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    Json(json!({
        "root": state.root,
        "python": resolve_python(),
        "factory": factory_script(&state.root),
        "cases": state.library.cases.len(),
        "templates": state.library.templates.len(),
        "purposes": state.library.purposes.len(),
    }))
}

async fn get_targets(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    Json(json!(list_targets(&state.root)))
}

async fn post_target(
    State(state): State<Arc<AppState>>,
    mut multipart: Multipart,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    let mut name = String::new();
    let mut files = Vec::new();
    while let Some(field) = multipart.next_field().await.map_err(map_err)? {
        let field_name = field.name().unwrap_or("").to_string();
        if field_name == "name" {
            name = field.text().await.map_err(map_err)?;
        } else if field_name == "files" {
            let filename = field.file_name().unwrap_or("foto.png").to_string();
            let data = field.bytes().await.map_err(map_err)?;
            files.push((filename, data.to_vec()));
        }
    }
    let dir = create_target(&state.root, &name).map_err(bad)?;
    if !files.is_empty() {
        save_photos(&dir, files).map_err(bad)?;
    }
    Ok(Json(json!({ "ok": true, "name": dir.file_name().unwrap().to_string_lossy() })))
}

async fn post_photos(
    State(state): State<Arc<AppState>>,
    Path(name): Path<String>,
    mut multipart: Multipart,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    let dir = alvos_dir(&state.root).join(&name);
    if !dir.is_dir() {
        return Err((StatusCode::NOT_FOUND, "alvo inexistente".into()));
    }
    let mut files = Vec::new();
    while let Some(field) = multipart.next_field().await.map_err(map_err)? {
        if field.name() != Some("files") {
            continue;
        }
        let filename = field.file_name().unwrap_or("foto.png").to_string();
        let data = field.bytes().await.map_err(map_err)?;
        files.push((filename, data.to_vec()));
    }
    let n = save_photos(&dir, files).map_err(bad)?;
    Ok(Json(json!({ "ok": true, "saved": n })))
}

async fn get_library(State(state): State<Arc<AppState>>) -> Json<Library> {
    Json(state.library.clone())
}

async fn thumb(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> Response {
    let path = state
        .root
        .join("vendor/awesome-gpt-image-2/data/images")
        .join(format!("case{id}.jpg"));
    send_file(&path)
}

async fn get_gallery(
    State(state): State<Arc<AppState>>,
    Path((target, focus)): Path<(String, String)>,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    let dir = alvos_dir(&state.root).join(&target);
    if !dir.is_dir() {
        return Err((StatusCode::NOT_FOUND, "alvo inexistente".into()));
    }
    let items = gallery(&dir, &focus);
    let _ = write_gallery_html(&dir, &focus, &state.library.cases);
    Ok(Json(json!(items)))
}

async fn open_gallery(
    State(state): State<Arc<AppState>>,
    Path((target, focus)): Path<(String, String)>,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    let dir = alvos_dir(&state.root).join(&target);
    if !dir.is_dir() {
        return Err((StatusCode::NOT_FOUND, "alvo inexistente".into()));
    }
    let path = write_gallery_html(&dir, &focus, &state.library.cases).map_err(bad)?;
    open_in_browser(&path).map_err(bad)?;
    Ok(Json(json!({ "ok": true, "path": path })))
}

async fn media(
    State(state): State<Arc<AppState>>,
    Path((target, focus, queue, file)): Path<(String, String, String, String)>,
) -> Response {
    if queue != "FILA_GROK" && queue != "FILA_CODEX" {
        return StatusCode::BAD_REQUEST.into_response();
    }
    let file_name = std::path::Path::new(&file)
        .file_name()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_default();
    let path = alvos_dir(&state.root)
        .join(target)
        .join("PRODUCOES")
        .join(focus)
        .join(queue)
        .join(file_name);
    send_file(&path)
}

async fn photo(
    State(state): State<Arc<AppState>>,
    Path((target, rel)): Path<(String, String)>,
) -> Response {
    let base = alvos_dir(&state.root).join(&target);
    let joined = base.join(rel.replace('\\', "/"));
    let Ok(canon) = joined.canonicalize() else {
        return StatusCode::NOT_FOUND.into_response();
    };
    let Ok(root) = base.canonicalize() else {
        return StatusCode::NOT_FOUND.into_response();
    };
    if !canon.starts_with(&root) {
        return StatusCode::FORBIDDEN.into_response();
    }
    send_file(&canon)
}

async fn post_run(
    State(state): State<Arc<AppState>>,
    Json(req): Json<RunRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    start_run(state.root.clone(), req, state.run.clone())
        .await
        .map_err(bad)?;
    Ok(Json(json!({ "ok": true })))
}

async fn post_stop(
    State(state): State<Arc<AppState>>,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    stop_run(state.run.clone()).await.map_err(bad)?;
    Ok(Json(json!({ "ok": true })))
}

async fn get_status(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let status = state.run.status.lock().await.clone();
    Json(json!(status))
}

async fn sse_log(
    State(state): State<Arc<AppState>>,
) -> Sse<impl futures_util::Stream<Item = Result<Event, Infallible>>> {
    let rx = state.run.log.subscribe();
    let stream = BroadcastStream::new(rx).filter_map(|item| async move {
        match item {
            Ok(line) => Some(Ok(Event::default().data(line))),
            Err(_) => None,
        }
    });
    Sse::new(stream).keep_alive(KeepAlive::default())
}

fn send_file(path: &std::path::Path) -> Response {
    match std::fs::read(path) {
        Ok(bytes) => {
            let mime = mime_guess::from_path(path)
                .first_or_octet_stream()
                .to_string();
            Response::builder()
                .header(header::CONTENT_TYPE, mime)
                .body(Body::from(bytes))
                .unwrap()
        }
        Err(_) => StatusCode::NOT_FOUND.into_response(),
    }
}

fn map_err<E: std::fmt::Display>(e: E) -> (StatusCode, String) {
    (StatusCode::BAD_REQUEST, e.to_string())
}

fn bad(msg: String) -> (StatusCode, String) {
    (StatusCode::BAD_REQUEST, msg)
}
