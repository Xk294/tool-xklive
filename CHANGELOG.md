# Changelog

All notable changes to **Auto Sound Engineer (`tool xklive`)** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-10-24

### Added
- **Easy Mode 4-Step Workflow (`EasyModeView.vue`)**: Guided assistant for non-technical operators covering mixer connection (`EasyStepConnect.vue`), microphone & preamp check (`EasyStepMicCheck.vue`), pre-show room calibration (`EasyStepWizard.vue`), and live show protection (`EasyStepLiveShow.vue`) with end-of-show summary report (`EasyShowReportModal.vue`).
- **10-Second Gain Calibration & Clip Guardian (`dsp/gain_staging.rs`)**: Real-time RMS/peak level analysis per channel with preamp gain delta suggestions and sustained clipping alerts.
- **MC Reverb Auto-Talkover (`dsp/talkover.rs`)**: Automatic FX return fader ducking when the designated MC microphone is active, with manual override cooldown protection.
- **Two-Factor Feedback Localizer (`dsp/localizer.rs`)**: Combined channel meter energy and mixer routing/mute state scoring to identify suspected feedback channels in LAN RTA mode.
- **Channel Low-Cut HPF & Whitelist Controls**: Per-channel 80 Hz high-pass filter toggle (`/ch/xx/preamp/hpon`, `/ch/xx/preamp/hpf`) and music/playback channel EQ lock whitelist.
- **Panic Undo (`undo_panic_reset`)**: One-click restoration of active PEQ notches cleared by an accidental Panic trigger.

### Changed
- **Background Ring-Out Wizard (`state.rs`, `core/ringout.rs`)**: Moved Ring-Out Wizard frame stepping into the 250ms background telemetry loop with automatic fader restoration on mixer disconnect, Panic, or snapshot rollback.
- **USB Multitrack Crosstalk Filtering (`commands.rs`)**: Filtered acoustic bleed across adjacent USB input channels before dispatching feedback proposals.
- **Paced PEQ Batch Transmission (`state.rs`)**: Added paced UDP batch sending for multi-band PEQ rollbacks and restorations to prevent X-Air UDP buffer drops.

### Fixed
- **Initial Preamp, Fader & Bus Send State Sync (`mixer/xair.rs`, `state.rs`)**: Queried `/headamp/00..16/gain`, `/ch/xx/preamp/trim`, `/ch/xx/mix/fader`, `/ch/xx/mix/xx/level`, and `/bus/xx/mix/on` upon mixer connection so gain calibration and two-factor feedback localization use live mixer values instead of fallback defaults.
- **Pre-Show Snapshot Rollback (`commands.rs`)**: Restored full cached mixer PEQ band states on `rollback_snapshot` even when taken prior to any automatic notch cuts.
- **USB Meter Decay & Concurrency (`state.rs`, `commands.rs`)**: Isolated USB meter updates from the UDP `/meters/1` receiver buffer and added time-based decay for inactive USB channels.

## [0.1.0] - 2026-03-15

### Added
- Initial release of Auto Sound Engineer on Tauri v2 (Rust backend + Nuxt 4 / Vue 3 Pro Studio Dashboard).
- Lock-free `cpal` + `rtrb` 18x18 USB audio engine and 2048-point Hann FFT MSD feedback detector (`dsp/detector.rs`).
- 100-band LAN RTA feedback detector (`dsp/rta_detector.rs`) and UDP/OSC protocol client (`mixer/xair.rs`) for Behringer X-Air (`XR12`, `XR16`, `XR18`) and Midas M-Air (`MR12`, `MR18`).
- Pure-function Safety Controller (`core/safety.rs`) enforcing `-12.0 dB` max cut, `+4.0 dB` max boost, 2 tx/sec rate limiting, 10s manual override lock, and 500ms expected-echo filtering.
