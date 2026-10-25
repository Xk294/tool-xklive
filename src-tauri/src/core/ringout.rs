use serde::{Deserialize, Serialize};
use crate::core::models::ActionProposal;
use crate::core::safety::HARD_MAX_BOOST_DB;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RingOutConfig {
    pub step_db: f32,
    pub step_interval_s: f64,
    pub max_boost_above_start_db: f32,
    pub fader_retreat_db: f32,
    pub notch_gain_db: f32,
    pub notch_q: f32,
    pub prominence_threshold_db: f32,
    pub max_notches: usize,
    pub r_floor_db: f32,
}

impl Default for RingOutConfig {
    fn default() -> Self {
        Self {
            step_db: 1.0,
            step_interval_s: 0.5,
            max_boost_above_start_db: HARD_MAX_BOOST_DB,
            fader_retreat_db: -3.0,
            notch_gain_db: -4.5,
            notch_q: 10.0,
            prominence_threshold_db: 12.0,
            max_notches: 5,
            r_floor_db: -75.0,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppliedNotchInfo {
    pub freq_hz: f32,
    pub gain_db: f32,
    pub q: f32,
    pub prominence_db: f32,
    pub level_db: f32,
    pub timestamp: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RingOutReport {
    pub target_type: String,
    pub target_id: u8,
    pub initial_fader_db: f32,
    pub final_fader_db: f32,
    pub total_duration_s: f64,
    pub notches_applied: Vec<AppliedNotchInfo>,
    pub status: String, // "COMPLETED", "ABORTED", "CEILING_REACHED"
    pub message: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WizardStatusSnapshot {
    pub state: String, // "idle", "running", "paused", "completed"
    pub target_type: String,
    pub target_id: u8,
    pub current_gain_added: f32,
    pub detected_notches: usize,
    pub detected_frequencies: Vec<f32>,
    pub status_message: String,
}

pub struct RingOutController {
    pub config: RingOutConfig,
    pub is_active: bool,
    pub state: String,
    pub target_type: String,
    pub target_id: u8,
    pub initial_fader_val: f32,
    pub current_fader_val: f32,
    pub initial_fader_db: f32,
    pub current_fader_db: f32,
    pub start_time: f64,
    pub last_step_time: f64,
    pub notches_found: Vec<AppliedNotchInfo>,
    pub status_message: String,
    last_pre_notch_fader: (f32, f32),
    frequencies: Vec<f32>,
    sort_buf: [f32; 100],
}

impl RingOutController {
    pub fn new(config: Option<RingOutConfig>) -> Self {
        let frequencies: Vec<f32> = (0..100)
            .map(|i| 20.0 * (1000.0f32).powf(i as f32 / 99.0))
            .collect();

        Self {
            config: config.unwrap_or_default(),
            is_active: false,
            state: "idle".to_string(),
            target_type: "bus".to_string(),
            target_id: 1,
            initial_fader_val: 0.75,
            current_fader_val: 0.75,
            initial_fader_db: 0.0,
            current_fader_db: 0.0,
            start_time: 0.0,
            last_step_time: 0.0,
            notches_found: Vec::new(),
            status_message: "Sẵn sàng".to_string(),
            last_pre_notch_fader: (0.75, 0.0),
            frequencies,
            sort_buf: [0.0; 100],
        }
    }

    pub fn revert_last_notch(&mut self) {
        self.notches_found.pop();
        self.current_fader_val = self.last_pre_notch_fader.0;
        self.current_fader_db = self.last_pre_notch_fader.1;
        if !self.is_active && self.state == "completed" {
            self.is_active = true;
            self.state = "running".to_string();
        }
    }

    pub fn start(
        &mut self,
        target_type: &str,
        target_id: u8,
        initial_fader_val: f32,
        initial_fader_db: f32,
        now: f64,
    ) -> bool {
        if self.is_active {
            return false;
        }

        self.is_active = true;
        self.state = "running".to_string();
        self.target_type = target_type.to_string();
        self.target_id = target_id;
        self.initial_fader_val = initial_fader_val.clamp(0.0, 1.0);
        self.current_fader_val = self.initial_fader_val;
        self.initial_fader_db = initial_fader_db;
        self.current_fader_db = initial_fader_db;

        self.start_time = now;
        self.last_step_time = now;
        self.notches_found.clear();
        self.status_message = format!("Bắt đầu Ring-Out trên {} {}", self.target_type.to_uppercase(), self.target_id);
        true
    }

    pub fn stop(&mut self, reason: &str, now: f64) -> RingOutReport {
        let was_active = self.is_active;
        self.is_active = false;
        let duration = if was_active { (now - self.start_time).max(0.0) } else { 0.0 };

        let (status, next_state, msg) = match reason {
            "completed" => ("COMPLETED", "completed", "Hoàn tất Ring-Out phòng"),
            "ceiling_reached" => ("CEILING_REACHED", "completed", "Đạt trần an toàn tối đa"),
            _ => ("ABORTED", "aborted", "Đã dừng khẩn cấp Ring-Out"),
        };
        self.state = next_state.to_string();
        self.current_fader_val = self.initial_fader_val;
        self.current_fader_db = self.initial_fader_db;
        self.status_message = msg.to_string();

        RingOutReport {
            target_type: self.target_type.clone(),
            target_id: self.target_id,
            initial_fader_db: self.initial_fader_db,
            final_fader_db: self.initial_fader_db,
            total_duration_s: (duration * 10.0).round() / 10.0,
            notches_applied: self.notches_found.clone(),
            status: status.to_string(),
            message: msg.to_string(),
        }
    }

    pub fn get_status(&self) -> WizardStatusSnapshot {
        let state = if self.is_active {
            "running"
        } else {
            self.state.as_str()
        };

        let gain_added = (self.current_fader_db - self.initial_fader_db).max(0.0);

        WizardStatusSnapshot {
            state: state.to_string(),
            target_type: self.target_type.clone(),
            target_id: self.target_id,
            current_gain_added: (gain_added * 10.0).round() / 10.0,
            detected_notches: self.notches_found.len(),
            detected_frequencies: self.notches_found.iter().map(|n| n.freq_hz).collect(),
            status_message: self.status_message.clone(),
        }
    }

    pub fn process_frame(
        &mut self,
        rta_levels_db: &[f32],
        now: f64,
    ) -> (Option<f32>, Option<ActionProposal>, Option<RingOutReport>) {
        if !self.is_active || rta_levels_db.len() < 100 {
            return (None, None, None);
        }

        // 1. Estimate floor by median using pre-allocated stack array (0 heap allocation)
        self.sort_buf.copy_from_slice(&rta_levels_db[0..100]);
        self.sort_buf.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let median_floor = self.sort_buf[50];

        let mut peak_bin = None;
        let mut peak_prominence = 0.0f32;
        let mut peak_level = -120.0f32;

        for b in 1..99 {
            let lvl = rta_levels_db[b];
            if lvl > self.config.r_floor_db && lvl > rta_levels_db[b - 1] && lvl > rta_levels_db[b + 1] {
                let prom = lvl - median_floor;
                if prom > peak_prominence {
                    peak_prominence = prom;
                    peak_bin = Some(b);
                    peak_level = lvl;
                }
            }
        }

        // 2. If resonance peak exceeds prominence threshold (respecting step cooldown)
        if now >= self.last_step_time {
            if let Some(b) = peak_bin {
                if peak_prominence >= self.config.prominence_threshold_db {
                    let freq_hz = self.frequencies[b];
                    let already_notched = self.notches_found.iter().any(|n| {
                        (n.freq_hz - freq_hz).abs() / freq_hz < 0.05
                    });

                    if !already_notched {
                        self.last_pre_notch_fader = (self.current_fader_val, self.current_fader_db);
                        let max_boost = self.config.max_boost_above_start_db.min(HARD_MAX_BOOST_DB);
                        self.current_fader_db = (self.current_fader_db + self.config.fader_retreat_db)
                            .clamp(self.initial_fader_db - 12.0, self.initial_fader_db + max_boost);
                        let delta_norm = crate::mixer::mapper::ParameterMapper::fader_delta_db_to_norm(
                            self.current_fader_db - self.initial_fader_db,
                        );
                        let max_boost_norm = crate::mixer::mapper::ParameterMapper::fader_delta_db_to_norm(max_boost);
                        self.current_fader_val = (self.initial_fader_val + delta_norm)
                            .clamp(0.0, (self.initial_fader_val + max_boost_norm).min(1.0));

                        let notch_info = AppliedNotchInfo {
                            freq_hz: (freq_hz * 10.0).round() / 10.0,
                            gain_db: self.config.notch_gain_db,
                            q: self.config.notch_q,
                            prominence_db: (peak_prominence * 10.0).round() / 10.0,
                            level_db: (peak_level * 10.0).round() / 10.0,
                            timestamp: now,
                        };
                        self.notches_found.push(notch_info);

                        let is_bus = self.target_type == "bus";
                        let mut prop = ActionProposal {
                            channel: if is_bus { 0 } else { self.target_id },
                            bus: if is_bus { Some(self.target_id) } else { None },
                            target: self.target_type.clone(),
                            freq_hz,
                            gain_db: self.config.notch_gain_db,
                            q: self.config.notch_q,
                            band: None,
                            reason: format!(
                                "Ring-Out phát hiện cộng hưởng phòng tại {:.0}Hz (+{:.1}dB)",
                                freq_hz, peak_prominence
                            ),
                            original_gain_db: 0.0,
                            ..Default::default()
                        };
                        prop.ensure_metadata(now);

                        self.status_message = format!(
                            "Phát hiện đỉnh {:.0}Hz! Đã lùi fader và ghim notch ({}/{})",
                            freq_hz,
                            self.notches_found.len(),
                            self.config.max_notches
                        );
                        self.last_step_time = now + 0.5;

                        if self.notches_found.len() >= self.config.max_notches {
                            let report = self.stop("completed", now);
                            return (Some(self.initial_fader_val), Some(prop), Some(report));
                        }

                        return (Some(self.current_fader_val), Some(prop), None);
                    }
                }
            }
        }

        // 3. Step up fader if interval passed
        if now >= self.last_step_time && now - self.last_step_time >= self.config.step_interval_s {
            self.last_step_time = now;
            let max_boost = self.config.max_boost_above_start_db.min(HARD_MAX_BOOST_DB);

            if (self.current_fader_db - self.initial_fader_db) >= max_boost {
                let report = self.stop("ceiling_reached", now);
                return (Some(self.initial_fader_val), None, Some(report));
            }

            self.current_fader_db = (self.current_fader_db + self.config.step_db)
                .min(self.initial_fader_db + max_boost);
            let boost_so_far = self.current_fader_db - self.initial_fader_db;
            let boost_norm = crate::mixer::mapper::ParameterMapper::fader_delta_db_to_norm(boost_so_far);
            let max_boost_norm = crate::mixer::mapper::ParameterMapper::fader_delta_db_to_norm(max_boost);
            self.current_fader_val = (self.initial_fader_val + boost_norm)
                .clamp(0.0, (self.initial_fader_val + max_boost_norm).min(1.0));
            self.status_message = format!("Đang dò: Nâng fader {:+.1}dB so với ban đầu...", boost_so_far);
            return (Some(self.current_fader_val), None, None);
        }

        (None, None, None)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ringout_lifecycle_and_step_boost() {
        let mut ctrl = RingOutController::new(None);
        let now = 1000.0;
        assert!(ctrl.start("bus", 1, 0.75, 0.0, now));

        let frame = vec![-65.0f32; 100];
        // After 0.6s -> should step fader up
        let (fader, prop, report) = ctrl.process_frame(&frame, now + 0.6);
        assert!(fader.is_some());
        assert!(prop.is_none());
        assert!(report.is_none());
        assert!(ctrl.current_fader_db > 0.0);
    }

    #[test]
    fn test_ringout_resonance_detection_and_retreat() {
        let mut ctrl = RingOutController::new(None);
        let now = 1000.0;
        ctrl.start("bus", 1, 0.75, 0.0, now);

        let mut frame = vec![-65.0f32; 100];
        // Simulate a resonance spike at bin 50
        frame[50] = -35.0; // 30 dB above floor

        let (fader, prop, _) = ctrl.process_frame(&frame, now + 0.1);
        assert!(fader.is_some());
        assert!(prop.is_some());
        let p = prop.unwrap();
        assert_eq!(p.bus, Some(1));
        assert_eq!(ctrl.notches_found.len(), 1);
        assert!(ctrl.current_fader_db < 0.0);

        ctrl.revert_last_notch();
        assert_eq!(ctrl.notches_found.len(), 0);
        assert!((ctrl.current_fader_db - 0.0).abs() < 1e-4);
        assert!((ctrl.current_fader_val - 0.75).abs() < 1e-4);
    }

    #[test]
    fn test_ringout_default_max_boost_safety_invariant() {
        let cfg = RingOutConfig::default();
        assert!(cfg.max_boost_above_start_db <= 4.0);
        assert_eq!(cfg.max_boost_above_start_db, 4.0);
    }

    #[test]
    fn test_capability_map_channel_count_for_models() {
        use crate::core::models::{classify_target, format_target_label, CapabilityMap};
        assert_eq!(CapabilityMap::channel_count_for_model("XR12"), 12);
        assert_eq!(CapabilityMap::channel_count_for_model("MR12 (v1.18)"), 12);
        assert_eq!(CapabilityMap::channel_count_for_model("XR16"), 16);
        assert_eq!(CapabilityMap::channel_count_for_model("XR18"), 16);
        assert_eq!(CapabilityMap::channel_count_for_model("MR18"), 16);

        assert!(!CapabilityMap::supports_usb_multitrack("XR12"));
        assert!(!CapabilityMap::supports_usb_multitrack("MR12"));
        assert!(!CapabilityMap::supports_usb_multitrack("XR16"));
        assert!(CapabilityMap::supports_usb_multitrack("XR18"));
        assert!(CapabilityMap::supports_usb_multitrack("MR18"));

        assert_eq!(classify_target("bus", 0, Some(2)), ("bus", -2, 0, Some(2)));
        assert_eq!(classify_target("main", 0, None), ("main", 0, 0, None));
        assert_eq!(classify_target("ch", 5, None), ("ch", 5, 5, None));
        assert_eq!(format_target_label("bus", 0, Some(3)), "Bus 3");
        assert_eq!(format_target_label("main", 0, None), "Main LR");
        assert_eq!(format_target_label("ch", 4, None), "Kênh 4");
    }

    #[test]
    fn test_ringout_state_completed_with_zero_notches_vs_aborted() {
        let mut ctrl = RingOutController::new(Some(RingOutConfig {
            step_db: 2.0,
            step_interval_s: 0.5,
            max_boost_above_start_db: 3.0,
            ..Default::default()
        }));
        let now = 1000.0;
        assert_eq!(ctrl.state, "idle");
        assert!(ctrl.start("main", 0, 0.50, -10.0, now));
        assert_eq!(ctrl.state, "running");

        let frame = vec![-65.0f32; 100];
        let (f1, _, r1) = ctrl.process_frame(&frame, now + 0.6);
        assert!(r1.is_none());
        assert!((f1.unwrap() - 0.55).abs() < 1e-4);

        let (f2, _, r2) = ctrl.process_frame(&frame, now + 1.2);
        assert!(r2.is_none());
        assert!((f2.unwrap() - 0.575).abs() < 1e-4);

        let (f3, _, r3) = ctrl.process_frame(&frame, now + 1.8);
        assert!(r3.is_some());
        assert_eq!(ctrl.notches_found.len(), 0);
        assert_eq!(ctrl.state, "completed");
        assert!((f3.unwrap() - 0.50).abs() < 1e-4);

        assert!(ctrl.start("main", 0, 0.50, -10.0, now + 5.0));
        ctrl.stop("user_aborted", now + 6.0);
        assert_eq!(ctrl.state, "aborted");
    }
}
