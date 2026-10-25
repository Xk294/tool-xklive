use std::collections::{HashMap, HashSet};
use crate::core::models::{
    classify_target, extract_suspect_suffix, format_target_label, ActionProposal, ActiveNotch,
    Decision,
};

/// Hard ceiling for any gain increase the system may apply (PEQ boost or Ring-Out fader boost).
pub const HARD_MAX_BOOST_DB: f32 = 4.0;

#[derive(Debug, Clone)]
pub struct SafetyState {
    pub active_notches: HashMap<(i32, u8), ActiveNotch>,
    pub channel_locks: HashMap<u8, f64>,
    pub transaction_history: Vec<f64>,
    pub whitelist: HashSet<u8>,
    pub allowed_bands: HashMap<u8, Vec<u8>>,
    pub bus_whitelist: HashSet<u8>,
    pub bus_locks: HashMap<u8, f64>,
    pub bus_allowed_bands: HashMap<u8, Vec<u8>>,
    pub main_allowed_bands: Vec<u8>,
    pub max_boost_db: f32,
    pub max_cut_db: f32,
    pub probe_step_db: f32,
    pub probe_wait_ms: f32,
    pub max_transactions_per_sec: f32,
    pub lock_duration_s: f64,
    pub reclaim_on_exhaustion: bool,
    pub auto_release_wait_s: f64,
    pub auto_release_rate_db_per_s: f32,
    pub auto_release_enabled: bool,
}

impl Default for SafetyState {
    fn default() -> Self {
        let mut allowed_bands = HashMap::new();
        for ch in 1..=16 {
            allowed_bands.insert(ch, vec![3, 4]);
        }
        let mut bus_allowed_bands = HashMap::new();
        for b in 1..=6 {
            bus_allowed_bands.insert(b, vec![5, 6]);
        }

        Self {
            active_notches: HashMap::new(),
            channel_locks: HashMap::new(),
            transaction_history: Vec::new(),
            whitelist: (1..=16).collect(),
            allowed_bands,
            bus_whitelist: (1..=6).collect(),
            bus_locks: HashMap::new(),
            bus_allowed_bands,
            main_allowed_bands: vec![3, 4, 5, 6],
            max_boost_db: HARD_MAX_BOOST_DB,
            max_cut_db: -12.0,
            probe_step_db: -3.0,
            probe_wait_ms: 80.0,
            max_transactions_per_sec: 2.0,
            lock_duration_s: 10.0,
            reclaim_on_exhaustion: true,
            auto_release_wait_s: 20.0,
            auto_release_rate_db_per_s: 1.0,
            auto_release_enabled: true,
        }
    }
}

