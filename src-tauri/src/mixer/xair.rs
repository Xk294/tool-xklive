use std::collections::HashMap;
use std::net::{SocketAddr, UdpSocket};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use parking_lot::Mutex;
use rosc::{encoder, OscMessage, OscPacket, OscType};

use crate::core::models::{CapabilityMap, ConnectionState, PEQBand};
use crate::mixer::mapper::ParameterMapper;

#[derive(Debug, Clone)]
pub struct ExpectedEcho {
    pub expected_val: f32,
    pub expiry: Instant,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct DiscoveredMixer {
    pub ip: String,
    pub model: String,
    pub name: String,
    pub firmware: String,
}

pub fn discover_mixers(timeout_ms: u64, port: u16) -> Vec<DiscoveredMixer> {
    let mut discovered = Vec::new();
    let socket = match UdpSocket::bind("0.0.0.0:0") {
        Ok(s) => s,
        Err(_) => return discovered,
    };
    let _ = socket.set_broadcast(true);
    let _ = socket.set_read_timeout(Some(Duration::from_millis(80)));

    let broadcast_targets = [
        "255.255.255.255",
        "192.168.1.255",
        "192.168.0.255",
        "127.0.0.1",
    ];

    let msg = OscPacket::Message(OscMessage {
        addr: "/xinfo".to_string(),
        args: vec![],
    });
    if let Ok(buf) = encoder::encode(&msg) {
        for target in &broadcast_targets {
            if let Ok(addr) = format!("{}:{}", target, port).parse::<SocketAddr>() {
                let _ = socket.send_to(&buf, addr);
            }
        }
    }

    let deadline = Instant::now() + Duration::from_millis(timeout_ms);
    let mut buf = [0u8; 2048];
    let mut seen_ips = std::collections::HashSet::new();

    while Instant::now() < deadline {
        if let Ok((len, from_addr)) = socket.recv_from(&mut buf) {
            if let Ok((_, OscPacket::Message(msg))) = rosc::decoder::decode_udp(&buf[..len]) {
                if msg.addr == "/xinfo" {
                    let from_ip = from_addr.ip().to_string();
                    let ip = if let Some(OscType::String(s)) = msg.args.get(0) {
                        s.clone()
                    } else {
                        from_ip.clone()
                    };

                    if !seen_ips.contains(&ip) {
                        seen_ips.insert(ip.clone());
                        let model = if let Some(OscType::String(s)) = msg.args.get(1) {
                            s.clone()
                        } else {
                            "X-Air".to_string()
                        };
                        let name = if let Some(OscType::String(s)) = msg.args.get(2) {
                            s.clone()
                        } else {
                            "Mixer".to_string()
                        };
                        let firmware = if let Some(OscType::String(s)) = msg.args.get(3) {
                            s.clone()
                        } else {
                            "Unknown".to_string()
                        };

                        discovered.push(DiscoveredMixer {
                            ip,
                            model,
                            name,
                            firmware,
                        });
                    }
                }
            }
        }
    }

    discovered
}

pub struct XAirClient {
    pub ip: String,
    pub port: u16,
    pub mapper: ParameterMapper,

    state: Arc<Mutex<ConnectionState>>,
    running: Arc<AtomicBool>,
    socket: Arc<Mutex<Option<UdpSocket>>>,

    pub capability_map: Arc<Mutex<CapabilityMap>>,
    pub meter_levels: Arc<Mutex<Vec<f32>>>,
    pub rta_levels: Arc<Mutex<Vec<f32>>>,
    pub channel_names: Arc<Mutex<HashMap<u8, String>>>,
    pub channel_mutes: Arc<Mutex<HashMap<u8, bool>>>,
    pub channel_eq_on: Arc<Mutex<HashMap<u8, bool>>>,
    pub params_cache: Arc<Mutex<HashMap<String, f32>>>,
    expected_echoes: Arc<Mutex<HashMap<String, ExpectedEcho>>>,

    pub last_rtt_ms: Arc<Mutex<Option<f32>>>,
    pub on_manual_override: Arc<Mutex<Option<Box<dyn Fn(u8, &str, Option<u8>) + Send + Sync>>>>,
}

impl XAirClient {
    pub fn new(ip: String, port: u16) -> Self {
        Self {
            ip,
            port,
            mapper: ParameterMapper::default(),
            state: Arc::new(Mutex::new(ConnectionState::Disconnected)),
            running: Arc::new(AtomicBool::new(false)),
            socket: Arc::new(Mutex::new(None)),
            capability_map: Arc::new(Mutex::new(CapabilityMap::default())),
            meter_levels: Arc::new(Mutex::new(vec![0.0; 18])),
            rta_levels: Arc::new(Mutex::new(vec![-100.0; 100])),
            channel_names: Arc::new(Mutex::new(HashMap::new())),
            channel_mutes: Arc::new(Mutex::new(HashMap::new())),
            channel_eq_on: Arc::new(Mutex::new(HashMap::new())),
            params_cache: Arc::new(Mutex::new(HashMap::new())),
            expected_echoes: Arc::new(Mutex::new(HashMap::new())),
            last_rtt_ms: Arc::new(Mutex::new(None)),
            on_manual_override: Arc::new(Mutex::new(None)),
        }
    }

