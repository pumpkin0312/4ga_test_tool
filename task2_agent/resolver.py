"""
task2_agent/resolver.py
PageResolver —— 「执行前主动读取页面」组件

工作模式（三阶段）：
1. 阶段 1（免费快通道）：用 executor._find() 校验 step.target 是否能直接定位
                          能 → 原样放行
2. 阶段 2（一次 LLM 调用）：找不到时，抓页面可交互元素快照，让 LLM 从中选出
                          语义最接近 step.target 的元素，重写 step.target
3. 阶段 3（兜底）：阶段 2 给出的新 target 仍可能错，由调用方（agent）继续走原有
                  的「步骤失败 → planner.get_alternatives」备选逻辑

设计目标：解决 LLM 在生成场景时对实际页面 DOM 的"幻觉"问题，但不让每步都
昂贵地调用 LLM。
"""

import json
import re

from rich.console import Console

from llm_client import LLMClient, DEFAULT_BASE_URL

console = Console(legacy_windows=False)


# 不涉及具体元素定位的 action：跳过 resolver（直接放行）
_NO_RESOLVE_ACTIONS = {
    "navigate", "wait", "sleep", "press",
    "setinputfiles", "set_input_files", "upload", "upload_file",
    "login", "enter_first_project", "open_first_board", "open_settings",
    "open_project_settings", "ensure_list_exists", "ensure_card_exists",
    "open_first_card",  # planner 注入的虚拟动作
}


REDIRECT_PROMPT = """\
你是一个 Web 测试自动化助手。原始测试步骤里的 target 无法在当前页面定位到任何元素，
请基于"页面元素快照"找到**语义最匹配**的真实元素，给出可被 Playwright 直接使用的
新 target。

## 原始步骤
- action: {action}
- target: {target}
- value:  {value}
- 描述:   {description}

## 当前页面元素快照（kind / text / placeholder / aria_label / name / in_dialog）
{snapshot}

## 重定向规则（按优先级）
1. action=input → 在 kind=input 的元素中选最匹配的（按 name / placeholder / aria_label）
   返回形式优先级：`input[name='X']` > `[placeholder='X']` > `[aria-label='X']`
2. action=click/hover → 在 kind=button/link/menuitem 中选最匹配的
   返回元素的精确 text（不带引号），让框架用 get_by_role 定位
3. 若当前页面有对话框打开（任何元素 in_dialog=true），**优先选 in_dialog=true 的候选**
4. 若快照里完全没有匹配的元素，返回空字符串
5. 不要编造快照里不存在的文本/属性

## 输出
只输出一行 JSON，不要任何解释：
```json
{{"new_target": "...", "reason": "为什么选这个"}}
```
"""


class PageResolver:
    """执行前对 step.target 做一次"睁眼"校验/重定向"""

    def __init__(self, api_key: str, model: str, base_url: str = DEFAULT_BASE_URL):
        self.llm = LLMClient(api_key=api_key, model=model, base_url=base_url)

    def resolve(self, executor, step: dict) -> dict:
        """
        若需要重定向，返回新的 step（拷贝后修改 target）；否则返回原 step。
        新 step 带 _resolved_by 标记，便于日志/调试。
        """
        action = (step.get("action") or "").lower()
        target = (step.get("target") or "").strip()
        if action in _NO_RESOLVE_ACTIONS or not target:
            return step

        # 阶段 1：快通道——能找到就直接放行（不调 LLM）
        try:
            if executor._find(target, timeout=1500):
                return step
        except Exception:
            pass

        # 阶段 2：抓快照 → LLM 重定向
        snapshot = executor.snapshot_interactive_elements(limit=60)
        if not snapshot:
            return step  # 拿不到快照就放行，让原逻辑跑

        new_target = self._ask_llm(action, target, step, snapshot)
        if not self._is_useful_redirect(target, new_target):
            return step

        # 在新 target 上再做一次快通道校验，避免 LLM 自己也产幻觉
        try:
            if not executor._find(new_target, timeout=1500):
                # 新 target 也找不到——放弃重写，留给 planner 备选
                return step
        except Exception:
            return step

        new_step = dict(step)
        new_step["target"]       = new_target
        new_step["_resolved_by"] = "page-resolver"
        console.print(
            f"  [cyan]🔍 重定向 target:[/cyan] {target!r} → {new_target!r}"
        )
        return new_step

    # ── 质量守门：过滤垃圾重定向 ─────────────────────────────────────────────

    # 通用 HTML 标签名 / 过于宽泛的词，作为 target 没有定位价值
    _USELESS_TARGETS = {
        "input", "button", "div", "span", "a", "form", "link",
        "textarea", "select", "label", "li", "ul", "ol", "tr", "td",
    }

    def _is_useful_redirect(self, old: str, new: str) -> bool:
        """判断 LLM 给的重定向是否值得采纳"""
        if not new:
            return False
        if new.strip().lower() == old.strip().lower():
            return False                              # 跟原 target 一样
        if len(new) < 3:
            return False                              # 太短，多半是垃圾
        if new.lower() in self._USELESS_TARGETS:
            return False                              # 通用标签名
        return True

    # ── 内部：调 LLM ─────────────────────────────────────────────────────────

    def _ask_llm(self,
                 action:   str,
                 target:   str,
                 step:     dict,
                 snapshot: list[dict]) -> str:
        """构造 prompt 调用 LLM，返回模型给出的 new_target 字符串"""
        # 压缩快照（避免 prompt 过长）
        snap_lines = []
        for el in snapshot:
            extras = []
            if el.get("text"):        extras.append(f"text={el['text']!r}")
            if el.get("placeholder"): extras.append(f"placeholder={el['placeholder']!r}")
            if el.get("aria_label"):  extras.append(f"aria_label={el['aria_label']!r}")
            if el.get("name"):        extras.append(f"name={el['name']!r}")
            if el.get("type"):        extras.append(f"type={el['type']!r}")
            in_dlg = " [dialog]" if el.get("in_dialog") else ""
            snap_lines.append(f"  - {el.get('kind','?'):8s} {'  '.join(extras)}{in_dlg}")
        snap_text = "\n".join(snap_lines) or "  （快照为空）"

        prompt = REDIRECT_PROMPT.format(
            action=action,
            target=target,
            value=step.get("value", ""),
            description=step.get("description", ""),
            snapshot=snap_text,
        )

        try:
            text  = self.llm.generate(prompt, max_tokens=400, temperature=0.1)
            match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)
            # 兜底：直接找第一个 { ... }
            m2 = re.search(r"\{[^{}]*\}", text)
            if m2:
                text = m2.group(0)
            data = json.loads(text.strip())
            return (data.get("new_target") or "").strip()
        except Exception as e:
            console.print(f"[yellow]PageResolver LLM 解析失败: {e}[/yellow]")
            return ""
