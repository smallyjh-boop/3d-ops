#!/bin/sh
# NAS「免构建」启动脚本：Container Station 直接用 ubuntu:24.04 镜像运行它，不需要 SSH / docker build。
# 第一次启动会自动安装 Python 依赖和 OrcaSlicer（约 5-15 分钟，需要联网），之后几秒钟就能启动。
set -e
RT=/data/.runtime
mkdir -p "$RT" /data/templates_lazada /data/templates_shopee
export LH_DOCKER=1 HOST=${HOST:-0.0.0.0} PORT=${PORT:-8765} LH_DATA_DIR=/data \
       LH_TEMPLATE_DIR=/data/templates_lazada LH_SHOPEE_TEMPLATE_DIR=/data/templates_shopee \
       PYTHONUNBUFFERED=1 LANG=C.UTF-8 DEBIAN_FRONTEND=noninteractive \
       U2NET_HOME=/data/.runtime/u2net
INSTALL_ORCA=${INSTALL_ORCA:-1}

log() { echo "[nas-start] $*"; }

# 1) 系统软件（容器重建后需要重新装一次）
fix_dpkg() {
  # 群晖/威联通的容器文件系统上，systemd 等系统服务包的安装脚本会失败（容器里本来也用不到它们），
  # 把这些包的安装后脚本换成空操作，再让 dpkg 完成配置。
  for p in systemd systemd-sysv systemd-timesyncd udev dbus dbus-system-bus-common dbus-daemon libpam-systemd; do
    for f in /var/lib/dpkg/info/$p.postinst /var/lib/dpkg/info/$p:amd64.postinst; do
      [ -f "$f" ] && printf '#!/bin/sh\nexit 0\n' > "$f"
    done
  done
  dpkg --configure -a || true
}
apt_install() {
  # 安装失败时先修复 dpkg 再重试（最多两次）
  apt-get install -y --no-install-recommends "$@" && return 0
  log "安装出错，尝试修复后重试…"
  fix_dpkg
  apt-get install -y -f --no-install-recommends || { fix_dpkg; true; }
  apt-get install -y --no-install-recommends "$@" && return 0
  fix_dpkg
  apt-get install -y --no-install-recommends "$@"
}
fix_dpkg >/dev/null 2>&1 || true
if [ -n "$TZ" ] && [ -e "/usr/share/zoneinfo/$TZ" ]; then ln -fs "/usr/share/zoneinfo/$TZ" /etc/localtime; fi
if [ ! -f /opt/.deps_ok ]; then
  log "安装系统依赖（Python）…"
  apt-get update
  if ! apt_install python3 python3-venv ca-certificates curl; then
    log "基础软件安装失败，5 分钟后自动重试。请把这段日志截图发给开发者。"
    sleep 300; exit 1
  fi
  mkdir -p /opt && touch /opt/.deps_ok
fi
if [ "$INSTALL_ORCA" = "1" ] && [ ! -f /opt/.orca_deps_ok ] && [ ! -f /opt/.orca_deps_failed ]; then
  log "安装 OrcaSlicer 需要的图形库…"
  [ -d /var/lib/apt/lists/partial ] || apt-get update
  if apt_install libgtk-3-0t64 libgl1 libegl1 libglx0 libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 \
      libwayland-egl1 libwayland-client0 libwayland-cursor0 libxkbcommon0 libdbus-1-3 libunwind8 \
      libepoxy0 libfontconfig1 libfreetype6 libharfbuzz0b libpango-1.0-0 libcairo2 libgdk-pixbuf-2.0-0; then
    touch /opt/.orca_deps_ok
  else
    log "图形库安装失败：自动切片暂时不可用，其他功能正常（可以用「导入切片文件」）"
    touch /opt/.orca_deps_failed
  fi
fi
rm -rf /var/lib/apt/lists/* 2>/dev/null || true
[ -f /opt/.orca_deps_ok ] || INSTALL_ORCA=0

# 2) Python 虚拟环境放在数据卷里，容器重建也不用重装
REQ_HASH=$(md5sum /app/requirements.txt | cut -d' ' -f1)
if [ ! -x "$RT/venv/bin/python" ] || [ "$(cat "$RT/venv/.req" 2>/dev/null)" != "$REQ_HASH" ]; then
  log "安装 Python 依赖…"
  python3 -m venv "$RT/venv"
  "$RT/venv/bin/pip" install --no-cache-dir -q -r /app/requirements.txt
  echo "$REQ_HASH" > "$RT/venv/.req"
fi

# 3) OrcaSlicer（自动切片，可选）
if [ "$INSTALL_ORCA" = "1" ]; then
  ORCA_URL=${ORCA_URL:-https://github.com/SoftFever/OrcaSlicer/releases/download/v2.3.1/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.3.1.AppImage}
  if [ ! -x "$RT/orca/bin/orca-slicer" ]; then
    log "下载 OrcaSlicer（约 110MB）…"
    rm -rf "$RT/orca" "$RT/orca_tmp" && mkdir -p "$RT/orca_tmp" && cd "$RT/orca_tmp"
    if curl -fL --retry 3 -o orca.AppImage "$ORCA_URL" && chmod +x orca.AppImage && ./orca.AppImage --appimage-extract >/dev/null; then
      mv squashfs-root "$RT/orca"
    else
      log "OrcaSlicer 下载/解压失败：自动切片不可用（其他功能正常，可用「导入切片文件」）"
    fi
    cd / && rm -rf "$RT/orca_tmp"
  fi
  if [ -x "$RT/orca/bin/orca-slicer" ]; then
    printf '#!/bin/sh\nexport LD_LIBRARY_PATH=/app/docker/stubs:%s/orca/bin:$LD_LIBRARY_PATH\nexport LC_ALL=C\nexec %s/orca/bin/orca-slicer "$@"\n' "$RT" "$RT" > /usr/local/bin/orca-slicer
    chmod +x /usr/local/bin/orca-slicer
    export ORCA_PROFILES_DIR="$RT/orca/resources/profiles"
  fi
fi

# 4) 内置类目模板复制到数据卷（不覆盖已有的，已删除的不恢复）
for f in /app/templates_lazada/*.xlsx; do
  [ -e "$f" ] || continue
  b=$(basename "$f")
  [ -e "/data/templates_lazada/$b" ] && continue
  ls /data/templates_lazada/_deleted 2>/dev/null | grep -qF "$b" && continue
  cp "$f" /data/templates_lazada/
done
for f in /app/templates_shopee/*.xlsx; do
  [ -e "$f" ] || continue
  [ -e "/data/templates_shopee/$(basename "$f")" ] || cp "$f" /data/templates_shopee/
done

log "启动3D 运营管理系统…"
exec "$RT/venv/bin/python" /app/app.py --no-browser
