"""Upload + mapping-confirm flow.

Pure orchestration (`prepare_upload`, `apply_mapping`) over the Phase-3 ingestion
backend, plus (in a later task) thin Streamlit render functions. The pure
functions take an injected `generate_fn` and an explicit `store_path`, so they are
unit-testable with no Streamlit and no network.
"""

from src.data.ingest.profiler import profile_columns
from src.data.ingest.mapper import propose_mapping, CANONICAL_FIELDS  # noqa: F401
from src.data.ingest.builder import build_canonical
from src.data.ingest.mapping_store import (
    load_mapping, save_mapping, _STORE,
)


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


def apply_mapping(df, mapping, store_path=_STORE):
    """Validate + build canonical for a confirmed mapping.

    On success, persists the mapping recipe for next time. Returns the builder
    result dict {ok, errors, warnings, orders, order_items, matrix}.
    """
    result = build_canonical(df, mapping)
    if result["ok"]:
        save_mapping(list(df.columns), mapping, path=store_path)
    return result