pub fn decide(
    state: &SafetyState,
    proposal: &ActionProposal,
    now: f64,
    get_current_gain: Option<&dyn Fn(u8, u8, &str) -> Option<f32>>,
) -> (SafetyState, Decision) {
    let (norm_target, target_key_id, ch, norm_bus) =
        classify_target(&proposal.target, proposal.channel, proposal.bus);
    let is_bus = norm_target == "bus";
    let is_main = norm_target == "main";
    let target_bus = norm_bus.unwrap_or(1);
    let tgt_name = format_target_label(norm_target, ch, norm_bus);

    if is_bus {
        if !state.bus_whitelist.contains(&target_bus) {
            return (
                state.clone(),
                Decision {
                    approved: false,
                    proposal: Some(proposal.clone()),
                    effective_gain_db: 0.0,
                    reason: format!("Bus {} không nằm trong danh sách cho phép (Bus Whitelist)", target_bus),
                    is_probing: false,
                    transaction_id: String::new(),
                    retryable: false,
                },
            );
        }
    } else if !is_main && !state.whitelist.contains(&ch) {
        return (
            state.clone(),
            Decision {
                approved: false,
                proposal: Some(proposal.clone()),
                effective_gain_db: 0.0,
                reason: format!("Kênh {} không nằm trong danh sách cho phép (Whitelist)", ch),
                is_probing: false,
                transaction_id: String::new(),
                retryable: false,
            },
        );
    }

    if is_bus {
        if let Some(&lock_until) = state.bus_locks.get(&target_bus) {
            if now < lock_until {
                let remaining = lock_until - now;
                return (
                    state.clone(),
                    Decision {
                        approved: false,
                        proposal: Some(proposal.clone()),
                        effective_gain_db: 0.0,
                        reason: format!("Bus {} đang bị tạm khóa ({:.1}s còn lại) do kỹ sư chỉnh tay", target_bus, remaining),
                        is_probing: false,
                        transaction_id: String::new(),
                        retryable: false,
                    },
                );
            }
        }
    } else if let Some(&lock_until) = state.channel_locks.get(&ch) {
        if now < lock_until {
            let remaining = lock_until - now;
            let label = if is_main { "Main LR".to_string() } else { format!("Kênh {}", ch) };
            return (
                state.clone(),
                Decision {
                    approved: false,
                    proposal: Some(proposal.clone()),
                    effective_gain_db: 0.0,
                    reason: format!("{} đang bị tạm khóa ({:.1}s còn lại) do kỹ sư chỉnh tay", label, remaining),
                    is_probing: false,
                    transaction_id: String::new(),
                    retryable: false,
                },
            );
        }
    }

    let recent_transactions: Vec<f64> = state
        .transaction_history
        .iter()
        .copied()
        .filter(|&t| now - t < 1.0)
        .collect();

    if recent_transactions.len() as f32 >= state.max_transactions_per_sec {
        let mut new_state = state.clone();
        new_state.transaction_history = recent_transactions;
        return (
            new_state,
            Decision {
                approved: false,
                proposal: Some(proposal.clone()),
                effective_gain_db: 0.0,
                reason: format!("Vượt quá hạn mức {} giao dịch/giây", state.max_transactions_per_sec),
                is_probing: false,
                transaction_id: String::new(),
                retryable: true,
            },
        );
    }

    if proposal.gain_db > state.max_boost_db {
        return (
            state.clone(),
            Decision {
                approved: false,
                proposal: Some(proposal.clone()),
                effective_gain_db: 0.0,
                reason: format!(
                    "Gain đề xuất ({:+.1}dB) vượt quá giới hạn an toàn (+{:.1}dB)",
                    proposal.gain_db, state.max_boost_db
                ),
                is_probing: false,
                transaction_id: String::new(),
                retryable: false,
            },
        );
    }

    let default_ch_bands = vec![3, 4];
    let default_bus_bands = vec![5, 6];
    let available_bands = if is_bus {
        state.bus_allowed_bands.get(&target_bus).unwrap_or(&default_bus_bands)
    } else if is_main {
        &state.main_allowed_bands
    } else {
        state.allowed_bands.get(&ch).unwrap_or(&default_ch_bands)
    };

    let mut allocated_band: Option<u8> = None;
    let mut existing_notch_key: Option<(i32, u8)> = None;

    for (&(t_id, b), notch) in &state.active_notches {
        if t_id == target_key_id && (notch.freq_hz - proposal.freq_hz).abs() / notch.freq_hz.max(20.0) <= 0.05 {
            existing_notch_key = Some((t_id, b));
            allocated_band = Some(b);
            break;
        }
    }

    if let Some(key) = existing_notch_key {
        let prev_notch = &state.active_notches[&key];
        let elapsed_ms = (now - prev_notch.last_updated_time) * 1000.0;
        if elapsed_ms >= 0.0 && elapsed_ms < state.probe_wait_ms as f64 {
            return (
                state.clone(),
                Decision {
                    approved: false,
                    proposal: Some(proposal.clone()),
                    effective_gain_db: prev_notch.gain_db,
                    reason: format!("Đang trong thời gian chờ thăm dò ({:.0}ms)", state.probe_wait_ms),
                    is_probing: true,
                    transaction_id: String::new(),
                    retryable: true,
                },
            );
        }
    }

    if allocated_band.is_none() {
        let used_bands: HashSet<u8> = state
            .active_notches
            .keys()
            .filter(|(t_id, _)| *t_id == target_key_id)
            .map(|(_, b)| *b)
            .collect();

        for &b in available_bands {
            if !used_bands.contains(&b) {
                allocated_band = Some(b);
                break;
            }
        }
    }

    let mut is_reclaimed = false;
    let mut reclaim_info = String::new();
    let mut reclaimed_original_gain = 0.0;
    let mut reclaimed_original_freq = proposal.freq_hz;
    let mut reclaimed_original_q = proposal.q.clamp(0.3, 10.0);

    if allocated_band.is_none() && state.reclaim_on_exhaustion {
        let mut candidates: Vec<(u8, &ActiveNotch)> = available_bands
            .iter()
            .filter_map(|&b| state.active_notches.get(&(target_key_id, b)).map(|n| (b, n)))
            .collect();

        if !candidates.is_empty() {
            candidates.sort_by(|a, b| {
                let a_abs = a.1.gain_db.abs();
                let b_abs = b.1.gain_db.abs();
                a_abs
                    .partial_cmp(&b_abs)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| a.1.last_updated_time.partial_cmp(&b.1.last_updated_time).unwrap_or(std::cmp::Ordering::Equal))
            });

            let (rec_band, rec_notch) = candidates[0];
            allocated_band = Some(rec_band);
            is_reclaimed = true;
            reclaimed_original_gain = rec_notch.original_gain_db;
            reclaimed_original_freq = rec_notch.original_freq_hz;
            reclaimed_original_q = rec_notch.original_q;
            reclaim_info = format!(
                "[CẠN BAND] Tái sử dụng Band {} (thay thế notch {:.1}Hz, {:+.1}dB) trên {}",
                rec_band, rec_notch.freq_hz, rec_notch.gain_db, tgt_name
            );
        }
    }

    let allocated_band = match allocated_band {
        Some(b) => b,
        None => {
            return (
                state.clone(),
                Decision {
                    approved: false,
                    proposal: Some(proposal.clone()),
                    effective_gain_db: 0.0,
                    reason: format!(
                        "{} đã sử dụng hết các band PEQ dành riêng cho hệ thống ({:?})",
                        tgt_name, available_bands
                    ),
                    is_probing: false,
                    transaction_id: String::new(),
                    retryable: false,
                },
            );
        }
    };

    let mut new_notches = state.active_notches.clone();
    let mut step_count = 1;
    let initial_cut = if proposal.gain_db < 0.0 && proposal.gain_db < state.probe_step_db {
        proposal.gain_db.max(state.max_cut_db)
    } else {
        state.probe_step_db
    };
    let mut target_gain = initial_cut;
    let mut orig_gain = proposal.original_gain_db;
    let mut orig_freq = proposal.freq_hz;
    let mut orig_q = proposal.q.clamp(0.3, 10.0);

    if let Some(key) = existing_notch_key {
        if !is_reclaimed {
            let prev_notch = &state.active_notches[&key];
            step_count = prev_notch.step_count + 1;
            target_gain = state.max_cut_db.max(prev_notch.gain_db + state.probe_step_db);
            orig_gain = prev_notch.original_gain_db;
            orig_freq = prev_notch.original_freq_hz;
            orig_q = prev_notch.original_q;
        }
    } else if is_reclaimed {
        orig_gain = reclaimed_original_gain;
        orig_freq = reclaimed_original_freq;
        orig_q = reclaimed_original_q;
    } else if let Some(get_gain) = get_current_gain {
        let target_type = if is_bus { "bus" } else if is_main { "main" } else { "ch" };
        let target_num = if is_bus { target_bus } else { ch };
        if let Some(g) = get_gain(target_num, allocated_band, target_type) {
            orig_gain = g;
        }
    }

    let clamped_q = proposal.q.clamp(0.3, 10.0);
    let normalized_target = if is_bus {
        "bus".to_string()
    } else if is_main {
        "main".to_string()
    } else {
        "ch".to_string()
    };

    let suspect_suffix = extract_suspect_suffix(&proposal.reason)
        .map(|s| format!(" {}", s))
        .unwrap_or_default();

    let reason_str = if is_reclaimed {
        format!("{}{}", reclaim_info, suspect_suffix)
    } else {
        format!(
            "Cắt thăm dò bước {} ({:+.1}dB tại {:.1}Hz){}",
            step_count, target_gain, proposal.freq_hz, suspect_suffix
        )
    };

    let notch_record = ActiveNotch {
        channel: ch,
        channel_name: None,
        band: allocated_band,
        freq_hz: proposal.freq_hz,
        gain_db: target_gain,
        q: clamped_q,
        is_probing: true,
        last_updated_time: now,
        step_count,
        age_s: 0.0,
        is_locked: false,
        target: normalized_target.clone(),
        bus: if is_bus { Some(target_bus) } else { None },
        original_gain_db: orig_gain,
        original_freq_hz: orig_freq,
        original_q: orig_q,
        reason: Some(reason_str.clone()),
        suspected_channel: proposal.suspected_channel,
    };

    new_notches.insert((target_key_id, allocated_band), notch_record);

    let mut updated_tx = recent_transactions;
    updated_tx.push(now);

    let mut new_state = state.clone();
    new_state.active_notches = new_notches;
    new_state.transaction_history = updated_tx;

    let mut approved_proposal = ActionProposal {
        id: proposal.id.clone(),
        channel: ch,
        band: Some(allocated_band),
        freq_hz: proposal.freq_hz,
        gain_db: target_gain,
        q: clamped_q,
        bus: if is_bus { Some(target_bus) } else { None },
        target: normalized_target,
        reason: reason_str,
        original_gain_db: orig_gain,
        confidence_score: proposal.confidence_score,
        created_at: if proposal.created_at > 0.0 { proposal.created_at } else { now },
        ttl_remaining_s: proposal.ttl_remaining_s,
        suspected_channel: proposal.suspected_channel,
    };
    approved_proposal.ensure_metadata(now);

    (
        new_state,
        Decision {
            approved: true,
            proposal: Some(approved_proposal),
            effective_gain_db: target_gain,
            reason: if is_reclaimed { reclaim_info } else { "Chấp thuận can thiệp hạ notch an toàn".to_string() },
            is_probing: true,
            transaction_id: format!("tx_{:.3}", now),
            retryable: false,
        },
    )
}

