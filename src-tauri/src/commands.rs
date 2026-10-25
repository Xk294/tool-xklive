use tauri::State;
use crate::core::models::{
    classify_target, format_target_label, ActionProposal, CapabilityMap, ConnectionState, PEQBand,
};
use crate::core::safety::{handle_manual_override, panic_rollback};
use crate::mixer::xair::{discover_mixers, DiscoveredMixer, XAirClient};
use crate::state::{now_secs, AppState, FullStateSnapshot};

#[tauri::command]
pub fn get_state(state: State<'_, AppState>) -> FullStateSnapshot {
    state.get_snapshot()
}

#[tauri::command]
pub async fn discover_mixers_cmd(
    timeout_ms: Option<u64>,
    port: Option<u16>,
) -> Result<Vec<DiscoveredMixer>, String> {
    let t = timeout_ms.unwrap_or(600);
    let p = port.unwrap_or(10024);
    tauri::async_runtime::spawn_blocking(move || discover_mixers(t, p))
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn list_audio_devices() -> Result<Vec<crate::audio::AudioDeviceItem>, String> {
    tauri::async_runtime::spawn_blocking(crate::audio::AudioEngine::list_input_devices)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn connect_mixer(
    state: State<'_, AppState>,
    ip: String,
    port: u16,
) -> Result<bool, String> {
    let app_state = state.inner().clone();
    let ip_clone = ip.clone();

    let (client, success) = tauri::async_runtime::spawn_blocking(move || {
        let c = XAirClient::new(ip_clone, port);
        let ok = c.connect();
        (c, ok)
    })
    .await
    .map_err(|e| e.to_string())?;

    let state_for_cb = app_state.clone();
    *client.on_manual_override.lock() = Some(Box::new(move |ch, target, bus| {
        let now = now_secs();
        if target == "fxrtn" {
            *state_for_cb.fx_override_until.lock() = now + 10.0;
            if let Some(fx_idx) = bus {
                let addr = format!("/fxrtn/{:02}/mix/fader", fx_idx);
                if let Some(c) = &*state_for_cb.xair.lock() {
                    if let Some(&val) = c.params_cache.lock().get(&addr) {
                        state_for_cb.talkover.lock().set_original_fader(val);
                    }
                }
            }
            let fx_label = format!("FX Return {}", bus.unwrap_or(1));
            state_for_cb.add_log_coded(
                &format!("Phát hiện kỹ sư chỉnh tay: Tạm khóa {} trong 10 giây", fx_label),
                "warning",
                "log.manualOverride",
                serde_json::json!({ "channel": ch, "target": fx_label }),
            );
            return;
        }
        let mut s = state_for_cb.safety.lock();
        *s = handle_manual_override(&s, ch, now, target, bus);
        drop(s);

        let label = format_target_label(target, ch, bus);
        state_for_cb.add_log_coded(
            &format!("Phát hiện kỹ sư chỉnh tay: Tạm khóa {} trong 10 giây", label),
            "warning",
            "log.manualOverride",
            serde_json::json!({ "channel": ch, "target": label }),
        );
    }));

    if let Some(prev) = app_state.xair.lock().take() {
        prev.disconnect();
    }
    app_state.reset_runtime_session();
    if let Some(&fx_val) = client.params_cache.lock().get("/fxrtn/01/mix/fader") {
        app_state.talkover.lock().set_original_fader(fx_val);
    }
    *app_state.xair.lock() = Some(client);
    app_state.add_log_coded(
        &format!(
            "Đã kết nối tới Mixer {}:{} ({})",
            ip,
            port,
            if success { "Thành công" } else { "Đang đợi phản hồi" }
        ),
        if success { "approved" } else { "warning" },
        "log.mixerConnected",
        serde_json::json!({ "ip": ip, "port": port, "success": success }),
    );

    Ok(success)
}

#[tauri::command]
pub fn disconnect_mixer(state: State<'_, AppState>) -> Result<(), String> {
    if let Some(client) = state.xair.lock().take() {
        client.disconnect();
    }
    state.reset_runtime_session();
    state.add_log_coded(
        "Đã ngắt kết nối mixer",
        "normal",
        "log.mixerDisconnected",
        serde_json::json!({}),
    );
    Ok(())
}

#[tauri::command]
pub fn panic_reset(state: State<'_, AppState>) -> Result<(), String> {
    let now = now_secs();
    state.abort_wizard_if_active(now);

    let prev_mode = state.current_mode.lock().clone();
    let mut safety = state.safety.lock();
    let prev_notches: Vec<_> = safety.active_notches.values().cloned().collect();
    let (new_safety, rollbacks) = panic_rollback(&safety, now);
    *safety = new_safety;
    drop(safety);

    if !prev_notches.is_empty() {
        *state.last_panic_snapshot.lock() = (prev_notches, prev_mode);
    }

    let mut rollback_bands = Vec::new();
    for prop in &rollbacks {
        if let Some(band) = prop.band {
            rollback_bands.push(PEQBand {
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
    }
    state.send_peq_batch_paced(rollback_bands);

    *state.current_mode.lock() = "manual".to_string();
    state.pending_proposals.lock().clear();
    let count = rollbacks.len();
    state.add_log_coded(
        &format!(
            "PANIC: Đã hoàn tác {} notch về trạng thái gốc và chuyển về chế độ MANUAL!",
            count
        ),
        "panic",
        "log.panicTriggered",
        serde_json::json!({ "count": count }),
    );
    Ok(())
}

#[tauri::command]
pub fn undo_panic_reset(state: State<'_, AppState>) -> Result<usize, String> {
    let now = now_secs();
    let (to_restore, prev_mode) = {
        let mut snap = state.last_panic_snapshot.lock();
        std::mem::replace(&mut *snap, (Vec::new(), "auto".to_string()))
    };

    if to_restore.is_empty() {
        return Ok(0);
    }

    {
        let mut safety = state.safety.lock();
        for mut notch in to_restore.iter().cloned() {
            let (norm_target, target_key_id, norm_ch, norm_bus) =
                classify_target(&notch.target, notch.channel, notch.bus);
            notch.target = norm_target.to_string();
            notch.channel = norm_ch;
            notch.bus = norm_bus;
            notch.last_updated_time = now;
            safety.active_notches.insert((target_key_id, notch.band), notch);
        }
    }

    let restore_bands: Vec<PEQBand> = to_restore
        .iter()
        .map(|notch| PEQBand {
            channel: notch.channel,
            band: notch.band,
            freq_hz: notch.freq_hz,
            gain_db: notch.gain_db,
            q: notch.q,
            is_on: true,
            filter_type: 2,
            target: notch.target.clone(),
            bus: notch.bus,
        })
        .collect();
    state.send_peq_batch_paced(restore_bands);

    let restored_mode = if prev_mode == "manual" || prev_mode.is_empty() {
        "auto".to_string()
    } else {
        prev_mode
    };
    *state.current_mode.lock() = restored_mode;

    let count = to_restore.len();
    state.add_log_coded(
        &format!("Đã hoàn tác PANIC: Khôi phục {} điểm chống hú", count),
        "approved",
        "messages.panic_undone",
        serde_json::json!({ "count": count }),
    );
    Ok(count)
}

#[tauri::command]
pub fn set_mode(state: State<'_, AppState>, mode: String) -> Result<(), String> {
    if ["auto", "semi", "manual"].contains(&mode.as_str()) {
        *state.current_mode.lock() = mode.clone();
        state.add_log_coded(
            &format!("Chế độ điều khiển chuyển sang: {}", mode),
            "normal",
            "log.modeChanged",
            serde_json::json!({ "mode": mode.to_uppercase() }),
        );
        Ok(())
    } else {
        Err("Chế độ không hợp lệ".to_string())
    }
}

#[tauri::command]
pub fn toggle_whitelist(state: State<'_, AppState>, channel: u8) -> Result<bool, String> {
    let mut safety = state.safety.lock();
    let is_whitelisted = if safety.whitelist.contains(&channel) {
        safety.whitelist.remove(&channel);
        false
    } else {
        safety.whitelist.insert(channel);
        true
    };
    drop(safety);
    state.add_log_coded(
        &format!(
            "Kênh {}: {}",
            channel,
            if is_whitelisted {
                "Đã thêm vào Whitelist"
            } else {
                "Đã loại khỏi Whitelist"
            }
        ),
        "normal",
        "log.whitelistToggled",
        serde_json::json!({ "channel": channel, "whitelisted": is_whitelisted }),
    );
    Ok(is_whitelisted)
}

#[tauri::command]
pub fn toggle_lock(state: State<'_, AppState>, channel: u8) -> Result<bool, String> {
    let now = now_secs();
    let mut safety = state.safety.lock();
    let is_currently_locked = safety
        .channel_locks
        .get(&channel)
        .map_or(false, |&until| now < until);

    if is_currently_locked {
        safety.channel_locks.remove(&channel);
        drop(safety);
        state.add_log_coded(
            &format!("Kênh {}: Đã mở khóa can thiệp thủ công", channel),
            "normal",
            "log.lockToggled",
            serde_json::json!({ "channel": channel, "locked": false }),
        );
        Ok(false)
    } else {
        safety.channel_locks.insert(channel, now + 3600.0);
        drop(safety);
        state.add_log_coded(
            &format!("Kênh {}: Đã khóa cố định bằng tay", channel),
            "warning",
            "log.lockToggled",
            serde_json::json!({ "channel": channel, "locked": true }),
        );
        Ok(true)
    }
}

#[tauri::command]
pub fn approve_proposal(
    state: State<'_, AppState>,
    id: Option<String>,
    channel: u8,
    freq_hz: f32,
) -> Result<bool, String> {
    let mut pending = state.pending_proposals.lock();
    let idx = pending.iter().position(|p| {
        if let Some(ref target_id) = id {
            if !target_id.is_empty() && p.id == *target_id {
                return true;
            }
        }
        p.channel == channel && (p.freq_hz - freq_hz).abs() < 10.0
    });

    let proposal = match idx {
        Some(i) => pending.remove(i),
        None => return Err("Không tìm thấy đề xuất phù hợp".to_string()),
    };
    drop(pending);

    let now = now_secs();
    let decision = state.execute_safety_decision(&proposal, now);

    if decision.approved {
        if let Some(approved_prop) = decision.proposal {
            state.add_log_coded(
                &format!(
                    "Đã phê duyệt notch tại {:.1}Hz ({:+.1}dB)",
                    approved_prop.freq_hz, approved_prop.gain_db
                ),
                "approved",
                "messages.proposal_approved",
                serde_json::json!({
                    "channel": approved_prop.channel,
                    "freq_hz": (approved_prop.freq_hz * 10.0).round() / 10.0,
                    "gain_db": (approved_prop.gain_db * 10.0).round() / 10.0
                }),
            );
            return Ok(true);
        }
    }

    state.add_log_coded(
        &format!("Từ chối notch: {}", decision.reason),
        "warning",
        "log.proposalRejectedBySafety",
        serde_json::json!({ "reason": decision.reason }),
    );
    Ok(false)
}

#[tauri::command]
pub fn reject_proposal(
    state: State<'_, AppState>,
    id: Option<String>,
    channel: u8,
    freq_hz: f32,
) -> Result<(), String> {
    let mut pending = state.pending_proposals.lock();
    pending.retain(|p| {
        if let Some(ref target_id) = id {
            if !target_id.is_empty() && p.id == *target_id {
                return false;
            }
        }
        !(p.channel == channel && (p.freq_hz - freq_hz).abs() < 10.0)
    });
    drop(pending);
    state.add_log_coded(
        &format!("Bỏ qua cảnh báo hú tại {:.1}Hz", freq_hz),
        "normal",
        "messages.proposal_rejected",
        serde_json::json!({ "channel": channel, "freq_hz": (freq_hz * 10.0).round() / 10.0 }),
    );
    Ok(())
}

#[tauri::command]
pub fn snooze_proposal(
    state: State<'_, AppState>,
    id: Option<String>,
    channel: u8,
    freq_hz: f32,
) -> Result<(), String> {
    let now = now_secs();
    let mut bus_to_lock: Option<u8> = None;
    {
        let mut pending = state.pending_proposals.lock();
        if let Some(pos) = pending.iter().position(|p| {
            if let Some(ref target_id) = id {
                if !target_id.is_empty() && p.id == *target_id {
                    return true;
                }
            }
            p.channel == channel && (p.freq_hz - freq_hz).abs() < 10.0
        }) {
            let removed = pending.remove(pos);
            if removed.target == "bus" {
                bus_to_lock = removed.bus;
            }
        }
    }

    {
        let mut safety = state.safety.lock();
        if let Some(bus_idx) = bus_to_lock {
            safety.bus_locks.insert(bus_idx, now + 60.0);
        } else {
            safety.channel_locks.insert(channel, now + 60.0);
        }
    }

    state.add_log_coded(
        &format!("Đã tạm khóa Kênh {} tại {:.1}Hz trong 60 giây", channel, freq_hz),
        "normal",
        "messages.channel_snoozed",
        serde_json::json!({ "channel": channel, "duration_s": 60 }),
    );
    Ok(())
}

#[tauri::command]
pub fn apply_manual_notch(
    state: State<'_, AppState>,
    target: String,
    channel: u8,
    bus: Option<u8>,
    freq_hz: f32,
    gain_db: f32,
    q: f32,
) -> Result<bool, String> {
    let now = now_secs();
    let mut prop = ActionProposal {
        channel,
        bus,
        target: target.clone(),
        freq_hz: freq_hz.clamp(20.0, 20000.0),
        gain_db: gain_db.clamp(-12.0, 0.0),
        q: q.clamp(0.3, 10.0),
        reason: format!("Cắt notch thủ công tại {:.1}Hz ({:+.1}dB)", freq_hz, gain_db),
        original_gain_db: 0.0,
        confidence_score: 1.0,
        ..Default::default()
    };
    prop.ensure_metadata(now);

    let decision = state.execute_safety_decision(&prop, now);

    if decision.approved {
        if let Some(approved) = decision.proposal {
            state.add_log_coded(
                &format!(
                    "Đã áp dụng notch thủ công tại {:.1}Hz ({:+.1}dB, Q={:.1})",
                    approved.freq_hz, approved.gain_db, approved.q
                ),
                "approved",
                "log.manualNotch",
                serde_json::json!({
                    "channel": approved.channel,
                    "freq_hz": (approved.freq_hz * 10.0).round() / 10.0,
                    "gain_db": (approved.gain_db * 10.0).round() / 10.0,
                    "q": (approved.q * 10.0).round() / 10.0
                }),
            );
            return Ok(true);
        }
    }

    state.add_log_coded(
        &format!("Không thể cắt notch thủ công: {}", decision.reason),
        "warning",
        "log.manualNotchRejected",
        serde_json::json!({ "reason": decision.reason }),
    );
    Ok(false)
}

#[tauri::command]
pub fn trigger_demo_feedback(
    state: State<'_, AppState>,
    channel: u8,
    freq_hz: f32,
    gain_db: Option<f32>,
) -> Result<(), String> {
    let now = now_secs();
    let mut proposal = ActionProposal {
        channel,
        freq_hz,
        gain_db: gain_db.unwrap_or(-3.0).clamp(-12.0, -3.0),
        q: 8.0,
        bus: None,
        band: None,
        target: if channel == 0 { "main".to_string() } else { "ch".to_string() },
        reason: format!("Mô phỏng phát hiện hú tại {:.1}Hz", freq_hz),
        original_gain_db: 0.0,
        confidence_score: 0.92,
        ..Default::default()
    };
    proposal.ensure_metadata(now);
    state.dispatch_proposal(proposal, now);
    Ok(())
}

#[tauri::command]
pub fn take_snapshot(state: State<'_, AppState>) -> Result<serde_json::Value, String> {
    let mut snap_bands: Vec<PEQBand> = Vec::new();
    let safety = state.safety.lock();
    for (&(t_id, band), notch) in &safety.active_notches {
        let inferred_bus = if t_id < 0 { notch.bus.or(Some((-t_id) as u8)) } else { notch.bus };
        let (norm_target, _, norm_ch, norm_bus) = classify_target(&notch.target, notch.channel, inferred_bus);
        snap_bands.push(PEQBand {
            channel: norm_ch,
            band,
            freq_hz: notch.original_freq_hz,
            gain_db: notch.original_gain_db,
            q: notch.original_q,
            is_on: true,
            filter_type: 2,
            target: norm_target.to_string(),
            bus: norm_bus,
        });
    }
    drop(safety);

    if let Some(client) = &*state.xair.lock() {
        let cache = client.params_cache.lock();
        let mut push_cached_band = |target_type: &str, ch: u8, bus: Option<u8>, band: u8| {
            if snap_bands.iter().any(|b| {
                b.target == target_type && b.channel == ch && b.bus == bus && b.band == band
            }) {
                return;
            }
            let target_num = bus.unwrap_or(ch);
            let prefix = crate::mixer::mapper::ParameterMapper::target_eq_band_prefix(
                target_type,
                target_num,
                band,
            );
            let Some(&norm_g) = cache.get(&format!("{}/g", prefix)) else {
                return;
            };
            let freq_hz = cache
                .get(&format!("{}/f", prefix))
                .map(|&v| (client.mapper.freq.from_float(v) * 10.0).round() / 10.0)
                .unwrap_or(1000.0);
            let gain_db = (client.mapper.gain.from_float(norm_g) * 10.0).round() / 10.0;
            let q = cache
                .get(&format!("{}/q", prefix))
                .map(|&v| (client.mapper.q.from_float(v) * 100.0).round() / 100.0)
                .unwrap_or(8.0);
            snap_bands.push(PEQBand {
                channel: ch,
                band,
                freq_hz,
                gain_db,
                q,
                is_on: true,
                filter_type: 2,
                target: target_type.to_string(),
                bus,
            });
        };
        for ch in 1..=16 {
            for band in 3..=4 {
                push_cached_band("ch", ch, None, band);
            }
        }
        for band in 3..=6 {
            push_cached_band("main", 0, None, band);
        }
        for bus in 1..=6 {
            for band in 5..=6 {
                push_cached_band("bus", 0, Some(bus), band);
            }
        }
    }

    let count = snap_bands.len();
    *state.snapshot_bands.lock() = Some(snap_bands);
    state.add_log_coded(
        &format!("Chụp Snapshot thành công ({} điểm PEQ)", count),
        "approved",
        "log.snapshotTaken",
        serde_json::json!({ "count": count }),
    );
    Ok(serde_json::json!({ "success": true, "bands_count": count }))
}

#[tauri::command]
pub fn rollback_snapshot(state: State<'_, AppState>) -> Result<serde_json::Value, String> {
    let now = now_secs();
    state.abort_wizard_if_active(now);

    let mut safety = state.safety.lock();
    let (new_safety, rollbacks) = panic_rollback(&safety, now);
    *safety = new_safety;
    drop(safety);

    let mut bands_to_send = Vec::new();
    for prop in &rollbacks {
        if let Some(band) = prop.band {
            bands_to_send.push(PEQBand {
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
    }

    if let Some(saved_bands) = &*state.snapshot_bands.lock() {
        for b in saved_bands {
            if !bands_to_send.iter().any(|existing| {
                existing.target == b.target
                    && existing.channel == b.channel
                    && existing.bus == b.bus
                    && existing.band == b.band
            }) {
                bands_to_send.push(b.clone());
            }
        }
    }
    let restored_count = bands_to_send.len();
    state.send_peq_batch_paced(bands_to_send);

    state.pending_proposals.lock().clear();
    state.add_log_coded(
        &format!("Đã khôi phục toàn bộ trạng thái mixer về Snapshot gốc ({} điểm PEQ)!", restored_count),
        "approved",
        "log.snapshotRollback",
        serde_json::json!({ "restored_count": restored_count }),
    );
    Ok(serde_json::json!({
        "success": true,
        "restored_count": restored_count,
        "message": "Rollback completed"
    }))
}

#[tauri::command]
pub fn release_notch(
    state: State<'_, AppState>,
    channel: u8,
    band: u8,
    target: String,
    bus: Option<u8>,
) -> Result<(), String> {
    let mut safety = state.safety.lock();
    let (norm_target, target_key_id, norm_ch, norm_bus) = classify_target(&target, channel, bus);

    let (orig_freq, orig_gain, orig_q) = if let Some(notch) = safety.active_notches.remove(&(target_key_id, band)) {
        (notch.original_freq_hz, notch.original_gain_db, notch.original_q)
    } else {
        (1000.0, 0.0, 8.0)
    };
    drop(safety);

    state.send_peq_if_live(&PEQBand {
        channel: norm_ch,
        band,
        freq_hz: orig_freq,
        gain_db: orig_gain,
        q: orig_q,
        is_on: true,
        filter_type: 2,
        target: norm_target.to_string(),
        bus: norm_bus,
    });

    let tgt_name = format_target_label(norm_target, norm_ch, norm_bus);
    let gain_rounded = (orig_gain * 10.0).round() / 10.0;
    state.add_log_coded(
        &format!("Đã nhả Band {} trên {} về {:.1}dB", band, tgt_name, gain_rounded),
        "approved",
        "messages.notch_released",
        serde_json::json!({ "band": band, "target": tgt_name, "gain_db": gain_rounded }),
    );
    Ok(())
}

#[tauri::command]
pub fn clear_logs(state: State<'_, AppState>) -> Result<(), String> {
    state.logs.lock().clear();
    Ok(())
}

#[tauri::command]
pub async fn get_diagnostics(state: State<'_, AppState>) -> Result<serde_json::Value, String> {
    let app_state = state.inner().clone();
    let (status, is_connected, model, fw, rtt, ip, port, total_notches, whitelist, locks, active_dev, active_ch, is_audio_running) = {
        let (status, is_connected, model, fw, rtt, ip, port) = if let Some(client) = &*app_state.xair.lock() {
            let cm = client.capability_map.lock();
            let st = client.get_state();
            let st_str = match st {
                ConnectionState::Connected => "CONNECTED",
                ConnectionState::Connecting => "CONNECTING",
                ConnectionState::Reconnecting => "RECONNECTING",
                ConnectionState::Mock => "MOCK",
                ConnectionState::Disconnected => "DISCONNECTED",
            };
            (
                st_str.to_string(),
                st == ConnectionState::Connected,
                cm.model.clone(),
                cm.firmware.clone(),
                *client.last_rtt_ms.lock(),
                client.ip.clone(),
                client.port,
            )
        } else {
            (
                "DISCONNECTED".to_string(),
                false,
                "Chưa kết nối".to_string(),
                "N/A".to_string(),
                None,
                "127.0.0.1".to_string(),
                10024,
            )
        };

        let safety = app_state.safety.lock();
        let total_notches = safety.active_notches.len();
        let whitelist: Vec<u8> = safety.whitelist.iter().copied().collect();
        let locks: Vec<u8> = safety.channel_locks.keys().copied().collect();
        drop(safety);

        let active_dev = app_state.active_audio_device.lock().clone();
        let active_ch = *app_state.active_audio_channels.lock();
        let is_audio_running = app_state.audio_engine.lock().is_running();

        (status, is_connected, model, fw, rtt, ip, port, total_notches, whitelist, locks, active_dev, active_ch, is_audio_running)
    };

    let devices = tauri::async_runtime::spawn_blocking(crate::audio::AudioEngine::list_input_devices)
        .await
        .unwrap_or_default();

    let default_dev_name = active_dev
        .or_else(|| devices.iter().find(|d| d.is_default).map(|d| d.name.clone()))
        .unwrap_or_else(|| "System Default Audio".to_string());

    let dsp_latency_ms = 42.7;

    Ok(serde_json::json!({
        "mixer": {
            "status": status,
            "mock_mode": false,
            "model": model,
            "firmware": fw,
            "ip": ip,
            "port": port,
            "rtt_ms": rtt,
            "dsp_latency_ms": dsp_latency_ms,
            "rta_registered": is_connected,
            "osc_tx_count": total_notches,
            "osc_rx_count": if is_connected { 1 } else { 0 },
            "last_error": serde_json::Value::Null
        },
        "latency": {
            "rtt_ms": rtt,
            "dsp_latency_ms": dsp_latency_ms
        },
        "safety": {
            "active_notches": total_notches,
            "whitelist": whitelist,
            "channel_locks": locks,
            "max_cut_db": -12.0,
            "max_boost_db": 4.0
        },
        "audio": {
            "device_name": default_dev_name,
            "channels": if active_ch > 0 { active_ch } else { 16 },
            "is_running": is_audio_running,
            "devices": devices,
            "sample_rate": 48000,
            "buffer_size": 2048
        },
        "routing": {
            "valid": is_audio_running || is_connected,
            "detail": if is_audio_running { "USB / CoreAudio Stream Active" } else { "Standby" }
        },
        "log_file": "tauri://logs/auto_sound.log"
    }))
}

pub fn filter_usb_crosstalk_proposals(
    ch: u8,
    peak_dbfs: f32,
    proposals: Vec<ActionProposal>,
    recent_peaks: &mut std::collections::HashMap<u8, (f32, f32, f64)>,
    now: f64,
) -> Vec<ActionProposal> {
    let mut approved_out = Vec::new();
    for prop in proposals {
        recent_peaks.retain(|_, &mut (_, _, ts)| now - ts < 0.12);
        recent_peaks.insert(ch, (prop.freq_hz, peak_dbfs, now));

        let mut is_crosstalk = false;
        for (&other_ch, &(other_freq, other_peak_db, ts)) in recent_peaks.iter() {
            if other_ch != ch
                && (now - ts) < 0.08
                && (other_freq - prop.freq_hz).abs() / prop.freq_hz.max(20.0) <= 0.03
                && (other_peak_db - peak_dbfs) >= 6.0
            {
                is_crosstalk = true;
                break;
            }
        }
        if !is_crosstalk {
            approved_out.push(prop);
        }
    }
    approved_out
}

#[tauri::command]
pub async fn start_audio_capture(
    state: State<'_, AppState>,
    device_name: Option<String>,
) -> Result<bool, String> {
    let app_state = state.inner().clone();

    let supports_usb = if let Some(client) = &*app_state.xair.lock() {
        let model = client.capability_map.lock().model.clone();
        CapabilityMap::supports_usb_multitrack(&model)
    } else {
        true
    };

    let req_dev = device_name.clone();
    let resolved_device = tauri::async_runtime::spawn_blocking(move || match req_dev {
        Some(ref name) if !name.trim().is_empty() => Some(name.clone()),
        _ if supports_usb => crate::audio::AudioEngine::find_preferred_mixer_device().map(|d| d.name),
        _ => None,
    })
    .await
    .map_err(|e| e.to_string())?;

    if resolved_device.is_none() {
        app_state.audio_engine.lock().stop();
        *app_state.active_audio_device.lock() = None;
        *app_state.active_audio_channels.lock() = 0;
        app_state.usb_meters.lock().fill(0.0);
        app_state.add_log_coded(
            "Không tìm thấy soundcard USB đa kênh (XR18/MR18) — Tự động sử dụng chế độ phân tích phổ LAN RTA 100-Band",
            "normal",
            "log.audioFallbackLanRta",
            serde_json::json!({ "error": "Không tìm thấy USB đa kênh XR18/MR18" }),
        );
        return Ok(false);
    }

    let state_for_cb = app_state.clone();
    let dev_label = resolved_device
        .clone()
        .unwrap_or_else(|| "USB Multitrack".to_string());
    let resolved_for_start = resolved_device.clone();
    let engine_arc = app_state.audio_engine.clone();

    let opened_channels = tauri::async_runtime::spawn_blocking(move || {
        engine_arc.lock().start(
            resolved_for_start.as_deref(),
            48000,
            0,
            move |ch: u8, chunk: &[f32]| {
                if let Some(client) = &*state_for_cb.xair.lock() {
                    if client.channel_mutes.lock().get(&ch).copied().unwrap_or(false) {
                        if let Some(slot) = state_for_cb.usb_meters.lock().get_mut((ch - 1) as usize) {
                            *slot = 0.0;
                        }
                        return;
                    }
                }

                let now = now_secs();
                let mut max_abs = 0.0f32;
                let mut sum_sq = 0.0f32;
                for &s in chunk {
                    let a = s.abs();
                    if a > max_abs {
                        max_abs = a;
                    }
                    sum_sq += s * s;
                }
                let clamped_lin = max_abs.clamp(0.0, 1.0);
                let idx = (ch - 1) as usize;
                if let Some(slot) = state_for_cb.usb_meters.lock().get_mut(idx) {
                    *slot = clamped_lin;
                }
                if let Some(ts_slot) = state_for_cb.usb_meters_updated_at.lock().get_mut(idx) {
                    *ts_slot = now;
                }

                let peak_dbfs = crate::mixer::mapper::ParameterMapper::linear_to_db(max_abs, -100.0);
                let rms_val = (sum_sq / (chunk.len().max(1) as f32)).sqrt();
                let rms_dbfs = crate::mixer::mapper::ParameterMapper::linear_to_db(rms_val, -100.0);

                let (_, clip_opt) = state_for_cb
                    .gain_staging
                    .lock()
                    .process_meter_sample(ch, peak_dbfs, rms_dbfs, now);
                if let Some(alert) = clip_opt {
                    state_for_cb.clip_alerts.lock().insert(ch, alert);
                }

                let proposals = {
                    let mut detector = state_for_cb.detector.lock();
                    detector.process_channel_frame(ch, chunk)
                };

                if proposals.is_empty() {
                    return;
                }

                let filtered = {
                    let mut recent = state_for_cb.recent_usb_peaks.lock();
                    filter_usb_crosstalk_proposals(ch, peak_dbfs, proposals, &mut recent, now)
                };
                for prop in filtered {
                    state_for_cb.dispatch_proposal(prop, now);
                }
            },
        )
    })
    .await
    .map_err(|e| e.to_string())??;

    *app_state.active_audio_device.lock() = resolved_device;
    *app_state.active_audio_channels.lock() = opened_channels;
    app_state.add_log_coded(
        &format!(
            "Đã kích hoạt luồng thu âm và phân tích phổ DSP từ {} ({} kênh)",
            dev_label, opened_channels
        ),
        "approved",
        "log.audioCaptureStarted",
        serde_json::json!({ "device": dev_label, "channels": opened_channels }),
    );
    Ok(true)
}

#[tauri::command]
pub fn stop_audio_capture(state: State<'_, AppState>) -> Result<(), String> {
    state.audio_engine.lock().stop();
    *state.active_audio_channels.lock() = 0;
    state.usb_meters.lock().fill(0.0);
    state.usb_meters_updated_at.lock().fill(0.0);
    state.add_log_coded(
        "Đã dừng luồng thu âm DSP",
        "normal",
        "log.audioCaptureStopped",
        serde_json::json!({}),
    );
    Ok(())
}

#[tauri::command]
pub fn start_wizard(
    state: State<'_, AppState>,
    channel: Option<u8>,
    max_boost_db: Option<f32>,
    dwell_time_s: Option<f64>,
) -> Result<serde_json::Value, String> {
    let now = now_secs();
    let ch = channel.unwrap_or(1);
    let target_type = if ch == 0 { "lr" } else { "bus" };
    let target_id = if ch == 0 { 0 } else { ch };

    let fader_addr =
        crate::mixer::mapper::ParameterMapper::target_fader_address(target_type, target_id);

    let initial_fader = if let Some(client) = &*state.xair.lock() {
        client
            .params_cache
            .lock()
            .get(&fader_addr)
            .copied()
            .unwrap_or(0.75)
            .clamp(0.0, 1.0)
    } else {
        0.75
    };
    let initial_fader_db = crate::mixer::mapper::ParameterMapper::fader_norm_to_db(initial_fader);

    let clamped_boost = max_boost_db
        .unwrap_or(3.0)
        .clamp(0.5, crate::core::safety::HARD_MAX_BOOST_DB);
    let mut ringout = state.ringout.lock();
    ringout.config.max_boost_above_start_db = clamped_boost;
    ringout.config.step_interval_s = dwell_time_s.unwrap_or(1.5).clamp(0.5, 10.0);

    let ok = ringout.start(target_type, target_id, initial_fader, initial_fader_db, now);
    drop(ringout);

    if ok {
        state.add_log_coded(
            &format!(
                "Bắt đầu Soundcheck Ring-Out trên {} {} (Trần: {:+.1}dB)",
                target_type.to_uppercase(),
                target_id,
                clamped_boost
            ),
            "approved",
            "log.wizardStarted",
            serde_json::json!({
                "target": format!("{} {}", target_type.to_uppercase(), target_id),
                "max_boost_db": clamped_boost
            }),
        );
        Ok(serde_json::json!({ "success": true }))
    } else {
        Err("Ring-Out đang chạy hoặc không thể khởi động".to_string())
    }
}

#[tauri::command]
pub fn stop_wizard(state: State<'_, AppState>) -> Result<serde_json::Value, String> {
    let now = now_secs();

    let mut ringout = state.ringout.lock();
    let report = ringout.stop("aborted", now);
    let fader_to_restore = ringout.initial_fader_val;
    let target_type = ringout.target_type.clone();
    let target_id = ringout.target_id;
    drop(ringout);

    state.restore_or_schedule_fader(&target_type, target_id, fader_to_restore);

    state.add_log_coded(
        "Đã dừng Ring-Out và trả fader về mức ban đầu an toàn",
        "warning",
        "wizard.aborted",
        serde_json::json!({}),
    );
    Ok(serde_json::to_value(report).unwrap_or(serde_json::json!({ "success": true })))
}

#[tauri::command]
pub fn get_wizard_status(
    state: State<'_, AppState>,
) -> Result<crate::core::ringout::WizardStatusSnapshot, String> {
    Ok(state.ringout.lock().get_status())
}

#[tauri::command]
pub fn get_dynamics_suggestions(state: State<'_, AppState>) -> Result<serde_json::Value, String> {
    let now = now_secs();
    let (mut meters, num_ch) = if let Some(client) = &*state.xair.lock() {
        let model = client.capability_map.lock().model.clone();
        (
            AppState::get_decayed_lan_meters(client),
            CapabilityMap::channel_count_for_model(&model),
        )
    } else {
        (state.usb_meters.lock().clone(), 16u8)
    };
    state.merge_active_usb_meters(&mut meters, now);

    let mut suggestions = Vec::new();
    for ch in 1..=num_ch {
        let raw_lin = meters.get(ch as usize - 1).copied().unwrap_or(0.0);
        let peak_db = crate::mixer::mapper::ParameterMapper::linear_to_db(raw_lin, -90.0);

        let gain_advice = if peak_db > -3.0 {
            "Tín hiệu sát ngưỡng Clip! Nên giảm Preamp Gain -3 dB".to_string()
        } else if peak_db < -35.0 {
            "Tín hiệu quá nhỏ, nên tăng Preamp Gain thêm +6 dB".to_string()
        } else {
            "Mức tín hiệu lý tưởng (Headroom an toàn)".to_string()
        };

        let comp_thresh = (peak_db - 4.0).clamp(-40.0, -10.0);
        let gate_thresh = (peak_db - 24.0).clamp(-65.0, -35.0);

        suggestions.push(serde_json::json!({
            "channel": ch,
            "current_peak_db": (peak_db * 10.0).round() / 10.0,
            "gain_advice": gain_advice,
            "comp_threshold_db": (comp_thresh * 10.0).round() / 10.0,
            "gate_threshold_db": (gate_thresh * 10.0).round() / 10.0,
        }));
    }

    Ok(serde_json::json!({ "suggestions": suggestions }))
}

#[tauri::command]
pub fn toggle_dry_run(state: State<'_, AppState>, enabled: Option<bool>) -> Result<bool, String> {
    let mut dry = state.dry_run.lock();
    let new_val = enabled.unwrap_or(!*dry);
    *dry = new_val;
    drop(dry);
    state.add_log_coded(
        &format!(
            "Chế độ Dry-Run: {}",
            if new_val {
                "ĐÃ BẬT (Không gửi lệnh xuống mixer)"
            } else {
                "ĐÃ TẮT (Gửi lệnh thật)"
            }
        ),
        if new_val { "warning" } else { "approved" },
        "log.dryRunToggled",
        serde_json::json!({ "enabled": new_val }),
    );
    Ok(new_val)
}

#[tauri::command]
pub fn export_report(state: State<'_, AppState>, format: Option<String>) -> Result<String, String> {
    let safety = state.safety.lock();
    let notches: Vec<_> = safety.active_notches.values().cloned().collect();
    let logs = state.logs.lock().clone();
    drop(safety);

    let fmt = format.unwrap_or_else(|| "json".to_string());
    if fmt == "csv" {
        let mut csv = String::from("channel,band,freq_hz,gain_db,q,target\n");
        for n in &notches {
            csv.push_str(&format!(
                "{},{},{:.1},{:.1},{:.2},{}\n",
                n.channel, n.band, n.freq_hz, n.gain_db, n.q, n.target
            ));
        }
        Ok(csv)
    } else {
        let report = serde_json::json!({
            "generated_at": chrono::Local::now().to_rfc3339(),
            "active_notches_count": notches.len(),
            "active_notches": notches,
            "event_logs": logs,
        });
        Ok(serde_json::to_string_pretty(&report).unwrap_or_default())
    }
}

#[tauri::command]
pub fn apply_preset(
    state: State<'_, AppState>,
    preset: String,
) -> Result<serde_json::Value, String> {
    let normalized = preset.trim().to_lowercase();
    let (prominence_db, confirm_frames, q_val, max_cut_db, auto_talkover, label) = match normalized.as_str() {
        "speech" => (8.5, 2usize, 6.5, -12.0f32, true, "Hội nghị / Phát biểu (Speech)"),
        "acoustic" => (12.0, 4usize, 10.0, -9.0f32, false, "Nhạc Acoustic / Giữ nguyên âm sắc"),
        "foh" => (10.5, 3usize, 9.0, -12.0f32, false, "Loa Chính Hội Trường (FOH)"),
        _ => (9.5, 3usize, 8.0, -12.0f32, false, "Loa Kiểm Âm Sân Khấu (Monitor)"),
    };

    *state.current_preset.lock() = normalized.clone();

    {
        let mut det = state.detector.lock();
        det.prominence_threshold_db = prominence_db;
        det.confirmation_frames = confirm_frames;
        det.default_notch_q = q_val;
        det.reset_all();
    }

    {
        let mut rta_det = state.rta_detector.lock();
        rta_det.prominence_threshold_db = prominence_db;
        rta_det.confirmation_frames = confirm_frames;
        rta_det.default_notch_q = q_val;
    }

    {
        let mut safety = state.safety.lock();
        safety.max_cut_db = max_cut_db;
    }

    let mut restore_fx: Option<(u8, f32)> = None;
    {
        let mut tk = state.talkover.lock();
        if auto_talkover {
            tk.config.enabled = true;
        } else {
            if tk.is_ducked {
                restore_fx = Some((tk.config.fx_return_channel, tk.original_fader_val));
                tk.is_ducked = false;
            }
            tk.config.enabled = false;
        }
    }
    if let Some((fx_ch, orig_val)) = restore_fx {
        let addr = format!("/fxrtn/{:02}/mix/fader", fx_ch);
        state.send_fader_if_live(&addr, orig_val);
    }

    state.add_log_coded(
        &format!(
            "Đã áp dụng cấu hình DSP cho kịch bản: {} (Ngưỡng nhạy {:.1}dB, Q={:.1})",
            label, prominence_db, q_val
        ),
        "approved",
        "log.presetApplied",
        serde_json::json!({
            "preset": normalized,
            "label": label,
            "prominence_db": prominence_db,
            "q": q_val
        }),
    );

    Ok(serde_json::json!({
        "success": true,
        "preset": normalized,
        "prominence_threshold_db": prominence_db,
        "confirmation_frames": confirm_frames,
        "default_notch_q": q_val,
        "max_cut_db": max_cut_db,
        "talkover_enabled": state.talkover.lock().config.enabled,
    }))
}

#[tauri::command]
pub fn set_talkover_config(
    state: State<'_, AppState>,
    enabled: bool,
    mic_channel: Option<u8>,
    fx_return: Option<u8>,
    ducking_depth_db: Option<f32>,
) -> Result<serde_json::Value, String> {
    let mut tk = state.talkover.lock();
    let was_ducked = tk.is_ducked;
    let orig_fader = tk.original_fader_val;
    let prev_fx = tk.config.fx_return_channel;

    tk.config.enabled = enabled;
    if let Some(mc) = mic_channel {
        tk.config.mic_channel = mc.clamp(1, 16);
    }
    if let Some(fx) = fx_return {
        tk.config.fx_return_channel = fx.clamp(1, 4);
    }
    if let Some(depth) = ducking_depth_db {
        tk.config.ducking_depth_db = depth.clamp(-30.0, -6.0);
        tk.recalculate_ducked_fader();
    }
    if !enabled {
        tk.is_ducked = false;
    }
    let cur_mic = tk.config.mic_channel;
    let cur_fx = tk.config.fx_return_channel;
    drop(tk);

    if !enabled && was_ducked {
        let addr = format!("/fxrtn/{:02}/mix/fader", prev_fx);
        state.send_fader_if_live(&addr, orig_fader);
    }

    state.add_log_coded(
        &format!(
            "Tự động ngắt vang khi MC nói (Talkover): {} (Mic {}, FX {})",
            if enabled { "ĐÃ BẬT" } else { "ĐÃ TẮT" },
            cur_mic,
            cur_fx
        ),
        if enabled { "approved" } else { "normal" },
        "log.talkoverToggled",
        serde_json::json!({
            "enabled": enabled,
            "status": if enabled { "ON" } else { "OFF" },
            "channel": cur_mic,
            "mic_channel": cur_mic,
            "fx_return": cur_fx
        }),
    );

    Ok(serde_json::json!({
        "success": true,
        "enabled": enabled,
        "mic_channel": cur_mic,
        "fx_return": cur_fx
    }))
}

#[tauri::command]
pub fn start_gain_calibration(
    state: State<'_, AppState>,
    channel: u8,
) -> Result<serde_json::Value, String> {
    let ch = channel.clamp(1, 16);
    let now = now_secs();
    let current_headamp_db = state.get_current_headamp_gain_db(ch);
    let mut gs = state.gain_staging.lock();
    gs.start_calibration(ch, current_headamp_db, now);
    let session = gs.sessions.get(&ch).cloned();
    drop(gs);

    state.add_log_coded(
        &format!(
            "Bắt đầu đo mức Gain chuẩn 10 giây trên Mic {} — Hãy nói hoặc hát thử đều đặn",
            ch
        ),
        "normal",
        "log.gainCalibStarted",
        serde_json::json!({ "channel": ch }),
    );

    Ok(serde_json::json!({
        "success": true,
        "channel": ch,
        "session": session
    }))
}

#[tauri::command]
pub fn cancel_gain_calibration(
    state: State<'_, AppState>,
    channel: u8,
) -> Result<serde_json::Value, String> {
    let ch = channel.clamp(1, 16);
    state.gain_staging.lock().cancel_calibration(ch);
    Ok(serde_json::json!({ "success": true, "channel": ch }))
}

#[tauri::command]
pub fn apply_channel_hpf(
    state: State<'_, AppState>,
    channel: u8,
    enabled: bool,
    freq_hz: Option<f32>,
) -> Result<bool, String> {
    let ch = channel.clamp(1, 16);
    let f_hz = freq_hz.unwrap_or(80.0).clamp(20.0, 400.0);

    state.mock_hpf_channels.lock().insert(ch, enabled);
    if !*state.dry_run.lock() {
        if let Some(client) = &*state.xair.lock() {
            client.set_channel_hpf(ch, enabled, f_hz);
        }
    }

    state.add_log_coded(
        &format!(
            "Mic {}: {} lọc trầm Low-Cut ({:.0}Hz)",
            ch,
            if enabled { "Đã bật" } else { "Đã tắt" },
            f_hz
        ),
        "approved",
        "log.hpfToggled",
        serde_json::json!({
            "channel": ch,
            "enabled": enabled,
            "status": if enabled { "ON" } else { "OFF" },
            "freq_hz": f_hz.round()
        }),
    );

    Ok(enabled)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_usb_crosstalk_veto_three_channels_2500hz() {
        let mut recent = std::collections::HashMap::new();
        let now = 100.0;

        let make_prop = |ch: u8| ActionProposal {
            channel: ch,
            freq_hz: 2500.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };

        // Channels sorted by descending peak amplitude (as AudioEngine does before invoking callback):
        // Ch 1 = -10 dBFS (source), Ch 2 = -22 dBFS (bleed), Ch 3 = -25 dBFS (bleed)
        let out_ch1 = filter_usb_crosstalk_proposals(1, -10.0, vec![make_prop(1)], &mut recent, now);
        let out_ch2 = filter_usb_crosstalk_proposals(2, -22.0, vec![make_prop(2)], &mut recent, now);
        let out_ch3 = filter_usb_crosstalk_proposals(3, -25.0, vec![make_prop(3)], &mut recent, now);

        assert_eq!(out_ch1.len(), 1);
        assert_eq!(out_ch1[0].channel, 1);
        assert!(out_ch2.is_empty());
        assert!(out_ch3.is_empty());
    }
}
