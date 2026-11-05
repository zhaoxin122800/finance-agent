"""vendors 包 —— 外部 Python 资产原样存放。

sim_trade.py 内部硬编码了 ACCOUNT_FILE 和 SKILL_SCRIPTS 绝对路径,
与设计 4.9「data/sim_account.json 为唯一来源」冲突。
这里在 import sim_trade 后用 monkeypatch 重定向到项目内路径,
保持 vendors 文件物理原样(便于以后同步上游升级)。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

VENDORS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = VENDORS_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 1. 让 sim_trade / portfolio 能 import 同目录的 analyze
#    (它们的代码里 sys.path.insert 指向了 autoclaw 目录,这里覆盖优先级)
if str(VENDORS_DIR) not in sys.path:
    sys.path.insert(0, str(VENDORS_DIR))

# 2. 重定向 sim_trade 的账户文件路径 —— 通过环境变量
os.environ["FINANCE_AGENT_DATA_DIR"] = str(DATA_DIR)

# 触发 sim_trade 导入并打补丁(惰性:只在首次 import vendors 时)
try:
    import vendors.sim_trade as _sim_trade
    _sim_trade.ACCOUNT_FILE = DATA_DIR / "sim_account.json"
    # SKILL_SCRIPTS 重定向到 vendors 目录本身
    _sim_trade.SKILL_SCRIPTS = str(VENDORS_DIR)
    # portfolio 同理(虽然 M1 不用,但避免它写错位置)
    import vendors.portfolio as _portfolio
    _portfolio.PORTFOLIO_FILE = DATA_DIR / "portfolio.json"
except ImportError:
    # import 链可能因 analyze 缺少某些运行时条件失败,留到真正用时再报错
    pass

# 3. 修补 data.get_sectors 的正则 bug(新浪返回无结尾分号,原正则要求 \s*; 失败)
#    用宽松正则覆盖,保持 data.py 物理原样。修复后 get_sectors 返回 list[dict]。
try:
    import json as _json
    import re as _re
    import urllib.request as _urlreq
    import vendors.data as _data

    _SINA_SECTOR_URL_PATCHED = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"

    def _get_sectors_patched():
        """宽松正则版 get_sectors(不要求结尾分号)。"""
        try:
            req = _urlreq.Request(_SINA_SECTOR_URL_PATCHED, headers={"User-Agent": "Mozilla/5.0"})
            text = _urlreq.urlopen(req, timeout=10).read().decode("gbk", errors="ignore")
            match = _re.search(r"var\s+S_Finance_bankuai_\w+\s*=\s*(\{.*\})", text, _re.DOTALL)
            if not match:
                return []
            raw = _json.loads(match.group(1))
            result = []
            for val in raw.values():
                if not isinstance(val, str):
                    continue
                fields = val.split(",")
                if len(fields) >= 13:
                    try:
                        change_pct = float(fields[4])
                    except (ValueError, IndexError):
                        change_pct = 0.0
                    result.append({
                        "name": fields[1],
                        "change_pct": round(change_pct, 2),
                        "leader_stock": fields[12] if len(fields) > 12 else "",
                    })
            return result
        except Exception:
            return []

    _data.get_sectors = _get_sectors_patched
except ImportError:
    pass
