#!/usr/bin/env bash
# 自检 serverchan 技能所需的环境变量。绝不打印 SendKey 本身。
set -u

missing=0

if [ -z "${SERVERCHAN_SENDKEY:-}" ]; then
  echo "[serverchan] ✗ 缺少 SERVERCHAN_SENDKEY"
  echo "     请在 Server 酱后台获取 SendKey，加入当前项目环境变量 SERVERCHAN_SENDKEY。"
  echo "     · Server酱Turbo(SCT)：https://sct.ftqq.com → SendKey 形如 SCTxxxxxx"
  echo "     · Server酱³(SC3)    ：https://sc3.ft07.com → SendKey 形如 sctp<数字>t<token>"
  missing=1
else
  case "$SERVERCHAN_SENDKEY" in
    sctp*) echo "[serverchan] ✓ SERVERCHAN_SENDKEY 已配置(SC3 / sctp…，长度 ${#SERVERCHAN_SENDKEY})" ;;
    SCT*)  echo "[serverchan] ✓ SERVERCHAN_SENDKEY 已配置(SCT  / SCT…，长度 ${#SERVERCHAN_SENDKEY})" ;;
    *)     echo "[serverchan] ⚠ SERVERCHAN_SENDKEY 已配置，但前缀既非 sctp(SC3) 也非 SCT(Turbo)，请确认是否正确" ;;
  esac
fi

if [ "$missing" -ne 0 ]; then
  echo "[serverchan] 环境不完整，已停止。请补齐后重试。"
  exit 1
fi

echo "[serverchan] 环境自检通过。"
