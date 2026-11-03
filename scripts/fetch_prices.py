#!/usr/bin/env python3
"""取日线：IBKR Gateway 优先（一个连接取全部），失败回退 yfinance；指数（^TNX/^VIX）只走 yfinance。
每只标的都取不到时沿用上一次的序列并标记 stale。输出 data/raw/prices.json：
  {asof, fetched_at, dates[], series{T:{c,h,l,v,src}}, gateway, counts}
用法：python3 scripts/fetch_prices.py [--no-ibkr] [--only CIBR,SMH]
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


def fetch_yahoo(tickers, years):
    out = {}
    if not tickers:
        return out
    try:
        import yfinance as yf
    except ImportError:
        log("yfinance 未安装"); return out
    try:
        df = yf.download(tickers, period=f"{years}y", interval="1d", progress=False, auto_adjust=False, group_by="ticker", threads=True)
    except Exception as e:
        log(f"yfinance 失败: {e}"); return out
    for t in tickers:
        try:
            sub = df[t] if len(tickers) > 1 else df
            sub = sub.dropna(subset=["Close"])
            out[t] = {d.strftime("%Y-%m-%d"): (float(r["Open"]), float(r["High"]), float(r["Low"]), float(r["Close"]), float(r["Volume"] or 0)) for d, r in sub.iterrows()}
            last = list(out[t].items())[-1]
            log(f"  Yahoo {t}: {len(out[t])} 根，最后 {last[0]} {last[1][3]}")
        except Exception as e:
            log(f"  Yahoo {t} 解析失败: {str(e)[:120]}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-ibkr", action="store_true")
    ap.add_argument("--only", default="")
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
        if got:
            raw.update(got); src.update({t: "ibkr" for t in got})
    missing = [t for t in universe if t not in raw] + yahoo_only
    if missing:
        got = fetch_yahoo(missing, years)
        raw.update(got); src.update({t: "yahoo" for t in got})
    # 兜底：沿用上一次
    for t in universe + yahoo_only:
        if t not in raw and prev.get("series", {}).get(t):
            s = prev["series"][t]
            raw[t] = {d: (None, s["h"][i], s["l"][i], s["c"][i], s["v"][i]) for i, d in enumerate(prev["dates"]) if s["c"][i] is not None}
            src[t] = "stale:" + s.get("src", "?")
            log(f"  {t}: 今日取不到，沿用上次（{src[t]}）")
    if "CIBR" not in raw:
        raise SystemExit("CIBR 都取不到，放弃")
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
                c.append(round(r[3], 4)); h.append(round(r[1], 4)); l.append(round(r[2], 4)); v.append(int(r[4] or 0))
            else:  # 缺口前向填充（指数在美股交易日基本都有）
                c.append(lc); h.append(lh); l.append(ll); v.append(0)
        series[t] = {"c": c, "h": h, "l": l, "v": v, "src": src[t]}
    counts = {}
    for s in src.values():
        k = s.split(":")[0]; counts[k] = counts.get(k, 0) + 1
    out = {"asof": dates[-1], "fetched_at": now_utc(), "gateway": gateway, "counts": counts, "dates": dates, "series": series}
    save(OUT, out)
    log(f"写入 {OUT}：{len(dates)} 个交易日，截至 {dates[-1]}，来源 {counts}，gateway={gateway}")


if __name__ == "__main__":
    main()
