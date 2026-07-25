"""Phase 6 upload flow + app-boot wiring tests (no network)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest

def test_app_boots_on_demo_zero_exceptions():
    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception, f"app raised: {at.exception}"
    # The active dataset is populated and labelled as the demo.
    assert at.session_state["dataset_source"] == "demo"
    assert at.session_state["dataset_label"]
    assert at.session_state["dataset_counts"]["customers"] > 0

import io, json, tempfile, pandas as pd
from src.ui.upload import prepare_upload, apply_mapping

_GOOD_CSV = (
    "Cust,Ord,When,Paid\n"
    "1,100,2024-01-01,10.00\n"
    "1,101,2024-01-15,5.50\n"
    "2,102,2024-02-01,20.00\n"
)

def _fake_generate(_prompt):
    # Deterministic "LLM": returns the correct mapping JSON for _GOOD_CSV.
    return json.dumps({"customer_id": "Cust", "order_id": "Ord",
                       "order_date": "When", "order_amount": "Paid"})

def test_prepare_upload_proposes_mapping_no_saved_recipe():
    df = pd.read_csv(io.StringIO(_GOOD_CSV), dtype=str)
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        state = prepare_upload(df, generate_fn=_fake_generate, store_path=store)
    assert state["stage"] == "confirm"
    assert state["saved"] is False
    assert state["mapping"]["order_amount"] == "Paid"
    assert [p["name"] for p in state["profile"]] == ["Cust", "Ord", "When", "Paid"]

def test_prepare_upload_uses_saved_recipe_fast_path():
    df = pd.read_csv(io.StringIO(_GOOD_CSV), dtype=str)
    mapping = {"customer_id": "Cust", "order_id": "Ord",
               "order_date": "When", "order_amount": "Paid"}
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        from src.data.ingest.mapping_store import save_mapping
        save_mapping(list(df.columns), mapping, path=store)
        state = prepare_upload(df, generate_fn=_fake_generate, store_path=store)
    assert state["stage"] == "build"      # skips confirm
    assert state["saved"] is True
    assert state["mapping"] == mapping

def test_apply_mapping_success_builds_canonical():
    df = pd.read_csv(io.StringIO(_GOOD_CSV), dtype=str)
    mapping = {"customer_id": "Cust", "order_id": "Ord",
               "order_date": "When", "order_amount": "Paid"}
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        result = apply_mapping(df, mapping, store_path=store)
        assert result["ok"] is True
        assert result["matrix"] is not None
        with open(store) as fh:
            assert json.load(fh)  # non-empty store (mapping persisted)

def test_apply_mapping_failure_returns_errors():
    bad = "Cust,Ord,When,Paid\n1,100,2024-01-01,notmoney\n2,101,2024-01-02,alsobad\n"
    df = pd.read_csv(io.StringIO(bad), dtype=str)
    mapping = {"customer_id": "Cust", "order_id": "Ord",
               "order_date": "When", "order_amount": "Paid"}
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        result = apply_mapping(df, mapping, store_path=store)
    assert result["ok"] is False
    assert result["errors"]
    assert result["matrix"] is None

def test_apply_mapping_honors_overrides():
    csv = "c,o,when,amt,sku\nc1,o1,03/04/2025,25,A\nc1,o1,03/04/2025,25,B\n"
    df = pd.read_csv(io.StringIO(csv), dtype=str)
    m = {"customer_id": "c", "order_id": "o", "order_date": "when",
         "order_amount": "amt", "product": "sku"}
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        # month-first => 03/04 is March 4; line_item => identical 25+25 summed to 50.
        res = apply_mapping(df, m, store_path=store, dayfirst=False, grain="line_item")
    assert res["ok"] is True
    row = res["orders"].iloc[0]
    assert float(row["order_amount"]) == 50.0
    assert row["order_date"] == pd.Timestamp("2025-03-04")

def test_confirm_gate_absent_on_demo_boot():
    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception, f"app raised: {at.exception}"
    # No confirm gate pending on a clean demo boot.
    assert "upload_stage" not in at.session_state or at.session_state["upload_stage"] is None

def test_confirm_gate_shows_locale_and_grain_radios():
    from streamlit.testing.v1 import AppTest
    script = (
        "import os, sys\n"
        "sys.path.insert(0, os.getcwd())\n"
        "import pandas as pd, streamlit as st\n"
        "from src.ui.upload import render_confirm_gate\n"
        "st.session_state['upload_stage'] = 'confirm'\n"
        "st.session_state['upload_df'] = pd.DataFrame({'c':['c1','c1'],'o':['o1','o1'],"
        "'when':['03/04/2025','03/04/2025'],'amt':['30','45'],'sku':['A','B']})\n"
        "st.session_state['upload_mapping'] = {'customer_id':'c','order_id':'o',"
        "'order_date':'when','order_amount':'amt','product':'sku'}\n"
        "st.session_state['upload_filename'] = 'f.csv'\n"
        "render_confirm_gate(lambda *a, **k: None)\n"
    )
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, f"confirm gate raised: {at.exception}"
    labels = [r.label for r in at.radio]
    assert "Date format" in labels, labels
    assert "Order grain" in labels, labels

_CUR_CSV = (
    "Cust,Ord,When,Paid,Cur\n"
    "c1,o1,2025-01-01,10.00,USD\n"
    "c2,o2,2025-01-02,10.00,AUD\n"
)
_CUR_MAPPING = {"customer_id": "Cust", "order_id": "Ord", "order_date": "When",
                "order_amount": "Paid", "order_currency": "Cur"}

def test_apply_mapping_forwards_and_persists_currency():
    df = pd.read_csv(io.StringIO(_CUR_CSV), dtype=str)
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        result = apply_mapping(df, _CUR_MAPPING, store_path=store,
                               reporting_currency="AUD",
                               rates={"AUD": 1.0, "USD": 1.5})
        assert result["ok"] is True
        assert result["reporting_currency"] == "AUD"
        saved = json.load(open(store))
    entry = next(iter(saved.values()))
    assert entry["reporting_currency"] == "AUD"
    assert entry["rates"]["USD"] == 1.5

def test_prepare_upload_fast_path_returns_saved_currency():
    df = pd.read_csv(io.StringIO(_CUR_CSV), dtype=str)
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        from src.data.ingest.mapping_store import save_mapping
        save_mapping(list(df.columns), _CUR_MAPPING, path=store,
                     extras={"reporting_currency": "AUD",
                             "rates": {"AUD": 1.0, "USD": 1.5}})
        state = prepare_upload(df, generate_fn=_fake_generate, store_path=store)
    assert state["stage"] == "build"
    assert state["reporting_currency"] == "AUD"
    assert state["rates"]["USD"] == 1.5

def test_confirm_gate_shows_currency_controls_and_gates():
    from streamlit.testing.v1 import AppTest
    script = (
        "import os, sys\n"
        "sys.path.insert(0, os.getcwd())\n"
        "import pandas as pd, streamlit as st\n"
        "from src.ui.upload import render_confirm_gate\n"
        "st.session_state['upload_stage'] = 'confirm'\n"
        "st.session_state['upload_df'] = pd.DataFrame({'c':['c1','c2'],'o':['o1','o2'],"
        "'when':['2025-01-01','2025-01-02'],'amt':['10','10'],'cur':['USD','AUD']})\n"
        "st.session_state['upload_mapping'] = {'customer_id':'c','order_id':'o',"
        "'order_date':'when','order_amount':'amt','order_currency':'cur'}\n"
        "st.session_state['upload_filename'] = 'f.csv'\n"
        "render_confirm_gate(lambda *a, **k: None)\n"
    )
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, f"confirm gate raised: {at.exception}"
    assert "Reporting currency" in [s.label for s in at.selectbox], \
        [s.label for s in at.selectbox]
    assert any(n.label.startswith("1 USD") for n in at.number_input), \
        [n.label for n in at.number_input]

def test_apply_mapping_unit_price_persists_and_replays():
    """amount_is_unit_price threads through apply_mapping (correct totals), is
    persisted in the recipe, and replays on a same-shaped re-upload's fast path."""
    csv = ("Cust,Ord,When,UnitPrice,Qty\n"
           "1,100,2024-01-01,50,2\n"
           "1,100,2024-01-01,120,1\n"
           "2,101,2024-02-01,40,3\n")
    df = pd.read_csv(io.StringIO(csv), dtype=str)
    mapping = {"customer_id": "Cust", "order_id": "Ord", "order_date": "When",
               "order_amount": "UnitPrice", "quantity": "Qty"}
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        res = apply_mapping(df, mapping, store_path=store, amount_is_unit_price=True)
        assert res["ok"] is True
        o = res["orders"].set_index("order_id")
        assert float(o.loc["100", "order_amount"]) == 220.0   # 50*2 + 120*1
        assert float(o.loc["101", "order_amount"]) == 120.0   # 40*3
        # Fast path on re-upload replays the persisted flag.
        state = prepare_upload(df, generate_fn=_fake_generate, store_path=store)
        assert state["stage"] == "build"
        assert state["amount_is_unit_price"] is True


