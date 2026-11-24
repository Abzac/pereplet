#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{fs, io::{Read, Write}, net::{TcpStream, TcpListener}, path::{Path, PathBuf}, process::{Child, Command, Stdio}, sync::{Mutex, atomic::{AtomicBool, Ordering}}, time::{Duration, Instant, SystemTime, UNIX_EPOCH}};
use std::os::windows::{process::CommandExt, io::AsRawHandle};
use serde::{Serialize, Deserialize};
use tauri::{Manager, Emitter, WebviewWindow, WebviewWindowBuilder, WebviewUrl, WindowEvent};
use windows_sys::Win32::{Foundation::{HANDLE, CloseHandle}, System::JobObjects::*, UI::WindowsAndMessaging::{MessageBoxW, ShowWindow, SW_MINIMIZE, MB_OK, MB_ICONERROR}};

// The demonstration installation is explicitly opt-in and owns a separate
// single-instance identity, server port and WebView profile beside its EXE.
static DEMO: AtomicBool = AtomicBool::new(false);
fn port() -> u16 { if DEMO.load(Ordering::SeqCst) {18771} else {18769} }
fn origin() -> String { format!("http://127.0.0.1:{}",port()) }
fn window_title() -> &'static str {if DEMO.load(Ordering::SeqCst) {"Переплёт — демо"} else {"Переплёт"}}


struct Job(HANDLE);
unsafe impl Send for Job {}
unsafe impl Sync for Job {}
impl Drop for Job { fn drop(&mut self) { unsafe { CloseHandle(self.0); } } }
impl Job {
    fn attach(child: &Child) -> Result<Self, String> {
        unsafe {
            let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if handle.is_null() { return Err(std::io::Error::last_os_error().to_string()); }
            let job = Self(handle);
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(handle, JobObjectExtendedLimitInformation, &info as *const _ as *const _, std::mem::size_of_val(&info) as u32) == 0 || AssignProcessToJobObject(handle, child.as_raw_handle() as HANDLE) == 0 {
                return Err(std::io::Error::last_os_error().to_string());
            }
            Ok(job)
        }
    }
}

fn http(path: &str, token: Option<&str>) -> Result<serde_json::Value, String> {
    let port = port();
    let address = format!("127.0.0.1:{port}").parse().map_err(|e| format!("{e}"))?;
    let mut stream = TcpStream::connect_timeout(&address, Duration::from_millis(700)).map_err(|e| e.to_string())?;
    stream.set_read_timeout(Some(Duration::from_secs(2))).map_err(|e| e.to_string())?;
    let request = if let Some(key) = token {
        format!("POST {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\nX-Pereplet: 1\r\nX-Pereplet-Token: {key}\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{{}}")
    } else { format!("GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n") };
    stream.write_all(request.as_bytes()).map_err(|e| e.to_string())?;
    let mut response = String::new();stream.read_to_string(&mut response).map_err(|e| e.to_string())?;
    if !response.starts_with("HTTP/1.1 200") {return Err("Локальный сервер вернул ошибку".into());}
    serde_json::from_str(response.split_once("\r\n\r\n").ok_or("Неполный ответ сервера")?.1).map_err(|e| e.to_string())
}

