-- 仅用于本地开发实例（端口 3307，root 无密码）。
-- 生产环境请由 DBA 创建库与最小权限账号，不要使用本文件。
CREATE DATABASE IF NOT EXISTS lwa_dev CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS lwa_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS 'lwa'@'127.0.0.1' IDENTIFIED BY 'lwa_dev_password';
GRANT ALL PRIVILEGES ON lwa_dev.* TO 'lwa'@'127.0.0.1';
GRANT ALL PRIVILEGES ON lwa_test.* TO 'lwa'@'127.0.0.1';
FLUSH PRIVILEGES;
