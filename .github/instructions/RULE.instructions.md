---
applyTo: "**"
---

## PART 1 — GLOBAL
### Language & Communication
- Code & comments: English only
- Chat responses: Vietnamese if complex/long; English otherwise
- Commit messages: English, imperative (feat:, fix:, refactor:, test:, docs:)
- No attribution: Never add Co-authored-by, Claude-Session, or AI trailers in git commits

### Dev Philosophy
- Single developer: Simple native flows, no enterprise bureaucracy
- MVP-first: Core DSP & Safety first, iterate companions later
- DRY & YAGNI: Don't add speculative layers or wrappers
- Done = verified: Run `npm test` before declaring any task complete

---

## PART 2 — AUTO SOUND ENGINEER STACK (TAURI v2 RUST + DSP + OSC + NUXT 4)
- Control Plane Only: Audio never flows through laptop code for processing.
- Licensing Compliance: Only MIT, BSD, Apache 2.0, Unlicense. Never introduce GPL/AGPL or FFTW.
- SPSC Ring Buffer: Zero heap allocation in steady-state loop.
- Rate Limit: Max 2 transactions/second over OSC.
- Expected-Echo Window: 500ms TTL on sent values to avoid false-triggering the 10s manual override lock.
- Soundman Tone Preservation: On mics, only touch Bands 3 & 4. On Main L/R, only touch Bands 3, 4, 5, 6. Keep Bands 1 & 2 for FOH tone.
- Frontend: Static SPA output (ssr: false) generated to frontend/dist/ and loaded by Tauri (`frontendDist`).
