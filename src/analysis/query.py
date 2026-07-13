"""Grounded data-query engine (pure, Streamlit-free).

One entry point, run_query(), computes constrained aggregates / group-bys /
correlations over the canonical tables. It NEVER raises: every guard failure
returns {"ok": False, "error": <plain message>}. This is the firewall that keeps
the tool safe on arbitrary client data — the LLM picks the query, code does the
math, and every referenced column is validated against the real dataframe.
"""

import pandas as pd
from pandas.api.types import is_numeric_dtype

TABLES = ("customers", "orders", "order_items")
OPERATIONS = ("aggregate", "correlate")
AGGS = ("count", "sum", "mean", "median", "min", "max")
_NUMERIC_AGGS = ("sum", "mean", "median", "min", "max")
FILTER_OPS = (">", "<", ">=", "<=", "==", "between")
_HARD_LIMIT = 50


def _err(msg):
    return {"ok": False, "error": msg}


def _cols_msg(df):
    return "Available columns: " + ", ".join(map(str, df.columns)) + "."


def _resolve_table(tables, table):
    """Return (df, None) on success or (None, error_dict) on any problem."""
    if table not in TABLES:
        return None, _err(f"No such table '{table}'. Choose one of: {', '.join(TABLES)}.")
    df = (tables or {}).get(table)
    if df is None:
        if table == "order_items":
            return None, _err("That needs product-level data, which isn't loaded for this dataset.")
        return None, _err(f"The '{table}' table isn't loaded for this dataset.")
    if len(df) == 0:
        return None, _err(f"The '{table}' table has no rows.")
    return df, None


def _coerce(df, col, raw):
    """Coerce a raw filter value to the column's type. Returns (value, None) or (None, error)."""
    if is_numeric_dtype(df[col]):
        try:
            return float(raw), None
        except (TypeError, ValueError):
            return None, _err(f"Filter value '{raw}' is not numeric, but column '{col}' is.")
    return str(raw), None


def _apply_filter(df, column, op, value, value2):
    """Apply one filter condition. Returns (df, None) or (None, error). No filter -> unchanged."""
    if not column and not op:
        return df, None
    if not column or not op:
        return None, _err("A filter needs both a column and an operator.")
    if column not in df.columns:
        return None, _err(f"No such column '{column}'. {_cols_msg(df)}")
    if op not in FILTER_OPS:
        return None, _err(f"No such filter operator '{op}'. Choose one of: {', '.join(FILTER_OPS)}.")
    if op == "between":
        if value in ("", None) or value2 in ("", None):
            return None, _err("'between' needs two bounds (filter_value and filter_value2).")
        lo, err = _coerce(df, column, value)
        if err:
            return None, err
        hi, err = _coerce(df, column, value2)
        if err:
            return None, err
        return df[(df[column] >= lo) & (df[column] <= hi)], None
    val, err = _coerce(df, column, value)
    if err:
        return None, err
    if op == "==":
        return df[df[column] == val], None
    if not is_numeric_dtype(df[column]):
        return None, _err(f"Operator '{op}' needs a numeric column, but '{column}' is text.")
    cmp = {">": df[column] > val, "<": df[column] < val,
           ">=": df[column] >= val, "<=": df[column] <= val}[op]
    return df[cmp], None


def _compute(series, agg):
    if agg == "count":
        return int(series.count())
    return float(getattr(series, agg)())


def _aggregate(df, metric, agg, group_by, limit):
    if agg not in AGGS:
        return _err(f"No such aggregation '{agg}'. Choose one of: {', '.join(AGGS)}.")
    if not metric:
        return _err("An aggregate needs a metric column.")
    if metric not in df.columns:
        return _err(f"No such column '{metric}'. {_cols_msg(df)}")
    if agg in _NUMERIC_AGGS and not is_numeric_dtype(df[metric]):
        return _err(f"'{agg}' needs a numeric column, but '{metric}' is text. Use 'count' instead.")
    if len(df) == 0:
        return _err("No rows matched — nothing to aggregate.")
    if group_by:
        if group_by not in df.columns:
            return _err(f"No such column '{group_by}'. {_cols_msg(df)}")
        grouped = df.groupby(group_by)[metric].agg(agg).sort_values(ascending=False)
        cap = max(1, min(int(limit or 20), _HARD_LIMIT))
        truncated = len(grouped) > cap
        rows = [{"group": str(k),
                 "value": (int(v) if agg == "count" else round(float(v), 4))}
                for k, v in grouped.head(cap).items()]
        return {"ok": True, "kind": "table", "rows": rows,
                "n_groups": int(len(grouped)), "truncated": truncated}
    value = _compute(df[metric], agg)
    return {"ok": True, "kind": "scalar",
            "value": (round(value, 4) if isinstance(value, float) else value),
            "n": int(len(df))}


def _correlate(df, column_a, column_b):
    for c in (column_a, column_b):
        if not c:
            return _err("Correlation needs two columns (column_a and column_b).")
        if c not in df.columns:
            return _err(f"No such column '{c}'. {_cols_msg(df)}")
        if not is_numeric_dtype(df[c]):
            return _err(f"Correlation needs numeric columns, but '{c}' is text.")
    pair = df[[column_a, column_b]].dropna()
    if len(pair) < 2:
        return _err("Not enough overlapping numeric values to correlate (need at least 2).")
    r = pair[column_a].corr(pair[column_b])
    if pd.isna(r):
        return _err("Correlation is undefined (one column has no variation).")
    return {"ok": True, "kind": "correlation", "r": round(float(r), 4), "n": int(len(pair))}


def run_query(tables, *, table="customers", operation="aggregate",
              metric="", agg="mean", group_by="",
              filter_column="", filter_op="", filter_value="", filter_value2="",
              column_a="", column_b="", limit=20):
    """Constrained aggregate / group-by / correlation over the canonical tables.

    Returns a plain result dict and NEVER raises. On success the dict carries the
    resolved `query` echo (Phase-9-ready); on any guard failure it is
    {"ok": False, "error": <plain message>}.
    """
    query = {"table": table, "operation": operation, "metric": metric, "agg": agg,
             "group_by": group_by, "filter_column": filter_column,
             "filter_op": filter_op, "filter_value": filter_value,
             "filter_value2": filter_value2, "column_a": column_a,
             "column_b": column_b, "limit": limit}
    try:
        if operation not in OPERATIONS:
            return _err(f"No such operation '{operation}'. Choose one of: {', '.join(OPERATIONS)}.")
        df, err = _resolve_table(tables, table)
        if err:
            return err
        df, err = _apply_filter(df, filter_column, filter_op, filter_value, filter_value2)
        if err:
            return err
        result = (_aggregate(df, metric, agg, group_by, limit)
                  if operation == "aggregate"
                  else _correlate(df, column_a, column_b))
        if result.get("ok"):
            result["query"] = query
        return result
    except Exception as e:  # belt-and-suspenders: the tool must never crash the chat
        return _err(f"Query failed: {type(e).__name__}: {e}")
