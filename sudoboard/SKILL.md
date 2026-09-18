---
name: sudoboard
description: 为当前项目创建 SudoBoard 数据看板（可视化数据面板/电视大屏）：帮用户配置数据源、编写页面展示模板（JSX）、在本地生成高保真 HTML 预览并打开浏览器迭代，确认后一键部署——同步到 SudoBoard App（局域网设备）或直接部署到 Cloudflare（带后端、无需任何 App）。当用户想为项目做可视化面板、数据大屏、电视看板，或提到 sudoboard、sudb、SudoBoard 时使用本技能。配置全部在 Agent 环境完成，App 端只管运行（如用 App），Cloudflare 部署则连 App 都不需要。
tags: [sudoboard, dashboard, visualization, data, bigscreen, cloudflare]
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
env_vars:
  - key: SUDOBOARD_URL
    required: false
    desc: SudoBoard 设备地址（含端口），如 http://192.168.1.23:8866。缺省 http://127.0.0.1:8866（App 与 Agent 同机时）。
  - key: SUDOBOARD_ADMIN_PIN
    required: false
    desc: SudoBoard App 管理员 PIN（首次启动引导时设置）。缺省时向用户询问。
---

# SudoBoard 看板配置技能（sudoboard / sudb）

把「为项目建一个可视化数据看板」变成纯 Agent 对话流程：**数据源 → 配置文件 → JSX 模板 → 本地 HTML 预览 → 一键部署**。
部署目标二选一（或都用）：

- **Cloudflare Workers（默认推荐，完全无需 App）**：整块看板（数据引擎 + 播放页 + 资产 + cron 定时抓取）直接上线到公网，电视/浏览器打开 URL 即看；
- **SudoBoard App（局域网电视/旧手机设备）**：同步完成后设备屏幕 ≤1s 自动更新（SSE playStamp），全程不需要登录 App 管理页。

> 下文 `<skill>` 指本 SKILL.md 所在目录；`<proj>` 指用户**当前项目**根目录；工程目录指 `<proj>/sudoboard/`。
> 本技能未安装到助手技能目录时，先跑 `bash <skill>/scripts/install-skill.sh`（可选 `--host dsh`、`--dir <目录>`、`--copy`）。
> 附录已拆到 `references/`：接口速查 `references/api.md`、排错 `references/faq.md`（需要时再读）。

```
阶段0 连接  →  阶段1 盘点/数据源  →  阶段2 生成工程  →  阶段3 模板  →  阶段4 本地预览(迭代)
  →  阶段5 部署：5A Cloudflare（无需 App）/ 5B 同步到 App（可选）  →  阶段6 打包分发（App 专用）
```

**任选部署目标**：
- **5A · Cloudflare Workers（默认）**：`deploy_cf.py` 一键上线，无 App 参与——见「阶段 5A」；
- **5B · 同步到 App（可选）**：已有 SudoBoard 设备时，`sync.py` 幂等同步——见「阶段 5B」。

---

## 阶段 0：连接与登录

```bash
SB_URL="${SUDOBOARD_URL:-http://127.0.0.1:8866}"
# 1) 探测（公开接口，无需登录）
curl -s --max-time 4 "$SB_URL/api/status"
```

- 成功：记下 `theme`、`sources`、`httpBind`（`lan`=可远程访问 / `loopback`=仅本机）。
- 失败（连不上）：按序排查——
  1. App 是否已启动并在运行（屏幕应有看板或引导页）；
  2. Agent 与 App 是否同机？不同机时 App 默认只绑 `127.0.0.1`，需要用户在 App 上：**菜单 → 进入管理 → 设备信息 → 局域网访问** 打开开关，然后 `SB_URL` 用设备 IP（设备信息页会显示本机 IP）；
  3. 手机与电脑是否同一局域网、端口是否 8866。

