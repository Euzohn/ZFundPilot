# Changelog

本文件记录 ZFundPilot 的版本变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.2.0] - 2025-07-06

### Added
- AI 投顾对话：配置 OpenAI 兼容 API → 联网搜索 + 持仓上下文 → 生成调仓建议（支持智谱/Kimi/通义千问/DeepSeek）
- 设置页面修改密码（SHA-256 哈希存储于 `data/auth.json`，无需改 .env）
- 净值走势图标记买入/卖出交易记录点，悬停显示交易明细
- 移动端适配：抽屉式侧边栏、响应式网格、顶部导航栏
- 长期大盘指数数据（akshare 获取上证/深证/创业板）注入 AI 上下文

### Changed
- 密码认证系统重构：环境变量仅用于首次初始化，之后通过 `data/auth.json` 管理
- 改密码时刷新 token 签名密钥 `AUTH_SECRET`，使所有设备立即失效需重新登录
- 设置页重新设计：单卡三分区布局（渠道/安全/AI），渠道顺序自动保存
- README 更新：功能列表、项目结构、环境变量说明、联系邮箱
- DEPLOY 更新：环境变量表说明密码仅首次启动使用
- 前端 Settings 页面重构：独立分区 + 减少按钮噪音

### Fixed
- 设置页 React error #301（渲染中调 setState → useEffect 同步）
- 清空全部交易改为输入文字确认弹窗，防止误触
- 通义千问/百炼联网搜索识别：补充 `aliyuncs`/`maas` 关键词，添加 `forced_search` 强制搜索参数
- Pages/Overview 等页面响应式布局完善（grid-cols 适配手机端）

## [0.1.0] - 2025-07-04
