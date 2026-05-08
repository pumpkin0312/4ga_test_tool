"""
task2_agent/memory.py
智能体记忆模块：维护单个场景的执行轨迹，以及跨场景的全局状态
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ══════════════════════════════════════════════════════════════════════════════
# 单步操作记录
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ActionRecord:
    step_index:      int
    action:          str
    target:          str
    value:           str
    description:     str
    success:         bool
    screenshot_path: str  = ""
    page_url:        str  = ""
    page_title:      str  = ""
    error_msg:       str  = ""
    timestamp:       str  = field(default_factory=lambda: datetime.now().isoformat())


# ══════════════════════════════════════════════════════════════════════════════
# 单个场景的记忆
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScenarioMemory:
    """记录一个测试场景从开始到结束的完整上下文"""

    scenario_id:   str
    scenario_name: str
    start_time:    str = field(default_factory=lambda: datetime.now().isoformat())
    end_time:      str = ""

    # 执行轨迹
    actions: list[ActionRecord] = field(default_factory=list)

    # 当前浏览器状态
    current_url:   str = ""
    current_title: str = ""

    # 中间变量（如创建的资源名称，供后续验证步骤使用）
    context_vars: dict[str, Any] = field(default_factory=dict)

    # 文字日志
    logs: list[str] = field(default_factory=list)

    # ── 操作 ──────────────────────────────────────────────────────────────────

    def add_action(self, record: ActionRecord):
        self.actions.append(record)
        status = "✓" if record.success else "✗"
        msg = f"[步骤 {record.step_index}] {status} {record.description}"
        if record.error_msg:
            msg += f"  |  错误: {record.error_msg}"
        self.logs.append(msg)

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.logs.append(f"[{ts}] {msg}")

    def set_var(self, key: str, value: Any):
        self.context_vars[key] = value

    def get_var(self, key: str, default=None):
        return self.context_vars.get(key, default)

    # ── 统计 ──────────────────────────────────────────────────────────────────

    def success_rate(self) -> float:
        if not self.actions:
            return 0.0
        return sum(1 for a in self.actions if a.success) / len(self.actions)

    def failed_actions(self) -> list[ActionRecord]:
        return [a for a in self.actions if not a.success]

    # ── 供 Verifier 使用的轨迹摘要 ───────────────────────────────────────────

    def trajectory_summary(self) -> str:
        """生成文字版执行轨迹，提供给 LLM 做综合验证"""
        lines = [
            f"场景: {self.scenario_name}",
            f"总步骤: {len(self.actions)}  |  "
            f"成功: {sum(1 for a in self.actions if a.success)}  |  "
            f"失败: {sum(1 for a in self.actions if not a.success)}",
            "",
        ]
        for a in self.actions:
            status = "成功" if a.success else f"失败（{a.error_msg}）"
            lines.append(f"  步骤 {a.step_index}: [{a.action}] {a.description} → {status}")
            if a.page_url:
                lines.append(f"    URL: {a.page_url}")
        return "\n".join(lines)

    # ── 序列化 ────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "scenario_id":   self.scenario_id,
            "scenario_name": self.scenario_name,
            "start_time":    self.start_time,
            "end_time":      self.end_time,
            "current_url":   self.current_url,
            "context_vars":  self.context_vars,
            "success_rate":  self.success_rate(),
            "actions": [
                {
                    "step_index":      a.step_index,
                    "action":          a.action,
                    "target":          a.target,
                    "description":     a.description,
                    "success":         a.success,
                    "error_msg":       a.error_msg,
                    "screenshot_path": a.screenshot_path,
                    "page_url":        a.page_url,
                    "timestamp":       a.timestamp,
                }
                for a in self.actions
            ],
            "logs": self.logs,
        }


# ══════════════════════════════════════════════════════════════════════════════
# 全局智能体记忆
# ══════════════════════════════════════════════════════════════════════════════

class AgentMemory:
    """跨场景的全局记忆：管理登录状态、所有场景的执行历史"""

    def __init__(self):
        self.sessions: dict[str, ScenarioMemory] = {}
        self.login_state = {
            "logged_in":       False,
            "username":        "",
            "current_project": "",
            "current_board":   "",
        }

    def new_session(self, scenario_id: str, scenario_name: str) -> ScenarioMemory:
        mem = ScenarioMemory(scenario_id=scenario_id, scenario_name=scenario_name)
        self.sessions[scenario_id] = mem
        return mem

    def get_session(self, scenario_id: str) -> ScenarioMemory | None:
        return self.sessions.get(scenario_id)

    def set_login_state(self, **kwargs):
        self.login_state.update(kwargs)

    def is_logged_in(self) -> bool:
        return self.login_state.get("logged_in", False)

    def all_results(self) -> list[dict]:
        return [mem.to_dict() for mem in self.sessions.values()]
