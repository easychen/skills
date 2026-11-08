# 复制给 Agent 的接入说明

把下边整段复制给用户的 Agent。默认走公共试用服务；用户只需要准备一个 ServerChan SendKey。

## 推荐版

```text
请安装 Ask4Me skill，并按它的 SKILL.md 引导我使用：
npx skills add easychen/skills --skill ask4me
如果 npx 不可用，就执行：
git clone --depth 1 https://github.com/easychen/skills /tmp/easychen-skills
然后阅读 /tmp/easychen-skills/ask4me/SKILL.md 并照做。

默认用公共试用服务 https://ask.app.ft07.com（邀请码 askd-2026），不要先让我搭服务器。
装完先问我要 ServerChan SendKey；如果我没有，引导我去 https://sct.ftqq.com/ 微信扫码登录，复制 SendKey（SCT... 或 sctp...）。没有 SendKey 不要创建请求。

拿到 SendKey 后，发一条测试请求让我点 OK；确认链路正常，再开始正式使用。
这是试用服务，可能不稳定、限流或清理数据；长期使用或遇到问题，再建议我自建：https://github.com/easychen/ask4me

不要把 SendKey、API key、E2EE 口令写进仓库、日志或公开文件。问我是否开启端到端加密；如果开启，口令要另行告诉回答者。
```

## 更短的版本

```text
请安装 Ask4Me skill：
npx skills add easychen/skills --skill ask4me

默认公共试用服务 https://ask.app.ft07.com，邀请码 askd-2026，不要先让我搭服务器。
装完问我要 ServerChan SendKey；没有就引导我去 https://sct.ftqq.com/ 注册/登录并复制 SendKey。没有 SendKey 不要发请求。
然后发一条测试请求让我点 OK。试用不稳定，长期使用再建议自建。不要把 key、SendKey、口令写进仓库或日志。
```

## 想用自己的服务器

```text
请安装 Ask4Me skill：
npx skills add easychen/skills --skill ask4me

我想用自己的 Ask4Me 服务器。请按 https://github.com/easychen/ask4me 的 docs/ubuntu-deploy.md 帮我部署，然后把 ASK4ME_BASE_URL 指到我的域名，用我自己的邀请码生成 key。部署前不要用公共试用服务代替。
```
