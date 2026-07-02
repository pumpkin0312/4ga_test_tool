"""
Tests for task2_agent/result_utils.py — result classification & failure attribution.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from task2_agent.result_utils import (
    detect_blocked_reason,
    classify_failure_reason,
    summarize,
    REASON_MISSING_DATA,
    REASON_FIXED_NAME,
    REASON_BAD_SELECTOR,
    REASON_SHARED_ACCOUNT,
    REASON_ENV_ERROR,
    REASON_PASS,
)


# ── detect_blocked_reason ─────────────────────────────────────────────────────

def test_blocked_when_upload_file_missing():
    scenario = {
        "steps": [
            {"action": "navigate", "target": "https://x", "value": ""},
            {"action": "setInputFiles", "target": "input[type='file']",
             "value": "test_data/definitely_missing_12345.json"},
        ]
    }
    reason = detect_blocked_reason(scenario)
    assert reason is not None
    assert "test_data/definitely_missing_12345.json" in reason


def test_not_blocked_when_upload_file_exists():
    # test_data/4gaboards_export.tgz exists in the repo.
    scenario = {
        "steps": [
            {"action": "setInputFiles", "target": "From 4ga Boards",
             "value": "test_data/4gaboards_export.tgz"},
        ]
    }
    assert detect_blocked_reason(scenario) is None


def test_not_blocked_when_no_upload_steps():
    scenario = {"steps": [{"action": "click", "target": "Add Board", "value": ""}]}
    assert detect_blocked_reason(scenario) is None


def test_blocked_for_shared_demo_password_mutation():
    scenario = {
        "name": "正常修改密码并验证成功提示",
        "steps": [
            {"action": "click", "target": "Edit Password", "description": "打开修改密码表单"},
            {"action": "input", "target": "input[name='currentPassword']", "value": "demo"},
            {"action": "input", "target": "input[name='newPassword']", "value": "NewDemoPass!23"},
            {"action": "click", "target": "Save", "description": "保存修改密码"},
        ],
    }
    reason = detect_blocked_reason(scenario)
    assert reason is not None
    assert "共享 demo 账号" in reason


# ── classify_failure_reason ───────────────────────────────────────────────────

def test_pass_is_classified_as_pass():
    assert classify_failure_reason({"result": "PASS"}) == REASON_PASS


def test_error_is_environment():
    assert classify_failure_reason({"result": "ERROR", "actions": []}) == REASON_ENV_ERROR


def test_blocked_missing_data_reason():
    r = {"result": "BLOCKED", "summary": "测试数据缺失：上传文件不存在 test_data/trello_export.json"}
    assert classify_failure_reason(r) == REASON_MISSING_DATA


def test_fail_bad_selector():
    r = {
        "result": "FAIL",
        "scenario_name": "修改卡片描述",
        "actions": [
            {"action": "input", "target": "textarea[name='description']",
             "success": False, "error_msg": "not found"},
        ],
    }
    assert classify_failure_reason(r) == REASON_BAD_SELECTOR


def test_fail_fixed_name():
    r = {
        "result": "FAIL",
        "scenario_name": "打开看板",
        "actions": [
            {"action": "click", "target": "text=Kanban Test Board",
             "success": False, "error_msg": "not found"},
        ],
    }
    assert classify_failure_reason(r) == REASON_FIXED_NAME


def test_fail_shared_account_destructive():
    # No selector-like failure, but a destructive scenario name.
    r = {
        "result": "FAIL",
        "scenario_name": "管理员删除项目",
        "actions": [
            {"action": "click", "target": "Delete", "success": False, "error_msg": "x"},
        ],
    }
    assert classify_failure_reason(r) == REASON_SHARED_ACCOUNT


# ── summarize ─────────────────────────────────────────────────────────────────

def test_summarize_counts_and_pass_rate_excludes_error_blocked():
    results = [
        {"result": "PASS"},
        {"result": "PASS"},
        {"result": "FAIL", "scenario_name": "x", "actions": [
            {"action": "input", "target": ".Card_card__container", "success": False}]},
        {"result": "ERROR", "actions": []},
        {"result": "BLOCKED", "summary": "测试数据缺失"},
    ]
    s = summarize(results)
    assert s["total"] == 5
    assert s["by_category"] == {"PASS": 2, "FAIL": 1, "ERROR": 1, "BLOCKED": 1}
    # pass rate over PASS+FAIL only = 2 / 3
    assert abs(s["pass_rate"] - 2 / 3) < 1e-9
    assert s["by_reason"][REASON_BAD_SELECTOR] == 1
    assert s["by_reason"][REASON_MISSING_DATA] == 1
