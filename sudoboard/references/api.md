# SudoBoard API 速查

> 本文件是 `SKILL.md` 的附录。日常流程不需要它；只有在手写 curl、排查接口、或需要 CLI 未封装的能力时再读。
> `<skill>` = 本技能目录；`$SB_URL` = 设备地址（如 `http://192.168.1.23:8866`）；`$SB_COOKIES` = `curl -c` 的临时 cookie 文件。

## App（局域网设备）接口 —— Admin Cookie 鉴权

鉴权：`POST /api/auth/admin-login {"pin":"..."}` → `Set-Cookie: sb_admin`（会话 30 分钟）。
后续请求带 `-b "$SB_COOKIES"`。响应统一 `{"ok":true,"data":{...}}` 或 `{"error":"..."}`。
id 前缀：`src*` / `tpl*` / `dash*` / `grp*` / `a*`。

| 方法 | 路径 | Body / 说明 |
|---|---|---|
| GET | `/api/status` | **公开**。running/port/httpBind/theme/sources 状态 |
| POST | `/api/auth/admin-login` | `{"pin":"..."}` → Set-Cookie `sb_admin`（会话 30min） |
| GET | `/api/session` | 当前会话身份（admin/display） |
| POST | `/api/auth/logout` | 注销 |
| POST | `/api/bundle/export` | `{"pin":"..."}`（admin）→ 看板包 ZIP（加密配置+资产） |
| POST | `/api/bundle/import` | `{"password","url"\|"zipBase64","newPin"?}`；未配置设备免鉴权（首启快速配置），已配置需 admin |
| GET/POST | `/api/datasources` | 列表 / 创建（见 SKILL.md 阶段1 payload） |
| PUT/DELETE | `/api/datasources/:id` | 更新（全量 payload）/ 删除 |
| POST | `/api/datasources/:id/fetch` | 立即抓取，返回快照 |
| POST | `/api/datasources/jsonata-test` | `{"expression","sample"}` → 抽取结果 |
| GET | `/api/data/:sourceId` | 最新快照 `{sourceId, ok, values, deltas, fetchedAt, lastError, rawPreview}` |
| GET/POST | `/api/templates` | 列表 / `{"name","source"}`（source=JSX 源码） |
| PUT/DELETE | `/api/templates/:id` | 更新 / 删除 |
| GET/POST | `/api/dashboards` | 列表 / `{"name","templateId","sourceIds","backgroundId","bgOpacity","bgBlur","refreshSeconds"}` |
| PUT/DELETE | `/api/dashboards/:id` | 更新（部分字段可省）/ 删除 |
| GET/POST | `/api/playback-groups` | 列表 / `{"name","dashboards":[{"dashboardId","durationSeconds"}],"transition":{"style","durationMs"},"music":{"assetIds":[],"mode","volume"},"background":{"mode":"perDashboard"}}` |
| POST | `/api/playback-groups/:id/activate` | 设为激活组 |
| GET | `/api/assets` | 素材列表（用于判断本地 hash 是否仍需上传） |
| POST | `/api/assets/upload` | `{"name","kind":"image","mime","base64","tags":[]}`（jpg/png/webp/svg） |
| GET | `/assets/:id` | 资产二进制（播放页背景） |
| GET | `/api/play/active` | 当前激活组 + 看板 + 资产 URL（同步后验证用） |
| GET | `/api/events` | SSE：`{type,rev,value:{theme,locale,volume,playing,playStamp,...}}`（≤1s 热更新） |

约束（`api_server.dart` 校验）：`datasources.intervalSeconds ≥ 1`、`dashboards.refreshSeconds ≥ 5`、
`playback.dashboards[].durationSeconds ≥ 5`；DB 源必须提供 `db.kind` + 查询；SQL 只读拦截默认开启。

## Cloudflare 部署的接口（`deploy_cf.py` 产出，免鉴权、公网）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` 或 `/play` | 播放页（模板/看板名/背景内联，轮询 `/api/data`） |
| GET | `/api/status` | 脱敏状态：mode=cloudflare/boardName/theme/updatedAt/refreshSeconds/sources[].ok |
| GET | `/api/data` | 全量快照 `{values, meta:{updatedAt,sourceStatus,theme}}`；未超源最小间隔直接用 KV 缓存 |
| POST | `/api/refresh` | 强制抓取全部源并落 KV（部署「预热」用的就是它） |
| GET | `/api/me` | Access 生效时返回访问者邮箱（`ctx.access.getIdentity()`） |
| GET | `/assets/<id>` | 资产二进制（壁纸），按 CONFIG.assets 的 mime 返回 |
| GET | `/robots.txt` | `Disallow: /`（避免被搜索引擎收录） |

单源失败不阻塞其他源；失败源会沿用上一份快照里属于它的命名值（不会清空看板）。
`fetch.headers` 等源凭据只进 Worker 配置，绝不下发到播放页/API。
