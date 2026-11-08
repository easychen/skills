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
    required: true
    desc: a4m_<invite>_<random>；用 keygen 生成，不要提交到仓库
  - key: ASK4ME_SERVERCHAN_SENDKEY
    required: true
    desc: 每次请求的 ServerChan SendKey；也可用 SERVERCHAN_SENDKEY
  - key: ASK4ME_E2EE_PASSWORD
    required: false
    desc: 可选 E2EE 口令；不要写入仓库、日志或通知正文
---

# Ask4Me · 让人工确认 / 选择 / 填表

Ask4Me 是一个已部署好的 Human-in-the-Loop 服务：你发一个请求，服务把交互链接推到真人的手机（ServerChan），对方点按钮或填表后，你的命令拿到最终结果。

**这是一个纯客户端 skill，不需要部署服务。** 默认用我们提供的公共试用服务器，开箱即用；多用户模式下每个用户用自己的 API key。

## 默认：先用公共试用服务

- 服务地址：`https://ask.app.ft07.com`
- 邀请码：`askd-2026`
- 这是**公共试用服务**：可能不稳定、限流、停机或清理数据；**不要放长期/敏感数据**，也不要做关键业务依赖。
- 先让用户用试用服务跑通；如果用户需要长期使用、数据不能丢，或遇到不稳定问题，再引导他自建独立服务器：
  - <https://github.com/easychen/ask4me>
  - 部署教程：<https://github.com/easychen/ask4me/blob/main/docs/ubuntu-deploy.md>

**不要一上来就让用户自建服务器**——先用试用服务，门槛最低；自建是升级路径，不是前置条件。

## 自动更新检查

脚本在每次 `ask` / `test` 启动时会检查一次 GitHub 上的 skill 版本（**最多每 24 小时一次**，网络失败自动忽略，不阻塞请求）。发现新版本会在 stderr 提示：

```text
[Ask4Me] 发现 skill 新版本 x.y.z（当前 a.b.c）。
[Ask4Me] 更新：npx skills add easychen/skills --skill ask4me
```

- 手动查版本：`node scripts/ask4me.mjs version`
- 关闭检查：`ASK4ME_NO_UPDATE_CHECK=1` 或 `--no-update-check`
- 不要自动替用户执行更新；提示后让用户决定。

## 先做环境检查

需要 Node.js 18+。脚本在技能目录的 `scripts/ask4me.mjs`，零依赖。

```bash
node -v
```

如果低于 18，先让用户升级 Node，不要继续。

## 第一次配置（按顺序问用户）

**不要一次把所有问题抛给用户；按下面步骤逐项完成。**

### 1. 服务地址

默认直接用 `https://ask.app.ft07.com`，不需要问。只有用户明确说自己有独立服务器时，才改 `ASK4ME_BASE_URL`。

### 2. 邀请码 → API key

默认邀请码是 `askd-2026`，直接生成：

```bash
node scripts/ask4me.mjs keygen
```

输出形如 `a4m_askd-2026_<32位hex>`。把它保存到**当前项目的环境变量** `ASK4ME_API_KEY`。

如果用户有自己的邀请码，才用 `--invite <邀请码>` 覆盖。

安全要求：

- 不要把完整 key 回显到最终回答、日志或公开文件；
- 不要写进仓库里的 `.env` 并提交；
- 如果必须让用户看到，提醒他这是租户凭证，等同于密码。
- `askd-2026` 是公开试用码，配额有限；不要拿它做长期/敏感业务。

### 3. ServerChan 通知渠道

多用户服务器**要求每次请求都带 `notify`**，没有全局兜底。问用户要 ServerChan SendKey：

- 没有的话，让用户去 <https://sct.ftqq.com/> 申请；
- 保存到 `ASK4ME_SERVERCHAN_SENDKEY`（也兼容 `SERVERCHAN_SENDKEY`）；
- 不要 echo / log SendKey。

### 4. 是否开启 E2EE（可选）

问用户：“这次/以后要不要端到端加密？”

- 不开启：不设置 `ASK4ME_E2EE_PASSWORD`，或加 `--no-e2ee`。
- 开启：让用户设一个口令，保存到 `ASK4ME_E2EE_PASSWORD`。**口令只用于加密，不会发给服务端。**
- 提醒用户：口令必须**另行**告知回答者，不能放在通知里；忘记口令数据不可恢复。

### 5. 发一条测试

在用户确认可以发推送后：

```bash
node scripts/ask4me.mjs test --expires 300
```

等用户在手机上点 **OK**。返回 `user.submitted` / `action=ok` 即配置成功。若失败，按下面的“排错”处理。

测试时脚本会打印公共试用服务器的提醒；请把这个提醒转告用户：**试用服务不稳定，正式使用请自建**。

## 试用 vs 自建

| | 公共试用服务 | 自建服务器 |
|---|---|---|
| 地址 | `https://ask.app.ft07.com` | 自己的域名 |
| 邀请码 | `askd-2026` | 自己配置 |
| 数据 | 可能清理，不保证保留 | 自己控制 |
| 稳定性 | 不保证，可能限流/停机 | 自己负责 |
| 适合 | 试用、体验、轻量任务 | 长期使用、敏感/关键任务 |

自建入口：<https://github.com/easychen/ask4me>（Docker / Ubuntu 部署教程见仓库 `docs/ubuntu-deploy.md`）。

先用试用服务跑通，再决定是否自建；不要在用户还没体验前就要求他搭服务器。

## 正式使用

### 按钮 / 审批

```bash
node scripts/ask4me.mjs ask \
  --title "确认发布 v1.2.3" \
  --body "请确认是否发布到生产环境。" \
  --mcd $':::buttons\n- [OK](ok)\n- [取消](cancel)\n:::' \
  --expires 600
```

### 文字输入

```bash
node scripts/ask4me.mjs ask \
  --title "补充说明" \
  --body "请填写发布备注。" \
  --mcd $':::input name="note" label="备注" submit="提交"\n:::' \
  --expires 600
```

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
node scripts/ask4me.mjs ask \
  --title "填写信息" \
  --body "请填写后提交。" \
  --jsonforms /tmp/form.json \
  --expires 600
```

脚本会把结果 JSON 打到 stdout：

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

## 对用户怎么说

发请求后，用一句简短的话告诉用户：

> 已经把确认请求推到你手机了，请点 OK（或打开链接提交）。我这边会等你的结果。

不要把 SendKey、API key、E2EE 口令、完整交互 URL 发到公开频道。交互 URL 本身是访问凭证；如果通知失败，可以私下发给用户。

## 排错

| 现象 | 处理 |
|---|---|
| `401 Unauthorized` | key 无效或邀请码被更换；重新 `keygen`，更新 `ASK4ME_API_KEY` |
| `400 notify is required` | 没有传 ServerChan SendKey；检查 `ASK4ME_SERVERCHAN_SENDKEY` |
| `notify.failed` | SendKey 无效/被限流；让用户检查 ServerChan。当前服务器镜像不带 Apprise，不要传 `apprise_urls` |
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
