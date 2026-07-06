# tests/test_config.py — standalone script (no network, no Streamlit UI)
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config

checks = 0
def ok(c, m):
    global checks
    assert c, m
    checks += 1


# dev-style profile reproduces the legacy Gemini-first-then-Claude arsenal + base_url
arsenal = config.build_llm_arsenal_for_profile(
    {"providers": [
        {"provider": "gemini", "keys": ["g1", "g2"], "models": ["mA", "mB"], "base_url": None},
        {"provider": "claude", "keys": ["c1"], "models": ["cX"], "base_url": "http://ent"},
    ]})
ok(arsenal[0]["provider"] == "gemini", "gemini combos come first")
ok(arsenal[0]["base_url"] is None, "gemini base_url defaults None")
ok(arsenal[-1] == {"provider": "claude", "key": "c1", "model": "cX",
                   "label": "Claude+cX", "base_url": "http://ent"},
   "claude combo carries base_url + label")
ok(len(arsenal) == 2 * 2 + 1, "N keys x M models per provider")

# a claude provider with no keys contributes nothing
arsenal2 = config.build_llm_arsenal_for_profile(
    {"providers": [{"provider": "claude", "keys": [], "models": ["cX"], "base_url": None}]})
ok(arsenal2 == [], "no keys -> no combos")

# LLM_BACKEND selects a real profile; every live combo carries base_url
ok(config.LLM_BACKEND in config.BACKEND_PROFILES, "LLM_BACKEND selects a real profile")
ok(all("base_url" in c for c in config.LLM_ARSENAL), "every live combo has base_url")

print(f"test_config: {checks} checks passed")