struct Backend { child: Child, _job: Job, instance: String }
impl Backend {
    fn start(root: &Path) -> Result<Self, String> {
        let reservation = TcpListener::bind(("127.0.0.1", port())).map_err(|_| format!("Порт {} занят. Закройте другую копию этой библиотеки и повторите запуск.",port()))?;
        fs::create_dir_all(root.join("data")).map_err(|e|e.to_string())?;
        let log_path=root.join("data/server.log");
        if log_path.metadata().map(|m|m.len()>8*1024*1024).unwrap_or(false) { let _=fs::rename(&log_path,root.join("data/server.previous.log")); }
        let log=fs::OpenOptions::new().create(true).append(true).open(log_path).map_err(|e|e.to_string())?;
        let instance=format!("{}-{}",std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos());
        drop(reservation);
        let mut child=Command::new(root.join("runtime/python.exe"))
            .args(["-B","-X","utf8","-u"]).arg(root.join("desktop_server.py"))
            .current_dir(root).env("PEREPLET_PORT",port().to_string())
            .env("PEREPLET_DATA_DIR",root.join("data")).env("PEREPLET_INSTANCE_ID",&instance)
            .env("PYTHONDONTWRITEBYTECODE","1")
            .stdin(Stdio::null()).stdout(Stdio::from(log.try_clone().map_err(|e|e.to_string())?)).stderr(Stdio::from(log))
            .creation_flags(0x08000000).spawn().map_err(|e|format!("Не удалось запустить внутренний сервер: {e}"))?;
        let job=match Job::attach(&child) {Ok(job)=>job,Err(e)=>{let _=child.kill();let _=child.wait();return Err(e)}};
        let mut server=Self{child,_job:job,instance};
        let deadline=Instant::now()+Duration::from_secs(25);
        while Instant::now()<deadline {
            if server.child.try_wait().map_err(|e|e.to_string())?.is_some() {return Err("Сервер завершился при запуске. Подробности: data/server.log".into());}
            if let Ok(health)=http("/api/health",None) { if health["instance"]==server.instance {return Ok(server);} }
            std::thread::sleep(Duration::from_millis(120));
        }
        Err("Сервер не успел запуститься. Подробности: data/server.log".into())
    }
}
impl Drop for Backend {
    fn drop(&mut self) {
        if http("/api/health",None).map(|h|h["instance"]==self.instance).unwrap_or(false) {
            if let Ok(session)=http("/api/session",None) {if let Some(token)=session["token"].as_str(){let _=http("/api/shutdown",Some(token));}}
        }
        let deadline=Instant::now()+Duration::from_secs(5);
        while Instant::now()<deadline {if self.child.try_wait().ok().flatten().is_some(){return;}std::thread::sleep(Duration::from_millis(100));}
        let _=self.child.kill();let _=self.child.wait();
    }
}

#[derive(Serialize,Deserialize)]
struct Geometry {width:f64,height:f64,x:i32,y:i32,maximized:bool}
struct Desktop { backend: Mutex<Option<Backend>>, root:PathBuf, ready:AtomicBool, closing:AtomicBool }

fn save_geometry(window:&WebviewWindow,root:&Path) {
    if window.is_fullscreen().unwrap_or(false){return;}
    let maximized=window.is_maximized().unwrap_or(false);
    let old=fs::read(root.join("data/window.json")).ok().and_then(|b|serde_json::from_slice::<Geometry>(&b).ok());
    let geometry=if maximized { old.map(|g|Geometry{maximized:true,..g}) } else {
        match (window.inner_size(),window.outer_position(),window.scale_factor()) {
            (Ok(size),Ok(pos),Ok(scale))=>Some(Geometry{width:size.width as f64/scale,height:size.height as f64/scale,x:pos.x,y:pos.y,maximized}),_=>None
        }
    };
    if let Some(g)=geometry {if let Ok(bytes)=serde_json::to_vec(&g){let _=fs::write(root.join("data/window.json"),bytes);}}
}

#[tauri::command]
fn desktop_ready(state:tauri::State<Desktop>) {state.ready.store(true,Ordering::SeqCst);}
#[tauri::command]
fn minimize_window(window:WebviewWindow)->Result<(),String>{
    let hwnd=window.hwnd().map_err(|e|e.to_string())?.0 as isize;
    std::thread::spawn(move||{std::thread::sleep(Duration::from_millis(150));let _=window.run_on_main_thread(move||unsafe{ShowWindow(hwnd as _,SW_MINIMIZE);});}); Ok(())
}
#[tauri::command]
fn finish_close(window:WebviewWindow,state:tauri::State<Desktop>)->Result<(),String>{
    save_geometry(&window,&state.root);state.closing.store(true,Ordering::SeqCst);window.close().map_err(|e|e.to_string())
}

