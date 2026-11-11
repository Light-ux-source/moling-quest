"""应用配置：全部通过环境变量 / .env 注入，代码里不出现任何密钥。"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# 固定读取 backend/.env，避免从仓库根目录或其他 cwd 启动时漏载配置
# （漏载会表现为 wechat_login=false、数据库连接失败等“诡异 503/500”）。
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "learn-with-ai"
    app_version: str = "0.3.0"
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
    # Search API 的 Base URL 与 Chat 网关可能不同（如阿里云 MaaS 无 Search API）
    deepseek_search_base_url: str = "https://api.deepseek.com"
    search_count: int = 6
    search_qps_guard: bool = True

    # ---- MySQL ----
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "lwa"
    mysql_password: str = ""
    mysql_database: str = "lwa_dev"
    mysql_charset: str = "utf8mb4"
    mysql_connect_timeout: int = 10

    # ---- 账号 / 登录 ----
    wechat_app_id: str = ""
    wechat_app_secret: str = ""
    auth_token_ttl_days: int = 30
    # 仅非生产环境可用；生产必须关闭
    dev_login_enabled: bool = True

    # ---- 配额（单位：组；一组 = 一次 AI 造关）----
    quota_enforced: bool = True
    guest_trial_limit: int = 1
    daily_quota_user: int = 3
    vip_daily_quota: int = 10
    vip_enabled: bool = False
    quota_timezone: str = "Asia/Shanghai"

    # ---- 头像上传 ----
    avatar_upload_dir: str = "./data/uploads/avatars"
    avatar_max_bytes: int = 2 * 1024 * 1024

    # ---- 业务限制 ----
    max_topic_chars: int = 200
    min_question_count: int = 3
    max_question_count: int = 10
    rate_limit_per_hour: int = 30
    login_rate_limit_per_hour: int = 20

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

    @property
    def wechat_login_configured(self) -> bool:
        return bool(self.wechat_app_id.strip() and self.wechat_app_secret.strip())

    @property
    def dev_login_allowed(self) -> bool:
        return bool(self.dev_login_enabled) and self.env.strip().lower() not in {"production", "prod"}

    @property
    def mysql_dsn_safe(self) -> str:
        return f"{self.mysql_user}@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"


@lru_cache
def get_settings() -> Settings:
    return Settings()