# 复制给 Agent 的接入说明

把下边整段复制给你的 Agent。默认使用公共试用服务，不需要自己搭服务器；如果以后要长期使用，再自建。

## 推荐版（直接复制）

```text
请帮我接入 Ask4Me（一个 Human-in-the-Loop 服务），按以下步骤做：

1. 安装 skill：
   npx skills add easychen/skills --skill ask4me
   如果 npx 不可用，就执行：
   git clone --depth 1 https://github.com/easychen/skills /tmp/easychen-skills
   然后阅读 /tmp/easychen-skills/ask4me/SKILL.md 并照做。

2. 先用公共试用服务，不要自己搭服务器：
   服务地址：https://ask.app.ft07.com
   邀请码：askd-2026

   注意：这是试用服务，可能不稳定、限流或清理数据，不要放长期/敏感数据。
   如果以后要长期使用、数据不能丢，再引导我自建：https://github.com/easychen/ask4me

3. 按 SKILL.md 引导我完成配置：
   - 用默认邀请码生成 ASK4ME_API_KEY；
   - 问我要 ServerChan SendKey（没有就教我去 https://sct.ftqq.com/ 申请）；
   - 问我是否启用端到端加密；如果启用，让我设一个口令，并提醒我口令要另行告诉回答者，不能放在通知里；
   - 配好后发一条测试请求，让我在手机上点 OK。

4. 测试通过后，以后需要我确认、选择或填表时，用 Ask4Me 发请求并等待结果；一次只发一个，标题和正文写清楚。

5. skill 会在每次启动时检查一次 GitHub 版本（最多每天一次）。如果提示有新版本，告诉我运行：
   npx skills add easychen/skills --skill ask4me

6. 安全：不要把我给你的 API key、SendKey、E2EE 口令写进仓库、日志、公开文件或通知正文；交互链接也不要发到公开群组。不要循环重发请求。
```

## 更短的版本

```text
请安装 Ask4Me skill：
npx skills add easychen/skills --skill ask4me

默认用公共试用服务：https://ask.app.ft07.com，邀请码 askd-2026。
这是试用服务，不稳定；先试用，长期使用再自建。

请读取 skill 的 SKILL.md，引导我配置 ServerChan SendKey 和可选的 E2EE 口令，然后发一条测试请求让我点 OK。之后需要我确认/选择/填表时用它，一次只发一个。skill 有新版本时提醒我更新。不要把 key、SendKey、口令写进仓库或日志。
```

## 不想用试用服务、要自建

```text
请安装 Ask4Me skill：
npx skills add easychen/skills --skill ask4me

我想用自己的 Ask4Me 服务器，请先帮我按 https://github.com/easychen/ask4me 的 docs/ubuntu-deploy.md 部署，然后把 ASK4ME_BASE_URL 指到我的域名，再用我自己的邀请码生成 key。

在部署完成前，不要用公共试用服务代替。
```

## 没有 npx 的环境

```text
请先执行：
git clone --depth 1 https://github.com/easychen/skills /tmp/easychen-skills
然后完整阅读 /tmp/easychen-skills/ask4me/SKILL.md，按里面的步骤帮我配置和测试 Ask4Me。
默认用公共试用服务 https://ask.app.ft07.com，邀请码 askd-2026；这是试用服务，不稳定，长期使用再自建。
```
