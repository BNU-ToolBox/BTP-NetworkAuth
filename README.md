# BTP-NetworkAuth

BNU-ToolBox 的校园网认证插件。账号和校园网密码统一在 BNU-ToolBox 的“账号管理”
中维护，并在插件页选择当前使用的账号。插件支持失败重试和用户级开机自启。

本仓库只发布插件源码及 Release 安装包。账号、日志与运行数据保存在
`%LOCALAPPDATA%\BNU-ToolBox\plugins\campus-network-auth`。认证凭据不写入插件配置。

依赖 BNU-ToolBox 0.1.1 或更高版本。可在 BNU-ToolBox 的插件管理页面直接安装或更新。
