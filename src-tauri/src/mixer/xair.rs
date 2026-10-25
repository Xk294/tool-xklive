use std::collections::HashMap;
use std::net::{SocketAddr, UdpSocket};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use parking_lot::Mutex;
use rosc::{encoder, OscMessage, OscPacket, OscType};

use crate::core::models::{CapabilityMap, ConnectionState, PEQBand};
use crate::mixer::mapper::ParameterMapper;

/// X-Air EQ band type index for a fully parametric band (GEMINI.md: Direct PEQ Enforcement).
const PEQ_FILTER_TYPE: i32 = 2;

type ManualOverrideCallback = Arc<Mutex<Option<Box<dyn Fn(u8, &str, Option<u8>) + Send + Sync>>>>;

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

pub fn decode_meters_1(blob: &[u8], out: &mut Vec<f32>) {
    if blob.len() >= 72 {
        if out.len() != 18 {
            out.resize(18, 0.0);
        }
        for i in 0..18 {
            let idx = i * 4;
            let f = f32::from_le_bytes([blob[idx], blob[idx + 1], blob[idx + 2], blob[idx + 3]]);
            out[i] = f;
        }
    }
}

pub fn decode_meters_4(blob: &[u8], out: &mut Vec<f32>) {
    let offset = if blob.len() >= 204 { 4 } else { 0 };
    if blob.len() >= offset + 200 {
        if out.len() != 100 {
            out.resize(100, -100.0);
        }
        for i in 0..100 {
            let idx = offset + i * 2;
            let s = i16::from_le_bytes([blob[idx], blob[idx + 1]]);
            out[i] = s as f32 / 256.0;
        }
    }
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
    pub meter_levels_updated_at: Arc<Mutex<Option<Instant>>>,
    pub rta_levels: Arc<Mutex<Vec<f32>>>,
    pub channel_names: Arc<Mutex<HashMap<u8, String>>>,
    pub channel_mutes: Arc<Mutex<HashMap<u8, bool>>>,
    pub channel_hpf_on: Arc<Mutex<HashMap<u8, bool>>>,
    pub params_cache: Arc<Mutex<HashMap<String, f32>>>,
    expected_echoes: Arc<Mutex<HashMap<String, ExpectedEcho>>>,

    pub last_rtt_ms: Arc<Mutex<Option<f32>>>,
    pub on_manual_override: ManualOverrideCallback,
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
            meter_levels_updated_at: Arc::new(Mutex::new(None)),
            rta_levels: Arc::new(Mutex::new(vec![-100.0; 100])),
            channel_names: Arc::new(Mutex::new(HashMap::new())),
            channel_mutes: Arc::new(Mutex::new(HashMap::new())),
            channel_hpf_on: Arc::new(Mutex::new(HashMap::new())),
            params_cache: Arc::new(Mutex::new(HashMap::new())),
            expected_echoes: Arc::new(Mutex::new(HashMap::new())),
            last_rtt_ms: Arc::new(Mutex::new(None)),
            on_manual_override: Arc::new(Mutex::new(None)),
        }
    }

    pub fn get_state(&self) -> ConnectionState {
        *self.state.lock()
    }

    fn send_xremote(sock: &UdpSocket, target: SocketAddr) {
        let remote_msg = OscPacket::Message(OscMessage {
            addr: "/xremote".to_string(),
            args: vec![],
        });
        if let Ok(b) = encoder::encode(&remote_msg) {
            let _ = sock.send_to(&b, target);
        }
    }

    fn send_meters(sock: &UdpSocket, target: SocketAddr) {
        let m1_msg = OscPacket::Message(OscMessage {
            addr: "/meters".to_string(),
            args: vec![OscType::String("/meters/1".to_string())],
        });
        if let Ok(b) = encoder::encode(&m1_msg) {
            let _ = sock.send_to(&b, target);
        }
        let m4_msg = OscPacket::Message(OscMessage {
            addr: "/meters".to_string(),
            args: vec![OscType::String("/meters/4".to_string())],
        });
        if let Ok(b) = encoder::encode(&m4_msg) {
            let _ = sock.send_to(&b, target);
        }
    }

    fn send_empty_query(sock: &UdpSocket, target: SocketAddr, addr: String) {
        let q = OscPacket::Message(OscMessage { addr, args: vec![] });
        if let Ok(b) = encoder::encode(&q) {
            let _ = sock.send_to(&b, target);
        }
    }

    fn query_channel_configs(sock: &UdpSocket, target: SocketAddr, running: &Arc<AtomicBool>) {
        let mut addrs = Vec::with_capacity(340);
        addrs.push("/headamp/00/gain".to_string());
        for ch in 1..=16 {
            addrs.push(format!("/ch/{:02}/config/name", ch));
            addrs.push(format!("/ch/{:02}/mix/on", ch));
            addrs.push(format!("/ch/{:02}/mix/fader", ch));
            addrs.push(format!("/headamp/{:02}/gain", ch));
            addrs.push(format!("/ch/{:02}/preamp/trim", ch));
            addrs.push(format!("/ch/{:02}/preamp/hpon", ch));
            addrs.push(format!("/ch/{:02}/preamp/hpf", ch));
            for bus in 1..=6 {
                addrs.push(format!("/ch/{:02}/mix/{:02}/level", ch, bus));
            }
            for band in 3..=4 {
                addrs.push(format!("/ch/{:02}/eq/{}/g", ch, band));
                addrs.push(format!("/ch/{:02}/eq/{}/f", ch, band));
                addrs.push(format!("/ch/{:02}/eq/{}/q", ch, band));
            }
        }
        addrs.push("/lr/mix/fader".to_string());
        for band in 3..=6 {
            addrs.push(format!("/lr/eq/{}/g", band));
            addrs.push(format!("/lr/eq/{}/f", band));
            addrs.push(format!("/lr/eq/{}/q", band));
        }
        for bus in 1..=6 {
            addrs.push(format!("/bus/{:02}/mix/on", bus));
            addrs.push(format!("/bus/{:02}/mix/fader", bus));
            for band in 5..=6 {
                addrs.push(format!("/bus/{:02}/eq/{}/g", bus, band));
                addrs.push(format!("/bus/{:02}/eq/{}/f", bus, band));
                addrs.push(format!("/bus/{:02}/eq/{}/q", bus, band));
            }
        }
        for fx in 1..=4 {
            addrs.push(format!("/fxrtn/{:02}/mix/fader", fx));
        }

        if let Ok(query_sock) = sock.try_clone() {
            let running_flag = Arc::clone(running);
            std::thread::spawn(move || {
                for chunk in addrs.chunks(24) {
                    if !running_flag.load(Ordering::SeqCst) {
                        break;
                    }
                    for addr in chunk {
                        Self::send_empty_query(&query_sock, target, addr.clone());
                    }
                    std::thread::sleep(Duration::from_millis(2));
                }
            });
        } else {
            for addr in addrs {
                Self::send_empty_query(sock, target, addr);
            }
        }
    }

    fn send_subscriptions(sock: &UdpSocket, target: SocketAddr) {
        Self::send_xremote(sock, target);
        Self::send_meters(sock, target);
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

        let sock_for_state = match socket.try_clone() {
            Ok(s) => s,
            Err(e) => {
                log::error!("Failed to clone UDP socket: {}", e);
                *self.state.lock() = ConnectionState::Disconnected;
                return false;
            }
        };
        let sock_clone = match socket.try_clone() {
            Ok(s) => s,
            Err(e) => {
                log::error!("Failed to clone worker socket: {}", e);
                *self.state.lock() = ConnectionState::Disconnected;
                return false;
            }
        };

        *self.socket.lock() = Some(sock_for_state);
        self.running.store(true, Ordering::SeqCst);

        let running = Arc::clone(&self.running);
        let state = Arc::clone(&self.state);
        let target_addr: SocketAddr = match format!("{}:{}", self.ip, self.port).parse() {
            Ok(a) => a,
            Err(_) => {
                *self.state.lock() = ConnectionState::Disconnected;
                return false;
            }
        };

        let cap_map = Arc::clone(&self.capability_map);
        let meter_levels = Arc::clone(&self.meter_levels);
        let meter_levels_updated_at = Arc::clone(&self.meter_levels_updated_at);
        let rta_levels = Arc::clone(&self.rta_levels);
        let ch_names = Arc::clone(&self.channel_names);
        let ch_mutes = Arc::clone(&self.channel_mutes);
        let ch_hpf = Arc::clone(&self.channel_hpf_on);
        let cache = Arc::clone(&self.params_cache);
        let echoes = Arc::clone(&self.expected_echoes);
        let last_rtt = Arc::clone(&self.last_rtt_ms);
        let on_override = Arc::clone(&self.on_manual_override);

        std::thread::spawn(move || {
            let mut last_heartbeat = Instant::now() - Duration::from_secs(10);
            let mut last_meters_req = Instant::now() - Duration::from_secs(10);
            let mut last_ping_req = Instant::now();
            let mut last_rx = Instant::now();
            let last_xinfo_sent = Arc::new(Mutex::new(Instant::now()));
            let mut buf = [0u8; 4096];

            let xinfo_msg = OscPacket::Message(OscMessage {
                addr: "/xinfo".to_string(),
                args: vec![],
            });
            if let Ok(b) = encoder::encode(&xinfo_msg) {
                *last_xinfo_sent.lock() = Instant::now();
                let _ = sock_clone.send_to(&b, target_addr);
            }

            while running.load(Ordering::SeqCst) {
                if let Ok((len, _)) = sock_clone.recv_from(&mut buf) {
                    last_rx = Instant::now();
                    if let Ok((_, OscPacket::Message(msg))) = rosc::decoder::decode_udp(&buf[..len]) {
                        Self::handle_incoming(
                            &msg,
                            &running,
                            &state,
                            &cap_map,
                            &meter_levels,
                            &meter_levels_updated_at,
                            &rta_levels,
                            &ch_names,
                            &ch_mutes,
                            &ch_hpf,
                            &cache,
                            &echoes,
                            &last_rtt,
                            &last_xinfo_sent,
                            &sock_clone,
                            target_addr,
                            &on_override,
                        );
                    }
                }

                let current_state = *state.lock();
                if current_state == ConnectionState::Connected {
                    if last_heartbeat.elapsed() >= Duration::from_secs(7) {
                        Self::send_xremote(&sock_clone, target_addr);
                        last_heartbeat = Instant::now();
                    }

                    if last_meters_req.elapsed() >= Duration::from_millis(500) {
                        Self::send_meters(&sock_clone, target_addr);
                        last_meters_req = Instant::now();
                    }

                    if last_ping_req.elapsed() >= Duration::from_secs(2) {
                        let ping_msg = OscPacket::Message(OscMessage {
                            addr: "/xinfo".to_string(),
                            args: vec![],
                        });
                        if let Ok(b) = encoder::encode(&ping_msg) {
                            *last_xinfo_sent.lock() = Instant::now();
                            let _ = sock_clone.send_to(&b, target_addr);
                        }
                        last_ping_req = Instant::now();
                    }

                    if last_rx.elapsed() >= Duration::from_secs(3) {
                        *state.lock() = ConnectionState::Reconnecting;
                    }
                } else if current_state == ConnectionState::Reconnecting {
                    if last_heartbeat.elapsed() >= Duration::from_secs(1) {
                        let xinfo_msg = OscPacket::Message(OscMessage {
                            addr: "/xinfo".to_string(),
                            args: vec![],
                        });
                        if let Ok(b) = encoder::encode(&xinfo_msg) {
                            *last_xinfo_sent.lock() = Instant::now();
                            let _ = sock_clone.send_to(&b, target_addr);
                        }
                        last_heartbeat = Instant::now();
                    }
                }
            }
        });

        let deadline = Instant::now() + Duration::from_millis(500);
        while Instant::now() < deadline {
            if *self.state.lock() == ConnectionState::Connected {
                return true;
            }
            std::thread::sleep(Duration::from_millis(20));
        }

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

    fn notify_eq_manual_override(addr: &str, on_override: &ManualOverrideCallback) {
        let parts: Vec<&str> = addr.split('/').collect();
        if parts.len() < 3 {
            return;
        }
        match parts[1] {
            "ch" => {
                if let Ok(ch) = parts[2].parse::<u8>() {
                    if let Some(cb) = &*on_override.lock() {
                        cb(ch, "ch", None);
                    }
                }
            }
            "bus" => {
                if let Ok(bus) = parts[2].parse::<u8>() {
                    if let Some(cb) = &*on_override.lock() {
                        cb(0, "bus", Some(bus));
                    }
                }
            }
            "lr" | "main" => {
                if let Some(cb) = &*on_override.lock() {
                    cb(0, "main", None);
                }
            }
            _ => {}
        }
    }

    fn handle_incoming(
        msg: &OscMessage,
        running: &Arc<AtomicBool>,
        state: &Arc<Mutex<ConnectionState>>,
        cap_map: &Arc<Mutex<CapabilityMap>>,
        meter_levels: &Arc<Mutex<Vec<f32>>>,
        meter_levels_updated_at: &Arc<Mutex<Option<Instant>>>,
        rta_levels: &Arc<Mutex<Vec<f32>>>,
        ch_names: &Arc<Mutex<HashMap<u8, String>>>,
        ch_mutes: &Arc<Mutex<HashMap<u8, bool>>>,
        ch_hpf: &Arc<Mutex<HashMap<u8, bool>>>,
        cache: &Arc<Mutex<HashMap<String, f32>>>,
        echoes: &Arc<Mutex<HashMap<String, ExpectedEcho>>>,
        last_rtt: &Arc<Mutex<Option<f32>>>,
        last_xinfo_sent: &Arc<Mutex<Instant>>,
        sock: &UdpSocket,
        target_addr: SocketAddr,
        on_override: &ManualOverrideCallback,
    ) {
        let addr = &msg.addr;

        if addr == "/xinfo" {
            let was_reconnecting = {
                let mut st = state.lock();
                let need_transition = *st == ConnectionState::Connecting || *st == ConnectionState::Reconnecting;
                if need_transition {
                    *st = ConnectionState::Connected;
                }
                need_transition
            };

            let ping_duration = last_xinfo_sent.lock().elapsed().as_secs_f32() * 1000.0;
            *last_rtt.lock() = Some(ping_duration.max(0.5));

            if was_reconnecting {
                Self::send_subscriptions(sock, target_addr);
                Self::query_channel_configs(sock, target_addr, running);
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
                    cm.num_channels = CapabilityMap::channel_count_for_model(model);
                    cm.probe_completed = true;
                }
            }
            return;
        }

        if addr == "/meters/4" {
            if let Some(OscType::Blob(blob)) = msg.args.get(0) {
                let mut rta = rta_levels.lock();
                decode_meters_4(blob, &mut rta);
            }
            return;
        }

        if addr == "/meters/1" {
            if let Some(OscType::Blob(blob)) = msg.args.get(0) {
                let mut meters = meter_levels.lock();
                decode_meters_1(blob, &mut meters);
                *meter_levels_updated_at.lock() = Some(Instant::now());
            }
            return;
        }

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
                        cache.lock().insert(addr.clone(), if *val != 0 { 1.0 } else { 0.0 });
                    }
                }
            }
        } else if addr.starts_with("/bus/") && addr.ends_with("/mix/on") {
            if let Some(OscType::Int(val)) = msg.args.get(0) {
                cache.lock().insert(addr.clone(), if *val != 0 { 1.0 } else { 0.0 });
            }
        } else if addr.contains("/eq/") && (addr.ends_with("/on") || addr.ends_with("/type")) {
            if let Some(OscType::Int(val)) = msg.args.get(0) {
                let mut echoes_guard = echoes.lock();
                let now_inst = Instant::now();
                echoes_guard.retain(|_, v| now_inst <= v.expiry);
                let expected_f = *val as f32;
                let is_expected = echoes_guard
                    .get(addr)
                    .map_or(false, |e| (e.expected_val - expected_f).abs() < 0.05);
                if is_expected {
                    echoes_guard.remove(addr);
                } else {
                    drop(echoes_guard);
                    Self::notify_eq_manual_override(addr, on_override);
                }
            }
        } else if addr.starts_with("/ch/") && addr.ends_with("/preamp/hpon") {
            if let Some(OscType::Int(val)) = msg.args.get(0) {
                let parts: Vec<&str> = addr.split('/').collect();
                if parts.len() >= 3 {
                    if let Ok(ch) = parts[2].parse::<u8>() {
                        ch_hpf.lock().insert(ch, *val != 0);
                    }
                }
            }
        }

        if let Some(OscType::Float(f)) = msg.args.get(0) {
            cache.lock().insert(addr.clone(), *f);

            let mut echoes_guard = echoes.lock();
            let now_inst = Instant::now();
            echoes_guard.retain(|_, v| now_inst <= v.expiry);

            let is_expected = if let Some(echo) = echoes_guard.get(addr) {
                (echo.expected_val - *f).abs() < 0.05
            } else {
                false
            };

            if is_expected {
                echoes_guard.remove(addr);
            } else if addr.contains("/eq/") {
                drop(echoes_guard);
                Self::notify_eq_manual_override(addr, on_override);
            } else if addr.starts_with("/fxrtn/") && addr.ends_with("/mix/fader") {
                drop(echoes_guard);
                let parts: Vec<&str> = addr.split('/').collect();
                if parts.len() >= 3 {
                    if let Ok(fx) = parts[2].parse::<u8>() {
                        if let Some(cb) = &*on_override.lock() {
                            cb(0, "fxrtn", Some(fx));
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

        let lr_prefix = self.capability_map.lock().lr_prefix.clone();
        let prefix = ParameterMapper::target_prefix(&band.target, band.channel, band.bus, &lr_prefix);

        let b = band.band;
        let eq_on_addr = format!("{}/eq/on", prefix);
        let type_addr = format!("{}/eq/{}/type", prefix, b);
        let f_addr = format!("{}/eq/{}/f", prefix, b);
        let q_addr = format!("{}/eq/{}/q", prefix, b);
        let gain_addr = format!("{}/eq/{}/g", prefix, b);

        let expiry = Instant::now() + Duration::from_millis(500);
        {
            let mut echoes = self.expected_echoes.lock();
            echoes.insert(eq_on_addr.clone(), ExpectedEcho { expected_val: 1.0, expiry });
            echoes.insert(type_addr.clone(), ExpectedEcho { expected_val: PEQ_FILTER_TYPE as f32, expiry });
            echoes.insert(f_addr.clone(), ExpectedEcho { expected_val: norm_f, expiry });
            echoes.insert(q_addr.clone(), ExpectedEcho { expected_val: norm_q, expiry });
            echoes.insert(gain_addr.clone(), ExpectedEcho { expected_val: norm_g, expiry });
        }

        let eq_on_msg = OscPacket::Message(OscMessage {
            addr: eq_on_addr,
            args: vec![OscType::Int(1)],
        });
        if let Ok(buf) = encoder::encode(&eq_on_msg) {
            let _ = sock.send_to(&buf, target_addr);
        }

        let type_msg = OscPacket::Message(OscMessage {
            addr: type_addr,
            args: vec![OscType::Int(PEQ_FILTER_TYPE)],
        });
        if let Ok(buf) = encoder::encode(&type_msg) {
            let _ = sock.send_to(&buf, target_addr);
        }

        let f_msg = OscPacket::Message(OscMessage {
            addr: f_addr,
            args: vec![OscType::Float(norm_f)],
        });
        if let Ok(buf) = encoder::encode(&f_msg) {
            let _ = sock.send_to(&buf, target_addr);
        }

        let q_msg = OscPacket::Message(OscMessage {
            addr: q_addr,
            args: vec![OscType::Float(norm_q)],
        });
        if let Ok(buf) = encoder::encode(&q_msg) {
            let _ = sock.send_to(&buf, target_addr);
        }

        let g_msg = OscPacket::Message(OscMessage {
            addr: gain_addr,
            args: vec![OscType::Float(norm_g)],
        });
        if let Ok(buf) = encoder::encode(&g_msg) {
            let _ = sock.send_to(&buf, target_addr);
        }

        true
    }

    pub fn send_fader(&self, addr: &str, fader_val: f32) -> bool {
        self.send_osc_float(addr, fader_val.clamp(0.0, 1.0))
    }

    pub fn set_channel_hpf(&self, channel: u8, enabled: bool, freq_hz: f32) -> bool {
        self.channel_hpf_on.lock().insert(channel, enabled);
        let sock_guard = self.socket.lock();
        let sock = match &*sock_guard {
            Some(s) => s,
            None => return false,
        };
        let target_addr: SocketAddr = match format!("{}:{}", self.ip, self.port).parse() {
            Ok(a) => a,
            Err(_) => return false,
        };

        let hpon_addr = format!("/ch/{:02}/preamp/hpon", channel);
        let hpf_addr = format!("/ch/{:02}/preamp/hpf", channel);
        let norm_hpf = self.mapper.hpf.to_float(freq_hz);
        let expiry = Instant::now() + Duration::from_millis(500);

        {
            let mut echoes = self.expected_echoes.lock();
            echoes.insert(
                hpon_addr.clone(),
                ExpectedEcho {
                    expected_val: if enabled { 1.0 } else { 0.0 },
                    expiry,
                },
            );
            echoes.insert(
                hpf_addr.clone(),
                ExpectedEcho {
                    expected_val: norm_hpf,
                    expiry,
                },
            );
        }

        let on_msg = OscPacket::Message(OscMessage {
            addr: hpon_addr,
            args: vec![OscType::Int(if enabled { 1 } else { 0 })],
        });
        if let Ok(buf) = encoder::encode(&on_msg) {
            let _ = sock.send_to(&buf, target_addr);
        }

        let freq_msg = OscPacket::Message(OscMessage {
            addr: hpf_addr,
            args: vec![OscType::Float(norm_hpf)],
        });
        if let Ok(buf) = encoder::encode(&freq_msg) {
            let _ = sock.send_to(&buf, target_addr);
        }

        true
    }

    pub fn send_osc_float(&self, addr: &str, val: f32) -> bool {
        let sock_guard = self.socket.lock();
        let sock = match &*sock_guard {
            Some(s) => s,
            None => return false,
        };
        let target_addr: SocketAddr = match format!("{}:{}", self.ip, self.port).parse() {
            Ok(a) => a,
            Err(_) => return false,
        };

        self.expected_echoes.lock().insert(
            addr.to_string(),
            ExpectedEcho {
                expected_val: val,
                expiry: Instant::now() + Duration::from_millis(500),
            },
        );

        let msg = OscPacket::Message(OscMessage {
            addr: addr.to_string(),
            args: vec![OscType::Float(val)],
        });
        if let Ok(buf) = encoder::encode(&msg) {
            let _ = sock.send_to(&buf, target_addr);
            true
        } else {
            false
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_decode_meters_1_blob() {
        let mut blob = Vec::with_capacity(72);
        for i in 0..18 {
            let val = (i as f32) * 0.05;
            blob.extend_from_slice(&val.to_le_bytes());
        }
        let mut out = Vec::new();
        decode_meters_1(&blob, &mut out);
        assert_eq!(out.len(), 18);
        assert!((out[2] - 0.10).abs() < 1e-5);
    }

    #[test]
    fn test_decode_meters_4_blob() {
        let mut blob = vec![0u8; 4];
        for i in 0..100 {
            let val_i16: i16 = (-50 * 256) + (i as i16 * 128);
            blob.extend_from_slice(&val_i16.to_le_bytes());
        }
        let mut out = Vec::new();
        decode_meters_4(&blob, &mut out);
        assert_eq!(out.len(), 100);
        assert!((out[0] - (-50.0)).abs() < 1e-3);
    }
}
