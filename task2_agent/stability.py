"""
task2_agent/stability.py

执行稳定性相关的纯函数（无浏览器 / 无 LLM 依赖，便于单测）。集中解决全量报告
里暴露的三类高频失败根因：

  1. selector 不贴合真实 DOM —— CSS Module 类名（如 .Card_card__container）在真实
     页面里往往带哈希后缀（Card_card__container_a1b2c），精确类选择器匹配不到。
     expand_selector() 把这类选择器扩展出 [class*='...'] 子串兜底变体。
  2. 固定项目/看板名依赖 —— 场景步骤写死 "Getting started1"/"Kanban Test Board"
     等名称，demo 环境里可能不存在。rewrite_fixed_name_step() 把这类点击改写为
     动态的 enter_first_project / open_first_board。
  3. 前置条件/破坏性场景 —— classify_precondition() 推断需要的页面深度（含 settings
     弹窗）；is_destructive_scenario() 识别会污染共享 demo 的破坏性场景。
"""
import re
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════════════
# 一、selector 归一化：CSS Module 哈希类名兜底
# ══════════════════════════════════════════════════════════════════════════════

# 仅由「(可选标签) + 一个或多个 .class」构成的简单类选择器（可含被截断的 ...）
_SIMPLE_CLASS_RE = re.compile(r"^[A-Za-z]*(\.[A-Za-z0-9_-]+(\.\.\.)?)+$")


def looks_like_css_module(token: str) -> bool:
    """类名是否像 CSS Module / 组件哈希类（含下划线或大写驼峰）→ 需要子串兜底。"""
    return ("_" in token) or any(c.isupper() for c in token)


def _module_base(token: str) -> str:
    """
    取 CSS Module 类名里稳定的「组件_元素」前缀。

    4ga Boards 用 CSS Module，运行时类名形如 `Card_card__ab12c`（`组件_元素__哈希`）。
    场景里写的 `Card_card__container` / `Card_description__...` 里的 `container` /
    `...` 是 LLM 幻觉出来的后缀，真实 DOM 里并不存在。截断到第一个 `__` 之前，用
    `[class*='Card_card']` 才能匹配到带哈希的真实类名。
    """
    t = token.rstrip("_-")
    if "__" in t:
        return t.split("__", 1)[0]
    # 没有 __ 但形如 Card_description__（尾部被 rstrip 掉了）也已处理
    return t


def expand_selector(selector: str) -> list[str]:
    """
    把一个原始 selector 扩展成「候选列表」：原始的排第一，之后追加更鲁棒的变体。
    只对简单类选择器做 CSS Module 兜底；带属性/组合符的复杂选择器原样返回，避免误伤。
    """
    sel = (selector or "").strip()
    if not sel:
        return []
    out = [sel]
    if not _SIMPLE_CLASS_RE.match(sel):
        return out

    tag_m = re.match(r"^[A-Za-z]+", sel)
    tag = tag_m.group(0) if (tag_m and not sel.startswith(".")) else ""
    tokens = re.findall(r"\.([A-Za-z0-9_.-]+)", sel)

    parts = []
    for t in tokens:
        if looks_like_css_module(t):
            parts.append(f"[class*='{_module_base(t)}']")
        else:
            parts.append(f".{t}")   # 稳定的工具类保持精确匹配
    variant = tag + "".join(parts)
    if variant and variant != sel and variant not in out:
        out.append(variant)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 二、selector / 文案归一化：把 LLM 幻觉出的 target 换成真实 DOM 值
# ══════════════════════════════════════════════════════════════════════════════
# 依据真实页面 DOM 证据（reports/dom_evidence_20260701_211951.md）确认：
#   - 列表列不是 BoardColumn，而是 List 组件：List_outerWrapper / List_innerWrapper / List_header
#   - 卡片可点击外层是 Card_wrapper（role=button），不要只依赖 Card_card
#   - 卡片详情是 CardModal_*（CardModal_wrapper），不是 CardDetail_*
#   - 描述编辑是 CardModal_descriptionText（title="Edit Description"），不是 Card_description
#   - Add list 按钮真实文本是 "Add list"，title="Add List" → 用 button[title='Add List']
#   - Add card 按钮 title="Add Card" → 用 button[title='Add Card']
#   - 新建看板输入框 input[name='name']（placeholder "Enter board name..."），在 [role=dialog] 内
#   - Profile 字段是 input[name='name'] / input[name='phone'] / input[name='organization']，无 displayName

