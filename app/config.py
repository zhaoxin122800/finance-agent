"""配置加载 — 从环境变量 / .env 读取."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv 可选；用户也可手动 export 环境变量
    pass


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
VENDORS_DIR = PROJECT_ROOT / "vendors"
QUANT_KB_DIR = VENDORS_DIR / "quant_kb"
METHODOLOGY_FILE = VENDORS_DIR / "backtest_methodology.md"


@dataclass(frozen=True)
class Settings:
    # LLM
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    # 数据源
    data_source: str  # "free" | "paid"
    cache_ttl_realtime: int
    # 服务
    host: str
    port: int

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            llm_base_url=os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", "glm-4-flash"),
            data_source=os.getenv("DATA_SOURCE", "free"),
            cache_ttl_realtime=int(os.getenv("CACHE_TTL_REALTIME", "30")),
            host=os.getenv("HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "8000")),
        )

    @property
    def ai_enabled(self) -> bool:
        return bool(self.llm_api_key) and self.llm_api_key != "your-api-key-here"


def get_settings() -> Settings:
    return Settings.load()
