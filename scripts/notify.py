#!/usr/bin/env python3
"""Telegram 推送：读 docs/data/meta.json 里的 alerts，去重后发。凭据在仓库外 ~/.cibr-live/.env（或沿用 ~/.ai-capital-flows/.env）。
状态 data/notify_state.json：{sent: {alert_key: date}}，同一条 zone/rsi/cal/data 信号同一状态只发一次；move 信号每天都发。
用法：python3 scripts/notify.py [--dry-run] [--force]
"""
import argparse, html, json, os, urllib.parse, urllib.request
from pathlib import Path
from common import ROOT, SITE_DATA, SETTINGS, load, save, log

STATE = ROOT / "data" / "notify_state.json"
ENV_FILES = [Path.home() / ".cibr-live" / ".env", Path.home() / ".ai-capital-flows" / ".env"]


def creds():
    env = {}
    for f in ENV_FILES:
        if f.exists():
            for line in f.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1); env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return os.environ.get("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID") or env.get("TELEGRAM_CHAT_ID")


def send(token, chat, text):
    data = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
    with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data), timeout=20) as r:
        return r.status


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--force", action="store_true"); a = ap.parse_args()
    M = load(SITE_DATA / "meta.json"); R = load(SITE_DATA / "report.json")
    state = load(STATE, {"sent": {}}); sent = state["sent"]
    asof = M["asof"]; todo = []
    for al in M.get("alerts", []):
        key = al["text"] if al["kind"] != "move" else f"move:{asof}:{al['text'][:12]}"
        if a.force or sent.get(key) != asof and (al["kind"] == "move" or key not in sent):
            todo.append((key, al))
    if not todo:
        log("notify: 没有新信号"); return
    S = R["summary"]; T = R["tech"]["CIBR"]
    head = (f"<b>CIBR 网安日报 · {asof}</b>\nCIBR {S['CIBR']['last']:.2f}（{S['CIBR']['ret1d']*100:+.1f}%）· 距高点 {S['CIBR']['off_high']*100:+.1f}% · "
            f"RSI {T['rsi14']:.0f} · MA50 {T['ma50']:.1f} / MA200 {T['ma200']:.1f}\n"
            f"SMH {S['SMH']['ret1d']*100:+.1f}% · IGV {S['IGV']['ret1d']*100:+.1f}% · QQQ {S['QQQ']['ret1d']*100:+.1f}%")
    icon = {"good": "🟢", "warning": "🟡", "serious": "🟠", "critical": "🔴"}
    body = "\n".join(f"{icon.get(al['level'],'•')} {html.escape(al['text'])}" for _, al in todo)
    url = M.get("site_url") or ""
    text = head + "\n\n" + body + (f"\n\n{url}" if url else "")
    if a.dry_run:
        print(text); return
    token, chat = creds()
    if not token or not chat:
        log("notify: 没有 Telegram 凭据，跳过"); return
    send(token, chat, text)
    for key, _ in todo: sent[key] = asof
    save(STATE, state, indent=1)
    log(f"notify: 已发 {len(todo)} 条")


if __name__ == "__main__":
    main()