```bash
# 2) 管理员登录（PIN 来自 $SUDOBOARD_ADMIN_PIN，或询问用户；App 引导页/设备信息页可见）
SB_COOKIES="$(mktemp)"
curl -s -c "$SB_COOKIES" -X POST "$SB_URL/api/auth/admin-login" \
  -H 'content-type: application/json' -d "{\"pin\":\"$SUDOBOARD_ADMIN_PIN\"}"
```

- 返回 `{"ok":true,...}` 即登录成功，后续所有请求带 `-b "$SB_COOKIES"`。
- 401 = PIN 错误；任何后续接口返回 401 = 会话过期（30 分钟），重新执行本条即可。
- 若用户也提供不了 PIN：让用户在 App 菜单 → 进入管理 的登录页查看（或首次引导时设置过）。

## 阶段 1：盘点已有资源 + 配置数据源

```bash
curl -s -b "$SB_COOKIES" "$SB_URL/api/datasources"   # 已有数据源
curl -s -b "$SB_COOKIES" "$SB_URL/api/templates"     # 已有模板
curl -s -b "$SB_COOKIES" "$SB_URL/api/dashboards"    # 已有看板
curl -s -b "$SB_COOKIES" "$SB_URL/api/playback-groups"  # 已有轮播方案
```

**先盘点再创建**，避免重复；用户已建过同名资源时优先复用（把 App 侧 id 填进 board.json 的 `appId` 字段）。

与用户确认要展示什么数据后，配置数据源。两类：

**HTTP 源**（API 抓取，一源多值是第一等公民）：

```jsonc
POST /api/datasources
{
  "name": "DeepSeek 余额",
  "type": "http",
  "intervalSeconds": 300,          // 抓取间隔（>=1）
  "enabled": true,
  "fetch": {
    "url": "https://api.deepseek.com/user/balance",
    "method": "GET",
    "headers": { "Authorization": "Bearer sk-xxx" },
    "timeoutSeconds": 10
  },
  "extractors": [                  // JSONATA：把原始 JSON 抽成「命名值」
    { "name": "balance", "jsonata": "balance_infos.total_balance" }
  ]
}
```

**数据库源**（默认只读）：`type: "db"`，`fetch` 换成 `db: { kind: "mysql"|"postgresql"|"sqlite", host, port, database, username, password, readOnly: true }` + `queries: [{ name, sql }]`（SQL 只读拦截默认开启）。`db.password` 只写不回读。

要点：
- 一个 URL 拆多个指标 = 多条 `extractors`（引擎一次抓取、多次抽取）。
- JSONATA 支持 `$number()`、`$round()` 等计算式；可先验证：
  `POST /api/datasources/jsonata-test {"expression":"...","sample":{...}}`。
- 创建/更新后**立即抓取验证**：`POST /api/datasources/:id/fetch`，再 `GET /api/data/:id`
  检查返回的 `data.ok` 与 `data.values`——values 的键名就是模板里 `data.values.*` 的键名，
  **把这份真实 values 存进 board.json 的 `demoData.values`**（预览即真实数据形态）。

## 阶段 2：生成看板工程（配置文件 + 模板）

在用户当前项目下创建：

```
<proj>/sudoboard/
├── board.json          # 声明式配置清单（唯一事实来源，appId 字段实现幂等同步）
├── templates/main.jsx  # 页面展示模板（JSX，契约见「模板写作技巧」）
├── assets/             # 壁纸等素材（wallpaper.sh 下载到这里）
└── preview/            # build_preview.py 的产物（index.html、data.json）
```

**同时提醒用户**：board.json 会包含 API Key / DB 密码等敏感信息，建议把 `sudoboard/` 加进 `<proj>/.gitignore`。

### board.json Schema

单看板（最常用，简写）：