# 精确 target 替换表（小写键匹配，替换为真实可用 selector）
_TARGET_REPLACEMENTS = {
    # 错误 placeholder → 真实输入框（列表/卡片标题都是 textarea[name='name']）
    "input[placeholder='enter list title...']":            "textarea[name='name']",
    "input[placeholder='enter a title for this card...']": "textarea[name='name']",
    "input[placeholder='enter card title...']":            "textarea[name='name']",
    "textarea[placeholder='enter list title...']":         "textarea[name='name']",
    "textarea[placeholder='enter a title for this card...']": "textarea[name='name']",
    # 新建看板输入框（在弹窗内）
    "input[placeholder='enter board name...']":            "input[name='name']",
    "input[placeholder='enter board name']":               "input[name='name']",
    "input[name='boardname']":                             "input[name='name']",
    # Profile：displayName 不存在，真实是 name
    "input[name='displayname']":                           "input[name='name']",
    # 卡片外层可点击容器（Card_wrapper 是 role=button 的点击区）
    ".card_card__container":            "[class*='Card_wrapper']",
    "[class*='card_card']":             "[class*='Card_wrapper']",
    # 卡片详情弹窗（CardDetail_* → CardModal_*）
    ".carddetail_carddetail__wrapper":  "[class*='CardModal_wrapper']",
    "[class*='carddetail_carddetail']": "[class*='CardModal_wrapper']",
    "[class*='carddetail']":            "[class*='CardModal_wrapper']",
    # 描述区域（Card_description → CardModal_descriptionText / Edit Description 按钮）
    ".card_description__...":           "[class*='CardModal_descriptionText']",
    "[class*='card_description']":      "[class*='CardModal_descriptionText']",
    # 登出/登录输入：等真实 input 而非纯文本
    "email or username":                "input[name='emailOrUsername']",
    "input[placeholder='enter email or username']": "input[name='emailOrUsername']",
}

# 按钮文案修正：真实按钮多为图标按钮，文本可能是小写/为空，名字在 title 属性里。
# 统一用 button[title='...'] 精确定位（大小写、可见文本都不可靠）。
_BUTTON_TEXT_FIXES = {
    "add a list": "button[title='Add List']",
    "add list":   "button[title='Add List']",
    "add a card": "button[title='Add Card']",
    "add card":   "button[title='Add Card']",
}


def _normalize_target(target: str) -> str:
    """把单个 target 归一到真实 DOM selector。不改变语义、只纠正幻觉写法。"""
    t = (target or "").strip()
    if not t:
        return t
    low = t.lower()

    # 1) 精确替换表
    if low in _TARGET_REPLACEMENTS:
        return _TARGET_REPLACEMENTS[low]

    # 2) CardDetail_* → CardModal_*（详情弹窗改名）
    if "carddetail" in low:
        return re.sub(r"CardDetail", "CardModal", t, flags=re.IGNORECASE)

    # 3) BoardColumn（幻觉类名）→ 真实的 List 组件类
    if "boardcolumn" in low:
        return re.sub(r"boardcolumn", "List_", t, flags=re.IGNORECASE)

    # 4) button[...]:has-text('X') / text=X 里的按钮文案修正
    #    4ga Boards 大量按钮是「图标按钮」，可见文本为空、名字只在 title 属性里
    #    （如 Settings / Add List / Members）。CSS 的 :has-text() 依赖真实文本节点，
    #    对这类按钮匹配不到。统一把 :has-text('X') 降级：Add List/Add Card 走
    #    button[title=...]，其它降为纯可访问名交给 get_by_role(name=X)。
    m = re.search(r"has-text\(\s*['\"](.+?)['\"]\s*\)", t, flags=re.IGNORECASE)
    if m:
        phrase = m.group(1).strip()
        return _BUTTON_TEXT_FIXES.get(phrase.lower(), phrase)

    # 5) 尾部截断的 CSS Module 类（.Card_description__... / .Card_card__...）
    if t.startswith(".") and ("__" in t or t.endswith("...")):
        base = _module_base(t.lstrip("."))
        low_base = base.lower()
        if low_base.startswith("card_description"):
            return "[class*='CardModal_descriptionText']"
        if low_base.startswith("card_card"):
            return "[class*='Card_wrapper']"
        if low_base.startswith("carddetail"):
            return "[class*='CardModal_wrapper']"
        return f"[class*='{base}']"

    # 6) 描述工具栏按钮：4ga 用 title 承载可访问名，把 aria-label 归一为 title，
    #    并修正已知措辞（Insert table → Add table）。
    if "aria-label=" in low:
        t2 = re.sub(r"aria-label\s*=", "title=", t, flags=re.IGNORECASE)
        t2 = re.sub(r"insert table", "Add table", t2, flags=re.IGNORECASE)
        return t2

    return t


