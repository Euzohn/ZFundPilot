# Changelog

本文件记录 ZFundPilot 的版本变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.9.0] - 2026-07-22

### Added
- 暗色模式：light / dark / system 三态切换，默认跟随 `prefers-color-scheme`，Settings 可手动锁定
  - `index.html` 防闪烁内联脚本，Layout 侧边栏底部 + Settings 显示设置卡双入口
  - `lib/theme.ts` 管理 localStorage 持久化 + 系统主题变化监听
- shadcn 原语组件：`dialog` / `alert-dialog` / `tooltip` / `popover` / `dropdown-menu` / `skeleton` / `checkbox`
- 业务组件：`MetricCard` / `SortHeader`（factory 模式）/ `ConfirmDialog` / `PageHeader` / `EmptyState` / `LoadingState` / `ThemeToggle`
- 公共工具：`lib/actionLabels.ts` / `lib/rangeLabels.ts` / `lib/chartPalette.ts` / 扩展 `lib/format.ts`（新增 `formatRelativeTime` / `formatTokens`）
- 设计 token：`warning` / `info` / `success` 语义色 + `brand-accent` / `brand-bg-dark` / `brand-text-light` 桥接 token + `chart-1..8` 统一图表色板（light/dark 双值）
- Vite `manualChunks` 代码拆分：`vendor-react` / `vendor-charts` / `vendor-radix` / `vendor-markdown` 4 个 vendor chunk + `index` 应用 chunk，vendor 可长期缓存

### Changed
- 中性色族由 `slate` 切换为 `zinc`（无蓝 tint，更中性，与 Linear 风格一致）
- 全局 200+ 处硬编码颜色 token 化（`text-blue-500` → `text-primary`、`text-amber-600` → `text-warning` 等）
- Home brutalist 桥接 token：`#0A0A0A` / `#FF2A2A` / `#EAEAEA` → `brand-bg-dark` / `brand-accent` / `brand-text-light`
- 4 套图表色板统一为 1 套 `CHART_PALETTE`（Overview / Returns / FundCompare 共用）
- 3 处手写 `fixed inset-0 z-50` 弹窗 → Radix Dialog / AlertDialog / Popover（Transactions 清空确认 / FundDetail 删除确认 / AIChat token 用量 / AIChat 历史会话下拉）
- 9 处 `<h1>` 标题 → `PageHeader` 组件（支持 tracking / truncate / actions props）
- 11 处 `LogoSpinner` 包装 → `LoadingState` 组件（支持 xs / sm / md / lg 四档 size）
- 14 处"暂无数据" 文本 → `EmptyState` 组件（支持 size / icon / description / action）
- `FundCompare` 4 个原生 `<table>` → shadcn `Table`（FilterSection / CompareTable / InfoTable / CorrelationMatrix）
- `Settings` 原生 `<input type="checkbox">` → Radix `Checkbox`，原生 `<select>` → shadcn `Select`
- `FundCompare` CorrelationMatrix RGB 热力图 → `hsl(var(--chart-*) / opacity)` 透明度混合，light/dark 双模适配
- 3 套重复 `MetricCard` 实现（Overview / Risk / FundDetail）→ 统一签名组件（支持 icon / color / subColor / size / fade props）
- 3 套重复 `SortHeader` 实现（Positions / Transactions / Returns）→ `makeSortHeader` factory 模式
- 3 处重复 `ACTION_LABELS` 定义 → `lib/actionLabels.ts`
- 多套 `RANGE_LABELS` / `PERIOD_LABELS` 定义 → `lib/rangeLabels.ts`
- 2 处重复 `formatRelativeTime` / `formatTokens`（AIChat / Settings）→ 合并到 `lib/format.ts`
- localStorage key 前缀统一为 `zfundpilot_*`（`zfund_lang` → `zfundpilot_lang`）
- 全局 `bg-blue-50` / `border-blue-300` 等 selected state → `bg-primary/10` / `border-primary/30`
- 全局 `bg-amber-50` / `bg-red-50` / `bg-green-50` → `bg-warning/10` / `bg-destructive/10` / `bg-success/10`

### Removed
- 4 个未使用 Logo 组件（`LogoHeartbeat` / `LogoCoinFlip` / `LogoPrism` / `LogoShuffle`）+ 对应 CSS keyframes
- `@radix-ui/react-progress` / `@radix-ui/react-select` 依赖（装了未用）
- `.dark` CSS 死代码已启用并补齐所有变量值

## [0.8.1] - 2026-07-20

### Added
- 基金筛选器：从天天基金全市场池按类型/板块/关键词筛选候选基金，一键加入对比
  - 后端 `fund_filter.py`：天天基金 fundcode_search.js 加载 + 本地缓存 24h + 多条件筛选
  - `POST /api/funds/filter` 端点，支持分页
  - 前端 `FundCompare.tsx` 新增 FilterSection 组件，筛选结果可直接加入对比

