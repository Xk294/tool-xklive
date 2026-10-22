# CLAUDE.md

## Aki Rules
Shared rules live at `~/.aki/claudedoc/`. Read `~/.aki/claudedoc/index.md` for the full rule index and loading policy.

---

## THIS PROJECT
### 1. Project Overview
- Name: Auto Sound Engineer (tool xklive)
- Description: Realtime acoustic feedback suppression system for Behringer X-Air (XR12, XR16, XR18) & Midas M-Air (MR12, MR18) via OSC UDP port 10024.
- Core Engine: Python 3.11+, FastAPI, Uvicorn, OSC UDP Socket (10024), DSP (NumPy, SciPy PocketFFT, SoundDevice PortAudio).
- Web Companion: Nuxt 4 / Vue 3 SPA + Vite + Tailwind CSS (compiled statically into src/auto_sound/web/dist).
- Hardware Integration: XR18/MR18 via USB 18x18 + LAN; XR12/XR16/MR12 via LAN RTA 100-band (/meters/4).

### 2. Verification Command
- Run test suite: `.venv/bin/pytest -v` (Must maintain 100% pass on all 69+ active tests).
- Commercial License Check: `pip-licenses`.
