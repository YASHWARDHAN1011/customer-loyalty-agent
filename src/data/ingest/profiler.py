"""
Column profiler: describe each column without exposing raw rows.

Produces, per column, a name / guessed kind / a few sample values / %null /
%unique. This profile is the ONLY thing the mapper sends to the LLM — never raw
rows — so mapping is cheap and no customer PII leaves the machine. Pure module.
"""

import pandas as pd


def _blank(series: pd.Series) -> pd.Series:
    """True where a cell is NaN or an empty/whitespace string."""
    return series.isna() | (series.astype(str).str.strip() == "")


def _guess_kind(series: pd.Series) -> str:
    """Guess numeric / date / text / empty from up to 50 non-blank samples."""
    vals = series[~_blank(series)].astype(str)
    if len(vals) == 0:
        return "empty"
    sample = vals.head(50)
    numeric = pd.to_numeric(
        sample.str.replace(r"[$,]", "", regex=True), errors="coerce")
    if numeric.notna().mean() > 0.9:
        return "numeric"
    dates = pd.to_datetime(sample, errors="coerce")
    if dates.notna().mean() > 0.7:
        return "date"
    return "text"


def profile_columns(df: pd.DataFrame) -> list:
    """Return a list of per-column profile dicts (no raw rows leak beyond samples)."""
    n = len(df)
    out = []
    for col in df.columns:
        s = df[col]
        blank = _blank(s)
        out.append({
            "name": str(col),
            "guessed_kind": _guess_kind(s),
            "samples": s[~blank].astype(str).head(5).tolist(),
            "pct_null": round(float(blank.mean()) * 100, 1) if n else 0.0,
            "pct_unique": (round(float(s[~blank].nunique()) / n * 100, 1)
                           if n else 0.0),
        })
    return out
