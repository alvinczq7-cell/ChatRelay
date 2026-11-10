# ChatRelay

让 AI(Claude / Codex / Cursor 等,通过 MCP)在你的授权下**只读**访问你本机的微信聊天记录与文件。
全程本地运行,不上传任何内容。已在 **微信 4.2.0.13 / Windows 11** 上验证通过。

> 核心工具在 [`wxcore/`](wxcore/)。完整说明见 **[wxcore/README.md](wxcore/README.md)**。

## 能做什么
- 列出会话、读某会话的历史消息、全文搜索聊天记录、查联系人、列出收到的文件。
- 把微信数据变成 AI 可查询的本地知识库——例如「搜一下聊天里关于某主题的消息」「某群最近聊了什么」。

## 原理(简述)
1. 从 `Weixin.dll` 提取内部 XOR 密钥;从微信进程内存定位口令;`口令 XOR 密钥 → PBKDF2(256000) → 数据库密钥`。
2. 用该密钥解密本地 WCDB(SQLCipher4)数据库,zstd 解压消息内容。
3. 建成本地索引,通过 MCP 暴露给 AI(查询只读索引,不解密;解密只发生在 `refresh`)。

## 快速开始
```bash
pip install cryptography zstandard "mcp<2"
# 微信需正在运行并已登录;首次会扫描进程内存提取密钥(约 1-2 分钟,之后缓存)
claude mcp add chatrelay -- python <项目路径>/wxcore/mcp_server.py
```
详见 [wxcore/README.md](wxcore/README.md)。

## ⚠️ 重要声明:风险与边界
- **仅限处理你本人拥有、或你本人在自有设备上有权访问的数据。** 不要用于读取、监控、跟踪他人的微信,不要部署到他人设备或远程静默运行。
- **解密依赖读取微信进程内存,属于逆向工程手段**,很可能**违反微信的服务条款**,并可能触发账号风控、限制或封禁。同类项目曾收到微信官方函件并删库。使用风险由你自行承担。
- 本项目**只读**:不发送消息、不修改微信、不联网(除你自己配置的 AI 服务外)。
- 解密副本与索引是明文,保存在 `%LOCALAPPDATA%\ChatRelay\`;不需要时删除该目录即可。
- 本项目仅用于个人数据归档与安全研究,不构成法律意见。遵守当地法律与微信服务条款是你的责任。

## 致谢 / Attribution
微信 4.x 的密钥提取方法(DLL 内 XOR 密钥的汇编特征、内存中密钥描述结构、口令 + PBKDF2 的派生流程)参考并移植自以下开源项目的研究成果,特此致谢:
- [LifeArchiveProject/WeChatDataAnalysis](https://github.com/LifeArchiveProject/WeChatDataAnalysis)(`key_v4.py` / `dll_key_scan.py`)
- [zhuobichen/weflow-cli](https://github.com/zhuobichen/weflow-cli)、[vpcoderli/wxq](https://github.com/vpcoderli/wxq)

## 关于 `ChatRelay/`(.NET)目录
这是早期尝试的另一条路线——把自己注册成 Windows「分享目标」,接收微信官方「合并转发 → 其他应用」导出的 ZIP(无需解密)。在微信 4.2 上该入口不再调用第三方分享目标,此方案**未能走通**,仅作参考保留。当前可用的是 `wxcore/` 的解密方案。

## 许可
见 [LICENSE](LICENSE)(MIT)。注意:上游研究项目有各自的许可与权利,移植部分的权利归原作者所有。