def test_confirm_gate_unit_price_option_only_with_quantity():
    """The 'unit price x quantity' grain option appears only when a quantity
    column is mapped (else it's meaningless)."""
    from streamlit.testing.v1 import AppTest
    script = (
        "import pandas as pd, streamlit as st\n"
        "from src.ui.upload import render_confirm_gate\n"
        "st.session_state['upload_stage'] = 'confirm'\n"
        "st.session_state['top_pct'] = 20\n"
        "st.session_state['upload_df'] = pd.DataFrame({\n"
        "  'Cust':['1','1'],'Ord':['100','100'],'When':['2024-01-01','2024-01-01'],\n"
        "  'UnitPrice':['50','120'],'Qty':['2','1']})\n"
        "st.session_state['upload_filename'] = 'f.csv'\n"
        "st.session_state['upload_mapping'] = {'customer_id':'Cust','order_id':'Ord',\n"
        "  'order_date':'When','order_amount':'UnitPrice','quantity':'Qty'}\n"
        "render_confirm_gate(lambda *a, **k: None)\n"
    )
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, f"confirm gate raised: {at.exception}"
    grain_opts = []
    for r in at.radio:
        if r.label == "Order grain":
            grain_opts = list(r.options)
    assert any("unit price" in o.lower() for o in grain_opts), grain_opts


