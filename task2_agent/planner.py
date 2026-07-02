"""
task2_agent/planner.py
规划器：将测试场景转换为可执行步骤序列，执行失败时请求 LLM 给出备选方案
"""

import json
import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rich.console import Console

from llm_client import LLMClient, DEFAULT_BASE_URL

console = Console(legacy_windows=False)


ADAPT_PROMPT = """\
Web 自动化测试执行时某个步骤失败。请基于当前页面**实际可见的按钮/链接文本**给出备选方案。

## 当前场景
{scenario_name}

## 已执行步骤
{executed}

## 失败步骤（target 字段没有匹配到任何元素）
{failed_step}

## 错误信息
{error_msg}

## 当前页面 URL
{current_url}

## 当前页面可见的按钮/链接文本（按出现顺序）
{visible_texts}

## 任务
- 仔细对比"失败步骤的 target"与上面的"可见文本列表"，找出**语义最接近**的真实按钮文本
- target 字段必须是 CSS selector 或上面列表中的**英文文本**，不要中文
- **不要返回 wait/sleep**，因为单纯等待无法替代失败的点击/输入动作
- 给出 1~2 个备选

只输出 JSON 数组，不要其他内容：
```json
[
  {{
    "action": "click|input|navigate|press",
    "target": "CSS selector 或英文文本（必须出现在上面的可见文本列表中）",
    "value":  "",
    "description": "备选方案说明"
  }}
]
```
"""


class Planner:
    """测试规划器"""

    def __init__(self, api_key: str, model: str, base_url: str = DEFAULT_BASE_URL):
        self.llm   = LLMClient(api_key=api_key, model=model, base_url=base_url)
        self.model = model

    # ── precondition 关键词 ──────────────────────────────────────────────────
    # 用于判断场景需要的页面深度（dashboard / project / board）
    _LOGIN_TEST_KW   = ["登录页", "登录界面", "登录前", "未登录", "login page", "not logged"]
    _PROJECT_KW      = ["项目", "project"]
    _BOARD_KW        = ["看板", "board", "列表", "list", "卡片", "card"]
    _DASHBOARD_KW    = ["仪表板", "仪表盘", "dashboard", "首页", "home"]

    def _contains_keyword(self, text: str, keyword: str) -> bool:
        """英文关键词按完整单词匹配，避免 dashboard 被 board 误命中。"""
        if not text or not keyword:
            return False
        if re.search(r"[a-zA-Z]", keyword):
            return re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE) is not None
        return keyword in text

    def prepare_steps(self,
                      scenario: dict,
                      app_url:  str,
                      username: str,
                      password: str) -> list[dict]:
        """
        在场景步骤前自动插入导航 / 登录 / 进入项目 / 打开看板 / 打开 Settings，并对
        场景步骤做稳定化改写（固定项目/看板名 → 动态导航），最后折叠重复的自动导航。

        具体规则见 task2_agent.stability.plan_steps（纯函数，便于单测）：
          - "已登录页面" / "未登录"        → 只 navigate，不 login（让场景自己测登录）
          - precondition/名称含"设置/密码/邮箱" → navigate + login + 打开 Settings 弹窗
          - precondition 含"项目"          → navigate + login + 进入第一个项目
          - precondition 含"看板/列表/卡片"  → navigate + login + 进项目 + 开看板
          - 默认                           → navigate + login（停在 dashboard）
        """
        from task2_agent.stability import plan_steps
        return plan_steps(scenario, app_url, username, password)

    def get_alternatives(self,
                         scenario_name: str,
                         executed:      list[dict],
                         failed_step:   dict,
                         current_url:   str,
                         error_msg:     str,
                         visible_texts: list[str] | None = None) -> list[dict]:
        """
        步骤失败时调用 LLM，获取备选操作方案。
        visible_texts: 当前页面可见的按钮/链接文本列表，帮助 LLM 选出真实存在的目标。
        """
        executed_text = "\n".join(
            f"  {i+1}. [{s.get('action')}] {s.get('description', '')}"
            for i, s in enumerate(executed)
        ) or "（无）"

        vt_text = "\n".join(f"  - {t}" for t in (visible_texts or [])) or "  （未提供）"

        prompt = ADAPT_PROMPT.format(
            scenario_name=scenario_name,
            executed=executed_text,
            failed_step=json.dumps(failed_step, ensure_ascii=False),
            error_msg=error_msg,
            current_url=current_url,
            visible_texts=vt_text,
        )

        try:
            text  = self.llm.generate(prompt, max_tokens=800)
            match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)
            return json.loads(text.strip())
        except Exception as e:
            console.print(f"[yellow]规划器备选方案获取失败: {e}[/yellow]")
            return []
