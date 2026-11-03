#!/usr/bin/env python3
"""财报抽取：用 claude -p（订阅额度，带联网）研究某家公司某日财报，按 config/calendar.json 里的 criteria 逐条判定，
写 content/earnings/{TICKER}_{DATE}.json，并在 content/updates.json 追加一条更新日志、config/events.json 追加事件点。
然后跑 run.py --skip-fetch 重新导出即可上页。

用法：python3 scripts/earnings.py NET 2026-11-05 [--model sonnet] [--dry-run] [--extra "补充说明"]
"""
import argparse, json, os, re, shutil, subprocess, time
from datetime import datetime
from common import ROOT, CONFIG, CONTENT, SETTINGS, load, save, log

SCHEMA = json.dumps({
    "type": "object",
    "properties": {
        "ticker": {"type": "string"}, "date": {"type": "string"}, "quarter": {"type": "string", "description": "如 FY26 Q3"},
        "revenue_b": {"type": ["number", "null"], "description": "季度收入，十亿美元"}, "rev_yoy_pct": {"type": ["number", "null"]},
        "guide": {"type": "string", "description": "下季/全年指引与一致预期的比较，一句话"},
        "kpis": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "value": {"type": "string"}, "note": {"type": "string"}}, "required": ["name", "value"]}},
        "fcf_margin_pct": {"type": ["number", "null"]}, "op_margin_pct": {"type": ["number", "null"], "description": "非 GAAP 营业利润率"},
        "ntm_rev_b": {"type": ["number", "null"], "description": "财报后未来 12 个月收入估计（指引+一致预期拼接），十亿美元"},
        "reaction_pct": {"type": ["number", "null"], "description": "财报后首个交易日涨跌幅 %"}, "reaction_date": {"type": ["string", "null"]},
        "mgmt_ai_comment": {"type": "string"}, "analyst_actions": {"type": "string"},
        "checks": {"type": "array", "items": {"type": "object", "properties": {"criterion": {"type": "string"}, "pass": {"type": ["boolean", "null"]}, "actual": {"type": "string"}}, "required": ["criterion", "pass", "actual"]}},
        "verdict": {"type": "string", "enum": ["pass", "fail", "mixed"]}, "verdict_reason": {"type": "string"},
        "summary_zh": {"type": "string", "description": "面向投资者的中文摘要 150-250 字，金融术语保留英文"},
        "event_label": {"type": "string", "description": "图表事件点一句话，≤30 字，如 'NET 三季报 +36%，盘后 +8%'"},
        "sources": {"type": "array", "items": {"type": "object", "properties": {"title": {"type": "string"}, "url": {"type": "string"}}, "required": ["url"]}},
        "unverified": {"type": "array", "items": {"type": "string"}, "description": "没查到或只有二手来源的数字"}
    },
    "required": ["ticker", "date", "quarter", "guide", "kpis", "checks", "verdict", "verdict_reason", "summary_zh", "event_label", "sources", "unverified"]
})


def claude_bin():
    return shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")


def build_prompt(ticker, date, criteria, extra):
    crit = "\n".join(f"- {c}" for c in criteria) or "- （日历里没有预设标准，请按行业常规：收入增速、ARR/cRPO 加速或减速、指引 vs 一致预期、FCF 利润率）"
    return f"""你是一名美股网络安全行业研究员。请研究 {ticker} 于 {date} 发布的季度财报，并输出结构化 JSON。

要求：
1. 用 WebSearch / WebFetch 找一手来源：公司 IR 新闻稿或 SEC 8-K Exhibit 99.1，其次 CNBC、Yahoo Finance、Bloomberg 报道。每个关键数字尽量给来源 URL。
2. 提取：收入与同比、下季/全年指引 vs 一致预期、ARR / cRPO / RPO / NRR / 大客户数等 KPI、非 GAAP 营业利润率、FCF 利润率、管理层关于 AI 需求或 AI 颠覆的评论、券商评级变动、财报后首个交易日股价反应。
3. 逐条对照下面的检验标准，给出 pass / fail / null（查不到），并写出实际值：
{crit}
4. 综合判定 verdict：全部通过 = pass；核心增长指标（收入增速 / ARR 增速 / 指引）任一未通过 = fail；其余 = mixed。
5. summary_zh 用中文写给有大学文凭、无行业背景的投资者，150–250 字，金融术语保留英文，不要套话。
6. 查不到的数字写 null 并列入 unverified，不要编造。
{('补充说明：' + extra) if extra else ''}"""


