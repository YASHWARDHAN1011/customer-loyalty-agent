"""Standalone tests for src/agent/deliverables.py (pure functions)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.agent.deliverables import (
    select_target_users, to_csv_bytes,
    campaign_emails_markdown, action_plan_markdown,
)
from src.analysis.interventions import INTERVENTION_TEMPLATES

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def _fixtures():
    features = pd.DataFrame({
        'user_id':               [1, 2, 3, 4],
        'total_orders':          [30, 5, 20, 2],
        'avg_days_between_orders':[10, 45, 12, 60],
        'reorder_rate':          [0.8, 0.2, 0.7, 0.1],
        'dept_diversity':        [15, 4, 12, 3],
        'avg_basket_size':       [12.0, 4.0, 10.0, 3.0],
        'total_items':           [360, 20, 200, 6],
    })
    scored = pd.DataFrame({'user_id': [1, 2, 3, 4],
                           'loyalty_score': [90.0, 30.0, 75.0, 15.0]})
    power   = features[features['user_id'].isin([1, 3])]
    regular = features[features['user_id'].isin([2, 4])]
    power_ids = {1, 3}
    return features, scored, power, regular, power_ids


def main():
    features, scored, power, regular, power_ids = _fixtures()

    # select_target_users: power segment returns only power users
    tgt = select_target_users(features, scored, power_ids, segment='power')
    check("target power-only", set(tgt['user_id']) == {1, 3})
    check("target has loyalty_score col", 'loyalty_score' in tgt.columns)
    check("target has segment col", 'segment' in tgt.columns)

    # min_orders filter
    tgt2 = select_target_users(features, scored, power_ids, min_orders=20)
    check("target min_orders filter", set(tgt2['user_id']) == {1, 3})

    # churn_days filter (avg_days_between_orders >= churn_days)
    tgt3 = select_target_users(features, scored, power_ids, churn_days=40)
    check("target churn filter", set(tgt3['user_id']) == {2, 4})

    # limit
    tgt4 = select_target_users(features, scored, power_ids, limit=1)
    check("target limit", len(tgt4) == 1)

    # CSV bytes round-trip
    raw = to_csv_bytes(tgt)
    check("csv is bytes", isinstance(raw, (bytes, bytearray)))
    check("csv has header", b'user_id' in raw)

    # campaign emails contain real numbers + subject markers
    from src.analysis.interventions import compute_intervention_gaps
    gaps = compute_intervention_gaps(power, regular)
    emails = campaign_emails_markdown(gaps, INTERVENTION_TEMPLATES)
    check("emails non-empty", len(emails) > 50)
    check("emails have Subject", "Subject:" in emails)

    # action plan dated + has checklist items
    plan = action_plan_markdown(gaps, INTERVENTION_TEMPLATES,
                                at_risk_count=2, at_risk_power=1,
                                date_str="2026-06-08")
    check("plan has date", "2026-06-08" in plan)
    check("plan has checkbox", "- [ ]" in plan)

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
