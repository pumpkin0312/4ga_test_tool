"""
Regression tests for the verification-result decision policy.

Bug: scenarios returned PASS even when the rule-verification (inline) pass
rate was low, because config.FORCE_FAIL_THRESHOLD was never wired into the
final decision — the only downgrade guard fired only at a 0% inline pass rate.

These tests pin the intended policy: an LLM PASS is forced to FAIL when the
inline pass rate is below FORCE_FAIL_THRESHOLD.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from task2_agent.verifier import decide_result


def _inline(*passes):
    """Build an inline_results list from a sequence of bools."""
    return [{"expectation": f"exp{i}", "inline_pass": p} for i, p in enumerate(passes)]


def test_llm_pass_downgraded_to_fail_when_inline_below_threshold():
    # LLM said PASS, but only 1 of 4 rule expectations actually verified (25%).
    llm = {"result": "PASS", "confidence": 0.9, "summary": "looks good"}
    out = decide_result(llm, _inline(True, False, False, False), force_fail_threshold=0.5)
    assert out["result"] == "FAIL"


def test_llm_pass_kept_when_inline_at_or_above_threshold():
    # 3 of 4 verified (75%) — above the 50% threshold, PASS should stand.
    llm = {"result": "PASS", "confidence": 0.9, "summary": "looks good"}
    out = decide_result(llm, _inline(True, True, True, False), force_fail_threshold=0.5)
    assert out["result"] == "PASS"


def test_all_inline_false_still_forces_fail():
    # The original guard: every expectation failed (0%) → FAIL.
    llm = {"result": "PASS", "confidence": 0.8, "summary": ""}
    out = decide_result(llm, _inline(False, False), force_fail_threshold=0.5)
    assert out["result"] == "FAIL"


def test_error_result_is_preserved():
    # ERROR (e.g. browser failed to start) is not a PASS — never touched.
    llm = {"result": "ERROR", "confidence": 0, "summary": "browser crashed"}
    out = decide_result(llm, _inline(False, False, False, False), force_fail_threshold=0.5)
    assert out["result"] == "ERROR"


def test_no_inline_results_does_not_downgrade():
    # No rule expectations to judge against → cannot overrule the LLM.
    llm = {"result": "PASS", "confidence": 0.9, "summary": "ok"}
    out = decide_result(llm, [], force_fail_threshold=0.5)
    assert out["result"] == "PASS"


def test_inline_pass_rate_is_attached():
    llm = {"result": "PASS", "confidence": 0.9, "summary": "ok"}
    out = decide_result(llm, _inline(True, True, False, False), force_fail_threshold=0.5)
    assert out["inline_pass_rate"] == 0.5
