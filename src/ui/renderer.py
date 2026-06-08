"""
UI Renderer — Cards, Charts, Tables, Theme

Visual language: NEO-BRUTALIST POP (DARK).
Near-black canvas, off-white 4px "ink" borders + hard offset shadows (no blur),
high-saturation color blocking (red/yellow/violet/mint), mechanical press
interactions, Space Grotesk display type. Bright accent blocks carry dark
(on-accent) text; neutral dark surfaces carry off-white text. Charts use solid
color blocks with black strokes on a dark panel.
"""

import streamlit as st
import altair as alt


# ── Brutalist palette (shared with tab charts) ────────────────────────────────

INK       = "#F5F2E6"   # off-white: borders, hard shadows, body text
ON_ACCENT = "#0A0A0A"   # dark ink: text/strokes that sit on bright accent fills
CREAM     = "#141416"   # app canvas + inset boxes
PAPER     = "#1F1F23"   # card / panel surfaces
RED       = "#FF5C5C"
YELLOW    = "#FFD93D"
VIOLET    = "#B9A4FF"
MINT      = "#3DDC84"
BLUE      = "#5B8DEF"
GRID      = "rgba(245,242,230,0.12)"


def brutal_axis(**overrides):
    """Light-on-dark, high-contrast Altair axis config in the brutalist key."""
    cfg = dict(
        labelColor=INK,
        titleColor=INK,
        gridColor=GRID,
        domainColor=INK,
        tickColor=INK,
        labelFont="Space Grotesk",
        titleFont="Space Grotesk",
        labelFontWeight=600,
        titleFontWeight=700,
        domainWidth=2,
        tickWidth=2,
    )
    cfg.update(overrides)
    return cfg


def brutal_bar(data, x, y, color=RED, height=280, label_angle=0, tooltip=None):
    """A solid, black-outlined brutalist bar chart on a dark panel."""
    return (
        alt.Chart(data)
        .mark_bar(cornerRadius=0, stroke=ON_ACCENT, strokeWidth=2, color=color)
        .encode(
            x=alt.X(x, sort=None, axis=alt.Axis(labelAngle=label_angle, **brutal_axis())),
            y=alt.Y(y, axis=alt.Axis(**brutal_axis())),
            tooltip=tooltip or [x, y],
        )
        .properties(height=height)
        .configure_view(strokeWidth=0, fill=PAPER)
        .configure_axis(grid=True)
    )


# ── Intervention Card ─────────────────────────────────────────────────────────

