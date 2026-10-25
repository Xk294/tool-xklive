#[derive(Debug, Clone)]
pub struct SubMapper {
    pub min_val: f32,
    pub max_val: f32,
    pub is_log: bool,
    log_min: f32,
    log_range: f32,
    range: f32,
}

impl SubMapper {
    pub fn new(min_val: f32, max_val: f32, is_log: bool) -> Self {
        assert!(min_val < max_val, "min_val must be less than max_val");
        if is_log {
            assert!(min_val > 0.0, "log mapper requires min_val > 0");
        }

        let (log_min, log_range) = if is_log {
            let l_min = min_val.log10();
            let l_max = max_val.log10();
            (l_min, l_max - l_min)
        } else {
            (0.0, 0.0)
        };

        Self {
            min_val,
            max_val,
            is_log,
            log_min,
            log_range,
            range: max_val - min_val,
        }
    }

    pub fn to_float(&self, val: f32) -> f32 {
        let clamped = val.clamp(self.min_val, self.max_val);
        let norm = if self.is_log {
            (clamped.log10() - self.log_min) / self.log_range
        } else {
            (clamped - self.min_val) / self.range
        };
        norm.clamp(0.0, 1.0)
    }

    pub fn from_float(&self, f: f32) -> f32 {
        let clamped = f.clamp(0.0, 1.0);
        let val = if self.is_log {
            10.0f32.powf(self.log_min + clamped * self.log_range)
        } else {
            self.min_val + clamped * self.range
        };
        val.clamp(self.min_val, self.max_val)
    }
}

#[derive(Debug, Clone)]
pub struct ParameterMapper {
    pub freq: SubMapper,
    pub gain: SubMapper,
    pub q: SubMapper,
    pub hpf: SubMapper,
    pub headamp: SubMapper,
    pub trim: SubMapper,
}

impl Default for ParameterMapper {
    fn default() -> Self {
        Self {
            freq: SubMapper::new(20.0, 20000.0, true),
            gain: SubMapper::new(-15.0, 15.0, false),
            q: SubMapper::new(0.3, 10.0, true),
            hpf: SubMapper::new(20.0, 400.0, true),
            headamp: SubMapper::new(-12.0, 60.0, false),
            trim: SubMapper::new(-18.0, 18.0, false),
        }
    }
}

impl ParameterMapper {
    pub fn linear_to_db(lin: f32, floor_db: f32) -> f32 {
        if lin > 1e-6 {
            (20.0 * lin.log10()).max(floor_db)
        } else {
            floor_db
        }
    }

    pub fn fader_norm_to_db(norm: f32) -> f32 {
        (norm.clamp(0.0, 1.0) - 0.75) * 40.0
    }

    pub fn fader_delta_db_to_norm(delta_db: f32) -> f32 {
        delta_db / 40.0
    }

    pub fn target_prefix(
        target_type: &str,
        channel: u8,
        bus: Option<u8>,
        lr_prefix: &str,
    ) -> String {
        let lr = if lr_prefix.is_empty() { "/lr" } else { lr_prefix };
        match target_type {
            "bus" => format!("/bus/{:02}", bus.unwrap_or(channel).max(1)),
            "main" | "lr" => lr.to_string(),
            _ => {
                if channel == 0 {
                    lr.to_string()
                } else {
                    format!("/ch/{:02}", channel)
                }
            }
        }
    }

    pub fn target_fader_address(target_type: &str, target_id: u8) -> String {
        if target_type == "lr" || target_type == "main" || target_id == 0 {
            "/lr/mix/fader".to_string()
        } else {
            format!("/bus/{:02}/mix/fader", target_id)
        }
    }

    pub fn target_eq_band_prefix(target_type: &str, target_num: u8, band: u8) -> String {
        let prefix = Self::target_prefix(
            target_type,
            target_num,
            if target_type == "bus" { Some(target_num) } else { None },
            "/lr",
        );
        format!("{}/eq/{}", prefix, band)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_gain_linear_mapping() {
        let mapper = ParameterMapper::default();
        // 0.0 dB should map to 0.5
        let norm = mapper.gain.to_float(0.0);
        assert!((norm - 0.5).abs() < 1e-4);

        let roundtrip = mapper.gain.from_float(0.5);
        assert!((roundtrip - 0.0).abs() < 1e-4);

        // -15 dB should map to 0.0
        assert!((mapper.gain.to_float(-15.0) - 0.0).abs() < 1e-4);
        // +15 dB should map to 1.0
        assert!((mapper.gain.to_float(15.0) - 1.0).abs() < 1e-4);

        // Headamp (-12..+60 dB) and Trim (-18..+18 dB) SSoT linear mappers
        assert!((mapper.headamp.from_float(0.0) - -12.0).abs() < 1e-4);
        assert!((mapper.headamp.from_float(1.0) - 60.0).abs() < 1e-4);
        assert!((mapper.trim.from_float(0.5) - 0.0).abs() < 1e-4);
    }

    #[test]
    fn test_freq_log_mapping() {
        let mapper = ParameterMapper::default();
        // 20 Hz -> 0.0
        assert!((mapper.freq.to_float(20.0) - 0.0).abs() < 1e-4);
        // 20000 Hz -> 1.0
        assert!((mapper.freq.to_float(20000.0) - 1.0).abs() < 1e-4);

        // Geometric mean ~ 632.45 Hz -> 0.5
        let mid_freq = (20.0 * 20000.0f32).sqrt();
        assert!((mapper.freq.to_float(mid_freq) - 0.5).abs() < 1e-3);
    }
}