### Fixed
- 标准 cron day_of_week 数值转换：APScheduler 使用 0=周一 6=周日，与标准 cron（0=周日 1=周一）不同
  - `scheduler.py` 新增 `_convert_dow()`，将 cron 数值型 day_of_week 做 `(n-1)%7` 转换
  - `0 21 * * 1-5` 之前错误地排在了 Tue-Sat，现正确为 Mon-Fri
- 首页「昨日收益」标签在周末/周一显示错误：昨天（日历日）非交易日时显示昨日收益常让人困惑
  - 改为 3 分支：today→今日收益、yesterday（日历日）→昨日收益、else→显示实际日期

## [0.8.0] - 2026-07-20

### Added
- 基金对比页面：输入任意基金代码，多维度横向对比
  - 基本信息：代码/名称/类型/板块/成立日期/规模/基金经理/费率
  - 收益表现：近1周/1月/3月/6月/1年/3年/成立以来收益率
  - 风险指标：最大回撤/年化波动率/夏普比率/卡玛比率/胜率
  - 净值走势：归一化基期=100 多线图（Recharts Legend 可切换）
  - 相关性矩阵：NxN 颜色编码，正相关绿色/负相关红色
  - 输入支持逗号/空格/换行分隔，URL 参数 `?codes=` 支持分享
  - 并发获取 AkShare 数据，单只失败不阻塞整体
- 后端 `compare.py`：纯函数计算（收益率、最大回撤、波动率、夏普、卡玛、胜率、相关性）
- `/api/funds/compare` 端点（POST，接收 codes 列表，返回结构化对比结果）
- DEPLOY.md 新增「多实例部署」章节（每人独立 Docker 容器，数据完全隔离）

### Changed
- 自托管字体：移除 Google Fonts 外部依赖，改用 `@fontsource/fira-sans` + `@fontsource/fira-code`
  - 字体文件内联到 `dist/assets/`，无外部请求，提升隐私与加载速度
- 删除未使用的 8 个 Logo 动画变体（B2/B4/B6/B7/B9/B10/B12），保留 4 个实际使用的
  - CSS bundle 从 50.5 kB 降至 46.5 kB

### Fixed
- 登录 429 响应体 JSON 被前端当原始字符串显示（now 解析 `detail` 字段）
- 速率限制窗口语义修正：`_LOGIN_WINDOW`（5 分钟）用于计数窗口，`_LOGIN_LOCKED_UNTIL` 独立跟踪锁定到期时间（15 分钟）
- 审计日志时间戳使用 `Asia/Shanghai` 时区（之前存 UTC，前端未转换导致相差 8 小时）
- `db.py` 内联 `import datetime` 移至文件顶部

## [0.7.0] - 2026-07-18

### Added
- 登录速率限制：5 分钟内失败 5 次锁定 15 分钟，返回 429 Too Many Requests
  - 安全读取 X-Forwarded-For（需配置 `ZFUNDPILOT_TRUSTED_PROXIES`），默认直接用 `request.client.host`
- 密码哈希升级 bcrypt（cost=12）：兼容旧 SHA-256，登录成功后无感自动 rehash
- 审计日志：`audit_log` 表记录敏感操作，设置页可查看最近 100 条
  - 记录：登录成功/失败、改密、改用户名、删交易、清空流水、CSV 导入清空、AI 配置修改、定时任务开关与 cron 变更
  - `detail` 字段不记密码 / API key 明文
- `/api/auth/me` 端点（需认证），返回当前登录用户名
- 新增环境变量 `ZFUNDPILOT_TRUSTED_PROXIES`（逗号分隔 CIDR，默认空）
- DEPLOY.md 新增「反向代理 + HTTPS（可选）」章节，给出 Caddy 示例

### Changed
- 隐藏 username 枚举：`/api/auth/status` 不再返回 `username` 字段，前端登录页不再预填用户名
- AI 错误脱敏：`test_connection` 和 SSE 对话不再将上游错误详情回传给客户端，改为后端日志记录
- Settings 页「当前用户名」改从 `/api/auth/me` 获取

### Security
- 密码哈希：SHA-256 无盐 → bcrypt（cost=12），常时间比较不变
- 所有 API 错误消息不再暴露上游服务细节

### Fixed
- 登录 429 响应体 JSON 被前端当原始字符串显示（now 解析 `detail` 字段）
- 速率限制窗口语义修正：`_LOGIN_WINDOW`（5 分钟）用于计数窗口，`_LOGIN_LOCKED_UNTIL` 独立跟踪锁定到期时间（15 分钟）
- 审计日志时间戳使用 `Asia/Shanghai` 时区（之前存 UTC，前端未转换导致相差 8 小时）
- `db.py` 内联 `import datetime` 移至文件顶部

## [0.6.0] - 2026-07-17

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
