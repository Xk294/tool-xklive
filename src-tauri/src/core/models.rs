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

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PEQBand {
    pub channel: u8,
    pub band: u8,
    pub freq_hz: f32,
    pub gain_db: f32,
    pub q: f32,
    pub is_on: bool,
    pub filter_type: u8, // 2 = PEQ
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ActionProposal {
    pub channel: u8,
    pub freq_hz: f32,
    pub gain_db: f32,
    pub q: f32,
    pub bus: Option<u8>,
    pub band: Option<u8>,
    pub target: String, // "ch", "main", "bus", "lr"
    pub reason: String,
    pub original_gain_db: f32,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Decision {
    pub approved: bool,
    pub proposal: Option<ActionProposal>,
    pub effective_gain_db: f32,
    pub reason: String,
    pub is_probing: bool,
    pub transaction_id: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ActiveNotch {
    pub channel: u8,
    pub channel_name: Option<String>,
    pub band: u8,
    pub freq_hz: f32,
    pub current_gain_db: f32,
    pub target_gain_db: f32,
    pub q: f32,
    pub is_probing: bool,
    pub last_updated_time: f64,
    pub probe_step_count: u32,
    pub target: String,
    pub bus: Option<u8>,
    pub original_gain_db: f32,
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
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LogEntry {
    pub id: u64,
    pub time: String,
    pub text: String,
    #[serde(rename = "type")]
    pub entry_type: String, // "normal", "panic", "approved", "warning"
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