    pub fn get_state(&self) -> ConnectionState {
        *self.state.lock()
    }

    pub fn connect(&self) -> bool {
        *self.state.lock() = ConnectionState::Connecting;
        let socket = match UdpSocket::bind("0.0.0.0:0") {
            Ok(s) => s,
            Err(_) => {
                *self.state.lock() = ConnectionState::Disconnected;
                return false;
            }
        };
        let _ = socket.set_read_timeout(Some(Duration::from_millis(50)));
        let _ = socket.set_nonblocking(false);

        *self.socket.lock() = Some(socket.try_clone().unwrap());
        self.running.store(true, Ordering::SeqCst);

        // Spawn background worker thread for UDP I/O and heartbeats
        let running = Arc::clone(&self.running);
        let state = Arc::clone(&self.state);
        let sock_clone = socket.try_clone().unwrap();
        let target_addr: SocketAddr = match format!("{}:{}", self.ip, self.port).parse() {
            Ok(a) => a,
            Err(_) => {
                *self.state.lock() = ConnectionState::Disconnected;
                return false;
            }
        };

        let cap_map = Arc::clone(&self.capability_map);
        let meter_levels = Arc::clone(&self.meter_levels);
        let rta_levels = Arc::clone(&self.rta_levels);
        let ch_names = Arc::clone(&self.channel_names);
        let ch_mutes = Arc::clone(&self.channel_mutes);
        let ch_eq = Arc::clone(&self.channel_eq_on);
        let cache = Arc::clone(&self.params_cache);
        let echoes = Arc::clone(&self.expected_echoes);
        let last_rtt = Arc::clone(&self.last_rtt_ms);
        let on_override = Arc::clone(&self.on_manual_override);

        std::thread::spawn(move || {
            let mut last_heartbeat = Instant::now();
            let mut last_rx = Instant::now();
            let mut buf = [0u8; 4096];

            // Initial handshake
            let xinfo_msg = OscPacket::Message(OscMessage {
                addr: "/xinfo".to_string(),
                args: vec![],
            });
            if let Ok(b) = encoder::encode(&xinfo_msg) {
                let _ = sock_clone.send_to(&b, target_addr);
            }

            while running.load(Ordering::SeqCst) {
                // Read incoming packets
                if let Ok((len, _)) = sock_clone.recv_from(&mut buf) {
                    last_rx = Instant::now();
                    if let Ok((_, OscPacket::Message(msg))) = rosc::decoder::decode_udp(&buf[..len]) {
                        Self::handle_incoming(
                            &msg,
                            &state,
                            &cap_map,
                            &meter_levels,
                            &rta_levels,
                            &ch_names,
                            &ch_mutes,
                            &ch_eq,
                            &cache,
                            &echoes,
                            &last_rtt,
                            &on_override,
                        );
                    }
                }

                // Heartbeat & renewals
                let current_state = *state.lock();
                if current_state == ConnectionState::Connected {
                    if last_heartbeat.elapsed() >= Duration::from_secs(8) {
                        let remote_msg = OscPacket::Message(OscMessage {
                            addr: "/xremote".to_string(),
                            args: vec![],
                        });
                        if let Ok(b) = encoder::encode(&remote_msg) {
                            let _ = sock_clone.send_to(&b, target_addr);
                        }
                        // Renew meters & RTA subscriptions
                        let m1_msg = OscPacket::Message(OscMessage {
                            addr: "/meters".to_string(),
                            args: vec![OscType::String("/meters/1".to_string())],
                        });
                        if let Ok(b) = encoder::encode(&m1_msg) {
                            let _ = sock_clone.send_to(&b, target_addr);
                        }
                        let m4_msg = OscPacket::Message(OscMessage {
                            addr: "/meters".to_string(),
                            args: vec![OscType::String("/meters/4".to_string())],
                        });
                        if let Ok(b) = encoder::encode(&m4_msg) {
                            let _ = sock_clone.send_to(&b, target_addr);
                        }
                        last_heartbeat = Instant::now();
                    }

                    // Check timeout (15s)
                    if last_rx.elapsed() >= Duration::from_secs(15) {
                        *state.lock() = ConnectionState::Reconnecting;
                    }
                } else if current_state == ConnectionState::Reconnecting {
                    if last_heartbeat.elapsed() >= Duration::from_secs(1) {
                        let xinfo_msg = OscPacket::Message(OscMessage {
                            addr: "/xinfo".to_string(),
                            args: vec![],
                        });
                        if let Ok(b) = encoder::encode(&xinfo_msg) {
                            let _ = sock_clone.send_to(&b, target_addr);
                        }
                        last_heartbeat = Instant::now();
                    }
                }
            }
        });

        // Wait up to 500ms for connection handshake
        let deadline = Instant::now() + Duration::from_millis(500);
        while Instant::now() < deadline {
            if *self.state.lock() == ConnectionState::Connected {
                return true;
            }
            std::thread::sleep(Duration::from_millis(20));
        }

        // Even if handshake didn't return immediately, set state to Reconnecting (it will auto-recover)
        if *self.state.lock() == ConnectionState::Connecting {
            *self.state.lock() = ConnectionState::Reconnecting;
        }
        false
    }

