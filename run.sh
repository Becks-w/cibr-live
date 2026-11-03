#!/bin/bash
# launchd 入口：取数 + 分析 + 导出 + Telegram + git push。日志 logs/run.log
export PATH="/Users/beckywang/.local/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:/usr/local/bin:/usr/bin:/bin"
export LANG=en_US.UTF-8
cd "/Users/beckywang/Projects/cibr-live" || exit 1
echo "---- $(date '+%F %T') ----" >> logs/run.log
python3 scripts/run.py "$@" >> logs/run.log 2>&1
