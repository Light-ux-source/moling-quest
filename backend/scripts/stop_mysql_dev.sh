#!/usr/bin/env bash
set -euo pipefail
PORT="${MYSQL_DEV_PORT:-3307}"
if mysqladmin --protocol=TCP -h127.0.0.1 -P"$PORT" -uroot ping >/dev/null 2>&1; then
  mysqladmin --protocol=TCP -h127.0.0.1 -P"$PORT" -uroot shutdown
  echo "已停止 127.0.0.1:$PORT 的开发 MySQL"
else
  echo "127.0.0.1:$PORT 没有运行中的 MySQL"
fi