def test_apply_mapping_on_real_shopify_reader_output():
    """End-to-end through the ACTUAL app seam: a faithful Shopify export read by
    read_table (pandas string dtype, blank continuation cells, mixed DST tz
    offsets, a parenthesised refund) -> apply_mapping -> canonical. Guards the two
    real-data crashes found by manual validation (mixed-tz + string-dtype NA)."""
    from src.data.ingest.reader import read_table
    header = "Name,Email,Currency,Total,Created at,Lineitem name\n"
    rows = [
        '"#1001","ann@x.com","AUD","1155.00","2025-06-13 08:14:52 +1000","Sofa"\n',
        '"#1001","","","","","Cushion"\n',
        '"#1001","","","","","Lamp"\n',
        '"#2001","bob@x.com","AUD","750.00","2025-01-15 19:40:10 +1100","Desk"\n',
        '"#2001","","","","","Chair"\n',
        '"#2002","bob@x.com","AUD","($20.00)","2025-06-15 09:00:00 +1000","Return"\n',
    ]
    fl = io.BytesIO((header + "".join(rows)).encode()); fl.name = "orders_export.csv"
    df = read_table(fl)
    m = {"customer_id": "Email", "order_id": "Name", "order_date": "Created at",
         "order_amount": "Total", "product": "Lineitem name",
         "order_currency": "Currency"}
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        res = apply_mapping(df, m, store_path=store)
    assert res["ok"] is True, res.get("errors")
    o = res["orders"].set_index("order_id")
    assert float(o.loc["#1001", "order_amount"]) == 1155.0
    assert float(o.loc["#2001", "order_amount"]) == 750.0
    assert float(o.loc["#2002", "order_amount"]) == 0.0        # refund clipped
    assert o.loc["#1001", "order_date"].normalize() == pd.Timestamp("2025-06-13")
    feats = res["matrix"].frame.set_index("customer_id")
    assert int(feats.loc["bob@x.com", "frequency"]) == 2       # #2001 + #2002


if __name__ == "__main__":
    test_app_boots_on_demo_zero_exceptions()
    test_confirm_gate_absent_on_demo_boot()
    test_prepare_upload_proposes_mapping_no_saved_recipe()
    test_prepare_upload_uses_saved_recipe_fast_path()
    test_apply_mapping_success_builds_canonical()
    test_apply_mapping_failure_returns_errors()
    test_apply_mapping_honors_overrides()
    test_confirm_gate_shows_locale_and_grain_radios()
    test_apply_mapping_forwards_and_persists_currency()
    test_prepare_upload_fast_path_returns_saved_currency()
    test_confirm_gate_shows_currency_controls_and_gates()
    test_apply_mapping_on_real_shopify_reader_output()
    test_apply_mapping_unit_price_persists_and_replays()
    test_confirm_gate_unit_price_option_only_with_quantity()
    print("test_upload_flow: OK")