    pub fn disconnect(&self) {
        self.running.store(false, Ordering::SeqCst);
        *self.state.lock() = ConnectionState::Disconnected;
        *self.socket.lock() = None;
    }

    fn handle_incoming(
        msg: &OscMessage,
        state: &Arc<Mutex<ConnectionState>>,
        cap_map: &Arc<Mutex<CapabilityMap>>,
        meter_levels: &Arc<Mutex<Vec<f32>>>,
        rta_levels: &Arc<Mutex<Vec<f32>>>,
        ch_names: &Arc<Mutex<HashMap<u8, String>>>,
        ch_mutes: &Arc<Mutex<HashMap<u8, bool>>>,
        ch_eq: &Arc<Mutex<HashMap<u8, bool>>>,
        cache: &Arc<Mutex<HashMap<String, f32>>>,
        echoes: &Arc<Mutex<HashMap<String, ExpectedEcho>>>,
        last_rtt: &Arc<Mutex<Option<f32>>>,
        on_override: &Arc<Mutex<Option<Box<dyn Fn(u8, &str, Option<u8>) + Send + Sync>>>>,
    ) {
        let addr = &msg.addr;

        if addr == "/xinfo" {
            let mut st = state.lock();
            if *st == ConnectionState::Connecting || *st == ConnectionState::Reconnecting {
                *st = ConnectionState::Connected;
            }
            if msg.args.len() >= 4 {
                let mut cm = cap_map.lock();
                if let (
                    Some(OscType::String(ip)),
                    Some(OscType::String(model)),
                    Some(OscType::String(_name)),
                    Some(OscType::String(fw)),
                ) = (
                    msg.args.get(0),
                    msg.args.get(1),
                    msg.args.get(2),
                    msg.args.get(3),
                ) {
                    cm.ip = ip.clone();
                    cm.model = model.clone();
                    cm.firmware = fw.clone();
                    cm.probe_completed = true;
                }
            }
            *last_rtt.lock() = Some(5.0); // nominal ping response
            return;
        }

        // Decode RTA 100-band (/meters/4)
        if addr == "/meters/4" {
            if let Some(OscType::Blob(blob)) = msg.args.get(0) {
                let offset = if blob.len() >= 204 { 4 } else { 0 };
                if blob.len() >= offset + 200 {
                    let mut rta = Vec::with_capacity(100);
                    for i in 0..100 {
                        let idx = offset + i * 2;
                        let s = i16::from_le_bytes([blob[idx], blob[idx + 1]]);
                        rta.push(s as f32 / 256.0);
                    }
                    *rta_levels.lock() = rta;
                }
            }
            return;
        }

        // Decode Channels 1-18 meters (/meters/1)
        if addr == "/meters/1" {
            if let Some(OscType::Blob(blob)) = msg.args.get(0) {
                if blob.len() >= 72 {
                    let mut meters = Vec::with_capacity(18);
                    for i in 0..18 {
                        let idx = i * 4;
                        let f = f32::from_le_bytes([blob[idx], blob[idx + 1], blob[idx + 2], blob[idx + 3]]);
                        meters.push(f);
                    }
                    *meter_levels.lock() = meters;
                }
            }
            return;
        }

        // Channel config and manual override tracking
        if addr.starts_with("/ch/") && addr.ends_with("/config/name") {
            if let Some(OscType::String(name)) = msg.args.get(0) {
                let parts: Vec<&str> = addr.split('/').collect();
                if parts.len() >= 3 {
                    if let Ok(ch) = parts[2].parse::<u8>() {
                        ch_names.lock().insert(ch, name.clone());
                    }
                }
            }
        } else if addr.starts_with("/ch/") && addr.ends_with("/mix/on") {
            if let Some(OscType::Int(val)) = msg.args.get(0) {
                let parts: Vec<&str> = addr.split('/').collect();
                if parts.len() >= 3 {
                    if let Ok(ch) = parts[2].parse::<u8>() {
                        ch_mutes.lock().insert(ch, *val == 0);
                    }
                }
            }
        } else if addr.starts_with("/ch/") && addr.ends_with("/eq/on") {
            if let Some(OscType::Int(val)) = msg.args.get(0) {
                let parts: Vec<&str> = addr.split('/').collect();
                if parts.len() >= 3 {
                    if let Ok(ch) = parts[2].parse::<u8>() {
                        ch_eq.lock().insert(ch, *val != 0);
                    }
                }
            }
        }

        // Check expected echo for manual override detection
        if let Some(OscType::Float(f)) = msg.args.get(0) {
            cache.lock().insert(addr.clone(), *f);

            let mut echoes_guard = echoes.lock();
            let is_expected = if let Some(echo) = echoes_guard.get(addr) {
                if Instant::now() <= echo.expiry && (echo.expected_val - *f).abs() < 0.05 {
                    true
                } else {
                    false
                }
            } else {
                false
            };

            if is_expected {
                echoes_guard.remove(addr);
            } else if addr.contains("/eq/") {
                // Manual override from soundman!
                let parts: Vec<&str> = addr.split('/').collect();
                if parts.len() >= 3 {
                    if parts[1] == "ch" {
                        if let Ok(ch) = parts[2].parse::<u8>() {
                            if let Some(cb) = &*on_override.lock() {
                                cb(ch, "ch", None);
                            }
                        }
                    } else if parts[1] == "bus" {
                        if let Ok(bus) = parts[2].parse::<u8>() {
                            if let Some(cb) = &*on_override.lock() {
                                cb(0, "bus", Some(bus));
                            }
                        }
                    }
                }
            }
        }
    }

