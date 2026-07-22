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
                                "receipt", "reference", "purchase"]},
    "order_date":  {"required": True,
                    "aliases": ["date", "ordered", "timestamp",
                                "created", "placed", "purchasedate"]},
    "order_amount": {"required": True,
                     "aliases": ["amount", "total", "revenue", "price", "value",
                                 "spend", "sales", "gross", "paid"]},
    "product":  {"required": False,
                 "aliases": ["product", "item", "sku", "article", "productname"]},
    "category": {"required": False,
                 "aliases": ["category", "department", "dept", "aisle",
                             "class", "group"]},
    "quantity": {"required": False,
                 "aliases": ["quantity", "qty", "count", "units", "number"]},
    "order_currency": {"required": False,
                       "aliases": ["currency", "curr", "ccy", "iso_currency",
                                   "currency_code"]},
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
    unmatched fields map to None.

    Assignment is greedy by best GLOBAL score: all (field, header) pairs scoring
    at or above the threshold are ranked by descending score, and each is taken
    only if neither its field nor its header is already claimed. This beats
    greedy-in-field-order, which could hand a required field's obvious column to
    an earlier, weaker match. Ties break deterministically by field order then
    header order (stable for mapping persistence).
    """
    field_order = {field: i for i, field in enumerate(CANONICAL_FIELDS)}
    headers = [p["name"] for p in profile]
    mapping = {field: None for field in CANONICAL_FIELDS}

    candidates = []
    for field, meta in CANONICAL_FIELDS.items():
        for h in headers:
            s = _score(h, field, meta["aliases"])
            if s >= _MATCH_THRESHOLD:
                candidates.append((s, field, h))

    # Best global score first; deterministic tie-break by field then header.
    candidates.sort(key=lambda c: (-c[0], field_order[c[1]], headers.index(c[2])))

    assigned_fields = set()
    used_headers = set()
    for score, field, header in candidates:
        if field in assigned_fields or header in used_headers:
            continue
        mapping[field] = header
        assigned_fields.add(field)
        used_headers.add(header)
    return mapping


def _build_prompt(profile: list) -> str:
    """Render the column profile (never raw rows) into a mapping request."""
    lines = ["You map a client's spreadsheet columns onto a fixed schema.",
             "Canonical fields (map each to ONE source column name, or omit it):",
             "  required: customer_id, order_id, order_date, order_amount",
             "  optional: product, category, quantity",
             "",
             "Source columns (name | kind | %null | %unique | samples):"]
    for p in profile:
        lines.append(
            f"  {p['name']} | {p.get('guessed_kind', '?')} | "
            f"{p.get('pct_null', '?')}% null | {p.get('pct_unique', '?')}% unique "
            f"| {p.get('samples', [])}")
    lines += ["",
              "Reply with ONLY a JSON object mapping canonical field -> source "
              "column name. Use exact source names. Omit fields with no match."]
    return "\n".join(lines)


def _parse_llm_mapping(raw: str, headers: list) -> dict:
    """Extract the JSON object and keep only real fields mapped to real headers."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in LLM reply")
    obj = json.loads(raw[start:end + 1])
    header_set = set(headers)
    mapping = {f: None for f in CANONICAL_FIELDS}
    for field, col in obj.items():
        if field in CANONICAL_FIELDS and isinstance(col, str) and col in header_set:
            mapping[field] = col
    return mapping


def propose_mapping(profile: list, generate_fn=None) -> dict:
    """Propose a mapping. Returns {'mapping', 'source'} where source is 'llm' or
    'fuzzy'. Tries the injected `generate_fn(prompt)->str` first; on ANY failure
    (no fn, exception, unparseable/empty result) falls back to `fuzzy_map`."""
    headers = [p["name"] for p in profile]
    if generate_fn is not None:
        try:
            mapping = _parse_llm_mapping(generate_fn(_build_prompt(profile)), headers)
            if any(mapping.get(f) for f in CANONICAL_FIELDS
                   if CANONICAL_FIELDS[f]["required"]):
                return {"mapping": mapping, "source": "llm"}
        except Exception:
            pass
    return {"mapping": fuzzy_map(profile), "source": "fuzzy"}
