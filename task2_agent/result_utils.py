"""
task2_agent/result_utils.py

结果分类与失败原因归因的纯函数集合（无浏览器 / 无 LLM 依赖，方便单测）。

两层分类：
  1. 结果类别 RESULT_CATEGORIES = PASS / FAIL / ERROR / BLOCKED
     - PASS    功能验证通过
     - FAIL    功能验证未通过（产品问题或用例问题）
     - ERROR   执行环境异常（浏览器启动失败、运行时异常），非产品失败
     - BLOCKED 前置条件不满足无法执行（如缺测试数据文件），非产品失败
  2. 失败原因归因 FAILURE_REASONS：把 FAIL/ERROR/BLOCKED 归到根因大类，
     便于验收报告解释「为什么失败」，而不是只显示 PASS/FAIL。
"""
from pathlib import Path

from task2_agent.stability import KNOWN_FIXED_NAMES, is_destructive_scenario

RESULT_CATEGORIES = ["PASS", "FAIL", "ERROR", "BLOCKED"]

# 上传类动作：其 value 指向本地文件
_UPLOAD_ACTIONS = {"setinputfiles", "set_input_files", "upload", "upload_file"}

_ACCOUNT_MUTATION_MARKERS = (
    "currentpassword",
    "newpassword",
    "confirmnewpassword",
    "edit password",
    "edit email",
    "edit username",
    "修改密码",
    "修改邮箱",
    "修改用户名",
    "change password",
    "change email",
    "change username",
    "update password",
    "update email",
    "update username",
)

# 失败原因大类（对外展示用的中文标签）
REASON_MISSING_DATA   = "测试数据缺失"
REASON_FIXED_NAME     = "固定项目/看板名不存在"
REASON_BAD_SELECTOR   = "selector 不贴合真实 DOM"
REASON_SHARED_ACCOUNT = "demo 共享账号状态污染"
REASON_PRECONDITION   = "前置条件不满足"
REASON_ENV_ERROR      = "浏览器/环境错误"
REASON_OTHER          = "其它失败"
REASON_PASS           = "通过"


def _selector_like(target: str) -> bool:
    """粗略判断 target 是否像 CSS selector（而非纯文本 / text= 定位）。"""
    t = (target or "").strip()
    if not t:
        return False
    if t.lower().startswith("text="):
        return False
    return any(c in t for c in "[].#>") or "name=" in t


def detect_blocked_reason(scenario: dict) -> str | None:
    """
    执行前静态检查：若场景注定无法执行（缺少上传文件），返回 BLOCKED 原因文本。
    目前覆盖：上传类步骤引用的本地文件不存在（如 Trello JSON 缺失）。
    返回 None 表示未发现阻塞条件。
    """
    if _is_shared_account_mutation(scenario):
        return "高风险破坏性场景：会修改共享 demo 账号密码/邮箱/用户名，已阻塞执行"

    for step in scenario.get("steps", []):
        action = (step.get("action") or "").lower()
        if action in _UPLOAD_ACTIONS:
            file_path = str(step.get("value") or "").strip()
            if not file_path:
                continue
            p = Path(file_path).expanduser()
            if not p.is_absolute():
                p = Path.cwd() / p
            if not p.exists():
                return f"测试数据缺失：上传文件不存在 {file_path}"
    return None


def _is_shared_account_mutation(scenario: dict) -> bool:
    """识别会污染共享 demo 登录凭据的场景，防止再次把 demo 密码改掉。"""
    fields = [
        scenario.get("name") or "",
        scenario.get("scenario_name") or "",
        scenario.get("precondition") or "",
        " ".join(scenario.get("tags", [])),
    ]
    for step in scenario.get("steps", []):
        fields.extend([
            step.get("action") or "",
            step.get("target") or "",
            step.get("value") or "",
            step.get("description") or "",
        ])
    blob = " ".join(fields).lower().replace("_", "")
    return any(marker in blob for marker in _ACCOUNT_MUTATION_MARKERS)


def failed_actions(result: dict) -> list[dict]:
    """从结果 dict 里取出失败的执行步骤（success 为假）。"""
    return [a for a in result.get("actions", []) if not a.get("success")]


def classify_failure_reason(result: dict) -> str:
    """
    对单个场景结果做根因归类，返回 FAILURE_REASONS 之一。
    PASS → REASON_PASS。其余按优先级归到最可能的根因大类。
    """
    status = result.get("result", "")
    if status == "PASS":
        return REASON_PASS

    # ERROR：环境 / 浏览器问题
    if status == "ERROR":
        return REASON_ENV_ERROR

    # BLOCKED：多为测试数据缺失
    if status == "BLOCKED":
        summary = (result.get("summary", "") or "")
        if "文件" in summary or "数据" in summary or "trello" in summary.lower():
            return REASON_MISSING_DATA
        return REASON_PRECONDITION

    # 以下为 FAIL：结合场景名 + 失败步骤 target / error 归因
    name = (result.get("scenario_name", "") or "").lower()
    fails = failed_actions(result)

    # 1) 上传/数据类错误（error_msg 提到文件不存在）
    for a in fails:
        err = (a.get("error_msg", "") or "").lower()
        if "文件不存在" in err or "no such file" in err or "上传文件" in err:
            return REASON_MISSING_DATA

    # 2) 固定项目/看板名不存在
    for a in fails:
        tgt = (a.get("target", "") or "").lower()
        stripped = tgt.replace("text=", "").strip("'\" ")
        if any(fixed in stripped for fixed in KNOWN_FIXED_NAMES):
            return REASON_FIXED_NAME

    # 3) selector 不贴合真实 DOM
    for a in fails:
        if _selector_like(a.get("target", "")):
            return REASON_BAD_SELECTOR

    # 4) demo 共享账号状态污染（破坏性场景）
    if is_destructive_scenario({"name": result.get("scenario_name", ""),
                                "steps": result.get("actions", [])}):
        return REASON_SHARED_ACCOUNT

    # 5) 前置条件不满足（早期导航 / 进入项目步骤失败）
    for a in fails:
        act = (a.get("action", "") or "").lower()
        if act in ("enter_first_project", "open_first_board", "navigate", "login"):
            return REASON_PRECONDITION

    return REASON_OTHER


def summarize(results: list[dict]) -> dict:
    """
    汇总一批结果：各结果类别计数 + 失败原因分类计数 + 通过率。
    通过率分母排除 ERROR / BLOCKED（非产品失败不计入功能通过率）。
    """
    by_category = {c: 0 for c in RESULT_CATEGORIES}
    by_reason: dict[str, int] = {}
    for r in results:
        status = r.get("result", "")
        if status in by_category:
            by_category[status] += 1
        reason = classify_failure_reason(r)
        if reason != REASON_PASS:
            by_reason[reason] = by_reason.get(reason, 0) + 1

    total = len(results)
    passed = by_category["PASS"]
    # 功能通过率：仅在 PASS + FAIL 之间计算（排除 ERROR / BLOCKED）
    functional = by_category["PASS"] + by_category["FAIL"]
    pass_rate = (passed / functional) if functional else 0.0

    return {
        "total":        total,
        "by_category":  by_category,
        "by_reason":    by_reason,
        "pass_rate":    pass_rate,
    }
