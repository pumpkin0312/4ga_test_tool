"""
Tests for task2_agent/stability.py — selector normalization, fixed-name rewriting,
precondition planning, destructive-scenario detection.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from task2_agent.stability import (
    expand_selector,
    normalize_step,
    rewrite_fixed_name_step,
    dedup_auto_nav,
    classify_precondition,
    plan_steps,
    is_destructive_scenario,
    unique_name,
)


# ── expand_selector ───────────────────────────────────────────────────────────

def test_css_module_class_truncates_at_double_underscore():
    # Real class is Card_card__<hash>; the __container suffix is hallucinated.
    # Truncating at __ yields a substring that matches the real hashed class.
    out = expand_selector(".Card_card__container")
    assert out[0] == ".Card_card__container"           # original kept first
    assert "[class*='Card_card']" in out


def test_truncated_css_module_class():
    out = expand_selector(".Card_description__...")
    assert "[class*='Card_description']" in out


def test_carddetail_wrapper_truncates_to_component_element():
    out = expand_selector(".CardDetail_cardDetail__wrapper")
    assert "[class*='CardDetail_cardDetail']" in out


def test_tagged_css_module_class():
    out = expand_selector("div.BoardColumn")
    assert "div[class*='BoardColumn']" in out


def test_attribute_selector_is_left_untouched():
    assert expand_selector("div[class*='BoardColumn']") == ["div[class*='BoardColumn']"]
    assert expand_selector("input[name='confirmPassword']") == ["input[name='confirmPassword']"]


def test_stable_utility_class_not_rewritten():
    assert expand_selector(".active") == [".active"]


# ── normalize_step (hallucinated → real DOM) ──────────────────────────────────

def test_normalize_wrong_list_placeholder():
    step = {"action": "input", "target": "input[placeholder='Enter list title...']", "value": "L1"}
    out = normalize_step(step)
    assert out["target"] == "textarea[name='name']"


def test_normalize_wrong_card_placeholder():
    step = {"action": "input", "target": "input[placeholder='Enter a title for this card...']", "value": "C1"}
    out = normalize_step(step)
    assert out["target"] == "textarea[name='name']"


def test_normalize_hallucinated_card_container_to_wrapper():
    # Card click should target the clickable outer Card_wrapper, not Card_card.
    step = {"action": "click", "target": ".Card_card__container"}
    out = normalize_step(step)
    assert out["target"] == "[class*='Card_wrapper']"


def test_normalize_carddetail_to_cardmodal():
    step = {"action": "assert_visible", "target": ".CardDetail_cardDetail__wrapper"}
    out = normalize_step(step)
    assert out["target"] == "[class*='CardModal_wrapper']"


def test_normalize_carddetail_prefix_general():
    step = {"action": "click", "target": "[class*='CardDetail_header']"}
    out = normalize_step(step)
    assert "CardModal" in out["target"]
    assert "CardDetail" not in out["target"]


def test_normalize_card_description_to_cardmodal_description():
    step = {"action": "click", "target": ".Card_description__abc"}
    out = normalize_step(step)
    assert out["target"] == "[class*='CardModal_descriptionText']"


def test_normalize_displayname_to_name():
    step = {"action": "input", "target": "input[name='displayName']", "value": "x"}
    out = normalize_step(step)
    assert out["target"] == "input[name='name']"


def test_normalize_board_name_placeholder_to_name_input():
    step = {"action": "input", "target": "input[placeholder='Enter board name...']", "value": "B"}
    out = normalize_step(step)
    assert out["target"] == "input[name='name']"


def test_normalize_add_list_to_title_selector():
    step = {"action": "click", "target": "button[type='button']:has-text('Add a list')"}
    out = normalize_step(step)
    assert out["target"] == "button[title='Add List']"


def test_normalize_add_card_to_title_selector():
    step = {"action": "click", "target": "button:has-text('Add card')"}
    out = normalize_step(step)
    assert out["target"] == "button[title='Add Card']"


def test_normalize_aria_label_to_title():
    # Description toolbar buttons use title, not aria-label.
    step = {"action": "click", "target": "button[aria-label='Add colored text']"}
    assert normalize_step(step)["target"] == "button[title='Add colored text']"


def test_normalize_insert_table_to_add_table():
    step = {"action": "click", "target": "button[aria-label='Insert table']"}
    assert normalize_step(step)["target"] == "button[title='Add table']"


def test_normalize_boardcolumn_to_list():
    step = {"action": "click", "target": "div[class*='BoardColumn']"}
    out = normalize_step(step)
    assert "List_" in out["target"]
    assert "BoardColumn" not in out["target"]


def test_normalize_has_text_icon_button_to_accessible_name():
    # Settings is an icon button (name only in title attr); :has-text can't match it.
    # Reduce to plain accessible name so get_by_role(name=...) resolves it.
    step = {"action": "click", "target": "button[type='button']:has-text('Settings')"}
    out = normalize_step(step)
    assert out["target"] == "Settings"
    step2 = {"action": "click", "target": "button[type='button']:has-text('Members')"}
    assert normalize_step(step2)["target"] == "Members"


def test_normalize_email_or_username_to_input():
    step = {"action": "input", "target": "Email or username", "value": "x"}
    out = normalize_step(step)
    assert out["target"] == "input[name='emailOrUsername']"


def test_normalize_leaves_good_selector_untouched():
    step = {"action": "click", "target": "button[type='submit']"}
    assert normalize_step(step) == step


# ── rewrite_fixed_name_step ───────────────────────────────────────────────────

def test_fixed_project_name_becomes_dynamic():
    step = {"action": "click", "target": "Getting started1", "description": "打开项目"}
    out = rewrite_fixed_name_step(step)
    assert out["action"] == "enter_first_project"
    assert out["_auto"] is True


def test_fixed_name_in_has_text_form_becomes_dynamic():
    step = {"action": "click", "target": "button[type='button']:has-text('Getting started1')"}
    out = rewrite_fixed_name_step(step)
    assert out["action"] == "enter_first_project"


def test_fixed_board_name_becomes_dynamic():
    step = {"action": "click", "target": "text=Kanban Test Board"}
    out = rewrite_fixed_name_step(step)
    assert out["action"] == "open_first_board"


def test_non_fixed_name_untouched():
    step = {"action": "click", "target": "Add Board"}
    assert rewrite_fixed_name_step(step) == step


# ── dedup_auto_nav ────────────────────────────────────────────────────────────

def test_dedup_collapses_duplicate_enter_project():
    steps = [
        {"action": "navigate"},
        {"action": "enter_first_project"},
        {"action": "open_first_board"},
        {"action": "enter_first_project"},   # duplicate → dropped
        {"action": "click", "target": "x"},
    ]
    out = dedup_auto_nav(steps)
    actions = [s["action"] for s in out]
    assert actions == ["navigate", "enter_first_project", "open_first_board", "click"]


# ── classify_precondition / plan_steps ────────────────────────────────────────

def test_settings_scenario_gets_open_settings_and_skips_project():
    scenario = {
        "name": "管理员修改用户邮箱",
        "precondition": "用户已登录，Settings 弹窗已打开",
        "steps": [{"action": "input", "target": "input[name='email']", "value": "a@b.com"}],
    }
    kind = classify_precondition(scenario)
    assert kind["needs_settings"] is True
    assert kind["needs_project"] is False
    actions = [s["action"] for s in plan_steps(scenario, "https://x", "u", "p")]
    assert "open_settings" in actions
    assert "enter_first_project" not in actions


def test_settings_section_detection():
    # email/username → Account; password → Authentication
    email_sc = {"name": "修改邮箱", "precondition": "Settings 已打开",
                "steps": [{"action": "input", "target": "input[name='email']"}]}
    pw_sc = {"name": "修改密码", "precondition": "Settings 已打开",
             "steps": [{"action": "input", "target": "input[name='password']"}]}
    assert classify_precondition(email_sc)["settings_section"] == "Account"
    assert classify_precondition(pw_sc)["settings_section"] == "Authentication"
    # the section is threaded into the open_settings step value
    step = next(s for s in plan_steps(email_sc, "https://x", "u", "p")
                if s["action"] == "open_settings")
    assert step["value"] == "Account"


def test_board_scenario_enters_project_and_board():
    scenario = {
        "name": "在看板中添加列表",
        "precondition": "用户已进入看板页",
        "steps": [{"action": "click", "target": "Add a list"}],
    }
    actions = [s["action"] for s in plan_steps(scenario, "https://x", "u", "p")]
    assert actions[:4] == ["navigate", "login", "enter_first_project", "open_first_board"]


def test_project_creation_stays_on_dashboard():
    scenario = {
        "name": "通过仪表板按钮成功创建项目",
        "precondition": "用户已登录并处于 Dashboard 页面",
        "steps": [{"action": "click", "target": "Add Project"}],
    }
    actions = [s["action"] for s in plan_steps(scenario, "https://x", "u", "p")]
    assert actions == ["navigate", "login", "click"]


def test_project_settings_routes_to_project_not_user_settings():
    # "项目设置" must go project→board→open_project_settings, NOT user open_settings.
    scenario = {
        "name": "取消修改项目设置",
        "precondition": "用户已进入项目设置页",
        "steps": [{"action": "click", "target": "input[name='name']"}],
    }
    kind = classify_precondition(scenario)
    assert kind["needs_project_settings"] is True
    assert kind["needs_settings"] is False
    actions = [s["action"] for s in plan_steps(scenario, "https://x", "u", "p")]
    assert "open_project_settings" in actions
    assert "open_settings" not in actions


def test_project_member_invite_routes_to_project_settings():
    scenario = {
        "name": "从项目设置弹窗邀请成员到项目",
        "precondition": "用户已进入项目页，项目设置弹窗已打开",
        "steps": [{"action": "click", "target": "text=Members"}],
    }
    kind = classify_precondition(scenario)
    assert kind["needs_project_settings"] is True
    assert kind["needs_settings"] is False


def test_user_settings_still_routes_to_open_settings():
    # A pure user-settings scenario (no 项目) still uses open_settings.
    scenario = {
        "name": "修改密码",
        "precondition": "用户已登录，Settings 已打开",
        "steps": [{"action": "input", "target": "input[type='password']"}],
    }
    kind = classify_precondition(scenario)
    assert kind["needs_settings"] is True
    assert kind["needs_project_settings"] is False
    assert kind["settings_section"] == "Authentication"


def test_card_scenario_not_routed_to_user_settings_even_with_description():
    # "编辑卡片描述" contains 描述 (a settings-trigger word) but is a card scenario.
    scenario = {
        "name": "编辑卡片描述 - 添加彩色文本",
        "precondition": "用户已打开卡片详情",
        "steps": [{"action": "click", "target": "[class*='CardModal_descriptionText']"}],
    }
    kind = classify_precondition(scenario)
    assert kind["needs_settings"] is False
    assert kind["needs_project_settings"] is False
    assert kind["needs_board"] is True
    assert kind["needs_card"] is True


def test_plan_steps_dedups_fixed_board_click_after_setup():
    # precondition needs a board (setup injects open_first_board), and the scenario
    # ALSO opens a fixed-name board → after rewrite+dedup there is only one.
    scenario = {
        "name": "打开看板并查看卡片",
        "precondition": "用户已进入看板页",
        "steps": [
            {"action": "click", "target": "Kanban Test Board"},
            {"action": "click", "target": "text=Some Card"},
        ],
    }
    actions = [s["action"] for s in plan_steps(scenario, "https://x", "u", "p")]
    assert actions.count("open_first_board") == 1


def test_login_test_scenario_skips_login_injection():
    scenario = {
        "name": "空密码登录被拒绝",
        "precondition": "用户在登录页，未登录",
        "steps": [{"action": "input", "target": "input[type='password']", "value": ""}],
    }
    actions = [s["action"] for s in plan_steps(scenario, "https://x", "u", "p")]
    assert "login" not in actions
    assert actions[0] == "navigate"


def test_leading_navigate_stripped_when_setup_entered_deep():
    # Scenario hardcodes a dead board URL then re-enters; setup already went deep,
    # so the scenario's leading navigate (which would reset state) is dropped.
    scenario = {
        "name": "折叠列表隐藏卡片",
        "precondition": "用户已进入看板页",
        "steps": [
            {"action": "navigate", "target": "https://demo/boards/999999", "value": ""},
            {"action": "click", "target": "[class*='List_header']"},
        ],
    }
    actions = [s["action"] for s in plan_steps(scenario, "https://x", "u", "p")]
    # setup nav is first; the scenario's own navigate must not appear after setup
    assert actions.count("navigate") == 1
    assert actions[0] == "navigate"


def test_leading_navigate_kept_for_login_test():
    # Login tests legitimately need their own navigate and no deep setup.
    scenario = {
        "name": "登录页校验",
        "precondition": "用户在登录页，未登录",
        "steps": [
            {"action": "navigate", "target": "https://x/login", "value": ""},
            {"action": "input", "target": "input[name='emailOrUsername']", "value": "a"},
        ],
    }
    actions = [s["action"] for s in plan_steps(scenario, "https://x", "u", "p")]
    assert actions.count("navigate") >= 1


def test_manual_login_prefix_removed_for_non_login_scenario():
    scenario = {
        "name": "导出看板为 tgz",
        "precondition": "用户已进入看板页",
        "steps": [
            {"action": "navigate", "target": "https://demo.4gaboards.com/login"},
            {"action": "input", "target": "input[name='emailOrUsername']", "value": "demo@demo.demo"},
            {"action": "input", "target": "input[type='password']", "value": "demo"},
            {"action": "click", "target": "button[type='submit']"},
            {"action": "wait", "target": "Add Project"},
            {"action": "click", "target": "Edit Board"},
        ],
    }
    steps = plan_steps(scenario, "https://x", "u", "p")
    assert [s["action"] for s in steps[:4]] == ["navigate", "login", "enter_first_project", "open_first_board"]
    assert not any(s.get("target") == "input[name='emailOrUsername']" for s in steps)
    assert steps[-1]["target"] == "Edit Board"


def test_stale_board_deep_link_removed_for_non_login_scenario():
    scenario = {
        "name": "新建卡片并添加富文本描述",
        "precondition": "用户已进入看板页",
        "steps": [
            {"action": "navigate", "target": "https://demo.4gaboards.com/boards/1782552018351555584"},
            {"action": "click", "target": "button:has-text('Add card')"},
        ],
    }
    steps = plan_steps(scenario, "https://x", "u", "p")
    assert not any("/boards/1782552018351555584" in (s.get("target") or "") for s in steps)
    assert steps[-1]["target"] == "button[title='Add Card']"


# ── is_destructive_scenario / unique_name ─────────────────────────────────────

def test_destructive_by_name():
    assert is_destructive_scenario({"name": "管理员删除项目", "steps": []}) is True
    assert is_destructive_scenario({"name": "修改密码", "steps": []}) is True


def test_destructive_by_step():
    scenario = {"name": "清理看板", "steps": [
        {"action": "click", "target": "Delete Board", "description": "删除看板"}]}
    assert is_destructive_scenario(scenario) is True


def test_destructive_by_password_form_fields():
    scenario = {"name": "新密码与确认密码不匹配时修改失败", "steps": [
        {"action": "input", "target": "input[name='currentPassword']", "value": "demo"},
        {"action": "input", "target": "input[name='confirmNewPassword']", "value": "x"},
    ]}
    assert is_destructive_scenario(scenario) is True


def test_non_destructive_read_scenario():
    scenario = {"name": "查看项目列表", "steps": [{"action": "click", "target": "Projects"}]}
    assert is_destructive_scenario(scenario) is False


def test_unique_name_has_base_and_timestamp():
    n = unique_name("Trello Import Test")
    assert n.startswith("Trello Import Test-")
    assert len(n) > len("Trello Import Test-")