def render_intervention_card(t, gap_pct, ru_avg, pu_avg, mid, count):
    # Severity drives the block accent color (dark text stays on all of them).
    accent = RED if gap_pct >= 80 else YELLOW if gap_pct >= 60 else MINT
    tilt   = "-0.6deg"

    st.markdown(
        f"""
        <div class="brutal-card" style="
            position: relative;
            padding: 1.4rem 1.5rem;
            margin-bottom: 1.4rem;
            background: {PAPER};
            border: 4px solid {INK};
            box-shadow: 8px 8px 0 {INK};
            transform: rotate({tilt});
        ">
            <div style="
                position:absolute; top:-4px; left:-4px; bottom:-4px;
                width:12px; background:{accent};
                border:4px solid {INK}; border-right:none;
            "></div>

            <div style="display:flex; align-items:flex-start; gap:14px; margin-bottom:14px; padding-left:10px;">
                <span style="
                    flex-shrink:0;
                    width:46px; height:46px;
                    display:flex; align-items:center; justify-content:center;
                    font-size:1.4rem; line-height:1;
                    background:{accent};
                    border:3px solid {ON_ACCENT};
                    box-shadow:3px 3px 0 {ON_ACCENT};
                ">{t['icon']}</span>
                <div style="flex:1; min-width:0;">
                    <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:5px;">
                        <span style="
                            color:{INK}; font-size:1.08rem; font-weight:700;
                            font-family:'Space Grotesk',sans-serif;
                            letter-spacing:-0.02em; line-height:1.1;
                        ">{t['title']}</span>
                        <span style="
                            background:{accent}; color:{ON_ACCENT};
                            border:2.5px solid {ON_ACCENT};
                            padding:2px 9px;
                            font-family:'Space Mono',monospace;
                            font-size:0.68rem; font-weight:700;
                            letter-spacing:0.05em; text-transform:uppercase;
                            box-shadow:2px 2px 0 {ON_ACCENT};
                        ">{gap_pct:.0f}% GAP</span>
                    </div>
                    <p style="color:{INK}; opacity:0.55; margin:0; font-size:0.74rem; font-weight:600;
                              font-family:'Space Mono',monospace; letter-spacing:0.02em;">
                        {count:,} USERS &nbsp;//&nbsp; REG {ru_avg:.2f} &nbsp;//&nbsp; POW {pu_avg:.2f}
                    </p>
                </div>
            </div>

            <div style="
                background:{CREAM};
                border:3px solid {INK};
                padding:1rem 1.1rem;
                display:grid; gap:12px;
                margin-left:10px;
            ">
                <div>
                    <p style="color:{accent}; margin:0 0 3px; font-size:0.64rem;
                              font-family:'Space Mono',monospace;
                              font-weight:700; text-transform:uppercase; letter-spacing:0.12em;">
                        ▸ What the data shows
                    </p>
                    <p style="color:{INK}; margin:0; font-size:0.86rem; line-height:1.5; font-weight:500;">
                        {t['what'].format(ru=ru_avg, pu=pu_avg)}
                    </p>
                </div>
                <div>
                    <p style="color:{accent}; margin:0 0 3px; font-size:0.64rem;
                              font-family:'Space Mono',monospace;
                              font-weight:700; text-transform:uppercase; letter-spacing:0.12em;">
                        ▸ Target segment
                    </p>
                    <p style="color:{INK}; margin:0; font-size:0.86rem; line-height:1.5; font-weight:500;">
                        {t['who'].format(mid=mid, count=count, ru=ru_avg, pu=pu_avg)}
                    </p>
                </div>
                <div>
                    <p style="color:{accent}; margin:0 0 3px; font-size:0.64rem;
                              font-family:'Space Mono',monospace;
                              font-weight:700; text-transform:uppercase; letter-spacing:0.12em;">
                        ▸ Campaign action
                    </p>
                    <p style="color:{INK}; margin:0; font-size:0.86rem; line-height:1.5; font-weight:500;">
                        {t['action']}
                    </p>
                </div>
                <div style="padding-top:10px; border-top:3px solid {INK};">
                    <p style="color:{accent}; margin:0 0 4px; font-size:0.64rem;
                              font-family:'Space Mono',monospace;
                              font-weight:700; text-transform:uppercase; letter-spacing:0.12em;">
                        ▸ Sample message
                    </p>
                    <p style="color:{INK}; opacity:0.82; margin:0; font-size:0.82rem;
                              font-style:italic; line-height:1.5;">
                        “{t['message']}”
                    </p>
                    <p style="color:{INK}; opacity:0.45; margin:5px 0 0; font-size:0.72rem;
                              font-family:'Space Mono',monospace;">
                        {t['metric'].format(ru=ru_avg, pu=pu_avg)}
                    </p>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Message / Chart Renderer ──────────────────────────────────────────────────

def download_key() -> str:
    """Monotonic unique key for st.download_button.

    st.tabs renders every tab body on each run, so the same artifact can be
    drawn in more than one place in a single pass. A monotonic counter
    guarantees a unique key per button within any single render.
    """
    st.session_state['_dl_counter'] = st.session_state.get('_dl_counter', 0) + 1
    return f"dl_{st.session_state['_dl_counter']}"


def render_message(msg: dict):
    with st.chat_message(msg["role"]):
        if msg["type"] == "text":
            st.markdown(msg["content"])

        elif msg["type"] == "table":
            if msg.get("title"):
                st.markdown(f"#### {msg['title']}")
            st.dataframe(msg["data"], use_container_width=True, hide_index=True)

        elif msg["type"] == "chart":
            st.markdown(f"#### {msg['title']}")
            data = msg["data"]

            if msg["chart_type"] == "bar":
                chart = (
                    alt.Chart(data)
                    .mark_bar(cornerRadius=0, stroke=ON_ACCENT, strokeWidth=2, color=RED)
                    .encode(
                        x=alt.X(msg["x"], sort=None,
                                axis=alt.Axis(labelAngle=-45, **brutal_axis())),
                        y=alt.Y(msg["y"], axis=alt.Axis(**brutal_axis())),
                        tooltip=[msg["x"], msg["y"]],
                    )
                    .properties(height=280)
                    .configure_view(strokeWidth=0, fill=PAPER)
                )
                st.altair_chart(chart, use_container_width=True)

            elif msg["chart_type"] == "grouped_bar":
                chart = (
                    alt.Chart(data)
                    .mark_bar(cornerRadius=0, stroke=ON_ACCENT, strokeWidth=1.5)
                    .encode(
                        x=alt.X(f"{msg['x']}:N",
                                axis=alt.Axis(labelAngle=-30, title="", **brutal_axis())),
                        y=alt.Y(f"{msg['y']}:Q", axis=alt.Axis(**brutal_axis())),
                        xOffset=f"{msg['color']}:N",
                        color=alt.Color(
                            f"{msg['color']}:N",
                            scale=alt.Scale(range=[RED, VIOLET]),
                            legend=alt.Legend(
                                title="SEGMENT",
                                labelColor=INK, titleColor=INK,
                                labelFont="Space Mono", titleFont="Space Mono",
                            ),
                        ),
                        tooltip=[msg["x"], msg["color"], msg["y"]],
                    )
                    .properties(height=300)
                    .configure_view(strokeWidth=0, fill=PAPER)
                )
                st.altair_chart(chart, use_container_width=True)

        elif msg["type"] == "artifact":
            st.download_button(
                label=msg.get("label", "⬇️ Download"),
                data=msg["content"],
                file_name=msg["filename"],
                mime=msg["mime"],
                key=download_key(),
            )


# ── Table Styling Helper ──────────────────────────────────────────────────────

def color_ratio(val):
    if val >= 3:
        return f"background-color:{MINT}; color:{ON_ACCENT}; font-weight:700"
    elif val >= 2:
        return "background-color:rgba(61,220,132,0.45); color:#F5F2E6; font-weight:600"
    elif val >= 1.5:
        return "background-color:rgba(61,220,132,0.20); color:#F5F2E6"
    return ""


# ── Theme ─────────────────────────────────────────────────────────────────────

def apply_theme():
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap');

/* ══════════════════════════════════════════════════
   DESIGN TOKENS — NEO-BRUTALIST POP (DARK)
══════════════════════════════════════════════════ */
:root {
  --ink:       #F5F2E6;   /* off-white lines / shadows / text       */
  --on-accent: #0A0A0A;   /* dark text/strokes on bright accents    */
  --canvas:    #141416;   /* app background + inset boxes           */
  --paper:     #1F1F23;   /* card / panel surfaces                  */
  --red:       #FF5C5C;
  --yellow:    #FFD93D;
  --violet:    #B9A4FF;
  --mint:      #3DDC84;
  --blue:      #5B8DEF;

  --font:  'Space Grotesk', system-ui, sans-serif;
  --mono:  'Space Mono', ui-monospace, monospace;

  --bw:    4px;                       /* primary border weight  */
  --bw2:   3px;                       /* secondary border weight */
  --sh:    6px 6px 0 var(--ink);      /* hard offset shadow (off-white) */
  --sh-lg: 8px 8px 0 var(--ink);
  --sh-sm: 3px 3px 0 var(--ink);
  --ease:  cubic-bezier(0.34, 1.4, 0.5, 1);
}

@keyframes fadeIn { from { opacity:0; } to { opacity:1; } }

/* ══════════════════════════════════════════════════
   BASE — near-black canvas with a faint pop dot-grid
══════════════════════════════════════════════════ */
html, body { background: var(--canvas) !important; }
.stApp {
  background-color: var(--canvas) !important;
  background-image:
    radial-gradient(rgba(245,242,230,0.06) 1.4px, transparent 1.4px);
  background-size: 22px 22px !important;
  background-attachment: fixed !important;
  font-family: var(--font) !important;
  color: var(--ink) !important;
}
.main, .block-container {
  background: transparent !important;
  padding-top: 1.5rem !important;
  padding-bottom: 5rem !important;
  max-width: 1380px !important;
  animation: fadeIn 0.4s var(--ease) both !important;
}
[data-testid="stHeader"]  { background: transparent !important; }
[data-testid="stToolbar"] { display: none !important; }

/* ══════════════════════════════════════════════════
   SCROLLBAR
══════════════════════════════════════════════════ */
::-webkit-scrollbar             { width:12px; height:12px; }
::-webkit-scrollbar-track       { background: var(--canvas); border-left:2px solid var(--ink); }
::-webkit-scrollbar-thumb       { background: var(--ink); border:3px solid var(--canvas); }
::-webkit-scrollbar-thumb:hover { background: var(--red); }

/* ══════════════════════════════════════════════════
   SIDEBAR — solid panel with hard right border
══════════════════════════════════════════════════ */
[data-testid="stSidebar"] {
  background: var(--paper) !important;
  border-right: var(--bw) solid var(--ink) !important;
}
[data-testid="stSidebar"] > div:first-child { padding-top: 1.6rem !important; }

/* ══════════════════════════════════════════════════
   TYPOGRAPHY
══════════════════════════════════════════════════ */
h1 {
  color: var(--ink) !important;
  font-family: var(--font) !important;
  font-size: 2rem !important;
  font-weight: 700 !important;
  letter-spacing: -0.04em !important;
  line-height: 1.05 !important;
  text-transform: uppercase !important;
}
h2 {
  color: var(--on-accent) !important;
  font-family: var(--font) !important;
  font-size: 1.35rem !important;
  font-weight: 700 !important;
  letter-spacing: -0.03em !important;
  text-transform: uppercase !important;
  display: inline-block !important;
  background: var(--yellow) !important;
  border: var(--bw2) solid var(--on-accent) !important;
  box-shadow: 3px 3px 0 var(--on-accent) !important;
  padding: 0.2rem 0.7rem !important;
  margin-bottom: 1rem !important;
}
h3 {
  color: var(--ink) !important;
  font-family: var(--font) !important;
  font-size: 1.05rem !important;
  font-weight: 700 !important;
  letter-spacing: -0.015em !important;
}
h4, h5, h6 {
  color: var(--ink) !important;
  font-family: var(--mono) !important;
  font-weight: 700 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.04em !important;
}
p, li { color: var(--ink) !important; line-height: 1.65 !important; font-weight: 500 !important; }
strong { color: var(--ink) !important; font-weight: 700 !important; }

code {
  background: var(--violet) !important;
  color: var(--on-accent) !important;
  border: 2px solid var(--on-accent) !important;
  border-radius: 0 !important;
  padding: 1px 6px !important;
  font-family: var(--mono) !important;
  font-size: 0.85em !important;
  font-weight: 700 !important;
}

[data-testid="stSidebar"] h2 {
  background: var(--red) !important;
  -webkit-text-fill-color: var(--on-accent) !important;
  color: var(--on-accent) !important;
  border: var(--bw2) solid var(--on-accent) !important;
  box-shadow: 3px 3px 0 var(--on-accent) !important;
  font-size: 1rem !important;
  width: 100% !important;
  text-align: center !important;
}
[data-testid="stSidebar"] h3 {
  color: var(--ink) !important;
  font-family: var(--mono) !important;
  font-size: 0.72rem !important;
  font-weight: 700 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.12em !important;
  border-bottom: 3px solid var(--ink) !important;
  padding-bottom: 0.25rem !important;
  margin-top: 0.6rem !important;
}

/* ══════════════════════════════════════════════════
   TABS — chunky pressable blocks
══════════════════════════════════════════════════ */
.stTabs [data-baseweb="tab-list"] {
  background: var(--paper) !important;
  border: var(--bw) solid var(--ink) !important;
  border-radius: 0 !important;
  padding: 6px !important;
  gap: 6px !important;
  margin-bottom: 1.6rem !important;
  box-shadow: var(--sh) !important;
  flex-wrap: wrap !important;
}
.stTabs [data-baseweb="tab"] {
  background: var(--canvas) !important;
  border: var(--bw2) solid var(--ink) !important;
  border-radius: 0 !important;
  color: var(--ink) !important;
  font-family: var(--font) !important;
  font-weight: 700 !important;
  font-size: 0.82rem !important;
  letter-spacing: -0.01em !important;
  padding: 0.45rem 0.9rem !important;
  transition: transform 0.12s var(--ease), box-shadow 0.12s var(--ease), background 0.12s, color 0.12s !important;
}
.stTabs [data-baseweb="tab"]:hover {
  background: var(--violet) !important;
  color: var(--on-accent) !important;
  border-color: var(--on-accent) !important;
  box-shadow: 3px 3px 0 var(--on-accent) !important;
  transform: translate(-1px,-1px) !important;
}
.stTabs [aria-selected="true"] {
  background: var(--red) !important;
  color: var(--on-accent) !important;
  border-color: var(--on-accent) !important;
  box-shadow: 3px 3px 0 var(--on-accent) !important;
  transform: translate(-1px,-1px) !important;
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display: none !important; }

/* ══════════════════════════════════════════════════
   METRIC CARDS — sticker blocks
══════════════════════════════════════════════════ */
[data-testid="stMetric"] {
  background: var(--paper) !important;
  border: var(--bw) solid var(--ink) !important;
  border-radius: 0 !important;
  padding: 1.2rem 1.3rem !important;
  box-shadow: var(--sh) !important;
  transition: transform 0.14s var(--ease), box-shadow 0.14s var(--ease) !important;
}
[data-testid="stMetric"]:hover {
  transform: translate(-3px,-3px) !important;
  box-shadow: var(--sh-lg) !important;
  border-color: var(--red) !important;
}
[data-testid="stMetricLabel"] > div,
[data-testid="stMetric"] label {
  color: var(--ink) !important;
  opacity: 0.7 !important;
  font-family: var(--mono) !important;
  font-size: 0.68rem !important;
  font-weight: 700 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.1em !important;
}
[data-testid="stMetricValue"] {
  color: var(--ink) !important;
  font-family: var(--font) !important;
  font-size: 2.1rem !important;
  font-weight: 700 !important;
  letter-spacing: -0.04em !important;
  line-height: 1.05 !important;
}
[data-testid="stMetricDelta"] {
  font-family: var(--mono) !important;
  font-size: 0.74rem !important;
  font-weight: 700 !important;
}

/* ══════════════════════════════════════════════════
   BUTTONS — chunky pressable
══════════════════════════════════════════════════ */
.stButton > button {
  background: var(--paper) !important;
  color: var(--ink) !important;
  border: var(--bw) solid var(--ink) !important;
  border-radius: 0 !important;
  font-family: var(--font) !important;
  font-weight: 700 !important;
  font-size: 0.86rem !important;
  letter-spacing: -0.01em !important;
  padding: 0.55rem 1.2rem !important;
  box-shadow: var(--sh) !important;
  transition: transform 0.1s var(--ease), box-shadow 0.1s var(--ease), background 0.1s, color 0.1s !important;
}
.stButton > button:hover {
  background: var(--violet) !important;
  color: var(--on-accent) !important;
  border-color: var(--on-accent) !important;
  transform: translate(-2px,-2px) !important;
  box-shadow: 8px 8px 0 var(--on-accent) !important;
}
.stButton > button:active {
  transform: translate(4px,4px) !important;
  box-shadow: 2px 2px 0 var(--on-accent) !important;
}

/* Primary buttons — red block, dark ink */
[data-testid="baseButton-primary"] {
  background: var(--red) !important;
  color: var(--on-accent) !important;
  border: var(--bw) solid var(--on-accent) !important;
  box-shadow: 6px 6px 0 var(--on-accent) !important;
}
[data-testid="baseButton-primary"]:hover {
  background: var(--yellow) !important;
  color: var(--on-accent) !important;
  transform: translate(-2px,-2px) !important;
  box-shadow: 8px 8px 0 var(--on-accent) !important;
}
[data-testid="baseButton-primary"]:active {
  transform: translate(4px,4px) !important;
  box-shadow: 2px 2px 0 var(--on-accent) !important;
}

/* Download buttons — violet block */
.stDownloadButton > button {
  background: var(--violet) !important;
  color: var(--on-accent) !important;
  border: var(--bw) solid var(--on-accent) !important;
  border-radius: 0 !important;
  font-family: var(--font) !important;
  font-weight: 700 !important;
  box-shadow: 6px 6px 0 var(--on-accent) !important;
}
.stDownloadButton > button:hover {
  background: var(--mint) !important;
  color: var(--on-accent) !important;
  transform: translate(-2px,-2px) !important;
  box-shadow: 8px 8px 0 var(--on-accent) !important;
}

/* ══════════════════════════════════════════════════
   INPUTS & SELECTS
══════════════════════════════════════════════════ */
[data-baseweb="select"] > div {
  background: var(--paper) !important;
  border: var(--bw2) solid var(--ink) !important;
  border-radius: 0 !important;
  color: var(--ink) !important;
  box-shadow: var(--sh-sm) !important;
  font-weight: 600 !important;
}
[data-baseweb="select"] > div:hover,
[data-baseweb="select"] > div:focus-within {
  background: var(--yellow) !important;
  color: var(--on-accent) !important;
  border-color: var(--on-accent) !important;
}
[data-baseweb="popover"] {
  background: var(--paper) !important;
  border: var(--bw2) solid var(--ink) !important;
  border-radius: 0 !important;
  box-shadow: var(--sh) !important;
}
[data-baseweb="menu"]   { background: var(--paper) !important; }
[role="option"]         { color: var(--ink) !important; font-weight:600 !important; }
[role="option"]:hover   { background: var(--violet) !important; color: var(--on-accent) !important; }

/* Sliders — square red thumb */
.stSlider [data-baseweb="slider"] [role="slider"] {
  background: var(--red) !important;
  border: 3px solid var(--ink) !important;
  border-radius: 0 !important;
  box-shadow: var(--sh-sm) !important;
  height: 22px !important; width: 22px !important;
}
.stSlider [data-baseweb="slider"] div[style*="background"] {
  border-radius: 0 !important;
}

/* ══════════════════════════════════════════════════
   CHAT MESSAGES — sticker blocks
══════════════════════════════════════════════════ */
[data-testid="stChatMessage"] {
  background: var(--paper) !important;
  border: var(--bw2) solid var(--ink) !important;
  border-radius: 0 !important;
  padding: 1rem 1.2rem !important;
  margin-bottom: 0.9rem !important;
  box-shadow: var(--sh-sm) !important;
}
[data-testid="stChatInput"] > div {
  background: var(--paper) !important;
  border: var(--bw) solid var(--ink) !important;
  border-radius: 0 !important;
  box-shadow: var(--sh) !important;
}
[data-testid="stChatInput"] > div:focus-within {
  border-color: var(--red) !important;
}
[data-testid="stChatInput"] textarea {
  color: var(--ink) !important;
  background: transparent !important;
  font-weight: 500 !important;
}

/* ══════════════════════════════════════════════════
   DATA TABLES
══════════════════════════════════════════════════ */
[data-testid="stDataFrame"] {
  background: var(--paper) !important;
  border: var(--bw) solid var(--ink) !important;
  border-radius: 0 !important;
  overflow: hidden !important;
  box-shadow: var(--sh) !important;
}

/* ══════════════════════════════════════════════════
   EXPANDERS
══════════════════════════════════════════════════ */
.stExpander {
  border: var(--bw2) solid var(--ink) !important;
  border-radius: 0 !important;
  background: var(--paper) !important;
  overflow: hidden !important;
  box-shadow: var(--sh-sm) !important;
}
.stExpander summary {
  color: var(--ink) !important;
  font-family: var(--font) !important;
  font-weight: 700 !important;
  font-size: 0.9rem !important;
  padding: 0.75rem 1rem !important;
}

/* ══════════════════════════════════════════════════
   PROGRESS & DIVIDER
══════════════════════════════════════════════════ */
.stProgress > div {
  background: var(--canvas) !important;
  border: 3px solid var(--ink) !important;
  border-radius: 0 !important;
  overflow: hidden !important;
}
.stProgress > div > div {
  background: var(--red) !important;
  border-radius: 0 !important;
}
hr {
  border: none !important;
  border-top: var(--bw2) solid var(--ink) !important;
  margin: 1.5rem 0 !important;
}

/* ══════════════════════════════════════════════════
   CAPTION & SMALL TEXT
══════════════════════════════════════════════════ */
.stCaption, [data-testid="stCaptionContainer"] p {
  color: var(--ink) !important;
  opacity: 0.6 !important;
  font-family: var(--mono) !important;
  font-size: 0.74rem !important;
  line-height: 1.6 !important;
}

/* ══════════════════════════════════════════════════
   ALTAIR / VEGA CHARTS
══════════════════════════════════════════════════ */
.vega-embed {
  background: var(--paper) !important;
  border: var(--bw) solid var(--ink) !important;
  box-shadow: var(--sh) !important;
  border-radius: 0 !important;
  overflow: hidden !important;
  padding: 8px !important;
}
.vega-embed summary { display: none !important; }

/* ══════════════════════════════════════════════════
   ALERTS, STATUS & SPINNER
══════════════════════════════════════════════════ */
[data-testid="stAlert"] {
  background: var(--paper) !important;
  border: var(--bw2) solid var(--ink) !important;
  border-radius: 0 !important;
  box-shadow: var(--sh-sm) !important;
  color: var(--ink) !important;
  font-weight: 600 !important;
  font-size: 0.87rem !important;
}
[data-testid="stAlert"] * { color: var(--ink) !important; }
[data-testid="stNotification"], [data-testid="stStatusWidget"] { border-radius: 0 !important; }
[data-testid="stStatus"] {
  background: var(--paper) !important;
  border: var(--bw2) solid var(--ink) !important;
  border-radius: 0 !important;
  box-shadow: var(--sh-sm) !important;
}
[data-testid="stSpinner"] > div { border-top-color: var(--red) !important; }

/* ══════════════════════════════════════════════════
   DIALOG (onboarding) — framed paper block
══════════════════════════════════════════════════ */
[data-testid="stDialog"] > div,
div[role="dialog"] {
  background: var(--paper) !important;
  border: var(--bw) solid var(--ink) !important;
  border-radius: 0 !important;
  box-shadow: var(--sh-lg) !important;
}
</style>
""",
        unsafe_allow_html=True,
    )
