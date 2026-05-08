"""
task2_agent/verifier.py
验证器：
  1. 规则验证  — 在浏览器中直接检查预期条件（快速、确定）
  2. LLM 验证  — 把完整执行轨迹交给 Claude 做综合判断（准确、有解释）
"""

import json
import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from rich.console import Console

from llm_client import LLMClient, DEFAULT_BASE_URL

console = Console(legacy_windows=False)


VERIFY_PROMPT = """\
你是一名专业的软件测试验证专家。请根据以下信息判断测试场景是否执行成功。

## 测试场景
名称: {scenario_name}
前置条件: {precondition}

## 预期步骤
{steps}

## 测试预期及**规则验证实际结果**（在浏览器中真实检查得到）
{expectations}

## 实际执行轨迹
{trajectory}

## 执行统计
- 总步骤: {total}，成功: {success}，失败: {failed}
- 最终页面 URL: {final_url}

## 判断规则（**严格优先级**）
1. **【最重要】**：若【规则验证实际结果】中所有预期都未通过（verified=false）→ **必须判 FAIL**
   原因：步骤"成功"只是说点击/输入没报错，并不等于功能真的完成；
   只有最终状态可观测特征（按钮消失、新元素出现）才能证明功能完成
2. 若部分预期通过、部分未通过 → 视核心预期是否通过决定，倾向保守（FAIL）
3. 若所有预期都通过 → PASS
4. 关键步骤被备选方案"救活"时要警惕：备选目标可能与原意图不一致（如点了同名但语义不同的按钮）

## 输出
请输出 JSON，不要其他内容：
```json
{{
  "result":     "PASS 或 FAIL",
  "confidence": 0.0到1.0之间的浮点数,
  "summary":    "一句话总结（必须基于实际验证结果，而非步骤通过率）",
  "expectation_results": [
    {{
      "expectation": "预期描述",
      "verified":    true或false（必须与规则验证结果一致，不能拍脑袋）,
      "comment":     "简短备注"
    }}
  ],
  "issues":      ["发现的问题"],
  "suggestions": ["改进建议"]
}}
```
"""


