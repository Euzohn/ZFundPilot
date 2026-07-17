# Changelog

本文件记录 ZFundPilot 的版本变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

### Added
- 基金实时估值：调用天天基金 fundgz API，交易日内实时估算基金涨跌幅
  - Overview 首行新增「今日估算」卡（组合估算 P&L + 涨幅，60s 自动刷新）
  - Positions 新增「估算涨跌」列，合计行显示总估算 P&L，跟随渠道筛选正确分摊
  - FundDetail 最新净值卡合并显示估算净值 + 涨跌幅 + 完整日期信息
  - 真实净值公布后估算自动失效（`jzrq == gztime` 日期则标记已更新）
  - 非交易时段 / 盘前自动隐藏估算（`gztime` 日期 != 今天则标记非交易时段）
  - 净值更新后 / DB 净值已超过估算基准时不显示估算
- 侧边栏底部新增 GitHub 链接
- NavUpdate 净值更新中用 LogoRipple 动画替换 Progress 进度条
- 净值更新改为后端异步 + 前端轮询（1.5s 轮询 `/api/nav/update/status`），切换页面不影响拉取进度，回来自动恢复
- 首页版本号从后端 API 获取（`/api/auth/status` 的 version 字段），不再写死
- update.sh 末尾打印常用命令（docker 操作、定时任务状态查询、执行日志查询）

### Changed
- FundDetail 估算信息合并至「最新净值」卡子文字，恢复 4×2 网格布局
- 首页收益标签根据 `as_of_date` 动态显示「今日收益」/「昨日收益」
- `/api/nav/update` 改为异步端点，新增 `GET /api/nav/update/status` 返回实时进度

### Fixed
- FundEstimate 字段缺默认值导致 `/api/estimate` 500 错误
- 定时任务拉取净值后未回填 T+1 交易（`backfill_transaction_navs`）且未清除分析缓存，现与手动拉取行为一致

### Performance
- Dockerfile 构建缓存优化：pip install 移至 COPY src/ 之前，源码变更不再重装依赖
- update.sh builder prune 改为 `--keep-storage 1g`，保留最近构建缓存加速增量构建

## [0.5.1] - 2026-07-16

### Added
- 持仓明细与基金详情新增「回本涨幅」指标（`avgCost / latestNav - 1`），亏损时以琥珀色子文字显示在收益率下方
- CONTRIBUTING.md 重写：补全前端开发流程（npm install / npm run dev）、Docker 部署说明、前后端代码规范、修正 commit 规范为中文

### Changed
- 偏好设置拆分为 3 张聚焦卡片（渠道管理 / 显示设置 / 定时净值更新），渠道顺序与颜色合并为单行列表
- 基础设计层升级：Card 去边框、圆角 0.5→0.75rem、card-hover 阴影增强、grain-overlay 噪点层
- 侧边栏导航分组（概览 / 交易与持仓 / 分析与工具）+ 活跃态改为半透明背景
- Overview 布局重构：4 行不等宽网格 + HeroCard/CompactCard 组件
- AI 助手界面全面重设计：去掉 Card 包装改扁平布局、用户消息改用主题变量、AI 消息去边框加头像、欢迎屏 2x2 带图标卡片、输入区改为自动展开 textarea（Enter 发送 / Shift+Enter 换行）、所有硬编码颜色改为主题变量

### Fixed
- 净值走势图交易标记点日期映射错误（交易日期晚于所有净值日时回退到最早日期，应回退到最近日期）
- Docker 容器时区为 UTC 导致定时任务从未运行（Dockerfile 设置 `TZ=Asia/Shanghai` + 安装 tzdata，scheduler.py 改用 `datetime.now(_TZ)` 时区感知）
- 删除残留 `app.py`（引用已不存在的 `zfundpilot.app` 模块）

## [0.5.0] - 2026-07-15

