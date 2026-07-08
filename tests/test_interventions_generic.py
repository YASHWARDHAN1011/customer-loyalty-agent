# tests/test_interventions_generic.py — standalone script
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis.interventions import template_for, INTERVENTION_TEMPLATES

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

t = template_for("monetary")
ok(set(("icon", "title", "what", "who", "action", "message")).issubset(t), "generic has all fields")
ok("Total Spend" in t["title"], "generic title uses the lever label")
_ = t["what"].format(ru=1.0, pu=2.0)
_ = t["who"].format(mid=1.5, count=10, ru=1.0, pu=2.0)
ok(True, "generic template survives the consumers' .format kwargs")

if "reorder_rate" in INTERVENTION_TEMPLATES:
    ok(template_for("reorder_rate") is INTERVENTION_TEMPLATES["reorder_rate"],
       "known column keeps its specific template")

print(f"test_interventions_generic: {checks} checks passed")
