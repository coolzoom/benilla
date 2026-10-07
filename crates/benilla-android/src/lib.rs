//! The Android launcher: NativeActivity loads this library and calls [`android_main`], which
//! points the install and the state folder at the app's external files folder and runs
//! `benilla_app`. An app gets no environment from adb, so `benilla.env` in that folder carries the
//! variables a desktop run takes from the shell. The folder, as `android.sh` fills it:
//!
//! ```text
//! /sdcard/Android/data/org.benilla.client/files/
//!   benilla.env       WOW_HOST=…, WOW_USER=…, one KEY=VALUE per line
//!   WoW/Data/         the player's own 1.12.1 Data, read-only
//!   benilla-config/   benilla's local state
//! ```
#![cfg(target_os = "android")]

use std::path::Path;

use benilla_app::BuildId;
use bevy::android::android_activity::AndroidApp;

/// NativeActivity's entry point, run on its own thread by `android-activity`.
#[no_mangle]
fn android_main(app: AndroidApp) {
    logcat::redirect_stdio();
    let files = app
        .external_data_path()
        .or_else(|| app.internal_data_path());
    let _ = bevy::android::ANDROID_APP.set(app);
    match files {
        Some(dir) => configure(&dir),
        None => eprintln!("android: the app has no files folder; running with no install"),
    }
    let exit = benilla_app::run(BuildId {
        version: env!("CARGO_PKG_VERSION"),
        describe: env!("BENILLA_GIT_DESCRIBE"),
        sha: env!("BENILLA_GIT_SHA"),
        short: env!("BENILLA_GIT_SHORT"),
        date: env!("BENILLA_GIT_DATE"),
        profile: env!("BENILLA_PROFILE"),
        project_dir: env!("BENILLA_PROJECT_DIR"),
        ..Default::default()
    });
    println!("android: app exit {exit:?}");
}

/// Sets `benilla.env`'s variables, then `WOW_DATA` and `BENILLA_HOME` under `dir` unless the file
/// named them. Runs before the app spawns a thread, so the environment writes race nothing.
fn configure(dir: &Path) {
    let env_file = dir.join("benilla.env");
    if let Ok(text) = std::fs::read_to_string(&env_file) {
        for line in text.lines().map(str::trim) {
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            if let Some((key, value)) = line.split_once('=') {
                std::env::set_var(key.trim(), value.trim());
            }
        }
        println!("android: read {}", env_file.display());
    }
    let defaults = [
        ("WOW_DATA", dir.join("WoW").join("Data")),
        ("BENILLA_HOME", dir.join("benilla-config")),
    ];
    for (key, path) in defaults {
        if std::env::var_os(key).is_none() {
            std::env::set_var(key, &path);
        }
        println!("android: {key}={}", std::env::var(key).unwrap_or_default());
    }
}

/// stdout and stderr into logcat: an app's fds 1 and 2 go to /dev/null, and the client reports
/// through `println!` as much as through `tracing`.
mod logcat {
    use std::ffi::{c_char, c_int, CString};
    use std::fs::File;
    use std::io::{BufRead, BufReader};
    use std::os::fd::FromRawFd;

    const ANDROID_LOG_INFO: c_int = 4;

    #[link(name = "log")]
    extern "C" {
        fn __android_log_write(prio: c_int, tag: *const c_char, text: *const c_char) -> c_int;
    }

    pub(crate) fn redirect_stdio() {
        let mut fds = [0 as c_int; 2];
        // SAFETY: `fds` is a two-int array as `pipe` requires; `dup2` onto 1 and 2 only replaces
        // the descriptors Rust's stdout and stderr write through.
        unsafe {
            if libc::pipe(fds.as_mut_ptr()) != 0 {
                return;
            }
            libc::dup2(fds[1], libc::STDOUT_FILENO);
            libc::dup2(fds[1], libc::STDERR_FILENO);
            libc::close(fds[1]);
        }
        // SAFETY: `fds[0]` is the pipe's read end, owned by this `File` alone from here.
        let reader = unsafe { File::from_raw_fd(fds[0]) };
        let _ = std::thread::Builder::new()
            .name("stdio-logcat".into())
            .spawn(move || {
                let tag = c"benilla";
                for line in BufReader::new(reader).split(b'\n').map_while(Result::ok) {
                    let line = CString::new(line).unwrap_or_else(|e| {
                        let mut bytes = e.into_vec();
                        bytes.retain(|&b| b != 0);
                        CString::new(bytes).unwrap_or_default()
                    });
                    // SAFETY: both pointers are NUL-terminated strings alive for the call.
                    unsafe { __android_log_write(ANDROID_LOG_INFO, tag.as_ptr(), line.as_ptr()) };
                }
            });
    }
}
