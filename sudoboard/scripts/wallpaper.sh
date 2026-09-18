#!/usr/bin/env bash
# SudoBoard Skill · wallpaper.sh — 看板壁纸下载
# 默认下载官方示意壁纸（深/浅各一张）到 <dir>/assets/，供本地预览与同步上传用。
# 用户可随时用 --url/--file 换成任意自己的图片（dark/black 配深色看板，light/white 配浅色看板）。
#
# 用法:
#   wallpaper.sh [--dir <sudoboard工程目录>] [--only dark|light]
#   wallpaper.sh [--dir <dir>] --url <图片URL> [--name <文件名>]
#   wallpaper.sh [--dir <dir>] --file <本地图片>          # 复制进 assets/
set -euo pipefail

DEMO_BASE="https://sudb.106001.xyz/background/demo"
DIR="."
ONLY=""
URL=""
NAME=""
FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)  DIR="$2"; shift 2 ;;
    --only) ONLY="$2"; shift 2 ;;
    --url)  URL="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --file) FILE="$2"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

ASSETS="$DIR/assets"
mkdir -p "$ASSETS"

fetch() { # $1=url $2=dest
  echo "↓ 下载 $1"
  if ! curl -fsSL --max-time 120 --retry 2 -o "$2" "$1"; then
    echo "✗ 下载失败: $1" >&2
    return 1
  fi
}

copy_file() { # $1=src $2=dest
  cp -f "$1" "$2"
}

declare -a RESULTS=()

if [[ -n "$URL" ]]; then
  [[ -n "$NAME" ]] || NAME="$(basename "${URL%%\?*}")"
  [[ "$NAME" == *.jpg || "$NAME" == *.jpeg || "$NAME" == *.png || "$NAME" == *.webp || "$NAME" == *.svg ]] \
    || NAME="$NAME.jpg"
  DEST="$ASSETS/$NAME"
  fetch "$URL" "$DEST"
  RESULTS+=("$DEST")
elif [[ -n "$FILE" ]]; then
  [[ -f "$FILE" ]] || { echo "✗ 文件不存在: $FILE" >&2; exit 1; }
  NAME="${NAME:-$(basename "$FILE")}"
  DEST="$ASSETS/$NAME"
  copy_file "$FILE" "$DEST"
  RESULTS+=("$DEST")
else
  if [[ -z "$ONLY" || "$ONLY" == "dark" ]]; then
    DEST="$ASSETS/wallpaper-dark.jpg"
    fetch "$DEMO_BASE/dark-demo.jpg" "$DEST" && RESULTS+=("$DEST")
  fi
  if [[ -z "$ONLY" || "$ONLY" == "light" ]]; then
    DEST="$ASSETS/wallpaper-light.jpg"
    fetch "$DEMO_BASE/light-demo.jpg" "$DEST" && RESULTS+=("$DEST")
  fi
fi

echo ""
for f in "${RESULTS[@]:-}"; do
  [[ -n "$f" && -f "$f" ]] || continue
  SIZE=$(du -h "$f" | cut -f1)
  echo "✓ $f ($SIZE)"
done
echo ""
echo "下一步: 在 board.json 的 dashboard.background.file 里引用所需壁纸"
echo "  深色看板 → wallpaper-dark.jpg    浅色看板 → wallpaper-light.jpg"