pub fn handle_manual_override(
    state: &SafetyState,
    channel: u8,
    now: f64,
    target: &str,
    bus: Option<u8>,
) -> SafetyState {
    let mut new_state = state.clone();
    if target == "bus" || bus.is_some() {
        let b = bus.unwrap_or(channel);
        new_state.bus_locks.insert(b, now + state.lock_duration_s);
    } else {
        new_state.channel_locks.insert(channel, now + state.lock_duration_s);
    }
    new_state
}

pub fn panic_rollback(state: &SafetyState, now: f64) -> (SafetyState, Vec<ActionProposal>) {
    let mut rollback_proposals = Vec::new();

    for (&(t_id, band), notch) in &state.active_notches {
        let inferred_bus = if t_id < 0 { notch.bus.or(Some((-t_id) as u8)) } else { notch.bus };
        let (norm_target, _, norm_ch, norm_bus) = classify_target(&notch.target, notch.channel, inferred_bus);
        let mut prop = ActionProposal {
            channel: norm_ch,
            band: Some(band),
            freq_hz: notch.original_freq_hz,
            gain_db: notch.original_gain_db,
            q: notch.original_q,
            bus: norm_bus,
            target: norm_target.to_string(),
            reason: format!("PANIC: Hoàn tác notch về giá trị gốc ({:+.1}dB)", notch.original_gain_db),
            original_gain_db: notch.original_gain_db,
            ..Default::default()
        };
        prop.ensure_metadata(now);
        rollback_proposals.push(prop);
    }

    let mut new_tx = state.transaction_history.clone();
    for _ in 0..rollback_proposals.len().max(1) {
        new_tx.push(now);
    }

    let mut new_state = state.clone();
    new_state.active_notches.clear();
    new_state.transaction_history = new_tx;

    (new_state, rollback_proposals)
}

