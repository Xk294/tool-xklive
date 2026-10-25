use std::sync::Arc;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

use crate::audio::AudioEngine;
use crate::core::models::{
    format_target_label_with_reason, ActionProposal, ActiveNotch, ChannelInfo, ConnectionState,
    LogEntry, PEQBand,
};
use crate::core::ringout::RingOutController;
use crate::core::safety::{decide, SafetyState};
use crate::dsp::detector::FeedbackDetector;
use crate::dsp::gain_staging::GainStagingManager;
use crate::dsp::localizer::TwoFactorLocalizer;
use crate::dsp::rta_detector::RTADetector;
use crate::dsp::talkover::TalkoverController;
use crate::mixer::xair::XAirClient;

pub const METER_DECAY_TTL_SECS: f64 = 0.75;

pub fn now_secs() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FullStateSnapshot {
    pub mixer_status: ConnectionState,
    pub dry_run: bool,
    pub mixer_model: String,
    pub latency_ms: f32,
    pub rtt_ms: Option<f32>,
    pub dsp_latency_ms: f32,
    pub current_mode: String,
    pub current_preset: String,
    pub audio_mode: String,
    pub talkover_enabled: bool,
    pub talkover_is_ducked: bool,
    pub talkover_mic_channel: u8,
    pub active_notches: Vec<ActiveNotch>,
    pub pending_proposals: Vec<ActionProposal>,
    pub channels: Vec<ChannelInfo>,
    pub meters: Vec<f32>,
    pub rta_bins: Vec<f32>,
    pub clip_alerts: Vec<crate::dsp::gain_staging::ClipAlert>,
    pub gain_sessions: std::collections::HashMap<u8, crate::dsp::gain_staging::GainCalibrationSession>,
    pub event_logs: Vec<LogEntry>,
}

