#!/usr/bin/env python3
"""合并 analytics + config + content → docs/data/report.json（页面唯一数据源）+ 当日存档 + meta.json。
这里也算“今日信号”（alerts），页面显示、notify.py 推送都用同一份。
"""
import glob
from datetime import datetime, timedelta
from common import RAW, CONFIG, CONTENT, SITE_DATA, SETTINGS, load, save, log, now_utc

A = load(RAW / "analytics.json")
FUND = load("fundamentals.json"); ZONES = load("zones.json"); CAL = load("calendar.json"); EV = load("events.json")
UPD = load(CONTENT / "updates.json", {"updates": []})
asof = A["asof"]; S = A["summary"]; T = A["tech"]
px_cibr = S["CIBR"]["last"]

# ---- 估值随股价重算 ----
companies = []; ladder = {}
for r in FUND["companies"]:
    t = r["t"]; px = S.get(t, {}).get("last") or T.get(t, {}).get("px")
    c = dict(r); c["px"] = px
    if px and r.get("px_asof"):
        k = px / r["px_asof"]
        c["mcap_now"] = round(r["mcap_b"] * k, 1)
        ev_now = c["mcap_now"] - r["net_cash_b"]
        c["evs_ntm_now"] = round(ev_now / r["ntm_rev_b"], 1) if r.get("ntm_rev_b") else None
        ttm_rev = r["ev_b"] / r["evs_ttm"] if r.get("evs_ttm") else None
        c["evs_ttm_now"] = round(ev_now / ttm_rev, 1) if ttm_rev else None
        c["fwd_pe_now"] = round(r["fwd_pe"] * k, 0) if r.get("fwd_pe") else None
        c["ev_fcf_now"] = round(r["ev_fcf"] * k, 0) if r.get("ev_fcf") else None
        c["px_chg_since_asof"] = round(k - 1, 4)
    ladder[t] = [[m, round((m * r["ntm_rev_b"] + r["net_cash_b"]) * 1000 / r["shares_m"], 0)] for m in r["ladder_mults"]]
    companies.append(c)

# ---- 观察区状态 ----
zones = []
for z in ZONES["zones"]:
    if px_cibr < z["lo"]: status = "已跌破"
    elif px_cibr <= z["hi"]: status = "触及中"
    else: status = f"未触及，距上沿 {(z['hi'] / px_cibr - 1) * 100:+.1f}%"
    zones.append({**z, "status": status})
ma200_up = (T["CIBR"]["ma200"] or 0) > (T["CIBR"]["ma200_prev20"] or 0)
framework = {"ma200_up": ma200_up, "invalid": px_cibr < ZONES["invalid_below"] and not ma200_up, "resumed": px_cibr > ZONES["resume_above"],
             "off_ref_high": px_cibr / ZONES["ref_high"] - 1}

# ---- 财报结果 + 日历状态 ----
earn = {}
for f in sorted(glob.glob(str(CONTENT / "earnings" / "*.json"))):
    e = load(f)
    if e and e.get("ticker") and e.get("date"): earn[(e["ticker"], e["date"])] = e
asof_d = datetime.strptime(asof, "%Y-%m-%d")
look = int(SETTINGS.get("alerts", {}).get("earnings_lookahead_days", 2))
calendar = []
for ev in CAL["events"]:
    d = datetime.strptime(ev["date"], "%Y-%m-%d"); days = (d - asof_d).days
    if days < -14:  # 已过两周的事件从页面日历移出（config 里保留）
        continue
    e = earn.get((ev.get("ticker"), ev["date"]))
    c = dict(ev); c["days"] = days
    if e: c["status"] = "已出"; c["result"] = e
    elif days < 0: c["status"] = "已过，待抽取" if ev.get("ticker") else "已过"
    elif days <= look: c["status"] = "即将"
    else: c["status"] = f"{days} 天后"
    calendar.append(c)
calendar.sort(key=lambda c: c["date"])
earnings_list = sorted(earn.values(), key=lambda e: e["date"], reverse=True)

# ---- 今日信号 ----
def vol_phrase(x):
    """成交量的完整描述：当日成交量 ÷ 前 20 个交易日日均成交量（不含当日）。"""
    r = x.get("vol_1d_ratio")
    if not r:
        return "成交量数据缺失"
    tag = "显著放量" if r >= 2 else "放量" if r >= 1.5 else "温和放量" if r >= 1.1 else "平量" if r >= 0.9 else "缩量"
    src = str(S["CIBR"].get("src", ""))
    basis = "IBKR 常规交易时段口径，低于含盘前盘后的全市场成交量" if src.startswith("ibkr") else "Yahoo 全市场口径"
    return f"当日成交量 {x['vol_1d']/1e6:.2f} 百万股，为前 20 个交易日日均成交量（{x['vol_prev20_avg']/1e6:.2f} 百万股）的 {r:.2f} 倍（{tag}；{basis}）"


