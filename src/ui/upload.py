"""Upload + mapping-confirm flow.

Pure orchestration (`prepare_upload`, `apply_mapping`) over the Phase-3 ingestion
backend, plus (in a later task) thin Streamlit render functions. The pure
functions take an injected `generate_fn` and an explicit `store_path`, so they are
unit-testable with no Streamlit and no network.
"""

import streamlit as st

from src.data.ingest.profiler import profile_columns
from src.data.ingest.mapper import propose_mapping, CANONICAL_FIELDS  # noqa: F401
from src.data.ingest.builder import build_canonical
from src.data.ingest.mapping_store import (
    load_mapping, save_mapping, _STORE,
)
from src.data.ingest.reader import read_table
from src.data.app_data import features_from_matrix, load_demo_app_data
from src.ui.dataset import set_active_dataset


def prepare_upload(df, generate_fn, store_path=_STORE):
    """Profile the uploaded frame and resolve its column mapping.

    Returns a dict: {stage, mapping, source, profile, saved}.
    - If a saved recipe matches the header fingerprint -> stage "build",
      saved=True (fast path, skip confirm).
    - Else propose a mapping (LLM via generate_fn, deterministic fuzzy fallback
      inside propose_mapping) -> stage "confirm", saved=False.
    """
    profile = profile_columns(df)
    headers = list(df.columns)
    saved = load_mapping(headers, path=store_path)
    if saved:
        return {"stage": "build", "mapping": saved, "source": "saved",
                "profile": profile, "saved": True}
    proposed = propose_mapping(profile, generate_fn=generate_fn)
    return {"stage": "confirm", "mapping": proposed["mapping"],
            "source": proposed["source"], "profile": profile, "saved": False}


def apply_mapping(df, mapping, store_path=_STORE, dayfirst=None, grain=None):
    """Validate + build canonical for a confirmed mapping.

    `dayfirst`/`grain` are optional operator overrides (None = auto). On success,
    persists the mapping recipe for next time. Returns the builder result dict
    {ok, errors, warnings, orders, order_items, matrix}.
    """
    result = build_canonical(df, mapping, dayfirst=dayfirst, grain=grain)
    if result["ok"]:
        save_mapping(list(df.columns), mapping, path=store_path)
    return result


_REQUIRED = [f for f, m in CANONICAL_FIELDS.items() if m["required"]]
_OPTIONAL = [f for f, m in CANONICAL_FIELDS.items() if not m["required"]]
_FIELD_LABEL = {
    "customer_id": "Customer ID", "order_id": "Order ID",
    "order_date": "Order date", "order_amount": "Order amount",
    "product": "Product (optional)", "category": "Category (optional)",
    "quantity": "Quantity (optional)", "order_currency": "Currency (optional)",
}


# Session keys owned by an in-progress upload (confirm screen state).
_UPLOAD_KEYS = ("upload_stage", "upload_df", "upload_filename", "upload_mapping",
                "upload_profile", "upload_saved", "upload_errors", "upload_warnings",
                "date_locale_choice", "order_grain_choice")


def _clear_upload_state(*, reset_uploader=False):
    """Drop all in-progress upload state (confirm keys + per-field selectbox keys).

    `reset_uploader=True` also bumps the file_uploader nonce so Streamlit discards
    the retained file (needed for Cancel / Back-to-demo so the guard won't re-fire).
    """
    for k in _UPLOAD_KEYS:
        st.session_state.pop(k, None)
    for k in [k for k in list(st.session_state) if k.startswith("map_")]:
        st.session_state.pop(k, None)
    if reset_uploader:
        st.session_state["uploader_nonce"] = st.session_state.get("uploader_nonce", 0) + 1


def _mapping_generate_fn(prompt):
    """Adapter: the mapper calls generate_fn(prompt)->str; wrap the app's generate."""
    from src.agent.caller import generate
    return generate(prompt, system_instruction="You map spreadsheet columns to a schema.")


def render_upload_section(run_analysis):
    """Sidebar 'Your data' section: active-dataset indicator, uploader, back-to-demo."""
    st.markdown("### 📁 Your data")
    source = st.session_state.get("dataset_source", "demo")
    label = st.session_state.get("dataset_label", "Instacart")
    counts = st.session_state.get("dataset_counts", {})
    if source == "demo":
        st.caption(f"📊 Demo data · {label}")
    else:
        st.success(f"📊 Your data · {label}")
        st.caption(f"{counts.get('customers', 0):,} customers · {counts.get('orders', 0):,} orders")
        if st.button("↩ Back to demo data", use_container_width=True):
            o, it, f, av, al = load_demo_app_data()
            set_active_dataset(st.session_state, orders=o, order_items=it, features=f,
                               available=av, active_levers=al, label="Instacart", source="demo")
            _clear_upload_state(reset_uploader=True)
            run_analysis(st.session_state["top_pct"])
            st.rerun()

    up = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx", "xls"],
                          key=f"dataset_uploader_{st.session_state.get('uploader_nonce', 0)}")
    if up is not None and st.session_state.get("upload_filename") != up.name:
        for k in [k for k in list(st.session_state) if k.startswith("map_")]:
            st.session_state.pop(k, None)
        try:
            df = read_table(up, filename=up.name)
        except Exception as e:
            st.error(f"Couldn't read that file: {e}")
            return
        prep = prepare_upload(df, generate_fn=_mapping_generate_fn)
        st.session_state["upload_df"] = df
        st.session_state["upload_filename"] = up.name
        st.session_state["upload_mapping"] = prep["mapping"]
        st.session_state["upload_profile"] = prep["profile"]
        st.session_state["upload_saved"] = prep["saved"]
        if prep["stage"] == "build":
            _build_and_activate(up.name, df, prep["mapping"], run_analysis)
        else:
            st.session_state["upload_stage"] = "confirm"
        st.rerun()


