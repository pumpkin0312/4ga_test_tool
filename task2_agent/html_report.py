"""
task2_agent/html_report.py

独立的 HTML 可视化报告生成器。产出自包含单文件 HTML（截图以 base64 内联），
可直接在 Streamlit 里下载、离线打开。

内容：
  - 总览统计（总场景 / PASS / FAIL / ERROR / BLOCKED / 功能通过率）
  - 失败原因分类统计
  - 每个场景：结果徽章、结论、inline 规则验证通过率、步骤成功率、LLM 置信度、
    失败步骤（action / target / error_msg）、恢复步骤 recovered_steps、截图
"""
import base64
import html
from datetime import datetime
from pathlib import Path

from task2_agent.result_utils import (
    summarize, classify_failure_reason, failed_actions, REASON_PASS,
)

_CATEGORY_COLORS = {
    "PASS":    "#27ae60",
    "FAIL":    "#e74c3c",
    "ERROR":   "#e67e22",
    "BLOCKED": "#2980b9",
}
_MAX_SHOTS_PER_SCENARIO = 4


def _esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _img_data_uri(path: str) -> str | None:
    """把截图读成 base64 data URI；文件不存在或过大返回 None。"""
    try:
        p = Path(path)
        if not p.exists() or p.stat().st_size > 4_000_000:  # 单张 >4MB 跳过
            return None
        ext = p.suffix.lstrip(".").lower() or "png"
        data = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:image/{ext};base64,{data}"
    except Exception:
        return None


def _badge(result: str) -> str:
    color = _CATEGORY_COLORS.get(result, "#7f8c8d")
    return (f"<span style='background:{color};color:#fff;padding:2px 10px;"
            f"border-radius:10px;font-size:13px;'>{_esc(result)}</span>")


def _scenario_section(r: dict) -> str:
    result = r.get("result", "")
    parts = [f"<div class='scenario {result}'>"]
    parts.append(
        f"<h3>{_badge(result)} &nbsp;{_esc(r.get('scenario_name',''))} "
        f"<code>{_esc(r.get('scenario_id',''))}</code></h3>"
    )

    reason = classify_failure_reason(r)
    reason_html = "" if reason == REASON_PASS else f" &nbsp;·&nbsp; 归因：<b>{_esc(reason)}</b>"
    parts.append(f"<p class='summary'>{_esc(r.get('summary',''))}{reason_html}</p>")

    # 指标行
    inline_rate = r.get("inline_pass_rate")
    step_rate   = r.get("step_success_rate", 0)
    conf        = r.get("confidence", 0)
    metrics = [
        f"规则验证通过率：<b>{inline_rate:.0%}</b>" if isinstance(inline_rate, (int, float)) else "规则验证通过率：—",
        f"步骤成功率：<b>{step_rate:.0%}</b>（{r.get('steps_passed',0)}/{r.get('steps_total',0)}）",
        f"LLM 置信度：<b>{conf:.0%}</b>" if isinstance(conf, (int, float)) else "LLM 置信度：—",
    ]
    parts.append("<p class='metrics'>" + " &nbsp;|&nbsp; ".join(metrics) + "</p>")

    # 失败步骤
    fails = failed_actions(r)
    if fails:
        parts.append("<div class='fails'><b>失败步骤</b><table>"
                     "<tr><th>#</th><th>action</th><th>target</th><th>错误</th></tr>")
        for a in fails:
            parts.append(
                f"<tr><td>{_esc(a.get('step_index',''))}</td>"
                f"<td><code>{_esc(a.get('action',''))}</code></td>"
                f"<td><code>{_esc(a.get('target',''))}</code></td>"
                f"<td>{_esc(a.get('error_msg','') or a.get('description',''))}</td></tr>"
            )
        parts.append("</table></div>")

    # 恢复步骤
    recovered = r.get("recovered_steps", [])
    if recovered:
        parts.append("<div class='recovered'><b>靠备选方案恢复的步骤</b><ul>")
        for rc in recovered:
            parts.append(f"<li>步骤 {_esc(rc.get('step_index',''))}：{_esc(rc.get('description',''))}</li>")
        parts.append("</ul></div>")

    # 截图：失败场景嵌入较多（便于取证），PASS 只留最后一张（控制文件体积）
    shots = r.get("screenshots", [])
    if result == "PASS":
        chosen = shots[-1:]
    else:
        chosen = shots[:_MAX_SHOTS_PER_SCENARIO]
    uris = [u for u in (_img_data_uri(s) for s in chosen) if u]
    if uris:
        parts.append("<div class='shots'>")
        for u in uris:
            parts.append(f"<img src='{u}' loading='lazy'/>")
        parts.append("</div>")

    parts.append("</div>")
    return "\n".join(parts)


