# Changelog

本文件记录 ZFundPilot 的版本变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

### Added
- AI 投顾对话（配置 OpenAI 兼容 API → 联网搜索 + 持仓上下文 → 生成调仓建议）
- 设置页面修改密码（SHA-256 哈希存储于 `data/auth.json`，无需改 .env）
- 净值走势图标记买入/卖出交易记录点，悬停显示交易明细
- 移动端适配：抽屉式侧边栏、响应式网格、顶部导航栏

### Changed
- 密码认证系统重构：环境变量仅用于首次初始化，之后通过 `data/auth.json` 管理
- README / DEPLOY 文档更新（新增 AI 功能说明、环境变量新行为）
- 前端 Settings 页面重构：渠道顺序 + 修改密码 + AI 配置三合一

## [0.1.0] - 2025-07-04

## [0.1.0] - 2025-07-04

### Added
- 交易流水驱动的持仓管理（买入/卖出/多渠道/移动加权平均成本法）
- AkShare + 天天基金双数据源净值自动获取
- 收益分析（浮动/已实现盈亏、组合收益曲线、IRR）
- 风险分析（最大回撤、年化波动率、集中度 HHI、结构占比）
- 组合结构再平衡建议（非交易指令）
- Streamlit 可视化界面（7 个页面）
- CSV 批量导入/导出交易流水
- 标准化 Python 包结构（src-layout）、pyproject.toml、pytest 测试、Ruff 配置
- MIT 许可证
