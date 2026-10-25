# CLAUDE.md

## Aki Rules
Shared rules live at `~/.aki/akidevrule/`. Read `~/.aki/akidevrule/index.md` for the full rule index and loading policy.

---

## THIS PROJECT
### 1. Project Overview
- Name: Auto Sound Engineer (tool xklive)
- Description: Realtime acoustic feedback suppression system for Behringer X-Air (XR12, XR16, XR18) & Midas M-Air (MR12, MR18) via OSC UDP port 10024.
- Core Desktop & Audio Engine: Tauri v2 (Rust 1.90+), CPAL (CoreAudio/ASIO/ALSA), RustFFT, RTRB (Zero-allocation SPSC Ring Buffer), ROSC (OSC UDP Socket 10024).
- User Interface: Nuxt 4 / Vue 3 SPA + Vite + Scoped CSS (compiled into frontend/dist).
- Hardware Integration: XR18/MR18 via USB 18x18 + LAN; XR12/XR16/MR12 via LAN RTA 100-band (/meters/4).

### 2. Verification Command
- Run test suite: `npm test` or `cargo test --manifest-path src-tauri/Cargo.toml` (Must maintain 100% pass on all unit tests).
- Build desktop app: `npm run build` or `npx tauri build`.
- Build UI: `npm run generate` (in root or `frontend/`).