def render_html_report(results: list[dict], title: str = "4ga Boards 测试报告") -> str:
    """把结果列表渲染成完整 HTML 字符串（自包含）。"""
    s = summarize(results)
    cat = s["by_category"]

    cards = ""
    for k, v in cat.items():
        color = _CATEGORY_COLORS.get(k, "#888")
        cards += (f"<div class='stat' style='border-top:4px solid {color}'>"
                  f"<div class='num'>{v}</div><div class='lbl'>{k}</div></div>")
    overview = (
        f"<div class='stat'><div class='num'>{s['total']}</div><div class='lbl'>总场景</div></div>"
        + cards +
        f"<div class='stat'><div class='num'>{s['pass_rate']*100:.1f}%</div>"
        f"<div class='lbl'>功能通过率</div></div>"
    )

    reason_rows = "".join(
        f"<tr><td>{_esc(reason)}</td><td>{n}</td></tr>"
        for reason, n in sorted(s["by_reason"].items(), key=lambda x: -x[1])
    ) or "<tr><td colspan='2'>无失败</td></tr>"

    scenarios_html = "\n".join(_scenario_section(r) for r in results)
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(title)}</title>
<style>
  body {{ font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
         margin:0;background:#f5f6f8;color:#222; }}
  header {{ background:#1f2d3d;color:#fff;padding:20px 32px; }}
  header h1 {{ margin:0;font-size:22px; }}
  header .gen {{ opacity:.7;font-size:13px;margin-top:4px; }}
  .wrap {{ max-width:1080px;margin:0 auto;padding:24px 32px; }}
  .stats {{ display:flex;flex-wrap:wrap;gap:12px;margin-bottom:24px; }}
  .stat {{ background:#fff;border-radius:8px;padding:14px 20px;min-width:96px;
          box-shadow:0 1px 3px rgba(0,0,0,.08);text-align:center; }}
  .stat .num {{ font-size:26px;font-weight:700; }}
  .stat .lbl {{ font-size:12px;color:#666;margin-top:2px; }}
  h2 {{ font-size:17px;border-left:4px solid #1f2d3d;padding-left:10px; }}
  table {{ border-collapse:collapse;width:100%;background:#fff;font-size:13px; }}
  th,td {{ border:1px solid #e2e5e9;padding:6px 10px;text-align:left;vertical-align:top; }}
  th {{ background:#f0f2f5; }}
  code {{ background:#eef1f4;padding:1px 4px;border-radius:3px;font-size:12px; }}
  .scenario {{ background:#fff;border-radius:8px;padding:16px 20px;margin-bottom:16px;
              box-shadow:0 1px 3px rgba(0,0,0,.06);border-left:5px solid #ccc; }}
  .scenario.PASS {{ border-left-color:#27ae60; }}
  .scenario.FAIL {{ border-left-color:#e74c3c; }}
  .scenario.ERROR {{ border-left-color:#e67e22; }}
  .scenario.BLOCKED {{ border-left-color:#2980b9; }}
  .scenario h3 {{ margin:0 0 6px;font-size:16px; }}
  .summary {{ color:#333;margin:4px 0; }}
  .metrics {{ color:#555;font-size:13px;margin:4px 0 10px; }}
  .fails table {{ margin:6px 0 12px; }}
  .recovered {{ font-size:13px;color:#1e7e34;margin:6px 0 12px; }}
  .shots {{ display:flex;flex-wrap:wrap;gap:8px; }}
  .shots img {{ max-width:230px;border:1px solid #ddd;border-radius:4px; }}
</style></head>
<body>
<header><h1>{_esc(title)}</h1><div class="gen">生成时间：{generated}</div></header>
<div class="wrap">
  <div class="stats">{overview}</div>
  <h2>失败原因分类</h2>
  <table><tr><th>原因</th><th>场景数</th></tr>{reason_rows}</table>
  <h2 style="margin-top:28px;">场景详情</h2>
  {scenarios_html}
</div>
</body></html>"""


def write_html_report(results: list[dict], output_path: str, title: str = "4ga Boards 测试报告") -> str:
    """渲染并写入文件，返回写入路径。"""
    html_text = render_html_report(results, title=title)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html_text, encoding="utf-8")
    return output_path
