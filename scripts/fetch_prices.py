#!/usr/bin/env python3
"""取日线：IBKR Gateway 优先（一个连接取全部），失败回退 yfinance；指数（^TNX/^VIX）只走 yfinance。
每只标的都取不到时沿用上一次的序列并标记 stale。输出 data/raw/prices.json：
  {asof, fetched_at, dates[], series{T:{c,h,l,v,src}}, gateway, counts}
用法：python3 scripts/fetch_prices.py [--no-ibkr] [--no-yahoo] [--only CIBR,SMH] [--retry-wait 45]
两个来源都取不到时不退出：全部沿用上一次的序列（src 标 stale），页面会显示数据未更新。
"""
import argparse, time
from datetime import datetime, timedelta
from common import RAW, TICKERS, load, save, log, now_utc

OUT = RAW / "prices.json"


def duration(years):
    return f"{years} Y"


def fetch_ibkr(tickers, years, cfg):
    """返回 {T: {date: (o,h,l,c,v)}}；连不上返回 None。"""
    try:
        from ib_async import IB, Stock
    except ImportError:
        log("ib_async 未安装，跳过 IBKR")
        return None
    ib = IB()
    try:
        ib.connect(cfg.get("host", "127.0.0.1"), cfg.get("port", 4001), clientId=cfg.get("client_id", 48), readonly=True, timeout=10)
    except Exception as e:
        log(f"IBKR Gateway 连接失败: {e}")
        return None
    out = {}
    try:
        for t in tickers:
            c = Stock(t, "SMART", "USD")
            try:
                ib.qualifyContracts(c)
                bars = None
                for attempt in range(2):
                    try:
                        bars = ib.reqHistoricalData(c, endDateTime="", durationStr=duration(years), barSizeSetting="1 day",
                                                    whatToShow="TRADES", useRTH=True, formatDate=1, timeout=30)
                        break
                    except Exception as e:
                        if "pacing" in str(e).lower():
                            log("  pacing，等 15 秒"); time.sleep(15)
                        else:
                            raise
                if bars:
                    out[t] = {str(b.date): (float(b.open), float(b.high), float(b.low), float(b.close), float(b.volume)) for b in bars}
                    log(f"  IBKR {t}: {len(bars)} 根，最后 {bars[-1].date} {bars[-1].close}")
                else:
                    log(f"  IBKR {t}: 无数据")
            except Exception as e:
                log(f"  IBKR {t} 失败: {str(e)[:120]}")
            time.sleep(0.3)
    finally:
        ib.disconnect()
    return out


def _yahoo_once(tickers, years):
    """一次 yfinance 批量请求。只返回确实有数据的代码（空结果不写入，否则会挡住后面的兜底）。"""
    out = {}
    try:
        import yfinance as yf
    except ImportError:
        log("yfinance 未安装"); return out
    try:
        df = yf.download(tickers, period=f"{years}y", interval="1d", progress=False, auto_adjust=False, group_by="ticker", threads=True)
    except Exception as e:
        log(f"yfinance 失败: {str(e)[:160]}"); return out
    for t in tickers:
        try:
            sub = df[t] if len(tickers) > 1 else df
            sub = sub.dropna(subset=["Close"])
            m = {d.strftime("%Y-%m-%d"): (float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]), float(r["Volume"] or 0)) for d, r in sub.iterrows()}
            if not m:
                continue
            out[t] = m
            last = max(m)
            log(f"  Yahoo {t}: {len(m)} 根，最后 {last} {m[last][3]}")
        except Exception as e:
            log(f"  Yahoo {t} 解析失败: {str(e)[:120]}")
    return out


