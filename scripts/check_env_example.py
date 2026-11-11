#!/usr/bin/env python3
"""校验 backend/.env.example：必需项齐全、敏感项保持空值、可安全提交。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "backend" / ".env.example"

REQUIRED = [
    "ENV",
    "LLM_PROVIDER",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "ENABLE_WEB_SEARCH",
    "MYSQL_HOST",
    "MYSQL_PORT",
    "MYSQL_USER",
    "MYSQL_PASSWORD",
    "MYSQL_DATABASE",
    "WECHAT_APP_ID",
    "WECHAT_APP_SECRET",
    "DEV_LOGIN_ENABLED",
    "AUTH_TOKEN_TTL_DAYS",
    "QUOTA_ENFORCED",
    "GUEST_TRIAL_LIMIT",
    "DAILY_QUOTA_USER",
    "AVATAR_UPLOAD_DIR",
    "AVATAR_MAX_BYTES",
    "CORS_ORIGINS",
]

MUST_BE_EMPTY = ["DEEPSEEK_API_KEY", "WECHAT_APP_ID", "WECHAT_APP_SECRET"]

# 真实密钥/AppID 的典型形态；示例文件里不应出现
SECRET_PATTERNS = [
    re.compile(r"^sk-[A-Za-z0-9_\-]{16,}$"),
    re.compile(r"^wxa[0-9a-f]{16}$", re.IGNORECASE),
    re.compile(r"^[A-Za-z0-9_\-]{40,}$"),
]


def parse_env(text: str) -> dict:
    values: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def main() -> int:
    if not EXAMPLE.exists():
        print(f"缺少 {EXAMPLE}", file=sys.stderr)
        return 1
    values = parse_env(EXAMPLE.read_text(encoding="utf-8"))
    errors = []

    for key in REQUIRED:
        if key not in values:
            errors.append(f"缺少必填项：{key}")

    for key in MUST_BE_EMPTY:
        if values.get(key):
            errors.append(f"示例文件中的 {key} 必须留空，不能包含真实值")

    for key, value in values.items():
        if key in MUST_BE_EMPTY:
            continue
        if any(pattern.match(value) for pattern in SECRET_PATTERNS):
            errors.append(f"{key} 的值看起来像真实密钥，请改为占位/空值")

    if values.get("ENV") == "production" and values.get("DEV_LOGIN_ENABLED", "").lower() in {"1", "true", "yes"}:
        errors.append("ENV=production 时 DEV_LOGIN_ENABLED 不能为 true")

    if errors:
        for item in errors:
            print(f"ERROR: {item}", file=sys.stderr)
        return 1

    print(f"OK: {EXAMPLE.relative_to(ROOT)} 共 {len(values)} 项，必需项齐全，敏感项为空")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
