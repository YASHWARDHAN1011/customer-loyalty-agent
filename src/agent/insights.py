"""
Proactive Insights — deterministic signal detection.

Pure Python (no Streamlit, no LLM), per the src/analysis convention. Reads the
results of the existing analysis layer and decides which few things are most
worth surfacing to the user. Every number here comes straight from the analysis
functions — nothing is invented. The LLM (in proactive.py) only narrates the
digest these signals produce; it never computes figures.
"""

from src.analysis.metrics import calculate_churn_risk
from src.analysis.segmentation import compute_segment_gaps
from src.analysis.interventions import (
    compute_intervention_gaps,
    INTERVENTION_TEMPLATES,
)
from src.analysis.happy_path import get_happy_paths


def _clamp(value):
    """Coerce a severity score into an int in [0, 100]."""
    return int(max(0, min(100, round(value))))


def _churn_signal(features, power_user_ids, churn_days):
    at_risk, at_risk_power = calculate_churn_risk(
        features, power_user_ids, churn_days
    )
    n_total = len(features)
    n_at_risk = len(at_risk)
    if n_total == 0 or n_at_risk == 0:
        return None

    pct = 100.0 * n_at_risk / n_total
    n_power = len(at_risk_power)
    # Severity scales with how widespread the risk is, plus extra weight when
    # the at-risk pool contains your most valuable (power) users.
    power_share = n_power / n_at_risk
    severity = _clamp(pct + 30.0 * power_share)

    detail = (
        f"{n_at_risk} of {n_total} customers haven't ordered in over "
        f"{churn_days} days"
    )
    if n_power > 0:
        detail += f" — {n_power} of them are power users you can't afford to lose"
    else:
        detail += " — none are power users yet, but the trend is worth watching"

    return {
        "id": "churn",
        "severity": severity,
        "icon": "⚠️",
        "headline": f"{n_at_risk} customers ({pct:.0f}%) are slipping away",
        "detail": detail,
        "action_label": "Build a retention plan",
        "action_prompt": (
            "Build an action plan for at-risk customers using a 30-day "
            "threshold and export the target list."
        ),
    }


def _segment_gap_signal(power, regular):
    if len(power) == 0 or len(regular) == 0:
        return None
    gaps = compute_segment_gaps(power, regular)
    if not gaps:
        return None
    top = gaps[0]
    ratio = top["ratio"]
    if ratio <= 1.0:
        return None

    # A 1× gap is nothing; the further above 1×, the more striking.
    severity = _clamp((ratio - 1.0) * 40.0)
    feature = top["feature"]

    return {
        "id": "segment_gap",
        "severity": severity,
        "icon": "📊",
        "headline": f"Power users have {ratio}× higher {feature}",
        "detail": (
            f"Power users average {top['power_user_avg']} vs "
            f"{top['regular_user_avg']} for regular users on {feature} — "
            f"your single biggest behavioral gap"
        ),
        "action_label": "Compare segments & draft campaigns",
        "action_prompt": (
            "Compare power users vs regular users and draft campaign emails "
            "for the biggest gap."
        ),
    }


def _intervention_signal(power, regular):
    if len(power) == 0 or len(regular) == 0:
        return None
    gaps = compute_intervention_gaps(power, regular)
    if not gaps:
        return None
    gap_pct, col, ru_avg, pu_avg = gaps[0]
    template = INTERVENTION_TEMPLATES.get(col)
    if template is None:
        return None

    severity = _clamp(gap_pct / 2.0)

    return {
        "id": "intervention",
        "severity": severity,
        "icon": template["icon"],
        "headline": f"Top opportunity: {template['title']}",
        "detail": (
            f"Closing the '{template['title'].lower()}' gap is your highest-"
            f"leverage move — regular users trail power users by "
            f"{gap_pct:.0f}% here"
        ),
        "action_label": "Generate the campaign",
        "action_prompt": (
            "What campaign should we run first to convert regular users? "
            "Generate the recommendations."
        ),
    }


def _power_value_signal(power, scored_df):
    n_total = len(scored_df)
    n_power = len(power)
    if n_total == 0 or n_power == 0:
        return None
    pct = 100.0 * n_power / n_total
    # A smaller elite carrying the base means higher leverage per customer.
    severity = _clamp(100.0 - pct)

    return {
        "id": "power_value",
        "severity": severity,
        "icon": "⭐",
        "headline": f"Your top {pct:.0f}% are your loyalty engine",
        "detail": (
            f"Just {n_power} of {n_total} customers qualify as power users — "
            f"a small, high-leverage core worth protecting and cloning"
        ),
        "action_label": "Profile the top customers",
        "action_prompt": (
            "Show me the top 20 most loyal customers and what makes them "
            "different."
        ),
    }


def _happy_path_signal(full_data, power_user_ids, lookback=4):
    if full_data is None or len(full_data) == 0:
        return None
    paths = get_happy_paths(full_data, power_user_ids, lookback=lookback, top_n=1)
    if not paths:
        return None
    funnel = paths[0]["funnel"]
    if len(funnel) < 2:
        return None

    # Biggest single drop-off between consecutive funnel steps.
    worst_drop_pct = 0.0
    worst_step = funnel[1]["step"]
    for i in range(len(funnel) - 1):
        before = funnel[i]["users"]
        after = funnel[i + 1]["users"]
        if before <= 0:
            continue
        drop_pct = 100.0 * (before - after) / before
        if drop_pct > worst_drop_pct:
            worst_drop_pct = drop_pct
            worst_step = funnel[i + 1]["step"]

    if worst_drop_pct <= 0:
        return None

    severity = _clamp(worst_drop_pct)

    return {
        "id": "happy_path",
        "severity": severity,
        "icon": "🛤️",
        "headline": f"{worst_drop_pct:.0f}% drop on the path to loyalty",
        "detail": (
            f"The biggest leak on your power-user happy path is at "
            f"\"{worst_step}\" — plug it to convert more customers"
        ),
        "action_label": "Map the happy path",
        "action_prompt": (
            "Find the happy path to power-user status and where customers "
            "drop off."
        ),
    }


def detect_signals(features, scored_df, power, regular, power_user_ids,
                   full_data, churn_days=30, top_pct=10):
    """
    Inspect the analysis results and return up to 4 noteworthy signals,
    sorted by severity (most urgent first).

    Each signal is a dict:
        {id, severity (int 0-100), icon, headline, detail,
         action_label, action_prompt}

    Any signal whose inputs are missing or unremarkable is skipped cleanly —
    this never raises on partial data.
    """
    candidates = [
        _churn_signal(features, power_user_ids, churn_days),
        _segment_gap_signal(power, regular),
        _intervention_signal(power, regular),
        _power_value_signal(power, scored_df),
        _happy_path_signal(full_data, power_user_ids),
    ]
    signals = [s for s in candidates if s is not None]
    signals.sort(key=lambda s: s["severity"], reverse=True)
    return signals[:4]


def briefing_digest(signals):
    """
    Flatten signals into a compact plaintext block for the LLM to narrate.

    Carries the already-computed headline + detail for each signal, so the
    model only has to write prose — it never recomputes a number.
    """
    if not signals:
        return "No noteworthy signals detected in the current analysis."
    lines = []
    for s in signals:
        lines.append(f"- {s['headline']}: {s['detail']}")
    return "\n".join(lines)
