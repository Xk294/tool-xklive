pub mod audio;
pub mod commands;
pub mod core;
pub mod dsp;
pub mod mixer;
pub mod state;

use crate::core::models::{ConnectionState, PEQBand};
use crate::mixer::mapper::ParameterMapper;
use crate::state::{now_secs, AppState};
use tauri::Manager;

fn run_auto_release_tick(state: &AppState, now: f64) {
    let releases = {
        let mut safety = state.safety.lock();
        let (new_safety, rel) = crate::core::safety::check_auto_release(&safety, now, 1.0);
        *safety = new_safety;
        rel
    };

    for prop in releases {
        if let Some(band) = prop.band {
            state.send_peq_unbatched(&PEQBand {
                channel: prop.channel,
                band,
                freq_hz: prop.freq_hz,
                gain_db: prop.gain_db,
                q: prop.q,
                is_on: true,
                filter_type: 2,
                target: prop.target.clone(),
                bus: prop.bus,
            });
        }
        state.add_log_coded(
            &prop.reason,
            "approved",
            "reasons.auto_release",
            serde_json::json!({
                "band": prop.band.unwrap_or(0),
                "target": prop.target,
                "gain_db": (prop.gain_db * 10.0).round() / 10.0
            }),
        );
    }
}

fn poll_and_merge_meters(
    state: &AppState,
    fx_addr: &str,
    usb_running: bool,
    now: f64,
) -> (Option<Vec<f32>>, Option<Vec<f32>>, Option<f32>) {
    let (rta_opt, mut meters_opt, cached_fx_fader) = if let Some(client) = &*state.xair.lock() {
        if client.get_state() == ConnectionState::Connected {
            let fx_fader = client.params_cache.lock().get(fx_addr).copied();
            (
                Some(client.rta_levels.lock().clone()),
                Some(AppState::get_decayed_lan_meters(client)),
                fx_fader,
            )
        } else {
            (None, None, None)
        }
    } else {
        (None, None, None)
    };

    if usb_running {
        let mut base_meters = meters_opt.unwrap_or_else(|| vec![0.0; 18]);
        state.merge_active_usb_meters(&mut base_meters, now);
        meters_opt = Some(base_meters);
    }

    (rta_opt, meters_opt, cached_fx_fader)
}

fn process_lan_gain_and_talkover(
    state: &AppState,
    meters: &[f32],
    usb_running: bool,
    cached_fx_fader: Option<f32>,
    now: f64,
) {
    if !usb_running {
        let mut gs = state.gain_staging.lock();
        for ch in 1..=16u8 {
            let lin = meters.get((ch - 1) as usize).copied().unwrap_or(0.0);
            let peak_db = ParameterMapper::linear_to_db(lin, -90.0);
            let rms_db = (peak_db - 6.0).max(-95.0);
            let (_, clip_opt) = gs.process_meter_sample(ch, peak_db, rms_db, now);
            if let Some(alert) = clip_opt {
                state.clip_alerts.lock().insert(ch, alert);
            }
        }
    }

    if now < *state.fx_override_until.lock() {
        return;
    }

    let whitelist_snap = state.safety.lock().whitelist.clone();
    let (fader_cmd, fx_ch, mic_ch_used, is_ducked_now, msg) = {
        let mut tk = state.talkover.lock();
        if let Some(hw_fader) = cached_fx_fader {
            if !tk.is_ducked {
                tk.set_original_fader(hw_fader);
            }
        }
        if tk.config.enabled {
            let mic_ch = tk.config.mic_channel.clamp(1, 16);
            let mic_lin = meters.get((mic_ch - 1) as usize).copied().unwrap_or(0.0);
            let mic_db = ParameterMapper::linear_to_db(mic_lin, -90.0);

            let mut music_db = -90.0f32;
            for &m_ch in &tk.config.music_channels {
                if m_ch >= 1 && (m_ch as usize) <= meters.len() && m_ch != mic_ch {
                    let db = ParameterMapper::linear_to_db(meters[(m_ch - 1) as usize], -90.0);
                    if db > music_db {
                        music_db = db;
                    }
                }
            }
            for ch in 1..=16u8 {
                if !whitelist_snap.contains(&ch) && ch != mic_ch && (ch as usize) <= meters.len() {
                    let db = ParameterMapper::linear_to_db(meters[(ch - 1) as usize], -90.0);
                    if db > music_db {
                        music_db = db;
                    }
                }
            }

            let (f_out, log_msg) = tk.process_frame(mic_db, music_db, now);
            (f_out, tk.config.fx_return_channel, mic_ch, tk.is_ducked, log_msg)
        } else {
            (None, 1, 1, false, String::new())
        }
    };

    if let Some(val) = fader_cmd {
        let addr = format!("/fxrtn/{:02}/mix/fader", fx_ch);
        state.send_fader_if_live(&addr, val);
    }
    if !msg.is_empty() {
        state.add_log_coded(
            &msg,
            "approved",
            "log.talkoverState",
            serde_json::json!({
                "channel": mic_ch_used,
                "ducked": if is_ducked_now { "ON" } else { "OFF" },
                "is_ducked": is_ducked_now,
                "message": msg
            }),
        );
    }
}

