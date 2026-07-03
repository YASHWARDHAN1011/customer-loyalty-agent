"""
Mapping persistence — recipe only, never raw rows.

Saves the confirmed column-mapping recipe keyed by a dataset FINGERPRINT (a hash
of the sorted, normalised header set). On re-upload of a same-shaped file the app
can auto-apply the saved mapping and skip the LLM/confirm step. No customer data
is ever written — only headers (hashed) and the field->column recipe. Best-effort
JSON store like the other `.app_state/*.json` stores: never raises.
"""

import hashlib
import json
import os

_STORE = os.path.join(".app_state", "mappings.json")


def fingerprint(headers) -> str:
    """Stable 16-char hash of the normalised (sorted, lowercased, trimmed) header
    set — order/case/whitespace insensitive."""
    joined = "|".join(sorted(str(h).strip().lower() for h in headers))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _load_all(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_mapping(headers, mapping: dict, path: str = _STORE) -> str:
    """Persist `mapping` under this header set's fingerprint. Returns the
    fingerprint. Best-effort: swallows any I/O error."""
    fp = fingerprint(headers)
    data = _load_all(path)
    data[fp] = {"mapping": mapping}
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
    return fp


def load_mapping(headers, path: str = _STORE):
    """Return the saved mapping for this header set's fingerprint, or None."""
    return _load_all(path).get(fingerprint(headers), {}).get("mapping")
