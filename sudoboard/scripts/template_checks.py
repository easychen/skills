#!/usr/bin/env python3
# SudoBoard Skill · template_checks.py — 模板契约共享校验
#
# 三件事（供 build_preview.py / sync.py / deploy_cf.py 复用，避免各写一份）：
#   1) 深浅色判定：显式声明 `/* sb-theme: dark|light */` > 旧的颜色启发式 > 兜底主题；
#   2) static_checks()：阻断项（编译/同步必须拒绝）；
#   3) style_warnings()：观感警告（不阻断，但会「上机变丑」）。
#
# ⚠ 契约必须与 App 侧 web/src/lib/boardTone.ts 保持一致（同一个正则、同一优先级）。
import re

# 显式声明：/* sb-theme: dark */、// sb-theme: light、SB-THEME:DARK 均可
THEME_DECL_RE = re.compile(r"sb-theme\s*:\s*(dark|light)", re.I)
# 颜色启发式（保留兼容未声明主题的历史模板；新模板请显式声明 sb-theme）
# 只认「像浅色底」的颜色：
#   - rgb(a) 白且 alpha≥0.5（浅色卡片底；深色描边 rgba(255,255,255,0.08) 不算）
#   - #f 开头且三个通道都 ≥0xE0 的 6 位 hex（#ffffff/#f5f6f8/#fafafa/#f0f0f0）
# 刻意不匹配： #f87171（红）/#F6E500（黄）——曾把 7/8 个内置深色模板误判成浅色；
#              #e8eaf0 / #e5e7eb 等「近白文字色」——深色模板最常见的写法，不能当浅色底。
# ⚠ 与 App 侧 web/src/lib/boardTone.ts 必须逐字一致。
LIGHT_HINT_PATTERN = (
    r"rgba?\(\s*255\s*,\s*255\s*,\s*255\s*(?:,\s*(?:0?\.(?:[5-9]\d*)|1(?:\.0+)?)\s*)?\)"
    r"|#f[0-9a-f](?:[ef][0-9a-f]){2}\b"
    r"|#fff\b"
)
LIGHT_HINT_RE = re.compile(LIGHT_HINT_PATTERN, re.I)

MAX_TEMPLATE_BYTES = 200 * 1024


def declared_theme(source):
    """返回模板显式声明的 'dark'/'light'；未声明返回 None。"""
    if not source:
        return None
    m = THEME_DECL_RE.search(source)
    return m.group(1).lower() if m else None


def heuristic_theme(source):
    """旧的颜色启发式判定（无声明时的兜底）。"""
    return "light" if source and LIGHT_HINT_RE.search(source) else "dark"


def resolve_theme(source, fallback="dark"):
    """返回 (tone, from)：from ∈ {'declared','heuristic','fallback'}。"""
    declared = declared_theme(source)
    if declared:
        return declared, "declared"
    if source:
        return heuristic_theme(source), "heuristic"
    return ("light" if fallback == "light" else "dark"), "fallback"


def static_checks(source):
    """阻断项：返回违规说明列表（空 = 通过）。"""
    bad = []
    if "export default" not in source:
        bad.append("缺少 export default（模板必须 export default function Screen）")
    if re.search(r"\bimport\s", source):
        bad.append("模板不允许 import")
    if re.search(r"\brequire\(", source):
        bad.append("模板不允许 require()")
    if re.search(r"\bfetch\(", source):
        bad.append("模板不允许 fetch()（模板零网络）")
    if "XMLHttpRequest" in source:
        bad.append("模板不允许 XMLHttpRequest")
    if len(source.encode("utf-8")) > MAX_TEMPLATE_BYTES:
        bad.append("模板超过 200KB")
    return bad


def style_warnings(source, board_theme=None):
    """观感警告：返回提示列表（不阻断）。board_theme 为 board.json 的 board.theme。"""
    warns = []
    tone, origin = resolve_theme(source, board_theme or "dark")

    if board_theme and tone != board_theme:
        warns.append(
            f"模板深浅色判定为 {tone}，但 board.theme={board_theme}："
            f"播放页遮罩会与看板主题相反。请显式声明 /* sb-theme: {board_theme} */，"
            f"或把颜色改成与 {board_theme} 一致")
    elif board_theme and origin == "heuristic":
        warns.append(
            f"模板未显式声明主题，靠颜色启发式判为 {tone}（含 #f 开头 hex / rgba(255 极易误判）；"
            f"建议首行加 /* sb-theme: {tone} */")

    if re.search(r"border[\s-]?radius", source, re.I):
        warns.append("模板不应使用圆角（border-radius）：播放页规范为直角卡片")
    if re.search(r"className\s*=", source):
        warns.append("模板不要用 Tailwind class（className 会被播放页丢弃）")
    return warns


if __name__ == "__main__":  # pragma: no cover - 手工自检
    import sys
    src = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else ""
    for w in style_warnings(src):
        print(f"⚠ {w}")
