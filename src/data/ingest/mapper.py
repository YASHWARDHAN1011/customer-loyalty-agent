"""
Column mapper: propose which upload column maps to each canonical field.

`propose_mapping` asks an injected LLM `generate_fn`; on any failure (or no
generate_fn) it falls back to `fuzzy_map`, a deterministic header matcher, so
ingestion works with zero LLM. Any LLM-proposed value that is not a real column
name is dropped — the mapper never trusts a hallucinated header. Pure module: no
Streamlit / no caller import; the app injects the LLM wrapper in a later phase.
"""

import json
import re
from difflib import SequenceMatcher

# Canonical target fields. `required` ones must be mapped before validation runs;
# `aliases` seed the fuzzy matcher. Order matters: earlier fields claim a header
# first (a header is used by at most one field).
CANONICAL_FIELDS = {
    "customer_id": {"required": True,
                    "aliases": ["customer", "cust", "user", "client", "buyer",
                                "member", "account", "email"]},
    "order_id":    {"required": True,
                    "aliases": ["order", "transaction", "txn", "invoice",
                                "receipt", "reference"]},
    "order_date":  {"required": True,
                    "aliases": ["date", "ordered", "purchase", "timestamp",
                                "created", "placed"]},
    "order_amount": {"required": True,
                     "aliases": ["amount", "total", "revenue", "price", "value",
                                 "spend", "sales", "gross", "paid", "aud"]},
    "product":  {"required": False,
                 "aliases": ["product", "item", "sku", "article", "name"]},
    "category": {"required": False,
                 "aliases": ["category", "department", "dept", "aisle", "type",
                             "class", "group"]},
    "quantity": {"required": False,
                 "aliases": ["quantity", "qty", "count", "units", "number"]},
}

_MATCH_THRESHOLD = 0.5


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _score(header: str, field: str, aliases: list) -> float:
    """Best similarity of a header to a canonical field name or its aliases."""
    h = _norm(header)
    best = 0.0
    for target in [field.replace("_", "")] + aliases:
        t = _norm(target)
        if not t or not h:
            continue
        if h == t:
            return 1.0
        if t in h or h in t:
            best = max(best, 0.8)
        best = max(best, SequenceMatcher(None, h, t).ratio())
    return best


def fuzzy_map(profile: list) -> dict:
    """Deterministic header->canonical mapping. `profile` is a list of column
    dicts (only each dict's `name` is used). Every canonical field is a key;
    unmatched fields map to None."""
    headers = [p["name"] for p in profile]
    mapping = {}
    used = set()
    for field, meta in CANONICAL_FIELDS.items():
        best_header, best_score = None, 0.0
        for h in headers:
            if h in used:
                continue
            s = _score(h, field, meta["aliases"])
            if s > best_score:
                best_header, best_score = h, s
        if best_header is not None and best_score >= _MATCH_THRESHOLD:
            mapping[field] = best_header
            used.add(best_header)
        else:
            mapping[field] = None
    return mapping