```jsonc
{
  "device": { "url": "http://192.168.1.23:8866" },   // 可被 $SUDOBOARD_URL / --url 覆盖
  "board": { "name": "项目数据看板", "theme": "dark" }, // theme: dark|light（预览默认遮罩/壁纸）
  "sources": [
    { "key": "github",            // 工程内引用名
      "appId": null,              // App 侧 id（src*）；首次同步后自动回填，之后幂等更新
      "create": { /* 阶段1 的完整数据源 payload */ } }
  ],
  "template": {
    "key": "main",
    "appId": null,                // tpl*
    "name": "项目总览",
    "file": "templates/main.jsx", // 相对 sudoboard/ 目录
    "theme": "dark",              // 可选：与模板内 /* sb-theme: dark */ 声明的期望值一致，用于校验提醒
    "demoData": {                 // 预览数据（无设备时用）；有 preview/data.json 时自动被真实快照覆盖
      "values": { /* 阶段1 抓到的真实命名值，或合理演示值 */ },
      "meta": { "updatedAt": "2026-01-01T00:00:00Z", "sourceStatus": { "github": { "ok": true } } }
    }
  },
  "dashboard": {
    "key": "main",
    "appId": null,                // dash*
    "name": "项目总览",            // 会显示为播放页顶部标题
    "templateKey": "main",
    "sourceKeys": ["github"],
    "background": {               // 可省略 = 无壁纸
      "file": "assets/wallpaper-dark.jpg",
      "assetAppId": null,         // a*
      "hash": null,               // sync 自动维护；文件变更自动重传
      "opacity": 1.0,             // 0~1
      "blur": 0                   // 0~100 px
    },
    "refreshSeconds": 60          // 数据静默刷新间隔（>=5）
  },
  "playback": {                   // 轮播方案（单看板也建一个，App /play 只播激活组）
    "key": "main",
    "appId": null,                // grp*
    "name": "主轮播",
    "dashboardKeys": ["main"],
    "durationSeconds": 30,        // 每屏停留（>=5）
    "transition": { "style": "fade", "durationMs": 800 },  // fade|slide|zoom|none
    "activate": true              // 同步后设为激活组
  }
}
```

**多屏轮播**（可选）：把 `template` / `dashboard` 换成数组 `templates: [...]` / `dashboards: [...]`，
每个看板用 `key` 标识、`templateKey` 指向模板，`playback.dashboardKeys` 按顺序列出要轮播的看板 key：

```jsonc
{
  "templates": [
    { "key": "kpi",  "name": "指标屏", "file": "templates/kpi.jsx",  "theme": "dark" },
    { "key": "chart","name": "趋势屏", "file": "templates/chart.jsx","theme": "dark" }
  ],
  "dashboards": [
    { "key": "main",  "name": "指标屏", "templateKey": "kpi",   "sourceKeys": ["github"], "refreshSeconds": 60 },
    { "key": "trend", "name": "趋势屏", "templateKey": "chart", "sourceKeys": ["github"], "refreshSeconds": 60 }
  ],
  "playback": { "name": "主轮播", "dashboardKeys": ["main", "trend"], "durationSeconds": 30, "activate": true }
}
```

- `sync.py` 支持数组语义（幂等、回填 appId）；**Cloudflare 只服务一块看板**（取 `key: main` 的那个，其余会提示走 App）；
- 数组写法与简写不可混用；数组存在时忽略 `template`/`dashboard` 简写。

## 阶段 3：模板写作技巧（核心，务必遵守）

模板是一段**受约束的 JSX**，App 端由 Babel（classic runtime）编译为 React 组件。**预览脚本与 App 用完全相同的编译路径**（含 React 19 运行时），所以本地预览通过 ≈ 上机可用；但仍要遵守以下契约，否则同步时被拒或上机观感异常。

### 3.1 硬性契约（违反 = 编译失败或被拒）

```jsx
/* sb-theme: dark */                 // ★ 深浅色显式声明（见 3.3），建议首行
export default function Screen({ data }) {
  // data = {
  //   values: { 指标名: 值 },                    // ★ 主要数据来源
  //   meta:  {
  //     updatedAt, theme,
  //     sourceStatus: { 源id: { ok, lastError } },
  //     deltas: { 指标名: { diff?, pct?, baseline?, baselineAt? } }  // 环比（仅 App 有）
  //   }
  // }
  return (/* 根节点铺满一屏 */);
}
```