def call_claude(prompt, model, timeout):
    cmd = [claude_bin(), "-p", "--model", model, "--output-format", "json", "--json-schema", SCHEMA,
           "--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch,WebFetch", "--max-turns", "25"]
    t0 = time.time()
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError(f"claude exit {p.returncode}: {p.stderr[-800:]}")
    out = p.stdout[p.stdout.find("{"):]
    d = json.loads(out)
    so = d.get("structured_output")
    if not so:
        raise RuntimeError(f"no structured_output: subtype={d.get('subtype')} result={str(d.get('result'))[:400]}")
    return so, d.get("total_cost_usd"), int(time.time() - t0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker"); ap.add_argument("date")
    ap.add_argument("--model", default=SETTINGS.get("claude_model", "sonnet"))
    ap.add_argument("--extra", default=""); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    ticker = a.ticker.upper(); date = a.date
    cal = load("calendar.json"); ev = next((e for e in cal["events"] if e.get("ticker") == ticker and e["date"] == date), None)
    criteria = (ev or {}).get("criteria", [])
    if not ev:
        log(f"日历里没有 {ticker} {date}，仍然抽取，但建议先加进 config/calendar.json")
    prompt = build_prompt(ticker, date, criteria, a.extra)
    if a.dry_run:
        print(prompt); return
    log(f"claude -p（{a.model}）研究 {ticker} {date} …")
    so, cost, sec = call_claude(prompt, a.model, int(SETTINGS.get("claude_timeout_sec", 1200)))
    so["ticker"] = ticker; so["date"] = date; so["extracted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M"); so["model"] = a.model
    out = CONTENT / "earnings" / f"{ticker}_{date}.json"
    save(out, so, indent=1)
    log(f"写入 {out}（{sec}s，cost {cost}）verdict={so['verdict']}")
    # 更新日志
    upd = load(CONTENT / "updates.json", {"updates": []})
    title = f"{ticker} {so.get('quarter','')} 财报：{ {'pass':'通过','fail':'未通过','mixed':'部分通过'}[so['verdict']] }"
    if not any(u.get("title") == title for u in upd["updates"]):
        upd["updates"].append({"date": so.get("reaction_date") or date, "title": title, "html": so["summary_zh"] + (f"<br><span class='muted'>判定理由：{so['verdict_reason']}</span>" if so.get("verdict_reason") else "")})
        save(CONTENT / "updates.json", upd, indent=1)
    # 事件点
    evs = load("events.json")
    d_ev = so.get("reaction_date") or date
    if not any(e["date"] == d_ev and e["label"].startswith(ticker) for e in evs["events"]):
        evs["events"].append({"date": d_ev, "label": so.get("event_label") or f"{ticker} 财报"}); evs["events"].sort(key=lambda e: e["date"])
        save(CONFIG / "events.json", evs, indent=1)
    # 梯子表的 NTM 收入
    if so.get("ntm_rev_b"):
        fund = load("fundamentals.json")
        for c in fund["companies"]:
            if c["t"] == ticker:
                c["ntm_rev_b"] = so["ntm_rev_b"]; c["ntm_note"] = f"{date} 财报后更新"
        save(CONFIG / "fundamentals.json", fund, indent=1)
    log("下一步：python3 scripts/run.py --skip-fetch  （或完整 run.py）重新导出")
    if so.get("unverified"):
        log("未核实：" + "; ".join(so["unverified"]))


if __name__ == "__main__":
    main()
