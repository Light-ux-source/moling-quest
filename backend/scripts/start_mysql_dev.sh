#!/usr/bin/env bash
# 启动一个独立的本地 MySQL（端口 3307），不碰系统已有的 3306 实例。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/.mysql/data"
RUN="$ROOT/.mysql/run"
LOG="$ROOT/.mysql/log"
PORT="${MYSQL_DEV_PORT:-3307}"
SOCKET="$RUN/mysql.sock"

mkdir -p "$DATA" "$RUN" "$LOG"

if ! command -v mysqld >/dev/null 2>&1; then
  echo "未找到 mysqld，请先安装 MySQL（brew install mysql）。" >&2
  exit 1
fi

if [ ! -d "$DATA/mysql" ]; then
  echo "初始化 MySQL 数据目录：$DATA"
  mysqld --initialize-insecure --datadir="$DATA" --basedir="$(brew --prefix mysql 2>/dev/null || echo /opt/homebrew/opt/mysql)" \
    --log-error="$LOG/init.log"
fi

if mysqladmin --protocol=TCP -h127.0.0.1 -P"$PORT" -uroot ping >/dev/null 2>&1; then
  echo "MySQL 已在 127.0.0.1:$PORT 运行"
else
  echo "启动 MySQL：127.0.0.1:$PORT"
  nohup mysqld --datadir="$DATA" --port="$PORT" --socket="$SOCKET" \
    --pid-file="$RUN/mysql.pid" --bind-address=127.0.0.1 --mysqlx=0 \
    --log-error="$LOG/mysqld.log" >/dev/null 2>&1 &
  for _ in $(seq 1 30); do
    if mysqladmin --protocol=TCP -h127.0.0.1 -P"$PORT" -uroot ping >/dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done
fi

if ! mysqladmin --protocol=TCP -h127.0.0.1 -P"$PORT" -uroot ping >/dev/null 2>&1; then
  echo "MySQL 启动失败，查看 $LOG/mysqld.log" >&2
  exit 1
fi

mysql --protocol=TCP -h127.0.0.1 -P"$PORT" -uroot < "$ROOT/scripts/init_mysql.sql"
echo "开发库已就绪：lwa_dev / lwa_test，用户 lwa"
echo "请确认 backend/.env 中 MYSQL_PORT=${PORT}、MYSQL_DATABASE=lwa_dev"
