use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum ConnectionState {
    Disconnected,
    Connecting,
    Connected,
    Reconnecting,
    Mock,
}

impl Default for ConnectionState {
    fn default() -> Self {
        Self::Disconnected
    }
}

fn default_target() -> String {
    "ch".to_string()
}

fn default_confidence() -> f32 {
    0.85
}

fn default_ttl() -> f32 {
    30.0
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PEQBand {
    pub channel: u8,
    pub band: u8,
    pub freq_hz: f32,
    pub gain_db: f32,
    pub q: f32,
    pub is_on: bool,
    pub filter_type: u8,
    #[serde(default = "default_target")]
    pub target: String,
    #[serde(default)]
    pub bus: Option<u8>,
}

impl Default for PEQBand {
    fn default() -> Self {
        Self {
            channel: 1,
            band: 3,
            freq_hz: 1000.0,
            gain_db: 0.0,
            q: 8.0,
            is_on: true,
            filter_type: 2,
            target: "ch".to_string(),
            bus: None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ActionProposal {
    #[serde(default)]
    pub id: String,
    pub channel: u8,
    pub freq_hz: f32,
    pub gain_db: f32,
    pub q: f32,
    pub bus: Option<u8>,
    pub band: Option<u8>,
    pub target: String,
    pub reason: String,
    pub original_gain_db: f32,
    #[serde(default = "default_confidence")]
    pub confidence_score: f32,
    #[serde(default)]
    pub created_at: f64,
    #[serde(default = "default_ttl")]
    pub ttl_remaining_s: f32,
    #[serde(default)]
    pub suspected_channel: Option<u8>,
}

impl Default for ActionProposal {
    fn default() -> Self {
        Self {
            id: String::new(),
            channel: 1,
            freq_hz: 1000.0,
            gain_db: -3.0,
            q: 8.0,
            bus: None,
            band: None,
            target: "ch".to_string(),
            reason: String::new(),
            original_gain_db: 0.0,
            confidence_score: 0.85,
            created_at: 0.0,
            ttl_remaining_s: 30.0,
            suspected_channel: None,
        }
    }
}

impl ActionProposal {
    pub fn ensure_metadata(&mut self, now: f64) {
        if self.id.is_empty() {
            let tgt_idx = self.bus.unwrap_or(self.channel);
            self.id = format!("{}_{}_{:.0}", self.target, tgt_idx, self.freq_hz);
        }
        if self.confidence_score <= 0.0 {
            self.confidence_score = 0.85;
        }
        if self.created_at <= 0.0 {
            self.created_at = now;
        }
        if self.ttl_remaining_s <= 0.0 {
            self.ttl_remaining_s = 30.0;
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Decision {
    pub approved: bool,
    pub proposal: Option<ActionProposal>,
    pub effective_gain_db: f32,
    pub reason: String,
    pub is_probing: bool,
    pub transaction_id: String,
    /// Rejection is temporary (rate limit / probe wait): the same proposal may succeed on a later frame.
    #[serde(default)]
    pub retryable: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ActiveNotch {
    pub channel: u8,
    pub channel_name: Option<String>,
    pub band: u8,
    pub freq_hz: f32,
    pub gain_db: f32,
    pub q: f32,
    pub is_probing: bool,
    pub last_updated_time: f64,
    pub step_count: u32,
    pub age_s: f64,
    pub is_locked: bool,
    pub target: String,
    pub bus: Option<u8>,
    pub original_gain_db: f32,
    pub original_freq_hz: f32,
    pub original_q: f32,
    #[serde(default)]
    pub reason: Option<String>,
    #[serde(default)]
    pub suspected_channel: Option<u8>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ChannelInfo {
    pub channel: u8,
    pub name: String,
    pub color: u8,
    pub is_muted: bool,
    pub level: f32,
    pub is_locked: bool,
    pub whitelisted: bool,
    #[serde(default)]
    pub hpf_enabled: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LogEntry {
    pub id: u64,
    pub time: String,
    pub text: String,
    #[serde(rename = "type")]
    pub entry_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub text_code: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub params: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CapabilityMap {
    pub model: String,
    pub firmware: String,
    pub ip: String,
    pub port: u16,
    pub num_channels: u8,
    pub num_busses: u8,
    pub channel_peq_bands: u8,
    pub bus_peq_bands: u8,
    pub lr_peq_bands: u8,
    pub lr_prefix: String,
    pub probe_completed: bool,
}

impl CapabilityMap {
    pub fn channel_count_for_model(model: &str) -> u8 {
        let upper = model.to_uppercase();
        if upper.contains("XR12") || upper.contains("MR12") {
            12
        } else {
            16
        }
    }

    pub fn supports_usb_multitrack(model: &str) -> bool {
        let upper = model.to_uppercase();
        if upper.contains("XR12")
            || upper.contains("MR12")
            || upper.contains("XR16")
        {
            return false;
        }
        true
    }
}

pub fn classify_target(
    target: &str,
    channel: u8,
    bus: Option<u8>,
) -> (&'static str, i32, u8, Option<u8>) {
    let is_bus = target == "bus"
        || (bus.is_some() && target != "ch" && target != "main" && target != "lr");
    let is_main = !is_bus && (target == "main" || target == "lr" || channel == 0);
    if is_bus {
        let b = bus.unwrap_or(channel).max(1);
        ("bus", -(b as i32), 0, Some(b))
    } else if is_main {
        ("main", 0, 0, None)
    } else {
        ("ch", channel as i32, channel, None)
    }
}

pub fn format_target_label(target: &str, channel: u8, bus: Option<u8>) -> String {
    let (norm_target, _, norm_ch, norm_bus) = classify_target(target, channel, bus);
    match norm_target {
        "bus" => format!("Bus {}", norm_bus.unwrap_or(1)),
        "main" => "Main LR".to_string(),
        _ => format!("Kênh {}", norm_ch),
    }
}

pub fn extract_suspect_suffix(reason: &str) -> Option<&str> {
    reason.find("(Nghi ngờ từ Mic").map(|idx| &reason[idx..])
}

pub fn format_target_label_with_reason(
    target: &str,
    channel: u8,
    bus: Option<u8>,
    reason: &str,
) -> String {
    let base = format_target_label(target, channel, bus);
    if let Some(suffix) = extract_suspect_suffix(reason) {
        format!("{} {}", base, suffix)
    } else {
        base
    }
}

impl Default for CapabilityMap {
    fn default() -> Self {
        Self {
            model: "Unknown".to_string(),
            firmware: "Unknown".to_string(),
            ip: "127.0.0.1".to_string(),
            port: 10024,
            num_channels: 18,
            num_busses: 6,
            channel_peq_bands: 4,
            bus_peq_bands: 6,
            lr_peq_bands: 6,
            lr_prefix: "/lr".to_string(),
            probe_completed: false,
        }
    }
}
