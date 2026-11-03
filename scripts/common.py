"""公共：路径、配置读取、日志。"""
import json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
CONTENT = ROOT / "content"
RAW = ROOT / "data" / "raw"
DOCS = ROOT / "docs"
SITE_DATA = DOCS / "data"
LOGS = ROOT / "logs"
for d in (RAW, SITE_DATA / "archive", LOGS, CONTENT / "earnings"):
    d.mkdir(parents=True, exist_ok=True)


def load(name, default=None):
    """name 可以是 config/ 下的文件名，或任意 Path。"""
    p = Path(name) if isinstance(name, Path) or "/" in str(name) else CONFIG / name
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def save(path, obj, indent=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=indent, default=_default), encoding="utf-8")


def _default(x):
    import math
    if isinstance(x, float) and math.isnan(x):
        return None
    return str(x)


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def log(*a):
    print(datetime.now().strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


SETTINGS = load("settings.json", {})
TICKERS = load("tickers.json", {})