def normalize_step(step: dict) -> dict:
    """对单个场景步骤做 target/placeholder/文案归一化（幻觉 → 真实 DOM）。"""
    target = step.get("target", "")
    new_target = _normalize_target(target)
    if new_target == target:
        return step
    out = dict(step)
    out["target"] = new_target
    out["_normalized_from"] = target
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 三、固定名称依赖：写死的项目/看板名 → 动态导航
# ══════════════════════════════════════════════════════════════════════════════

# demo 环境里不稳定 / 可能不存在的固定名称（小写匹配）
FIXED_PROJECT_NAMES = {"getting started", "getting started1"}
FIXED_BOARD_NAMES   = {"kanban test board", "my new board"}
KNOWN_FIXED_NAMES   = FIXED_PROJECT_NAMES | FIXED_BOARD_NAMES


def _plain_target(target: str) -> str:
    """把 target 归一为纯文本：去掉 text= 前缀、has-text('X') 包装与引号。"""
    t = (target or "").strip()
    # button[type='button']:has-text('Getting started1') → Getting started1
    m = re.search(r"has-text\(\s*['\"](.+?)['\"]\s*\)", t, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip("'\" ").lower()
    t = re.sub(r"^text\s*=\s*", "", t, flags=re.IGNORECASE)
    return t.strip("'\" ").lower()


def rewrite_fixed_name_step(step: dict) -> dict:
    """
    若 step 是「点击某个写死的项目/看板名」，改写为动态的 _auto 导航动作。
    否则原样返回。改写后的动作由 agent._run_one_step 处理（enter_first_project /
    open_first_board），并被 resolver 跳过。
    """
    action = (step.get("action") or "").lower().strip()
    if action not in ("click", "", "navigate_to"):
        return step
    name = _plain_target(step.get("target", ""))
    if not name:
        return step

    if name in FIXED_PROJECT_NAMES:
        return {**step, "action": "enter_first_project", "target": "", "value": "",
                "description": (step.get("description", "") + "（固定项目名→动态进入第一个项目）").strip(),
                "_auto": True, "_stabilized": "fixed-project"}
    if name in FIXED_BOARD_NAMES:
        return {**step, "action": "open_first_board", "target": "", "value": "",
                "description": (step.get("description", "") + "（固定看板名→动态打开第一个看板）").strip(),
                "_auto": True, "_stabilized": "fixed-board"}
    return step


def dedup_auto_nav(steps: list[dict]) -> list[dict]:
    """
    折叠重复的自动导航动作：同一段内（两次 navigate 之间）重复的 enter_first_project /
    open_first_board 只保留第一次。避免 setup 注入 + 场景改写导致的双重进入。
    """
    _NAV = {"enter_first_project", "open_first_board", "open_settings",
            "open_project_settings", "ensure_list_exists", "ensure_card_exists",
            "open_first_card"}
    out: list[dict] = []
    seen: set[str] = set()
    for s in steps:
        action = (s.get("action") or "").lower().strip()
        if action == "navigate":
            seen.clear()
            out.append(s)
            continue
        if action in _NAV:
            if action in seen:
                continue          # 丢弃重复的自动导航
            seen.add(action)
        out.append(s)
    return out


# ══════════════════════════════════════════════════════════════════════════════
# 三、前置条件推断（含 settings 弹窗）
# ══════════════════════════════════════════════════════════════════════════════

_LOGIN_TEST_KW = ["登录页", "登录界面", "登录前", "未登录", "login page", "not logged"]
_PROJECT_KW    = ["项目", "project"]
_BOARD_KW      = ["看板", "board", "列表", "list", "卡片", "card"]
_LIST_KW       = ["列表", "list"]
_CARD_KW       = ["卡片", "card"]
# 用户设置（顶部 Settings → Profile/Account/Authentication/Users）关键词
_USER_SETTINGS_KW = ["个人资料", "资料", "profile", "账户", "account", "authentication",
                     "密码", "password", "邮箱", "email", "用户名", "username",
                     "用户管理", "users", "settings", "设置"]
# 触发「项目设置 / 项目成员」的词（需与项目关键词同时出现）
_PROJECT_SETTINGS_TRIGGER = ["设置", "settings", "名称", "name", "成员", "member",
                             "邀请", "invite", "描述", "description"]
_PROJECT_CREATION_KW = ["创建项目", "新建项目", "添加项目", "add project", "create project"]


def _contains_keyword(text: str, keyword: str) -> bool:
    """英文关键词按完整单词匹配，避免 dashboard 被 board 误命中。"""
    if not text or not keyword:
        return False
    if re.search(r"[a-zA-Z]", keyword):
        return re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE) is not None
    return keyword in text


