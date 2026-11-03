# cibr-live — 网络安全行业 CIBR 龙头：持续更新的复盘报告

首版是 2026-11-03 的一次性 HTML 报告（`股票研究/网络安全行业_CIBR龙头年度复盘_2026-11-03.html`）。这个仓库把它拆成三层，
让**行情与统计每天自动刷新**、**财报后半自动对照**、**叙事按需人工更新**，用 GitHub Pages 发布 `docs/`。

- 线上地址：https://becks-w.github.io/cibr-live/ ；仓库 https://github.com/Becks-w/cibr-live（Pages：main 分支 `/docs`）
- 页面：`docs/index.html`（静态壳，打开时读 `docs/data/report.json`；`?snapshot=YYYY-MM-DD` 看当日存档）
- 数据：`docs/data/report.json`（页面唯一数据源）、`docs/data/meta.json`（截至日 + 今日信号）、`docs/data/archive/`（每日存档）
- 原始行情 `data/raw/`（不进 git；公开仓库里只有归一化序列、指标和 CIBR 单只 ETF 的日线）

## 三层结构

| 层 | 文件 | 谁改 | 频率 |
|---|---|---|---|
| 行情与统计 | `scripts/fetch_prices.py` → `analyze.py` → `export.py` | 机器 | 每天 07:30（launchd） |
| 事实配置 | `config/fundamentals.json`（基本面快照、梯子倍数、持仓）、`config/calendar.json`（判决日 + 检验标准）、`config/zones.json`（观察区）、`config/events.json`（图表事件点） | 人 / `earnings.py` | 财报后、再平衡后 |
| 叙事 | `docs/index.html` 里带「叙事快照」标签的段落、`content/updates.json`（更新日志） | 人（或让 Claude 改） | 有新判断时；改完把 `config/settings.json` 的 `narrative_date` 改成当天 |

页面上凡是数字表格、图表、「机器快照」、观察区状态、判决日倒数、今日信号，都是机器算的；凡是带「叙事快照 日期」标签的段落，是分析师当时的判断，不会自动变。

## 跑一次

```bash
python3 scripts/run.py --skip-publish        # 取数（IBKR 优先，Yahoo 回退）+ 分析 + 导出 + Telegram，不推送
python3 scripts/run.py --skip-fetch          # 改了 config/content 之后只重新导出
python3 scripts/run.py                       # 全流程，最后 git add docs && commit "Publish <日期>" && push
python3 scripts/fetch_prices.py --no-ibkr    # 只用 Yahoo
python3 scripts/notify.py --dry-run          # 看今天会发什么
python3 -m http.server 8766 --directory docs # 本地预览 http://localhost:8766（页面用 fetch，不能直接双击打开）
```

依赖：Python 3.11+，`pip3 install ib_async yfinance`。IBKR Gateway（只读，127.0.0.1:4001）开着时走 IBKR，否则自动回退 Yahoo；两者都失败沿用上一次并在页面标出。

## 财报后（半自动）

```bash
python3 scripts/earnings.py NET 2026-11-05   # claude -p 联网研究 → content/earnings/NET_2026-11-05.json
python3 scripts/run.py                       # 重新导出并发布
```

`earnings.py` 按 `config/calendar.json` 里该事件的 `criteria` 逐条判定通过/未通过，写入财报对照结果；同时在 `content/updates.json` 追加一条更新日志、`config/events.json` 追加图表事件点、更新 `config/fundamentals.json` 的 NTM 收入（梯子表随之重算）。
它只改这些事实；叙事段落（核心结论、技术判断、三层过滤里的「谁满足谁不满足」）仍由人判断后改 `docs/index.html`。
判定结果请对照一手来源复核，`unverified` 字段列出了没查到的数字。

## 定时

```bash
cp launchd/com.becks.cibr-live.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.becks.cibr-live.plist
launchctl start com.becks.cibr-live     # 手动触发一次
tail -f logs/run.log
```

每天 07:30（北京时间，美股收盘后）。Mac 休眠错过会在唤醒后补跑。

## Telegram

凭据在仓库外 `~/.cibr-live/.env`（`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`），没有就沿用 `~/.ai-capital-flows/.env`。
信号规则在 `config/settings.json`：CIBR 单日 ±3%、龙头单日 ±8%、RSI < 30 / > 75、进入观察区、框架失效/回撤结束、判决日前 2 天、财报已过未抽取、数据源降级。状态类信号同一状态只发一次。

## 发布

GitHub Pages：main 分支 `/docs` 目录。`docs/` 由本机定时任务自动提交（`Publish …`），改页面逻辑请改 `docs/index.html` 后走正常提交。
`config/settings.json` 的 `site_url` 填上 Pages 地址后，Telegram 消息和页脚会带链接。
