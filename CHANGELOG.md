# Changelog

本文件记录 ZFundPilot 的版本变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.4.0] - 2026-07-07

### Added
- AI 助手独立侧边栏页面：从风险页迁出，全屏对话布局，支持联网搜索 + 持仓上下文
- AI 自然语言录入交易：描述交易（如「昨天在支付宝买了1000元005827」）→ AI 输出结构化 JSON → 内联确认卡片（可编辑日期、切换 15:00 前/后）→ 确认后写入，支持 `after_three`（T+1）字段
- 交易流水页筛选工具栏：搜索（代码/名称）+ 操作类型筛选 + 日期范围快捷按钮（本月/近30天/本年/全部/自定义，默认近30天并持久化）+ 加载更多分页
- 持仓明细页搜索框（名称/代码/板块/类型模糊匹配）
- 罗盘玫瑰 Z 字 Logo（favicon + 侧边栏 + 移动端）+ 花瓣旋转加载动画（LogoSpinner，2.5s，替换所有页面加载态）
- 卖出表单快捷份额按钮（1/4、1/2、3/4、全部）+ 持有量提示 + 超额校验
- 卖出时自动匹配渠道：单渠道直传预填，多渠道各渠道行加卖出按钮
- 持仓明细和基金详情页显示净值日期，非今日数据标琥珀色
- 保存交易后自动跳转到该基金持仓详情页
- 交易管理选项卡加图标（录入/流水/CSV）

### Changed
- 系统提示词注入「交易记录录入能力」段：JSON schema + 字段规则 + 渠道取值 + after_three/T+1 说明
- 风险与建议页移除 AI 对话面板，聚焦静态风险报告
- README 优化：Logo + 徽章 + 目录 + emoji 功能列表 + 技术栈表 + Docker 快捷启动 + 截图 + Star History

### Fixed
- 停止追踪误提交的 `data/auth.json`，加入 `.gitignore`
- 移除残留的净值日期表头
- 统一退出登录与收起侧边栏按钮样式（w-full/rounded-lg/hover-bg/icon-size）
- 侧边栏收起按钮对齐方式改为左对齐

## [0.3.0] - 2025-07-06

### Added
- 现金分红（dividend）和红利再投资（reinvest）交易类型支持
- 分红/再投资表单录入：分红只需到账金额，再投资自动计算金额
- 交易列表按操作类型显示不同颜色 Badge（分红=蓝色、再投资=紫色）
- 收益分析页单基金表格新增「分红」列（累计分红金额，可排序）
- 持仓模型新增 `dividend_count` / `dividend_total` 字段
- 组合汇总新增 `total_dividend`（累计分红总额）
- CSV 导入/导出支持分红/再投资（识别"分红"/"红利再投资"中文）
- 新增 9 个分红/再投资相关测试用例（is_valid / normalize / 持仓计算）

### Changed
- DB 迁移：重建 `transactions` 表，去掉 `CHECK(action IN ('buy','sell'))` 约束，放宽 `amount`/`shares` 的 NOT NULL（同时修复待确认交易的 DB 层拦截 bug）
- `_backfill_transaction_navs()` 跳过分红交易（分红 nav 含义为每股股息，非基金净值）

### Fixed
- `calculate_summary()` 中 `realized=` → `realized_pnl=` 参数名错误（端到端调用时触发 TypeError）

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
