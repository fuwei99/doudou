# /Dockerfile
# ====================================================================
# Dockerfile for doubao-2api (v2.0 - CDP 模式 + 持久化 Chrome)
# ====================================================================

FROM python:3.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# 安装系统依赖 + Google Chrome 稳定版
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg curl \
    # Chrome 核心运行时依赖
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libasound2 libatspi2.0-0 \
    libpango-1.0-0 libcairo2 \
    fonts-unifont fonts-liberation \
    && wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && apt-get install -y /tmp/chrome.deb \
    && rm /tmp/chrome.deb \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建非 root 用户并设置权限
RUN useradd --create-home appuser && \
    chown -R appuser:appuser /app && \
    # 为持久化 Chrome 用户数据目录预创建并设置权限
    mkdir -p /app/chrome_data && chown -R appuser:appuser /app/chrome_data

# 安装 Playwright 浏览器（仅用于 cookie-fetch.py 等独立脚本）
USER appuser
RUN playwright install chromium

# 容器环境默认配置
ENV CHROME_PATH=/usr/bin/google-chrome-stable
ENV CHROME_USER_DATA_DIR=/app/chrome_data
ENV CHROME_DEBUG_PORT=9222
ENV HEADLESS=true

EXPOSE 7860
CMD ["python", "main.py"]