#[derive(Clone)]
pub struct AppState {
    pub xair: Arc<Mutex<Option<XAirClient>>>,
    pub safety: Arc<Mutex<SafetyState>>,
    pub detector: Arc<Mutex<FeedbackDetector>>,
    pub audio_engine: Arc<Mutex<AudioEngine>>,
    pub active_audio_device: Arc<Mutex<Option<String>>>,
    pub active_audio_channels: Arc<Mutex<u16>>,
    pub current_mode: Arc<Mutex<String>>,
    pub current_preset: Arc<Mutex<String>>,
    pub dry_run: Arc<Mutex<bool>>,
    pub logs: Arc<Mutex<Vec<LogEntry>>>,
    pub pending_proposals: Arc<Mutex<Vec<ActionProposal>>>,
    pub log_counter: Arc<Mutex<u64>>,
    pub snapshot_bands: Arc<Mutex<Option<Vec<PEQBand>>>>,
    pub peq_batch_generation: Arc<std::sync::atomic::AtomicU64>,
    pub pending_fader_restore: Arc<Mutex<Option<(String, f32)>>>,
    pub ringout: Arc<Mutex<RingOutController>>,
    pub localizer: Arc<Mutex<TwoFactorLocalizer>>,
    pub rta_detector: Arc<Mutex<RTADetector>>,
    pub gain_staging: Arc<Mutex<GainStagingManager>>,
    pub talkover: Arc<Mutex<TalkoverController>>,
    pub clip_alerts: Arc<Mutex<std::collections::HashMap<u8, crate::dsp::gain_staging::ClipAlert>>>,
    pub mock_hpf_channels: Arc<Mutex<std::collections::HashMap<u8, bool>>>,
    pub fx_override_until: Arc<Mutex<f64>>,
    pub recent_usb_peaks: Arc<Mutex<std::collections::HashMap<u8, (f32, f32, f64)>>>,
    pub usb_meters: Arc<Mutex<Vec<f32>>>,
    pub usb_meters_updated_at: Arc<Mutex<Vec<f64>>>,
    pub last_panic_snapshot: Arc<Mutex<(Vec<ActiveNotch>, String)>>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            xair: Arc::new(Mutex::new(None)),
            safety: Arc::new(Mutex::new(SafetyState::default())),
            detector: Arc::new(Mutex::new(FeedbackDetector::default_config())),
            audio_engine: Arc::new(Mutex::new(AudioEngine::new())),
            active_audio_device: Arc::new(Mutex::new(None)),
            active_audio_channels: Arc::new(Mutex::new(0)),
            current_mode: Arc::new(Mutex::new("auto".to_string())),
            current_preset: Arc::new(Mutex::new("monitor".to_string())),
            dry_run: Arc::new(Mutex::new(false)),
            logs: Arc::new(Mutex::new(Vec::new())),
            pending_proposals: Arc::new(Mutex::new(Vec::new())),
            log_counter: Arc::new(Mutex::new(1)),
            snapshot_bands: Arc::new(Mutex::new(None)),
            peq_batch_generation: Arc::new(std::sync::atomic::AtomicU64::new(0)),
            pending_fader_restore: Arc::new(Mutex::new(None)),
            ringout: Arc::new(Mutex::new(RingOutController::new(None))),
            localizer: Arc::new(Mutex::new(TwoFactorLocalizer::new())),
            rta_detector: Arc::new(Mutex::new(RTADetector::new(100, 20.0, 20000.0))),
            gain_staging: Arc::new(Mutex::new(GainStagingManager::new())),
            talkover: Arc::new(Mutex::new(TalkoverController::new(None))),
            clip_alerts: Arc::new(Mutex::new(std::collections::HashMap::new())),
            mock_hpf_channels: Arc::new(Mutex::new(std::collections::HashMap::new())),
            fx_override_until: Arc::new(Mutex::new(0.0)),
            recent_usb_peaks: Arc::new(Mutex::new(std::collections::HashMap::new())),
            usb_meters: Arc::new(Mutex::new(vec![0.0; 18])),
            usb_meters_updated_at: Arc::new(Mutex::new(vec![0.0; 18])),
            last_panic_snapshot: Arc::new(Mutex::new((Vec::new(), "auto".to_string()))),
        }
    }

    pub fn add_log_coded(
        &self,
        text: &str,
        entry_type: &str,
        text_code: &str,
        params: serde_json::Value,
    ) {
        self.add_log_entry(text, entry_type, Some(text_code.to_string()), Some(params));
    }

    fn add_log_entry(
        &self,
        text: &str,
        entry_type: &str,
        text_code: Option<String>,
        params: Option<serde_json::Value>,
    ) {
        let mut counter = self.log_counter.lock();
        let id = *counter;
        *counter += 1;

        let now = chrono::Local::now().format("%H:%M:%S").to_string();
        let mut logs = self.logs.lock();
        logs.push(LogEntry {
            id,
            time: now,
            text: text.to_string(),
            entry_type: entry_type.to_string(),
            text_code,
            params,
        });
        if logs.len() > 100 {
            logs.remove(0);
        }
    }

    pub fn send_peq_unbatched(&self, band: &PEQBand) {
        if *self.dry_run.lock() {
            return;
        }
        if let Some(client) = &*self.xair.lock() {
            client.set_peq(band);
        }
    }

    pub fn send_peq_if_live(&self, band: &PEQBand) {
        self.peq_batch_generation
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        self.send_peq_unbatched(band);
    }

    pub fn send_fader_if_live(&self, addr: &str, val: f32) {
        if *self.dry_run.lock() {
            return;
        }
        if let Some(client) = &*self.xair.lock() {
            client.send_fader(addr, val);
        }
    }

    pub fn send_peq_batch_paced(&self, bands: Vec<PEQBand>) {
        if bands.is_empty() || *self.dry_run.lock() {
            return;
        }
        let batch_gen = self
            .peq_batch_generation
            .fetch_add(1, std::sync::atomic::Ordering::SeqCst)
            + 1;
        let max_immediate = 2usize;
        let now = now_secs();
        {
            let mut safety = self.safety.lock();
            for _ in 0..bands.len().min(max_immediate) {
                safety.transaction_history.push(now);
            }
        }
        for band in bands.iter().take(max_immediate) {
            self.send_peq_unbatched(band);
        }
        if bands.len() > max_immediate {
            let remaining: Vec<PEQBand> = bands.into_iter().skip(max_immediate).collect();
            let state_clone = self.clone();
            tauri::async_runtime::spawn(async move {
                for chunk in remaining.chunks(2) {
                    tokio::time::sleep(std::time::Duration::from_millis(520)).await;
                    if state_clone
                        .peq_batch_generation
                        .load(std::sync::atomic::Ordering::SeqCst)
                        != batch_gen
                    {
                        break;
                    }
                    let chunk_now = now_secs();
                    {
                        let mut safety = state_clone.safety.lock();
                        for _ in 0..chunk.len() {
                            safety.transaction_history.push(chunk_now);
                        }
                    }
                    for b in chunk {
                        state_clone.send_peq_unbatched(b);
                    }
                }
            });
        }
    }

    pub fn reset_runtime_session(&self) {
        {
            let mut safety = self.safety.lock();
            safety.active_notches.clear();
            safety.channel_locks.clear();
            safety.bus_locks.clear();
            safety.transaction_history.clear();
        }
        self.pending_proposals.lock().clear();
        self.clip_alerts.lock().clear();
        self.gain_staging.lock().sessions.clear();
        self.recent_usb_peaks.lock().clear();
        self.usb_meters.lock().fill(0.0);
        self.usb_meters_updated_at.lock().fill(0.0);
        *self.last_panic_snapshot.lock() = (Vec::new(), "auto".to_string());
    }

    pub fn merge_active_usb_meters(&self, meters: &mut [f32], now: f64) {
        let usb_running = self.audio_engine.lock().is_running() && *self.active_audio_channels.lock() >= 2;
        if !usb_running {
            return;
        }
        let mut usb_m = self.usb_meters.lock();
        let updated_at = self.usb_meters_updated_at.lock();
        for (i, slot) in usb_m.iter_mut().enumerate() {
            let age = (now - updated_at.get(i).copied().unwrap_or(0.0)).max(0.0);
            if age > METER_DECAY_TTL_SECS {
                *slot = 0.0;
            }
            if i < meters.len() && *slot > meters[i] {
                meters[i] = *slot;
            }
        }
    }

    pub fn get_decayed_lan_meters(client: &XAirClient) -> Vec<f32> {
        let mut meters = client.meter_levels.lock().clone();
        let stale = client
            .meter_levels_updated_at
            .lock()
            .map_or(false, |inst| {
                inst.elapsed() > std::time::Duration::from_secs_f64(METER_DECAY_TTL_SECS)
            });
        if stale {
            meters.fill(0.0);
        }
        meters
    }

    pub fn build_routing_snapshot(&self) -> crate::dsp::localizer::RoutingSnapshot {
        let mut routing = crate::dsp::localizer::RoutingSnapshot::default();
        if let Some(client) = &*self.xair.lock() {
            let mutes = client.channel_mutes.lock();
            let cache = client.params_cache.lock();
            for ch in 1..=16u8 {
                if let Some(&is_muted) = mutes.get(&ch) {
                    routing.channel_on.insert(ch, !is_muted);
                }
                let fader_addr = format!("/ch/{:02}/mix/fader", ch);
                if let Some(&fader_val) = cache.get(&fader_addr) {
                    routing.channel_faders.insert(ch, fader_val.clamp(0.0, 1.0));
                }
                for b in 1..=6u8 {
                    let send_addr = format!("/ch/{:02}/mix/{:02}/level", ch, b);
                    if let Some(&send_val) = cache.get(&send_addr) {
                        routing.bus_sends.insert((ch, b), send_val.clamp(0.0, 1.0));
                    }
                }
            }
            for b in 1..=6u8 {
                let on_addr = format!("/bus/{:02}/mix/on", b);
                if let Some(&on_val) = cache.get(&on_addr) {
                    routing.bus_on.insert(b, on_val >= 0.5);
                }
                let fader_addr = format!("/bus/{:02}/mix/fader", b);
                if let Some(&fader_val) = cache.get(&fader_addr) {
                    routing.bus_faders.insert(b, fader_val.clamp(0.0, 1.0));
                }
            }
        }
        routing
    }

    pub fn execute_safety_decision(
        &self,
        prop: &ActionProposal,
        now: f64,
    ) -> crate::core::models::Decision {
        let mut safety = self.safety.lock();
        let (mut new_safety, decision) = decide(
            &safety,
            prop,
            now,
            Some(&|t_num, b, t_type| self.get_current_gain_from_cache(t_num, b, t_type)),
        );
        if decision.approved {
            if let Some(ref approved) = decision.proposal {
                self.sync_notch_original_params(&mut new_safety, approved);
            }
        }
        *safety = new_safety;
        drop(safety);

        if decision.approved {
            if let Some(ref approved) = decision.proposal {
                if let Some(band) = approved.band {
                    self.send_peq_if_live(&PEQBand {
                        channel: approved.channel,
                        band,
                        freq_hz: approved.freq_hz,
                        gain_db: approved.gain_db,
                        q: approved.q,
                        is_on: true,
                        filter_type: 2,
                        target: approved.target.clone(),
                        bus: approved.bus,
                    });
                }
            }
        }
        decision
    }

    pub fn get_current_headamp_gain_db(&self, ch: u8) -> f32 {
        let client_guard = self.xair.lock();
        let Some(client) = client_guard.as_ref() else {
            return 20.0;
        };
        let clamped_ch = ch.clamp(1, 16);
        let cache = client.params_cache.lock();
        let headamp_1based = format!("/headamp/{:02}/gain", clamped_ch);
        let headamp_0based = format!("/headamp/{:02}/gain", clamped_ch - 1);
        let trim_addr = format!("/ch/{:02}/preamp/trim", clamped_ch);
        if let Some(&norm) = cache.get(&headamp_1based).or_else(|| cache.get(&headamp_0based)) {
            return (client.mapper.headamp.from_float(norm) * 10.0).round() / 10.0;
        }
        if let Some(&norm) = cache.get(&trim_addr) {
            return (client.mapper.trim.from_float(norm) * 10.0).round() / 10.0;
        }
        20.0
    }

    pub fn restore_or_schedule_fader(&self, target_type: &str, target_id: u8, fader_val: f32) {
        let fader_addr =
            crate::mixer::mapper::ParameterMapper::target_fader_address(target_type, target_id);
        let is_connected = self
            .xair
            .lock()
            .as_ref()
            .map_or(false, |c| c.get_state() == ConnectionState::Connected);
        if is_connected {
            self.send_fader_if_live(&fader_addr, fader_val);
        } else {
            *self.pending_fader_restore.lock() = Some((fader_addr, fader_val));
        }
    }

    pub fn abort_wizard_if_active(&self, now: f64) {
        let mut ringout = self.ringout.lock();
        if !ringout.is_active {
            return;
        }
        let _ = ringout.stop("aborted", now);
        let fader_to_restore = ringout.initial_fader_val;
        let target_type = ringout.target_type.clone();
        let target_id = ringout.target_id;
        drop(ringout);

        self.restore_or_schedule_fader(&target_type, target_id, fader_to_restore);
    }

    pub fn step_wizard(&self, now: f64) -> crate::core::ringout::WizardStatusSnapshot {
        let (mut rta, is_live_client, is_connected) = if let Some(client) = &*self.xair.lock() {
            let connected = client.get_state() == ConnectionState::Connected;
            (client.rta_levels.lock().clone(), true, connected)
        } else {
            (vec![-65.0; 100], false, false)
        };

        let mut ringout = self.ringout.lock();
        if ringout.is_active {
            if is_live_client && !is_connected {
                let fader_to_restore = ringout.initial_fader_val;
                let target_type = ringout.target_type.clone();
                let target_id = ringout.target_id;
                let _ = ringout.stop("aborted", now);
                let status = ringout.get_status();
                drop(ringout);

                let fader_addr = crate::mixer::mapper::ParameterMapper::target_fader_address(
                    &target_type,
                    target_id,
                );
                *self.pending_fader_restore.lock() = Some((fader_addr, fader_to_restore));
                self.add_log_coded(
                    "Mất kết nối mixer khi đang Ring-Out — Đã tự động dừng khẩn cấp và đặt lịch hoàn trả fader khi kết nối lại",
                    "warning",
                    "wizard.aborted",
                    serde_json::json!({}),
                );
                return status;
            }

            if !is_live_client
                && ringout.notches_found.is_empty()
                && (ringout.current_fader_db - ringout.initial_fader_db) >= 1.5
            {
                rta[55] = -35.0;
            }
            let (new_fader, prop, mut report) = ringout.process_frame(&rta, now);
            let target_type = ringout.target_type.clone();
            let target_id = ringout.target_id;
            drop(ringout);

            let fader_addr = crate::mixer::mapper::ParameterMapper::target_fader_address(
                &target_type,
                target_id,
            );

            if let Some(p) = prop {
                let decision = self.execute_safety_decision(&p, now);
                if decision.approved {
                    if let Some(fader_val) = new_fader {
                        self.send_fader_if_live(&fader_addr, fader_val);
                    }
                    if let Some(approved) = decision.proposal {
                        self.add_log_coded(
                            &format!(
                                "[WIZARD] Đã hạ notch PEQ tại {:.0}Hz ({:+.1}dB)",
                                approved.freq_hz, approved.gain_db
                            ),
                            "approved",
                            "log.wizardNotch",
                            serde_json::json!({
                                "freq_hz": approved.freq_hz.round(),
                                "gain_db": (approved.gain_db * 10.0).round() / 10.0
                            }),
                        );
                    }
                } else {
                    let mut ro = self.ringout.lock();
                    ro.revert_last_notch();
                    if decision.retryable {
                        report = None;
                    } else {
                        let stop_rep = ro.stop("ceiling_reached", now);
                        let restore_val = ro.initial_fader_val;
                        drop(ro);
                        self.restore_or_schedule_fader(&target_type, target_id, restore_val);
                        report = Some(stop_rep);
                    }
                }
            } else if let Some(fader_val) = new_fader {
                self.send_fader_if_live(&fader_addr, fader_val);
            }

            if let Some(rep) = report {
                let actual_count = self
                    .ringout
                    .lock()
                    .notches_found
                    .len()
                    .min(rep.notches_applied.len());
                self.add_log_coded(
                    &format!(
                        "Hoàn tất Soundcheck Ring-Out: Đã áp dụng {} notch an toàn!",
                        actual_count
                    ),
                    "approved",
                    "wizard.completed",
                    serde_json::json!({ "count": actual_count }),
                );
            }
        }

        self.ringout.lock().get_status()
    }

    pub fn get_current_gain_from_cache(&self, target_num: u8, band: u8, target_type: &str) -> Option<f32> {
        let client_guard = self.xair.lock();
        let client = client_guard.as_ref()?;
        let prefix = crate::mixer::mapper::ParameterMapper::target_eq_band_prefix(
            target_type,
            target_num,
            band,
        );
        let addr = format!("{}/g", prefix);
        let norm_val = *client.params_cache.lock().get(&addr)?;
        Some((client.mapper.gain.from_float(norm_val) * 10.0).round() / 10.0)
    }

    pub fn get_current_band_params_from_cache(
        &self,
        target_num: u8,
        band: u8,
        target_type: &str,
    ) -> (Option<f32>, Option<f32>, Option<f32>) {
        let client_guard = self.xair.lock();
        let Some(client) = client_guard.as_ref() else {
            return (None, None, None);
        };
        let prefix = crate::mixer::mapper::ParameterMapper::target_eq_band_prefix(
            target_type,
            target_num,
            band,
        );
        let cache = client.params_cache.lock();
        let orig_f = cache
            .get(&format!("{}/f", prefix))
            .map(|&v| (client.mapper.freq.from_float(v) * 10.0).round() / 10.0);
        let orig_g = cache
            .get(&format!("{}/g", prefix))
            .map(|&v| (client.mapper.gain.from_float(v) * 10.0).round() / 10.0);
        let orig_q = cache
            .get(&format!("{}/q", prefix))
            .map(|&v| (client.mapper.q.from_float(v) * 100.0).round() / 100.0);
        (orig_f, orig_g, orig_q)
    }

    pub fn sync_notch_original_params(&self, safety: &mut SafetyState, approved: &ActionProposal) {
        let Some(band) = approved.band else {
            return;
        };
        let (norm_target, target_key_id, norm_ch, norm_bus) =
            crate::core::models::classify_target(&approved.target, approved.channel, approved.bus);
        let target_num = if norm_target == "bus" {
            norm_bus.unwrap_or(1)
        } else {
            norm_ch
        };
        let (orig_f, orig_g, orig_q) =
            self.get_current_band_params_from_cache(target_num, band, norm_target);
        if let Some(notch) = safety.active_notches.get_mut(&(target_key_id, band)) {
            if notch.step_count == 1 {
                if let Some(f) = orig_f {
                    notch.original_freq_hz = f;
                }
                if let Some(g) = orig_g {
                    notch.original_gain_db = g;
                }
                if let Some(q) = orig_q {
                    notch.original_q = q;
                }
            }
        }
    }

    pub fn dispatch_proposal(&self, mut prop: ActionProposal, now: f64) {
        prop.ensure_metadata(now);
        let mode = self.current_mode.lock().clone();

        if mode == "auto" {
            let decision = self.execute_safety_decision(&prop, now);

            if decision.approved {
                if let Some(approved) = decision.proposal {
                    let tgt_label = format_target_label_with_reason(
                        &approved.target,
                        approved.channel,
                        approved.bus,
                        &prop.reason,
                    );
                    self.add_log_coded(
                        &format!(
                            "[AUTO] Tự động hạ notch {} tại {:.1}Hz ({:+.1}dB)",
                            tgt_label, approved.freq_hz, approved.gain_db
                        ),
                        "approved",
                        "log.autoNotch",
                        serde_json::json!({
                            "target": tgt_label,
                            "channel": approved.channel,
                            "freq_hz": (approved.freq_hz * 10.0).round() / 10.0,
                            "gain_db": (approved.gain_db * 10.0).round() / 10.0
                        }),
                    );
                }
            }
        } else {
            let mut pending = self.pending_proposals.lock();
            let duplicate = pending.iter().any(|p| {
                p.target == prop.target
                    && p.channel == prop.channel
                    && p.bus == prop.bus
                    && (p.freq_hz - prop.freq_hz).abs() < 15.0
            });
            if !duplicate {
                let tgt_label = format_target_label_with_reason(
                    &prop.target,
                    prop.channel,
                    prop.bus,
                    &prop.reason,
                );
                pending.push(prop.clone());
                drop(pending);
                self.add_log_coded(
                    &format!("Cảnh báo hú: Phát hiện tần số {:.1}Hz trên {}", prop.freq_hz, tgt_label),
                    "warning",
                    "log.feedbackWarning",
                    serde_json::json!({
                        "target": tgt_label,
                        "channel": prop.channel,
                        "freq_hz": (prop.freq_hz * 10.0).round() / 10.0
                    }),
                );
            }
        }
    }

    pub fn get_snapshot(&self) -> FullStateSnapshot {
        let now = now_secs();
        let (mixer_status, mixer_model, rtt_ms, mut meters, rta, ch_names, ch_mutes, ch_hpfs, num_ch) = if let Some(client) = &*self.xair.lock() {
            let cm = client.capability_map.lock();
            let ch_count = crate::core::models::CapabilityMap::channel_count_for_model(&cm.model);
            (
                client.get_state(),
                format!("{} ({})", cm.model, cm.firmware),
                *client.last_rtt_ms.lock(),
                Self::get_decayed_lan_meters(client),
                client.rta_levels.lock().clone(),
                client.channel_names.lock().clone(),
                client.channel_mutes.lock().clone(),
                client.channel_hpf_on.lock().clone(),
                ch_count,
            )
        } else {
            (
                ConnectionState::Disconnected,
                "Chưa kết nối".to_string(),
                None,
                self.usb_meters.lock().clone(),
                vec![-100.0; 100],
                std::collections::HashMap::new(),
                std::collections::HashMap::new(),
                self.mock_hpf_channels.lock().clone(),
                16u8,
            )
        };
        self.merge_active_usb_meters(&mut meters, now);

        let safety_guard = self.safety.lock();
        let active_notches: Vec<ActiveNotch> = safety_guard
            .active_notches
            .values()
            .cloned()
            .map(|mut n| {
                n.age_s = (now - n.last_updated_time).max(0.0);
                n.is_locked = if n.target == "bus" {
                    n.bus
                        .and_then(|b| safety_guard.bus_locks.get(&b))
                        .map_or(false, |&until| until > now)
                } else {
                    safety_guard
                        .channel_locks
                        .get(&n.channel)
                        .map_or(false, |&until| until > now)
                };
                n
            })
            .collect();

        let mut channels = Vec::with_capacity(num_ch as usize);
        for ch in 1..=num_ch {
            let is_locked = safety_guard
                .channel_locks
                .get(&ch)
                .map_or(false, |&until| until > now);
            let whitelisted = safety_guard.whitelist.contains(&ch);
            let level = meters.get(ch as usize - 1).copied().unwrap_or(0.0);
            let name = ch_names.get(&ch).cloned().unwrap_or_else(|| format!("CH{:02}", ch));
            let is_muted = ch_mutes.get(&ch).copied().unwrap_or(false);
            let hpf_enabled = ch_hpfs.get(&ch).copied().unwrap_or(false);
            channels.push(ChannelInfo {
                channel: ch,
                name,
                color: 1,
                is_muted,
                level,
                is_locked,
                whitelisted,
                hpf_enabled,
            });
        }
        drop(safety_guard);

        let dsp_latency_ms = 42.7;
        let latency_ms = dsp_latency_ms + rtt_ms.unwrap_or(0.0);

        let pending_proposals: Vec<ActionProposal> = self
            .pending_proposals
            .lock()
            .iter()
            .cloned()
            .map(|mut p| {
                p.ensure_metadata(now);
                p.ttl_remaining_s = (30.0 - (now - p.created_at) as f32).max(0.0);
                p
            })
            .collect();

        let usb_running = self.audio_engine.lock().is_running() && *self.active_audio_channels.lock() >= 2;
        let audio_mode = if usb_running {
            "usb".to_string()
        } else if mixer_status == ConnectionState::Connected {
            "lan_rta".to_string()
        } else {
            "none".to_string()
        };

        let (talkover_enabled, talkover_is_ducked, talkover_mic_channel) = {
            let tk = self.talkover.lock();
            (tk.config.enabled, tk.is_ducked, tk.config.mic_channel)
        };

        let mut alerts_guard = self.clip_alerts.lock();
        alerts_guard.retain(|_, a| now - a.timestamp < 5.0);
        let clip_alerts: Vec<_> = alerts_guard.values().cloned().collect();
        drop(alerts_guard);

        let gain_sessions = self.gain_staging.lock().sessions.clone();

        FullStateSnapshot {
            mixer_status,
            dry_run: *self.dry_run.lock(),
            mixer_model,
            latency_ms,
            rtt_ms,
            dsp_latency_ms,
            current_mode: self.current_mode.lock().clone(),
            current_preset: self.current_preset.lock().clone(),
            audio_mode,
            talkover_enabled,
            talkover_is_ducked,
            talkover_mic_channel,
            active_notches,
            pending_proposals,
            channels,
            meters,
            rta_bins: rta,
            clip_alerts,
            gain_sessions,
            event_logs: self.logs.lock().clone(),
        }
    }
}
