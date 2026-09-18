#!/usr/bin/env python3
# SudoBoard Skill · build_preview.py — 生成本地高保真预览页
#
# 与 App /play 同一条渲染路径：
#   Babel(classic runtime) 编译模板 + 全局 React/echarts/Masonry
#   + 播放页外层观感（壁纸层 / 深浅遮罩 / 标题栏 / 溢出横向滚动）
# 因此「预览通过 ≈ 上机可用」。
#
# 用法:
#   python3 build_preview.py [--dir <sudoboard工程目录>] [--open]
#
# 数据优先级: preview/data.json（sync.py snapshot 产出的真实快照）
#            > board.json 的 template.demoData
import argparse
import json
import os
import re
import subprocess
import sys

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import board_model as bm  # noqa: E402
import template_checks as tc  # noqa: E402

# 预览页依赖（与 App 打包版本对齐：React 19.2.8 / echarts 6 / masonry 4 / Babel 8）
# ⚠ React 19 起官方不再发布 UMD 构建 → react/react-dom 走 ESM（esm.sh / jsdelivr +esm）。
CDN_PACKAGES = [
    ("react", "react@19.2.8"),
    ("react-dom", "react-dom@19.2.8/client"),
    ("babel", "@babel/standalone/babel.min.js"),
    ("echarts", "echarts@6/dist/echarts.min.js"),
    ("masonry", "masonry-layout@4/dist/masonry.pkgd.min.js"),
]
ESM_PACKAGES = {"react", "react-dom"}

# 与 App web/src/lib/boardTone.ts / template_checks.py 同一契约
static_checks = tc.static_checks
style_warnings = tc.style_warnings
LIGHT_RE = tc.LIGHT_HINT_RE


class PreviewError(Exception):
    pass


def run_local_engine(root: str) -> None:
    """运行 engine.js（Node 版本地数据引擎）抓取真实数据 → preview/data.json。"""
    import subprocess
    engine = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine.js")
    if not os.path.isfile(engine):
        print("⚠ 找不到 engine.js，跳过本地抓取")
        return
    try:
        r = subprocess.run(["node", engine, "--dir", root],
                           capture_output=True, text=True, timeout=180)
        if r.stdout:
            print(r.stdout.rstrip())
        if r.returncode != 0:
            if r.stderr:
                print(r.stderr.rstrip(), file=sys.stderr)
            print("⚠ 本地抓取未完全成功，预览将继续使用已有数据")
    except FileNotFoundError:
        print("⚠ 未安装 Node.js（>=18），无法本地抓取；DB 源或无 Node 时可用 sync.py snapshot 从设备拉取")
    except subprocess.TimeoutExpired:
        print("⚠ 本地抓取超时（180s），预览将继续使用已有数据")


def js_embed(obj) -> str:
    """把 Python 对象安全嵌入 <script>（防 </script> 提前闭合）。"""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def render_page_html(board_name, source, data, theme, is_light, bg, cdns, live=None):
    """按播放页 HTML_TEMPLATE 渲染完整页面。

    board_name  看板名（标题栏）
    source      JSX 模板源码
    data        {values, meta}（preview 模式内嵌；live 模式仅作首帧占位）
    theme       dark|light（board.theme）
    is_light    浅色启发式判定结果（决定初始遮罩色调）
    bg          {src, dark, light, opacity, blur}（src 为空 = 无壁纸）
    cdns        CDN 包列表 [(name, path)]
    live        为 None = 预览模式（用内嵌数据）；为 dict {url, intervalMs} =
                Cloudflare 部署模式（轮询 url，隐藏调试工具栏）
    """
    bg_src = bg.get("src") or ""
    html = HTML_TEMPLATE
    html = html.replace("__TITLE__", f"SB Preview · {board_name}")
    html = html.replace("__BOARD_NAME__", js_embed(board_name))
    html = html.replace("__TEMPLATE__", js_embed(source))
    html = html.replace("__DATA__", js_embed(data))
    html = html.replace("__THEME__", js_embed(theme))
    html = html.replace("__IS_LIGHT__", "true" if is_light else "false")
    html = html.replace("__LIVE__", js_embed(live))
    html = html.replace("__BG_SRC__", js_embed(bg_src))
    html = html.replace("__BG_DARK__", js_embed(bg.get("dark") or bg_src))
    html = html.replace("__BG_LIGHT__", js_embed(bg.get("light") or bg_src))
    html = html.replace("__BG_OPACITY__", str(bg.get("opacity", 1.0)))
    html = html.replace("__BG_BLUR__", str(bg.get("blur", 0)))
    html = html.replace("__CDNS__", js_embed(cdns))
    return html


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 SudoBoard 本地预览页")
    ap.add_argument("--dir", default="./sudoboard", help="sudoboard 工程目录")
    ap.add_argument("--open", action="store_true", help="生成后打开浏览器")
    ap.add_argument("--fetch", action="store_true",
                    help="先运行本地数据引擎 engine.js：按 board.json 的源配置真实抓取 + JSONATA 抽取")
    args = ap.parse_args()
    try:
        info = build(args.dir, fetch=args.fetch, open_browser=args.open)
    except PreviewError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    return 0 if info else 1


