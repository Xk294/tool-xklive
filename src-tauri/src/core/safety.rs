use std::collections::{HashMap, HashSet};
use crate::core::models::{ActionProposal, ActiveNotch, Decision};

#[derive(Debug, Clone)]
pub struct SafetyState {
    pub active_notches: HashMap<(i32, u8), ActiveNotch>, // (target_key_id, band) -> ActiveNotch
    pub channel_locks: HashMap<u8, f64>,                 // channel -> lock_until_timestamp
    pub transaction_history: Vec<f64>,                  // timestamps of recent transactions
    pub whitelist: HashSet<u8>,                         // allowed channels (1..=16)
    pub allowed_bands: HashMap<u8, Vec<u8>>,            // channel -> allowed PEQ bands (e.g. [3, 4])
    pub bus_whitelist: HashSet<u8>,                     // allowed busses (1..=6)
    pub bus_locks: HashMap<u8, f64>,                    // bus -> lock_until_timestamp
    pub bus_allowed_bands: HashMap<u8, Vec<u8>>,        // bus -> allowed bands (e.g. [5, 6])
    pub max_boost_db: f32,                              // +4.0 dB
    pub max_cut_db: f32,                                // -12.0 dB
    pub probe_step_db: f32,                             // -3.0 dB
    pub probe_wait_ms: f32,                             // 80.0 ms
    pub max_transactions_per_sec: f32,                  // 2.0
    pub lock_duration_s: f64,                           // 10.0 s
    pub reclaim_on_exhaustion: bool,
    pub auto_release_wait_s: f64,                       // 20.0 s
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
            max_boost_db: 4.0,
            max_cut_db: -12.0,
            probe_step_db: -3.0,
            probe_wait_ms: 80.0,
            max_transactions_per_sec: 2.0,
            lock_duration_s: 10.0,
            reclaim_on_exhaustion: false,
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
    let is_bus = proposal.target == "bus" || (proposal.bus.is_some() && proposal.target != "ch");
    let target_bus = proposal.bus.unwrap_or(proposal.channel);
    let ch = proposal.channel;

