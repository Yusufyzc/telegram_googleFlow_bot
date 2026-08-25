# ════════════════════════════════════════════════════════════════════════════
# Dockerfile — Google Flow Telegram Bot (VNC + noVNC destekli)
# ════════════════════════════════════════════════════════════════════════════

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DISPLAY=:99 \
    VNC_PASSWORD=flowbot123

# ── Sistem bağımlılıkları ─────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Temel araçlar
    git curl wget unzip procps \
    # Xvfb (sanal ekran)
    xvfb \
    # Openbox (hafif pencere yöneticisi — Chromium için gerekli)
    openbox \
    # x11vnc (VNC server)
    x11vnc \
    # noVNC bağımlılıkları
    python3-websockify \
    # Chromium bağımlılıkları
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    libx11-6 libx11-xcb1 libxcb1 libxext6 libxrender1 \
    fonts-liberation libfontconfig1 libxss1 \
    && rm -rf /var/lib/apt/lists/*

# ── noVNC kur ────────────────────────────────────────────────────────────────
RUN git clone --depth 1 https://github.com/novnc/noVNC.git /opt/novnc \
    && git clone --depth 1 https://github.com/novnc/websockify.git /opt/novnc/utils/websockify \
    && ln -s /opt/novnc/vnc.html /opt/novnc/index.html

# ── Çalışma dizini ───────────────────────────────────────────────────────────
WORKDIR /bot

# ── Python bağımlılıkları ─────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# ── Playwright Chromium kurulumu ──────────────────────────────────────────────
RUN playwright install chromium

# ── Uygulama kodu ────────────────────────────────────────────────────────────
COPY app/ ./app/

# ── Dizinler ─────────────────────────────────────────────────────────────────
RUN mkdir -p /data /data/profiles /data/chrome-profile /tmp/flow_videos

# ── Başlatma scripti ──────────────────────────────────────────────────────────
COPY start.sh /start.sh
RUN chmod +x /start.sh

CMD ["/start.sh"]