def build(root, fetch=False, open_browser=False):
    """生成预览页并返回信息字典（供测试与 main 复用）。

    返回 {"out","tone","origin","warnings","data_source","board_name","theme"}
    """
    root = os.path.abspath(root)

    if fetch:
        run_local_engine(root)

    board_path = os.path.join(root, "board.json")
    if not os.path.isfile(board_path):
        raise PreviewError(f"找不到 {board_path}（先在工程里创建 board.json）")
    with open(board_path, encoding="utf-8") as f:
        board = json.load(f)

    tpl = bm.primary_template(board) or {}
    tpl_rel = tpl.get("file") or "templates/main.jsx"
    tpl_path = os.path.join(root, tpl_rel)
    if not os.path.isfile(tpl_path):
        raise PreviewError(f"找不到模板文件 {tpl_path}")
    with open(tpl_path, encoding="utf-8") as f:
        source = f.read()

    theme = (board.get("board") or {}).get("theme", "dark")

    # 数据：真实快照 > demoData
    data_path = os.path.join(root, "preview", "data.json")
    if os.path.isfile(data_path):
        with open(data_path, encoding="utf-8") as f:
            data = json.load(f)
        data_src = "live snapshot (preview/data.json)"
    else:
        data = tpl.get("demoData") or {}
        data_src = "demoData (board.json)"
    data.setdefault("values", {})
    meta = data.setdefault("meta", {})
    meta.setdefault("updatedAt", data.get("updatedAt") or "2026-01-01T00:00:00Z")
    meta.setdefault("sourceStatus", {})
    meta.setdefault("theme", theme)

    # 违规/观感警告（不阻断预览——预览正是发现问题的地方）
    warnings = []
    for v in static_checks(source):
        warnings.append(v)
        print(f"⚠ 模板静态检查: {v}")
    for w in style_warnings(source, theme):
        warnings.append(w)
        print(f"⚠ 模板观感: {w}")

    # 深浅色：显式声明 > 颜色启发式 > board.theme
    tone, origin = tc.resolve_theme(source, theme)
    is_light = tone == "light"

    # 背景图层（相对 preview/ 的路径）；assets 里有 dark/light 对应图时，预览切换会联动替换
    bg = (bm.primary_dashboard(board) or {}).get("background") or {}
    bg_current, bg_dark, bg_light = "", "", ""
    bg_opacity, bg_blur = 1.0, 0
    if bg.get("file"):
        bg_abs = os.path.join(root, bg["file"])
        if os.path.isfile(bg_abs):
            bg_current = os.path.relpath(bg_abs, os.path.join(root, "preview"))
            bg_opacity = float(bg.get("opacity", 1.0))
            bg_blur = float(bg.get("blur", 0))
            name = os.path.basename(bg["file"])
            swaps = [("dark", "light"), ("light", "dark"), ("black", "white"), ("white", "black")]
            counterpart = ""
            for a, b in swaps:
                if re.search(a, name, re.I):
                    cand = os.path.join(os.path.dirname(bg_abs), re.sub(a, b, name, flags=re.I))
                    if os.path.isfile(cand):
                        counterpart = os.path.relpath(cand, os.path.join(root, "preview"))
                    break
            if re.search(r"dark|black", name, re.I):
                bg_dark, bg_light = bg_current, (counterpart or bg_current)
            elif re.search(r"light|white", name, re.I):
                bg_dark, bg_light = (counterpart or bg_current), bg_current
            else:
                bg_dark = bg_light = bg_current
            if counterpart:
                print("  壁纸联动    : 检测到 dark/light 对应图，预览切换时自动替换")
        else:
            print(f"⚠ 背景文件不存在: {bg_abs}（预览将用纯色底）")

    board_name = bm.board_display_name(board)

    out_dir = os.path.join(root, "preview")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "index.html")

    html = render_page_html(
        board_name, source, data, theme, is_light,
        {"src": bg_current, "dark": bg_dark, "light": bg_light,
         "opacity": bg_opacity, "blur": bg_blur},
        CDN_PACKAGES, live=None)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✓ 预览已生成: {out_path}")
    print(f"  数据来源   : {data_src}")
    print(f"  模板深浅判定: {'浅色(白遮罩)' if is_light else '深色(黑遮罩)'}"
          f"  board.theme={theme}  依据={origin}")
    if not data_src.startswith("live"):
        print("  提示: 当前为演示数据；要预览真实数据可先运行 sync.py snapshot")
    if open_browser:
        for opener in ("open", "xdg-open"):
            try:
                subprocess.run([opener, out_path], check=False)
                break
            except FileNotFoundError:
                continue
    return {"out": out_path, "tone": tone, "origin": origin, "warnings": warnings,
            "data_source": data_src, "board_name": board_name, "theme": theme}


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  html, body { margin: 0; padding: 0; height: 100%; overflow: hidden; background: #000; }
  #bg { position: absolute; inset: 0; }
  #bg img { width: 100%; height: 100%; object-fit: cover; }
  #mask { position: absolute; inset: 0; }
  #titlebar {
    position: absolute; top: 0; left: 0; right: 0; z-index: 20;
    display: flex; flex-direction: column; align-items: center;
    padding: 16px 16px 0; text-align: center; pointer-events: none;
    font-family: system-ui, -apple-system, sans-serif;
    font-size: 20px; font-weight: 600; color: #fff;
    line-height: 1.25; text-shadow: 0 1px 4px rgba(0,0,0,0.75);
  }
  #titlebar sup { font-size: 20px; font-weight: 600; color: rgba(255,255,255,0.9); }
  /* SmartStage 舞台：横向溢出时无缝循环（与 App SmartStage.tsx 一致） */
  #stage-wrap {
    position: absolute; inset: 0; overflow-y: auto;
    overscroll-behavior: contain; scrollbar-width: none;
  }
  #stage-wrap::-webkit-scrollbar { display: none; }
  #stage-content { height: 100%; }
  #stage-content.h-loop { display: flex; width: max-content; }
  #stage-copy { display: none; }
  #stage-content.h-loop #stage-copy { display: block; flex: 0 0 auto; }
  #stage { width: 100%; height: 100%; }
  #toolbar {
    position: absolute; right: 12px; bottom: 12px; z-index: 30;
    display: flex; gap: 6px; font-family: system-ui, sans-serif;
  }
  #toolbar button {
    border: 1px solid rgba(255,255,255,0.25); background: rgba(0,0,0,0.4);
    color: rgba(255,255,255,0.85); border-radius: 6px; padding: 4px 10px;
    font-size: 12px; cursor: pointer; backdrop-filter: blur(4px);
  }
  #toolbar button.on { background: rgba(255,255,255,0.2); }
  #banner {
    position: absolute; inset: 0; z-index: 40; display: flex;
    align-items: center; justify-content: center; padding: 24px;
    background: #15181F; color: #fca5a5; font: 14px/1.7 ui-monospace, monospace;
    white-space: pre-wrap; text-align: center;
  }
  /* display:flex 会覆盖 hidden 属性的 UA display:none，必须显式声明 */
  #banner[hidden] { display: none; }
