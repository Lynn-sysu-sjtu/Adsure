# 北大法宝 MCP 接入

本项目通过项目级 `.codex/config.toml` 接入四个只读检索服务：

- `pkulaw-law-semantic`：法律法规语义检索
- `pkulaw-law-keyword`：法律法规关键词检索
- `pkulaw-case-semantic`：司法案例语义检索
- `pkulaw-case-keyword`：司法案例关键词检索

## 1. 获取并注入 Token

在[北大法宝 MCP 控制台](https://mcp.pkulaw.com/console/apps)创建应用并获取 Token。Token 不得写入仓库、`config.toml`、文档或脚本。

macOS 上运行：

```bash
zsh scripts/configure_pkulaw_mcp_token.sh
```

脚本会隐藏输入，并通过 `launchctl` 将 `PKULAW_MCP_TOKEN` 提供给之后启动的 Codex 进程。随后完全退出并重新启动 Codex，重新打开本项目。

其他系统应在启动 Codex 前设置同名环境变量。

## 2. 验证连接

在 Codex 中输入 `/mcp`，或打开“设置 > MCP servers”。四个 `pkulaw-*` 服务应显示为已连接。

可用以下请求做功能验收：

1. `用北大法宝关键词检索现行有效的《中华人民共和国广告法》，返回效力状态、发布日期、正文链接。`
2. `用北大法宝精确查找《中华人民共和国广告法》第九条，逐字返回条文并附来源。`
3. `用北大法宝案例关键词检索与“互联网广告 虚假宣传 行政处罚”相关的案例，返回案号、法院、裁判日期和原文链接。`
4. `用北大法宝案例语义检索：直播带货中对普通食品宣称治疗高血压引发争议的相似案件。`

## 3. 项目数据边界

- MCP 返回结果只作为检索证据，不自动进入生产 RAG。
- 入库前必须保留真实 `source_url` 和可回溯原文；无法核验的记录保持候选态。
- 司法案例不能替代行政处罚事实来源。广告行政处罚案例仍优先采用市场监管总局、地方市场监管部门和信用中国的公开材料。
- 不得批量高频调用、绕过登录或验证码，也不得抓取非公开接口。

官方入口：

- [北大法宝 MCP 平台](https://mcp.pkulaw.com/)
- [北大法宝 MCP 文档中心](https://mcp.pkulaw.com/docs)

团队成员从 Git 拉取后的完整步骤，以及在其他法律 AI 项目中的复用方式，见：

- [北大法宝 MCP 团队使用与跨项目复用指南](北大法宝MCP团队使用与跨项目复用指南.md)
- [通用安装器说明](../tools/pkulaw_mcp/README.md)
