# 复制给 Agent 的接入说明

把下边整段复制给用户的 Agent。默认走公共试用服务，装完直接可用，不需要先搭服务器。

## 推荐版

```text
请安装 Ask4Me skill，并按它的 SKILL.md 引导我使用：
npx skills add easychen/skills --skill ask4me
如果 npx 不可用，就执行：
git clone --depth 1 https://github.com/easychen/skills /tmp/easychen-skills
然后阅读 /tmp/easychen-skills/ask4me/SKILL.md 并照做。

默认用公共试用服务 https://ask.app.ft07.com（邀请码 askd-2026），不要先让我搭服务器。
装完直接创建请求，把交互链接发给我，我提交后你取结果。
这是试用服务，可能不稳定、限流或清理数据；如果长期使用或遇到问题，再建议我自建：https://github.com/easychen/ask4me

不需要一开始就让我配置 ServerChan SendKey；没有 SendKey 就用链接模式。
不要把我的 API key、SendKey、E2EE 口令写进仓库、日志或公开文件。
```

## 更短的版本

```text
请安装 Ask4Me skill：
npx skills add easychen/skills --skill ask4me

默认公共试用服务 https://ask.app.ft07.com，邀请码 askd-2026，装完直接用，不要先让我搭服务器。按 SKILL.md 的零配置流程：创建请求 → 把链接发给我 → 我提交后取结果。试用不稳定，长期使用再建议自建。不要把 key、SendKey、口令写进仓库或日志。
```

## 想用自己的服务器

```text
请安装 Ask4Me skill：
npx skills add easychen/skills --skill ask4me

我想用自己的 Ask4Me 服务器。请按 https://github.com/easychen/ask4me 的 docs/ubuntu-deploy.md 帮我部署，然后把 ASK4ME_BASE_URL 指到我的域名，用我自己的邀请码生成 key。部署前不要用公共试用服务代替。
```

## 没有 npx 的环境

```text
请先执行：
git clone --depth 1 https://github.com/easychen/skills /tmp/easychen-skills
然后完整阅读 /tmp/easychen-skills/ask4me/SKILL.md，按零配置流程帮我用 Ask4Me。
默认公共试用服务 https://ask.app.ft07.com，邀请码 askd-2026；装完直接用，不要先让我搭服务器；试用不稳定，长期再自建。
```
