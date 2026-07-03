"""Standalone tests for src/data/ingest/. No network, tiny fixtures."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def test_reader_csv_comma(tmpdir):
    from src.data.ingest.reader import read_table
    p = os.path.join(tmpdir, "a.csv")
    with open(p, "w", encoding="utf-8") as f:
        f.write("cust,order,amt\n1,100,9.50\n1,101,3.00\n")
    df = read_table(p)
    check("csv rows read", len(df) == 2)
    check("csv headers read", list(df.columns) == ["cust", "order", "amt"])
    check("csv cells are strings", df["amt"].iloc[0] == "9.50")


def test_reader_semicolon_and_utf16(tmpdir):
    from src.data.ingest.reader import read_table
    p = os.path.join(tmpdir, "b.csv")
    with open(p, "w", encoding="utf-16") as f:
        f.write("cust;order;amt\n1;100;9,50\n")
    df = read_table(p)
    check("semicolon delimiter sniffed", list(df.columns) == ["cust", "order", "amt"])
    check("utf-16 decoded", df["amt"].iloc[0] == "9,50")


def test_profiler():
    from src.data.ingest.profiler import profile_columns
    df = pd.DataFrame({
        "Cust Ref": ["1", "2", "2", "3"],
        "Total (AUD)": ["$9.50", "$3.00", "", "12"],
        "When": ["2024-01-02", "2024-01-05", "2024-02-01", "bad"],
        "Note": ["a", "b", "c", "d"],
    })
    profs = profile_columns(df)
    by = {p["name"]: p for p in profs}
    check("all columns profiled", set(by) == {"Cust Ref", "Total (AUD)", "When", "Note"})
    check("amount guessed numeric", by["Total (AUD)"]["guessed_kind"] == "numeric")
    check("date guessed date", by["When"]["guessed_kind"] == "date")
    check("note guessed text", by["Note"]["guessed_kind"] == "text")
    check("null pct computed", by["Total (AUD)"]["pct_null"] == 25.0)
    check("samples are strings", all(isinstance(s, str) for s in by["Note"]["samples"]))


def test_fuzzy_map():
    from src.data.ingest.mapper import fuzzy_map
    profile = [
        {"name": "Customer Ref"}, {"name": "Order No"},
        {"name": "Order Date"}, {"name": "Total (AUD)"},
        {"name": "Product Name"}, {"name": "Dept"},
    ]
    m = fuzzy_map(profile)
    check("customer_id mapped", m["customer_id"] == "Customer Ref")
    check("order_id mapped", m["order_id"] == "Order No")
    check("order_date mapped", m["order_date"] == "Order Date")
    check("order_amount mapped", m["order_amount"] == "Total (AUD)")
    check("product mapped", m["product"] == "Product Name")
    check("category mapped", m["category"] == "Dept")
    check("absent optional is None", m["quantity"] is None)


def test_fuzzy_map_no_match():
    from src.data.ingest.mapper import fuzzy_map
    m = fuzzy_map([{"name": "xyz"}, {"name": "foo"}])
    check("unmatched required is None", m["customer_id"] is None)


def test_fuzzy_map_global_best():
    # Header set where greedy-in-field-order used to mis-map: "Purchase ID"
    # must NOT steal order_date, and order_amount must keep its column.
    from src.data.ingest.mapper import fuzzy_map
    profile = [{"name": h} for h in
               ["Member ID", "Purchase ID", "Purchase Date",
                "Purchase Total", "Item", "Qty"]]
    m = fuzzy_map(profile)
    check("customer mapped to member", m["customer_id"] == "Member ID")
    check("order_id not lost", m["order_id"] == "Purchase ID")
    check("order_date is the date column", m["order_date"] == "Purchase Date")
    check("order_amount is the total column", m["order_amount"] == "Purchase Total")
    check("product mapped to item", m["product"] == "Item")
    check("quantity mapped to qty", m["quantity"] == "Qty")


def test_propose_mapping_llm():
    from src.data.ingest.mapper import propose_mapping
    profile = [{"name": "Cust Ref", "guessed_kind": "text", "samples": ["1"],
                "pct_null": 0.0, "pct_unique": 90.0}]

    def fake_gen(prompt):
        check("prompt carries header", "Cust Ref" in prompt)
        check("prompt has no raw-row dump", "SELECT" not in prompt)
        return '{"customer_id": "Cust Ref", "order_id": "Ghost Col"}'

    res = propose_mapping(profile, generate_fn=fake_gen)
    check("llm source", res["source"] == "llm")
    check("valid header kept", res["mapping"]["customer_id"] == "Cust Ref")
    check("hallucinated header dropped", res["mapping"].get("order_id") is None)


def test_propose_mapping_fallback():
    from src.data.ingest.mapper import propose_mapping
    profile = [{"name": "Customer Ref"}, {"name": "Order No"},
               {"name": "Order Date"}, {"name": "Total"}]

    def broken_gen(prompt):
        raise RuntimeError("all keys exhausted")

    res = propose_mapping(profile, generate_fn=broken_gen)
    check("falls back to fuzzy", res["source"] == "fuzzy")
    check("fuzzy still maps required", res["mapping"]["customer_id"] == "Customer Ref")

    res2 = propose_mapping(profile, generate_fn=None)
    check("no generate_fn -> fuzzy", res2["source"] == "fuzzy")


def test_propose_mapping_nested_values():
    # Some LLMs wrap each answer as {"column":..., "confidence":...} or return a
    # number. Non-string values must be ignored, not crash — and with no usable
    # required field mapped, propose_mapping falls back to fuzzy.
    from src.data.ingest.mapper import propose_mapping, _parse_llm_mapping
    profile = [{"name": "Cust Ref"}, {"name": "Order No"},
               {"name": "Order Date"}, {"name": "Total"}]

    parsed = _parse_llm_mapping(
        '{"customer_id": {"column": "Cust Ref", "confidence": 0.9}, "order_id": 3}',
        ["Cust Ref", "Order No", "Order Date", "Total"])
    check("nested value ignored", parsed["customer_id"] is None)
    check("numeric value ignored", parsed["order_id"] is None)

    def nested_gen(prompt):
        return '{"customer_id": {"column": "Cust Ref"}}'

    res = propose_mapping(profile, generate_fn=nested_gen)
    check("nested-only reply falls back to fuzzy", res["source"] == "fuzzy")
    check("fuzzy recovered customer_id", res["mapping"]["customer_id"] == "Cust Ref")


def _good_df():
    return pd.DataFrame({
        "cust": ["1", "1", "2"],
        "ord":  ["100", "101", "200"],
        "when": ["2024-01-02", "2024-01-20", "2024-01-05"],
        "amt":  ["$9.50", "1,200.00", "40"],
    })

_GOOD_MAP = {"customer_id": "cust", "order_id": "ord",
             "order_date": "when", "order_amount": "amt",
             "product": None, "category": None, "quantity": None}


def test_validate_happy():
    from src.data.ingest.validator import validate
    r = validate(_good_df(), _GOOD_MAP)
    check("valid input ok", r.ok is True)
    check("no errors", r.errors == [])
    check("dollar+comma amount cleaned", float(r.orders["order_amount"].iloc[1]) == 1200.0)
    check("dates parsed", str(r.orders["order_date"].dtype).startswith("datetime"))
    check("no items when unmapped", r.order_items is None)


def test_validate_missing_required():
    from src.data.ingest.validator import validate
    m = dict(_GOOD_MAP, order_amount=None)
    r = validate(_good_df(), m)
    check("rejects missing required", r.ok is False)
    check("names the missing field", any("order_amount" in e for e in r.errors))
    check("message is human, not a trace", all("Traceback" not in e for e in r.errors))


def test_validate_bad_dates():
    from src.data.ingest.validator import validate
    df = _good_df(); df["when"] = ["nope", "nope", "nope"]
    r = validate(df, _GOOD_MAP)
    check("rejects unparseable dates", r.ok is False)
    check("date error mentions column", any("when" in e for e in r.errors))


def test_validate_negative_amount_warns():
    from src.data.ingest.validator import validate
    df = _good_df(); df["amt"] = ["-5", "10", "20"]
    r = validate(df, _GOOD_MAP)
    check("negatives do not hard-fail", r.ok is True)
    check("negative produces a warning", any("negative" in w.lower() for w in r.warnings))
    check("negative clipped to 0", float(r.orders["order_amount"].iloc[0]) == 0.0)


def test_validate_builds_items():
    from src.data.ingest.validator import validate
    df = _good_df(); df["prod"] = ["milk", "eggs", "soda"]; df["dept"] = ["dairy", "dairy", "drinks"]
    m = dict(_GOOD_MAP, product="prod", category="dept")
    r = validate(df, m)
    check("items built when mapped", r.order_items is not None)
    check("items have canonical cols",
          set(["order_id", "product", "category", "quantity"]).issubset(r.order_items.columns))
    check("quantity defaults to 1", int(r.order_items["quantity"].iloc[0]) == 1)


def test_validate_empty_file():
    from src.data.ingest.validator import validate
    r = validate(pd.DataFrame({"cust": [], "ord": [], "when": [], "amt": []}), _GOOD_MAP)
    check("empty file rejected cleanly", r.ok is False)
    check("empty file has a message", len(r.errors) > 0)


def test_validate_absent_columns():
    # A confirmed mapping that points at columns not present in df must be
    # rejected cleanly by the firewall — never a KeyError / stack trace.
    from src.data.ingest.validator import validate
    r = validate(pd.DataFrame({"x": ["1"], "y": ["2"]}), _GOOD_MAP)
    check("absent mapped columns rejected", r.ok is False)
    check("firewall gives a human message, no crash",
          any("not in the uploaded file" in e for e in r.errors))


def test_validate_accounting_negative():
    from src.data.ingest.validator import validate
    df = _good_df(); df["amt"] = ["(50.00)", "10", "20"]
    r = validate(df, _GOOD_MAP)
    check("accounting negative treated as negative -> clipped to 0",
          float(r.orders["order_amount"].iloc[0]) == 0.0)
    check("accounting negative warns", any("negative" in w.lower() for w in r.warnings))


def test_validate_category_only_no_product_column():
    # Only category mapped (no product) -> order_items must NOT have a product
    # column, so Phase 1 marks reorder_rate unavailable rather than computing junk.
    from src.data.ingest.validator import validate
    df = _good_df(); df["dept"] = ["dairy", "dairy", "drinks"]
    m = dict(_GOOD_MAP, category="dept")
    r = validate(df, m)
    check("items built for category-only", r.order_items is not None)
    check("no product column when product unmapped", "product" not in r.order_items.columns)
    check("category column present", "category" in r.order_items.columns)


def test_build_canonical_full():
    from src.data.ingest.builder import build_canonical
    df = _good_df()
    df["prod"] = ["milk", "eggs", "soda"]; df["dept"] = ["dairy", "dairy", "drinks"]
    m = dict(_GOOD_MAP, product="prod", category="dept")
    res = build_canonical(df, m)
    check("build ok", res["ok"] is True)
    check("orders returned", res["orders"] is not None)
    check("matrix returned", res["matrix"] is not None)
    check("optional features available on rich upload",
          res["matrix"].is_available("avg_basket_size"))
    check("core features available",
          res["matrix"].is_available("monetary"))


def test_build_canonical_orders_only():
    from src.data.ingest.builder import build_canonical
    res = build_canonical(_good_df(), _GOOD_MAP)
    check("orders-only ok", res["ok"] is True)
    check("optional tagged unavailable",
          res["matrix"].is_available("reorder_rate") is False)
    check("core still available", res["matrix"].is_available("recency_days"))


def test_build_canonical_dedups_orders():
    from src.data.ingest.builder import build_canonical
    # order 100 appears twice (two line rows); amount is the order total repeated.
    df = pd.DataFrame({
        "cust": ["1", "1"], "ord": ["100", "100"],
        "when": ["2024-01-02", "2024-01-02"], "amt": ["50", "50"]})
    res = build_canonical(df, _GOOD_MAP)
    check("duplicate order rows collapsed", len(res["orders"]) == 1)
    check("monetary not double-counted",
          float(res["matrix"].frame["monetary"].iloc[0]) == 50.0)


def test_build_canonical_rejects_bad():
    from src.data.ingest.builder import build_canonical
    res = build_canonical(_good_df(), dict(_GOOD_MAP, customer_id=None))
    check("bad mapping surfaces not-ok", res["ok"] is False)
    check("errors passed through", len(res["errors"]) > 0)
    check("no matrix on failure", res["matrix"] is None)


def test_build_canonical_line_grained_warns():
    # Same order_id with two different amounts (a line-grained file): builder
    # must still succeed but WARN that revenue may be under-counted.
    from src.data.ingest.builder import build_canonical
    df = pd.DataFrame({
        "cust": ["1", "1"], "ord": ["100", "100"],
        "when": ["2024-01-02", "2024-01-02"], "amt": ["12.50", "8.00"]})
    res = build_canonical(df, _GOOD_MAP)
    check("line-grained still ok", res["ok"] is True)
    check("line-grained warns about differing amounts",
          any("more than one distinct amount" in w for w in res["warnings"]))
    check("still deduped to one order", len(res["orders"]) == 1)


def main():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        test_reader_csv_comma(d)
        test_reader_semicolon_and_utf16(d)
    test_profiler()
    test_fuzzy_map()
    test_fuzzy_map_no_match()
    test_fuzzy_map_global_best()
    test_propose_mapping_llm()
    test_propose_mapping_fallback()
    test_propose_mapping_nested_values()
    test_validate_happy()
    test_validate_missing_required()
    test_validate_bad_dates()
    test_validate_negative_amount_warns()
    test_validate_builds_items()
    test_validate_empty_file()
    test_validate_absent_columns()
    test_validate_accounting_negative()
    test_validate_category_only_no_product_column()
    test_build_canonical_full()
    test_build_canonical_orders_only()
    test_build_canonical_dedups_orders()
    test_build_canonical_rejects_bad()
    test_build_canonical_line_grained_warns()
    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
