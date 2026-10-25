use std::collections::HashMap;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalizerCandidate {
    pub channel: u8,
    pub bus: Option<u8>,
    pub score: f32,
    pub spectral_energy_db: f32,
    pub send_level_db: f32,
    pub is_channel_muted: bool,
    pub is_bus_muted: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalizationResult {
    pub f0_hz: f32,
    pub candidates: Vec<LocalizerCandidate>,
    pub top_candidate: Option<LocalizerCandidate>,
    pub is_ambiguous: bool,
    pub ambiguity_delta: f32,
    pub recommended_mode: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RoutingSnapshot {
    pub bus_sends: HashMap<(u8, u8), f32>,
    pub channel_on: HashMap<u8, bool>,
    pub channel_faders: HashMap<u8, f32>,
    pub bus_on: HashMap<u8, bool>,
    pub bus_faders: HashMap<u8, f32>,
}

impl Default for RoutingSnapshot {
    fn default() -> Self {
        let mut channel_on = HashMap::new();
        let mut channel_faders = HashMap::new();
        for ch in 1..=16 {
            channel_on.insert(ch, true);
            channel_faders.insert(ch, 0.75);
        }
        let mut bus_on = HashMap::new();
        let mut bus_faders = HashMap::new();
        for b in 1..=6 {
            bus_on.insert(b, true);
            bus_faders.insert(b, 0.75);
        }
        Self {
            bus_sends: HashMap::new(),
            channel_on,
            channel_faders,
            bus_on,
            bus_faders,
        }
    }
}

pub struct TwoFactorLocalizer {
    pub spectral_weight: f32,
    pub routing_weight: f32,
    pub ambiguity_threshold: f32,
    pub min_confidence_for_auto: f32,
}

impl Default for TwoFactorLocalizer {
    fn default() -> Self {
        Self::new()
    }
}

impl TwoFactorLocalizer {
    pub fn new() -> Self {
        Self {
            spectral_weight: 0.65,
            routing_weight: 0.35,
            ambiguity_threshold: 0.15,
            min_confidence_for_auto: 0.50,
        }
    }

    pub fn localize_from_energies(
        &self,
        channel_spectral_db: &HashMap<u8, f32>,
        f0_hz: f32,
        routing_opt: Option<&RoutingSnapshot>,
        suspected_bus: Option<u8>,
    ) -> LocalizationResult {
        let default_routing = RoutingSnapshot::default();
        let routing = routing_opt.unwrap_or(&default_routing);

        let active_energies: Vec<f32> = channel_spectral_db
            .values()
            .copied()
            .filter(|&db| db > -90.0)
            .collect();

        let min_db = active_energies.iter().copied().fold(f32::INFINITY, f32::min);
        let min_db = if min_db.is_infinite() { -90.0 } else { min_db };
        let max_db = active_energies.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        let max_db = if max_db.is_infinite() { -30.0 } else { max_db };
        let db_range = (max_db - min_db).max(1.0);

        let targets_to_eval: Vec<Option<u8>> = match suspected_bus {
            Some(b) => vec![Some(b)],
            None => vec![None],
        };

        let mut candidates = Vec::new();

        for (&ch, &spec_db) in channel_spectral_db {
            let is_ch_on = *routing.channel_on.get(&ch).unwrap_or(&true);
            let ch_fader = *routing.channel_faders.get(&ch).unwrap_or(&0.75);

            let norm_spectral = if spec_db > -90.0 {
                ((spec_db - min_db) / db_range).clamp(0.0, 1.0)
            } else {
                0.0
            };

            for &bus_opt in &targets_to_eval {
                let (is_bus_on, bus_fader, send_val) = if let Some(b) = bus_opt {
                    (
                        *routing.bus_on.get(&b).unwrap_or(&true),
                        *routing.bus_faders.get(&b).unwrap_or(&0.75),
                        *routing.bus_sends.get(&(ch, b)).unwrap_or(&0.75),
                    )
                } else {
                    let best_bus = (1..=6u8)
                        .filter(|b| *routing.bus_on.get(b).unwrap_or(&true))
                        .filter_map(|b| {
                            let send = *routing.bus_sends.get(&(ch, b))?;
                            let bf = *routing.bus_faders.get(&b).unwrap_or(&0.75);
                            Some((bf, send))
                        })
                        .max_by(|a, b| {
                            (a.0 * a.1)
                                .partial_cmp(&(b.0 * b.1))
                                .unwrap_or(std::cmp::Ordering::Equal)
                        });
                    if let Some((bf, send)) = best_bus {
                        if bf * send > 0.75 * 0.75 {
                            (true, bf, send)
                        } else {
                            (true, 0.75, 0.75)
                        }
                    } else {
                        (true, 0.75, 0.75)
                    }
                };

                let total_score = if !is_ch_on || !is_bus_on {
                    0.0
                } else {
                    let norm_routing = send_val * ch_fader * bus_fader;
                    (self.spectral_weight * norm_spectral) + (self.routing_weight * norm_routing)
                };

                let send_db = 20.0 * (send_val.max(1e-4)).log10();

                candidates.push(LocalizerCandidate {
                    channel: ch,
                    bus: bus_opt,
                    score: (total_score * 10000.0).round() / 10000.0,
                    spectral_energy_db: (spec_db * 10.0).round() / 10.0,
                    send_level_db: (send_db * 10.0).round() / 10.0,
                    is_channel_muted: !is_ch_on,
                    is_bus_muted: !is_bus_on,
                });
            }
        }

        candidates.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));

        let top_candidate = candidates.first().cloned();
        let mut is_ambiguous = false;
        let mut ambiguity_delta = 1.0f32;
        let mut recommended_mode = "auto".to_string();

        if let Some(ref top) = top_candidate {
            let other_cands: Vec<&LocalizerCandidate> = candidates
                .iter()
                .filter(|c| c.channel != top.channel)
                .collect();

            if let Some(second) = other_cands.first() {
                ambiguity_delta = top.score - second.score;
                if ambiguity_delta < self.ambiguity_threshold {
                    is_ambiguous = true;
                }
            } else {
                ambiguity_delta = 1.0;
                is_ambiguous = false;
            }

            if top.score < self.min_confidence_for_auto || is_ambiguous {
                recommended_mode = "semi".to_string();
            } else {
                recommended_mode = "auto".to_string();
            }
        }

        LocalizationResult {
            f0_hz,
            candidates,
            top_candidate,
            is_ambiguous,
            ambiguity_delta: (ambiguity_delta * 10000.0).round() / 10000.0,
            recommended_mode,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_localizer_basic_scoring_and_ranking() {
        let localizer = TwoFactorLocalizer::new();

        let mut energies = HashMap::new();
        energies.insert(1, -20.0); // Channel 1 has strong feedback energy
        energies.insert(2, -50.0); // Channel 2 has moderate crosstalk
        energies.insert(3, -80.0); // Channel 3 has minimal floor

        let mut routing = RoutingSnapshot::default();
        routing.bus_sends.insert((1, 1), 0.9); // High send to Bus 1
        routing.bus_sends.insert((2, 1), 0.5);

        let res = localizer.localize_from_energies(&energies, 2500.0, Some(&routing), Some(1));
        assert!(res.top_candidate.is_some());
        let top = res.top_candidate.unwrap();
        assert_eq!(top.channel, 1);
        assert_eq!(top.bus, Some(1));
        assert_eq!(res.recommended_mode, "auto");

        // Also verify suspected_bus = None uses active bus_sends & bus_on from RoutingSnapshot
        let res_none = localizer.localize_from_energies(&energies, 2500.0, Some(&routing), None);
        assert_eq!(res_none.top_candidate.unwrap().channel, 1);
    }

    #[test]
    fn test_localizer_mute_awareness() {
        let localizer = TwoFactorLocalizer::new();

        let mut energies = HashMap::new();
        energies.insert(1, -15.0); // Strongest energy
        energies.insert(2, -22.0); // Second strongest

        let mut routing = RoutingSnapshot::default();
        routing.channel_on.insert(1, false); // Channel 1 is MUTED!

        let res = localizer.localize_from_energies(&energies, 1000.0, Some(&routing), Some(1));
        let top = res.top_candidate.unwrap();
        // Channel 1 should have score 0 because it's muted, so Channel 2 must be top!
        assert_eq!(top.channel, 2);
    }
}
