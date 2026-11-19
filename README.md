# cibr-live — 网络安全行业 CIBR 龙头：持续更新的复盘报告

首版是 2026-11-03 的一次性 HTML 报告（`股票研究/网络安全行业_CIBR龙头年度复盘_2026-11-03.html`）。这个仓库把它拆成三层，
让**行情与统计每天自动刷新**、**财报后自动对照**、**叙事按需人工更新**，用 GitHub Pages 发布 `docs/`。

- 线上地址：https://becks-w.github.io/cibr-live/ ；仓库 https://github.com/Becks-w/cibr-live（Pages：main 分支 `/docs`）
- 页面：`docs/index.html`（静态壳，打开时读 `docs/data/report.json`；`?snapshot=YYYY-MM-DD` 看当日存档）
- 数据：`docs/data/report.json`（页面唯一数据源）、`docs/data/meta.json`（截至日 + 今日信号）、`docs/data/archive/`（每日存档）
- 原始行情 `data/raw/`（不进 git；公开仓库里只有归一化序列、指标和 CIBR 单只 ETF 的日线）

## 三层结构

| 层 | 文件 | 谁改 | 频率 |
|---|---|---|---|
| 行情与统计 | `scripts/fetch_prices.py` → `analyze.py` → `export.py` | 机器 | 每天 11:00，失败则 14:00 补跑（launchd，东八区） |
| 事实配置 | `config/fundamentals.json`（基本面快照、梯子倍数、持仓）、`config/calendar.json`（判决日 + 检验标准）、`config/zones.json`（观察区）、`config/events.json`（图表事件点） | 人 / `auto_earnings.py` | 财报后（自动）、再平衡后 |
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

依赖：Python 3.11+，`pip3 install ib_async yfinance`。IBKR Gateway（只读，127.0.0.1:4001）开着时走 IBKR，否则自动回退 Yahoo（Yahoo 没取到的代码隔 45 秒重试，共 3 次）。
两者都失败、或某只取到的数据比上次还旧时，沿用上一次的序列（`src` 标 `stale`），流程不中断，页面「今日信号」会提示，14:00 自动补跑。

漏掉某天的存档时补录：`python3 scripts/backfill.py 2026-11-17`（用现有行情截断到那天重算，只写 `docs/data/archive/<日期>.json`，不带入那天之后的财报结果）。

## 财报后（自动）

每日刷新在行情发布之后会跑 `scripts/auto_earnings.py`，不需要人触发：

1. **核对日期**：`config/calendar.json` 里标了 `tentative` 的财报日（21 天内到期），每 2 天用 `claude -p` 查一次公司公告。查到就改日历；发现公司其实已经发了，日期改成实际发布日并当场进入下一步。
2. **抽取对照**：财报日（美东）已过、还没有结果文件的事件，调 `earnings.py` 联网研究，按该事件的 `criteria` 逐条判定，写 `content/earnings/<TICKER>_<DATE>.json`，同时追加更新日志（含「对 CIBR 复盘的意义」）、图表事件点、NTM 收入。美东盘后发布约等于北京时间次日 05:00–06:30，所以 11:00 的刷新能拿到。
3. 有新结果就再导出、发布一次，最后合并成一条 Telegram。自动生成的源文件单独提交（`Auto earnings: …`）；某个文件运行前就有未提交的改动时不会被自动提交。

几种情况的处理：

| 情况 | 处理 |
|---|---|
| 公司还没发布 | 不写结果，日历显示「公司尚未发布，每日自动再查」；查到官方日期会改日历 |
| 抽取出错（超时等） | 当天 14:00 补跑再试一次，之后每天重试；累计 6 次失败后提示手动处理 |
| 财报后首日涨跌幅 | 抽取时那个交易日通常还没收盘，留空；之后由 `export.py` 用本页行情补（盘后发布看次日，盘前发布看当日） |
| 财报过去超过 14 天仍无结果 | 不再自动追 |

手动跑仍然可以（比如想换模型或补充说明）：

```bash
python3 scripts/earnings.py NET 2026-11-05 --extra "重点看 FCF"   # 公司没发布时不会写文件
python3 scripts/run.py --skip-fetch                              # 重新导出并发布
```

自动对照只改事实。带「叙事快照」标签的段落（核心结论、技术判断、三层过滤里的「谁满足谁不满足」）仍由人判断后改 `docs/index.html` 并更新 `settings.json` 的 `narrative_date`；在那之前，标签上会写明「未含 XX 财报」。
联网抽取的文字写入前统一做 HTML 转义。判定结果请对照一手来源复核，`unverified` 字段列出了没查到的数字。

## 定时

```bash
cp launchd/com.becks.cibr-live.plist ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.becks.cibr-live.plist
launchctl start com.becks.cibr-live     # 手动触发一次
tail -f logs/run.log
```

每天 11:00 正式刷新，14:00 补跑一次（本机时间 = 东八区）：上午已成功拿到新数据时，14:00 那次直接跳过；上午失败或有标的沿用旧数据时才真正重跑；行情没问题但财报对照出错时，14:00 只补跑财报对照。Mac 休眠错过会在唤醒后补跑。

## Telegram

凭据在仓库外 `~/.cibr-live/.env`（`TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`），没有就沿用 `~/.ai-capital-flows/.env`。
信号规则在 `config/settings.json`：CIBR 单日 ±3%、龙头单日 ±8%、RSI < 30 / > 75、进入观察区、框架失效/回撤结束、判决日前 2 天、新出的财报对照结果、财报日已过但公司未发布、自动对照多次失败、数据源降级。状态类信号同一状态只发一次。

## 发布

GitHub Pages：main 分支 `/docs` 目录。`docs/` 由本机定时任务自动提交（`Publish …`），改页面逻辑请改 `docs/index.html` 后走正常提交。
`config/settings.json` 的 `site_url` 填上 Pages 地址后，Telegram 消息和页脚会带链接。

## 指标口径

RSI(14) 用 Wilder 平滑（`analyze.py` 的 `rsi()`），与 IBKR / TradingView 默认一致。2026-11-19 之前用的是不做平滑的简单平均，急跌后偏低；那之前的每日存档保留原值。
