#!/usr/bin/env python3
"""从 data/raw/prices.json 算全部统计量与图表序列，写 data/raw/analytics.json。
窗口随数据滚动：1 年窗 = 截至日往前一年；YTD = 当年 1 月 1 日起。
"""
import math, statistics as st
from datetime import datetime
from common import RAW, TICKERS, load, save, log

P = load(RAW / "prices.json")
dates = P["dates"]; n = len(dates); SER = P["series"]
asof = dates[-1]


def ser(t):
    return SER[t]["c"]


def has(t):
    return t in SER and SER[t]["c"] and SER[t]["c"][-1] is not None


def idx(date):
    for i, d in enumerate(dates):
        if d >= date:
            return i
    return n - 1


y = datetime.strptime(asof, "%Y-%m-%d")
i1y = idx(y.replace(year=y.year - 1).strftime("%Y-%m-%d"))
iytd = idx(f"{y.year}-01-01")
if i1y < 1: i1y = 1
if iytd < 1: iytd = 1


def rets(t, a, b):
    s = ser(t); out = []
    for i in range(a + 1, b + 1):
        out.append(s[i] / s[i - 1] - 1 if s[i] and s[i - 1] else 0.0)
    return out


def corr(x, y):
    mx, my = st.mean(x), st.mean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x)); sy = math.sqrt(sum((b - my) ** 2 for b in y))
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy) if sx and sy else None


def beta(x, y):
    mx, my = st.mean(x), st.mean(y)
    den = sum((b - my) ** 2 for b in y)
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / den if den else None


def maxdd(s, a, b):
    pk = s[a]; pki = a; mdd = 0; rec = (a, a)
    for i in range(a, b + 1):
        if s[i] > pk: pk = s[i]; pki = i
        dd = s[i] / pk - 1
        if dd < mdd: mdd = dd; rec = (pki, i)
    return [mdd, dates[rec[0]], dates[rec[1]]]


def sma(s, w, i):
    return sum(s[i - w + 1:i + 1]) / w if i >= w - 1 else None


def sma_series(s, w):
    return [None if i < w - 1 else round(sum(s[i - w + 1:i + 1]) / w, 2) for i in range(len(s))]


def ema_series(s, w):
    k = 2 / (w + 1); out = [s[0]]
    for v in s[1:]: out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(s, i, w=14):
    g = l = 0
    for j in range(i - w + 1, i + 1):
        d = s[j] - s[j - 1]; g += max(d, 0); l += max(-d, 0)
    return 100 if l == 0 else 100 - 100 / (1 + (g / w) / (l / w))


# ---- 一年统计 ----
tick = [t for t in TICKERS["universe"] if has(t)]
rq = rets("QQQ", i1y, n - 1); rs = rets("SMH", i1y, n - 1); rsp = rets("SPY", i1y, n - 1)
summary = {}
for t in tick:
    s = ser(t); r = rets(t, i1y, n - 1)
    hi = max(s[i1y:]); hii = s.index(hi, i1y); lo = min(s[i1y:]); loi = s.index(lo, i1y)
    up = [(a, b) for a, b in zip(r, rq) if b > 0]; dn = [(a, b) for a, b in zip(r, rq) if b < 0]
    summary[t] = {"last": s[-1], "prev": s[-2], "ret1d": s[-1] / s[-2] - 1, "ret1y": s[-1] / s[i1y] - 1, "retytd": s[-1] / s[iytd - 1] - 1,
                  "vol1y": st.pstdev(r) * math.sqrt(252), "beta_qqq": beta(r, rq), "beta_smh": beta(r, rs), "beta_spy": beta(r, rsp),
                  "corr_qqq": corr(r, rq), "corr_smh": corr(r, rs), "mdd1y": maxdd(s, i1y, n - 1),
                  "high1y": hi, "high1y_date": dates[hii], "low1y": lo, "low1y_date": dates[loi], "off_high": s[-1] / hi - 1, "off_low": s[-1] / lo - 1,
                  "beta_up": beta([a for a, b in up], [b for a, b in up]), "beta_dn": beta([a for a, b in dn], [b for a, b in dn]),
                  "src": SER[t]["src"]}
cm_t = [t for t in TICKERS["corr_matrix"] if has(t)]
R = {t: rets(t, i1y, n - 1) for t in cm_t}
cmat = [[round(corr(R[a], R[b]), 2) for b in cm_t] for a in cm_t]


