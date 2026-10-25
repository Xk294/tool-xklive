use std::collections::{HashMap, HashSet};
use crate::core::models::ActionProposal;

pub struct RTADetector {
    pub num_bins: usize,
    pub f_min_hz: f32,
    pub f_max_hz: f32,
    pub prominence_threshold_db: f32,
    pub min_peak_db: f32,
    pub growth_threshold_db: f32,
    pub confirmation_frames: usize,
    pub default_notch_q: f32,
    pub probe_gain_db: f32,
    pub cooldown_s: f64,
    bin_center_freqs: Vec<f32>,
    history: HashMap<usize, RtaTrackEntry>,
    cooldown_until: HashMap<usize, f64>,
    baseline_buf: Vec<f32>,
    window_buf: Vec<f32>,
    candidates_buf: Vec<(usize, f32)>,
    active_bins_buf: HashSet<usize>,
}

#[derive(Debug, Clone)]
struct RtaTrackEntry {
    frames: usize,
    last_energy: f32,
    accumulated_growth: f32,
}

impl RTADetector {
    pub fn new(num_bins: usize, f_min_hz: f32, f_max_hz: f32) -> Self {
        let span = f_max_hz / f_min_hz;
        let bin_center_freqs: Vec<f32> = (0..num_bins)
            .map(|i| {
                let frac = i as f32 / (num_bins - 1).max(1) as f32;
                f_min_hz * span.powf(frac)
            })
            .collect();

        Self {
            num_bins,
            f_min_hz,
            f_max_hz,
            prominence_threshold_db: 10.0,
            min_peak_db: -50.0,
            growth_threshold_db: 2.0,
            confirmation_frames: 3,
            default_notch_q: 10.0,
            probe_gain_db: -3.0,
            cooldown_s: 2.0,
            bin_center_freqs,
            history: HashMap::with_capacity(num_bins),
            cooldown_until: HashMap::with_capacity(num_bins),
            baseline_buf: vec![0.0f32; num_bins],
            window_buf: Vec::with_capacity(11),
            candidates_buf: Vec::with_capacity(num_bins),
            active_bins_buf: HashSet::with_capacity(num_bins),
        }
    }

    pub fn bin_to_freq(&self, bin_idx: usize) -> f32 {
        let idx = bin_idx.min(self.num_bins - 1);
        self.bin_center_freqs[idx]
    }

    pub fn freq_to_bin(&self, freq_hz: f32) -> usize {
        let clipped = freq_hz.clamp(self.f_min_hz, self.f_max_hz);
        let ratio = clipped / self.f_min_hz;
        let log_span = self.f_max_hz / self.f_min_hz;
        let bin_float = (ratio.ln() / log_span.ln()) * (self.num_bins - 1) as f32;
        (bin_float.round() as usize).min(self.num_bins - 1)
    }

    pub fn process_rta_frame(
        &mut self,
        levels_db: &[f32],
        target_name: &str,
    ) -> Vec<ActionProposal> {
        self.process_rta_frame_at(levels_db, target_name, 0.0)
    }