fn process_lan_rta_feedback(
    state: &AppState,
    rta: &[f32],
    meters_opt: Option<&[f32]>,
    now: f64,
) {
    let proposals = {
        let mut rta_det = state.rta_detector.lock();
        rta_det.process_rta_frame_at(rta, "main", now)
    };
    for mut prop in proposals {
        if let Some(meters) = meters_opt {
            let mut energies = std::collections::HashMap::new();
            for ch in 1..=16u8 {
                let lin = meters.get((ch - 1) as usize).copied().unwrap_or(0.0);
                let db = ParameterMapper::linear_to_db(lin, -100.0);
                energies.insert(ch, db);
            }
            let routing = state.build_routing_snapshot();
            let loc = state
                .localizer
                .lock()
                .localize_from_energies(&energies, prop.freq_hz, Some(&routing), None);
            if let Some(top) = loc.top_candidate {
                if top.score >= 0.55 && !loc.is_ambiguous {
                    prop.suspected_channel = Some(top.channel);
                    prop.reason = format!("{} (Nghi ngờ từ Mic {})", prop.reason, top.channel);
                }
            }
        }
        state.dispatch_proposal(prop, now);
    }
}

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
            commands::undo_panic_reset,
            commands::set_mode,
            commands::toggle_whitelist,
            commands::toggle_lock,
            commands::approve_proposal,
            commands::reject_proposal,
            commands::snooze_proposal,
            commands::apply_manual_notch,
            commands::trigger_demo_feedback,
            commands::take_snapshot,
            commands::rollback_snapshot,
            commands::release_notch,
            commands::clear_logs,
            commands::get_diagnostics,
            commands::start_audio_capture,
            commands::stop_audio_capture,
            commands::start_wizard,
            commands::stop_wizard,
            commands::get_wizard_status,
            commands::get_dynamics_suggestions,
            commands::toggle_dry_run,
            commands::export_report,
            commands::apply_preset,
            commands::set_talkover_config,
            commands::start_gain_calibration,
            commands::cancel_gain_calibration,
            commands::apply_channel_hpf,
        ])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            let state = app.state::<AppState>().inner().clone();

            tauri::async_runtime::spawn(async move {
                let mut interval = tokio::time::interval(std::time::Duration::from_millis(250));
                let mut tick_count: u64 = 0;

                loop {
                    interval.tick().await;
                    tick_count += 1;
                    let now = now_secs();

                    if tick_count % 2 == 0 {
                        run_auto_release_tick(&state, now);
                    }

                    let usb_running = state.audio_engine.lock().is_running()
                        && *state.active_audio_channels.lock() >= 2;
                    let fx_idx = state.talkover.lock().config.fx_return_channel.clamp(1, 4);
                    let fx_addr = format!("/fxrtn/{:02}/mix/fader", fx_idx);

                    let (rta_opt, meters_opt, cached_fx_fader) =
                        poll_and_merge_meters(&state, &fx_addr, usb_running, now);

                    if state.ringout.lock().is_active {
                        state.step_wizard(now);
                    }

                    if let Some(ref meters) = meters_opt {
                        if let Some((addr, val)) = state.pending_fader_restore.lock().take() {
                            state.send_fader_if_live(&addr, val);
                        }
                        process_lan_gain_and_talkover(&state, meters, usb_running, cached_fx_fader, now);
                    } else {
                        let mut tk = state.talkover.lock();
                        if tk.is_ducked {
                            tk.is_ducked = false;
                            let orig = tk.original_fader_val;
                            drop(tk);
                            *state.pending_fader_restore.lock() = Some((fx_addr, orig));
                        }
                    }

                    if !usb_running {
                        if let Some(ref rta) = rta_opt {
                            process_lan_rta_feedback(&state, rta, meters_opt.as_deref(), now);
                        }
                    }
                }
            });

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while building tauri application");
}