def classify_precondition(scenario: dict) -> dict:
    """
    根据 precondition + 名称推断需要的页面深度，返回各 needs_* 布尔标记。

    优先级（互斥，从上到下先命中先定）：
      1. 登录测试            → 只 navigate，不 login
      2. 项目设置 / 项目成员  → 进项目+看板，再 open_project_settings（不走用户 Settings）
      3. 看板 / 列表 / 卡片   → 进项目+看板（+按需 list/card），不走用户 Settings
      4. 用户设置            → open_settings（Profile/Account/Authentication/Users）
      5. 纯项目              → 进第一个项目
      6. 默认                → 停在 dashboard
    """
    precondition = (scenario.get("precondition") or "").lower()
    name = (scenario.get("name") or "").lower()
    text = precondition + " " + name
    first_target = ""
    if scenario.get("steps"):
        first_target = (scenario["steps"][0].get("target") or "").lower()

    # 「已登录」类前置绝不是登录测试，避免修改密码/邮箱（首步是 password/email 输入）
    # 被 first_target 启发式误判为登录测试而跳过登录。
    already_logged_in = any(kw in precondition for kw in
                            ["已登录", "登录后", "logged in", "已经登录"])
    is_login_test = (not already_logged_in) and (
        any(_contains_keyword(precondition, kw) for kw in _LOGIN_TEST_KW)
        or any(kw in first_target for kw in
               ["input[name='emailorusername']", "input[type='password']", "input[type='email']"])
    )

    proj_kw   = any(_contains_keyword(text, kw) for kw in _PROJECT_KW)
    board_kw  = any(_contains_keyword(text, kw) for kw in _BOARD_KW)
    card_kw   = any(_contains_keyword(text, kw) for kw in _CARD_KW)
    list_kw   = any(_contains_keyword(text, kw) for kw in _LIST_KW)
    proj_settings_trigger = any(_contains_keyword(text, kw) for kw in _PROJECT_SETTINGS_TRIGGER)
    user_settings_kw = any(_contains_keyword(text, kw) for kw in _USER_SETTINGS_KW)
    project_creation = any(_contains_keyword(text, kw) for kw in _PROJECT_CREATION_KW)

    # 「项目设置 / 项目成员」：出现“项目”且有设置/成员/名称等触发词，但本质不是看板/卡片操作
    needs_project_settings = proj_kw and proj_settings_trigger and not (list_kw or card_kw)

    # 结果（互斥）
    needs_settings = needs_project_settings_flag = False
    needs_project = needs_board = needs_list = needs_card = False
    settings_section = None

    if is_login_test:
        pass
    elif needs_project_settings:
        needs_project = needs_board = needs_project_settings_flag = True
    elif board_kw:
        needs_project = needs_board = True
        needs_list = list_kw or card_kw
        needs_card = card_kw
    elif user_settings_kw:
        needs_settings = True
        settings_section = _settings_section(text)
    elif proj_kw and not project_creation:
        needs_project = True

    return {
        "is_login_test":          is_login_test,
        "needs_settings":         needs_settings,
        "settings_section":       settings_section,
        "needs_project_settings": needs_project_settings_flag,
        "needs_project":          needs_project,
        "needs_board":            needs_board,
        "needs_list":             needs_list,
        "needs_card":             needs_card,
    }


