use tauri::State;
use crate::core::models::{ActionProposal, PEQBand};
use crate::core::safety::{decide, panic_rollback};
use crate::mixer::xair::{discover_mixers, DiscoveredMixer, XAirClient};
use crate::state::{AppState, FullStateSnapshot};

#[tauri::command]
pub fn get_state(state: State<AppState>) -> FullStateSnapshot {
    state.get_snapshot()
}

#[tauri::command]
pub fn discover_mixers_cmd(timeout_ms: Option<u64>, port: Option<u16>) -> Vec<DiscoveredMixer> {
    discover_mixers(timeout_ms.unwrap_or(600), port.unwrap_or(10024))
}

#[tauri::command]
pub fn list_audio_devices() -> Vec<crate::audio::AudioDeviceItem> {
    crate::audio::AudioEngine::list_input_devices()
        .into_iter()
        .map(|d| crate::audio::AudioDeviceItem {
            name: d.name,
            is_default: d.is_default,
        })
        .collect()
}

#[tauri::command]
pub fn connect_mixer(state: State<AppState>, ip: String, port: u16) -> Result<bool, String> {
    let client = XAirClient::new(ip.clone(), port);
    let success = client.connect();

    // Register manual override callback
    let safety_clone = state.safety.clone();
    let logs_clone = state.logs.clone();
    let counter_clone = state.log_counter.clone();

    *client.on_manual_override.lock() = Some(Box::new(move |ch, target, bus| {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();
        let mut s = safety_clone.lock();
        *s = crate::core::safety::handle_manual_override(&s, ch, now, target, bus);

        let mut counter = counter_clone.lock();
        let id = *counter;
        *counter += 1;
        let time_str = chrono::Local::now().format("%H:%M:%S").to_string();
        logs_clone.lock().push(crate::core::models::LogEntry {
            id,
            time: time_str,
            text: format!("Phát hiện kỹ sư chỉnh tay: Tạm khóa kênh {} trong 10 giây", ch),
            entry_type: "warning".to_string(),
        });
    }));

    *state.xair.lock() = Some(client);
    state.add_log(
        &format!("Đã kết nối tới Mixer {}:{} ({})", ip, port, if success { "Thành công" } else { "Đang đợi phản hồi" }),
        if success { "approved" } else { "warning" },
    );

    Ok(success)
}

#[tauri::command]
pub fn disconnect_mixer(state: State<AppState>) -> Result<(), String> {
    if let Some(client) = state.xair.lock().take() {
        client.disconnect();
    }
    state.add_log("Đã ngắt kết nối mixer", "normal");
    Ok(())
}

#[tauri::command]
pub fn panic_reset(state: State<AppState>) -> Result<(), String> {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64();

    let mut safety = state.safety.lock();
    let (new_safety, rollbacks) = panic_rollback(&safety, now);
    *safety = new_safety;

    // Send reset commands to mixer
    if let Some(client) = &*state.xair.lock() {
        for prop in &rollbacks {
            if let Some(band) = prop.band {
                client.set_peq(&PEQBand {
                    channel: prop.channel,
                    band,
                    freq_hz: prop.freq_hz,
                    gain_db: prop.gain_db,
                    q: prop.q,
                    is_on: true,
                    filter_type: 2,
                });
            }
        }
    }

    state.pending_proposals.lock().clear();
    state.add_log(
        &format!("PANIC: Đã hoàn tác {} notch về trạng thái gốc của mixer!", rollbacks.len()),
        "panic",
    );
    Ok(())
}

#[tauri::command]
pub fn set_mode(state: State<AppState>, mode: String) -> Result<(), String> {
    if ["auto", "semi", "manual"].contains(&mode.as_str()) {
        *state.current_mode.lock() = mode.clone();
        state.add_log(&format!("Chế độ điều khiển chuyển sang: {}", mode), "normal");
        Ok(())
    } else {
        Err("Chế độ không hợp lệ".to_string())
    }
}

#[tauri::command]
pub fn toggle_whitelist(state: State<AppState>, channel: u8) -> Result<bool, String> {
    let mut safety = state.safety.lock();
    let is_whitelisted = if safety.whitelist.contains(&channel) {
        safety.whitelist.remove(&channel);
        false
    } else {
        safety.whitelist.insert(channel);
        true
    };
    state.add_log(
        &format!("Kênh {}: {}", channel, if is_whitelisted { "Đã thêm vào Whitelist" } else { "Đã loại khỏi Whitelist" }),
        "normal",
    );
    Ok(is_whitelisted)
}

