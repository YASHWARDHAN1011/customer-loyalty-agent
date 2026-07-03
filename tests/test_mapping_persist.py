"""Standalone tests for src/data/ingest/mapping_store.py. No network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def test_fingerprint_order_insensitive():
    from src.data.ingest.mapping_store import fingerprint
    a = fingerprint(["Cust", "Order", "Amt"])
    b = fingerprint(["amt", "  order ", "CUST"])
    check("fingerprint ignores order/case/space", a == b)
    c = fingerprint(["Cust", "Order", "Amt", "Extra"])
    check("different shape -> different fingerprint", a != c)


def test_save_load_roundtrip(tmpdir):
    from src.data.ingest.mapping_store import save_mapping, load_mapping
    path = os.path.join(tmpdir, "mappings.json")
    headers = ["Cust Ref", "Order No", "When", "Total"]
    mapping = {"customer_id": "Cust Ref", "order_id": "Order No",
               "order_date": "When", "order_amount": "Total"}
    save_mapping(headers, mapping, path=path)
    got = load_mapping(headers, path=path)
    check("saved mapping loads back", got == mapping)
    check("same shape re-upload hits", load_mapping(["total", "when", "order no", "cust ref"], path=path) == mapping)
    check("different shape misses", load_mapping(["a", "b"], path=path) is None)


def test_store_never_holds_rows(tmpdir):
    from src.data.ingest.mapping_store import save_mapping
    path = os.path.join(tmpdir, "mappings.json")
    save_mapping(["Cust", "Amt"], {"customer_id": "Cust"}, path=path)
    with open(path) as f:
        blob = f.read()
    check("only mapping recipe persisted, no obvious PII keys",
          "row" not in blob.lower() and "value" not in blob.lower())


def test_missing_store_returns_none():
    from src.data.ingest.mapping_store import load_mapping
    check("absent store -> None", load_mapping(["x"], path="does/not/exist.json") is None)


def test_corrupt_store_degrades(tmpdir):
    # A store file that is valid JSON but not an object (or is garbage) must not
    # break load/save — the app should just re-map. Never raise.
    from src.data.ingest.mapping_store import load_mapping, save_mapping
    path = os.path.join(tmpdir, "mappings.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write('["not", "an", "object"]')
    check("corrupt store loads as miss", load_mapping(["a", "b"], path=path) is None)
    # save over a corrupt store must not raise and must then be loadable
    save_mapping(["a", "b"], {"customer_id": "a"}, path=path)
    check("save recovers a corrupt store",
          load_mapping(["a", "b"], path=path) == {"customer_id": "a"})


if __name__ == "__main__":
    import tempfile
    test_fingerprint_order_insensitive()
    with tempfile.TemporaryDirectory() as d:
        test_save_load_roundtrip(d)
        test_store_never_holds_rows(d)
        test_corrupt_store_degrades(d)
    test_missing_store_returns_none()
    print(f"\n{_passed} checks passed.")