1. **唯一导出** `export default function Screen({ data })`；不用 TS 类型标注。
2. **无 `import`/`require`**，无 `fetch`/`XMLHttpRequest`/WebSocket——模板零网络。
3. 可用全局只有三个：`React`、`echarts`、`Masonry`。hooks 从 React 解构：`const { useState, useEffect, useRef } = React;`（仅限 React 内建）。
4. 体积 < 200KB；不外链任何公网资源（App 离线运行）；样式用内联 `style` 或局部 `<style>{...}</style>`。
5. **不要用 Tailwind class**（那是应用 UI 专用，模板会被丢弃）。
6. **不要依赖 `data.raw`**：播放页数据分发不回传 raw（只有 `rawPreview` 摘要），只用 `values` 与 `meta`。
7. **环比 `meta.deltas`**：App 端引擎会算（按源的 `deltaFormat` 裁剪），本地引擎与 Cloudflare 不算（取不到时字段缺失）。
   写法：`const d = (data.meta.deltas || {})[key]; d && (d.diff ?? d.pct)`，无数据就不渲染角标。

### 3.2 播放页观感规范（违反 = 上机后"变丑"）

App 的 `/play` 在模板外层统一渲染了这些东西，**模板不要重复做**：

| 播放页已提供 | 模板应怎么做 |
|---|---|
| 壁纸背景图层（看板绑定的 backgroundId + opacity/blur） | 根节点 `background: 'transparent'` |
| 半透明遮罩层（提升卡片可读性） | 同上，不要自己叠底色 |
| 顶部标题栏「看板名 · HH:MM」 | **不要在模板里做标题** |
| 溢出兜底：内容超宽时 SmartStage 自动横向无缝慢速滚动 | 按横向瀑布流排版即可，不怕内容超屏 |
| 轮播转场动画 | 模板内不要做整屏转场 |
| 模板运行期报错兜底（ErrorBoundary + 错误横幅） | 正常写即可，报错会在页面上显示 |

排版惯例（与内置模板库一致，观感统一）：
- 根节点：`{ width: '100%', height: '100%', boxSizing: 'border-box', padding: '22px 26px', display: 'flex', flexDirection: 'column', background: 'transparent' }`
- **直角**（不要 border-radius）；卡片间 `gap: 15`，不贴边。
- **横向瀑布流**：把内容项每 4 个一列手工分列，行高 `calc((100% - 3*15px) / 4)`，列宽按内容估宽（上限 ~360px）。参考 `<skill>/examples/` 的骨架模板——骨架自带「占位填充」段（不足 32 项时重复填充标记为「占位」的卡片，把画面撑出横向滚动观感），**正式模板删掉该段即可**只显示真实指标。
- 数字排版：`fontVariantNumeric: 'tabular-nums'` + `Number(v).toLocaleString('zh-CN')`，大字号（34~64px），标签小字灰阶。

### 3.3 深浅色：显式声明，不要靠颜色猜

播放页决定遮罩色调（深色看板黑遮罩 / 浅色看板白遮罩），判定顺序：

1. **模板里的显式声明**（推荐，唯一可靠）：源码任意位置写 `/* sb-theme: dark */` 或 `/* sb-theme: light */`
   （大小写不敏感，`// sb-theme: light` 也行）。三端（App / 本地预览 / Cloudflare）读同一份声明。
2. 没有声明时退回**颜色启发式**：源码里出现 `#fff`/`#ffffff`、`#f5f6f8` 这类 `#f` 开头且各通道 ≥0xE0 的 6 位 hex、
   或 `rgba(255,255,255,α≥0.5)` → 判浅色；否则判深色。
   - 深色模板里写 `#fff` 白字、或大块 `rgba(255,255,255,0.9)` 底，**仍会被判成浅色**；
   - `#f87171`（红）、`#F6E500`（黄）、`rgba(255,255,255,0.08)`（描边）、`#e8eaf0`（近白文字）不会误判。

