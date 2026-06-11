"""Standalone tests for src/agent/insights.py (pure signal detection)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.agent.insights import detect_signals, briefing_digest

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


SIGNAL_KEYS = {
    "id", "severity", "icon", "headline",
    "detail", "action_label", "action_prompt",
}


def _fixtures():
    # 6 users. Power = {1, 2}. churn_days=30 => at risk are those whose
    # avg_days_between_orders > 30: users 2, 3, 5 (and user 2 is a power user).
    features = pd.DataFrame({
        'user_id':                [1, 2, 3, 4, 5, 6],
        'total_orders':           [40, 35, 8, 12, 5, 10],
        'avg_days_between_orders': [10, 40, 50, 20, 60, 15],
        'reorder_rate':           [0.85, 0.80, 0.20, 0.30, 0.10, 0.25],
        'dept_diversity':         [16, 14, 4, 6, 3, 5],
        'avg_basket_size':        [13.0, 12.0, 4.0, 5.0, 3.0, 4.5],
        'total_items':            [520, 420, 32, 60, 15, 45],
    })
    scored_df = features.copy()
    scored_df['loyalty_score'] = [95.0, 88.0, 30.0, 40.0, 12.0, 28.0]

    power = features[features['user_id'].isin([1, 2])].copy()
    regular = features[features['user_id'].isin([3, 4, 5, 6])].copy()
    power_ids = {1, 2}

    # Minimal full_data for happy paths: power users 1 & 2 share an early
    # 4-order department sequence; regulars diverge so prefixes thin out.
    rows = []
    seq_power = ['dairy', 'produce', 'dairy', 'snacks']
    seq_reg3  = ['dairy', 'produce', 'beverages', 'frozen']
    seq_reg4  = ['dairy', 'bakery', 'produce', 'snacks']
    for uid, seq in [(1, seq_power), (2, seq_power),
                     (3, seq_reg3), (4, seq_reg4)]:
        for onum, dept in enumerate(seq, start=1):
            rows.append({'user_id': uid, 'order_number': onum,
                         'department': dept})
    full_data = pd.DataFrame(rows)

    return features, scored_df, power, regular, power_ids, full_data


def main():
    features, scored_df, power, regular, power_ids, full_data = _fixtures()

    signals = detect_signals(
        features, scored_df, power, regular, power_ids, full_data,
        churn_days=30, top_pct=10,
    )

    # ---- shape & contract ----
    check("returns a list", isinstance(signals, list))
    check("at most 4 signals", len(signals) <= 4)
    check("at least 1 signal", len(signals) >= 1)
    check("every signal has all keys",
          all(SIGNAL_KEYS.issubset(s.keys()) for s in signals))
    check("severities are ints 0-100",
          all(isinstance(s['severity'], int) and 0 <= s['severity'] <= 100
              for s in signals))
    check("sorted by severity descending",
          all(signals[i]['severity'] >= signals[i + 1]['severity']
              for i in range(len(signals) - 1)))
    check("ids are unique",
          len({s['id'] for s in signals}) == len(signals))
    check("every action_prompt is a non-trivial string",
          all(isinstance(s['action_prompt'], str) and len(s['action_prompt']) > 10
              for s in signals))

    # ---- churn signal grounded in real counts ----
    churn = next((s for s in signals if s['id'] == 'churn'), None)
    check("churn signal present", churn is not None)
    # at-risk = users with avg_days_between_orders > 30 => {2,3,5} = 3 users,
    # one of which (user 2) is a power user.
    check("churn headline cites 3 at-risk", '3' in churn['headline'])
    check("churn detail flags power exposure",
          'power' in churn['detail'].lower())

    # ---- digest is plain text carrying every headline ----
    digest = briefing_digest(signals)
    check("digest is a string", isinstance(digest, str))
    check("digest carries each headline",
          all(s['headline'] in digest for s in signals))

    # ---- robustness: empty full_data must not crash, just skip happy_path ----
    safe = detect_signals(
        features, scored_df, power, regular, power_ids,
        pd.DataFrame(columns=['user_id', 'order_number', 'department']),
        churn_days=30, top_pct=10,
    )
    check("empty full_data: no crash", isinstance(safe, list))
    check("empty full_data: no happy_path signal",
          all(s['id'] != 'happy_path' for s in safe))

    # ---- robustness: no at-risk users => no churn signal, still no crash ----
    calm = features.copy()
    calm['avg_days_between_orders'] = 5  # nobody over a 30-day threshold
    none_at_risk = detect_signals(
        calm, scored_df, power, regular, power_ids, full_data,
        churn_days=30, top_pct=10,
    )
    check("no at-risk: churn skipped",
          all(s['id'] != 'churn' for s in none_at_risk))

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
