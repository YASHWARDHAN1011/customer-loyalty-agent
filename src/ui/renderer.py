"""
UI Renderer — Cards, Charts, Tables, Theme
"""

import streamlit as st
import altair as alt


# ── Intervention Card ─────────────────────────────────────────────────────────

def render_intervention_card(t, gap_pct, ru_avg, pu_avg, mid, count):
    badge_bg  = "rgba(239,68,68,0.15)"  if gap_pct >= 80 else "rgba(245,158,11,0.15)"  if gap_pct >= 60 else "rgba(16,185,129,0.15)"
    badge_col = "#ff6b6b"               if gap_pct >= 80 else "#fbbf24"                if gap_pct >= 60 else "#34d399"
    badge_bdr = "rgba(239,68,68,0.35)"  if gap_pct >= 80 else "rgba(245,158,11,0.35)" if gap_pct >= 60 else "rgba(16,185,129,0.35)"
    glow_col  = "rgba(239,68,68,0.12)"  if gap_pct >= 80 else "rgba(245,158,11,0.12)" if gap_pct >= 60 else "rgba(16,185,129,0.12)"

    st.markdown(
        f"""
        <div style="
            position: relative;
            padding: 1.3rem 1.5rem;
            margin-bottom: 1rem;
            background: rgba(0,0,0,0.65);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            border: 1px solid rgba(255,255,255,0.08);
            border-left: 3px solid {t['color']};
            border-radius: 16px;
            box-shadow:
                0 4px 32px rgba(0,0,0,0.5),
                inset 0 1px 0 rgba(255,255,255,0.06),
                0 0 0 1px rgba(255,255,255,0.03);
            overflow: hidden;
        ">
            <div style="
                position:absolute; top:-24px; right:-24px;
                width:160px; height:160px;
                background: radial-gradient(circle, {glow_col} 0%, transparent 70%);
                pointer-events:none;
            "></div>

            <div style="display:flex; align-items:flex-start; gap:12px; margin-bottom:14px;">
                <span style="
                    flex-shrink:0;
                    width:42px; height:42px;
                    display:flex; align-items:center; justify-content:center;
                    font-size:1.35rem; line-height:1;
                    border-radius:12px;
                    background: linear-gradient(135deg, rgba(79,106,255,0.20), rgba(34,212,255,0.10));
                    border: 1px solid rgba(79,106,255,0.28);
                    box-shadow: 0 0 18px rgba(79,106,255,0.15), inset 0 1px 0 rgba(255,255,255,0.12);
                ">{t['icon']}</span>
                <div style="flex:1; min-width:0;">
                    <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:4px;">
                        <span style="
                            color:rgba(255,255,255,0.92); font-size:1rem; font-weight:700;
                            letter-spacing:-0.015em;
                        ">{t['title']}</span>
                        <span style="
                            background:{badge_bg}; color:{badge_col};
                            border:1px solid {badge_bdr};
                            border-radius:99px; padding:2px 10px;
                            font-size:0.7rem; font-weight:700;
                            letter-spacing:0.05em;
                        ">{gap_pct:.0f}% GAP</span>
                    </div>
                    <p style="color:rgba(255,255,255,0.3); margin:0; font-size:0.76rem; font-weight:500;">
                        {count:,} users targeted &nbsp;&middot;&nbsp;
                        Regular: {ru_avg:.2f} &nbsp;&middot;&nbsp;
                        Power: {pu_avg:.2f}
                    </p>
                </div>
            </div>

            <div style="
                background: rgba(255,255,255,0.03);
                border: 1px solid rgba(255,255,255,0.06);
                border-radius: 12px;
                padding: 1rem 1.1rem;
                display: grid;
                gap: 10px;
            ">
                <div>
                    <p style="color:rgba(255,255,255,0.25); margin:0 0 2px; font-size:0.68rem;
                              font-weight:700; text-transform:uppercase; letter-spacing:0.1em;">
                        What the data shows
                    </p>
                    <p style="color:rgba(255,255,255,0.72); margin:0; font-size:0.84rem; line-height:1.5;">
                        {t['what'].format(ru=ru_avg, pu=pu_avg)}
                    </p>
                </div>
                <div>
                    <p style="color:rgba(255,255,255,0.25); margin:0 0 2px; font-size:0.68rem;
                              font-weight:700; text-transform:uppercase; letter-spacing:0.1em;">
                        Target segment
                    </p>
                    <p style="color:rgba(255,255,255,0.72); margin:0; font-size:0.84rem; line-height:1.5;">
                        {t['who'].format(mid=mid, count=count, ru=ru_avg, pu=pu_avg)}
                    </p>
                </div>
                <div>
                    <p style="color:rgba(255,255,255,0.25); margin:0 0 2px; font-size:0.68rem;
                              font-weight:700; text-transform:uppercase; letter-spacing:0.1em;">
                        Campaign action
                    </p>
                    <p style="color:rgba(255,255,255,0.72); margin:0; font-size:0.84rem; line-height:1.5;">
                        {t['action']}
                    </p>
                </div>
                <div style="padding-top:8px; border-top:1px solid rgba(255,255,255,0.05);">
                    <p style="color:rgba(255,255,255,0.25); margin:0 0 3px; font-size:0.68rem;
                              font-weight:700; text-transform:uppercase; letter-spacing:0.1em;">
                        Sample message
                    </p>
                    <p style="color:rgba(255,255,255,0.45); margin:0; font-size:0.8rem;
                              font-style:italic; line-height:1.5;">
                        {t['message']}
                    </p>
                    <p style="color:rgba(255,255,255,0.2); margin:4px 0 0; font-size:0.74rem;">
                        {t['metric'].format(ru=ru_avg, pu=pu_avg)}
                    </p>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Message / Chart Renderer ──────────────────────────────────────────────────

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

            axis_cfg = dict(
                labelColor="rgba(255,255,255,0.35)",
                titleColor="rgba(255,255,255,0.35)",
                gridColor="rgba(255,255,255,0.05)",
                domainColor="rgba(255,255,255,0.08)",
                tickColor="rgba(255,255,255,0.08)",
            )

            if msg["chart_type"] == "bar":
                chart = (
                    alt.Chart(data)
                    .mark_bar(
                        cornerRadiusTopLeft=6,
                        cornerRadiusTopRight=6,
                        color=alt.Gradient(
                            gradient="linear",
                            stops=[
                                alt.GradientStop(color="#4f6aff", offset=0),
                                alt.GradientStop(color="#22d4ff", offset=1),
                            ],
                            x1=0, x2=0, y1=1, y2=0,
                        ),
                    )
                    .encode(
                        x=alt.X(msg["x"], sort=None,
                                axis=alt.Axis(labelAngle=-45, **axis_cfg)),
                        y=alt.Y(msg["y"],
                                axis=alt.Axis(**axis_cfg)),
                        tooltip=[msg["x"], msg["y"]],
                    )
                    .properties(height=280)
                    .configure_view(strokeWidth=0, fill="#050505")
                )
                st.altair_chart(chart, use_container_width=True)

            elif msg["chart_type"] == "grouped_bar":
                chart = (
                    alt.Chart(data)
                    .mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5)
                    .encode(
                        x=alt.X(f"{msg['x']}:N",
                                axis=alt.Axis(labelAngle=-30, title="", **axis_cfg)),
                        y=alt.Y(f"{msg['y']}:Q",
                                axis=alt.Axis(**axis_cfg)),
                        xOffset=f"{msg['color']}:N",
                        color=alt.Color(
                            f"{msg['color']}:N",
                            scale=alt.Scale(range=["#4f6aff", "#1a2d4f"]),
                            legend=alt.Legend(
                                title="Segment",
                                labelColor="rgba(255,255,255,0.45)",
                                titleColor="rgba(255,255,255,0.35)",
                            ),
                        ),
                        tooltip=[msg["x"], msg["color"], msg["y"]],
                    )
                    .properties(height=300)
                    .configure_view(strokeWidth=0, fill="#050505")
                )
                st.altair_chart(chart, use_container_width=True)


# ── Table Styling Helper ──────────────────────────────────────────────────────

def color_ratio(val):
    if val >= 3:
        return "background-color:rgba(52,211,153,0.12); color:#34d399"
    elif val >= 2:
        return "background-color:rgba(110,231,183,0.08); color:#6ee7b7"
    elif val >= 1.5:
        return "background-color:rgba(167,243,208,0.06); color:#a7f3d0"
    return ""


# ── Theme ─────────────────────────────────────────────────────────────────────

def apply_theme():
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');

/* ══════════════════════════════════════════════════
   DESIGN TOKENS
══════════════════════════════════════════════════ */
:root {
  --accent:      #4f6aff;
  --accent-soft: rgba(79,106,255,0.12);
  --accent-glow: rgba(79,106,255,0.3);
  --cyan:        #22d4ff;

  --text:        rgba(255,255,255,0.92);
  --text-2:      rgba(255,255,255,0.55);
  --text-3:      rgba(255,255,255,0.28);

  --glass:       rgba(0,0,0,0.62);
  --glass-hi:    rgba(255,255,255,0.05);
  --border:      rgba(255,255,255,0.08);
  --border-md:   rgba(255,255,255,0.14);

  --font: 'Inter', system-ui, -apple-system, sans-serif;
  --r:    12px;
  --r-lg: 18px;
  --ease: cubic-bezier(0.4, 0, 0.2, 1);

  /* glass box-shadow — slim, clean: soft drop + subtle top highlight + hairline */
  --glass-shadow:
    0 4px 20px rgba(0,0,0,0.28),
    inset 0 1px 0 rgba(255,255,255,0.06),
    0 0 0 1px rgba(255,255,255,0.02);
  --glass-shadow-hover:
    0 6px 26px rgba(0,0,0,0.34),
    inset 0 1px 0 rgba(255,255,255,0.08),
    0 0 0 1px rgba(79,106,255,0.10);
}

/* ══════════════════════════════════════════════════
   KEYFRAMES — page load only (never re-fires per element)
══════════════════════════════════════════════════ */
@keyframes fadeIn {
  from { opacity:0; }
  to   { opacity:1; }
}

/* ══════════════════════════════════════════════════
   BASE — static ambient aurora gradient, no motion
══════════════════════════════════════════════════ */
html, body {
  background: #000 !important;
}
.stApp {
  background:
    radial-gradient(1200px 800px at 12% -8%, rgba(79,106,255,0.16) 0%, transparent 55%),
    radial-gradient(1100px 760px at 100% 108%, rgba(34,212,255,0.12) 0%, transparent 55%),
    radial-gradient(900px 700px at 88% 6%, rgba(79,106,255,0.06) 0%, transparent 60%),
    #050507 !important;
  background-attachment: fixed !important;
  font-family: var(--font) !important;
  color: var(--text) !important;
}
.main, .block-container {
  background: transparent !important;
  padding-top: 1.5rem !important;
  padding-bottom: 5rem !important;
  max-width: 1380px !important;
  animation: fadeIn 0.5s var(--ease) both !important;
}

[data-testid="stHeader"]  { background: transparent !important; }
[data-testid="stToolbar"] { display: none !important; }

/* ══════════════════════════════════════════════════
   SCROLLBAR
══════════════════════════════════════════════════ */
::-webkit-scrollbar             { width:5px; height:5px; }
::-webkit-scrollbar-track       { background: transparent; }
::-webkit-scrollbar-thumb       { background: rgba(255,255,255,0.1); border-radius:99px; }
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.22); }

/* ══════════════════════════════════════════════════
   SIDEBAR — dark glass panel
══════════════════════════════════════════════════ */
[data-testid="stSidebar"] {
  background: rgba(0,0,0,0.82) !important;
  backdrop-filter: blur(32px) !important;
  -webkit-backdrop-filter: blur(32px) !important;
  border-right: 1px solid var(--border) !important;
}
[data-testid="stSidebar"] > div:first-child { padding-top: 1.8rem !important; }

/* ══════════════════════════════════════════════════
   TYPOGRAPHY
══════════════════════════════════════════════════ */
h1 {
  color: var(--text) !important;
  font-size: 1.9rem !important;
  font-weight: 800 !important;
  letter-spacing: -0.03em !important;
  line-height: 1.15 !important;
}
h2 {
  color: rgba(255,255,255,0.75) !important;
  font-size: 1.3rem !important;
  font-weight: 700 !important;
  letter-spacing: -0.02em !important;
  border-bottom: 1px solid var(--border) !important;
  padding-bottom: 0.4rem !important;
  margin-bottom: 0.8rem !important;
}
h3 {
  color: rgba(255,255,255,0.58) !important;
  font-size: 1.05rem !important;
  font-weight: 600 !important;
  letter-spacing: -0.015em !important;
}
h4, h5, h6 { color: rgba(255,255,255,0.42) !important; font-weight: 600 !important; }
p, li { color: var(--text-2) !important; line-height: 1.75 !important; }
strong { color: var(--text) !important; }

code {
  background: rgba(255,255,255,0.06) !important;
  color: var(--cyan) !important;
  border: 1px solid var(--border) !important;
  border-radius: 6px !important;
  padding: 2px 7px !important;
  font-size: 0.87em !important;
}

[data-testid="stSidebar"] h2 {
  background: linear-gradient(125deg, rgba(255,255,255,0.92) 0%, #4f6aff 100%) !important;
  -webkit-background-clip: text !important;
  -webkit-text-fill-color: transparent !important;
  background-clip: text !important;
  border-bottom: none !important;
  font-size: 1.1rem !important;
}
[data-testid="stSidebar"] h3 {
  color: var(--text-2) !important;
  font-size: 0.78rem !important;
  font-weight: 700 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.1em !important;
  -webkit-text-fill-color: unset !important;
}

/* ══════════════════════════════════════════════════
   TABS — glass pill row
══════════════════════════════════════════════════ */
.stTabs [data-baseweb="tab-list"] {
  background: var(--glass) !important;
  backdrop-filter: blur(20px) !important;
  -webkit-backdrop-filter: blur(20px) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--r-lg) !important;
  padding: 5px !important;
  gap: 3px !important;
  margin-bottom: 1.5rem !important;
  box-shadow: var(--glass-shadow) !important;
}
.stTabs [data-baseweb="tab"] {
  background: transparent !important;
  border: none !important;
  border-radius: var(--r) !important;
  color: var(--text-2) !important;
  font-weight: 500 !important;
  font-size: 0.83rem !important;
  padding: 0.5rem 0.9rem !important;
  transition: color 0.2s var(--ease), background 0.2s var(--ease) !important;
}
.stTabs [data-baseweb="tab"]:hover {
  color: var(--text) !important;
  background: rgba(255,255,255,0.05) !important;
}
.stTabs [aria-selected="true"] {
  background: rgba(79,106,255,0.22) !important;
  border: 1px solid rgba(79,106,255,0.38) !important;
  color: #fff !important;
  font-weight: 600 !important;
  box-shadow: 0 0 20px rgba(79,106,255,0.28), var(--glass-shadow) !important;
  backdrop-filter: blur(10px) !important;
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] { display: none !important; }

/* ══════════════════════════════════════════════════
   METRIC CARDS — liquid glass
══════════════════════════════════════════════════ */
[data-testid="stMetric"] {
  background: var(--glass) !important;
  backdrop-filter: blur(24px) !important;
  -webkit-backdrop-filter: blur(24px) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--r-lg) !important;
  padding: 1.25rem 1.4rem !important;
  box-shadow: var(--glass-shadow) !important;
  transition: border-color 0.25s var(--ease),
              box-shadow    0.25s var(--ease) !important;
}
[data-testid="stMetric"]:hover {
  border-color: rgba(79,106,255,0.30) !important;
  box-shadow: var(--glass-shadow-hover), 0 0 22px rgba(79,106,255,0.12) !important;
}
[data-testid="stMetricLabel"] > div,
[data-testid="stMetric"] label {
  color: var(--text-3) !important;
  font-size: 0.7rem !important;
  font-weight: 700 !important;
  text-transform: uppercase !important;
  letter-spacing: 0.1em !important;
}
[data-testid="stMetricValue"] {
  color: var(--text) !important;
  font-size: 2rem !important;
  font-weight: 800 !important;
  letter-spacing: -0.03em !important;
  line-height: 1.1 !important;
}
[data-testid="stMetricDelta"] {
  font-size: 0.76rem !important;
  font-weight: 600 !important;
}

/* ══════════════════════════════════════════════════
   BUTTONS — liquid glass style
══════════════════════════════════════════════════ */
.stButton > button {
  background: rgba(255,255,255,0.05) !important;
  backdrop-filter: blur(14px) !important;
  -webkit-backdrop-filter: blur(14px) !important;
  color: var(--text-2) !important;
  border: 1px solid var(--border) !important;
  border-radius: 99px !important;
  font-weight: 500 !important;
  font-size: 0.84rem !important;
  padding: 0.5rem 1.2rem !important;
  letter-spacing: 0.01em !important;
  box-shadow: var(--glass-shadow) !important;
  transition: all 0.22s var(--ease) !important;
}
.stButton > button:hover {
  background: rgba(255,255,255,0.09) !important;
  color: var(--text) !important;
  border-color: rgba(79,106,255,0.30) !important;
  box-shadow: var(--glass-shadow-hover) !important;
}
.stButton > button:active {
  background: rgba(255,255,255,0.06) !important;
  box-shadow: var(--glass-shadow) !important;
}

/* Primary buttons */
[data-testid="baseButton-primary"] {
  background: rgba(79,106,255,0.22) !important;
  color: #fff !important;
  border: 1px solid rgba(79,106,255,0.4) !important;
  box-shadow: 0 0 24px rgba(79,106,255,0.22), var(--glass-shadow) !important;
}
[data-testid="baseButton-primary"]:hover {
  background: rgba(79,106,255,0.32) !important;
  border-color: rgba(79,106,255,0.6) !important;
  box-shadow: 0 0 30px rgba(79,106,255,0.28), var(--glass-shadow-hover) !important;
}

/* Download buttons */
.stDownloadButton > button {
  background: rgba(79,106,255,0.06) !important;
  color: rgba(79,106,255,0.85) !important;
  border: 1px solid rgba(79,106,255,0.25) !important;
  box-shadow: var(--glass-shadow) !important;
}
.stDownloadButton > button:hover {
  background: rgba(79,106,255,0.12) !important;
  border-color: rgba(79,106,255,0.45) !important;
  color: #fff !important;
}

/* ══════════════════════════════════════════════════
   INPUTS & SELECTS
══════════════════════════════════════════════════ */
[data-baseweb="select"] > div {
  background: rgba(255,255,255,0.05) !important;
  backdrop-filter: blur(12px) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--r) !important;
  color: var(--text) !important;
  transition: border-color 0.2s var(--ease) !important;
}
[data-baseweb="select"] > div:hover,
[data-baseweb="select"] > div:focus-within {
  border-color: rgba(79,106,255,0.45) !important;
  box-shadow: 0 0 0 3px rgba(79,106,255,0.1) !important;
}
[data-baseweb="popover"] {
  background: rgba(0,0,0,0.88) !important;
  backdrop-filter: blur(20px) !important;
  border: 1px solid var(--border-md) !important;
  border-radius: var(--r) !important;
}
[data-baseweb="menu"]   { background: transparent !important; }
[role="option"]:hover   { background: rgba(255,255,255,0.06) !important; }

/* Sliders */
.stSlider [role="slider"] {
  background: var(--accent) !important;
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 4px rgba(79,106,255,0.15) !important;
}

/* ══════════════════════════════════════════════════
   CHAT MESSAGES — glass panels
══════════════════════════════════════════════════ */
[data-testid="stChatMessage"] {
  background: var(--glass) !important;
  backdrop-filter: blur(20px) !important;
  -webkit-backdrop-filter: blur(20px) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--r-lg) !important;
  padding: 1rem 1.2rem !important;
  margin-bottom: 0.75rem !important;
  box-shadow: var(--glass-shadow) !important;
  transition: border-color 0.2s var(--ease) !important;
}
[data-testid="stChatMessage"]:hover {
  border-color: var(--border-md) !important;
}

/* Chat input */
[data-testid="stChatInput"] > div {
  background: rgba(0,0,0,0.65) !important;
  backdrop-filter: blur(20px) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--r-lg) !important;
  box-shadow: var(--glass-shadow) !important;
  transition: border-color 0.2s var(--ease), box-shadow 0.2s var(--ease) !important;
}
[data-testid="stChatInput"] > div:focus-within {
  border-color: rgba(79,106,255,0.45) !important;
  box-shadow: 0 0 0 3px rgba(79,106,255,0.1), var(--glass-shadow) !important;
}
[data-testid="stChatInput"] textarea {
  color: var(--text) !important;
  background: transparent !important;
}

/* ══════════════════════════════════════════════════
   DATA TABLES
══════════════════════════════════════════════════ */
[data-testid="stDataFrame"] {
  background: var(--glass) !important;
  backdrop-filter: blur(16px) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--r) !important;
  overflow: hidden !important;
  box-shadow: var(--glass-shadow) !important;
}

/* ══════════════════════════════════════════════════
   EXPANDERS
══════════════════════════════════════════════════ */
.stExpander {
  border: 1px solid var(--border) !important;
  border-radius: var(--r) !important;
  background: var(--glass) !important;
  backdrop-filter: blur(16px) !important;
  -webkit-backdrop-filter: blur(16px) !important;
  overflow: hidden !important;
  box-shadow: var(--glass-shadow) !important;
  transition: border-color 0.2s var(--ease) !important;
}
.stExpander:hover { border-color: var(--border-md) !important; }
.stExpander summary {
  color: var(--text-2) !important;
  font-weight: 600 !important;
  font-size: 0.9rem !important;
  padding: 0.75rem 1rem !important;
}

/* ══════════════════════════════════════════════════
   PROGRESS & DIVIDER
══════════════════════════════════════════════════ */
.stProgress > div {
  background: rgba(255,255,255,0.07) !important;
  border-radius: 99px !important;
}
.stProgress > div > div {
  background: linear-gradient(90deg, var(--accent), var(--cyan)) !important;
  border-radius: 99px !important;
}
hr {
  border: none !important;
  border-top: 1px solid var(--border) !important;
  margin: 1.5rem 0 !important;
}

/* ══════════════════════════════════════════════════
   CAPTION & SMALL TEXT
══════════════════════════════════════════════════ */
.stCaption, [data-testid="stCaptionContainer"] p {
  color: var(--text-3) !important;
  font-size: 0.79rem !important;
  line-height: 1.6 !important;
}

/* ══════════════════════════════════════════════════
   ALTAIR / VEGA CHARTS
══════════════════════════════════════════════════ */
.vega-embed {
  border-radius: var(--r) !important;
  overflow: hidden !important;
}
.vega-embed summary { display: none !important; }

/* ══════════════════════════════════════════════════
   ALERTS & SPINNER
══════════════════════════════════════════════════ */
[data-testid="stAlert"] {
  background: var(--glass) !important;
  backdrop-filter: blur(12px) !important;
  border-radius: var(--r) !important;
  border-color: var(--border) !important;
  font-size: 0.87rem !important;
}
[data-testid="stSpinner"] > div { border-top-color: var(--accent) !important; }
</style>
""",
        unsafe_allow_html=True,
    )
