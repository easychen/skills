# Ask4Me Skill

让 Agent 通过 [Ask4Me](https://github.com/easychen/ask4me) 请真人确认、选择或填表，并等待结果。

- **默认公共试用服务**：`https://ask.app.ft07.com`，邀请码 `askd-2026`。
- **装完即用**：首次运行自动生成并保存 API key，不需要手动 keygen。
- **唯一需要配置的是 ServerChan SendKey**：没有就去 <https://sct.ftqq.com/> 微信扫码登录，复制 SendKey。
- E2EE 可选；开启后正文/表单/回答在客户端加密，页面输入口令解密。
- **试用不稳定**：可能限流、停机或清理数据；正式使用请自建：<https://github.com/easychen/ask4me>。

## 安装

```bash
npx skills add easychen/skills --skill ask4me
```

或直接读 [`SKILL.md`](./SKILL.md)。

## 配置

```bash
# 必填：ServerChan SendKey
export ASK4ME_SERVERCHAN_SENDKEY="SCT..."   # 或 sctp...

# 可选：E2EE 口令（不要提交到仓库）
export ASK4ME_E2EE_PASSWORD="和回答者另行约定的口令"

# 可选：自有服务器
# export ASK4ME_BASE_URL="https://your-domain.com"
# export ASK4ME_INVITE="your-invite"
```

`ASK4ME_API_KEY` 不用手动设置；第一次运行会自动生成并保存到 `~/.config/ask4me/config.json`（权限 600）。

不要把 key / SendKey / 口令提交到仓库或发到公开频道。

## 使用

```bash
# 测试
node scripts/ask4me.mjs ask --title "Ask4Me 配置测试" --body "收到请点 OK" --expires 3600

# 按钮
node scripts/ask4me.mjs ask --title "确认发布" --body "请确认" \
  --mcd $':::buttons\n- [OK](ok)\n- [取消](cancel)\n:::'

# 输入
node scripts/ask4me.mjs ask --title "备注" --body "请填写" \
  --mcd $':::input name="note" label="备注" submit="提交"\n:::'

# JSON Forms
node scripts/ask4me.mjs ask --title "填表" --body "请填写" --jsonforms ./form.json
```

结果以 JSON 打到 stdout；E2EE 开启时自动解密 `data.text` / `data.payload`。

## 自动更新

脚本每次 `ask` / `create` / `test` 会检查一次 GitHub 版本，最多每 24 小时一次；网络失败不阻塞。发现新版本会提示：

```text
[Ask4Me] 发现 skill 新版本 x.y.z（当前 a.b.c）。
[Ask4Me] 更新：npx skills add easychen/skills --skill ask4me
```

手动查版本：`node scripts/ask4me.mjs version`。  
关闭检查：`ASK4ME_NO_UPDATE_CHECK=1` 或 `--no-update-check`。

## 给用户的一段话

见 [`INSTALL_PROMPT.md`](./INSTALL_PROMPT.md)，可直接复制给其他 Agent。