    pub fn process_rta_frame_at(
        &mut self,
        levels_db: &[f32],
        target_name: &str,
        now: f64,
    ) -> Vec<ActionProposal> {
        if levels_db.len() != self.num_bins {
            return Vec::new();
        }

        if now > 0.0 {
            self.cooldown_until.retain(|_, &mut until| until > now);
        }

        // 1. Median filter baseline estimation (window size 11, reusing pre-allocated buffers)
        let half_w = 5;
        if self.baseline_buf.len() != self.num_bins {
            self.baseline_buf.resize(self.num_bins, 0.0);
        }

        for i in 0..self.num_bins {
            let start = i.saturating_sub(half_w);
            let end = (i + half_w + 1).min(self.num_bins);
            self.window_buf.clear();
            self.window_buf.extend_from_slice(&levels_db[start..end]);
            self.window_buf.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            self.baseline_buf[i] = self.window_buf[self.window_buf.len() / 2];
        }

        self.candidates_buf.clear();
        self.active_bins_buf.clear();

        // 2. Identify local peaks with prominence above threshold
        for i in 1..(self.num_bins - 1) {
            if now > 0.0 {
                if let Some(&until) = self.cooldown_until.get(&i) {
                    if now < until {
                        continue;
                    }
                }
            }
            let val = levels_db[i];
            if val > levels_db[i - 1] && val > levels_db[i + 1] {
                let prom = val - self.baseline_buf[i];
                if prom >= self.prominence_threshold_db && val >= self.min_peak_db {
                    self.candidates_buf.push((i, prom));
                    self.active_bins_buf.insert(i);
                }
            }
        }

        // Prune inactive bins from history
        let active_bins = &self.active_bins_buf;
        self.history.retain(|&k, _| active_bins.contains(&k));

        let mut proposals = Vec::new();

        // 3. Track growth across consecutive frames
        for idx in 0..self.candidates_buf.len() {
            let (bin_idx, prom) = self.candidates_buf[idx];
            let cur_val = levels_db[bin_idx];
            let entry = self.history.entry(bin_idx).or_insert(RtaTrackEntry {
                frames: 0,
                last_energy: cur_val,
                accumulated_growth: 0.0,
            });

            entry.frames += 1;
            let growth = cur_val - entry.last_energy;
            if growth > 0.0 {
                entry.accumulated_growth += growth;
            }
            entry.last_energy = cur_val;

            if entry.frames >= self.confirmation_frames && entry.accumulated_growth >= self.growth_threshold_db {
                let f_hz = self.bin_to_freq(bin_idx);
                let mut prop = ActionProposal {
                    channel: 0,
                    target: target_name.to_string(),
                    freq_hz: f_hz,
                    gain_db: self.probe_gain_db,
                    q: self.default_notch_q,
                    bus: None,
                    band: None,
                    reason: format!(
                        "Phát hiện hú qua RTA {} tại {:.0}Hz (nổi bật {:.1}dB)",
                        target_name.to_uppercase(),
                        f_hz,
                        prom
                    ),
                    original_gain_db: 0.0,
                    confidence_score: ((prom / 25.0) + 0.5).clamp(0.6, 0.98),
                    ..Default::default()
                };
                prop.ensure_metadata(now);
                proposals.push(prop);
                self.history.remove(&bin_idx);
                if now > 0.0 {
                    self.cooldown_until.insert(bin_idx, now + self.cooldown_s);
                }
            }
        }

        proposals
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rta_bin_freq_conversion() {
        let detector = RTADetector::new(100, 20.0, 20000.0);
        let f0 = detector.bin_to_freq(0);
        assert!((f0 - 20.0).abs() < 0.1);
        let f_last = detector.bin_to_freq(99);
        assert!((f_last - 20000.0).abs() < 1.0);

        let bin_1k = detector.freq_to_bin(1000.0);
        let recovered_f = detector.bin_to_freq(bin_1k);
        assert!((recovered_f - 1000.0).abs() / 1000.0 < 0.05); // Within 5%
    }

    #[test]
    fn test_rta_feedback_detection() {
        let mut detector = RTADetector::new(100, 20.0, 20000.0);
        let target_bin = detector.freq_to_bin(2500.0);

        let mut frame = vec![-60.0f32; 100];
        // Frame 1: peak appears
        frame[target_bin] = -35.0;
        let p1 = detector.process_rta_frame(&frame, "main");
        assert!(p1.is_empty()); // needs confirmation frames

        // Frame 2: peak grows
        frame[target_bin] = -30.0;
        let p2 = detector.process_rta_frame(&frame, "main");
        assert!(p2.is_empty());

        // Frame 3: peak grows further
        frame[target_bin] = -25.0;
        let p3 = detector.process_rta_frame(&frame, "main");
        assert_eq!(p3.len(), 1);
        assert!((p3[0].freq_hz - 2500.0).abs() / 2500.0 < 0.06);
    }

    #[test]
    fn test_rta_cooldown_suppresses_duplicate_proposal() {
        let mut detector = RTADetector::new(100, 20.0, 20000.0);
        let target_bin = detector.freq_to_bin(2500.0);
        let mut frame = vec![-60.0f32; 100];

        frame[target_bin] = -35.0;
        assert!(detector.process_rta_frame_at(&frame, "main", 10.0).is_empty());
        frame[target_bin] = -30.0;
        assert!(detector.process_rta_frame_at(&frame, "main", 10.2).is_empty());
        frame[target_bin] = -25.0;
        let emitted = detector.process_rta_frame_at(&frame, "main", 10.4);
        assert_eq!(emitted.len(), 1);

        // Within 2.0s cooldown window (until 12.4s), the same bin must not emit again
        frame[target_bin] = -35.0;
        assert!(detector.process_rta_frame_at(&frame, "main", 10.6).is_empty());
        frame[target_bin] = -30.0;
        assert!(detector.process_rta_frame_at(&frame, "main", 10.8).is_empty());
        frame[target_bin] = -20.0;
        assert!(detector.process_rta_frame_at(&frame, "main", 11.0).is_empty());

        // After cooldown expires (t >= 12.5s), detection resumes normally
        frame[target_bin] = -35.0;
        assert!(detector.process_rta_frame_at(&frame, "main", 12.5).is_empty());
        frame[target_bin] = -30.0;
        assert!(detector.process_rta_frame_at(&frame, "main", 12.7).is_empty());
        frame[target_bin] = -24.0;
        let emitted_after = detector.process_rta_frame_at(&frame, "main", 12.9);
        assert_eq!(emitted_after.len(), 1);
    }
}
