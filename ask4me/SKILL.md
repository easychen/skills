---
name: ask4me
description: 用 Ask4Me 让真人确认、选择或填表，并等待结果（Human-in-the-Loop）。默认使用公共试用服务 https://ask.app.ft07.com，邀请码 askd-2026，开箱即用；支持多用户 API key、ServerChan 推送和可选端到端加密（E2EE）。当用户说“问一下我 / 让他确认 / 发个审批 / 收集表单 / 需要人工确认 / 用 Ask4Me”时使用。
tags: [human-in-the-loop, approval, form, notification, e2ee, ask4me]
allowed-tools:
  - Bash
  - Read
  - Write
env_vars:
  - key: ASK4ME_BASE_URL
    required: false
    desc: Ask4Me 服务地址，默认 https://ask.app.ft07.com
  - key: ASK4ME_API_KEY
    required: false
    desc: 可选；不填时首次 create 会自动生成并保存到 ~/.config/ask4me/config.json
  - key: ASK4ME_SERVERCHAN_SENDKEY
    required: false
    desc: 可选；填了就走 ServerChan 推送，不填就走链接模式
  - key: ASK4ME_E2EE_PASSWORD
    required: false
    desc: 可选 E2EE 口令；不要写入仓库、日志或通知正文
---

# Ask4Me · 让人工确认 / 选择 / 填表

Ask4Me 是一个已部署好的 Human-in-the-Loop 服务：你发一个请求，服务生成交互链接；可以推到真人手机（ServerChan），也可以直接把链接发给对方。对方点按钮或填表后，你的命令拿到最终结果。

**这是一个纯客户端 skill，不需要部署服务。** 默认用我们提供的公共试用服务器，开箱即用；多用户模式下每个用户用自己的 API key。

## 自动更新检查

脚本在每次 `create` / `ask` / `test` 启动时会检查一次 GitHub 上的 skill 版本（**最多每 24 小时一次**，网络失败自动忽略，不阻塞请求）。发现新版本会在 stderr 提示：

```text
[Ask4Me] 发现 skill 新版本 x.y.z（当前 a.b.c）。
[Ask4Me] 更新：npx skills add easychen/skills --skill ask4me
```

- 手动查版本：`node scripts/ask4me.mjs version`
- 关闭检查：`ASK4ME_NO_UPDATE_CHECK=1` 或 `--no-update-check`
- 不要自动替用户执行更新；提示后让用户决定。

## 装完就能用：默认试用

- 默认服务：`https://ask.app.ft07.com`；默认邀请码：`askd-2026`。
- **不要先让用户自建服务器，也不要先让他准备 SendKey 或手动 keygen。**
- 第一次 `create` 会自动生成并保存 API key 到 `~/.config/ask4me/config.json`（权限 600）。
- 没有 `ASK4ME_SERVERCHAN_SENDKEY` 时走**链接模式**：`create` 返回 `interaction_url`，你把它发给用户；用户打开页面提交后，`wait` 拿结果。
- 配了 SendKey 时自动走 ServerChan 推送，同时也可以把链接发给用户。
- 第一句话可以这样说（简短，不要吓到用户）：

  > Ask4Me 可以直接用公共试用服务，不需要你搭服务器。你把确认/表单点一下就行。试用服务不稳定，长期用再自建。

**试用服务不稳定**：可能停机、限流或清理数据；不要放长期/敏感数据。正式使用或遇到问题，再引导自建：

- <https://github.com/easychen/ask4me>
- <https://github.com/easychen/ask4me/blob/main/docs/ubuntu-deploy.md>

## 先做环境检查

需要 Node.js 18+。脚本在技能目录的 `scripts/ask4me.mjs`，零依赖。

```bash
node -v
```

如果低于 18，先让用户升级 Node，不要继续。

## 第一次使用（零配置）

### 1. 服务地址与邀请码

默认已经内置，不需要问用户；只有用户明确要自建/自定义时才改 `ASK4ME_BASE_URL` / `--invite`。

### 2. 创建请求（create）

```bash
node scripts/ask4me.mjs create \
  --title "确认发布" \
  --body "请确认。" \
  --mcd $':::buttons\n- [OK](ok)\n- [取消](cancel)\n:::'
```

输出：

```json
{"request_id":"req_xxx","interaction_url":"https://ask.app.ft07.com/r/...","mode":"web"}
```

- `mode=web`：没有 SendKey，链接模式。把 `interaction_url` 发给用户（私下发，不要公开）。
- `mode=notify`：有 SendKey，已推送；也可以同时把链接发给用户。
- 第一次运行会自动生成 key，不需要手动 keygen；不要在回答里回显完整 key。

### 3. 等待结果（wait）

```bash
node scripts/ask4me.mjs wait --request-id req_xxx
```

输出 `user.submitted` 的 `data`；`request.expired` 表示用户没提交。

### 4. 可选：E2EE

```bash
export ASK4ME_E2EE_PASSWORD='和回答者另行约定的口令'
node scripts/ask4me.mjs create --title "加密审批" --body "这段会加密"
node scripts/ask4me.mjs wait --request-id req_xxx
```

- 口令只用于客户端加解密，不会发给服务端；
- 必须另行告知回答者，不能放在通知/同一消息里；
- 忘记口令无法恢复。