fn run()->Result<(),Box<dyn std::error::Error>> {
    let root=std::env::current_exe()?.parent().ok_or("Не определена папка приложения")?.to_owned();
    DEMO.store(root.join("demo-profile.json").is_file(),Ordering::SeqCst);
    let mut context=tauri::generate_context!();
    if DEMO.load(Ordering::SeqCst) {context.config_mut().identifier="app.pereplet.demo".into();}
    if !root.join("webview2/msedgewebview2.exe").exists(){return Err("Не найден встроенный WebView2. Распакуйте архив целиком.".into());}
    std::env::set_var("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER",root.join("webview2"));
    // Do not inherit an unrelated WebView2 profile or developer settings.
    std::env::remove_var("WEBVIEW2_USER_DATA_FOLDER");std::env::remove_var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS");
    let app=tauri::Builder::default()
      .plugin(tauri_plugin_single_instance::init(|app,_,_|{if let Some(w)=app.get_webview_window("main"){let _=w.unminimize();let _=w.show();let _=w.set_focus();}}))
      .invoke_handler(tauri::generate_handler![desktop_ready,minimize_window,finish_close])
      .setup(move |app| {
        let backend=Backend::start(&root).map_err(std::io::Error::other)?;
        let geometry=fs::read(root.join("data/window.json")).ok().and_then(|b|serde_json::from_slice::<Geometry>(&b).ok());
        app.manage(Desktop{backend:Mutex::new(Some(backend)),root:root.clone(),ready:AtomicBool::new(false),closing:AtomicBool::new(false)});
        let mut builder=WebviewWindowBuilder::new(app,"main",WebviewUrl::External(origin().parse()?))
          .title(window_title()).decorations(false).shadow(true).resizable(true).drag_and_drop(false)
          .inner_size(1320.0,880.0).min_inner_size(800.0,600.0).center()
          .data_directory(root.join("data/webview2"))
          .on_navigation(|url|url.scheme()=="http"&&url.host_str()==Some("127.0.0.1")&&url.port()==Some(port()));
        if std::env::var("PEREPLET_QA").as_deref()==Ok("1") {builder=builder.additional_browser_args(if DEMO.load(Ordering::SeqCst){"--remote-debugging-port=18772"}else{"--remote-debugging-port=18770"});}
        if let Some(g)=&geometry {builder=builder.inner_size(g.width.clamp(800.0,3840.0),g.height.clamp(600.0,2160.0));}
        let window=builder.build()?;
        if let Some(g)=geometry {
          let visible=window.available_monitors()?.iter().any(|m|{let p=m.position();let s=m.size();g.x+120>p.x&&g.y+36>p.y&&g.x<p.x+s.width as i32-80&&g.y<p.y+s.height as i32-40});
          if visible {let _=window.set_position(tauri::PhysicalPosition::new(g.x,g.y));}
          save_geometry(&window,&root);
          if g.maximized {let _=window.maximize();}
        } else {save_geometry(&window,&root);}
        window.on_window_event({let window=window.clone();move |event| {
          if let WindowEvent::CloseRequested{api,..}=event {
            let state=window.state::<Desktop>();
            if state.ready.load(Ordering::SeqCst)&&!state.closing.load(Ordering::SeqCst) {api.prevent_close();let _=window.emit("desktop-close-requested",());}
            else {save_geometry(&window,&state.root);}
          }
        }});
        Ok(())
      }).build(context)?;
    app.run(|app,event|{if let tauri::RunEvent::Exit=event {if let Some(state)=app.try_state::<Desktop>() {if let Ok(mut server)=state.backend.lock(){drop(server.take());}}}});
    Ok(())
}
fn main(){if let Err(error)=run(){let msg:Vec<u16>=format!("{error}").encode_utf16().chain(Some(0)).collect();let title:Vec<u16>="Переплёт".encode_utf16().chain(Some(0)).collect();unsafe{MessageBoxW(std::ptr::null_mut(),msg.as_ptr(),title.as_ptr(),MB_OK|MB_ICONERROR);}}}