class Verifier:
    """测试结果验证器"""

    def __init__(self, api_key: str, model: str, base_url: str = DEFAULT_BASE_URL):
        self.llm   = LLMClient(api_key=api_key, model=model, base_url=base_url)
        self.model = model

    # ══════════════════════════════════════════════════════════════════════════
    # 规则验证：直接在浏览器中检查预期条件
    # ══════════════════════════════════════════════════════════════════════════

    def verify_expectation(self, executor, expectation: dict) -> bool:
        """
        用规则方式验证单个预期条件，无需调用 LLM。
        支持的 condition: visible / not_visible / url_contains /
                          text_contains / text_equals /
                          count_equals / count_greater_than /
                          page_title_contains
        """
        condition = expectation.get("condition", "").lower()
        target    = expectation.get("target", "")
        value     = expectation.get("value",  "")

        try:
            if condition == "visible":
                return self._is_visible_robust(executor, target, value)

            elif condition == "not_visible":
                return not self._is_visible_robust(executor, target, value)

            elif condition == "url_contains":
                return value.lower() in executor.get_url().lower()

            elif condition == "text_contains":
                return value.lower() in executor.get_text(target).lower()

            elif condition == "text_equals":
                return executor.get_text(target).strip() == value.strip()

            elif condition == "count_equals":
                return executor.count(target) == int(value)

            elif condition == "count_greater_than":
                return executor.count(target) > int(value)

            elif condition == "page_title_contains":
                return value.lower() in executor.get_title().lower()

            else:
                # 未知条件：降级为 visible 检查
                console.print(f"[yellow]未知验证条件 '{condition}'，降级为 visible[/yellow]")
                return executor.is_visible(target)

        except Exception as e:
            console.print(f"[yellow]规则验证异常: {e}[/yellow]")
            return False

    # ── 鲁棒可见性检查 ────────────────────────────────────────────────────────

    def _is_visible_robust(self, executor, target: str, value: str = "") -> bool:
        """
        兼容 LLM 写出的各种 selector 形式：
          - "text='Foo'"   → 用文本搜索
          - "Add Project"   → 当作可见文本
          - CSS selector    → 直接调 executor.is_visible
        若 value 非空且 condition 是 visible/text_contains，也用 value 当文本兜底。
        """
        candidates = []
        t = (target or "").strip()
        v = (value or "").strip()

        # 1) 标准 CSS / 文本 selector
        if t:
            candidates.append(t)

        # 2) "text='Foo'" 或 "text=Foo" → 提取里面的文本，再用 _find 找
        import re as _re
        m = _re.match(r"^text\s*=\s*['\"]?(.+?)['\"]?$", t)
        if m:
            candidates.append(m.group(1).strip())

        # 3) 如果 value 提供了文本（如期望某个项目名出现），也试试
        if v and v not in candidates:
            candidates.append(v)

        for c in candidates:
            try:
                if executor.is_visible(c):
                    return True
            except Exception:
                pass
            # 文本类候选用 _find 更鲁棒
            try:
                el = executor._find(c, timeout=2000)
                if el:
                    return True
            except Exception:
                pass
        return False

    # ══════════════════════════════════════════════════════════════════════════
    # LLM 验证：综合执行轨迹做整体判断
    # ══════════════════════════════════════════════════════════════════════════

    def verify_with_llm(self, scenario: dict, memory, inline_results: list[dict] | None = None) -> dict:
        """
        将完整执行轨迹交给 LLM 判断测试是否通过。
        scenario       : 原始测试场景 dict
        memory         : ScenarioMemory 对象
        inline_results : 规则验证的实际结果 [{expectation, inline_pass}, ...]
        返回标准化的验证结果 dict
        """
        steps_text = "\n".join(
            f"  {i+1}. [{s.get('action')}] {s.get('description', '')}"
            for i, s in enumerate(scenario.get("steps", []))
        )

        # 把规则验证的实际结果合并到预期描述里，让 LLM 看到「真实」与「期望」的对比
        inline_map = {r.get("expectation", ""): r.get("inline_pass") for r in (inline_results or [])}
        exp_lines = []
        for e in scenario.get("expectations", []):
            desc = e.get("description", "")
            actual = inline_map.get(desc)
            actual_text = ("✓ 通过" if actual else "✗ 未通过") if actual is not None else "未检查"
            exp_lines.append(
                f"  - [{e.get('condition')}] {desc}\n"
                f"      期望值: {e.get('value', '')}\n"
                f"      规则验证实际结果: {actual_text}"
            )
        exp_text = "\n".join(exp_lines) or "  （无）"

        total   = len(memory.actions)
        success = sum(1 for a in memory.actions if a.success)
        failed  = total - success

        prompt = VERIFY_PROMPT.format(
            scenario_name=scenario.get("name", ""),
            precondition=scenario.get("precondition", "无"),
            steps=steps_text   or "（无）",
            expectations=exp_text or "（无）",
            trajectory=memory.trajectory_summary(),
            total=total,
            success=success,
            failed=failed,
            final_url=memory.current_url,
        )

        try:
            text  = self.llm.generate(prompt, max_tokens=2000)
            match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                text = match.group(1)
            result = json.loads(text.strip())

            label = result.get("result", "?")
            conf  = result.get("confidence", 0)
            color = "green" if label == "PASS" else "red"
            console.print(f"  [bold {color}]LLM 验证: {label}[/]  置信度 {conf:.0%}  —  {result.get('summary','')}")
            return result

        except Exception as e:
            console.print(f"[red]LLM 验证失败: {e}，使用步骤成功率降级判断[/red]")
            rate = success / total if total > 0 else 0
            return {
                "result":               "PASS" if rate >= 0.7 else "FAIL",
                "confidence":           rate,
                "summary":              f"步骤成功率 {rate:.0%}（LLM 不可用，降级判断）",
                "expectation_results":  [],
                "issues":               [f"LLM 验证调用失败: {e}"],
                "suggestions":          [],
            }