**结论：每个模板都写上 `/* sb-theme: ... */`**，并让它与 `board.theme` 一致。
`build_preview.py` / `sync.py` 会在两者不一致时打印 `⚠ 模板观感`。

### 3.4 ECharts 用法（图表模板）

```jsx
const { useEffect, useRef } = React;
const chartRef = useRef(null);
useEffect(() => {
  if (!chartRef.current || typeof echarts === 'undefined') return;
  const chart = echarts.init(chartRef.current);
  chart.setOption({
    backgroundColor: 'transparent',       // ★ 透出壁纸
    /* xAxis/series ... 数据取自 data.values */
  });
  return () => chart.dispose();           // ★ 必须 dispose（7×24 长稳）
}, [/* ★ 依赖里带上模板用到的数据字段（如 trend），数据刷新时图表重绘 */]);
```

容器 div 要有明确宽高（放进瀑布流卡片即可）；深色大屏的坐标轴/分割线用低饱和灰（`#3a3f4a` / `#23262E`），标签 `#8f8f8f`。

### 3.5 同步前自查清单

- [ ] 首行有 `/* sb-theme: dark|light */`，且与 `board.theme` 一致
- [ ] `export default function Screen` 存在；无 import/require/fetch；无 TS 标注
- [ ] 根节点铺满 + `background: 'transparent'`；无内置标题；无 border-radius
- [ ] ECharts 有 `backgroundColor: 'transparent'` 和 `dispose` 清理
- [ ] 体积 < 200KB
- `build_preview.py` / `sync.py` 会做静态校验（阻断项 + 观感警告）；`sync.py` 不通过会拒绝同步（除非 `--force`）。

## 阶段 4：本地预览（真实抓取 + 保真渲染，浏览器里迭代）

```bash
# 首次：抓默认壁纸（dark-demo / light-demo 两张示意图；也可自定义，见下一节）
bash <skill>/scripts/wallpaper.sh --dir <proj>/sudoboard

# 生成预览并打开浏览器：--fetch 会先运行本地数据引擎（engine.js）——
# 按 board.json 里源配置真实发起 HTTP 抓取（Method/Headers/超时），
# 用官方 JSONATA 抽取命名值，写入 preview/data.json 后嵌入模板渲染
python3 <skill>/scripts/build_preview.py --dir <proj>/sudoboard --fetch --open
```

**本地数据引擎（`engine.js`，Node ≥18）**：与 App 同一套取数逻辑的本地实现——
- **HTTP 源**：按配置真实抓取 → JSONATA 抽取（官方 jsonata 实现，与 App 的 jsonata_dart 同语言）；
- **DB 源（sqlite / mysql / pg）**：本地直接执行命名查询，`values[查询名] = {columns, rows}`（与 App QueryTable 同形态）；只读拦截 1:1 移植 ReadOnlyGuard（写前缀/多语句/字符串剥离）。sqlite 用 Node 内置 `node:sqlite`（≥22.13）零依赖；mysql2/pg 为纯 JS 驱动，首次使用自动安装到 `<skill>/scripts/vendor/nodejs/`（需网络，仅一次）；
- 单源失败只标记该源 `sourceStatus.ok=false`，不阻塞其他源；DB 源部分查询失败时 ok=false 但成功结果照常保留（与 App 引擎一致）；
- **全部源失败时不写 `preview/data.json`**（避免空值盖掉 demoData / 上一次的好数据），并打印提示；
- **限制**：一次性取数，不做定时轮询与环比（`deltas`）计算；DB 源也可以改用 `python3 <skill>/scripts/sync.py snapshot --dir ...` 从设备 App 引擎拉真实快照（同样写入 preview/data.json）。

预览页与 App `/play` 同一条渲染路径，并复刻了播放页的全部外层观感：

