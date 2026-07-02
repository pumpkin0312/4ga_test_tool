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
        from task2_agent.resolver import PageResolver
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

        # 页面感知 Resolver：执行前主动读取页面，对齐 LLM target 与真实 DOM
        self.page_aware = config.get("page_aware", True)
        self.resolver   = PageResolver(api_key, model, base_url=base_url) if self.page_aware else None

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

        # 每个场景开始时重置登录状态（因为浏览器每次都会重启）
        self.memory.set_login_state(
            logged_in=False, username="", current_project="", current_board=""
        )

        # 初始化场景记忆
        mem = self.memory.new_session(sid, sname)
        mem.log(f"开始执行: {sname}")

        # ── 0. 前置阻塞检查：缺测试数据等无法执行的场景，直接标 BLOCKED（不算产品失败）──
        from task2_agent.result_utils import detect_blocked_reason
        blocked_reason = detect_blocked_reason(scenario)
        if blocked_reason:
            mem.log(f"场景被阻塞，跳过执行: {blocked_reason}")
            console.print(f"  [yellow]BLOCKED: {blocked_reason}[/yellow]")
            mem.end_time = datetime.now().isoformat()
            result = self._build_result(scenario, mem, {
                "result": "BLOCKED", "confidence": 0,
                "summary": blocked_reason,
                "expectation_results": [], "issues": [blocked_reason],
                "suggestions": ["补齐所需测试数据文件，或在演示时排除该场景"],
            })
            result["expectations_inline"] = []
            result["inline_pass_rate"] = 0
            result["logs"] = mem.logs
            return result

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
                # 执行前页面感知：让 Resolver 校验/重定向 target
                if self.resolver and not step.get("_auto"):
                    try:
                        step = self.resolver.resolve(self.executor, step)
                    except Exception as e:
                        console.print(f"[yellow]Resolver 调用异常，跳过: {e}[/yellow]")

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
                    failed_ctx = ((step.get("target", "") or "") + " " +
                                  (step.get("description", "") or "")).lower()
                    is_cancel_step = any(k in failed_ctx for k in
                                         ("cancel", "取消", "关闭", "close", "discard", "放弃"))

                    if is_cancel_step:
                        # 取消类步骤失败：禁止 fallback 到 Save/Create/Add 等相反操作；
                        # 只用 Escape 兜底关闭表单，绝不把“取消”做成“保存”。
                        console.print(f"  [yellow]步骤 {i+1}(取消) 失败，用 Escape 兜底，不 fallback 到保存类操作[/yellow]")
                        actionable = [{"action": "press", "target": "", "value": "Escape",
                                       "description": "按 Escape 取消（禁止 Save fallback）"}]
                    else:
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
                        # 备选方案也经过 Resolver 校验，确保 target 匹配真实 DOM
                        if self.resolver and alt.get("action", "").lower() not in {
                            "setinputfiles", "set_input_files", "upload", "upload_file",
                        }:
                            try:
                                alt = self.resolver.resolve(self.executor, alt)
                            except Exception as e:
                                mem.log(f"备选方案 Resolver 调用失败，使用原始备选步骤: {e}")
                        alt_ok, alt_ss, alt_err = self._run_one_step(alt, f"{i+1}b")
                        if alt_ok:
                            mem.log(f"备选方案成功: {alt.get('description','')}")
                            alt_record = ActionRecord(
                                step_index=f"{i+1}b",
                                action=alt.get("action", ""),
                                target=alt.get("target", ""),
                                value=alt.get("value", ""),
                                description=f"[备选] {alt.get('description', '')}",
                                success=True,
                                screenshot_path=alt_ss,
                                page_url=self.executor.get_url(),
                                page_title=self.executor.get_title(),
                                error_msg="",
                            )
                            mem.add_action(alt_record)
                            executed_steps.append({**alt, "_alternative_for": i + 1})
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

        # 强制降级：即使 LLM 判 PASS，规则验证通过率低于 FORCE_FAIL_THRESHOLD 时改判 FAIL
        # （防止 LLM 看着步骤通过率拍 PASS、忽略真实功能失败）
        from task2_agent.verifier import decide_result
        before = verify_result.get("result")
        verify_result = decide_result(verify_result, inline_results)
        if before == "PASS" and verify_result.get("result") == "FAIL":
            console.print(
                f"  [red]规则验证通过率 {verify_result.get('inline_pass_rate', 0):.0%} "
                f"低于阈值，强制将结果降级为 FAIL[/red]"
            )

        # 取消类场景防假通过：必须确认「表单/弹窗曾经打开且临时值曾经输入」。
        # 若既没有成功的输入动作、关键步骤也失败，则不允许仅因“目标名称不可见”而 PASS。
        if self._is_cancel_scenario(scenario) and verify_result.get("result") == "PASS":
            form_input_ok = any(
                a.success and (a.action or "").lower() in ("input", "type", "fill")
                for a in mem.actions
            )
            core_fail = any(
                (not a.success) and not str(a.step_index).endswith("b")
                for a in mem.actions
            )
            if not form_input_ok:
                verify_result["result"] = "FAIL"
                verify_result["summary"] = (
                    "（取消场景防假通过）未确认表单/弹窗曾打开且临时值曾输入，"
                    "无法证明‘取消’真实发生：" + verify_result.get("summary", "")
                )
                console.print("  [red]取消场景未确认表单曾打开/输入，强制判 FAIL（防假通过）[/red]")
            elif core_fail:
                verify_result["result"] = "FAIL"
                verify_result["summary"] = (
                    "（取消场景防假通过）存在失败的关键步骤，不能仅凭名称不可见判通过："
                    + verify_result.get("summary", "")
                )
                console.print("  [red]取消场景关键步骤失败，强制判 FAIL（防假通过）[/red]")

        result = self._build_result(scenario, mem, verify_result)
        result["expectations_inline"] = inline_results
        result["inline_pass_rate"] = verify_result.get("inline_pass_rate", 0)
        result["logs"] = mem.logs
        return result

    @staticmethod
    def _is_cancel_scenario(scenario: dict) -> bool:
        """场景是否为「取消/放弃」类（取消创建、取消编辑、取消导入等）。"""
        blob = ((scenario.get("name", "") or "") + " " +
                (scenario.get("precondition", "") or "") + " " +
                " ".join(scenario.get("tags", []))).lower()
        return any(k in blob for k in ("取消", "cancel", "放弃", "discard", "不保存"))

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

        idx_label = f"{idx:03d}" if isinstance(idx, int) else str(idx)

        if action == "login":
            value    = step.get("value", "")
            parts    = value.split("|") if "|" in value else []
            username = parts[0].strip() if parts else self.username
            password = parts[1].strip() if len(parts) > 1 else self.password
            if username == self.username and password == "demo" and self.password != "demo":
                # Generated scenarios often hard-code the old shared demo password.
                # The configured password reflects the current real demo state.
                password = self.password

            success  = self.executor.login(username, password)
            ss_path  = self.executor.screenshot(f"step_{idx_label}_login")
            self.memory.set_login_state(logged_in=success, username=username)
            return success, ss_path, ("" if success else "登录失败")

        if action == "enter_first_project":
            success = self.executor.enter_first_project()
            ss_path = self.executor.screenshot(f"step_{idx_label}_enter_project")
            return success, ss_path, ("" if success else "进入项目失败")

        if action == "open_first_board":
            success = self.executor.open_first_board()
            ss_path = self.executor.screenshot(f"step_{idx_label}_open_board")
            return success, ss_path, ("" if success else "打开看板失败")

        if action == "open_settings":
            section = (step.get("value") or "").strip() or None
            success = self.executor.open_settings(section)
            ss_path = self.executor.screenshot(f"step_{idx_label}_open_settings")
            return success, ss_path, ("" if success else "打开设置失败")

        if action == "open_project_settings":
            success = self.executor.open_project_settings()
            ss_path = self.executor.screenshot(f"step_{idx_label}_open_project_settings")
            return success, ss_path, ("" if success else "打开项目设置失败")

        if action == "ensure_list_exists":
            success = self.executor.ensure_list_exists()
            ss_path = self.executor.screenshot(f"step_{idx_label}_ensure_list")
            return success, ss_path, ("" if success else "确保列表存在失败")

        if action == "ensure_card_exists":
            success = self.executor.ensure_card_exists()
            ss_path = self.executor.screenshot(f"step_{idx_label}_ensure_card")
            return success, ss_path, ("" if success else "确保卡片存在失败")

        if action == "open_first_card":
            success = self.executor.open_first_card()
            ss_path = self.executor.screenshot(f"step_{idx_label}_open_card")
            return success, ss_path, ("" if success else "打开卡片失败")

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
            "recovered_steps":     [
                {"step_index": a.step_index, "description": a.description}
                for a in mem.actions
                if isinstance(a.step_index, str) and a.success
            ],
            "actions":             [a.__dict__ for a in mem.actions],
        }

    def _save_report(self, results: list[dict]):
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self._report_dir / f"test_report_{ts}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        console.print(f"\n[green]报告已保存: {path}[/green]")

    def _print_summary(self, results: list[dict]):
        from task2_agent.result_utils import summarize
        s = summarize(results)
        cat = s["by_category"]
        console.rule("[bold]测试摘要[/bold]")
        t = Table()
        t.add_column("指标")
        t.add_column("数值", style="bold")
        t.add_row("总场景数", str(s["total"]))
        t.add_row("通过 PASS",   f"[green]{cat['PASS']}[/green]")
        t.add_row("失败 FAIL",   f"[red]{cat['FAIL']}[/red]")
        t.add_row("错误 ERROR",  f"[yellow]{cat['ERROR']}[/yellow]")
        t.add_row("阻塞 BLOCKED", f"[cyan]{cat['BLOCKED']}[/cyan]")
        t.add_row("功能通过率",   f"{s['pass_rate']*100:.1f}%")
        console.print(t)
        if s["by_reason"]:
            rt = Table(title="失败原因分类")
            rt.add_column("原因")
            rt.add_column("场景数", style="bold")
            for reason, n in sorted(s["by_reason"].items(), key=lambda x: -x[1]):
                rt.add_row(reason, str(n))
            console.print(rt)
