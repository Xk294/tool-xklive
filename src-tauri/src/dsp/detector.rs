use std::collections::{HashMap, HashSet};
use std::f32::consts::PI;
use std::sync::Arc;
use rustfft::{num_complex::Complex, Fft, FftPlanner};
use crate::core::models::ActionProposal;

#[derive(Debug, Clone)]
pub struct ChannelTrackedPeak {
    pub bin_idx: usize,
    pub freq_hz: f32,
    pub last_mag_db: f32,
    pub accumulated_growth_db: f32,
    pub consecutive_frames: usize,
    pub is_reported: bool,
}

pub struct FeedbackDetector {
    pub sample_rate: u32,
    pub frame_size: usize,
    pub prominence_threshold_db: f32,
    pub growth_threshold_db: f32,
    pub confirmation_frames: usize,
    pub min_freq_hz: f32,
    pub max_freq_hz: f32,
    pub min_peak_db: f32,
    pub default_notch_q: f32,
    pub probe_gain_db: f32,

    bin_res: f32,
    min_bin: usize,
    max_bin: usize,

    window: Vec<f32>,
    fft: Arc<dyn Fft<f32>>,

    complex_buffer: Vec<Complex<f32>>,
    mag_db: Vec<f32>,
    noise_floor: Vec<f32>,
    prominence: Vec<f32>,
    detected_peaks: Vec<(usize, f32, f32)>,
    active_bins: HashSet<usize>,

    tracked_peaks: HashMap<u8, HashMap<usize, ChannelTrackedPeak>>,
}

impl FeedbackDetector {
    pub fn new(
        sample_rate: u32,
        frame_size: usize,
        prominence_threshold_db: f32,
        growth_threshold_db: f32,
        confirmation_frames: usize,
        min_freq_hz: f32,
        max_freq_hz: f32,
        min_peak_db: f32,
        default_notch_q: f32,
        probe_gain_db: f32,
    ) -> Self {
        let mut planner = FftPlanner::new();
        let fft = planner.plan_fft_forward(frame_size);

        let window: Vec<f32> = (0..frame_size)
            .map(|i| 0.5 * (1.0 - (2.0 * PI * i as f32 / (frame_size - 1) as f32).cos()))
            .collect();

        let num_bins = frame_size / 2 + 1;
        let bin_res = sample_rate as f32 / frame_size as f32;
        let min_bin = 2.max((min_freq_hz / bin_res).floor() as usize);
        let max_bin = (frame_size / 2 - 2).min((max_freq_hz / bin_res).ceil() as usize);

        Self {
            sample_rate,
            frame_size,
            prominence_threshold_db,
            growth_threshold_db,
            confirmation_frames,
            min_freq_hz,
            max_freq_hz,
            min_peak_db,
            default_notch_q,
            probe_gain_db,
            bin_res,
            min_bin,
            max_bin,
            window,
            fft,
            complex_buffer: vec![Complex::new(0.0, 0.0); frame_size],
            mag_db: vec![0.0; num_bins],
            noise_floor: vec![0.0; num_bins],
            prominence: vec![0.0; num_bins],
            detected_peaks: Vec::with_capacity(32),
            active_bins: HashSet::with_capacity(32),
            tracked_peaks: HashMap::new(),
        }
    }

    pub fn default_config() -> Self {
        Self::new(
            48000, 2048, 10.0, 2.0, 3, 100.0, 15000.0, -50.0, 8.0, -3.0,
        )
    }

    pub fn reset_all(&mut self) {
        self.tracked_peaks.clear();
    }

    fn is_musical_harmonic(&self, bin_idx: usize) -> bool {
        let peak_mag = self.mag_db[bin_idx];
        let total_bins = self.mag_db.len();

        for mul in 2..=4 {
            let target = mul * bin_idx;
            if target < total_bins {
                let start = target.saturating_sub(1);
                let end = (target + 2).min(total_bins);
                let local_max = self.mag_db[start..end]
                    .iter()
                    .copied()
                    .fold(f32::NEG_INFINITY, f32::max);
                if peak_mag - local_max < 15.0 {
                    return true;
                }
            }
        }

        for div in 2..=4 {
            let target = (bin_idx as f32 / div as f32).round() as usize;
            if target >= 2 && target < total_bins {
                let start = target.saturating_sub(1);
                let end = (target + 2).min(total_bins);
                let local_max = self.mag_db[start..end]
                    .iter()
                    .copied()
                    .fold(f32::NEG_INFINITY, f32::max);
                if peak_mag - local_max < 15.0 {
                    return true;
                }
            }
        }

        false
    }

    fn compute_median_filter(&mut self, window_size: usize) {
        let n = self.mag_db.len();
        let half = window_size / 2;
        let mut temp = [0.0f32; 31];

        for i in 0..n {
            let mut count = 0;
            for j in 0..window_size {
                let idx = if i + j < half {
                    0
                } else if i + j - half >= n {
                    n - 1
                } else {
                    i + j - half
                };
                temp[count] = self.mag_db[idx];
                count += 1;
            }
            temp[..count].sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
            self.noise_floor[i] = temp[half];
            self.prominence[i] = self.mag_db[i] - self.noise_floor[i];
        }
    }

