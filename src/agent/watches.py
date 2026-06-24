"""
Watches — deterministic threshold alerts (triggered proactivity).

Pure Python (no Streamlit, no LLM), per the src/agent/insights.py convention.
The user defines watch conditions on real loyalty metrics; this module computes
each metric's current value from an analysis snapshot dict and reports which
watches have fired. Every number comes from the analysis layer; alert messages
are templated, so nothing here can hallucinate.
"""

import json
import math
import os
import uuid
from datetime import datetime

from src.analysis.metrics import calculate_churn_risk
from src.analysis.segmentation import compute_segment_gaps

CHURN_DAYS = 30


# --- Metric registry -------------------------------------------------------

def _churn_pct(snap):
    features = snap.get("features")
    if features is None or len(features) == 0:
        return None
    at_risk, _ = calculate_churn_risk(
        features, snap.get("power_user_ids") or set(),
        snap.get("churn_days", CHURN_DAYS),
    )
    return 100.0 * len(at_risk) / len(features)


def _at_risk_power(snap):
    features = snap.get("features")
    if features is None or len(features) == 0:
        return None
    _, at_risk_power = calculate_churn_risk(
        features, snap.get("power_user_ids") or set(),
        snap.get("churn_days", CHURN_DAYS),
    )
    return float(len(at_risk_power))


def _power_cutoff(snap):
    cutoff = snap.get("cutoff")
    if cutoff is None:
        return None
    return float(cutoff)


def _top_segment_gap(snap):
    power = snap.get("power")
    regular = snap.get("regular")
    if power is None or regular is None or len(power) == 0 or len(regular) == 0:
        return None
    gaps = compute_segment_gaps(power, regular)
    if not gaps:
        return None
    return float(max(g["ratio"] for g in gaps))


WATCHABLE_METRICS = [
    {"id": "churn_pct", "label": "Churn risk (% of customers)", "unit": "%",
     "compute": _churn_pct},
    {"id": "at_risk_power", "label": "At-risk power users", "unit": "",
     "compute": _at_risk_power},
    {"id": "power_cutoff", "label": "Power-user loyalty cutoff", "unit": "",
     "compute": _power_cutoff},
    {"id": "top_segment_gap", "label": "Largest power-vs-regular gap", "unit": "x",
     "compute": _top_segment_gap},
]

_METRICS_BY_ID = {m["id"]: m for m in WATCHABLE_METRICS}

# Metrics where exceeding the threshold upward is "bad" -> red error banner.
_ERROR_WHEN_ABOVE = {"churn_pct", "at_risk_power"}


def evaluate_metric(metric_id, snapshot):
    """Current value of a metric for the snapshot, or None if unavailable."""
    m = _METRICS_BY_ID.get(metric_id)
    if m is None:
        return None
    return m["compute"](snapshot)


def _fmt(value, unit):
    """Format a metric value: whole numbers without a decimal, else 1 dp."""
    if abs(value - round(value)) < 1e-9:
        num = f"{int(round(value))}"
    else:
        num = f"{value:.1f}"
    if unit == "%":
        return f"{num}%"
    if unit == "x":
        return f"{num}x"
    return num


def _fires(direction, current, threshold):
    if direction == "above":
        return current > threshold
    if direction == "below":
        return current < threshold
    return False


def evaluate_watches(watches, snapshot):
    """Return fired alerts (in `watches` order).

    Each alert: {watch_id, metric, label, direction, threshold, current,
    severity, message}. A watch whose metric is unavailable (compute -> None)
    never fires. Severity is "error" for an upward breach of an always-bad
    metric, else "warning".
    """
    fired = []
    for watch in watches or []:
        metric_id = watch.get("metric")
        m = _METRICS_BY_ID.get(metric_id)
        if m is None:
            continue
        current = m["compute"](snapshot)
        if current is None:
            continue
        direction = watch.get("direction")
        threshold = watch.get("threshold")
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            continue
        if not _fires(direction, current, threshold):
            continue
        severity = (
            "error" if direction == "above" and metric_id in _ERROR_WHEN_ABOVE
            else "warning"
        )
        icon = "\U0001f6a8" if severity == "error" else "⚠️"
        message = (
            f"{icon} {m['label']} is {_fmt(current, m['unit'])}, "
            f"{direction} your {_fmt(threshold, m['unit'])} watch."
        )
        fired.append({
            "watch_id": watch.get("id"),
            "metric": metric_id,
            "label": m["label"],
            "direction": direction,
            "threshold": threshold,
            "current": current,
            "severity": severity,
            "message": message,
        })
    return fired


# --- Persistence (best-effort, never raises on I/O) ------------------------

STATE_DIR = ".app_state"
WATCHES_FILE = os.path.join(STATE_DIR, "watches.json")
_VALID_DIRECTIONS = ("above", "below")


def load_watches(path=WATCHES_FILE):
    """Return the stored list of watches, or [] if absent/corrupt.

    Filters out entries whose metric is no longer known so the UI/evaluator
    never sees a dangling watch.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return [
            wch for wch in data
            if isinstance(wch, dict) and wch.get("metric") in _METRICS_BY_ID
        ]
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return []


def _save(data, path):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def add_watch(metric, direction, threshold, path=WATCHES_FILE):
    """Validate and persist a new watch; return it.

    Raises ValueError on unknown metric, bad direction, or a non-finite /
    non-numeric threshold. The file write itself is best-effort.
    """
    if metric not in _METRICS_BY_ID:
        raise ValueError(f"unknown metric: {metric}")
    if direction not in _VALID_DIRECTIONS:
        raise ValueError(f"direction must be one of {_VALID_DIRECTIONS}")
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        raise ValueError("threshold must be a number")
    if not math.isfinite(threshold):
        raise ValueError("threshold must be finite")
    watch = {
        "id": uuid.uuid4().hex,
        "metric": metric,
        "direction": direction,
        "threshold": threshold,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    data = load_watches(path=path)
    data.append(watch)
    _save(data, path)
    return watch


def remove_watch(watch_id, path=WATCHES_FILE):
    """Drop a watch by id; return True if one was removed."""
    data = load_watches(path=path)
    kept = [wch for wch in data if wch.get("id") != watch_id]
    if len(kept) == len(data):
        return False
    _save(kept, path)
    return True
