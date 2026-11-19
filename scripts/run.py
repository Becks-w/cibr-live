#!/usr/bin/env python3
"""一键：取数 → 分析 → 导出 → 推送 → 发布（git add docs && commit && push）。
python3 scripts/run.py                 全流程
python3 scripts/run.py --skip-publish  本地看效果
python3 scripts/run.py --skip-fetch    用上次的行情重算（改了 config/content 后）
python3 scripts/run.py --retry-only    今天已成功刷新就跳过，否则补跑
python3 scripts/run.py --skip-earnings 不做财报后自动对照

顺序：行情先发布 → 财报后自动对照（auto_earnings.py，有到期财报才会调 claude）→ 有新结果就再导出发布一次 → 最后统一推送。
"""
import argparse, subprocess, sys
from common import ROOT, DOCS, log

PY = sys.executable


def step(name, args):
    log(f"== {name}")
    r = subprocess.run([PY, str(ROOT / "scripts" / name)] + args, cwd=ROOT)
    if r.returncode != 0:
        raise SystemExit(f"{name} 失败（exit {r.returncode}）")


def publish(asof):
    site = str(DOCS.relative_to(ROOT))
    st = subprocess.run(["git", "status", "--porcelain", site], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if st:
        subprocess.run(["git", "add", site], cwd=ROOT, check=True)
        subprocess.run(["git", "commit", "-q", "-m", f"Publish {asof}"], cwd=ROOT, check=True)
    else:
        ahead = subprocess.run(["git", "rev-list", "--count", "@{u}..HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        if ahead in ("", "0"):
            log("publish: docs/ 没变化"); return
    remotes = subprocess.run(["git", "remote"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    if not remotes:
        log("publish: 没有 remote，只提交不推送"); return
    p = subprocess.run(["git", "push", "-q"], cwd=ROOT, capture_output=True, text=True)
    log("publish: 已推送" if p.returncode == 0 else f"publish: push 失败 {p.stderr[-300:]}")


def auto_earnings(skip_publish):
    """财报后自动对照。任何异常都不能拖垮每日刷新。"""
    try:
        import auto_earnings as AE
        return AE.run(commit=not skip_publish)
    except BaseException as ex:  # 包括 SystemExit / 超时
        log(f"auto_earnings 出错，跳过：{str(ex)[:300]}")
        return {"changed": False, "retry": True, "new": [], "errors": ["auto_earnings"]}


def main():
    ap = argparse.ArgumentParser()
    for f in ("fetch", "notify", "publish", "earnings"): ap.add_argument(f"--skip-{f}", action="store_true")
    ap.add_argument("--no-ibkr", action="store_true")
    ap.add_argument("--retry-only", action="store_true", help="补跑：今天已经成功取到新数据、也没有待重试的财报对照就直接退出（launchd 14:00 用）")
    a = ap.parse_args()
    import json
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    last_f = ROOT / "data" / "raw" / "last_run.json"
    last = json.loads(last_f.read_text()) if last_f.exists() else {}
    if a.retry_only and last:
        if last.get("day") == today and last.get("ok"):
            if not last.get("earnings_retry"):
                log(f"retry-only: 今天 {last.get('at')} 已成功刷新到 {last.get('asof')}，跳过"); return
            log("retry-only: 行情今天已刷新，只补跑上午失败的财报对照"); a.skip_fetch = True
        else:
            log(f"retry-only: 今天还没有成功的刷新（上次 {last.get('day')} ok={last.get('ok')}），补跑")
    if not a.skip_fetch:
        step("fetch_prices.py", ["--no-ibkr"] if a.no_ibkr else [])
        try: step("holdings_px.py", [])   # 持仓表补充数据：失败只影响那几列，不拦主流程
        except SystemExit as e: log(f"holdings_px 失败，持仓表补充列沿用上次：{e}")
    step("analyze.py", []); step("export.py", [])
    asof = json.loads((DOCS / "data" / "meta.json").read_text())["asof"]
    if not a.skip_publish: publish(asof)   # 先把行情发出去，财报对照可能要跑十几分钟
    if a.skip_earnings:
        er = {"changed": False, "retry": bool(last.get("earnings_retry")) and last.get("day") == today}
    else:
        log("== auto_earnings")
        er = auto_earnings(a.skip_publish)
        if er.get("changed"):
            step("export.py", [])
            if not a.skip_publish: publish(asof)
    if not a.skip_notify: step("notify.py", [])   # 放最后：财报结果和行情信号合成一条消息
    if not a.skip_fetch:  # 记录今天这次取数是否拿到了新数据，供 14:00 补跑判断
        P = json.loads((ROOT / "data" / "raw" / "prices.json").read_text())
        ok = not P.get("stale")
        last = {"day": today, "at": datetime.now().strftime("%H:%M"), "asof": P["asof"], "ok": ok, "stale": len(P.get("stale") or []), "gateway": P.get("gateway")}
        if not ok: log(f"注意：{len(P['stale'])} 只标的沿用旧数据，14:00 会自动补跑")
    last["earnings_retry"] = bool(er.get("retry"))
    if last.get("day"): last_f.write_text(json.dumps(last))
    if er.get("retry"): log("注意：有财报对照失败，14:00 会再试一次")
    log("done")


if __name__ == "__main__":
    main()
