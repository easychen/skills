#!/usr/bin/env bash
# SudoBoard Skill · install-skill.sh — 把本技能安装到 AI 助手的技能目录
#
# 用法:
#   bash install-skill.sh                     # 默认软链到 ~/.claude/skills/sudoboard
#   bash install-skill.sh --host dsh          # 装到 ~/.dsh/skills/sudoboard
#   bash install-skill.sh --dir ~/my/skills   # 指定技能目录
#   bash install-skill.sh --copy              # 复制而不是软链（打包分发/CI 用）
#   bash install-skill.sh --uninstall         # 卸载（只删自己装的那个链接/副本）
#
# 说明：技能目录必须同时包含 SKILL.md、scripts/、examples/、references/、tests/。
#      软链安装的好处：仓库更新后无需重装。
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HOST="claude"
TARGET=""
MODE="link"
UNINSTALL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)      HOST="$2"; shift 2 ;;
    --dir)       TARGET="$2"; shift 2 ;;
    --copy)      MODE="copy"; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help)   grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$TARGET" ]]; then
  case "$HOST" in
    claude) TARGET="$HOME/.claude/skills" ;;
    dsh)    TARGET="$HOME/.dsh/skills" ;;
    agents) TARGET="$HOME/.agents/skills" ;;
    *) echo "未知 host: ${HOST}（可选 claude|dsh|agents，或用 --dir 指定）" >&2; exit 2 ;;
  esac
fi

DEST="$TARGET/sudoboard"

if [[ "$UNINSTALL" == "1" ]]; then
  if [[ -L "$DEST" ]]; then
    rm -f "$DEST"; echo "✓ 已卸载软链: $DEST"
  elif [[ -d "$DEST" ]]; then
    rm -rf "$DEST"; echo "✓ 已卸载副本: $DEST"
  else
    echo "（未安装，跳过）: $DEST"
  fi
  exit 0
fi

[[ -f "$SKILL_DIR/SKILL.md" ]] || { echo "✗ 找不到 $SKILL_DIR/SKILL.md" >&2; exit 1; }
mkdir -p "$TARGET"

# 已存在且指向别处：先提示，避免误删用户自己的同名技能
if [[ -e "$DEST" || -L "$DEST" ]]; then
  if [[ "$(readlink "$DEST" 2>/dev/null || true)" == "$SKILL_DIR" ]]; then
    echo "✓ 已安装（软链指向本仓库），跳过: $DEST"
    exit 0
  fi
  echo "✗ $DEST 已存在且不是本仓库的软链；请先手动处理（或 --uninstall 后重装）" >&2
  exit 1
fi

if [[ "$MODE" == "copy" ]]; then
  cp -R "$SKILL_DIR" "$DEST"
  # 副本不带缓存/测试产物
  rm -rf "$DEST/scripts/__pycache__" "$DEST/tests/__pycache__"
  echo "✓ 已复制安装: $DEST"
else
  ln -s "$SKILL_DIR" "$DEST"
  echo "✓ 已软链安装: $DEST -> $SKILL_DIR"
fi

cat <<EOF

下一步：
  · 重启 / 重新加载 AI 助手会话，让技能目录被重新扫描；
  · 让助手说「用 sudoboard 技能给这个项目做数据看板」验证是否被识别。
可选环境变量：
  export SUDOBOARD_URL=http://<设备IP>:8866     # 默认 http://127.0.0.1:8866
  export SUDOBOARD_ADMIN_PIN=<管理员 PIN>        # 缺省时助手会询问
EOF