def rolling(fa, fb, win=60, fn=corr):
    ra = rets(fa, 0, n - 1); rb = rets(fb, 0, n - 1); out = []
    for i in range(len(ra)):
        out.append(None if i < win - 1 else (lambda v: None if v is None else round(v, 3))(fn(ra[i - win + 1:i + 1], rb[i - win + 1:i + 1])))
    return out


roll = {"dates": dates[1:], "CIBR_SMH": rolling("CIBR", "SMH"), "CIBR_QQQ": rolling("CIBR", "QQQ"), "IGV_SMH": rolling("IGV", "SMH"),
        "CIBR_beta_QQQ": rolling("CIBR", "QQQ", 60, beta), "CIBR_beta_SMH": rolling("CIBR", "SMH", 60, beta)}
if has("^TNX"): roll["CIBR_TNX"] = rolling("CIBR", "^TNX")

# ---- CIBR 回撤阶段（≥5%）----
s = ser("CIBR"); eps = []; pk = s[0]; pki = 0; tr = s[0]; tri = 0; in_dd = False
for i in range(1, n):
    if s[i] >= pk and not in_dd:
        pk = s[i]; pki = i; tr = s[i]; tri = i; continue
    if s[i] < tr:
        tr = s[i]; tri = i; in_dd = (tr / pk - 1) <= -0.05
    if s[i] >= pk:
        if in_dd: eps.append({"peak": dates[pki], "trough": dates[tri], "recover": dates[i], "dd": round(tr / pk - 1, 4), "peak_px": pk, "trough_px": tr})
        pk = s[i]; pki = i; tr = s[i]; tri = i; in_dd = False
if in_dd: eps.append({"peak": dates[pki], "trough": dates[tri], "recover": None, "dd": round(tr / pk - 1, 4), "peak_px": pk, "trough_px": tr})

# ---- 大波动日 ----
mv = []
for i in range(i1y + 1, n):
    mv.append([dates[i]] + [round(ser(t)[i] / ser(t)[i - 1] - 1, 4) for t in ("CIBR", "SMH", "QQQ", "IGV")])
mv.sort(key=lambda x: x[1]); big = {"down": mv[:12], "up": mv[-12:][::-1]}


# ---- 月度 ----
def monthly(t):
    s = ser(t); out = {}
    for i, d in enumerate(dates):
        m = d[:7]
        if m not in out: out[m] = {"start": s[i - 1] if i > 0 else s[i]}
        out[m]["end"] = s[i]
    return {m: round(v["end"] / v["start"] - 1, 4) for m, v in out.items() if m >= dates[i1y][:7]}


mon = {t: monthly(t) for t in TICKERS["monthly"] if has(t)}

# ---- 技术面 ----
tech = {}
for t in TICKERS["tech_panel"]:
    if not has(t): continue
    s = ser(t); i = n - 1
    e12 = ema_series(s, 12); e26 = ema_series(s, 26); macd = [a - b for a, b in zip(e12, e26)]; sig = ema_series(macd, 9)
    m20 = sma(s, 20, i); sd20 = st.pstdev(s[i - 19:i + 1]); vol = SER[t]["v"]
    lo = min(s[i1y:]); hi = max(s[i1y:])
    v20 = sum(vol[i - 19:i + 1]) / 20; v100 = sum(vol[i - 99:i + 1]) / 100
    tech[t] = {"px": s[i], "ret1d": s[i] / s[i - 1] - 1, "ma20": m20, "ma50": sma(s, 50, i), "ma100": sma(s, 100, i), "ma200": sma(s, 200, i),
               "ma200_prev20": sma(s, 200, i - 20), "ma50_prev20": sma(s, 50, i - 20),
               "rsi14": rsi(s, i), "rsi14_prev": rsi(s, i - 1), "macd": macd[i], "macd_sig": sig[i], "macd_hist": macd[i] - sig[i],
               "bb_up": m20 + 2 * sd20, "bb_lo": m20 - 2 * sd20, "bb_pos": (s[i] - (m20 - 2 * sd20)) / (4 * sd20) if sd20 else None,
               "hi52": hi, "lo52": lo, "hi52_date": dates[s.index(hi, i1y)], "lo52_date": dates[s.index(lo, i1y)],
               "ret5": s[i] / s[i - 5] - 1, "ret20": s[i] / s[i - 20] - 1, "ret60": s[i] / s[i - 60] - 1,
               "vol_ratio": (v20 / v100) if v100 else None, "vol_1d_ratio": (vol[i] / v20) if v20 else None,
               "fib": {str(k): hi - (hi - lo) * k for k in (0.236, 0.382, 0.5, 0.618, 0.786)}}
    h = SER[t]["h"]; l = SER[t]["l"]
    if h[-1] is not None and all(x is not None for x in h[-15:] + l[-15:]):
        trs = [max(h[j] - l[j], abs(h[j] - s[j - 1]), abs(l[j] - s[j - 1])) for j in range(n - 14, n)]
        tech[t]["atr14"] = sum(trs) / 14
