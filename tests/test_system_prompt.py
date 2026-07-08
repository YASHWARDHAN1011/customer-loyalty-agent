# tests/test_system_prompt.py — standalone script
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

sp = config.SYSTEM_PROMPT
ok("Instacart" not in sp, "prompt names no specific dataset")
ok("206,209" not in sp, "prompt hardcodes no dataset row count")
ok("department" not in sp.lower(), "prompt assumes no Instacart-only department field")
for tool_name in ("run_scoring_analysis", "analyze_churn_risk", "get_current_stats"):
    ok(tool_name in sp, f"prompt still lists the {tool_name} tool")
ok("loyalty_score" in sp, "prompt still explains the loyalty score")

print(f"test_system_prompt: {checks} checks passed")