def _settings_section(text: str) -> str | None:
    """
    从场景文字推断该进入的 Settings 子页（真实左侧导航项）：
      - 密码 → Authentication（Edit Password 在此）
      - 邮箱 / 用户名 / 账户 → Account（Edit Email / Edit Username 在此）
      - 资料 / 姓名 / 电话 / 组织 → Profile
      - 用户管理 → Users
    """
    low = text.lower()
    if any(_contains_keyword(low, kw) for kw in ["密码", "password"]):
        return "Authentication"
    if any(_contains_keyword(low, kw) for kw in ["邮箱", "email", "用户名", "username", "账户", "account"]):
        return "Account"
    if any(_contains_keyword(low, kw) for kw in ["用户管理", "users"]):
        return "Users"
    if any(_contains_keyword(low, kw) for kw in ["资料", "姓名", "电话", "组织", "profile", "phone", "organization"]):
        return "Profile"
    return None


def plan_steps(scenario: dict, app_url: str, username: str, password: str) -> list[dict]:
    """
    构建完整可执行步骤序列（纯函数）：
      导航 → [登录] → [打开 Settings | 进入项目 [→ 打开看板]] → 稳定化后的场景步骤
    场景步骤会先经过 rewrite_fixed_name_step，最后整体 dedup 自动导航。
    """
    kind = classify_precondition(scenario)
    steps: list[dict] = []

    # ① 打开应用
    steps.append({"action": "navigate", "target": app_url, "value": app_url,
                  "description": f"打开目标应用 {app_url}", "_auto": True})

    # ② 登录（登录测试场景跳过）
    if not kind["is_login_test"]:
        steps.append({"action": "login", "target": "login_form",
                      "value": f"{username}|{password}",
                      "description": f"使用账号 {username} 登录", "_auto": True})

    # ③ 前置页面准备
    if kind["needs_settings"]:
        section = kind.get("settings_section") or ""
        steps.append({"action": "open_settings", "target": "", "value": section,
                      "description": f"打开用户设置（Settings{' / ' + section if section else ''}）",
                      "_auto": True})
    elif kind["needs_project_settings"]:
        # 项目设置：进项目 → 打开看板 → 点顶部 Project Settings（不是用户 Settings）
        steps.append({"action": "enter_first_project", "target": "", "value": "",
                      "description": "从仪表板进入第一个项目", "_auto": True})
        steps.append({"action": "open_first_board", "target": "", "value": "",
                      "description": "打开第一个看板", "_auto": True})
        steps.append({"action": "open_project_settings", "target": "", "value": "",
                      "description": "打开项目设置（Project Settings）", "_auto": True})
    elif kind["needs_project"]:
        steps.append({"action": "enter_first_project", "target": "", "value": "",
                      "description": "从仪表板进入第一个项目", "_auto": True})
        if kind["needs_board"]:
            steps.append({"action": "open_first_board", "target": "", "value": "",
                          "description": "打开第一个看板", "_auto": True})
        # 列表/卡片场景：保证看板里真的有列表（必要时创建），卡片场景再保证有卡片
        if kind["needs_list"]:
            steps.append({"action": "ensure_list_exists", "target": "", "value": "",
                          "description": "确保当前看板存在至少一个列表（无则创建）", "_auto": True})
        if kind["needs_card"]:
            steps.append({"action": "ensure_card_exists", "target": "", "value": "",
                          "description": "确保当前列表存在至少一张卡片（无则创建）", "_auto": True})

    # ④ 场景步骤（固定名称改写 + 幻觉 selector 归一化）
    scenario_steps = list(scenario.get("steps", []))

    # 非登录测试：setup 已经 navigate + login + 深入到项目/看板/列表/卡片。
    # 场景开头写死的 navigate（尤其是 /boards/<固定ID>、/projects/<固定ID> 这类深链）
    # 会把页面重置、丢弃刚准备好的状态，且固定 ID 在 demo 里多半已失效——直接剔除。
    setup_went_deep = (kind["needs_project"] or kind["needs_settings"]
                       or kind["needs_project_settings"])
    if not kind["is_login_test"] and setup_went_deep:
        while scenario_steps and (scenario_steps[0].get("action") or "").lower() == "navigate":
            scenario_steps.pop(0)
        scenario_steps = _drop_leading_manual_login_steps(scenario_steps)
    elif not kind["is_login_test"]:
        scenario_steps = _drop_leading_manual_login_steps(scenario_steps)
    if not kind["is_login_test"]:
        scenario_steps = [s for s in scenario_steps if not _is_stale_deep_navigation(s)]

    for s in scenario_steps:
        step = rewrite_fixed_name_step(dict(s))
        if not step.get("_stabilized"):     # 已改写为动态导航的步骤无需再归一化 target
            step = normalize_step(step)
        steps.append(step)

    # ⑤ 折叠重复的自动导航
    return dedup_auto_nav(steps)


