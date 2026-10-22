use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{Stream, StreamConfig};
use rtrb::RingBuffer;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

pub struct AudioEngine {
    stream: Option<Stream>,
    running: Arc<AtomicBool>,
}

unsafe impl Send for AudioEngine {}
unsafe impl Sync for AudioEngine {}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct AudioDeviceItem {
    pub name: String,
    pub is_default: bool,
}

impl AudioEngine {
    pub fn new() -> Self {
        Self {
            stream: None,
            running: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn list_input_devices() -> Vec<AudioDeviceItem> {
        let mut result = Vec::new();
        let host = cpal::default_host();
        let default_device_name = host.default_input_device().and_then(|d| d.name().ok());

        if let Ok(devices) = host.input_devices() {
            for device in devices {
                if let Ok(name) = device.name() {
                    let is_default = default_device_name.as_ref().map_or(false, |def| *def == name);
                    result.push(AudioDeviceItem { name, is_default });
                }
            }
        }
        result
    }

    pub fn start<F>(
        &mut self,
        device_name: Option<&str>,
        sample_rate: u32,
        channels: u16,
        mut on_samples_chunk: F,
    ) -> Result<(), String>
    where
        F: FnMut(&[f32]) + Send + 'static,
    {
        let host = cpal::default_host();
        let device = match device_name {
            Some(name) => host
                .input_devices()
                .map_err(|e| e.to_string())?
                .find(|d| d.name().map_or(false, |n| n == name))
                .ok_or_else(|| format!("Thiết bị âm thanh '{}' không tồn tại", name))?,
            None => host
                .default_input_device()
                .ok_or_else(|| "Không tìm thấy thiết bị thu âm thanh mặc định".to_string())?,
        };

        let config = StreamConfig {
            channels,
            sample_rate: cpal::SampleRate(sample_rate),
            buffer_size: cpal::BufferSize::Default,
        };

        // Create zero-allocation real-time Ring Buffer (capacity: 32768 samples)
        let (mut producer, mut consumer) = RingBuffer::<f32>::new(32768);

        self.running.store(true, Ordering::SeqCst);
        let running_clone = Arc::clone(&self.running);

        // DSP Worker Thread reading from Consumer
        std::thread::spawn(move || {
            let mut chunk = vec![0.0f32; 2048];
            while running_clone.load(Ordering::SeqCst) {
                if consumer.slots() >= 2048 {
                    for i in 0..2048 {
                        if let Ok(sample) = consumer.pop() {
                            chunk[i] = sample;
                        }
                    }
                    on_samples_chunk(&chunk);
                } else {
                    std::thread::sleep(std::time::Duration::from_millis(5));
                }
            }
        });

        // Audio Input Callback - STRICT ZERO ALLOCATION
        let stream = device
            .build_input_stream(
                &config,
                move |data: &[f32], _: &_| {
                    for &sample in data {
                        let _ = producer.push(sample);
                    }
                },
                |err| {
                    eprintln!("Lỗi stream âm thanh: {}", err);
                },
                None,
            )
            .map_err(|e| e.to_string())?;

        stream.play().map_err(|e| e.to_string())?;
        self.stream = Some(stream);

        Ok(())
    }

    pub fn stop(&mut self) {
        self.running.store(false, Ordering::SeqCst);
        self.stream = None;
    }
}
