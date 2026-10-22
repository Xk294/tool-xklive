use std::sync::Arc;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

use crate::audio::AudioEngine;
use crate::core::models::{
    ActionProposal, ActiveNotch, ChannelInfo, ConnectionState, LogEntry,
};
use crate::core::safety::SafetyState;
use crate::dsp::detector::FeedbackDetector;
use crate::mixer::xair::XAirClient;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FullStateSnapshot {
    pub mixer_status: ConnectionState,
    pub is_mock_mode: bool,
    pub dry_run: bool,
    pub mixer_model: String,
    pub latency_ms: f32,
    pub rtt_ms: Option<f32>,
    pub dsp_latency_ms: f32,
    pub firmware_reason: String,
    pub current_mode: String,
    pub active_notches: Vec<ActiveNotch>,
    pub pending_proposals: Vec<ActionProposal>,
    pub channels: Vec<ChannelInfo>,
    pub meters: Vec<f32>,
    pub rta_bins: Vec<f32>,
    pub event_logs: Vec<LogEntry>,
}

pub struct AppState {
    pub xair: Arc<Mutex<Option<XAirClient>>>,
    pub safety: Arc<Mutex<SafetyState>>,
    pub detector: Arc<Mutex<FeedbackDetector>>,
    pub audio_engine: Arc<Mutex<AudioEngine>>,
    pub current_mode: Arc<Mutex<String>>, // "auto", "semi", "manual"
    pub dry_run: Arc<Mutex<bool>>,
    pub logs: Arc<Mutex<Vec<LogEntry>>>,
    pub pending_proposals: Arc<Mutex<Vec<ActionProposal>>>,
    pub log_counter: Arc<Mutex<u64>>,
}

impl AppState {
    pub fn new() -> Self {
        Self {
            xair: Arc::new(Mutex::new(None)),
            safety: Arc::new(Mutex::new(SafetyState::default())),
            detector: Arc::new(Mutex::new(FeedbackDetector::default_config())),
            audio_engine: Arc::new(Mutex::new(AudioEngine::new())),
            current_mode: Arc::new(Mutex::new("semi".to_string())),
            dry_run: Arc::new(Mutex::new(false)),
            logs: Arc::new(Mutex::new(Vec::new())),
            pending_proposals: Arc::new(Mutex::new(Vec::new())),
            log_counter: Arc::new(Mutex::new(1)),
        }
    }

    pub fn add_log(&self, text: &str, entry_type: &str) {
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
        });
        if logs.len() > 100 {
            logs.remove(0);
        }
    }

    pub fn get_snapshot(&self) -> FullStateSnapshot {
        let (mixer_status, mixer_model, rtt_ms, meters, rta) = if let Some(client) = &*self.xair.lock() {
            let cm = client.capability_map.lock();
            (
                client.get_state(),
                format!("{} ({})", cm.model, cm.firmware),
                *client.last_rtt_ms.lock(),
                client.meter_levels.lock().clone(),
                client.rta_levels.lock().clone(),
            )
        } else {
            (
                ConnectionState::Disconnected,
                "Chưa kết nối".to_string(),
                None,
                vec![0.0; 18],
                vec![-100.0; 100],
            )
        };

        let safety_guard = self.safety.lock();
        let active_notches: Vec<ActiveNotch> = safety_guard.active_notches.values().cloned().collect();

        let mut channels = Vec::with_capacity(16);
        for ch in 1..=16 {
            let is_locked = safety_guard
                .channel_locks
                .get(&ch)
                .map_or(false, |&until| until > 0.0);
            let whitelisted = safety_guard.whitelist.contains(&ch);
            let level = meters.get(ch as usize - 1).copied().unwrap_or(0.0);
            channels.push(ChannelInfo {
                channel: ch,
                name: format!("CH{:02}", ch),
                color: 1,
                is_muted: false,
                level,
                is_locked,
                whitelisted,
            });
        }

        FullStateSnapshot {
            mixer_status,
            is_mock_mode: false,
            dry_run: *self.dry_run.lock(),
            mixer_model,
            latency_ms: 12.5,
            rtt_ms,
            dsp_latency_ms: 4.2,
            firmware_reason: String::new(),
            current_mode: self.current_mode.lock().clone(),
            active_notches,
            pending_proposals: self.pending_proposals.lock().clone(),
            channels,
            meters,
            rta_bins: rta,
            event_logs: self.logs.lock().clone(),
        }
    }
}
