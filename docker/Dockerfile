# 上新/运营系统 —— NAS (QNAP / 群晖, x86_64) 用的 Docker 镜像
# 构建：在 NAS 上进入程序文件夹，运行  docker compose up -d --build
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    TZ=Asia/Bangkok

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv python3-pip ca-certificates curl tzdata fonts-thai-tlwg fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r /app/requirements.txt

# ---- OrcaSlicer 命令行（自动切片用，可关闭：docker-compose.yml 里 INSTALL_ORCA: "0"）----
ARG INSTALL_ORCA=1
ARG ORCA_URL=https://github.com/SoftFever/OrcaSlicer/releases/download/v2.3.1/OrcaSlicer_Linux_AppImage_Ubuntu2404_V2.3.1.AppImage
COPY docker/stubs /opt/orca-stubs
RUN if [ "$INSTALL_ORCA" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        libgtk-3-0t64 libgl1 libegl1 libglx0 libgstreamer1.0-0 libgstreamer-plugins-base1.0-0 \
        libwayland-egl1 libwayland-client0 libwayland-cursor0 libxkbcommon0 libdbus-1-3 libunwind8 \
        libepoxy0 libfontconfig1 libfreetype6 libharfbuzz0b libpango-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
      && rm -rf /var/lib/apt/lists/* \
      && mkdir -p /opt/orca && cd /opt/orca \
      && curl -fL --retry 3 -o orca.AppImage "$ORCA_URL" \
      && chmod +x orca.AppImage && ./orca.AppImage --appimage-extract >/dev/null \
      && mv squashfs-root/* . && rm -rf squashfs-root orca.AppImage \
      && printf '#!/bin/sh\nexport LD_LIBRARY_PATH=/opt/orca-stubs:/opt/orca/bin:$LD_LIBRARY_PATH\nexport LC_ALL=C\nexec /opt/orca/bin/orca-slicer "$@"\n' > /usr/local/bin/orca-slicer \
      && chmod +x /usr/local/bin/orca-slicer \
      && (/usr/local/bin/orca-slicer --help >/dev/null 2>&1 && echo "OrcaSlicer OK" || echo "OrcaSlicer 安装后自检失败（自动切片不可用，其他功能正常）"); \
    fi
ENV ORCA_PROFILES_DIR=/opt/orca/resources/profiles

COPY . /app
RUN chmod +x /app/docker/entrypoint.sh

ENV LH_DOCKER=1 HOST=0.0.0.0 PORT=8765 \
    LH_DATA_DIR=/data \
    LH_TEMPLATE_DIR=/data/templates_lazada \
    LH_SHOPEE_TEMPLATE_DIR=/data/templates_shopee
EXPOSE 8765
VOLUME ["/data"]
ENTRYPOINT ["/app/docker/entrypoint.sh"]
