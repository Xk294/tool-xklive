# GEMINI.md — Rules & Bootstrap Configuration
This file serves as a global guardrail and bootstrap loader for Gemini and Antigravity agents working on the Auto Sound Engineer (tool xklive) project.

## Core Directives
### 1. Audio Plane vs Control Plane Isolation (CRITICAL)
- The live audio stream MUST NEVER pass through the laptop. Audio runs directly Micro -> Mixer -> Speakers.
- Laptop only receives signal copies via USB (XR18/MR18) or LAN RTA 100-band (XR12/XR16/MR12) to analyze DSP and send PEQ notch commands via OSC/UDP port 10024.
- If the software crashes or disconnects, the live show MUST NOT be interrupted.

### 2. Native Flow & Real-Time Safety Invariants
- Zero-Allocation: SPSC Ring Buffer in steady-state audio loops must strictly have 0 heap allocations.
- Safety Controller: Pure function safety rules (Rate limit max 2 tx/sec, -3 dB incremental probing, max cut -12 dB, max boost +4 dB, 10s manual override lock, expected-echo window 500ms TTL).
- Direct PEQ Enforcement: set_peq() must always verify /eq/on = 1 and enforce type = 2 (PEQ).
- Licensing Constraint: 100% Permissive open-source only (MIT, BSD, Apache-2.0, Unlicense). Strictly NO GPL/AGPL or FFTW dependencies.

### 3. Verification Standard
- All changes must pass the unit test suite (`npm test` / `cargo test`).

## Bootstrap Loader
The absolute source of truth for this project's rules, stack, and guidelines is CLAUDE.md at the project root.
