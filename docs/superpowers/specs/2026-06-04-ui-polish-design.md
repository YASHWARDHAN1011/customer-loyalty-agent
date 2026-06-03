# UI Polish — "Calm, Seamless Glass"

**Date:** 2026-06-04
**Scope:** Visual polish only. No logic, data, or agent changes.
**Files touched:** `src/ui/renderer.py` (`apply_theme`, `render_intervention_card`), `app.py` (header block).

## Problem

The app uses a dark "liquid-glass" aesthetic over an animated WebGL shader. It reads as
sloppy because:

1. **Animations replay on every rerun.** Streamlit reruns the whole script on any
   interaction. Per-element `fadeUp`/`fadeIn` (set with `both`) re-fire each rerun, so the
   page visibly jumps/flickers on every click, slider, or tab switch.
2. **The shader clashes.** A perpetually-moving RGB-split sine-wave background is visual
   noise against the otherwise restrained glass UI, and runs a constant GPU animation loop.
3. **Glass shadows are too heavy.** The 8-layer `--glass-shadow` reads as muddy/overdone.
4. **Hovers are twitchy.** `translateY(-3px) scale(1.015)` on cards/buttons feels jumpy.
5. **Glass icon chips don't belong.** The header logo tile (and similar chips) use neutral
   white glass (`rgba(255,255,255,0.06)`) that floats on top of the background rather than
   feeling lit by it.

## Design

### 1. Background → static ambient gradient
Remove `_SHADER_HTML` and `_inject_shader()` entirely (and the call in `apply_theme`).
Replace with a still, layered CSS radial gradient on near-black: a soft accent
blue (`#4f6aff`) → cyan (`#22d4ff`) aurora glow anchored top-left and bottom-right.
Zero motion. Applied via `.stApp` background; `html, body` stay `#000`.

### 2. Motion → once on load only
Remove `animation: fadeUp ...` / `fadeIn ...` from: `[data-testid="stMetric"]`,
`[data-testid="stChatMessage"]`, `[data-testid="stDataFrame"]`, `.vega-embed`.
Keep a single subtle `fadeIn` on `.block-container` only. Keep `transition:` rules
(hover/color/border) everywhere — these do not replay and keep the UI feeling responsive.
Keyframe `fadeUp` may be removed once unused; keep `fadeIn` for the page load.

### 3. Glass → lighter
Slim `--glass-shadow` from 8 layers to ~3: one soft outer drop shadow, one subtle top
inner highlight, one faint hairline. `--glass-shadow-hover` similarly trimmed (no heavy
white glow bloom).

### 4. Hover → calm
Replace transforms that scale or lift >1px with border-color + soft accent glow changes
only. Applies to `[data-testid="stMetric"]:hover`, `.stButton > button:hover`,
`[data-testid="baseButton-primary"]:hover`, download buttons. At most `translateY(-1px)`,
no `scale`.

### 5. Icons → match the background vibe
Introduce an accent-tinted glass treatment for icon chips. The header logo tile in
`app.py` changes from neutral white glass to a faint accent blue→cyan gradient fill,
accent-tinted border (`rgba(79,106,255,0.3)`), and a soft accent glow that echoes the
background aurora — so it reads as lit by the same light. Intervention-card icon spans
get the same tinted treatment where they sit on glass.

## Out of scope
Tab content, sidebar structure, Altair chart internals, any non-visual behavior.

## Verification
Launch the app (`..\venv\Scripts\python.exe -m streamlit run app.py` from the inner dir),
confirm: no shader/motion on the background; clicking tabs/sliders does not re-fade cards;
header icon tile is accent-tinted and harmonizes with the background; glass panels look
lighter; hovers are calm. Existing standalone tests still pass.