al = SETTINGS.get("alerts", {}); alerts = []
r1 = S["CIBR"]["ret1d"]
if abs(r1) >= al.get("cibr_abs_move", 0.03):
    alerts.append({"kind": "move", "level": "serious" if r1 < 0 else "good",
                   "text": f"CIBR 单日 {r1*100:+.1f}%（SMH {S['SMH']['ret1d']*100:+.1f}%、QQQ {S['QQQ']['ret1d']*100:+.1f}%、IGV {S['IGV']['ret1d']*100:+.1f}%）；{vol_phrase(T['CIBR'])}"})
for t in ("CRWD", "PANW", "FTNT", "ZS", "NET", "OKTA", "S", "RBRK", "CHKP"):
    if t in S and abs(S[t]["ret1d"]) >= al.get("leader_abs_move", 0.08):
        alerts.append({"kind": "move", "level": "serious" if S[t]["ret1d"] < 0 else "good", "text": f"{t} 单日 {S[t]['ret1d']*100:+.1f}%"})
rsi = T["CIBR"]["rsi14"]
if rsi < al.get("rsi_oversold", 30): alerts.append({"kind": "rsi", "level": "warning", "text": f"CIBR RSI(14) = {rsi:.0f}，超卖区"})
if rsi > al.get("rsi_overbought", 75): alerts.append({"kind": "rsi", "level": "warning", "text": f"CIBR RSI(14) = {rsi:.0f}，超买区"})
for z in zones:
    if z["status"] in ("触及中",): alerts.append({"kind": "zone", "level": "warning", "text": f"CIBR {px_cibr:.2f} 进入{z['name']}观察区 {z['lo']}–{z['hi']}（{z['plan']}）"})
if framework["invalid"]: alerts.append({"kind": "zone", "level": "critical", "text": f"CIBR 跌破 {ZONES['invalid_below']} 且 200 日线走平/向下：框架失效条件触发"})
if framework["resumed"]: alerts.append({"kind": "zone", "level": "good", "text": f"CIBR 收复 {ZONES['resume_above']}：回撤结束条件触发"})
for c in calendar:
    if c["status"] == "即将": alerts.append({"kind": "cal", "level": "warning", "text": f"{c['date']} {c['event']}：{c['watch']}"})
    if c["status"] == "已过，待抽取": alerts.append({"kind": "cal", "level": "warning", "text": f"{c['date']} {c['event']} 已过，待跑 earnings.py {c['ticker']} {c['date']}"})
src = A["sources"]
if src.get("gateway") == "down": alerts.append({"kind": "data", "level": "warning", "text": "IBKR Gateway 未连上，本次行情来自 Yahoo"})
stale = [t for t, s in src.get("per_ticker", {}).items() if str(s).startswith("stale")]
if stale: alerts.append({"kind": "data", "level": "warning", "text": f"{len(stale)} 只标的今日未取到、沿用上次：{', '.join(stale)}"})

meta = {"asof": asof, "generated_at": now_utc(), "window_start": A["window_start"], "ytd_start": A["ytd_start"], "n_days": A["n"],
        "sources": src, "narrative_date": SETTINGS.get("narrative_date"), "fundamentals_asof": FUND["asof"], "holdings_asof": FUND["holdings"]["asof"],
        "zones_asof": ZONES["asof"], "site_url": SETTINGS.get("site_url", ""), "stale_after_days": SETTINGS.get("stale_after_days", 4), "title": SETTINGS.get("report_title")}
report = {"meta": meta, "summary": S, "tech": T, "cm_t": A["cm_t"], "cmat": A["cmat"], "monthly": A["monthly"], "episodes": A["episodes"], "big": A["big"],
          "yield_corr": A["yield_corr"], **A["charts"],
          "F": companies, "ladder": ladder, "holdings": FUND["holdings"], "band": FUND["band"], "fund_note": FUND.get("note"),
          "events": EV["events"], "calendar": calendar, "earnings": earnings_list, "zones": zones, "zones_cfg": ZONES, "framework": framework,
          "updates": sorted(UPD["updates"], key=lambda u: u["date"], reverse=True), "alerts": alerts}
save(SITE_DATA / "report.json", report)
save(SITE_DATA / "archive" / f"{asof}.json", report)
archives = sorted(p.name[:-5] for p in (SITE_DATA / "archive").glob("*.json"))
save(SITE_DATA / "meta.json", {**meta, "alerts": alerts, "archives": archives}, indent=1)
log(f"export: docs/data/report.json（截至 {asof}，{len(alerts)} 条信号，{len(earnings_list)} 份财报，{len(archives)} 个存档）")
for a in alerts: log("  ·", a["text"])
