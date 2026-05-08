"""
task2_agent/agent.py
Web 测试智能体主控：协调 Planner / Memory / Executor / Verifier 完成测试
"""

import json
import time
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table

console = Console(legacy_windows=False)


class TestAgent:
    """
    Web 测试智能体
    数据流：
      场景 JSON
        → Planner.prepare_steps()        构建完整步骤序列
        → Executor.execute_step() × N    逐步在浏览器执行
        → Memory.add_action() × N        记录每步结果
        → Verifier.verify_expectation()  规则验证预期条件
        → Verifier.verify_with_llm()     LLM 综合判断
        → 结果 dict
    """

    def __init__(self, config: dict):
        self.cfg      = config
        api_key       = config["api_key"]
        model         = config["model"]
        base_url      = config.get("base_url", "")

        from task2_agent.planner  import Planner
        from task2_agent.memory   import AgentMemory
        from task2_agent.executor import BrowserExecutor
        from task2_agent.verifier import Verifier
        from llm_client           import DEFAULT_BASE_URL

        base_url = base_url or DEFAULT_BASE_URL
        self.planner  = Planner(api_key, model, base_url=base_url)
        self.memory   = AgentMemory()
        self.verifier = Verifier(api_key, model, base_url=base_url)
        self.executor = BrowserExecutor(
            target_url     = config["app_url"],
            screenshot_dir = config.get("screenshot_dir", "reports/screenshots"),
            headless       = config.get("headless", True),
            timeout        = config.get("timeout",   10000),
        )

        self.app_url   = config["app_url"]
        self.username  = config.get("username", "demo@demo.demo")
        self.password  = config.get("password", "demo")
        self.max_steps = config.get("max_steps", 20)
        self.take_ss   = config.get("screenshot", True)

        self._report_dir = Path(config.get("report_dir", "reports"))
        self._report_dir.mkdir(parents=True, exist_ok=True)

    # ══════════════════════════════════════════════════════════════════════════
    # 公共接口
    # ══════════════════════════════════════════════════════════════════════════

    def run_scenario(self, scenario: dict) -> dict:
        """执行单个测试场景，返回标准化结果 dict"""
        sid   = scenario.get("id",   "unknown")
        sname = scenario.get("name", "未命名场景")
        console.rule(f"[bold cyan]场景: {sname}[/bold cyan]")

        # 初始化场景记忆
        mem = self.memory.new_session(sid, sname)
        mem.log(f"开始执行: {sname}")

        # ── 1. 规划：生成完整步骤序列 ─────────────────────────────────────────
        steps = self.planner.prepare_steps(
            scenario, self.app_url, self.username, self.password
        )
        mem.log(f"规划完成，共 {len(steps)} 步")

        # ── 2. 启动浏览器 ──────────────────────────────────────────────────────
        try:
            self.executor.start()
        except Exception as e:
            mem.log(f"浏览器启动失败: {e}")
            return self._build_result(scenario, mem, {
                "result": "ERROR", "confidence": 0,
                "summary": f"浏览器启动失败: {e}",
                "expectation_results": [], "issues": [str(e)], "suggestions": [],
            })

        executed_steps: list[dict] = []
        consecutive_failures = 0
        MAX_CONSECUTIVE_FAILURES = 3   # 连续 3 步失败就放弃，避免单场景拖死全量

        try:
            # ── 3. 逐步执行 ───────────────────────────────────────────────────
            for i, step in enumerate(steps[: self.max_steps]):
                success, ss_path, error = self._run_one_step(step, i + 1)

                # 记录到记忆
                from task2_agent.memory import ActionRecord
                record = ActionRecord(
                    step_index      = i + 1,
                    action          = step.get("action", ""),
                    target          = step.get("target", ""),
                    value           = step.get("value",  ""),
                    description     = step.get("description", ""),
                    success         = success,
                    screenshot_path = ss_path,
                    page_url        = self.executor.get_url(),
                    page_title      = self.executor.get_title(),
                    error_msg       = error,
                )
                mem.add_action(record)
                mem.current_url = record.page_url
                executed_steps.append(step)

                # 非自动前置步骤失败 → 向 Planner 请求一次备选（只试一次，避免无限滚雪球）
                if not success and not step.get("_auto"):
                    console.print(f"  [yellow]步骤 {i+1} 失败，请求备选方案...[/yellow]")
                    visible = self.executor.list_clickable_texts(limit=40)
                    alternatives = self.planner.get_alternatives(
                        sname, executed_steps, step,
                        mem.current_url, error,
                        visible_texts=visible,
                    )
                    actionable = [
                        a for a in alternatives
                        if a.get("action", "").lower() not in ("wait", "sleep")
                    ]
                    if actionable:
                        alt = actionable[0]               # 只尝试第一个，避免链式失败拖时间
                        alt_ok, alt_ss, alt_err = self._run_one_step(alt, f"{i+1}b")
                        if alt_ok:
                            mem.log(f"备选方案成功: {alt.get('description','')}")
                            mem.actions[-1].success = True
                            success = True

                # 连续失败保护：避免一个场景卡死整个全量执行
                if success:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        mem.log(f"连续 {MAX_CONSECUTIVE_FAILURES} 步失败，提前终止本场景以节省时间")
                        console.print(f"  [red]连续 {MAX_CONSECUTIVE_FAILURES} 步失败，跳过剩余步骤[/red]")
                        break

                time.sleep(0.3)

            # ── 4. 规则验证预期条件 ───────────────────────────────────────────
            console.print("  [dim]规则验证预期条件...[/dim]")
            inline_results = []
            for exp in scenario.get("expectations", []):
                ok = self.verifier.verify_expectation(self.executor, exp)
                inline_results.append({
                    "expectation": exp.get("description", ""),
                    "inline_pass": ok,
                })
                mem.log(f"预期验证: {exp.get('description','')} → {'✓' if ok else '✗'}")

            mem.end_time = datetime.now().isoformat()

        except Exception as e:
            console.print(f"[red]执行异常: {e}[/red]")
            mem.log(f"执行异常: {e}")
            mem.end_time = datetime.now().isoformat()
            inline_results = []
        finally:
            self.executor.stop()

        # ── 5. LLM 综合验证（把规则验证的实际结果一并喂给 LLM）─────────────────
        console.print("  [dim]LLM 综合验证...[/dim]")
        verify_result = self.verifier.verify_with_llm(scenario, mem, inline_results=inline_results)

        # 兜底：若规则验证全部 false，强制降级为 FAIL（防止 LLM 看着步骤通过率拍 PASS）
        if inline_results and all(not r.get("inline_pass") for r in inline_results):
            if verify_result.get("result") == "PASS":
                verify_result["result"]  = "FAIL"
                verify_result["summary"] = "（强制降级）所有规则验证均未通过：" + verify_result.get("summary", "")
                console.print("  [red]规则验证全部失败，强制将结果降级为 FAIL[/red]")

        result = self._build_result(scenario, mem, verify_result)
        result["expectations_inline"] = inline_results
        result["logs"] = mem.logs
        return result

    def run_scenarios(self,
                      scenarios:         list[dict],
                      progress_callback = None) -> list[dict]:
        """批量执行测试场景；每完成一个就增量写盘，避免中断丢失。"""
        results = []
        ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
        partial_path = self._report_dir / f"test_report_{ts}_running.json"

        for i, scenario in enumerate(scenarios):
            console.print(f"\n[bold]进度 {i+1}/{len(scenarios)}[/bold]")
            result = self.run_scenario(scenario)
            results.append(result)

            # 增量写盘：每完成一个就更新 _running 文件
            try:
                with open(partial_path, "w", encoding="utf-8") as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            if progress_callback:
                progress_callback(i + 1, len(scenarios), result)
            time.sleep(1)

        # 全量完成 → 重命名为正式报告
        final_path = self._report_dir / f"test_report_{ts}.json"
        try:
            partial_path.rename(final_path)
            console.print(f"\n[green]报告已保存: {final_path}[/green]")
        except Exception:
            self._save_report(results)
        self._print_summary(results)
        return results

    # ══════════════════════════════════════════════════════════════════════════
    # 内部方法
    # ══════════════════════════════════════════════════════════════════════════

    def _run_one_step(self, step: dict, idx) -> tuple[bool, str, str]:
        """处理 login 特殊动作，其余委托给 executor"""
        action = step.get("action", "").lower()

        if action == "login":
            value    = step.get("value", "")
            parts    = value.split("|") if "|" in value else []
            username = parts[0].strip() if parts else self.username
            password = parts[1].strip() if len(parts) > 1 else self.password

            success  = self.executor.login(username, password)
            idx_label = f"{idx:03d}" if isinstance(idx, int) else str(idx)
            ss_path  = self.executor.screenshot(f"step_{idx_label}_login")
            self.memory.set_login_state(logged_in=success, username=username)
            return success, ss_path, ("" if success else "登录失败")

        return self.executor.execute_step(step, idx, take_screenshot=self.take_ss)

    def _build_result(self, scenario: dict, mem, verify: dict) -> dict:
        """组装标准化的测试结果 dict"""
        total  = len(mem.actions)
        passed = sum(1 for a in mem.actions if a.success)
        return {
            "scenario_id":         scenario.get("id",       ""),
            "scenario_name":       scenario.get("name",     ""),
            "feature_id":          scenario.get("feature_id", ""),
            "priority":            scenario.get("priority", "medium"),
            "result":              verify.get("result",     "UNKNOWN"),
            "confidence":          verify.get("confidence", 0),
            "summary":             verify.get("summary",    ""),
            "issues":              verify.get("issues",     []),
            "suggestions":         verify.get("suggestions",[]),
            "expectation_results": verify.get("expectation_results", []),
            "steps_total":         total,
            "steps_passed":        passed,
            "step_success_rate":   passed / total if total > 0 else 0,
            "start_time":          mem.start_time,
            "end_time":            mem.end_time or datetime.now().isoformat(),
            "screenshots":         [a.screenshot_path for a in mem.actions if a.screenshot_path],
        }

    def _save_report(self, results: list[dict]):
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self._report_dir / f"test_report_{ts}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        console.print(f"\n[green]报告已保存: {path}[/green]")

    def _print_summary(self, results: list[dict]):
        total  = len(results)
        passed = sum(1 for r in results if r.get("result") == "PASS")
        console.rule("[bold]测试摘要[/bold]")
        t = Table()
        t.add_column("指标")
        t.add_column("数值", style="bold")
        t.add_row("总场景数", str(total))
        t.add_row("通过",     f"[green]{passed}[/green]")
        t.add_row("失败",     f"[red]{total - passed}[/red]")
        t.add_row("通过率",   f"{passed/total*100:.1f}%" if total else "0%")
        console.print(t)
