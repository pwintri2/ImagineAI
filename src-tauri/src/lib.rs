use std::{
    net::{SocketAddr, TcpStream},
    path::PathBuf,
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::Duration,
};

use tauri::{Manager, WindowEvent};

struct ServerState {
    child: Mutex<Option<Child>>,
}

const SERVER_PORT: u16 = 8799;
// Absolute fallback used when running the un-bundled dev binary (resources not
// staged next to the executable). These are local single-user tools.
const DEV_SERVER_PATH: &str = "/home/pwintri2/imagineai/server.py";

fn port_is_open(port: u16) -> bool {
    let address = SocketAddr::from(([127, 0, 0, 1], port));
    TcpStream::connect_timeout(&address, Duration::from_millis(250)).is_ok()
}

fn wait_for_port(port: u16) {
    for _ in 0..80 {
        if port_is_open(port) {
            return;
        }
        thread::sleep(Duration::from_millis(150));
    }
}

fn resolve_server_path(resource_dir: &std::path::Path) -> PathBuf {
    let direct = resource_dir.join("server.py");
    if direct.exists() {
        return direct;
    }
    let bundled = resource_dir.join("_up_").join("server.py");
    if bundled.exists() {
        return bundled;
    }
    PathBuf::from(DEV_SERVER_PATH)
}

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let mut child = None;
            // If something is already serving on the port (e.g. the launcher
            // wrapper pre-started it, or a dev server is running), just attach.
            if !port_is_open(SERVER_PORT) {
                let resource_dir = app.path().resource_dir()?;
                let server_path = resolve_server_path(&resource_dir);
                let spawned = Command::new("python3")
                    .arg("-u")
                    .arg(&server_path)
                    .arg("--host")
                    .arg("127.0.0.1")
                    .arg("--port")
                    .arg(SERVER_PORT.to_string())
                    .env("COMFYUI_URL", "http://127.0.0.1:8188")
                    .env("IMAGINEAI_PORT", SERVER_PORT.to_string())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .spawn()?;
                child = Some(spawned);
                wait_for_port(SERVER_PORT);
            }

            app.manage(ServerState {
                child: Mutex::new(child),
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                // Only kill the server if *we* started it.
                let child = {
                    let state = window.app_handle().state::<ServerState>();
                    state.child.lock().ok().and_then(|mut guard| guard.take())
                };
                if let Some(mut child) = child {
                    let _ = child.kill();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running ImagineAI");
}
