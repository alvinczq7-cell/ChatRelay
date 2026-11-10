# ChatRelay · 微信 → AI（MCP）

在你的授权下，让 Claude / Codex / Cursor 能**只读**访问你本机的微信聊天记录与文件。
全程本地运行，不上传任何内容。已在 **微信 4.2.0.13 / Windows 11** 上验证通过。

> **只用于你本人账号、你本机的数据。** 不要用它读取、监控、跟踪他人的微信。
> 首次运行前须执行 `python wxcore/consent.py accept` 确认使用须知，否则服务会拒绝解密。

## 原理
1. 从 `Weixin.dll` 提取内部 XOR 密钥；从微信进程内存定位口令；`口令 XOR 密钥 → PBKDF2(256000) → 数据库密钥`。
2. 用该密钥解密本地 WCDB（SQLCipher4）数据库，zstd 解压消息内容。
3. 把会话、联系人、消息建成本地可搜索索引，通过 MCP 暴露给 AI。

数据库里**不写入、不改动**微信；只读取你自己账号的本地文件。

## 依赖与确认
- Python 3.11+，微信正在运行并已登录。
- `pip install cryptography zstandard "mcp<2"`
- 首次运行前：`python wxcore/consent.py accept`（确认你读取的是本人数据；撤销用 `revoke`）。

## 文件
- `wx.py` — 密钥提取（verify_key.py）之上的解密 / zstd 封装
- `verify_key.py` — 密钥提取与数据库解密核心
- `store.py` — 解密、名称解析、消息渲染、本地全文索引
- `consent.py` — 一次性使用须知确认门（解密前的良性闸门）
- `mcp_server.py` — MCP 服务（工具见下）
- 生成物都在 `%LOCALAPPDATA%\ChatRelay\`：`passphrase.hex`（密钥缓存）、`dec_*.db`（解密副本）、`index.db`（搜索索引）

## MCP 工具
| 工具 | 作用 |
|---|---|
| `list_sessions(limit)` | 最近会话（名称/是否群/未读/时间） |
| `get_history(conversation, limit, before)` | 读某会话消息（名称或 id，可翻页） |
| `search(keyword, limit, conversation?)` | 全文搜索聊天记录 |
| `list_contacts(query, limit)` | 查联系人 |
| `list_files(limit)` | 最近收到的文件（含本地路径） |
| `refresh()` | 重新解密并增量更新索引 |

## 接入 Claude

### Claude Desktop
编辑 `%APPDATA%\Claude\claude_desktop_config.json`，加入（把路径换成本项目实际路径）：
```json
{
  "mcpServers": {
    "chatrelay": {
      "command": "python",
      "args": ["<项目路径>\\wxcore\\mcp_server.py"]
    }
  }
}
```
重启 Claude Desktop 即可。

### Claude Code（命令行）
```bash
claude mcp add chatrelay -- python <项目路径>\wxcore\mcp_server.py
```

接好后可以直接问：「列出我最近的微信会话」「搜索聊天里提到某关键词的消息」「某联系人最近跟我说了什么」「我最近收到哪些 PDF」。

## 隐私与边界
- 只读你本人账号、你本机的数据；不发消息、不改微信、不联网。
- 解密副本与索引是明文，保存在 `%LOCALAPPDATA%\ChatRelay\`；不需要时可删除整个目录。
- 解密依赖读取微信进程内存，属于逆向手段，可能违反微信使用条款、存在账号风险，仅供你在本人设备上处理本人数据。
