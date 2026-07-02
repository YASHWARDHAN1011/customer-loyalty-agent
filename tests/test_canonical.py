"""Standalone tests for src/data/canonical.py — the trust contract. No network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.data.canonical import (
    CORE_FEATURES, OPTIONAL_FEATURES, FeatureMatrix,
)

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def test_feature_matrix_container():
    frame = pd.DataFrame({"customer_id": [1, 2], "recency_days": [3, 9]})
    fm = FeatureMatrix(frame=frame, available={"recency_days": True,
                                               "category_diversity": False})
    check("frame round-trips", list(fm.frame["customer_id"]) == [1, 2])
    check("is_available true", fm.is_available("recency_days") is True)
    check("is_available false", fm.is_available("category_diversity") is False)
    check("unknown feature is unavailable",
          fm.is_available("does_not_exist") is False)
    check("available_features lists only available",
          fm.available_features() == ["recency_days"])
    check("core constant shape", CORE_FEATURES[0] == "recency_days"
          and len(CORE_FEATURES) == 6)
    check("optional constant shape", set(OPTIONAL_FEATURES) ==
          {"category_diversity", "avg_basket_size", "reorder_rate"})


def main():
    test_feature_matrix_container()
    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
