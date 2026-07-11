"""Full numbers panel — a lean, dataset-agnostic figures view.

Replaces the 5 retired analytical tabs with one panel that works identically on
the demo and on client uploads, because it reads the canonical feature matrix and
the lever-agnostic analysis helpers the agent tools already use. Best-effort: any
failure collapses to a one-line hint rather than crashing the chat-first page.
"""

import streamlit as st
import altair as alt

from src.analysis.metrics import calculate_churn_risk
from src.analysis.segmentation import compute_segment_gaps, build_comparison_data
from src.export.generator import generate_csv_export

_HINT = ("No analysis yet — ask the agent to \"score customers\", or use "
         "**Run Full Analysis** in the sidebar.")


def render_full_numbers():
    """Render the panel; never raise (collapses to a hint on any error)."""
    try:
        _render()
    except Exception:
        st.caption(_HINT)


def _render():
    scored = st.session_state.get("scored_df")
    if scored is None or len(scored) == 0:
        st.caption(_HINT)
        return

    features = st.session_state.get("features")
    power = st.session_state.get("power")
    regular = st.session_state.get("regular")
    cutoff = st.session_state.get("cutoff")
    power_ids = st.session_state.get("power_user_ids") or set()

    # --- key metrics ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Customers", f"{len(scored):,}")
    c2.metric("Power users",
              f"{len(power):,}" if power is not None else "—",
              help=(f"Score cutoff {cutoff:.1f}" if cutoff else None))
    at_risk_n = 0
    if features is not None:
        at_risk, _ = calculate_churn_risk(features, power_ids, 30)
        at_risk_n = len(at_risk)
    c3.metric("At-risk (30d)", f"{at_risk_n:,}")
    c4.metric("Avg loyalty score", f"{scored['loyalty_score'].mean():.1f}")

    # --- scored customers table + download ---
    st.divider()
    st.subheader("Scored customers")
    st.caption("Top 500 shown; download for the full list.")
    st.dataframe(
        scored.sort_values("loyalty_score", ascending=False).head(500),
        use_container_width=True, hide_index=True,
    )
    csv = generate_csv_export()
    if csv:
        st.download_button("⬇️ Download full scored CSV", data=csv,
                           file_name="scored_customers.csv", mime="text/csv")

    # --- power vs regular by active lever ---
    if power is not None and regular is not None:
        gaps = compute_segment_gaps(power, regular)
        if gaps:
            st.divider()
            st.subheader("Power vs regular — by lever")
            chart = (
                alt.Chart(build_comparison_data(gaps))
                .mark_bar(stroke="#00141F", strokeWidth=1.5)
                .encode(
                    x=alt.X("Feature:N", axis=alt.Axis(
                        labelAngle=-20, title="", labelColor="#FEF0D5",
                        domainColor="#FEF0D5")),
                    y=alt.Y("Value:Q", axis=alt.Axis(
                        labelColor="#FEF0D5", domainColor="#FEF0D5")),
                    xOffset="Segment:N",
                    color=alt.Color("Segment:N",
                        scale=alt.Scale(range=["#C1121F", "#FEF0D5"]),
                        legend=alt.Legend(labelColor="#FEF0D5",
                                          titleColor="#FEF0D5")),
                    tooltip=["Feature", "Segment", "Value"],
                )
                .properties(height=300)
                .configure_view(strokeWidth=0, fill="#0A3D5C")
            )
            st.altair_chart(chart, use_container_width=True)
