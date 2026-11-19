#!/usr/bin/env python3
"""补录漏掉的每日存档：用现有行情截断到那一天重算，只写 docs/data/archive/<日期>.json。
不会改 report.json / meta.json，也不会带入那天之后才有的财报结果和更新日志。
用法：python3 scripts/backfill.py 2026-11-17 [2026-11-18 ...]
"""
import os, subprocess, sys
from common import ROOT

for day in sys.argv[1:]:
    env = dict(os.environ, CIBR_BACKFILL=day)
    for name in ("analyze.py", "export.py"):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / name)], cwd=ROOT, env=env)
        if r.returncode != 0:
            raise SystemExit(f"{name} 失败（{day}）")
