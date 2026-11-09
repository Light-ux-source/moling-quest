"""应用配置：全部通过环境变量 / .env 注入，代码里不出现任何密钥。"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "learn-with-ai"
    app_version: str = "0.1.0"
    env: str = "dev"

    # ---- LLM ----
    # auto: 有 key 用 deepseek，否则 mock；deepseek: 强制真实调用；mock: 强制离线
    llm_provider: str = "auto"
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"
    deepseek_thinking: bool = False          # 出题/判分默认关闭思考，省时省钱
    deepseek_timeout: float = 120.0
    deepseek_max_retries: int = 2

    # ---- 联网检索（DeepSeek 官方 Search API）----
    enable_web_search: bool = True
    search_count: int = 6
    search_qps_guard: bool = True

    # ---- 存储 ----
    sqlite_path: str = "./data/app.db"
    max_session_age_days: int = 7

    # ---- 业务限制 ----
    max_topic_chars: int = 200
    min_question_count: int = 3
    max_question_count: int = 10
    rate_limit_per_hour: int = 30

    # ---- 成本估算（元 / 百万 token，按高峰价保守估算）----
    cost_input_per_m: float = 2.0
    cost_output_per_m: float = 8.0

    cors_origins: str = "*"

    @property
    def is_mock(self) -> bool:
        if self.llm_provider == "mock":
            return True
        if self.llm_provider == "deepseek":
            return False
        return not bool(self.deepseek_api_key.strip())

    @property
    def mode(self) -> str:
        return "mock" if self.is_mock else "deepseek"


@lru_cache
def get_settings() -> Settings:
    return Settings()