def _build_and_activate(filename, df, mapping, run_analysis, *, dayfirst=None, grain=None):
    """Run apply_mapping; on success swap the active dataset + analyze."""
    result = apply_mapping(df, mapping, dayfirst=dayfirst, grain=grain)
    if not result["ok"]:
        st.session_state["upload_stage"] = "confirm"
        st.session_state["upload_errors"] = result["errors"]
        return
    feats, available, active = features_from_matrix(result["matrix"])
    set_active_dataset(st.session_state, orders=result["orders"],
                       order_items=result["order_items"], features=feats,
                       available=available, active_levers=active,
                       label=filename, source="upload")
    warnings = result.get("warnings", [])
    _clear_upload_state()
    st.session_state["upload_warnings"] = warnings
    run_analysis(st.session_state["top_pct"])


def render_confirm_gate(run_analysis):
    """Main-area confirm screen. Renders only when upload_stage == 'confirm'.
    Returns True if the gate rendered (caller should skip the tabs)."""
    if st.session_state.get("upload_stage") != "confirm":
        return False
    df = st.session_state["upload_df"]
    mapping = st.session_state["upload_mapping"]
    columns = list(df.columns)
    fname = st.session_state.get("upload_filename", "your file")

    st.markdown(f"## 📋 Confirm column mapping — `{fname}`")
    if st.session_state.get("upload_saved"):
        st.info("Using your saved mapping for this file. Review below or confirm.")
    st.caption("Tell us which of your columns is which. We check the data before "
               "running anything.")
    errs = st.session_state.pop("upload_errors", [])
    for e in errs:
        st.error(e)

    chosen = {}
    none_opt = "— none —"
    for field in _REQUIRED + _OPTIONAL:
        opts = columns if field in _REQUIRED else [none_opt] + columns
        cur = mapping.get(field)
        idx = opts.index(cur) if cur in opts else 0
        chosen[field] = st.selectbox(_FIELD_LABEL[field], opts, index=idx,
                                     key=f"map_{field}")
    chosen = {f: (None if v == none_opt else v) for f, v in chosen.items()}

    st.markdown("**Preview** (first rows of the columns you chose):")
    picked = [c for c in chosen.values() if c]
    if picked:
        st.dataframe(df[picked].head(5), use_container_width=True)

    # --- Locale & grain: show what build will do, let the operator override. ---
    from src.data.ingest.validator import _infer_dayfirst
    from src.data.ingest.builder import detect_grain

    date_col = chosen.get("order_date")
    if date_col and date_col in df.columns:
        inferred_df, ambiguous = _infer_dayfirst(df[date_col])
    else:
        inferred_df, ambiguous = True, False
    if ambiguous:
        detected_locale = "ambiguous — assuming Day-first (DD/MM/YYYY)"
    elif inferred_df:
        detected_locale = "Day-first (DD/MM/YYYY)"
    else:
        detected_locale = "Month-first (MM/DD/YYYY)"
    st.radio("Date format",
             ["Auto", "Day-first (DD/MM/YYYY)", "Month-first (MM/DD/YYYY)"],
             key="date_locale_choice")
    st.caption(f"Detected: {detected_locale}")

    detected_grain = detect_grain(df, chosen)
    grain_label = ("line-item — lines will be summed per order"
                   if detected_grain == "line_item" else "order-level (one row per order)")
    st.radio("Order grain",
             ["Auto", "Line-item — sum lines per order", "Order-level — one row per order"],
             key="order_grain_choice")
    st.caption(f"Detected: {grain_label}")

    def _dayfirst_override():
        c = st.session_state.get("date_locale_choice", "Auto")
        if c.startswith("Day-first"):
            return True
        if c.startswith("Month-first"):
            return False
        return None

    def _grain_override():
        c = st.session_state.get("order_grain_choice", "Auto")
        if c.startswith("Line-item"):
            return "line_item"
        if c.startswith("Order-level"):
            return "order_level"
        return None

    c1, c2 = st.columns(2)
    if c1.button("✅ Confirm & analyze", type="primary", use_container_width=True):
        _build_and_activate(fname, df, chosen, run_analysis,
                            dayfirst=_dayfirst_override(), grain=_grain_override())
        st.rerun()
    if c2.button("Cancel", use_container_width=True):
        _clear_upload_state(reset_uploader=True)
        st.rerun()
    return True


def render_upload_notices():
    """Show any pending upload build-warnings once (best-effort), then clear them."""
    warnings = st.session_state.pop("upload_warnings", None)
    if warnings:
        for w in warnings:
            st.warning(f"⚠️ {w}")
