#!/bin/sh
# 首次启动/升级时，把程序自带的类目模板复制到数据卷（已有的不覆盖，你上传的模板会保留）
set -e
mkdir -p "$LH_DATA_DIR" "$LH_TEMPLATE_DIR" "$LH_SHOPEE_TEMPLATE_DIR"
for f in /app/templates_lazada/*.xlsx; do
  [ -e "$f" ] || continue
  b=$(basename "$f"); [ -e "$LH_TEMPLATE_DIR/$b" ] || [ -e "$LH_TEMPLATE_DIR/_deleted" -a -n "$(ls "$LH_TEMPLATE_DIR/_deleted" 2>/dev/null | grep -F "$b")" ] || cp "$f" "$LH_TEMPLATE_DIR/"
done
for f in /app/templates_shopee/*.xlsx; do
  [ -e "$f" ] || continue
  b=$(basename "$f"); [ -e "$LH_SHOPEE_TEMPLATE_DIR/$b" ] || cp "$f" "$LH_SHOPEE_TEMPLATE_DIR/"
done
exec /venv/bin/python /app/app.py --no-browser