    pub fn set_peq(&self, band: &PEQBand) -> bool {
        let sock_guard = self.socket.lock();
        let sock = match &*sock_guard {
            Some(s) => s,
            None => return false,
        };
        let target_addr: SocketAddr = match format!("{}:{}", self.ip, self.port).parse() {
            Ok(a) => a,
            Err(_) => return false,
        };

        let norm_f = self.mapper.freq.to_float(band.freq_hz);
        let norm_g = self.mapper.gain.to_float(band.gain_db);
        let norm_q = self.mapper.q.to_float(band.q);

        let ch = band.channel;
        let b = band.band;

        // Register expected echo for gain
        let gain_addr = format!("/ch/{:02}/eq/{}/g", ch, b);
        self.expected_echoes.lock().insert(
            gain_addr.clone(),
            ExpectedEcho {
                expected_val: norm_g,
                expiry: Instant::now() + Duration::from_millis(500),
            },
        );

        // 1. Enforce EQ ON (/ch/../eq/on = 1)
        let eq_on_msg = OscPacket::Message(OscMessage {
            addr: format!("/ch/{:02}/eq/on", ch),
            args: vec![OscType::Int(1)],
        });
        if let Ok(buf) = encoder::encode(&eq_on_msg) {
            let _ = sock.send_to(&buf, target_addr);
        }

        // 2. Enforce Filter Type PEQ (/ch/../eq/../type = 2)
        let type_msg = OscPacket::Message(OscMessage {
            addr: format!("/ch/{:02}/eq/{}/type", ch, b),
            args: vec![OscType::Int(2)],
        });
        if let Ok(buf) = encoder::encode(&type_msg) {
            let _ = sock.send_to(&buf, target_addr);
        }

        // 3. Set Frequency
        let f_msg = OscPacket::Message(OscMessage {
            addr: format!("/ch/{:02}/eq/{}/f", ch, b),
            args: vec![OscType::Float(norm_f)],
        });
        if let Ok(buf) = encoder::encode(&f_msg) {
            let _ = sock.send_to(&buf, target_addr);
        }

        // 4. Set Q
        let q_msg = OscPacket::Message(OscMessage {
            addr: format!("/ch/{:02}/eq/{}/q", ch, b),
            args: vec![OscType::Float(norm_q)],
        });
        if let Ok(buf) = encoder::encode(&q_msg) {
            let _ = sock.send_to(&buf, target_addr);
        }

        // 5. Set Gain
        let g_msg = OscPacket::Message(OscMessage {
            addr: gain_addr,
            args: vec![OscType::Float(norm_g)],
        });
        if let Ok(buf) = encoder::encode(&g_msg) {
            let _ = sock.send_to(&buf, target_addr);
        }

        true
    }
}
