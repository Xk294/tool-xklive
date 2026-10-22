pub mod audio;
pub mod commands;
pub mod core;
pub mod dsp;
pub mod mixer;
pub mod state;

use state::AppState;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app_state = AppState::new();

    tauri::Builder::default()
        .manage(app_state)
        .invoke_handler(tauri::generate_handler![
            commands::get_state,
            commands::discover_mixers_cmd,
            commands::list_audio_devices,
            commands::connect_mixer,
            commands::disconnect_mixer,
            commands::panic_reset,
            commands::set_mode,
            commands::toggle_whitelist,
            commands::toggle_lock,
            commands::approve_proposal,
            commands::reject_proposal,
            commands::trigger_demo_feedback,
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while building tauri application");
}