- Babel classic runtime 编译 + `React`/`echarts`/`Masonry` 三全局（React 19 与 App 打包版本一致）；
- 壁纸图层（用 board.json 配置的背景，含 opacity/blur）+ 深浅遮罩（同一套判定：声明 > 启发式）；
- 顶部「看板名 · HH:MM」标题栏；溢出自动横向**无缝循环滚动**（与 App SmartStage 相同：内容克隆两份只向前滚，永不反向；纵向溢出则下行-停留-上行）；
- 右上角 dark/light 切换：联动切换遮罩色调与背景图（`assets/` 里有文件名对应的 dark/light 图时自动替换，如 `wallpaper-dark.jpg` ↔ `wallpaper-light.jpg`），模板收到对应 `meta.theme`，用于检查两套观感；
- 编译错误与**运行期错误**都直接显示在页面上（ErrorBoundary，等同于 App 的兜底错误视图）。

**数据模式**：优先用 `<proj>/sudoboard/preview/data.json`（真实数据），否则用 board.json 的 `demoData`。真实数据两种来源：
1. **本地引擎**（HTTP 源，无需设备在线）：`build_preview.py --fetch` 或单独 `node <skill>/scripts/engine.js --dir ...`；
2. **设备快照**（DB 源，或想用 App 引擎结果）：`sync.py snapshot --dir ...`。

迭代：改模板 → 重跑 build（或让用户刷新浏览器）→ 截图给用户看 → 满意为止。
> 注：预览库走 CDN（React 19 ESM + Babel/echarts/Masonry），离线时预览页会明确报 CDN 加载失败；这不影响 App 端运行（App 内置这些库）。

### 壁纸

```bash
bash <skill>/scripts/wallpaper.sh --dir <proj>/sudoboard              # 默认：dark+light 两张示意壁纸
bash <skill>/scripts/wallpaper.sh --dir ... --only dark               # 只下深色
bash <skill>/scripts/wallpaper.sh --dir ... --url https://...jpg --name my-wall.jpg  # 用户自定义图片
```

默认壁纸是官方示意图（`sudb.106001.xyz/background/demo/dark-demo.jpg` / `light-demo.jpg`），仅作示意预览；用户可在 board.json 的 `background.file` 里指向任何本地图片。深色看板配深色壁纸（dark/black 系），浅色看板配浅色壁纸（light/white 系）。

## 阶段 5A：部署到 Cloudflare（无 App 参与，最省事）

无需任何设备：把整个看板（**数据引擎 + 播放页 + 资产 + cron 定时抓取**）作为 Cloudflare Worker
上线到公网，浏览器/电视打开 URL 即看。`board.json`/模板与本地预览完全同源，App 只是另一个可选部署目标。

```bash
python3 <skill>/scripts/deploy_cf.py --dir <proj>/sudoboard            # 默认名：由主看板名生成
python3 <skill>/scripts/deploy_cf.py --dir <proj>/sudoboard --name sudb-my-board  # 自定义名
python3 <skill>/scripts/deploy_cf.py --dir <proj>/sudoboard --dry-run # 只生成 dist/cf/ 工程不部署
```

- 默认 Worker 名 = 主看板名（`dashboard.name` > `board.name`）slug 化；纯中文名会退化成
  `sudb-<6位哈希>`（避免所有中文看板撞名），要固定名字就显式 `--name`；
- **多屏看板**：Cloudflare 只服务主看板（`dashboards` 里 `key: main`），其余看板会提示走 App。

**产出与效果**：
- 生成 `<proj>/sudoboard/dist/cf/` 完整 Worker 工程（worker.js + wrangler.jsonc + play.html + 资产）；
  **首次部署需已登录的 wrangler**（`wrangler login`；KV/cron 需要真实账号，匿名临时账号不支持）；
- 自动创建/复用 KV namespace（幂等，重复执行不产生重复资源），上传资产，`wrangler deploy`；
- 输出两个地址：播放页 `https://<name>.<account>.workers.dev/play`、状态 API `/api/status`；
- 部署完成自动「预热」一次（POST /api/refresh），数据立刻可用，之后 cron 按源最小间隔刷新。

