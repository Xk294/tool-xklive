#[derive(Debug, Clone)]
pub struct SubMapper {
    pub min_val: f32,
    pub max_val: f32,
    pub steps: u32,
    pub is_log: bool,
    log_min: f32,
    log_range: f32,
    range: f32,
}

impl SubMapper {
    pub fn new(min_val: f32, max_val: f32, steps: u32, is_log: bool) -> Self {
        assert!(min_val < max_val, "min_val must be less than max_val");
        assert!(steps >= 2, "steps must be >= 2");
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
            steps,
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

    pub fn quantize_float(&self, f: f32) -> f32 {
        let clamped = f.clamp(0.0, 1.0);
        let step_idx = (clamped * (self.steps - 1) as f32).round();
        step_idx / (self.steps - 1) as f32
    }

    pub fn snap(&self, val: f32) -> f32 {
        let norm = self.to_float(val);
        let q_norm = self.quantize_float(norm);
        self.from_float(q_norm)
    }
}

#[derive(Debug, Clone)]
pub struct ParameterMapper {
    pub freq: SubMapper,
    pub gain: SubMapper,
    pub q: SubMapper,
}

impl Default for ParameterMapper {
    fn default() -> Self {
        Self {
            freq: SubMapper::new(20.0, 20000.0, 201, true),
            gain: SubMapper::new(-15.0, 15.0, 121, false),
            q: SubMapper::new(0.3, 10.0, 72, true),
        }
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
