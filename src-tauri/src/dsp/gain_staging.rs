use std::collections::HashMap;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GainCalibrationSession {
    pub channel: u8,
    pub duration_s: f64,
    pub start_time: f64,
    pub is_active: bool,
    pub samples_peak: Vec<f32>,
    pub samples_rms: Vec<f32>,
    pub current_headamp_gain_db: f32,
    pub proposed_gain_db: Option<f32>,
    pub proposed_gain_change_db: f32,
    pub target_rms_dbfs: f32,
    pub max_peak_dbfs: f32,
    pub state: String, // "measuring", "completed", "cancelled"
    pub advice: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClipAlert {
    pub channel: u8,
    pub channel_name: String,
    pub clip_duration_ms: f64,
    pub current_gain_db: f32,
    pub suggested_reduction_db: f32,
    pub timestamp: f64,
}

pub struct GainStagingManager {
    pub target_rms_dbfs: f32,
    pub max_peak_dbfs: f32,
    pub max_gain_step_db: f32,
    pub headamp_min_db: f32,
    pub headamp_max_db: f32,
    pub clip_threshold_dbfs: f32,
    pub clip_persist_ms: f64,
    pub sessions: HashMap<u8, GainCalibrationSession>,
    clip_start_times: HashMap<u8, f64>,
}

impl Default for GainStagingManager {
    fn default() -> Self {
        Self {
            target_rms_dbfs: -18.0,
            max_peak_dbfs: -6.0,
            max_gain_step_db: 6.0,
            headamp_min_db: -12.0,
            headamp_max_db: 60.0,
            clip_threshold_dbfs: -0.5,
            clip_persist_ms: 300.0,
            sessions: HashMap::new(),
            clip_start_times: HashMap::new(),
        }
    }
}

impl GainStagingManager {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn start_calibration(&mut self, channel: u8, current_headamp_gain_db: f32, now: f64) -> bool {
        let session = GainCalibrationSession {
            channel,
            duration_s: 10.0,
            start_time: now,
            is_active: true,
            samples_peak: Vec::new(),
            samples_rms: Vec::new(),
            current_headamp_gain_db,
            proposed_gain_db: None,
            proposed_gain_change_db: 0.0,
            target_rms_dbfs: self.target_rms_dbfs,
            max_peak_dbfs: self.max_peak_dbfs,
            state: "measuring".to_string(),
            advice: "Đang lắng nghe tín hiệu micro trong 10 giây...".to_string(),
        };
        self.sessions.insert(channel, session);
        true
    }

    pub fn cancel_calibration(&mut self, channel: u8) {
        if let Some(session) = self.sessions.get_mut(&channel) {
            session.is_active = false;
            session.state = "cancelled".to_string();
        }
    }

    pub fn process_meter_sample(
        &mut self,
        channel: u8,
        peak_level_dbfs: f32,
        rms_level_dbfs: f32,
        now: f64,
    ) -> (Option<f32>, Option<ClipAlert>) {
        let mut proposed_gain = None;
        let mut clip_alert = None;

        // 1. Process active calibration session
        if let Some(session) = self.sessions.get_mut(&channel) {
            if session.is_active {
                session.samples_peak.push(peak_level_dbfs);
                session.samples_rms.push(rms_level_dbfs);

                if (now - session.start_time) >= session.duration_s {
                    session.is_active = false;
                    session.state = "completed".to_string();

                    let valid_rms: Vec<f32> = session.samples_rms.iter().copied().filter(|&r| r > -80.0).collect();
                    let avg_rms = if !valid_rms.is_empty() {
                        valid_rms.iter().sum::<f32>() / valid_rms.len() as f32
                    } else {
                        -50.0
                    };

                    let max_peak = session.samples_peak.iter().copied().fold(f32::NEG_INFINITY, f32::max);
                    let max_peak = if max_peak.is_infinite() { -20.0 } else { max_peak };

                    let delta_rms = self.target_rms_dbfs - avg_rms;
                    let peak_headroom = self.max_peak_dbfs - max_peak;
                    let safe_delta = delta_rms.min(peak_headroom);

                    let clamped_delta = safe_delta.clamp(-self.max_gain_step_db, self.max_gain_step_db);
                    let delta_rounded = (clamped_delta * 10.0).round() / 10.0;
                    let target_gain = session.current_headamp_gain_db + clamped_delta;
                    let final_gain = target_gain.clamp(self.headamp_min_db, self.headamp_max_db);

                    let res = (final_gain * 10.0).round() / 10.0;
                    session.proposed_gain_db = Some(res);
                    session.proposed_gain_change_db = delta_rounded;
                    session.advice = if valid_rms.is_empty() {
                        format!("Mic {}: Chưa thu được tiếng nói rõ ràng. Hãy kiểm tra dây mic hoặc tăng nhẹ Gain.", channel)
                    } else if delta_rounded > 1.0 {
                        format!("Mic {}: Mức tín hiệu hơi nhỏ (Peak {:.1} dBFS). Nên tăng Gain trên mixer thêm {:+.1} dB.", channel, max_peak, delta_rounded)
                    } else if delta_rounded < -1.0 {
                        format!("Mic {}: Mức tín hiệu hơi lớn (Peak {:.1} dBFS). Nên giảm Gain trên mixer {:+.1} dB để tránh vỡ tiếng.", channel, max_peak, delta_rounded)
                    } else {
                        format!("Mic {}: Mức Gain hiện tại đã chuẩn (Peak {:.1} dBFS, Headroom an toàn).", channel, max_peak)
                    };
                    proposed_gain = Some(res);
                }
            }
        }

        // 2. Clip Guardian detection
        if peak_level_dbfs >= self.clip_threshold_dbfs {
            let start = *self.clip_start_times.entry(channel).or_insert(now);
            let elapsed_ms = (now - start) * 1000.0;
            if elapsed_ms >= self.clip_persist_ms {
                let current_gain = self.sessions.get(&channel).map_or(0.0, |s| s.current_headamp_gain_db);
                clip_alert = Some(ClipAlert {
                    channel,
                    channel_name: format!("CH {:02}", channel),
                    clip_duration_ms: (elapsed_ms * 10.0).round() / 10.0,
                    current_gain_db: current_gain,
                    suggested_reduction_db: -3.0,
                    timestamp: now,
                });
                self.clip_start_times.insert(channel, now);
            }
        } else {
            self.clip_start_times.remove(&channel);
        }

        (proposed_gain, clip_alert)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_gain_calibration_calculation() {
        let mut mgr = GainStagingManager::new();
        let now = 100.0;
        mgr.start_calibration(1, 20.0, now);

        // Feed samples with average RMS around -28 dBFS (needs ~+6 dB)
        for i in 0..20 {
            mgr.process_meter_sample(1, -16.0, -28.0, now + (i as f64 * 0.5));
        }

        // Complete 10 seconds
        let (proposed, _) = mgr.process_meter_sample(1, -16.0, -28.0, now + 10.1);
        assert!(proposed.is_some());
        let final_g = proposed.unwrap();
        assert!(final_g > 20.0); // Should recommend increasing preamp gain
    }

    #[test]
    fn test_clip_guardian_trigger() {
        let mut mgr = GainStagingManager::new();
        let now = 100.0;
        // Peak is clipping (-0.2 dBFS >= -0.5 dBFS)
        let (_, alert1) = mgr.process_meter_sample(2, -0.2, -10.0, now);
        assert!(alert1.is_none()); // Not sustained for 300ms yet

        // 350ms later
        let (_, alert2) = mgr.process_meter_sample(2, -0.1, -10.0, now + 0.35);
        assert!(alert2.is_some());
        let a = alert2.unwrap();
        assert_eq!(a.channel, 2);
        assert_eq!(a.suggested_reduction_db, -3.0);
    }
}
