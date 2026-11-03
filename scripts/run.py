#!/usr/bin/env python3
"""一键：取数 → 分析 → 导出 → 推送 → 发布（git add docs && commit && push）。
python3 scripts/run.py                 全流程
python3 scripts/run.py --skip-publish  本地看效果
python3 scripts/run.py --skip-fetch    用上次的行情重算（改了 config/content 后）
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
    if not st:
        log("publish: docs/ 没变化"); return
    subprocess.run(["git", "add", site], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-q", "-m", f"Publish {asof}"], cwd=ROOT, check=True)
    remotes = subprocess.run(["git", "remote"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    if not remotes:
        log("publish: 没有 remote，只提交不推送"); return
    p = subprocess.run(["git", "push", "-q"], cwd=ROOT, capture_output=True, text=True)
    log("publish: 已推送" if p.returncode == 0 else f"publish: push 失败 {p.stderr[-300:]}")


def main():
    ap = argparse.ArgumentParser()
    for f in ("fetch", "notify", "publish"): ap.add_argument(f"--skip-{f}", action="store_true")
    ap.add_argument("--no-ibkr", action="store_true")
    a = ap.parse_args()
    if not a.skip_fetch: step("fetch_prices.py", ["--no-ibkr"] if a.no_ibkr else [])
    step("analyze.py", []); step("export.py", [])
    if not a.skip_notify: step("notify.py", [])
    import json
    asof = json.loads((DOCS / "data" / "meta.json").read_text())["asof"]
    if not a.skip_publish: publish(asof)
    log("done")


if __name__ == "__main__":
    main()
