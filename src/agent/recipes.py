"""Recipes — saved, replayable grounded-query actions.

Pure Python (no Streamlit, no LLM), same best-effort JSON-store shape as
`watches.py`. A recipe stores only the `run_grounded_query` argument dict plus a
name — never raw data, numbers, or code. Replaying a recipe re-runs the
deterministic Phase-8 engine on the current dataset, so numbers are always fresh
and the trust invariant holds.
"""

import json
import os
import uuid
from datetime import datetime

STATE_DIR = ".app_state"
RECIPES_FILE = os.path.join(STATE_DIR, "recipes.json")


def describe_query(query):
    """A deterministic human label for a grounded-query arg dict (no data access)."""
    q = query or {}
    table = q.get("table", "")

    def sp(s):
        return str(s).replace("_", " ")

    if q.get("operation") == "correlate":
        base = f"Correlation: {sp(q.get('column_a', ''))} vs {sp(q.get('column_b', ''))}"
    else:
        agg = str(q.get("agg", "")).title()
        metric = sp(q.get("metric", ""))
        group_by = q.get("group_by", "")
        base = (f"{agg} of {metric} by {sp(group_by)}" if group_by
                else f"{agg} of {metric}")
    if table:
        base += f" ({table})"
    if q.get("filter_column") and q.get("filter_op"):
        base += ", filtered"
    return base


# NOTE: path defaults to None and resolves to the MODULE-LEVEL RECIPES_FILE at
# call time (not as a bound default). This lets a test monkeypatch
# `recipes.RECIPES_FILE` and have the UI (which calls with no path) pick it up —
# a plain `path=RECIPES_FILE` default would bind once at def time and ignore the
# monkeypatch.
def load_recipes(path=None):
    """Stored recipes, or [] if absent/corrupt. Drops entries without a dict query."""
    path = path or RECIPES_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return [r for r in data
                if isinstance(r, dict) and isinstance(r.get("query"), dict)]
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return []


def _save(data, path):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def add_recipe(name, query, path=None):
    """Persist a recipe; a blank name falls back to the derived label. Returns it."""
    path = path or RECIPES_FILE
    name = (name or "").strip() or describe_query(query)
    rec = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "query": dict(query or {}),
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    data = load_recipes(path=path)
    data.append(rec)
    _save(data, path)
    return rec


def remove_recipe(recipe_id, path=None):
    """Drop a recipe by id; return True if one was removed."""
    path = path or RECIPES_FILE
    data = load_recipes(path=path)
    kept = [r for r in data if r.get("id") != recipe_id]
    if len(kept) == len(data):
        return False
    _save(kept, path)
    return True