# 200 日线乖离两年区间（CIBR）
c = ser("CIBR"); ma200s = sma_series(c, 200)
dev = [(c[i] / ma200s[i] - 1) for i in range(n) if ma200s[i]]
tech["CIBR"]["dev200_min"] = min(dev) if dev else None; tech["CIBR"]["dev200_max"] = max(dev) if dev else None

# ---- 利率相关 ----
yc = {}
if has("^TNX"):
    tnx = ser("^TNX"); dy = [tnx[i] - tnx[i - 1] for i in range(i1y + 1, n)]
    yc = {f"corr_{t}": corr(rets(t, i1y, n - 1), dy) for t in ("CIBR", "IGV", "SMH", "QQQ")}


# ---- 图表序列 ----
def norm(t, a):
    s = ser(t); return [round(s[i] / s[a] * 100, 2) for i in range(a, n)]


rel = {"dates": dates[i1y:]}
for a, b in (("CIBR", "SMH"), ("CIBR", "QQQ"), ("IGV", "SMH")):
    sa, sb = ser(a), ser(b); base = sa[i1y] / sb[i1y]
    rel[f"{a}_{b}"] = [round((sa[i] / sb[i]) / base, 4) for i in range(i1y, n)]


def rvol(t, w=20):
    r = rets(t, 0, n - 1)
    return [None if i < w - 1 else round(st.pstdev(r[i - w + 1:i + 1]) * math.sqrt(252), 3) for i in range(len(r))]


rv = {"dates": dates[i1y:], **{t: rvol(t)[i1y - 1:] for t in ("CIBR", "SMH", "QQQ", "IGV")}}
pk = c[0]; uw = []
for v in c:
    pk = max(pk, v); uw.append(round((v / pk - 1) * 100, 2))
vol = SER["CIBR"]["v"]; v20 = sma_series(vol, 20)
topvol = sorted([[dates[i], vol[i], round(vol[i] / v20[i - 1], 2), round((c[i] / c[i - 1] - 1) * 100, 2)] for i in range(i1y, n) if v20[i - 1]], key=lambda x: -x[2])[:10]
leaders = [t for t in TICKERS["leaders"] if has(t)]
charts = {
    "dates1y": dates[i1y:], "dates2y": dates,
    "norm": {t: norm(t, i1y) for t in TICKERS["benchmarks"] if has(t)},
    "normLeaders": {t: norm(t, i1y) for t in leaders},
    "cibr": {"px": c, "ma50": sma_series(c, 50), "ma100": sma_series(c, 100), "ma200": ma200s, "uw": uw, "vol": vol, "v20": v20},
    "roll": {k: v[i1y - 1:] for k, v in roll.items() if k != "dates"}, "rollDates": roll["dates"][i1y - 1:],
    "rel": rel, "rvol": rv, "topvol": topvol,
}
out = {"asof": asof, "window_start": dates[i1y], "ytd_start": dates[iytd], "i1y": i1y, "iytd": iytd, "n": n,
       "summary": summary, "cm_t": cm_t, "cmat": cmat, "episodes": eps, "big": big, "monthly": mon, "tech": tech, "yield_corr": yc, "charts": charts,
       "sources": {"gateway": P.get("gateway"), "counts": P.get("counts"), "fetched_at": P.get("fetched_at"), "per_ticker": {t: SER[t]["src"] for t in SER}}}
save(RAW / "analytics.json", out)
log(f"analytics: 窗口 {dates[i1y]} → {asof}，CIBR {c[-1]} 1y {summary['CIBR']['ret1y']*100:.1f}% RSI {tech['CIBR']['rsi14']:.1f} MA200 {tech['CIBR']['ma200']:.2f}")