    // 1. Check Whitelist
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
                },
            );
        }
    } else if !state.whitelist.contains(&ch) {
        return (
            state.clone(),
            Decision {
                approved: false,
                proposal: Some(proposal.clone()),
                effective_gain_db: 0.0,
                reason: format!("Kênh {} không nằm trong danh sách cho phép (Whitelist)", ch),
                is_probing: false,
                transaction_id: String::new(),
            },
        );
    }

    // 2. Check Manual Override Lock (10s)
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
                    },
                );
            }
        }
    } else if let Some(&lock_until) = state.channel_locks.get(&ch) {
        if now < lock_until {
            let remaining = lock_until - now;
            return (
                state.clone(),
                Decision {
                    approved: false,
                    proposal: Some(proposal.clone()),
                    effective_gain_db: 0.0,
                    reason: format!("Kênh {} đang bị tạm khóa ({:.1}s còn lại) do kỹ sư chỉnh tay", ch, remaining),
                    is_probing: false,
                    transaction_id: String::new(),
                },
            );
        }
    }

    // 3. Rate Limiting (max 2 tx/sec)
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
            },
        );
    }

    // 4. Max Boost Guard
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
            },
        );
    }

    // 5. Band Allocation
    let default_ch_bands = vec![3, 4];
    let default_bus_bands = vec![5, 6];
    let (available_bands, target_key_id) = if is_bus {
        (
            state.bus_allowed_bands.get(&target_bus).unwrap_or(&default_bus_bands),
            -(target_bus as i32),
        )
    } else {
        (
            state.allowed_bands.get(&ch).unwrap_or(&default_ch_bands),
            ch as i32,
        )
    };

    let mut allocated_band: Option<u8> = None;
    let mut existing_notch_key: Option<(i32, u8)> = None;

    // Check for existing notch within 5% frequency tolerance
    for (&(t_id, b), notch) in &state.active_notches {
        if t_id == target_key_id && (notch.freq_hz - proposal.freq_hz).abs() / notch.freq_hz <= 0.05 {
            existing_notch_key = Some((t_id, b));
            allocated_band = Some(b);
            break;
        }
    }

    // If not found, find an unused band
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

    // Handle band exhaustion reclaim
    let mut is_reclaimed = false;
    let mut reclaim_info = String::new();
    let mut reclaimed_original_gain = 0.0;

    if allocated_band.is_none() && state.reclaim_on_exhaustion {
        let mut candidates: Vec<(u8, &ActiveNotch)> = available_bands
            .iter()
            .filter_map(|&b| state.active_notches.get(&(target_key_id, b)).map(|n| (b, n)))
            .collect();

        if !candidates.is_empty() {
            candidates.sort_by(|a, b| {
                let a_abs = a.1.current_gain_db.abs();
                let b_abs = b.1.current_gain_db.abs();
                a_abs
                    .partial_cmp(&b_abs)
                    .unwrap_or(std::cmp::Ordering::Equal)
                    .then_with(|| a.1.last_updated_time.partial_cmp(&b.1.last_updated_time).unwrap_or(std::cmp::Ordering::Equal))
            });

            let (rec_band, rec_notch) = candidates[0];
            allocated_band = Some(rec_band);
            is_reclaimed = true;
            reclaimed_original_gain = rec_notch.original_gain_db;
            let tgt_name = if is_bus { format!("Bus {}", target_bus) } else { format!("Kênh {}", ch) };
            reclaim_info = format!(
                "[CẠN BAND] Tái sử dụng Band {} (thay thế notch {:.1}Hz, {:+.1}dB) trên {}",
                rec_band, rec_notch.freq_hz, rec_notch.current_gain_db, tgt_name
            );
        }
    }

    let allocated_band = match allocated_band {
        Some(b) => b,
        None => {
            let tgt_name = if is_bus { format!("Bus {}", target_bus) } else { format!("Kênh {}", ch) };
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
                },
            );
        }
    };

    // 6. -3 dB Incremental Probing
    let mut new_notches = state.active_notches.clone();
    let mut step_count = 1;
    let mut target_gain = state.probe_step_db;
    let mut orig_gain = proposal.original_gain_db;

    if let Some(key) = existing_notch_key {
        if !is_reclaimed {
            let prev_notch = &state.active_notches[&key];
            step_count = prev_notch.probe_step_count + 1;
            target_gain = state.max_cut_db.max(prev_notch.current_gain_db + state.probe_step_db);
            orig_gain = prev_notch.original_gain_db;
        }
    } else if is_reclaimed {
        orig_gain = reclaimed_original_gain;
    } else if let Some(get_gain) = get_current_gain {
        let target_type = if is_bus { "bus" } else if ch == 0 { "main" } else { "ch" };
        let target_num = if is_bus { target_bus } else { ch };
        if let Some(g) = get_gain(target_num, allocated_band, target_type) {
            orig_gain = g;
        }
    }

    let clamped_q = proposal.q.clamp(0.3, 10.0);

    let notch_record = ActiveNotch {
        channel: if is_bus { 0 } else { ch },
        channel_name: None,
        band: allocated_band,
        freq_hz: proposal.freq_hz,
        current_gain_db: target_gain,
        target_gain_db: target_gain,
        q: clamped_q,
        is_probing: true,
        last_updated_time: now,
        probe_step_count: step_count,
        target: if is_bus { "bus".to_string() } else if ch == 0 { "main".to_string() } else { "ch".to_string() },
        bus: if is_bus { Some(target_bus) } else { None },
        original_gain_db: orig_gain,
    };

    new_notches.insert((target_key_id, allocated_band), notch_record);

    let mut updated_tx = recent_transactions;
    updated_tx.push(now);

    let mut new_state = state.clone();
    new_state.active_notches = new_notches;
    new_state.transaction_history = updated_tx;

    let reason_str = if is_reclaimed {
        reclaim_info.clone()
    } else {
        format!("Cắt thăm dò bước {} ({:+.1}dB tại {:.1}Hz)", step_count, target_gain, proposal.freq_hz)
    };

    let approved_proposal = ActionProposal {
        channel: if is_bus { 0 } else { ch },
        band: Some(allocated_band),
        freq_hz: proposal.freq_hz,
        gain_db: target_gain,
        q: clamped_q,
        bus: if is_bus { Some(target_bus) } else { None },
        target: if is_bus { "bus".to_string() } else if ch == 0 { "main".to_string() } else { "ch".to_string() },
        reason: reason_str,
        original_gain_db: orig_gain,
    };

    (
        new_state,
        Decision {
            approved: true,
            proposal: Some(approved_proposal),
            effective_gain_db: target_gain,
            reason: if is_reclaimed { reclaim_info } else { "Chấp thuận can thiệp hạ notch an toàn".to_string() },
            is_probing: true,
            transaction_id: format!("tx_{:.3}", now),
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
        let is_bus = notch.target == "bus" || t_id < 0;
        rollback_proposals.push(ActionProposal {
            channel: if is_bus { 0 } else { notch.channel },
            band: Some(band),
            freq_hz: notch.freq_hz,
            gain_db: notch.original_gain_db,
            q: notch.q,
            bus: if is_bus { notch.bus } else { None },
            target: if is_bus { "bus".to_string() } else if notch.channel == 0 { "main".to_string() } else { "ch".to_string() },
            reason: format!("PANIC: Hoàn tác notch về giá trị gốc ({:+.1}dB)", notch.original_gain_db),
            original_gain_db: notch.original_gain_db,
        });
    }

    let mut new_tx = state.transaction_history.clone();
    new_tx.push(now);

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

    let mut proposals = Vec::new();
    let mut new_notches = state.active_notches.clone();

    for (&(t_id, band), notch) in &state.active_notches {
        let is_bus = notch.target == "bus" || t_id < 0;

        if is_bus {
            let bus_idx = notch.bus.unwrap_or((-t_id) as u8);
            if let Some(allowed) = state.bus_allowed_bands.get(&bus_idx) {
                if !allowed.contains(&band) {
                    continue;
                }
            } else {
                continue;
            }
        } else if let Some(allowed) = state.allowed_bands.get(&notch.channel) {
            if !allowed.contains(&band) {
                continue;
            }
        } else {
            continue;
        }

        let idle_time = now - notch.last_updated_time;
        if idle_time >= state.auto_release_wait_s {
            let target_baseline = notch.original_gain_db;
            let new_gain = ((notch.current_gain_db + step_db) * 10.0).round() / 10.0;

            if new_gain >= target_baseline {
                new_notches.remove(&(t_id, band));
                let tgt_name = if is_bus { format!("Bus {:?}", notch.bus) } else { format!("Kênh {}", notch.channel) };
                proposals.push(ActionProposal {
                    channel: if is_bus { 0 } else { notch.channel },
                    band: Some(band),
                    freq_hz: notch.freq_hz,
                    gain_db: target_baseline,
                    q: notch.q,
                    bus: if is_bus { notch.bus } else { None },
                    target: if is_bus { "bus".to_string() } else if notch.channel == 0 { "main".to_string() } else { "ch".to_string() },
                    reason: format!(
                        "Auto-release: Nhả hoàn toàn Band {} về {:+.1}dB sau {:.1}s ổn định trên {}",
                        band, target_baseline, idle_time, tgt_name
                    ),
                    original_gain_db: target_baseline,
                });
            } else {
                let updated = ActiveNotch {
                    channel: if is_bus { 0 } else { notch.channel },
                    channel_name: notch.channel_name.clone(),
                    band,
                    freq_hz: notch.freq_hz,
                    current_gain_db: new_gain,
                    target_gain_db: new_gain,
                    q: notch.q,
                    is_probing: false,
                    last_updated_time: now,
                    probe_step_count: notch.probe_step_count,
                    target: if is_bus { "bus".to_string() } else { "ch".to_string() },
                    bus: if is_bus { notch.bus } else { None },
                    original_gain_db: notch.original_gain_db,
                };
                new_notches.insert((t_id, band), updated);
                let tgt_name = if is_bus { format!("Bus {:?}", notch.bus) } else { format!("Kênh {}", notch.channel) };
                proposals.push(ActionProposal {
                    channel: if is_bus { 0 } else { notch.channel },
                    band: Some(band),
                    freq_hz: notch.freq_hz,
                    gain_db: new_gain,
                    q: notch.q,
                    bus: if is_bus { notch.bus } else { None },
                    target: if is_bus { "bus".to_string() } else if notch.channel == 0 { "main".to_string() } else { "ch".to_string() },
                    reason: format!(
                        "Auto-release: Nhả bước Band {} lên {:+.1}dB sau {:.1}s ổn định trên {}",
                        band, new_gain, idle_time, tgt_name
                    ),
                    original_gain_db: notch.original_gain_db,
                });
            }
        }
    }

    let mut new_tx = state.transaction_history.clone();
    if !proposals.is_empty() {
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
            bus: None,
            band: None,
            target: "ch".to_string(),
            reason: String::new(),
            original_gain_db: 0.0,
        };

        let (_, dec) = decide(&state, &prop, 10.0, None);
        assert!(!dec.approved);
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
            bus: None,
            band: None,
            target: "ch".to_string(),
            reason: String::new(),
            original_gain_db: 0.0,
        };

        // Try at t = 10.0s (still locked until 15.0s)
        let (state, dec1) = decide(&state, &prop, 10.0, None);
        assert!(!dec1.approved);
        assert!(dec1.reason.contains("chỉnh tay"));

        // Try at t = 15.1s (lock expired)
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
            bus: None,
            band: None,
            target: "ch".to_string(),
            reason: String::new(),
            original_gain_db: 0.0,
        };
        let prop2 = ActionProposal {
            channel: 2,
            freq_hz: 2000.0,
            gain_db: -3.0,
            q: 8.0,
            bus: None,
            band: None,
            target: "ch".to_string(),
            reason: String::new(),
            original_gain_db: 0.0,
        };
        let prop3 = ActionProposal {
            channel: 3,
            freq_hz: 3000.0,
            gain_db: -3.0,
            q: 8.0,
            bus: None,
            band: None,
            target: "ch".to_string(),
            reason: String::new(),
            original_gain_db: 0.0,
        };

        // Tx 1 at t = 1.0 -> OK
        let (state, d1) = decide(&state, &prop1, 1.0, None);
        assert!(d1.approved);

        // Tx 2 at t = 1.2 -> OK
        let (state, d2) = decide(&state, &prop2, 1.2, None);
        assert!(d2.approved);

        // Tx 3 at t = 1.5 -> Exceeds rate limit
        let (state, d3) = decide(&state, &prop3, 1.5, None);
        assert!(!d3.approved);
        assert!(d3.reason.contains("hạn mức"));

        // Tx 3 at t = 2.1 -> OK (> 1s after tx 1)
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
            bus: None,
            band: None,
            target: "ch".to_string(),
            reason: String::new(),
            original_gain_db: 0.0,
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
            ..Default::default()
        };

        let prop1 = ActionProposal {
            channel: 1,
            freq_hz: 1000.0,
            gain_db: -3.0,
            q: 8.0,
            bus: None,
            band: None,
            target: "ch".to_string(),
            reason: String::new(),
            original_gain_db: 0.0,
        };
        let (state, d1) = decide(&state, &prop1, 1.0, None);
        assert!(d1.approved);
        assert_eq!(d1.proposal.unwrap().band, Some(3));

        let prop2 = ActionProposal {
            channel: 1,
            freq_hz: 2000.0,
            gain_db: -3.0,
            q: 8.0,
            bus: None,
            band: None,
            target: "ch".to_string(),
            reason: String::new(),
            original_gain_db: 0.0,
        };
        let (state, d2) = decide(&state, &prop2, 2.1, None);
        assert!(d2.approved);
        assert_eq!(d2.proposal.unwrap().band, Some(4));

        let prop3 = ActionProposal {
            channel: 1,
            freq_hz: 3000.0,
            gain_db: -3.0,
            q: 8.0,
            bus: None,
            band: None,
            target: "ch".to_string(),
            reason: String::new(),
            original_gain_db: 0.0,
        };
        let (_, d3) = decide(&state, &prop3, 3.2, None);
        assert!(!d3.approved);
        assert!(d3.reason.contains("hết các band PEQ"));
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
            bus: None,
            band: None,
            target: "ch".to_string(),
            reason: String::new(),
            original_gain_db: 0.0,
        };

        // Step 1: -3 dB
        let (state, d1) = decide(&state, &prop, 1.0, None);
        assert!(d1.approved);
        assert_eq!(d1.effective_gain_db, -3.0);

        // Step 2: -6 dB
        let (state, d2) = decide(&state, &prop, 2.1, None);
        assert!(d2.approved);
        assert_eq!(d2.effective_gain_db, -6.0);

        // Step 3: -9 dB
        let (state, d3) = decide(&state, &prop, 3.2, None);
        assert!(d3.approved);
        assert_eq!(d3.effective_gain_db, -9.0);

        // Step 4: -12 dB (max cut)
        let (state, d4) = decide(&state, &prop, 4.3, None);
        assert!(d4.approved);
        assert_eq!(d4.effective_gain_db, -12.0);

        // Step 5: Clamped at -12 dB
        let (_, d5) = decide(&state, &prop, 5.4, None);
        assert!(d5.approved);
        assert_eq!(d5.effective_gain_db, -12.0);
    }

    #[test]
    fn test_panic_rollback() {
        let state = SafetyState::default();
        let prop = ActionProposal {
            channel: 1,
            freq_hz: 1000.0,
            gain_db: -3.0,
            q: 8.0,
            bus: None,
            band: None,
            target: "ch".to_string(),
            reason: String::new(),
            original_gain_db: -1.5,
        };
        let (state, _) = decide(&state, &prop, 1.0, None);
        assert_eq!(state.active_notches.len(), 1);

        let (state, rollbacks) = panic_rollback(&state, 2.0);
        assert_eq!(state.active_notches.len(), 0);
        assert_eq!(rollbacks.len(), 1);
        assert_eq!(rollbacks[0].gain_db, -1.5);
    }
}