</style>
</head>
<body>
<div id="bg"><img id="bg-img" alt=""></div>
<div id="mask"></div>
<div id="titlebar"></div>
<div id="stage-wrap">
  <div id="stage-content">
    <div id="stage"></div>
    <div id="stage-copy" aria-hidden="true"></div>
  </div>
</div>
<div id="toolbar">
  <button id="btn-dark">dark</button>
  <button id="btn-light">light</button>
  <button id="btn-reload" title="重新编译模板">↻</button>
</div>
<div id="banner" hidden></div>
<script>
window.__SB = {
  boardName: __BOARD_NAME__,
  template: __TEMPLATE__,
  data: __DATA__,
  theme: __THEME__,
  isLight: __IS_LIGHT__,
  live: __LIVE__,
  bg: { src: __BG_SRC__, dark: __BG_DARK__, light: __BG_LIGHT__, opacity: __BG_OPACITY__, blur: __BG_BLUR__ },
  cdns: __CDNS__,
};
</script>
<script>
(function () {
  'use strict';
  var SB = window.__SB;
  var banner = document.getElementById('banner');
  function fail(msg) { banner.hidden = false; banner.textContent = msg; }
  function clearFail() { banner.hidden = true; }

  /* ---- 依赖加载：react/react-dom 走 ESM（React 19 起官方不再发布 UMD），其余经典脚本 ----
     按序 await：react-dom 依赖 React 全局。失败自动换 CDN。 */
  var ESM_PKGS = { 'react': 1, 'react-dom': 1 };
  function loadClassic(pkg) {
    return new Promise(function (resolve, reject) {
      var hosts = ['https://unpkg.com/', 'https://cdn.jsdelivr.net/npm/'];
      var i = 0;
      (function tryNext() {
        if (i >= hosts.length) { reject(new Error(pkg[0] + '（所有 CDN 均失败，请检查网络）')); return; }
        var s = document.createElement('script');
        s.src = hosts[i] + pkg[1];
        s.onload = function () { resolve(); };
        s.onerror = function () { s.remove(); i++; tryNext(); };
        document.head.appendChild(s);
      })();
    });
  }
  function loadEsm(pkg) {
    var spec = pkg[1];
    var urls = ['https://esm.sh/' + spec, 'https://cdn.jsdelivr.net/npm/' + spec + '/+esm'];
    return new Promise(function (resolve, reject) {
      var i = 0;
      (function tryNext() {
        if (i >= urls.length) { reject(new Error(pkg[0] + '（所有 CDN 均失败，请检查网络）')); return; }
        import(urls[i]).then(function (mod) {
          if (pkg[0] === 'react') { window.React = mod.default || mod; }
          else { window.ReactDOM = mod; }
          resolve();
        }, function () { i++; tryNext(); });
      })();
    });
  }
  function loadPkg(pkg) { return ESM_PKGS[pkg[0]] ? loadEsm(pkg) : loadClassic(pkg); }
  var loadAll = SB.cdns.reduce(function (p, pkg) {
    return p.then(function () { return loadPkg(pkg); });
  }, Promise.resolve());
  loadAll.then(boot, function (e) {
    fail('预览依赖 CDN 加载失败: ' + e.message + '\n（仅影响本地预览；App 端内置这些库不受影响）');
  });

  /* ---- 渲染期错误兜底：模板组件抛错时显示 banner，而不是白屏（App 侧同款边界） ---- */
  function makeBoundary() {
    if (window.__SB_BOUNDARY) return window.__SB_BOUNDARY;
    var R = window.React;
    class SBErrorBoundary extends R.Component {
      constructor(props) { super(props); this.state = { error: null }; }
      static getDerivedStateFromError(error) { return { error: error }; }
      componentDidCatch(error, info) {
        console.error('[sudoboard] 模板渲染错误', error, info);
        if (this.props && this.props.onError) this.props.onError(error);
      }
      render() {
        if (this.state.error) return null;  // 错误信息交给 banner 呈现
        return this.props.children;
      }
    }
    window.__SB_BOUNDARY = SBErrorBoundary;
    return SBErrorBoundary;
  }

  /* ---- 与 App TemplateView.compileTemplate 完全一致的编译路径 ---- */
  function compileTemplate(source) {
    var code = Babel.transform(source, { presets: [['react', { runtime: 'classic' }]] }).code;
    var moduleCode = code.replace(/\bexport\s+default\b/, 'module.exports =');
    var factory = new Function('React', 'echarts', 'Masonry', 'module', 'require',
      moduleCode +
      '\nreturn module.exports && module.exports.__esModule ? module.exports.default : module.exports;');
    var module = { exports: {} };
    factory(React, echarts, Masonry, module, function () { throw new Error('模板不允许 import'); });
    var resolved = typeof module.exports === 'function' ? module.exports : module.exports.default;
    if (typeof resolved !== 'function') throw new Error('模板必须导出组件（export default function Screen）');
    return resolved;
  }

  /* ---- 播放页观感 ---- */
  function applyChrome(tone) {
    var bgImg = document.getElementById('bg-img');
    if (SB.bg.src) {
      bgImg.src = tone === 'light' ? (SB.bg.light || SB.bg.src) : (SB.bg.dark || SB.bg.src);
      bgImg.style.opacity = SB.bg.opacity;
      bgImg.style.filter = SB.bg.blur > 0 ? 'blur(' + SB.bg.blur + 'px)' : '';
    } else {
      document.body.style.background = tone === 'light' ? '#e9eaec' : '#0b0e13';
    }
    // 遮罩色调跟随 tone（初始值来自模板启发式，与 App 判定一致；按钮可手动预览另一种）
    document.getElementById('mask').style.background = tone === 'light' ? 'rgba(255,255,255,0.35)' : 'rgba(0,0,0,0.45)';
    var t = new Date(SB.data && SB.data.meta && SB.data.meta.updatedAt || Date.now());
    var hh = ('0' + t.getHours()).slice(-2), mm = ('0' + t.getMinutes()).slice(-2);
    var bar = document.getElementById('titlebar');
    bar.innerHTML = '';
    var line = document.createElement('div');
    line.style.whiteSpace = 'nowrap';
    line.appendChild(document.createTextNode(SB.boardName));
    var sup = document.createElement('span');
    sup.textContent = ' · ' + hh + ':' + mm;
    line.appendChild(sup);
    bar.appendChild(line);
  }

  /* ---- SmartStage：按 App SmartStage.tsx 现行实现移植 ----
    横向溢出 → 无缝循环（内容克隆两份，只向前滚，滚过一份宽即回绕，永不反向/空屏）；
    纵向溢出 → 下行 → 到底停留 2.5s → 上行 → 循环；
    交互（拖拽/滚轮/触摸）暂停 10s；prefers-reduced-motion 禁用自动滚动。 */
  var autoState = null;   // { el, axis, loop, speed, phase, dwellNext, dwellUntil, pausedUntil }
  var sbRoot = null, sbCopyRoot = null;

  function stopAutoScroll() { autoState = null; }

  function autoTick(dtMs, nowMs) {
    var s = autoState;
    if (!s || nowMs < s.pausedUntil) return;
    var el = s.el;
    var pos = s.axis === 'horizontal' ? el.scrollLeft : el.scrollTop;
    var max = s.axis === 'horizontal'
      ? Math.max(0, el.scrollWidth - el.clientWidth)
      : Math.max(0, el.scrollHeight - el.clientHeight);
    if (max <= 0) return;
    if (s.loop && s.axis === 'horizontal') {
      var oneCopy = el.scrollWidth / 2;  // 一份内容宽（总共两份）
      pos = pos + (s.speed * dtMs) / 1000;
      if (oneCopy > 0) pos = pos % oneCopy;  // 回绕到 [0, 一份宽)：视觉无缝
      el.scrollLeft = pos;
      return;
    }
    if (s.phase === 'down') {
      pos = Math.min(max, pos + (s.speed * dtMs) / 1000);
      el.scrollTop = pos;
      if (pos >= max) { s.phase = 'dwell'; s.dwellNext = 'up'; s.dwellUntil = nowMs + 2500; }
    } else if (s.phase === 'up') {
      pos = Math.max(0, pos - (s.speed * dtMs) / 1000);
      el.scrollTop = pos;
      if (pos <= 0) { s.phase = 'dwell'; s.dwellNext = 'down'; s.dwellUntil = nowMs + 2500; }
    } else { // dwell：端点停留后反向
      if (nowMs >= s.dwellUntil) { s.phase = s.dwellNext; autoTick(dtMs, nowMs); }
    }
  }

  function reducedMotion() {
    return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  function measureOverflow(el) {
    return {
      h: el.scrollWidth > el.clientWidth + 4,
      v: el.scrollHeight > el.clientHeight + 4,
    };
  }

  function setupScroll(Component, data) {
    var wrap = document.getElementById('stage-wrap');
    var content = document.getElementById('stage-content');
    var copyWrap = document.getElementById('stage-copy');
    var ov = measureOverflow(wrap);
    if (!ov.h && !ov.v) return;
    if (ov.h) {
      // 无缝循环：克隆一份相同内容跟在后面（两份相同 → 回绕视觉无缝）
      content.classList.add('h-loop');
      sbCopyRoot = ReactDOM.createRoot(copyWrap);
      var SBErrorBoundary = makeBoundary();
      sbCopyRoot.render(React.createElement(SBErrorBoundary, null,
        React.createElement(Component, { data: data })));
      requestAnimationFrame(function () {
        startAutoScroll(wrap);
      });
    } else {
      startAutoScroll(wrap);
    }
  }

  function startAutoScroll(el) {
    var ov = measureOverflow(el);
    if (!ov.h && !ov.v) return;
    if (reducedMotion()) return;
    var axis = ov.h ? 'horizontal' : 'vertical';
    autoState = {
      el: el,
      axis: axis,
      loop: axis === 'horizontal',
      speed: axis === 'horizontal' ? 36 : 24,  // 横向无缝滚动稍快（对齐 App）
      phase: 'down', dwellNext: 'up', dwellUntil: 0, pausedUntil: 0,
    };
  }

  // 自动滚动主循环：活动时走 rAF；空闲/暂停时退化为低频 setTimeout（不占用渲染帧）
  var lastT = null;
  function autoLoop(t) {
    if (autoState && !window.__SB_PAUSED) {
      if (lastT == null) lastT = t;
      var dt = Math.min(100, t - lastT);
      lastT = t;
      autoTick(dt, t);
      requestAnimationFrame(autoLoop);
    } else {
      lastT = null;
      setTimeout(autoLoop, 250);
    }
  }
  requestAnimationFrame(autoLoop);

  // 人工优先：拖拽/滚轮/触摸暂停自动滚动 10s；鼠标可拖拽滚动（与 App 一致）
  (function bindInteractions() {
    var wrap = document.getElementById('stage-wrap');
    var drag = null;
    function pause() { if (autoState) autoState.pausedUntil = performance.now() + 10000; }
    wrap.addEventListener('pointerdown', function (e) {
      pause();
      if (e.pointerType === 'mouse') {
        drag = { x: e.clientX, y: e.clientY, left: wrap.scrollLeft, top: wrap.scrollTop };
        if (wrap.setPointerCapture) wrap.setPointerCapture(e.pointerId);
      }
    });
    wrap.addEventListener('pointermove', function (e) {
      if (!drag || e.pointerType !== 'mouse') return;
      wrap.scrollLeft = drag.left - (e.clientX - drag.x);
      wrap.scrollTop = drag.top - (e.clientY - drag.y);
    });
    wrap.addEventListener('pointerup', function () { drag = null; });
    wrap.addEventListener('pointerleave', function () { drag = null; });
    wrap.addEventListener('wheel', pause, { passive: true });
    wrap.addEventListener('touchstart', pause, { passive: true });
  })();

  function render() {
    clearFail();
    var data = JSON.parse(JSON.stringify(SB.data));
    data.meta.theme = SB.tone;
    try {
      var Component = compileTemplate(SB.template);
      var wrap = document.getElementById('stage-wrap');
      var content = document.getElementById('stage-content');
      var stage = document.getElementById('stage');
      var copyWrap = document.getElementById('stage-copy');
      if (sbRoot) { sbRoot.unmount(); sbRoot = null; }  // 先卸载旧组件（副作用正确清理），再清容器
      if (sbCopyRoot) { sbCopyRoot.unmount(); sbCopyRoot = null; }
      stopAutoScroll();
      content.classList.remove('h-loop');
      copyWrap.innerHTML = '';
      stage.innerHTML = '';
      wrap.scrollLeft = 0; wrap.scrollTop = 0;
      var SBErrorBoundary = makeBoundary();
      sbRoot = ReactDOM.createRoot(stage);
      sbRoot.render(React.createElement(SBErrorBoundary, {
        onError: function (err) {
          fail('模板渲染失败（App 端也会显示同样的兜底错误视图）:\n' + (err && err.message || err));
        }
      }, React.createElement(Component, { data: data })));
      requestAnimationFrame(function () { requestAnimationFrame(function () { setupScroll(Component, data); }); });
    } catch (e) {
      fail('模板渲染失败（App 端也会显示同样的兜底错误视图）:\n' + (e && e.message || e));
    }
  }

  function boot() {
    // tone = 遮罩色调 + meta.theme 的联合开关；初始值：浅色模板启发式优先，其次 board.theme
    SB.tone = SB.isLight || SB.theme === 'light' ? 'light' : 'dark';
    if (!SB.data || !SB.data.values || !SB.data.meta) {
      // 深度缺省（live 模式首帧）：保证模板每次都拿到完整契约
      SB.data = { values: {}, meta: { updatedAt: new Date().toISOString(), sourceStatus: {}, theme: SB.tone } };
    }
    applyChrome(SB.tone);
    var bd = document.getElementById('btn-dark'), bl = document.getElementById('btn-light');
    function setTone(tone) {
      SB.tone = tone;
      SB.theme = tone;
      bd.className = tone === 'dark' ? 'on' : '';
      bl.className = tone === 'light' ? 'on' : '';
      applyChrome(tone);
      render();
    }
    bd.onclick = function () { setTone('dark'); };
    bl.onclick = function () { setTone('light'); };
    document.getElementById('btn-reload').onclick = render;
    bd.className = SB.tone === 'dark' ? 'on' : '';
    bl.className = SB.tone === 'light' ? 'on' : '';

    if (SB.live) {
      // Cloudflare 部署模式：轮询 /api/data 拉最新快照，隐藏调试工具栏
      document.getElementById('toolbar').style.display = 'none';
      function tick() {
        fetch(SB.live.url, { cache: 'no-store' })
          .then(function (r) { return r.json(); })
          .then(function (j) {
            if (j && j.ok && j.data) {
              SB.data = j.data;
              if (!SB.data.meta) SB.data.meta = {};
              SB.data.meta.theme = SB.tone;
              applyChrome(SB.tone);
              render();
            }
          })
          .catch(function () { /* 单次失败保持上一帧，下个周期重试 */ });
      }
      tick();
      setInterval(tick, SB.live.intervalMs || 60000);
    } else {
      render();
    }
  }
})();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main())
