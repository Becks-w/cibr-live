#!/usr/bin/env python3
"""持仓表的补充数据（run.py 在 fetch_prices 之后调用；失败不影响主流程）。

1. 上个周期的最大回撤：2021-01-01 至 2025-12-31 的收盘价峰谷回撤。区间已经结束，结果不会再变，
   所以只算一次，存 config/cycle_dd.json；之后只补缺的代码（新进持仓），--rebuild 全部重算。
2. 不在每日行情清单（config/tickers.json）里的持仓：每天用 Yahoo 取两年日线，算现价、一年高低点、
   一年最大回撤等，口径与 analyze.py 的 summary 相同，存 data/raw/holdings_px.json。
   取不到就沿用上一次的结果并标 stale。

价格用拆股复权、不含分红的收盘价（Yahoo 的 Close），海外上市的两只用当地货币。
用法：python3 scripts/holdings_px.py [--rebuild] [--no-daily]
"""
import argparse
from datetime import datetime
from common import RAW, CONFIG, TICKERS, load, save, log, now_utc
from fetch_prices import fetch_yahoo

CYC = CONFIG / "cycle_dd.json"
OUT = RAW / "holdings_px.json"
YAHOO = {"HO.FP": "HO.PA", "4704.JP": "4704.T"}          # 持仓代码 → Yahoo 代码
CUR = {"HO.FP": "EUR", "4704.JP": "JPY"}
C0, C1 = "2021-01-01", "2025-12-31"


def maxdd(ds, cs):
    """返回 (回撤, 峰日, 峰价, 谷日, 谷价)。"""
    pk = cs[0]; pki = 0; mdd = 0.0; rec = (0, 0)
    for i, c in enumerate(cs):
        if c > pk: pk = c; pki = i
        dd = c / pk - 1
        if dd < mdd: mdd = dd; rec = (pki, i)
    return mdd, ds[rec[0]], cs[rec[0]], ds[rec[1]], cs[rec[1]]


def closes(m, a=None, b=None):
    ds = sorted(d for d in m if (a is None or d >= a) and (b is None or d <= b) and m[d][3] is not None)
    return ds, [m[d][3] for d in ds]


def cycle(tickers, rebuild=False):
    cyc = load(CYC, None) or {"note": "", "rows": {}}
    cyc["note"] = f"上个周期（{C0} 至 {C1}）收盘价的最大峰谷回撤。区间已结束，算一次即可；scripts/holdings_px.py 只补缺的代码。拆股复权、不含分红。"
    todo = [t for t in tickers if rebuild or t not in cyc["rows"]]
    if not todo:
        return cyc
    log(f"上个周期回撤：需要计算 {len(todo)} 只")
    got = fetch_yahoo([YAHOO.get(t, t) for t in todo], 6, attempts=2, wait=30)
    for t in todo:
        m = got.get(YAHOO.get(t, t))
        if not m:
            log(f"  {t}: 取不到长历史，留空"); continue
        ds, cs = closes(m, C0, C1)
        if len(ds) < 40 or ds[0] > "2024-12-31":
            cyc["rows"][t] = {"na": True, "first": ds[0] if ds else None, "src": "yahoo"}   # 2025 年才上市，谈不上上个周期
            continue
        dd, pd_, pp, td, tp = maxdd(ds, cs)
        row = {"mdd": round(dd, 4), "peak_date": pd_, "peak": round(pp, 2), "trough_date": td, "trough": round(tp, 2), "first": ds[0], "src": "yahoo"}
        if ds[0] > "2021-02-01": row["late"] = True   # 2021 年之后才上市，区间不完整
        cyc["rows"][t] = row
        log(f"  {t}: {dd:.1%}（{pd_} {pp:.2f} → {td} {tp:.2f}）" + ("，上市较晚" if row.get("late") else ""))
    cyc["computed_at"] = now_utc()
    save(CYC, cyc, indent=1)
    return cyc


def stats(m, upto=None):
    """与 analyze.py 的 summary 同口径：一年窗口 = 最新交易日往前一年。upto = 主行情的截止日，
    之后的 K 线不要（欧洲、日本盘中取数会带一根当天没走完的）。"""
    ds, cs = closes(m, b=upto)
    if len(ds) < 30: return None
    asof = ds[-1]; y = datetime.strptime(asof, "%Y-%m-%d")
    d1y = y.replace(year=y.year - 1).strftime("%Y-%m-%d")
    i1y = max(next((i for i, d in enumerate(ds) if d >= d1y), len(ds) - 1), 1)
    iytd = max(next((i for i, d in enumerate(ds) if d >= f"{y.year}-01-01"), len(ds) - 1), 1)
    w = cs[i1y:]; hi = max(w); lo = min(w); hii = cs.index(hi, i1y); loi = cs.index(lo, i1y)
    dd, pd_, _, td, _ = maxdd(ds[i1y:], w)
    return {"asof": asof, "last": round(cs[-1], 4), "ret1y": cs[-1] / cs[i1y] - 1, "retytd": cs[-1] / cs[iytd - 1] - 1,
            "high1y": round(hi, 4), "high1y_date": ds[hii], "low1y": round(lo, 4), "low1y_date": ds[loi],
            "off_high": cs[-1] / hi - 1, "mdd1y": [dd, pd_, td], "src": "yahoo"}


def daily(tickers):
    prev = (load(OUT, None) or {}).get("rows", {})
    upto = (load(RAW / "prices.json", {}) or {}).get("asof")
    extra = [t for t in tickers if t not in TICKERS["universe"]]
    got = fetch_yahoo([YAHOO.get(t, t) for t in extra], 2, attempts=2, wait=30) if extra else {}
    rows = {}; stale = []
    for t in extra:
        m = got.get(YAHOO.get(t, t)); s = stats(m, upto) if m else None
        if s and (t not in prev or s["asof"] >= prev[t].get("asof", "")):
            rows[t] = s
        elif t in prev:
            rows[t] = {**prev[t], "src": "stale:yahoo"}; stale.append(t)
        if t in rows and t in CUR: rows[t]["cur"] = CUR[t]
    save(OUT, {"fetched_at": now_utc(), "stale": stale, "rows": rows}, indent=1)
    log(f"持仓补充行情：{len(rows)}/{len(extra)} 只" + (f"，{len(stale)} 只沿用旧数据" if stale else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true"); ap.add_argument("--no-daily", action="store_true")
    a = ap.parse_args()
    held = [r["t"] for r in load("fundamentals.json")["holdings"]["rows"]]
    cycle(held, a.rebuild)
    if not a.no_daily: daily(held)