    pub fn process_channel_frame(
        &mut self,
        channel: u8,
        samples: &[f32],
    ) -> Vec<ActionProposal> {
        if samples.len() != self.frame_size {
            log::warn!("Frame size mismatch: expected {}, got {}", self.frame_size, samples.len());
            return Vec::new();
        }

        for i in 0..self.frame_size {
            self.complex_buffer[i] = Complex::new(samples[i] * self.window[i], 0.0);
        }

        self.fft.process(&mut self.complex_buffer);

        let num_bins = self.frame_size / 2 + 1;
        for i in 0..num_bins {
            let mag = (self.complex_buffer[i].norm()).max(1e-8);
            self.mag_db[i] = 20.0 * mag.log10();
        }

        self.compute_median_filter(31);

        self.detected_peaks.clear();

        for k in self.min_bin..self.max_bin {
            if self.mag_db[k] < self.min_peak_db {
                continue;
            }

            if self.mag_db[k] > self.mag_db[k - 1] && self.mag_db[k] > self.mag_db[k + 1] {
                if self.prominence[k] >= self.prominence_threshold_db {
                    if self.is_musical_harmonic(k) {
                        continue;
                    }

                    let alpha = self.mag_db[k - 1];
                    let beta = self.mag_db[k];
                    let gamma = self.mag_db[k + 1];
                    let denom = alpha - 2.0 * beta + gamma;
                    let p = if denom.abs() > 1e-7 {
                        0.5 * (alpha - gamma) / denom
                    } else {
                        0.0
                    };

                    let exact_bin = k as f32 + p;
                    let exact_freq = exact_bin * self.bin_res;
                    let exact_mag = beta - 0.25 * (alpha - gamma) * p;

                    self.detected_peaks.push((k, exact_freq, exact_mag));
                }
            }
        }

        let tracked = self.tracked_peaks.entry(channel).or_default();
        self.active_bins.clear();
        let mut proposals = Vec::new();

        for &(k, freq, mag_val) in &self.detected_peaks {
            self.active_bins.insert(k);

            let matched_prev_bin = [k, k.saturating_sub(1), k + 1]
                .into_iter()
                .find(|&b| tracked.contains_key(&b));

            if let Some(prev_bin) = matched_prev_bin {
                if let Some(mut peak_record) = tracked.remove(&prev_bin) {
                    let growth = mag_val - peak_record.last_mag_db;

                    if growth < -1.0 {
                        tracked.insert(k, peak_record);
                        continue;
                    }

                    let total_growth = peak_record.accumulated_growth_db + growth.max(0.0);
                    let consecutive = peak_record.consecutive_frames + 1;
                    let is_reported = peak_record.is_reported;

                    peak_record.bin_idx = k;
                    peak_record.freq_hz = freq;
                    peak_record.last_mag_db = mag_val;
                    peak_record.accumulated_growth_db = total_growth;
                    peak_record.consecutive_frames = consecutive;

                    if consecutive >= self.confirmation_frames && !is_reported {
                        if total_growth >= self.growth_threshold_db {
                            peak_record.is_reported = true;
                            let rounded_freq = (freq * 10.0).round() / 10.0;
                            let mut prop = ActionProposal {
                                channel,
                                freq_hz: rounded_freq,
                                gain_db: self.probe_gain_db,
                                q: self.default_notch_q,
                                bus: None,
                                band: None,
                                target: "ch".to_string(),
                                reason: format!("Feedback {:.1}Hz (+{:.1}dB tích lũy)", freq, total_growth),
                                original_gain_db: 0.0,
                                confidence_score: ((total_growth / 12.0) + 0.65).clamp(0.65, 0.99),
                                ..Default::default()
                            };
                            prop.ensure_metadata(0.0);
                            proposals.push(prop);
                        }
                    }

                    tracked.insert(k, peak_record);
                }
            } else {
                tracked.insert(
                    k,
                    ChannelTrackedPeak {
                        bin_idx: k,
                        freq_hz: freq,
                        last_mag_db: mag_val,
                        accumulated_growth_db: 0.0,
                        consecutive_frames: 1,
                        is_reported: false,
                    },
                );
            }
        }

        let active_bins_ref = &self.active_bins;
        tracked.retain(|b, _| active_bins_ref.contains(b));

        proposals
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detector_initialization() {
        let detector = FeedbackDetector::default_config();
        assert_eq!(detector.frame_size, 2048);
        assert_eq!(detector.sample_rate, 48000);
        assert_eq!(detector.confirmation_frames, 3);
    }

    #[test]
    fn test_feedback_detection_on_growing_sine() {
        let mut detector = FeedbackDetector::default_config();
        let target_freq = 1000.0f32;
        let sample_rate = 48000.0f32;

        let mut proposals = Vec::new();

        for frame_idx in 0..5 {
            let amp = 0.05 * 1.5f32.powi(frame_idx);
            let samples: Vec<f32> = (0..2048)
                .map(|i| amp * (2.0 * PI * target_freq * i as f32 / sample_rate).sin())
                .collect();

            let props = detector.process_channel_frame(1, &samples);
            proposals.extend(props);
        }

        assert!(!proposals.is_empty(), "Expected feedback proposal to be generated");
        let detected = &proposals[0];
        assert_eq!(detected.channel, 1);
        assert!((detected.freq_hz - target_freq).abs() < 25.0);
        assert_eq!(detected.gain_db, -3.0);
    }
}
