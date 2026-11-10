# ChatRelay（原型 v0.1）

把微信「合并转发 → 其他应用」导出的聊天记录 ZIP 接到本地，为后续的解析、知识库和 MCP 服务打基础。

**只用微信官方的转发能力**：不读数据库、不解密、不注入，也不联网。

## 它做什么
- 把自己注册成 Windows 分享目标，在微信「其他应用」里显示为 **ChatRelay**。
- 收到的所有内容（ZIP、文件、文本、链接、图片）存到 `%LOCALAPPDATA%\ChatRelay\Inbox\<时间戳>\`，附带 `manifest.json`，然后打开该文件夹。
- 日志：`%LOCALAPPDATA%\ChatRelay\relay.log`

## 安装（Windows 10 2004+ / 11，需要 .NET 10 SDK 和 Windows SDK）
```powershell
# 1. 构建 + 打包 + 签名（普通权限）
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
# 2. 仅首次：用「管理员」PowerShell 信任本地开发证书
powershell -ExecutionPolicy Bypass -File scripts\trust-cert.ps1
# 3. 注册分享目标（普通权限，每次 build 后都要重跑）
powershell -ExecutionPolicy Bypass -File scripts\register.ps1
```
然后在任务管理器里结束所有 `Weixin`、`WeChatAppEx` 进程，再重新打开微信，因为微信会缓存分享菜单。

卸载：`scripts\unregister.ps1`。撤销证书信任：打开 `certlm.msc`，进入「受信任的人」→「证书」，删除 “ChatRelay Dev”。

## 关键约束（来自 WeChatBridge 的踩坑记录和腾讯 WeixinShare 清单）
- 必须声明 `SupportsAnyFileType`，并同时声明 StorageItems、Text、URI、Bitmap 四种格式，否则微信在枚举时会过滤掉。
- 显示名里不能出现连续的「微信」「WeChat」「Weixin」。
- 稀疏包的 Logo 和 `resources.pri` 在外部目录里也必须存在，否则系统会静默不枚举。
