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
    pub max_channels: u16,
    pub is_default: bool,
}

impl AudioEngine {
    pub fn new() -> Self {
        Self {
            stream: None,
            running: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn is_running(&self) -> bool {
        self.running.load(Ordering::SeqCst)
    }

    pub fn is_preferred_mixer_device_name(name: &str, max_channels: u16) -> bool {
        let upper = name.to_uppercase();
        upper.contains("X-USB")
            || upper.contains("X-AIR")
            || upper.contains("XR18")
            || upper.contains("MR18")
            || upper.contains("X18")
            || upper.contains("BEHRINGER")
            || upper.contains("MIDAS")
            || max_channels >= 8
    }

    pub fn find_preferred_mixer_device() -> Option<AudioDeviceItem> {
        let devices = Self::list_input_devices();
        devices
            .into_iter()
            .find(|d| Self::is_preferred_mixer_device_name(&d.name, d.max_channels))
    }

    pub fn list_input_devices() -> Vec<AudioDeviceItem> {
        let mut result = Vec::new();
        let host = cpal::default_host();
        let default_device_name = host.default_input_device().and_then(|d| d.name().ok());

        if let Ok(devices) = host.input_devices() {
            for device in devices {
                if let Ok(name) = device.name() {
                    let is_default = default_device_name.as_ref().map_or(false, |def| *def == name);
                    let max_channels = device
                        .default_input_config()
                        .map(|c| c.channels())
                        .unwrap_or(2);
                    result.push(AudioDeviceItem {
                        name,
                        max_channels,
                        is_default,
                    });
                }
            }
        }
        result
    }

    pub fn start<F>(
        &mut self,
        device_name: Option<&str>,
        sample_rate: u32,
        requested_channels: u16,
        mut on_channel_frame: F,
    ) -> Result<u16, String>
    where
        F: FnMut(u8, &[f32]) + Send + 'static,
    {
        self.stop();

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

        let hw_channels = device
            .default_input_config()
            .map(|c| c.channels())
            .unwrap_or(1)
            .clamp(1, 18);

        let channels = if requested_channels == 0 {
            hw_channels
        } else {
            requested_channels.min(hw_channels).max(1)
        };

        let config = StreamConfig {
            channels,
            sample_rate: cpal::SampleRate(sample_rate),
            buffer_size: cpal::BufferSize::Default,
        };

        let ring_capacity = (2048 * channels as usize * 8).max(65536);
        let (mut producer, mut consumer) = RingBuffer::<f32>::new(ring_capacity);

        self.running.store(true, Ordering::SeqCst);
        let running_clone = Arc::clone(&self.running);
        let ch_count = channels as usize;
        let monitored_channels = ch_count.min(16);

        std::thread::spawn(move || {
            let frame_samples = 2048 * ch_count;
            let mut ch_buffers: Vec<Vec<f32>> = (0..monitored_channels)
                .map(|_| vec![0.0f32; 2048])
                .collect();

            while running_clone.load(Ordering::SeqCst) {
                if consumer.slots() >= frame_samples {
                    for sample_idx in 0..2048 {
                        for c in 0..ch_count {
                            if let Ok(sample) = consumer.pop() {
                                if c < monitored_channels {
                                    ch_buffers[c][sample_idx] = sample;
                                }
                            }
                        }
                    }
                    let mut ch_order: Vec<(usize, f32)> = (0..monitored_channels)
                        .map(|c| {
                            let max_amp = ch_buffers[c]
                                .iter()
                                .fold(0.0f32, |acc, &s| acc.max(s.abs()));
                            (c, max_amp)
                        })
                        .collect();
                    ch_order.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
                    for (c, _) in ch_order {
                        on_channel_frame((c + 1) as u8, &ch_buffers[c]);
                    }
                } else {
                    std::thread::sleep(std::time::Duration::from_millis(5));
                }
            }
        });

        let running_for_err = Arc::clone(&self.running);
        let stream = device
            .build_input_stream(
                &config,
                move |data: &[f32], _: &_| {
                    for &sample in data {
                        let _ = producer.push(sample);
                    }
                },
                move |err| {
                    eprintln!("Audio stream error: {}", err);
                    running_for_err.store(false, Ordering::SeqCst);
                },
                None,
            )
            .map_err(|e| e.to_string())?;

        stream.play().map_err(|e| e.to_string())?;
        self.stream = Some(stream);

        Ok(channels)
    }

    pub fn stop(&mut self) {
        self.running.store(false, Ordering::SeqCst);
        self.stream = None;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_preferred_mixer_device_matching() {
        assert!(AudioEngine::is_preferred_mixer_device_name("X-USB", 2));
        assert!(AudioEngine::is_preferred_mixer_device_name("Behringer XR18", 18));
        assert!(AudioEngine::is_preferred_mixer_device_name("MIDAS MR18", 18));
        assert!(AudioEngine::is_preferred_mixer_device_name("Custom USB Audio Interface", 8));

        assert!(!AudioEngine::is_preferred_mixer_device_name("MacBook Pro Microphone", 1));
        assert!(!AudioEngine::is_preferred_mixer_device_name("Built-in Input", 2));
    }
}
