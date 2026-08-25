#!/bin/bash
# ════════════════════════════════════════════════════════════════════════════
# start.sh — Container başlatma scripti
# Sırayla: Xvfb → Openbox → x11vnc → noVNC → Telegram Bot
# ════════════════════════════════════════════════════════════════════════════

# Lock dosyalarını temizle (restart durumunda kalıntı kalabilir)
rm -f /tmp/.X99-lock /tmp/.x11vnc* 2>/dev/null || true

# Chrome profil kilit dosyalarını da temizle
rm -f /data/chrome-profile/SingletonLock \
      /data/chrome-profile/SingletonSocket \
      /data/chrome-profile/SingletonCookie \
      /data/chrome-profile/Default/lockfile 2>/dev/null || true

echo "[start.sh] Xvfb başlatılıyor..."
Xvfb :99 -screen 0 1280x800x24 -ac &
sleep 2

echo "[start.sh] Openbox başlatılıyor..."
DISPLAY=:99 openbox &
sleep 1

echo "[start.sh] x11vnc başlatılıyor..."
x11vnc \
    -display :99 \
    -passwd "${VNC_PASSWORD:-flowbot123}" \
    -shared \
    -forever \
    -noxdamage \
    -rfbport 5900 \
    -bg \
    -o /tmp/x11vnc.log
sleep 1

echo "[start.sh] noVNC başlatılıyor (port 6080)..."
/opt/novnc/utils/novnc_proxy \
    --vnc localhost:5900 \
    --listen 6080 &
sleep 2

echo "[start.sh] VNC erişimi: http://SUNUCU_IP:6080/vnc.html"
echo "[start.sh] VNC şifresi: ${VNC_PASSWORD:-flowbot123}"
echo "[start.sh] NOT: VNC sadece izleme/manuel giriş içindir."
echo "[start.sh] Bot kendi Chromium penceresini VNC üzerinde açacak."
echo ""
echo "[start.sh] Telegram botu başlatılıyor..."
exec python -m app.bot