#[tauri::command]
pub fn toggle_lock(state: State<AppState>, channel: u8) -> Result<bool, String> {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64();
    let mut safety = state.safety.lock();
    let is_currently_locked = safety.channel_locks.get(&channel).map_or(false, |&until| now < until);

    if is_currently_locked {
        safety.channel_locks.remove(&channel);
        state.add_log(&format!("Kênh {}: Đã mở khóa can thiệp thủ công", channel), "normal");
        Ok(false)
    } else {
        safety.channel_locks.insert(channel, now + 3600.0); // Lock 1 hour manually
        state.add_log(&format!("Kênh {}: Đã khóa cố định bằng tay", channel), "warning");
        Ok(true)
    }
}

#[tauri::command]
pub fn approve_proposal(state: State<AppState>, channel: u8, freq_hz: f32) -> Result<bool, String> {
    let mut pending = state.pending_proposals.lock();
    let idx = pending.iter().position(|p| p.channel == channel && (p.freq_hz - freq_hz).abs() < 5.0);

    let proposal = match idx {
        Some(i) => pending.remove(i),
        None => return Err("Không tìm thấy đề xuất phù hợp".to_string()),
    };

    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64();

    let mut safety = state.safety.lock();
    let (new_safety, decision) = decide(&safety, &proposal, now, None);
    *safety = new_safety;

    if decision.approved {
        if let Some(approved_prop) = decision.proposal {
            if let Some(client) = &*state.xair.lock() {
                if let Some(band) = approved_prop.band {
                    client.set_peq(&PEQBand {
                        channel: approved_prop.channel,
                        band,
                        freq_hz: approved_prop.freq_hz,
                        gain_db: approved_prop.gain_db,
                        q: approved_prop.q,
                        is_on: true,
                        filter_type: 2,
                    });
                }
            }
            state.add_log(
                &format!("Đã phê duyệt notch Kênh {} tại {:.1}Hz ({:+.1}dB)", channel, freq_hz, approved_prop.gain_db),
                "approved",
            );
            return Ok(true);
        }
    }

    state.add_log(&format!("Từ chối notch: {}", decision.reason), "warning");
    Ok(false)
}

#[tauri::command]
pub fn reject_proposal(state: State<AppState>, channel: u8, freq_hz: f32) -> Result<(), String> {
    let mut pending = state.pending_proposals.lock();
    pending.retain(|p| !(p.channel == channel && (p.freq_hz - freq_hz).abs() < 5.0));
    state.add_log(&format!("Bỏ qua cảnh báo hú Kênh {} tại {:.1}Hz", channel, freq_hz), "normal");
    Ok(())
}

#[tauri::command]
pub fn trigger_demo_feedback(state: State<AppState>, channel: u8, freq_hz: f32) -> Result<(), String> {
    let proposal = ActionProposal {
        channel,
        freq_hz,
        gain_db: -3.0,
        q: 8.0,
        bus: None,
        band: None,
        target: "ch".to_string(),
        reason: format!("Mô phỏng phát hiện hú tại {:.1}Hz", freq_hz),
        original_gain_db: 0.0,
    };

    let mode = state.current_mode.lock().clone();
    if mode == "auto" {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs_f64();
        let mut safety = state.safety.lock();
        let (new_safety, decision) = decide(&safety, &proposal, now, None);
        *safety = new_safety;

        if decision.approved {
            if let Some(approved_prop) = decision.proposal {
                if let Some(client) = &*state.xair.lock() {
                    if let Some(band) = approved_prop.band {
                        client.set_peq(&PEQBand {
                            channel: approved_prop.channel,
                            band,
                            freq_hz: approved_prop.freq_hz,
                            gain_db: approved_prop.gain_db,
                            q: approved_prop.q,
                            is_on: true,
                            filter_type: 2,
                        });
                    }
                }
                state.add_log(
                    &format!("[AUTO] Tự động dập notch Kênh {} tại {:.1}Hz ({:+.1}dB)", channel, freq_hz, approved_prop.gain_db),
                    "approved",
                );
            }
        }
    } else {
        state.pending_proposals.lock().push(proposal);
        state.add_log(
            &format!("Cảnh báo hú: Phát hiện tần số {:.1}Hz trên Kênh {}", freq_hz, channel),
            "warning",
        );
    }

    Ok(())
}
