# Ask4Me Skill

让 Agent 通过 [Ask4Me](https://github.com/easychen/ask4me) 请真人确认、选择或填表，并等待结果。

- **默认公共试用服务**：`https://ask.app.ft07.com`，邀请码 `askd-2026`。
- **装完即用**：首次运行自动生成并保存 API key，不需要手动 keygen。
- **不需要先准备 SendKey**：没配 SendKey 时走链接模式——把交互链接发给用户，用户提交后 `wait` 拿结果。
- 配了 ServerChan SendKey 就自动推送；当前镜像不支持 Apprise。
- E2EE 可选；开启后正文/表单/回答在客户端加密，页面输入口令解密。
- **试用不稳定**：可能限流、停机或清理数据；正式使用请自建：<https://github.com/easychen/ask4me>。

## 安装

```bash
npx skills add easychen/skills --skill ask4me
```

或直接读 [`SKILL.md`](./SKILL.md)。

## 快速开始（零配置）

```bash
# 1. 创建请求；没有 key 会自动生成，没有 SendKey 会返回链接
node scripts/ask4me.mjs create \
  --title "确认发布" \
  --body "请确认是否发布。" \
  --mcd $':::buttons\n- [OK](ok)\n- [取消](cancel)\n:::'
```

输出类似：

```json
{
  "request_id": "req_xxx",
  "interaction_url": "https://ask.app.ft07.com/r/...",
  "mode": "web"
}
```

把 `interaction_url` 发给用户；用户提交后：

```bash
# 2. 等待并拿结果
node scripts/ask4me.mjs wait --request-id req_xxx
```

## 可选配置

```bash
# 有 ServerChan SendKey 就自动推送；不设就是链接模式
export ASK4ME_SERVERCHAN_SENDKEY="SCT..."   # 或 sctp...

# E2EE 口令；不要提交到仓库
export ASK4ME_E2EE_PASSWORD="和回答者另行约定的口令"

# 自有服务器（可选）
export ASK4ME_BASE_URL="https://your-domain.com"
export ASK4ME_INVITE="your-invite"
```

不要把 key / SendKey / 口令提交到仓库或发到公开频道。

## 自动更新

脚本每次 `create` / `ask` / `test` 会检查一次 GitHub 版本，最多每 24 小时一次；网络失败不阻塞。发现新版本会提示：

```text
[Ask4Me] 发现 skill 新版本 x.y.z（当前 a.b.c）。
[Ask4Me] 更新：npx skills add easychen/skills --skill ask4me
```

手动查版本：`node scripts/ask4me.mjs version`。  
关闭检查：`ASK4ME_NO_UPDATE_CHECK=1` 或 `--no-update-check`。

## 给用户的一段话

见 [`INSTALL_PROMPT.md`](./INSTALL_PROMPT.md)，可直接复制给其他 Agent。
