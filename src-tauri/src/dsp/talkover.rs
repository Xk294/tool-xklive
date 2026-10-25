use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TalkoverConfig {
    pub enabled: bool,
    pub mic_channel: u8,
    pub music_channels: Vec<u8>,
    pub fx_return_channel: u8,
    pub mic_speech_threshold_dbfs: f32,
    pub music_silence_threshold_dbfs: f32,
    pub hold_time_s: f64,
    pub fade_duration_ms: f64,
    pub ducking_depth_db: f32,
}

impl Default for TalkoverConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            mic_channel: 1,
            music_channels: vec![15, 16, 17, 18],
            fx_return_channel: 1,
            mic_speech_threshold_dbfs: -42.0,
            music_silence_threshold_dbfs: -48.0,
            hold_time_s: 1.5,
            fade_duration_ms: 300.0,
            ducking_depth_db: -18.0,
        }
    }
}

pub struct TalkoverController {
    pub config: TalkoverConfig,
    pub is_ducked: bool,
    pub last_speech_time: f64,
    pub original_fader_val: f32,
    pub ducked_fader_val: f32,
    pub current_fader_val: f32,
    fade_start_val: f32,
    fade_target_val: f32,
    fade_start_time: f64,
    is_fading: bool,
}

impl TalkoverController {
    pub fn new(config: Option<TalkoverConfig>) -> Self {
        let cfg = config.unwrap_or_default();
        Self {
            config: cfg,
            is_ducked: false,
            last_speech_time: 0.0,
            original_fader_val: 0.75,
            ducked_fader_val: 0.40,
            current_fader_val: 0.75,
            fade_start_val: 0.75,
            fade_target_val: 0.75,
            fade_start_time: 0.0,
            is_fading: false,
        }
    }

    pub fn set_original_fader(&mut self, val: f32) {
        let clamped = val.clamp(0.0, 1.0);
        self.original_fader_val = clamped;
        let depth_norm = crate::mixer::mapper::ParameterMapper::fader_delta_db_to_norm(
            self.config.ducking_depth_db.abs(),
        )
        .clamp(0.10, 0.75);
        self.ducked_fader_val = (clamped - depth_norm).max(0.0);
        if !self.is_ducked && !self.is_fading {
            self.current_fader_val = clamped;
        }
    }

    pub fn recalculate_ducked_fader(&mut self) {
        let depth_norm = crate::mixer::mapper::ParameterMapper::fader_delta_db_to_norm(
            self.config.ducking_depth_db.abs(),
        )
        .clamp(0.10, 0.75);
        self.ducked_fader_val = (self.original_fader_val - depth_norm).max(0.0);
    }

    pub fn process_frame(
        &mut self,
        mic_energy_dbfs: f32,
        music_energy_dbfs: f32,
        now: f64,
    ) -> (Option<f32>, String) {
        if !self.config.enabled {
            return (None, String::new());
        }

        let is_music_silent = music_energy_dbfs < self.config.music_silence_threshold_dbfs;
        let is_speech_present = mic_energy_dbfs > self.config.mic_speech_threshold_dbfs;

        let mut msg = String::new();

        if is_music_silent && is_speech_present {
            self.last_speech_time = now;
            if !self.is_ducked {
                self.is_ducked = true;
                msg = format!(
                    "Kích hoạt Talkover: Nhạc dừng ({:.1}dBFS) & Mic nói ({:.1}dBFS)",
                    music_energy_dbfs, mic_energy_dbfs
                );
                self.start_fade(self.ducked_fader_val, now);
            }
        } else if self.is_ducked {
            let music_resumed = !is_music_silent;
            let hold_expired = (now - self.last_speech_time) >= self.config.hold_time_s;

            if music_resumed || hold_expired {
                self.is_ducked = false;
                let trigger = if music_resumed { "Nhạc nổi lên" } else { "Hết câu giao lưu" };
                msg = format!(
                    "Nhả Talkover ({}) -> Khôi phục FX Return về {:.2}",
                    trigger, self.original_fader_val
                );
                self.start_fade(self.original_fader_val, now);
            }
        }

        let fader_out = if self.is_fading {
            self.update_fade(now)
        } else {
            None
        };

        (fader_out, msg)
    }

    fn start_fade(&mut self, target_val: f32, now: f64) {
        self.fade_start_val = self.current_fader_val;
        self.fade_target_val = target_val;
        self.fade_start_time = now;
        self.is_fading = true;
    }

    fn update_fade(&mut self, now: f64) -> Option<f32> {
        let duration_s = (self.config.fade_duration_ms / 1000.0).max(0.05);
        let progress = ((now - self.fade_start_time) / duration_s) as f32;

        if progress >= 1.0 {
            self.current_fader_val = self.fade_target_val;
            self.is_fading = false;
            return Some((self.current_fader_val * 1000.0).round() / 1000.0);
        }

        let val = self.fade_start_val + (self.fade_target_val - self.fade_start_val) * progress;
        self.current_fader_val = val;
        Some((val * 1000.0).round() / 1000.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_talkover_trigger_and_release() {
        let mut cfg = TalkoverConfig::default();
        cfg.enabled = true;
        let mut ctrl = TalkoverController::new(Some(cfg));
        let now = 100.0;

        // Music is silent (-55 dBFS), mic is speaking (-30 dBFS)
        let (fader, msg) = ctrl.process_frame(-30.0, -55.0, now);
        assert!(ctrl.is_ducked);
        assert!(!msg.is_empty());
        assert!(fader.is_some());

        // Fast forward 2.0 seconds with speech stopping
        let (_, release_msg) = ctrl.process_frame(-60.0, -55.0, now + 2.0);
        assert!(!ctrl.is_ducked);
        assert!(!release_msg.is_empty());
    }
}
