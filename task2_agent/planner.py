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

    def prepare_steps(self,
                      scenario: dict,
                      app_url:  str,
                      username: str,
                      password: str) -> list[dict]:
        """
        在场景步骤前自动插入：导航到应用 + 登录。
        返回完整的可执行步骤列表。
        """
        steps = []

        # 自动前置：打开应用
        steps.append({
            "action":      "navigate",
            "target":      app_url,
            "value":       app_url,
            "description": f"打开目标应用 {app_url}",
            "_auto":       True,
        })

        # 自动前置：登录
        steps.append({
            "action":      "login",
            "target":      "login_form",
            "value":       f"{username}|{password}",
            "description": f"使用账号 {username} 登录",
            "_auto":       True,
        })

        # 场景本身的步骤
        for s in scenario.get("steps", []):
            steps.append(dict(s))

        return steps

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
