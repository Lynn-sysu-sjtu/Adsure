---
name: pkulaw-mcp-installer
description: 北京大学法宝 MCP 连接器安装助手（星瀚专用）。当用户表达安装北大法宝 MCP 连接器的意图时触发（如"安装北大法宝"、"配置北大法宝 MCP"、"pkulaw mcp"、"北大法宝连接器"等）。
author: 星瀚智能体大赛团队
---

## 功能概览

北大法宝 MCP 提供 9 个法律专业工具，覆盖法律法规检索、法条溯源、案例查询、AI 幻觉校验等场景：

1. **检索法律法规（语义）** — 自然语言语义检索法规全文，支持精确查询法条
2. **检索法律法规（关键词）** — 通过标题/关键词快速定位法规
3. **精准查找法条（关键词）** — 输入准确法条名称和条号，定位精确条文
4. **修正生成幻觉（法条校验）** — 智能分析上下文返回准确法条原文，防止 AI 幻觉法条
5. **法宝超链** — 自动识别法律元素生成超链，获取最新版本
6. **法条识别与溯源** — 从文本中识别法规名称和条款，返回标准名称和法条内容
7. **案号识别与溯源** — 精准提取案号，关联权威案例原文
8. **检索司法案例（关键词）** — 通过标题或正文关键词快速定位案例
9. **检索司法案例（语义）** — 自然语言描述案情，智能匹配权威案例

## 步骤

1. 先醒目提醒用户：
   > **⚠️ 重要提醒：本配置中的 Authorization Token 为「星瀚」专用密钥，请勿将本 Skill 或 Token 分享给他人使用。**
   > **目前处于测试阶段，总调用额度约 10,000 次，请合理使用。**

2. 向用户说明配置入口和手动配置方式：
   - 配置入口：对话框底部 →「连接第三方应用」→「管理连接器」→「自定义连接器」→「配置 MCP」
   - 配置文件路径：
     - Mac：`~/.workbuddy/mcp.json`
     - Windows：`C:\Users\<用户名>\.workbuddy\mcp.json`
   - 参考文档：https://mcp.pkulaw.com/docs?doc=mcp-integration#workbuddy

3. 询问用户是否希望我直接帮他修改 `mcp.json` 文件。如果用户同意，执行步骤 4；如果用户选择手动配置，结束。

4. 读取用户本地的 `mcp.json`（路径按系统判断：Mac 取 `~/.workbuddy/mcp.json`，Windows 取 `C:\Users\<用户名>\.workbuddy\mcp.json`）。
   - 如果文件不存在，新建一个包含 9 个北大法宝工具的 JSON。
   - 如果文件已存在，在现有的 `mcpServers` 对象中追加全部 9 个 `pkulaw-*` 节点，保留原有配置，避免覆盖。

5. 写入后，再次读取文件确认内容正确，并检查是否出现语法错误（如 JSON 解析失败）。

6. 告诉用户配置已写入，但是不同的工具使用的时候还会有区别，有的可能要关闭重启一下，有的比如你用的是workbuddy需要人工进入配置窗口点击信任一下，但 **必须手动完成最后一步「信任」**：
   - 打开 WorkBuddy 对话框底部 →「连接第三方应用」→「管理连接器」→「自定义连接器」
   - 对每个北大法宝 MCP 服务点击「信任」按钮（如图所示）
   - **只有点击「信任」后，才能正常获取法宝数据，否则连接器无法使用**
   - 再打开一个新的任务，直接提问就可以使用北大法宝mcp来查发条了，比如：
     - "帮我查一下合同法关于违约责任的相关法条"
   - 参考文档：https://mcp.pkulaw.com/docs?doc=mcp-integration#workbuddy

## 需要添加的 9 个配置节点

