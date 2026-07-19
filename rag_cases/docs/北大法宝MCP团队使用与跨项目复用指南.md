# 北大法宝 MCP 团队使用与跨项目复用指南

## 一、Git 推送时应包含什么

应将以下文件提交并推送：

- `.codex/config.toml`：本项目四个北大法宝 MCP 服务的 Codex 配置；
- `.env.example`：只声明变量名，不包含真实 Token；
- `scripts/configure_pkulaw_mcp_token.sh`：macOS 隐藏输入 Token 的辅助脚本；
- `docs/北大法宝MCP接入.md`：本项目快速接入说明；
- `docs/北大法宝MCP团队使用与跨项目复用指南.md`：本文；
- `tools/pkulaw_mcp/`：可复制到其他法律 AI 项目的通用安装器；
- `tests/test_pkulaw_mcp_config.py` 和 `tests/test_install_pkulaw_mcp.py`：配置回归测试。

不得提交：

- `.env`；
- 真实 Token、Cookie、Authorization 请求头；
- 个人账号导出的浏览器配置或登录态。

建议每名队友使用自己获授权的 Token，或使用管理员为该项目创建的团队 Token。不要在群聊、Issue、PR 描述或代码评审中粘贴 Token。

## 二、队友首次使用

### 1. 克隆指定分支

```bash
git clone --branch codex/ads-penalty-rag-pipeline \
  https://github.com/Lynn-sysu-sjtu/Adsure.git
cd Adsure
```

如果队友已经有本地仓库：

```bash
git fetch origin
git switch codex/ads-penalty-rag-pipeline
git pull --ff-only
```

### 2. 信任项目

Codex 只会加载受信任项目中的 `.codex/config.toml`。队友首次打开仓库时，应确认信任该项目，然后重启 Codex。

### 3. 获取北大法宝 Token

在[北大法宝 MCP 控制台](https://mcp.pkulaw.com/console/apps)创建或加入获授权的应用，取得 Token。不要使用仓库中的占位符，也不要把 Token 写进 `.codex/config.toml`。

### 4. 让 Codex 读取 Token

macOS：

```bash
zsh scripts/configure_pkulaw_mcp_token.sh
```

输入不会显示。脚本通过 `launchctl` 向之后启动的应用提供 `PKULAW_MCP_TOKEN`。完全退出 Codex 后重新打开；macOS 注销或重启后如变量失效，重新运行脚本。

Linux 或 Codex CLI：

```bash
read -rs PKULAW_MCP_TOKEN
export PKULAW_MCP_TOKEN
codex
```

Windows 或受企业策略管理的设备，应由管理员使用安全的系统环境变量或凭证管理方式注入 `PKULAW_MCP_TOKEN`，不要把 Token 固化到 Git 文件。

### 5. 验证 MCP

在 Codex 中输入 `/mcp`，或打开“设置 > MCP servers”，确认以下四项已经连接：

- `pkulaw-law-semantic`
- `pkulaw-law-keyword`
- `pkulaw-case-semantic`
- `pkulaw-case-keyword`

也可在终端执行本地检查：

```bash
python3 tools/pkulaw_mcp/install.py --check
```

检查命令不访问网络，也不会打印 Token。

### 6. 功能验收

依次发起：

1. `用北大法宝关键词检索现行有效的《中华人民共和国广告法》，返回效力状态、发布日期和来源链接。`
2. `用北大法宝语义检索互联网广告中普通食品使用医疗用语涉及的现行法规。`
3. `用北大法宝案例关键词检索“互联网广告 虚假宣传”，返回案号、法院、裁判日期和原文链接。`
4. `用北大法宝案例语义检索：直播带货对普通食品宣称具有疾病治疗效果的相似案件。`

验收结果必须带可回溯来源；无法核验的结果不得直接进入生产 RAG。

## 三、在其他法律 AI 项目中复用

把整个 `tools/pkulaw_mcp/` 目录复制到目标项目，然后在目标项目根目录运行：

```bash
python3 tools/pkulaw_mcp/install.py
```

安装器会：

1. 创建或读取目标项目的 `.codex/config.toml`；
2. 保留文件中的模型、沙箱、Hook 和其他 MCP 配置；
3. 只追加缺失的北大法宝服务；
4. 已存在的同名服务保持原值，不覆盖；
5. 不接收、不保存、不输出 Token；
6. 原子写入配置，重复执行不会生成重复节点。

只需要法规检索：

```bash
python3 tools/pkulaw_mcp/install.py --services law
```

只需要案例检索：

```bash
python3 tools/pkulaw_mcp/install.py --services case
```

指定其他项目路径：

```bash
python3 tools/pkulaw_mcp/install.py --project /path/to/legal-ai-project
```

写入前预览：

```bash
python3 tools/pkulaw_mcp/install.py --dry-run
```

安装后，由每个项目自行安全设置 `PKULAW_MCP_TOKEN` 并重启 Codex。

## 四、项目中的数据使用边界

- 法规检索结果可用于确定现行法条、效力状态和监管依据，但引用时仍应保留来源链接。
- 司法案例用于裁判观点、争议焦点和法律适用研究，不能冒充行政处罚事实。
- 广告行政处罚案例仍优先采用市场监管总局、地方市场监管部门和信用中国的公开材料。
- MCP 结果进入案例库前，必须保留 `source_url` 和原文回溯路径；来源不完整的记录保持候选态和待复核状态。
- 不得高频批量调用、绕过登录或验证码，也不得访问非公开接口。

## 五、常见问题

| 现象 | 排查方法 |
| --- | --- |
| `/mcp` 看不到北大法宝 | 确认分支已更新、项目已信任、`.codex/config.toml` 存在，并完全重启 Codex |
| 服务存在但返回 `401` | `PKULAW_MCP_TOKEN` 未被新启动的 Codex 进程继承，或 Token 已失效 |
| `--check` 提示 Token 未设置 | 在同一终端导出变量后启动 Codex，macOS 桌面端可运行项目辅助脚本 |
| 其他 MCP 配置消失 | 不要手工覆盖整个 `config.toml`；使用通用安装器追加缺失节点 |
| 检索结果不能入库 | 检查真实来源、全文回溯、时效状态和人工复核字段，未核验内容保持候选态 |
