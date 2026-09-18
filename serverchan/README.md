# serverchan-skill

一个 [Agent Skill](https://github.com/vercel-labs/agent-skills)，用 [Server 酱（方糖）](https://sct.ftqq.com) 向微信 / App 推送消息通知。

发送逻辑对齐官方 SDK [easychen/serverchan-sdk](https://github.com/easychen/serverchan-sdk)，**同时兼容**：

- **Server酱Turbo（SCT）** — SendKey 形如 `SCTxxxxxx`
- **Server酱³（SC3）** — SendKey 形如 `sctp<数字>t<token>`

按 SendKey 前缀**自动选择推送端点**，无需任何额外配置。纯 `bash` + `curl` 实现，零依赖。

## 安装

通过 [`skills`](https://www.npmjs.com/package/skills) CLI 安装：

```bash
# 安装到当前项目
npx skills add easychen/serverchan-skill

# 或安装到全局（所有 agent 可用）
npx skills add easychen/serverchan-skill -g
```

## 配置

在环境变量中提供你的 Server 酱 SendKey：

```bash
export SERVERCHAN_SENDKEY="SCTxxxxxx"        # Server酱Turbo
# 或
export SERVERCHAN_SENDKEY="sctp123txxxxxx"   # Server酱³
```

- Server酱Turbo SendKey：https://sct.ftqq.com
- Server酱³ SendKey：https://sc3.ft07.com

> ⚠️ SendKey 等同推送凭证，请勿提交进代码库或打印到日志。本技能脚本绝不会 echo / log SendKey。

## 用法

安装后，直接让 agent「用 Server 酱给我推送一条消息」即可。底层调用脚本：

```bash
# 仅标题
bash scripts/send.sh "部署完成"

# 标题 + Markdown 正文（多行用 \n）
bash scripts/send.sh "部署完成" "服务已上线 ✅\n\n版本 v1.2.3"

# 带可选参数（第三个参数是透传给 Server 酱的 options JSON）
bash scripts/send.sh "告警" "CPU **95%**，请处理" '{"tags":"运维|告警","short":"CPU 95%"}'
```

| 位置 | 字段 | 说明 |
|------|------|------|
| 1（必填） | `title` | 消息标题 |
| 2（可选） | `desp` | 正文，支持 Markdown |
| 3（可选） | `options` JSON | 透传字段：`tags`（`\|` 分隔）、`short`、`channel`、`noip` 等 |

成功时服务端返回 `{"code":0,...}`，脚本退出码为 0；失败时打印响应并以非 0 退出。

环境自检：

```bash
bash scripts/check-env.sh
```

## 工作原理

| SendKey 前缀 | 推送端点 |
|--------------|----------|
| `sctp`（SC3） | `https://<num>.push.ft07.com/send/<sendkey>.send`（`num` 取自 `sctp<num>t`） |
| 其它（SCT） | `https://sctapi.ftqq.com/<sendkey>.send` |

POST JSON `{title, desp, ...options}`，`Content-Type: application/json;charset=utf-8`。

## License

MIT
