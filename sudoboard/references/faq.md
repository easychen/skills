# SudoBoard 常见问题 / 排错

> 本文件是 `SKILL.md` 的附录。按现象查。

## 改了不生效？

两个部署目标分别验证：

- **Cloudflare**：重跑 `deploy_cf.py`（同名覆盖）后看 `/api/status` 的 `updatedAt` 是否更新；
  想立刻刷新数据用 `curl -X POST https://<name>.<acct>.workers.dev/api/refresh`。
- **App**：确认 `sync.py` 最后一步 `play/active` 验证通过，设备屏 ≤1s 自动更新（SSE playStamp）。

## 深色看板发灰 / 遮罩色调相反？

播放页靠**模板源码**判定深浅色：优先读模板里的显式声明 `/* sb-theme: dark */`，没有声明才退回颜色启发式。
所以：

1. 在模板首行加 `/* sb-theme: dark */`（或 `light`），这是唯一可靠的判定方式；
2. 没有声明时，启发式只认「像浅色底」的颜色：`#fff`/`#ffffff`、`#f5f6f8` 这类 `#f` 开头且各通道 ≥0xE0 的
   6 位 hex、以及 `rgba(255,255,255,α≥0.5)`；
3. 所以深色模板里写 `#fff` 白字、或 `rgba(255,255,255,0.9)` 大块白底，仍会被判成浅色 ——
   显式声明可以彻底绕开这个问题。

`build_preview.py` / `sync.py` 会在「声明与 `board.theme` 不一致」时打印 `⚠ 模板观感` 提醒。

## 预览一片空白？

- 模板**编译**错误 → 预览页直接显示错误横幅（与 App 兜底视图一致）；
- 模板**运行期**报错（如访问了 `data.values` 里不存在的字段再 `.toFixed()`）→ 现在也会显示错误横幅
  （预览页内置 ErrorBoundary；App 端同样有兜底）。先看横幅里的 JS 报错，再打开浏览器 console。
- 依赖 CDN 加载失败（离线环境）→ 横幅会明确说明；这只影响本地预览，App 端内置这些库。

## 预览里的数据是演示值，不是真实数据？

数据优先级：`preview/data.json`（真实快照）> `board.json` 的 `template.demoData`。

- HTTP 源：`python3 <skill>/scripts/build_preview.py --dir ... --fetch`（或单独 `node <skill>/scripts/engine.js --dir ...`）；
- **全部源都失败时 engine 不写 `data.json`**（避免空值盖掉 demoData / 上一次的好数据），预览会继续用旧数据或演示值；
- DB 源 / 想用 App 引擎结果：`python3 <skill>/scripts/sync.py snapshot --dir ...`。

## 数据源抓取失败怎么排查？

- `http_403` / `http_429`：目标 API 拦数据中心 IP（GitHub、CoinGecko 对 Workers 出口尤其明显）。
  换对云端友好的源，或给源加 `User-Agent` 等请求头。
- `timeout`：加大 `fetch.timeoutSeconds`（App 端与本地引擎都生效）。
- `non_json_response`：接口返回的不是 JSON（HTML 错误页/CSV），JSONATA 抽取器无法工作。
- JSONATA 报错：先用 `POST /api/datasources/jsonata-test {"expression":"...","sample":{...}}` 单独验证表达式。
- Cloudflare 上内网地址不可达：Worker 在云端抓取，`http://192.168.x.x` 之类必然失败，请用公网 API 或走 App。

## Cloudflare 部署相关

- **要登录 wrangler 吗？** 要。`wrangler login` 后才有真实账号资源（KV namespace + cron）；
  匿名临时账号（`--temporary`）不支持本部署，但 `bundle.py` 的分发通道仍可用匿名临时账号。
- **Worker 名怎么来的？** 默认取主看板名（`dashboard.name` > `board.name`）slug 化；
  纯中文名会退化成 `sudb-<6位哈希>`，可用 `--name` 显式指定。
- **一次能部署几块看板？** Cloudflare 只服务一块（主看板 = `dashboards` 里 `key: main` 的那个）；
  多屏轮播请用 App（`sync.py`）。`deploy_cf.py` 会提示哪些看板没上线。
- **看板被公网看到了？** 部署默认不带访问限制 → 输出里会有 ⚠ 提示。尽快启用 Cloudflare Access：
  重跑 `deploy_cf.py --access-allow <自己的邮箱>`（需 `CLOUDFLARE_API_TOKEN` 带 Access Edit 权限），
  或按提示去 Workers & Pages → 该 Worker → Access tab 手动开。

## App 同步相关

- **401？** 会话 30 分钟过期，重新 admin-login；`sync.py` 每次会自己登录。
- **`--dry-run` 要 PIN 吗？** 不要（它不连设备）；只有真实同步才需要 PIN。
- **连不上设备？** App 默认只绑 `127.0.0.1`：在 App 里「菜单 → 进入管理 → **设备信息** → 局域网访问」打开开关，
  然后 `SUDOBOARD_URL` 用设备 IP（设备信息页可见）。
- **资源被删了怎么办？** `sync.py` 检测到 404 会自动降级为重新创建并把新 id 回填 `board.json`。

## 敏感信息

`board.json` 与 cookie 临时文件含凭据，别提交进 git（把 `sudoboard/` 加进 `.gitignore`）；用完删除 `$SB_COOKIES`。
Cloudflare 部署会把 `fetch.headers` 等源凭据嵌入 Worker 配置（服务端必需），播放页/API 不会下发。