def _drop_leading_manual_login_steps(steps: list[dict]) -> list[dict]:
    """
    非登录场景已经由 setup 自动登录。若场景开头又带一串手写登录表单步骤，
    删除这段开头，避免在 Dashboard/看板页继续找登录输入框。
    """
    out = list(steps)
    dropped = False
    while out and _looks_like_manual_login_step(out[0]):
        out.pop(0)
        dropped = True
    if dropped:
        while out and (out[0].get("action") or "").lower() == "wait" and _waits_for_dashboard(out[0]):
            out.pop(0)
    return out


def _looks_like_manual_login_step(step: dict) -> bool:
    action = (step.get("action") or "").lower()
    target = (step.get("target") or "").lower()
    desc = (step.get("description") or "").lower()
    blob = target + " " + desc
    if action == "navigate" and "/login" in target:
        return True
    if action == "input" and any(k in blob for k in [
        "emailorusername", "input[type='email']", 'input[type="email"',
        "input[type='password']", 'input[type="password"', "登录", "log in",
    ]):
        return True
    if action == "click" and any(k in blob for k in [
        "button[type='submit']", 'button[type="submit"', "log in", "登录",
    ]):
        return True
    return False


def _waits_for_dashboard(step: dict) -> bool:
    target = (step.get("target") or "").lower()
    desc = (step.get("description") or "").lower()
    return any(k in target + " " + desc for k in ["add project", "dashboard", "仪表板"])


def _is_stale_deep_navigation(step: dict) -> bool:
    action = (step.get("action") or "").lower()
    target = (step.get("target") or "").lower()
    if action != "navigate":
        return False
    return any(path in target for path in ["/boards/", "/projects/", "/cards/"])


# ══════════════════════════════════════════════════════════════════════════════
# 四、破坏性场景（污染共享 demo 账号）
# ══════════════════════════════════════════════════════════════════════════════

_DESTRUCTIVE_KEYWORDS = [
    "修改密码", "修改邮箱", "修改用户名", "修改项目名", "重命名", "改名",
    "删除", "移除", "delete", "remove", "rename",
    "change password", "change email", "update email", "update password",
    "currentpassword", "newpassword", "confirmnewpassword",
    "edit password", "edit email", "edit username",
]


def is_destructive_scenario(scenario: dict) -> bool:
    """
    判断场景是否会污染共享 demo 状态（改密码/邮箱/用户名、删除项目/看板/列表/卡片）。
    综合场景名、tags 与步骤动作/目标判断。
    """
    name = (scenario.get("name") or "").lower()
    tags = " ".join(scenario.get("tags", [])).lower()
    blob = name + " " + tags
    if any(kw in blob for kw in _DESTRUCTIVE_KEYWORDS):
        return True
    for s in scenario.get("steps", []):
        target = _plain_target(s.get("target", "")).lower().replace("_", "")
        desc   = (s.get("description", "") or "").lower()
        if any(kw in (target + " " + desc) for kw in _DESTRUCTIVE_KEYWORDS):
            return True
    return False


def unique_name(base: str) -> str:
    """给临时测试数据生成带时间戳的唯一名，便于隔离与清理。"""
    return f"{base}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