**Cloudflare 扮演的角色（完全替代 App 的运行时）**：

| App 内能力 | Cloudflare 对应 |
|---|---|
| 数据引擎（HTTP 抓取 + JSONATA 抽取） | Worker 内的数据引擎（同一套逻辑，见 `engine.js`） |
| 定时抓取（intervalSeconds） | Cron Trigger（`*/N * * * *`，N=最小源间隔分钟数） |
| 快照存储（内存库） | KV（binding `SDB`：`snapshot` 最新快照 + `asset:<id>` 资产） |
| `/play` 播放页（壳内 Web） | Worker 路由 `/` 与 `/play` → 生成的播放页（**与预览页同一条渲染路径**，轮询 `/api/data`） |
| `/api/status` `/api/data/:id` | `/api/status`（脱敏）、`/api/data`（全量快照，未过期直接用 KV 缓存） |
| 资产（壁纸） | `/assets/<id>` → KV 读二进制 |
| 刷新 | `POST /api/refresh` 强制重抓（部署预热也用这个） |

**约束（deploy_cf 生成阶段直接拒绝）**：
- 仅支持 **HTTP 源**；DB 源（mysql/pg/sqlite 直连）请走本地预览或 App；
- 源必须 **公网可达**（Worker 在云端抓取，内网地址不可达；不支持的源在 `/api/status` 标记 ok=false 不阻塞其他源）；
- 默认公网可达；**敏感数据记得配 Access 限邮箱**（见下「访问控制」）。`fetch.headers` 等源凭据
  **只进 Worker 配置，绝不下发到播放页/API**（播放页仅含看板名/模板/背景 URL；`/api/status` 只回名称与状态）。

**🔒 访问控制（重要：线上看板默认应该限访问者）**：
线上 URL 对公网公开 = 谁都看得到数据。**建议每次部署都启用 Cloudflare Access**（Worker 级，
2026-08+ 支持）只允许指定邮箱/域名访问：

```bash
# 自动创建 Access（需要带 Access: Apps and Policies Edit 权限的 API token）
export CLOUDFLARE_API_TOKEN=<含 Access Edit 权限的 token>
export CLOUDFLARE_ACCOUNT_ID=<你的账户 ID>   # 可选，缺省从 wrangler whoami 解析
python3 <skill>/scripts/deploy_cf.py --dir <proj>/sudoboard --access-allow you@x.com,@corp.cn
```

- `--access-allow` 逗号分隔：`you@x.com` 限单邮箱；`@corp.cn`/`example.com` 限整个邮箱域名；
- 实现方式：`POST /accounts/{id}/access/apps`，`destinations:[{type:"worker",worker_id}]` 保护该
  Worker 的全部域名（workers.dev/自定义域/路由），policy `include` 按邮箱放行；
- **没有 token 时部署也照常成功**，但会在输出里打印 ⚠ 公开提示 + 三种启用方式
  （自动 / Dashboard 手动 / 可复制的 API curl）——见到提示就说明看板还没上锁；
- Dashboard 手动路径：Workers & Pages → 对应 Worker → **Access tab** → Enable Access → All traffic
  → policy 选 Email / Email domain 输入允许名单（Zero Trust → Access → Applications 里可复查）；
- 已受保护时 Worker 内可用 `ctx.access.getIdentity()` 取访问者邮箱（本技能生成的 Worker 预留该能力，`/api/me` 可自查）。

**更新与清理**：
- 改了 board.json/模板/壁纸后**重跑同一命令即可**（`--name` 保持一致），Worker 覆盖更新、资产按内容寻址去重；
- 下线：`wrangler delete --name <worker名>`（KV 保留）。

## 阶段 5B：同步到 App（可选，已有 SudoBoard 设备时）

```bash
python3 <skill>/scripts/sync.py --dir <proj>/sudoboard \
  [--url "$SB_URL"] [--pin "$SUDOBOARD_ADMIN_PIN"] [--dry-run] [--no-activate] [--force]
```