```json
{
  "mcpServers": {
    "pkulaw-law-search": {
      "name": "北大法宝-检索法律法规（语义）",
      "type": "streamableHttp",
      "description": "通过语义理解检索法律法规全文内容，支持精确查询特定法条（get_article）和自然语言语义检索（search_article），适用于法律咨询、合规审查、合同风险排查、立法追踪、学术研究等场景。",
      "url": "https://apim-gateway.pkulaw.com/mcp-law-search-service",
      "headers": {
        "Authorization": "Bearer YOUR_ACCESS_TOKEN"
      }
    },
    "pkulaw-law-keyword": {
      "name": "北大法宝-检索法律法规（关键词）",
      "type": "streamableHttp",
      "description": "通过精确标题或关键词快速定位匹配法规信息。",
      "url": "https://apim-gateway.pkulaw.com/mcp-law",
      "headers": {
        "Authorization": "Bearer YOUR_ACCESS_TOKEN"
      }
    },
    "pkulaw-fatiao-keyword": {
      "name": "北大法宝-精准查找法条（关键词）",
      "type": "streamableHttp",
      "description": "输入准确法条名称和条号，快速定位精确条文内容。",
      "url": "https://apim-gateway.pkulaw.com/mcp-fatiao",
      "headers": {
        "Authorization": "Bearer YOUR_ACCESS_TOKEN"
      }
    },
    "pkulaw-citation-validator": {
      "name": "北大法宝-修正生成幻觉（法条校验）",
      "type": "streamableHttp",
      "description": "智能分析上下文返回准确法条原文，防止AI幻觉法条。",
      "url": "https://apim-gateway.pkulaw.com/pku_citation_validator",
      "headers": {
        "Authorization": "Bearer YOUR_ACCESS_TOKEN"
      }
    },
    "pkulaw-doc-link": {
      "name": "北大法宝-法宝超链",
      "type": "streamableHttp",
      "description": "自动识别法律元素生成超链，获取最新版本。",
      "url": "https://apim-gateway.pkulaw.com/add-doc-link",
      "headers": {
        "Authorization": "Bearer YOUR_ACCESS_TOKEN"
      }
    },
    "pkulaw-law-recognition": {
      "name": "北大法宝-法条识别与溯源",
      "type": "streamableHttp",
      "description": "从文本中识别法规名称和条款，返回标准名称和法条内容。",
      "url": "https://apim-gateway.pkulaw.com/law_recognition",
      "headers": {
        "Authorization": "Bearer YOUR_ACCESS_TOKEN"
      }
    },
    "pkulaw-case-number-recognition": {
      "name": "北大法宝-案号识别与溯源",
      "type": "streamableHttp",
      "description": "精准提取案号，关联权威案例原文。",
      "url": "https://apim-gateway.pkulaw.com/case_number_recognition",
      "headers": {
        "Authorization": "Bearer YOUR_ACCESS_TOKEN"
      }
    },
    "pkulaw-case-keyword": {
      "name": "北大法宝-检索司法案例（关键词）",
      "type": "streamableHttp",
      "description": "通过标题或正文关键词快速精准定位案例。",
      "url": "https://apim-gateway.pkulaw.com/mcp-case",
      "headers": {
        "Authorization": "Bearer YOUR_ACCESS_TOKEN"
      }
    },
    "pkulaw-case-search": {
      "name": "北大法宝-检索司法案例（语义）",
      "type": "streamableHttp",
      "description": "自然语言描述案情，智能匹配司法案例库权威案例，告别幻觉案例。",
      "url": "https://apim-gateway.pkulaw.com/mcp-case-search-service",
      "headers": {
        "Authorization": "Bearer YOUR_ACCESS_TOKEN"
      }
    }
  }
}
```

## 注意事项
- 绝对不要覆盖用户已有的其他 MCP 配置（如企查查、天眼查等）。
- 如果某个 `pkulaw-*` 节点已存在，保留现有值，跳过重复添加。
- 写入后如果发现 JSON 格式错误（如逗号缺失、括号不匹配），立即尝试修复并重新写入。
- 如果用户手动配置，务必提醒：配置写入后，还需要在「自定义连接器」中对每个北大法宝服务点击「信任」才能正常使用。
