# 复制给 Agent 的接入说明

把下边整段复制给你的 Agent。把 `{{INVITE_CODE}}` 换成 Ask4Me 服务提供者给你的邀请码；不想暴露邀请码，就保留占位符，让 Agent 问你。

## 推荐版（不带 SendKey，Agent 会问）

```text
请帮我接入 Ask4Me（一个 Human-in-the-Loop 服务），按以下步骤做：

1. 安装 skill：
   npx skills add easychen/skills --skill ask4me
   如果 npx 不可用，就执行：
   git clone --depth 1 https://github.com/easychen/skills /tmp/easychen-skills
   然后阅读 /tmp/easychen-skills/ask4me/SKILL.md 并照做。

2. 我的 Ask4Me 服务地址：https://ask.app.ft07.com
   邀请码：{{INVITE_CODE}}
   如果邀请码还是占位符，直接问我。

3. 按 SKILL.md 引导我完成配置：
   - 用邀请码生成 ASK4ME_API_KEY；
   - 问我要 ServerChan SendKey（没有就教我去 https://sct.ftqq.com/ 申请）；
   - 问我是否启用端到端加密；如果启用，让我设一个口令，并提醒我口令要另行告诉回答者，不能放在通知里；
   - 配好后发一条测试请求，让我在手机上点 OK。

4. 测试通过后，以后需要我确认、选择或填表时，用 Ask4Me 发请求并等待结果；一次只发一个，标题和正文写清楚。

5. 安全：不要把我给你的邀请码、API key、SendKey、E2EE 口令写进仓库、日志、公开文件或通知正文；交互链接也不要发到公开群组。不要循环重发请求。
```

## 带邀请码的短版

如果邀请码可以直接公开（比如公开试用），用这段更短：

```text
请安装并使用 Ask4Me skill：
npx skills add easychen/skills --skill ask4me

服务地址：https://ask.app.ft07.com
邀请码：{{INVITE_CODE}}

请读取 skill 的 SKILL.md，引导我配置 ServerChan SendKey 和可选的 E2EE 口令，然后发一条测试请求让我点 OK。之后需要我确认/选择/填表时用它，一次只发一个。不要把 key、SendKey、口令写进仓库或日志。
```

## 没有 npx 的环境

```text
请先执行：
git clone --depth 1 https://github.com/easychen/skills /tmp/easychen-skills
然后完整阅读 /tmp/easychen-skills/ask4me/SKILL.md，按里面的步骤帮我配置和测试 Ask4Me。
服务地址：https://ask.app.ft07.com
邀请码：{{INVITE_CODE}}
```