### Added
- 首页：深色主题门户页，独立顶栏 + 品牌展示 + 核心指标 + 快捷入口 + GitHub 链接，不含侧边栏
- 涨跌颜色主题切换：设置页支持切换「绿涨红跌（国际）」/「红涨绿跌（A股）」，全局 CSS 变量驱动，同步到服务端
- 登录页增加用户名输入框，支持用户名 + 密码双因素登录
- `POST /api/auth/change-username` 修改用户名端点（需当前密码验证，改后 token 失效）
- `ZFUNDPILOT_USERNAME` 环境变量，首次部署时可自定义用户名（默认 `admin`）
- 设置页「账户与安全」显示当前用户名 + 修改用户名区域
- 新 Logo（罗盘玫瑰 Z）+ 11 个 Logo 动画组件（开屏金光入场、加载翻牌洗牌、AI 思考光环打字）
- AI 对话多会话管理：创建/切换/归档/删除，localStorage 持久化，日期-时间命名 + 自定义重命名
- AI 对话 token 用量记录（SQLite 持久化 + 状态栏 + 明细弹窗 + 每日趋势 sparkline）
- AI 对话持仓明细开关 + 折叠展示系统提示词
- AI 系统提示每对话只建一次，切会话随存随取
- AI 设置页重构为 3-Tab 布局 + 测试连接 + 平台预设
- 自动查询基金申购/赎回费率，预填交易手续费（天天基金 HTML 抓取，按金额分档匹配优惠折扣价）
- 卖出按 FIFO 先进先出匹配买入批次计算赎回费
- 组合收益曲线增强：累计收益 + 累计收益率两条线，图例可点击切换显示/隐藏
- 组合收益曲线时间区间选择器（1月/3月/6月/1年/持仓至今）
- 收益波动图按渠道堆叠柱状图 + 日历视图（日/周/月/年切换）
- 今日收益改为按基金净值直接计算 + 周/月/年收益
- 持仓明细净值走势图增加每日收益柱 + 时间区间选择
- 渠道颜色自定义（预设色板 + 自由选色，服务端同步）
- 关键词映射自定义（服务端同步，多设备统一）
- 偏好设置（购买渠道顺序）同步到服务端
- 录入交易时默认填入当前日期

### Changed
- 旧 `auth.json` 升级时自动补填 `username: "admin"`，登录不受影响
- 所有涨跌颜色引用统一改为 CSS 变量 `var(--gain-*)` / `var(--loss-*)`
- AI 用量时间戳统一存 UTC，前端按 UTC 解析转本地时区
- `update.sh` 优化：无更新时跳过构建 + 缓存构建 + 构建后清理旧镜像
- NavUpdate 页面排除已清仓基金，只显示当前持有基金
- NavUpdate 页面改为单 API 数据源，与持仓页同源
- 净值更新只更新当前持仓中的基金，不再更新已清仓/误添加的
- CSV 导出文件名加时间戳

### Fixed
- FundDetail 交易标记点挂到最近净值日，周末/筹备期交易不再丢失
- FundDetail/Returns 图表柱状图颜色改用 CSS 变量，随涨跌主题切换
- Settings 涨跌颜色切换按钮符号（▲/▼）硬编码为绿色/红色，不受当前主题影响
- `normalize()` 计算份额/净值/金额未舍入到标准精度（shares→2, nav→4, amount→2）
- `normalize()` 计算份额/金额时扣除手续费
- 买入成本和卖出盈亏双重计算手续费
- AI 卖出交易未显示预估金额，`feecalc` 未返回 `amount`/`nav`
- T+1 待确认交易导致收益分析图今日收益显示虚假亏损
- 赎回手续费改用卖出确认净值计算 + T+1 待确认处理
- 卖出 T+1 手续费计算的三个问题
- 收益计算把买入金额误算为收益的问题
- `AreaChart` → `ComposedChart` 修复多指标图例不显示问题
- 板块分布图表 Tooltip 显示板块名称而非 market_value
- 收益标签根据最新净值日期动态显示（今日/昨日/日期）
- FundDetail `useMemo` 移到 early return 之前修复 React #310
- 卖出交易金额字段改为可编辑
- 费率查询改为直接抓取天天基金 HTML，修复申购费率一直为 0
- DeepSeek 启用联网搜索支持
- NavUpdate 页面 race condition 导致数据加载不全
- `/api/nav/latest` 查询范围统一
- 系统提示词按是否启用联网搜索分两套
- token 用量未捕获（usage chunk 的 choices 为空时被 IndexError 跳过）
- 关键词映射移到偏好设置 tab + 默认关键词默认展开

### Performance
- `analysis.py` 加内存 TTL 缓存（60s），避免页面间切换重复计算，8 个写入端点自动清除缓存

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
