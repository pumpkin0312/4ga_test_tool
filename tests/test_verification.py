"""
Tests for verification hardening in task2_agent/agent.py:
cancel-scenario detection used to prevent false-PASS.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from task2_agent.agent import TestAgent as Agent


def test_is_cancel_scenario_detects_cancel_names():
    assert Agent._is_cancel_scenario({"name": "创建看板时取消操作"}) is True
    assert Agent._is_cancel_scenario({"name": "取消编辑用户资料"}) is True
    assert Agent._is_cancel_scenario({"name": "Cancel import", "tags": []}) is True
    assert Agent._is_cancel_scenario({"name": "放弃修改"}) is True


def test_is_cancel_scenario_false_for_normal():
    assert Agent._is_cancel_scenario({"name": "成功创建看板"}) is False
    assert Agent._is_cancel_scenario({"name": "为卡片添加标签"}) is False