sync 按依赖序执行并**把 App 侧 id 回填进 board.json**，重复执行不会产生重复资源：

1. 上传壁纸资产（hash 未变则跳过）→ 2. 创建/更新数据源 + 立即抓取验证 → 3. 创建/更新模板（先静态校验）→ 4. 创建/更新看板（绑模板/源/背景/opacity/blur）→ 5. 创建/更新轮播方案并激活 → 6. `GET /api/play/active` 回读验证。

- `--dry-run` 只打印计划不执行（**不连接设备，因此不需要 PIN**）；`--no-activate` 不切换激活组；`--force` 跳过模板静态校验。
- 多屏：`templates`/`dashboards` 数组会全部同步并按 `playback.dashboardKeys` 组成轮播。
- 全部通过后输出：设备屏幕 ≤1s 自动更新（无需重启 App）；局域网预览地址 `http://<设备IP>:8866/play`。
- 改了模板/配置后**重跑 sync 即可**，App 端自动热更新。
- 设备上资源被删/重置时，sync 检测到 404 会自动重新创建并回填新 id。

## 阶段 6：打包分发（App 专用：跨网部署到电视/旧手机）

仅当目标设备是 **SudoBoard App**（电视/旧手机，且与电脑不在同一局域网）时使用：
把配置打成**看板包**（Bundle v1）上传到互联网，电视 App 首启向导「从看板包恢复」输入直链即可完成部署。
> 提示：没有 App 设备、只想网页看板？直接用「阶段 5A」部署到 Cloudflare，不需要打包。

```bash
# 1. 生成看板包（PIN 必填：既是包加密密码，也是导入设备的新管理密码）
python3 <skill>/scripts/bundle.py pack --dir <proj>/sudoboard --pin "$SUDOBOARD_ADMIN_PIN"
#    可选 --from-device --url http://<设备IP>:8866 --device-pin XXX：配置取自已同步设备

# 2. 分发（三选一，默认 auto：wrangler 已登录→R2 永久；未登录→Cloudflare 匿名临时账号 60 分钟有效）
python3 <skill>/scripts/bundle.py deploy <proj>/sudoboard/dist/bundle.zip
python3 <skill>/scripts/bundle.py deploy <zip> --mode temporary     # 强制匿名临时（60min，附 Claim URL 可转正）
python3 <skill>/scripts/bundle.py deploy <zip> --mode cmd --upload-cmd 'sh upload.sh "$SUDOBOARD_ZIP"'  # 自建兜底：stdout 输出直链

# 3. 校验（可选）
python3 <skill>/scripts/bundle.py verify <zip> --pin "$SUDOBOARD_ADMIN_PIN"
```

- **电视端操作**：首次启动 App → 引导页点「从看板包恢复」→ 粘贴直链 + 输入看板包密码
  （= 打包时的管理密码；可选再设新管理密码）→ 导入成功自动激活播放。
  若设备已配置过，从管理页备份区导入（需管理员登录）。
- **Bundle 契约 v1**（与 App `/api/bundle/export` 产物完全同构，格式与生成地无关）：
  `manifest.json`（schemaVersion/files sha256）+ `config/payload`（PBKDF2-10k + AES-256-CBC，
  内含管理 PIN 明文）+ `assets/<id>.<ext>`；ZIP 本体不加密，敏感内容全在加密 payload 内。
- **约束**：单资产 ≤5 MiB（超限先压缩壁纸再打包）；临时通道 60 分钟内有效
  （Claim URL 可转正为永久账号；或随时重新 deploy）；workers.dev 可达性不佳的自建网络用 `--mode cmd` 兜底。
- 多屏工程的 `templates`/`dashboards` 数组会完整进包（`playback.dashboardKeys` 决定轮播顺序）。

---

## 附录

- **接口速查**（App 与 Cloudflare 的全部端点、鉴权、约束）：`references/api.md`
- **排错 / 常见问题**（不生效、发灰、白屏、抓取失败、Access、401 等）：`references/faq.md`
