#!/usr/bin/env bash
# Server 酱消息推送。逻辑对齐 easychen/serverchan-sdk：
#   - SendKey 以 sctp 开头 → Server酱³(SC3)：https://<num>.push.ft07.com/send/<sendkey>.send
#     其中 num 取自 sendkey 的 ^sctp(\d+)t
#   - 其余 → Server酱Turbo(SCT)：https://sctapi.ftqq.com/<sendkey>.send
# POST JSON：{title, desp, ...options}；options 透传额外字段（tags/short/channel/noip 等）。
#
# 用法:
#   send.sh "<标题>" ["<正文desp，支持Markdown>"] ['<options JSON，可选>']
# 例:
#   send.sh "部署完成" "服务已上线 ✅"
#   send.sh "告警" "CPU **95%**\n\n请处理" '{"tags":"运维|告警","short":"CPU 95%"}'
#
# 退出码：服务端返回 code==0 视为成功(0)；否则非 0。SendKey 绝不打印。
set -u

if [ -z "${SERVERCHAN_SENDKEY:-}" ]; then
  echo "[serverchan] 缺少 SERVERCHAN_SENDKEY，已停止。" >&2
  exit 1
fi

TITLE="${1:-}"
DESP="${2:-}"
OPTIONS="${3:-}"

if [ -z "$TITLE" ]; then
  echo "[serverchan] 用法: send.sh \"<标题>\" [\"<正文desp>\"] ['<options JSON>']" >&2
  exit 2
fi

# 选择推送端点（不打印完整 sendkey）
case "$SERVERCHAN_SENDKEY" in
  sctp*)
    num="$(printf '%s' "$SERVERCHAN_SENDKEY" | sed -n 's/^sctp\([0-9][0-9]*\)t.*/\1/p')"
    if [ -z "$num" ]; then
      echo "[serverchan] SendKey 以 sctp 开头但格式非法(应为 sctp<数字>t<token>)。" >&2
      exit 2
    fi
    URL="https://${num}.push.ft07.com/send/${SERVERCHAN_SENDKEY}.send"
    ;;
  *)
    URL="https://sctapi.ftqq.com/${SERVERCHAN_SENDKEY}.send"
    ;;
esac

# 组装 JSON body：title + desp + 展开 options。优先用 python3 保证转义正确。
if command -v python3 >/dev/null 2>&1; then
  BODY="$(TITLE="$TITLE" DESP="$DESP" OPTIONS="$OPTIONS" python3 - <<'PY'
import os, json
body = {"title": os.environ["TITLE"], "desp": os.environ.get("DESP", "")}
opt = os.environ.get("OPTIONS", "").strip()
if opt:
    try:
        extra = json.loads(opt)
        if not isinstance(extra, dict):
            raise ValueError("options 必须是 JSON 对象")
        body.update(extra)
    except Exception as e:
        import sys
        print(f"[serverchan] options 不是合法 JSON 对象: {e}", file=sys.stderr)
        sys.exit(2)
print(json.dumps(body, ensure_ascii=False))
PY
)" || exit $?
else
  # 无 python3 的降级路径：仅支持 title/desp，不支持 options。
  if [ -n "$OPTIONS" ]; then
    echo "[serverchan] 当前环境无 python3，无法安全拼装 options，请仅传 title/desp。" >&2
    exit 2
  fi
  esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
  BODY="{\"title\":\"$(esc "$TITLE")\",\"desp\":\"$(esc "$DESP")\"}"
fi

out="$(curl -sS -X POST \
  -H 'Content-Type: application/json;charset=utf-8' \
  -d "$BODY" \
  -w '\n%{http_code}' \
  "$URL")"
code="${out##*$'\n'}"
body="${out%$'\n'*}"
printf '%s\n' "$body"

# 业务成功判定：HTTP 2xx 且响应 JSON 的 code==0
biz_ok=0
if command -v python3 >/dev/null 2>&1; then
  biz_ok="$(printf '%s' "$body" | python3 -c 'import sys,json
try:
  print(1 if json.load(sys.stdin).get("code")==0 else 0)
except Exception:
  print(0)' 2>/dev/null || echo 0)"
else
  case "$body" in *'"code":0'*) biz_ok=1 ;; *) biz_ok=0 ;; esac
fi

case "$code" in
  2*) [ "$biz_ok" = "1" ] && exit 0 || { echo "[serverchan] 推送被服务端拒绝(code!=0)。" >&2; exit 1; } ;;
  *)  echo "[serverchan] HTTP $code，推送失败。" >&2; exit 1 ;;
esac