def fetch_yahoo(tickers, years, attempts=3, wait=45):
    """Yahoo 偶发整体故障（全部报 possibly delisted），所以对没取到的代码隔一会儿重试。"""
    out = {}; todo = list(tickers)
    for k in range(attempts):
        if not todo:
            break
        if k:
            log(f"Yahoo 还有 {len(todo)} 只没取到，{wait} 秒后第 {k + 1} 次尝试")
            time.sleep(wait)
        out.update(_yahoo_once(todo, years))
        todo = [t for t in tickers if t not in out]
    if todo:
        log(f"Yahoo 最终仍缺 {len(todo)} 只：{', '.join(todo)}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ibkr", action="store_true")
    ap.add_argument("--no-yahoo", action="store_true", help="测试用：模拟 Yahoo 不可用")
    ap.add_argument("--only", default="")
    ap.add_argument("--retry-wait", type=int, default=45)
    a = ap.parse_args()
    years = int(TICKERS.get("history_years", 2))
    universe = list(TICKERS["universe"]); yahoo_only = list(TICKERS.get("yahoo_only", []))
    if a.only:
        keep = set(a.only.split(","))
        universe = [t for t in universe if t in keep]; yahoo_only = [t for t in yahoo_only if t in keep]
    prev = load(OUT) if OUT.exists() else {}
    raw = {}; src = {}
    gateway = "skipped"
    if not a.no_ibkr:
        got = fetch_ibkr(universe, years, TICKERS.get("ibkr", {}))
        gateway = "down" if got is None else "connected"
        for t, m in (got or {}).items():
            if m: raw[t] = m; src[t] = "ibkr"
    missing = [t for t in universe if t not in raw] + yahoo_only
    if missing and not a.no_yahoo:
        for t, m in fetch_yahoo(missing, years, wait=a.retry_wait).items():
            if m: raw[t] = m; src[t] = "yahoo"
    # 兜底：今天没取到、或取到的比上次还旧 → 沿用上一次
    stale = []
    pdates = prev.get("dates", [])
    for t in universe + yahoo_only:
        ps = prev.get("series", {}).get(t)
        prev_last = max((d for i, d in enumerate(pdates) if ps["c"][i] is not None), default=None) if ps else None
        got_last = max(raw[t]) if raw.get(t) else None
        if got_last and (not prev_last or got_last >= prev_last):
            continue
        if ps and prev_last:
            raw[t] = {d: (None, ps["h"][i], ps["l"][i], ps["c"][i], ps["v"][i]) for i, d in enumerate(pdates) if ps["c"][i] is not None}
            src[t] = "stale:" + str(ps.get("src", "?")).split(":")[-1]
            stale.append(t)
            log(f"  {t}: 今日取不到（或比上次旧），沿用上次（截至 {prev_last}，{src[t]}）")
        elif not got_last:
            raw.pop(t, None); src.pop(t, None)
            log(f"  {t}: 取不到且没有历史可沿用，跳过")
    if not raw.get("CIBR"):
        raise SystemExit("CIBR 取不到且没有上一次的数据可沿用，放弃")
    # 主日期轴：CIBR 的交易日，截到 2 年内
    dates = sorted(raw["CIBR"].keys())
    cutoff = (datetime.strptime(dates[-1], "%Y-%m-%d") - timedelta(days=365 * years + 7)).strftime("%Y-%m-%d")
    dates = [d for d in dates if d >= cutoff]
    series = {}
    for t, m in raw.items():
        c = []; h = []; l = []; v = []
        lc = lh = ll = None
        for d in dates:
            r = m.get(d)
            if r and r[3] is not None:
                lc, lh, ll = r[3], r[1], r[2]
                c.append(round(r[3], 4)); h.append(round(r[1], 4) if r[1] is not None else None); l.append(round(r[2], 4) if r[2] is not None else None); v.append(int(r[4] or 0))
            else:  # 缺口前向填充（指数在美股交易日基本都有）
                c.append(lc); h.append(lh); l.append(ll); v.append(0)
        series[t] = {"c": c, "h": h, "l": l, "v": v, "src": src[t]}
    counts = {}
    for x in src.values():
        k = x.split(":")[0]; counts[k] = counts.get(k, 0) + 1
    fresh = len(stale) == 0
    out = {"asof": dates[-1], "fetched_at": now_utc(), "gateway": gateway, "counts": counts, "stale": stale, "all_stale": len(stale) == len(series),
           "dates": dates, "series": series}
    save(OUT, out)
    log(f"写入 {OUT}：{len(dates)} 个交易日，截至 {dates[-1]}，来源 {counts}，gateway={gateway}" + ("" if fresh else f"，{len(stale)} 只沿用旧数据"))


if __name__ == "__main__":
    main()