pub fn check_auto_release(
    state: &SafetyState,
    now: f64,
    step_db: f32,
) -> (SafetyState, Vec<ActionProposal>) {
    if !state.auto_release_enabled || state.active_notches.is_empty() {
        return (state.clone(), Vec::new());
    }

    let recent_transactions: Vec<f64> = state
        .transaction_history
        .iter()
        .copied()
        .filter(|&t| now - t < 1.0)
        .collect();
    let max_tx = (state.max_transactions_per_sec.floor() as usize).max(1);
    let remaining_budget = max_tx.saturating_sub(recent_transactions.len());
    if remaining_budget == 0 {
        let mut throttled_state = state.clone();
        throttled_state.transaction_history = recent_transactions;
        return (throttled_state, Vec::new());
    }

    let mut proposals = Vec::new();
    let mut new_notches = state.active_notches.clone();
    let step_interval_s = (1.0 / state.auto_release_rate_db_per_s.max(0.1)) as f64;

    for (&(t_id, band), notch) in &state.active_notches {
        if proposals.len() >= remaining_budget {
            break;
        }

        let is_bus = notch.target == "bus" || t_id < 0;
        let is_main = !is_bus && (notch.target == "main" || notch.target == "lr" || notch.channel == 0 || t_id == 0);

        if is_bus {
            let bus_idx = notch.bus.unwrap_or((-t_id) as u8);
            if state.bus_locks.get(&bus_idx).map_or(false, |&until| now < until) {
                continue;
            }
            if let Some(allowed) = state.bus_allowed_bands.get(&bus_idx) {
                if !allowed.contains(&band) {
                    continue;
                }
            } else {
                continue;
            }
        } else {
            let ch_key = if is_main { 0 } else { notch.channel };
            if state.channel_locks.get(&ch_key).map_or(false, |&until| now < until) {
                continue;
            }
            if is_main {
                if !state.main_allowed_bands.contains(&band) {
                    continue;
                }
            } else if let Some(allowed) = state.allowed_bands.get(&notch.channel) {
                if !allowed.contains(&band) {
                    continue;
                }
            } else {
                continue;
            }
        }

        let idle_time = now - notch.last_updated_time;
        if idle_time >= state.auto_release_wait_s {
            let target_baseline = notch.original_gain_db;
            let new_gain = ((notch.gain_db + step_db) * 10.0).round() / 10.0;
            let inferred_bus = if is_bus { notch.bus.or(Some((-t_id) as u8)) } else { None };
            let (target_type, _, norm_ch, norm_bus) = classify_target(&notch.target, notch.channel, inferred_bus);
            let tgt_name = format_target_label(target_type, norm_ch, norm_bus);
            let target_str = target_type.to_string();

            if new_gain >= target_baseline {
                new_notches.remove(&(t_id, band));
                let mut prop = ActionProposal {
                    channel: if is_bus || is_main { 0 } else { notch.channel },
                    band: Some(band),
                    freq_hz: notch.original_freq_hz,
                    gain_db: target_baseline,
                    q: notch.original_q,
                    bus: if is_bus { notch.bus } else { None },
                    target: target_str,
                    reason: format!(
                        "Auto-release: Nhả hoàn toàn Band {} về {:+.1}dB trên {}",
                        band, target_baseline, tgt_name
                    ),
                    original_gain_db: target_baseline,
                    ..Default::default()
                };
                prop.ensure_metadata(now);
                proposals.push(prop);
            } else {
                let next_update_anchor = (now - state.auto_release_wait_s + step_interval_s).min(now);
                let updated = ActiveNotch {
                    channel: if is_bus || is_main { 0 } else { notch.channel },
                    channel_name: notch.channel_name.clone(),
                    band,
                    freq_hz: notch.freq_hz,
                    gain_db: new_gain,
                    q: notch.q,
                    is_probing: false,
                    last_updated_time: next_update_anchor,
                    step_count: notch.step_count,
                    age_s: (now - notch.last_updated_time).max(0.0),
                    is_locked: false,
                    target: target_str.clone(),
                    bus: if is_bus { notch.bus } else { None },
                    original_gain_db: notch.original_gain_db,
                    original_freq_hz: notch.original_freq_hz,
                    original_q: notch.original_q,
                    reason: notch.reason.clone(),
                    suspected_channel: notch.suspected_channel,
                };
                new_notches.insert((t_id, band), updated);
                let mut prop = ActionProposal {
                    channel: if is_bus || is_main { 0 } else { notch.channel },
                    band: Some(band),
                    freq_hz: notch.freq_hz,
                    gain_db: new_gain,
                    q: notch.q,
                    bus: if is_bus { notch.bus } else { None },
                    target: target_str,
                    reason: format!(
                        "Auto-release: Nhả bước Band {} lên {:+.1}dB trên {}",
                        band, new_gain, tgt_name
                    ),
                    original_gain_db: notch.original_gain_db,
                    ..Default::default()
                };
                prop.ensure_metadata(now);
                proposals.push(prop);
            }
        }
    }

    let mut new_tx = recent_transactions;
    for _ in 0..proposals.len() {
        new_tx.push(now);
    }

    let mut new_state = state.clone();
    new_state.active_notches = new_notches;
    new_state.transaction_history = new_tx;

    (new_state, proposals)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_whitelist_rejection() {
        let mut state = SafetyState::default();
        state.whitelist = [1, 2, 3].into_iter().collect();

        let prop = ActionProposal {
            channel: 4,
            freq_hz: 1000.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };

        let (_, dec) = decide(&state, &prop, 10.0, None);
        assert!(!dec.approved);
        assert!(!dec.retryable);
        assert!(dec.reason.contains("Whitelist"));
    }

    #[test]
    fn test_manual_override_lock_10s() {
        let state = SafetyState::default();
        let state = handle_manual_override(&state, 2, 5.0, "ch", None);

        let prop = ActionProposal {
            channel: 2,
            freq_hz: 1000.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };

        let (state, dec1) = decide(&state, &prop, 10.0, None);
        assert!(!dec1.approved);
        assert!(dec1.reason.contains("chỉnh tay"));

        let (_, dec2) = decide(&state, &prop, 15.1, None);
        assert!(dec2.approved);
    }

    #[test]
    fn test_rate_limit_2_transactions_per_sec() {
        let state = SafetyState {
            max_transactions_per_sec: 2.0,
            ..Default::default()
        };

        let prop1 = ActionProposal {
            channel: 1,
            freq_hz: 1000.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };
        let prop2 = ActionProposal {
            channel: 2,
            freq_hz: 2000.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };
        let prop3 = ActionProposal {
            channel: 3,
            freq_hz: 3000.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };

        let (state, d1) = decide(&state, &prop1, 1.0, None);
        assert!(d1.approved);

        let (state, d2) = decide(&state, &prop2, 1.2, None);
        assert!(d2.approved);

        let (state, d3) = decide(&state, &prop3, 1.5, None);
        assert!(!d3.approved);
        assert!(d3.retryable);
        assert!(d3.reason.contains("hạn mức"));

        let (_, d4) = decide(&state, &prop3, 2.1, None);
        assert!(d4.approved);
    }

    #[test]
    fn test_max_boost_guard() {
        let state = SafetyState {
            max_boost_db: 4.0,
            ..Default::default()
        };

        let prop = ActionProposal {
            channel: 1,
            freq_hz: 1000.0,
            gain_db: 5.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };

        let (_, dec) = decide(&state, &prop, 1.0, None);
        assert!(!dec.approved);
        assert!(dec.reason.contains("giới hạn an toàn"));
    }

    #[test]
    fn test_system_band_isolation_and_exhaustion() {
        let mut allowed = HashMap::new();
        allowed.insert(1, vec![3, 4]);
        let state = SafetyState {
            allowed_bands: allowed,
            reclaim_on_exhaustion: false,
            ..Default::default()
        };

        let prop1 = ActionProposal {
            channel: 1,
            freq_hz: 1000.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };
        let (state, d1) = decide(&state, &prop1, 1.0, None);
        assert!(d1.approved);
        assert_eq!(d1.proposal.unwrap().band, Some(3));

        let prop2 = ActionProposal {
            channel: 1,
            freq_hz: 2000.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };
        let (state, d2) = decide(&state, &prop2, 2.1, None);
        assert!(d2.approved);
        assert_eq!(d2.proposal.unwrap().band, Some(4));

        let prop3 = ActionProposal {
            channel: 1,
            freq_hz: 3000.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };
        let (_, d3) = decide(&state, &prop3, 3.2, None);
        assert!(!d3.approved);
        assert!(d3.reason.contains("hết các band PEQ"));
    }

    #[test]
    fn test_band_reclaim_on_exhaustion() {
        let state = SafetyState::default();

        let prop1 = ActionProposal {
            channel: 1,
            freq_hz: 1000.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };
        let (state, _) = decide(&state, &prop1, 1.0, None);
        let (state, _) = decide(&state, &prop1, 2.1, None); // Band 3 is now at -6.0 dB

        let prop2 = ActionProposal {
            channel: 1,
            freq_hz: 2000.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };
        let (state, _) = decide(&state, &prop2, 3.2, None); // Band 4 is at -3.0 dB (shallower)

        let prop3 = ActionProposal {
            channel: 1,
            freq_hz: 3500.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };
        let (_, d3) = decide(&state, &prop3, 4.5, None);
        assert!(d3.approved);
        assert_eq!(d3.proposal.unwrap().band, Some(4));
    }

    #[test]
    fn test_main_lr_band_allocation_and_probe_wait() {
        let state = SafetyState::default();
        let prop = ActionProposal {
            channel: 0,
            freq_hz: 2500.0,
            gain_db: -3.0,
            q: 10.0,
            target: "main".to_string(),
            ..Default::default()
        };

        let (state, d1) = decide(&state, &prop, 10.0, None);
        assert!(d1.approved);
        let approved = d1.proposal.unwrap();
        assert_eq!(approved.band, Some(3));
        assert_eq!(approved.target, "main");

        // Within 80ms probe_wait_ms -> rejected
        let (_, d_early) = decide(&state, &prop, 10.04, None);
        assert!(!d_early.approved);
        assert!(d_early.retryable);
        assert!(d_early.reason.contains("thăm dò"));

        // After 100ms -> steps deeper to -6.0 dB
        let (_, d2) = decide(&state, &prop, 10.15, None);
        assert!(d2.approved);
        assert_eq!(d2.effective_gain_db, -6.0);
    }

    #[test]
    fn test_incremental_probing_step() {
        let state = SafetyState {
            probe_step_db: -3.0,
            max_cut_db: -12.0,
            ..Default::default()
        };

        let prop = ActionProposal {
            channel: 1,
            freq_hz: 1000.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };

        let (state, d1) = decide(&state, &prop, 1.0, None);
        assert!(d1.approved);
        assert_eq!(d1.effective_gain_db, -3.0);

        let (state, d2) = decide(&state, &prop, 2.1, None);
        assert!(d2.approved);
        assert_eq!(d2.effective_gain_db, -6.0);

        let (state, d3) = decide(&state, &prop, 3.2, None);
        assert!(d3.approved);
        assert_eq!(d3.effective_gain_db, -9.0);

        let (state, d4) = decide(&state, &prop, 4.3, None);
        assert!(d4.approved);
        assert_eq!(d4.effective_gain_db, -12.0);

        let (_, d5) = decide(&state, &prop, 5.4, None);
        assert!(d5.approved);
        assert_eq!(d5.effective_gain_db, -12.0);
    }

    #[test]
    fn test_auto_release_continuous_rate() {
        let state = SafetyState::default();
        let prop = ActionProposal {
            channel: 1,
            freq_hz: 1200.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };
        let (state, _) = decide(&state, &prop, 0.0, None);

        // At t = 20.0s -> first +1 dB release (-3.0 -> -2.0 dB)
        let (state, r1) = check_auto_release(&state, 20.0, 1.0);
        assert_eq!(r1.len(), 1);
        assert_eq!(r1[0].gain_db, -2.0);

        // 1 second later at t = 21.0s -> second +1 dB release (-2.0 -> -1.0 dB)
        let (state, r2) = check_auto_release(&state, 21.0, 1.0);
        assert_eq!(r2.len(), 1);
        assert_eq!(r2[0].gain_db, -1.0);

        // 1 second later at t = 22.0s -> final release to 0.0 dB and notch removed
        let (state, r3) = check_auto_release(&state, 22.0, 1.0);
        assert_eq!(r3.len(), 1);
        assert_eq!(r3[0].gain_db, 0.0);
        assert!(state.active_notches.is_empty());
    }

    #[test]
    fn test_panic_rollback() {
        let state = SafetyState::default();
        let prop = ActionProposal {
            channel: 1,
            freq_hz: 1000.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            original_gain_db: -1.5,
            ..Default::default()
        };
        let (state, _) = decide(&state, &prop, 1.0, None);
        assert_eq!(state.active_notches.len(), 1);

        let (state, rollbacks) = panic_rollback(&state, 2.0);
        assert_eq!(state.active_notches.len(), 0);
        assert_eq!(rollbacks.len(), 1);
        assert_eq!(rollbacks[0].gain_db, -1.5);
    }

    #[test]
    fn test_auto_release_respects_manual_override_lock() {
        let state = SafetyState::default();
        let prop = ActionProposal {
            channel: 1,
            freq_hz: 1500.0,
            gain_db: -3.0,
            q: 8.0,
            target: "ch".to_string(),
            ..Default::default()
        };
        let (state, _) = decide(&state, &prop, 0.0, None);

        // Technician manually overrides channel 1 at t = 15.0s (locked until t = 25.0s)
        let state = handle_manual_override(&state, 1, 15.0, "ch", None);

        // At t = 21.0s (idle >= 20s, but still inside 10s manual override lock) -> must NOT auto-release
        let (state, blocked_rel) = check_auto_release(&state, 21.0, 1.0);
        assert!(blocked_rel.is_empty());
        assert_eq!(state.active_notches.len(), 1);

        // At t = 25.5s (lock expired) -> auto-release proceeds normally
        let (_, allowed_rel) = check_auto_release(&state, 25.5, 1.0);
        assert_eq!(allowed_rel.len(), 1);
    }
}
