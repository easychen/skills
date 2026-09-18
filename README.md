# Skills

个人 Agent Skills 统一目录。所有 skill 都遵循 [Agent Skills](https://agentskills.io) 规范（含 `SKILL.md`），可直接被 Claude Code 等支持 skill 的 Agent 安装使用。

## 目录结构

```
skills/
├── sudoboard/      # SudoBoard 数据看板
├── serverchan/     # Server 酱消息推送
└── opc/            # OPC 一人公司方法论（9 个子 skill）
```

## Skill 索引

### sudoboard

- **目录**：[`sudoboard/`](./sudoboard/)
- **来源**：[SudoBoard](https://github.com/easychen/SudoBoard) 项目内置 skill
- **说明**：为当前项目创建 SudoBoard 数据看板（可视化数据面板/电视大屏）：配置数据源、编写 JSX 展示模板、本地高保真预览，确认后一键同步到 SudoBoard App 或部署到 Cloudflare。

### serverchan

- **目录**：[`serverchan/`](./serverchan/)
- **来源**：[easychen/serverchan-skill](https://github.com/easychen/serverchan-skill)
- **说明**：通过 Server 酱（方糖）向微信/App 推送消息通知，支持标题、Markdown 正文及 tags/short/channel 等可选参数，自动识别 SCT / SC3 SendKey。

### opc（一人公司方法论）

- **目录**：[`opc/`](./opc/)
- **来源**：[easychen/opc-methodology](https://github.com/easychen/opc-methodology) 的 `skills/` 目录
- **子 skill**：

| Skill | 说明 |
|---|---|
| [`opc-orchestrator`](./opc/opc-orchestrator/) | 编排完整的一人公司工作流，串联所有 OPC skill |
| [`opc-niche-positioning`](./opc/opc-niche-positioning/) | 市场测绘 + 客户素描，寻找并定位利基市场 |
| [`opc-value-proposition`](./opc/opc-value-proposition/) | 为候选客群设计价值主张并选出最优方案 |
| [`opc-business-model-design`](./opc/opc-business-model-design/) | 精益画布 + 简化商业模式画布设计商业模式 |
| [`opc-mvp-designer`](./opc/opc-mvp-designer/) | 定义最小可行实验与 MVP |
| [`opc-conversion-loop`](./opc/opc-conversion-loop/) | 设计从触达、获客到成交的转化循环 |
| [`opc-asset-ops`](./opc/opc-asset-ops/) | 把可重复产出转化为可复利的资产 |
| [`opc-dashboard-review`](./opc/opc-dashboard-review/) | 轻量指标复盘经营健康度与瓶颈分析 |
| [`opc-resource-audit`](./opc/opc-resource-audit/) | 8 大类盘点创始人资源 |

## 新增 Skill

把新的 skill 目录（含 `SKILL.md`）直接放进本仓库根目录或对应分组目录下，并在上面的索引里加一行即可。
