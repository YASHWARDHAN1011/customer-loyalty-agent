"""
File reader: bytes -> pandas DataFrame.

Reads CSV or Excel robustly. Every cell is read as a STRING (dtype=str) so raw
amounts ("$1,234.50"), leading-zero ids, and ambiguous dates survive verbatim to
the validator, which is the single place that coerces types. Pure / no Streamlit.
"""

import csv

import pandas as pd

# UTF-16 is handled by BOM detection above; latin-1 is the last-resort fallback.
_ENCODINGS = ["utf-8"]


def sniff_encoding(raw: bytes) -> str:
    """Pick an encoding from a BOM, else the first that decodes cleanly."""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for enc in _ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"   # always decodes any byte sequence; last-resort fallback


def sniff_delimiter(sample: str) -> str:
    """Guess the CSV delimiter; default to comma when the sniffer is unsure."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def read_table(source, sheet=0, *, filename: str = None) -> pd.DataFrame:
    """Read a CSV or Excel source into an all-string DataFrame.

    `source` may be a filesystem path (str) or a binary file-like object such as
    a Streamlit UploadedFile. File type is inferred from `filename`, else the
    source's own name/path extension. CSV encoding + delimiter are sniffed.
    """
    from io import BytesIO, StringIO

    name = filename or (source if isinstance(source, str)
                        else getattr(source, "name", "")) or ""
    is_excel = str(name).lower().endswith((".xlsx", ".xls"))

    if isinstance(source, str):
        with open(source, "rb") as f:
            raw = f.read()
    else:
        raw = source.read()
        if hasattr(source, "seek"):
            try:
                source.seek(0)
            except Exception:
                pass

    if is_excel:
        return pd.read_excel(BytesIO(raw), sheet_name=sheet, dtype=str)
    text = raw.decode(sniff_encoding(raw))
    sep = sniff_delimiter(text[:4096])
    return pd.read_csv(StringIO(text), sep=sep, dtype=str)