### 5. 可选：ServerChan 推送

```bash
export ASK4ME_SERVERCHAN_SENDKEY='SCT...'
```

有 SendKey 时 `create` 自动走推送；没有就走链接模式。当前服务镜像不支持 Apprise。

### 6. 自定义服务器（可选）

只有用户明确要自建时：

```bash
export ASK4ME_BASE_URL='https://your-domain.com'
export ASK4ME_INVITE='your-invite'
node scripts/ask4me.mjs create ...
```

## 正式使用（按钮 / 输入 / JSON Forms）

零配置流程始终是：**`create` → 把链接或通知给用户 → `wait`**。

### 按钮 / 审批

```bash
node scripts/ask4me.mjs create \
  --title "确认发布 v1.2.3" \
  --body "请确认是否发布到生产环境。" \
  --mcd $':::buttons\n- [OK](ok)\n- [取消](cancel)\n:::'
```

把输出里的 `interaction_url` 发给用户；用户提交后：

```bash
node scripts/ask4me.mjs wait --request-id req_xxx
```

### 文字输入

```bash
node scripts/ask4me.mjs create \
  --title "补充说明" \
  --body "请填写发布备注。" \
  --mcd $':::input name="note" label="备注" submit="提交"\n:::'
```

然后 `wait --request-id ...`。

### JSON Forms 表单

先写一个 JSON 文件（例如 `/tmp/form.json`）：

```json
{
  "schema": {
    "type": "object",
    "properties": {
      "name": { "type": "string", "minLength": 1 },
      "age": { "type": "integer", "minimum": 0 }
    },
    "required": ["name"]
  },
  "uischema": {
    "type": "VerticalLayout",
    "elements": [
      { "type": "Control", "scope": "#/properties/name" },
      { "type": "Control", "scope": "#/properties/age" }
    ]
  },
  "data": { "age": 18 },
  "submit_label": "提交"
}
```

```bash
node scripts/ask4me.mjs create \
  --title "填写信息" \
  --body "请填写后提交。" \
  --jsonforms /tmp/form.json
```

然后 `wait --request-id ...`。结果 JSON：

```json
{
  "request_id": "req_xxx",
  "last_event_type": "user.submitted",
  "data": {
    "action": "ok",
    "text": "",
    "payload": { "name": "Alice", "age": 18 }
  }
}
```

E2EE 开启时，`data.text` / `data.payload` 已在本地解密，直接使用。

如果已经配置了 SendKey，并且想一步完成，也可以用 `ask`（内部会创建并等待）；但链接模式请用 `create` + `wait`，否则你拿不到中途的链接。

## 对用户怎么说

链接模式（没有 SendKey）：

> 我把确认链接发给你了，打开后点一下/填一下就行。  
> <interaction_url>

推送模式（配了 SendKey）：

> 已经把确认请求推到你手机了，请点 OK（或打开链接提交）。我这边会等你的结果。

不要把 SendKey、API key、E2EE 口令、完整交互 URL 发到公开频道。链接是访问凭证；通知失败时私下发给用户。

## 排错

| 现象 | 处理 |
|---|---|
| `401 Unauthorized` | 自动保存的 key 失效或邀请码被更换；删掉 `~/.config/ask4me/config.json` 后重试，或 `--invite` 指定新邀请码 |
| `400 notify is required` | 旧服务器不支持链接模式；先升级服务端镜像，或临时配置 `ASK4ME_SERVERCHAN_SENDKEY` |
| `notify.failed` | 推送失败；链接模式会忽略它继续等页面提交。检查 SendKey，或改用链接模式 |
| `mode=web` 没有推送 | 正常：链接模式不推送，把 `interaction_url` 发给用户即可 |
| `429` | 配额满（每 key / 每 IP / 全局）；稍后再试，不要循环重发 |
| `request.expired` | 用户没在有效期内提交；问用户是否重发，不要自动连发 |
| 命令被 Agent 超时 | 把 `--expires` 调小（如 120/300），或让用户先确认在线再发 |
| E2EE 页面提示口令错误 | 口令不一致；让用户确认大小写/空格。服务端无法找回 |

## 安全红线

- 不把 `ASK4ME_API_KEY`、`ASK4ME_SERVERCHAN_SENDKEY`、`ASK4ME_E2EE_PASSWORD` 写进仓库、提交、日志或公开回答。
- 不把 E2EE 口令放进通知正文；口令必须另行传递。
- 一次只发一个请求；不要循环轰炸用户。
- 交互 URL 含访问 token，不要发到公开群组/issue。
- 用户拒绝或长时间不回复时，停止等待并如实说明，不要伪造结果。

## 服务端事实

- 默认是**公共试用服务**：可能不稳定、限流、停机或清理数据；不要放长期/敏感数据。正式使用请自建。
- 多用户模式：key = 租户，无账号；服务端不保存用户资料。
- `notify` 必须每请求携带；全局 ServerChan/Apprise 不生效。
- E2EE 是**按请求 opt-in**：`ASK4ME_E2EE_ENABLED=true` 只表示服务器允许，不会强制。
- 服务端只存密文和盐，不接触 E2EE 口令。
- 协议与测试向量见 <https://github.com/easychen/ask4me/blob/main/E2EE.md>。
