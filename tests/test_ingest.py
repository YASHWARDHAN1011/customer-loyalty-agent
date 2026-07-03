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


def main():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        test_reader_csv_comma(d)
        test_reader_semicolon_and_utf16(d)
    test_profiler()
    test_fuzzy_map()
    test_fuzzy_map_no_match()
    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
