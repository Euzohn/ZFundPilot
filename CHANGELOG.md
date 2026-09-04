# Changelog

本文件记录 ZFundPilot 的版本变更。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

### Added
- 组合真实行业敞口（基金穿透）：跨基金聚合底层持仓的真实行业分布，而非基金名称推导的板块。后端 `fetch_fund_industry_allocation()` 封装 `ak.fund_portfolio_industry_allocation_em`（证监会 ~19 类行业配置，当年无数据回退上一年，1h 缓存），`analysis.aggregate_industry_exposure()` 按基金市值 × 行业占比加权求和，穿透/未穿透分离。新增 `GET /api/portfolio/industry-exposure`（60/min 限流）+ `GET /api/funds/{code}/industry-allocation`。前端 Positions 页改 Tabs 结构（持仓列表 / 行业敞口 / 已清仓），行业敞口 Tab 含汇总条 + BarChart + PieChart + 明细表（`IndustryExposurePanel` 组件）。FundDetail 页新增行业配置卡片（饼图 + 行业明细表）。`taxonomyLabels` 新增 19 个证监会行业双语映射 + `translateIndustry()`。AI 投顾上下文注入行业穿透数据（穿透覆盖度 + 前 10 大行业 + 未穿透部分）。新增 `tests/test_industry_exposure.py`（6 用例）+ `test_fetch_fund.py` 扩 6 个行业配置测试，总测试 407→419

### Fixed
- 行业名称中英文夹杂：QDII 基金返回 GICS 分类（非必需消费品/电信服务/能源等）与 CSRC 分类混合，映射表未覆盖导致未映射名称透传中文。扩展 `INDUSTRIES` 映射至 ~35 条（CSRC + GICS + 别名变体），覆盖「金融/金融业」「房地产/房地产业」「信息科技/信息技术」「通讯/电信服务/通信服务」等异写。后端新增 `_clean_industry_name()` 清洗前导数字脏值（如 "45信息技术"→"信息技术"）。新增 5 个测试，总测试 419→424

## [0.21.0] - 2026-09-05

### Added
- 基金转换功能：交易表单操作类型新增「转换」，一次录入转出基金（卖出腿：份额+净值+赎回费）和转入基金（买入腿：金额+净值+申购费），后端 `POST /api/conversions` 原子创建两条关联交易，共享 `conversion_id`（UUID）。转出份额带持有量校验 + 快捷比例按钮（复用卖出逻辑），双基金代码独立识别，双净值自动加载，赎回费/申购费分别自动计算（防抖 500ms）。支持 T+1 标记，T+1 时转入金额可留空（待净值确认），非 T+1 时未填转入金额则从卖出腿自动推导。支持自定义渠道。交易列表对有 `conversion_id` 的流水显示「转换」badge。`transactions` 表新增 `conversion_id TEXT` 列（幂等迁移），`Transaction`/`TransactionCreate` 模型同步扩展，编辑转换腿保留关联不断链。新增 `tests/test_conversion.py`（15 用例），测试总数 390→405
- 转换腿关联：交易列表「转换」badge 可点击（`role=button` + 键盘 Enter/Space 支持）跳转配对腿详情弹窗；`TransactionDetailDialog` 新增「配对交易」区块（配对腿动作/代码/日期 + 「查看配对交易」按钮），配对腿从前端全量 `txs` 按 `conversion_id` 本地查找，无需新增 API。新增 i18n 键 `pairedTransaction`/`viewPairedTransaction`
- 持仓明细页新增网格视图（Bento 大卡布局）：列表/网格视图切换，切换状态 `localStorage` 持久化（`zfundpilot_positionsView`）；网格模式下每只基金一张大卡，展示代码/名称 + 仓位占比条 + 成本/估值/盈亏额/盈亏率 + 持仓天数/板块/跟踪指数；按市值/盈亏额/收益率/名称排序（仅网格模式显示排序下拉）；底部汇总条展示持仓基金数 + 总估值 + 总盈亏额。已清仓持仓仍仅以表格显示（与现有筛选器一致）。新增 i18n 键 `viewList`/`viewGrid`/`sortValue`/`sortPnl`/`sortReturn`/`sortName`/`positionsTotal`/`fundCountHintGrid`
- 净值更新页进度条：更新进行中显示完成进度条（done/total 百分比，平滑过渡动画），保留 `(16/33)` 数字文本。README/README_EN 基金转换条目补充「转换」badge 可点击跳转配对腿说明

### Fixed
- 转入金额不可编辑：`value={toAmount || autoToAmount}` 导致清空后弹回卖出金额（`""` falsy 回退 auto）。改用 `toAmountManuallyEdited` ref 单向自动填充（镜像 `toFeeManuallyEdited` 模式），`value` 改为纯 `toAmount`。"自动"标签手编辑后隐藏；差值时显示"卖出净到账 ¥X（+/-Y.ZZ）"。新增 i18n 键 `sellNetProceeds`
- 转换表单布局重排：转出/转入字段分行——Row1 [转出份额][转出净值][转出手续费]，Row2 [转入金额][转入净值][转入手续费]。空占位 div 加 `hidden sm:block` 确保仅 sm+ 4 列布局生效，移动端不产生多余间隙
- 删除转换腿后孤儿 `conversion_id`：`delete_transaction` 删单条时检查 `conversion_id`，非空则同时清空配对腿的 `conversion_id`（`UPDATE … SET conversion_id=''`），避免剩余交易显示不可点击的「转换」badge。新增 2 个测试用例（孤儿清理 + 普通删除无副作用），总测试 405→407
- 编辑/删除转换腿无上下文提示：编辑表单顶部，当 `editingTx.conversion_id` 存在时显示提示「此交易属于一笔基金转换，编辑仅作用于当前记录」；删除确认弹窗对转换腿追加警告「删除后将解除与配对交易的关联」。新增 i18n 键 `conversionLegHint`/`conversionDeleteWarning`
- 英文模式货币符号：`format.ts` `money()`/`signedMoney()` 数据全为人民币，切英文仅换 locale 格式（千分位），不再切换为 $，避免 $ 暗示 USD 误导用户
- 英文模式硬编码中文漏网：`DividendCheckDialog` 分红备注改用 i18n 模板键（`dividendReinvestNote`/`dividendCashNote`）；`FundDetail` 持仓股市值「亿」改用 `formatLargeCN()`（英文 M/B/T）；`backendLabels` 新增 `BACKEND_ERRORS` 翻译表 + `translateBackendError()`（精确匹配 + 最长前缀匹配），各 catch 块 toast/setParseError/setStartError 改用翻译；`Transactions`/`Returns`/`TransactionDetailDialog` 渠道显示加 `translateChannel()`；`Transactions` 定投执行去掉 `msg.includes("已执行")` 中文匹配，改依赖 409 状态码

## [0.20.1] - 2026-09-01

### Fixed
- 表单验证统一（Login/Transactions/Settings）：创建 `FieldError` 内联错误组件，替代 toast 弹窗，三个页面的表单输入统一使用 `aria-invalid` + `aria-describedby` + 内联错误文本，密码输入补充 `autoComplete` 属性
- 无障碍改进：Screener 筛选 chip 加 `focus-visible` ring、行选择 checkbox 加 `aria-label`、移动端抽屉加 Escape 关闭 + `role="dialog"` + `aria-modal`、可点击行加 `tabIndex=0` + `role="button"` + Enter/Space 键盘支持
- 硬编码值提取到 `config.py`：`T1_CUTOFF_HOUR`、登录限流常量、AI httpx 超时常量、CORS origins 支持环境变量 `ZFUNDPILOT_CORS_ORIGINS`
- 前端重复轮询：Transactions 页与 Layout 重复 60s 轮询 `getPendingDividendAlertCount`，Transactions 改为仅挂载时取一次
- 图标按钮 tooltip：约 26 处纯图标按钮补 `title`，新增 i18n key
- 静默 except 吞错误：22 处 `except: pass` 加 `logger.warning`/`logger.debug`
- 死代码清理：删除 13 个无调用方 Python 函数
- 重复 import 修复（`api.py` F811）
- 净值缓存污染：`_index_fallback` 与 `get_estimates` 原地改写 `FundEstimate` 共享引用 → 改用 `dataclasses.replace` 生成新对象
- 定投计划重复执行：`execute_plan` 加 `_execute_lock` + 幂等检查，手动执行遇重复返回 HTTP 409
- 净值更新 TOCTOU 竞态：`_run_nav_update` 与 api 手动触发共用 `nav_update_state.py` 共享锁，两路更新互斥
- SQLite 并发健壮性：`get_connection()` 加 `PRAGMA busy_timeout = 5000`，`init_db()` 加 `PRAGMA journal_mode = WAL`
- AI 用量时区：存储与读取统一为本地时间，修复上海时区早 8 点前当日 token 归到前一天的问题
- 朴素 datetime 收敛约定：`ai.py` 与 `fetch_dividend.py` 改用 `datetime.now(config.TIMEZONE)`
- API 输入验证补全：所有 Pydantic 请求模型加 `allow_inf_nan=False`，各模型加 field_validator
- SSRF 防护：AI `base_url` 加协议/内网地址校验
- 上传大小限制：截图 10MB、CSV 5MB
- FastAPI 生命周期迁移：`@app.on_event` → `lifespan` async context manager
- 非原子配置写入：`_save_auth_data` / `_save_ai_config` / `_save_sector_map` 改用 `_atomic_write`
- 阻塞式 bootstrap：改为 `threading.Thread(daemon=True)` 异步执行
- 登录限流字典无界增长：新增 `_sweep_login_attempts()` 清理过期条目
- CSV 清空重导确认：加 `ConfirmDialog` 防误删
- SortHeader 键盘不可达：加 `tabIndex` + `role="button"` + `aria-sort` + `onKeyDown`
- IME 输入 bug：13 处 Enter 提交加 `!e.nativeEvent.isComposing` 守卫
- 加载态闪烁：8 处 `useApi` 解构 `loading` 加 guard
- 破坏性操作无确认：8 处加 `ConfirmDialog`
- AIChat 配置加载闪烁：`useApi` 加载中 `data=null` → `configured=false`，每次进页面闪"未配置"，解构 `loading` 加 guard
- TpSlAlertsPanel error 用错组件：error 路径用 `EmptyState` 无重试按钮，改 `ErrorState size="sm" onRetry={reload}`
- Transactions 渲染阶段副作用：`useApi().data.forEach` 中调 `setFunds` 改 `useEffect`
- FundDetail 表头标注错误：交易列表两列都标"操作"，第一列改 `t.common.type`
- ErrorState AlertTriangle 丢失 `text-loss-500` 颜色
- 路由遮蔽 `/api/nav/latest`、`_migrate_add_indexes` 顺序、`_migrate_dividend_alerts_unique` 去重、`_migrate_relax_transactions_schema` 负金额与 is_t1、`update_auto_invest_plan` SQL 注入防护、`update_scheduler_cron` 坏 cron、`calc_fund_fee` 坏日期、`auth_login` 审计日志、`recalculate_t1_transactions` 启动异常、限流端点 key 不匹配
- 图表硬编码颜色改为 `hsl(var(--chart-1/2))`
- 文件名误导：`ScreenshotImportDialog.tsx` → `ScreenshotImportPanel.tsx`
- 过时文件清理：删除 `frontend/vite.config.js` + `vite.config.d.ts`（tsc 编译产物）
- `CONTEXT.md` 文档矛盾：fundgz 描述从"已废弃"更正为"估值替补源"
- `pyproject.toml` 残留关键词：`keywords` 移除旧架构遗留的 `streamlit`
- TypeScript `any` 收窄：7 处
- 未使用 import 清理：~20 处

### Performance
- 消除 5 处 N+1 查询：(1) `api.py get_latest_navs` 逐只 `get_latest_nav` → `get_latest_navs_batch` 单次查询；(2) `analysis.py calculate_positions` 逐持仓 `get_latest_nav` → 批量预取 `nav_map`；(3) `analysis.py backfill_transaction_navs` 逐笔 `get_nav_on_or_after` → `get_navs_on_or_after_batch` 批量预取，逐条 `update_transaction` → `executemany` 单连接批量写；(4) `scheduler.py _run_tp_sl_check` 逐持仓 `get_tp_sl_alert_state` → `get_tp_sl_alert_states_batch` 批量预载 + 本地映射同步更新；(5) `api.py _mark_duplicates` / `fetch_dividend.py` 全表 `get_transactions` → SQL IN 过滤 + 内存查找表；(6) `analysis.py calculate_summary` 冗余 `get_transactions` → `_get_transactions_cached` 共用缓存。新增 `db.py` 函数 `get_latest_navs_batch` / `get_navs_on_or_after_batch` / `get_tp_sl_alert_states_batch`，`get_transactions` 扩展 `fund_codes/actions/dates` 可选参数

### Added
- 端点速率限制（in-memory，单 worker）：AI 对话/截图解析（20/min）、基金对比/回测（60/min）、CSV 导入（30/min），超出返回 429 + Retry-After 头。复用 `_get_client_ip` + 滑动窗口，sweep 防字典无界增长
- `dividend_alerts` 唯一约束：`UNIQUE(fund_code, ex_date, alert_type)` 防止 check-then-insert 竞态。`add_dividend_alert` 改 `INSERT OR IGNORE`，`dividend_alert_exists` 加 alert_type 过滤
- `auto_invest_plans` 数据约束：`CHECK(amount > 0)`，表重建时清理无效数据
- `nav_history` 数据约束：`CHECK(nav > 0)`，表重建时清理无效数据
- 数据库索引优化：补充 `ai_usage(created_at)`、`transactions(fund_code, date)` 复合索引、`auto_invest_plans(enabled, next_run)`、`dividend_alerts(alert_type, status)`；删除冗余 `idx_nav_code_date`、`idx_index_code_date`、`idx_tx_code`
- 测试覆盖：新增 156 个测试覆盖 backtest（26）、compare（28）、rebalance（8）、API 输入验证回归（70）、原子写入（4）、db WAL/时区（5）、config 密码哈希（13），测试总数 234→390

## [0.20.0] - 2026-08-28

### Added
- 截图导入交易/持仓对账：Transactions 页新增第 5 个 tab「截图导入」（inline 面板，切 tab 自动卸载重置），上传购买记录或持仓截图，AI 视觉模型自动解析为结构化数据。两种模式：交易模式（解析交易行 → 预览编辑 → 批量保存）；持仓对账模式（解析持仓 → 按渠道对比已记录份额 → 生成差额调整交易 → 勾选确认）。视觉模型独立配置（Settings 新增视觉模型卡片，4 个预设：智谱 GLM-4V 推荐/通义千问 VL/OpenAI GPT-4o/Kimi 视觉），与对话 AI 解耦。截图常只有基金名称无代码，后端 `resolve_fund_code` 用 fund universe 自动解析名称→代码（精确/多候选下拉选/无匹配手填），模型输出的代码经 `verify_fund_code` 校验防编造。对账成本用 latest_nav 估算并标注「请核实」，预览表可编辑
- 截图导入去重：后端 `_mark_duplicates` 按 fund_code+action+date+amount（0.01 容差）或 shares 匹配标记疑似重复，预览表重复行加「重复」badge，默认跳过不入库
- 截图导入视觉模型 token 用量追踪：`parse_screenshot` 从响应提取 `usage` 调用 `db.add_ai_usage`，与对话 AI 用量统一记录
- 截图导入用户补充说明：解析前可输入 `user_hint` 补充语境（前端 textarea → client → API → prompt 末尾追加），提升无上下文截图的解析准确率
- perf: 截图导入图片自动缩放——发送前用 Pillow 将图片缩到最长边 1280px + 转 JPEG quality 85（`_compress_image`），手机截图（1080×2340）image tokens 减少 50-70%、网络 payload 同步减小。Dockerfile 加 `libjpeg62-turbo`，新增 5 个压缩测试用例
- 自选页列头点击排序：复用 `SortHeader` 组件（与 Screener/Positions/Returns/Transactions 一致），6 列可排序（代码/名称/类型/板块/分组/添加时间），默认按添加时间降序。点击同列切换升降序，切换列默认降序

### Fixed
- DividendCheckDialog 关闭时 aria-hidden 警告：点击「记为分红」时 `onOpenChange(false)` + `navigate()` 同时触发，Radix Dialog 在退出动画期间对 `#root` 应用 `aria-hidden`，`onCloseAutoFocus` 尝试恢复焦点到隐藏元素触发浏览器警告。`DialogContent` 添加 `onCloseAutoFocus={(e) => e.preventDefault()}` 阻止焦点恢复
- 幽灵分红提醒二次修复：v0.19.0 的 `_cleanup_stale_alerts` 仍无法清理部分幽灵提醒。(1) `fetched_funds.add(code)` 在空响应检查之后执行，AkShare 返回空 DataFrame 的基金（如 QDII 017641 摩根标普500）不进入 `fetched_funds`，其 pending 提醒被跳过永不清理。修复：将 `fetched_funds.add(code)` 移到空响应检查之前。(2) TTL 90 天兜底失效：SQLite `created_at` 是朴素无时区字符串（`datetime('now','localtime')`），与 aware `cutoff` 比较抛 `TypeError` 被 except 吞掉导致 TTL 静默失效。修复：检测 `created_dt.tzinfo is None` 时补 `config.TIMEZONE`（+5 测试，229→234）

## [0.19.0] - 2026-08-25

### Added
- 基准指数数据持久化：新增 `index_history` 表存储沪深300/上证指数/创业板指历史收盘价。`fetch_index_history()` 改为三级缓存（L1 内存 1h → L2 SQLite → L3 新浪在线），在线拉取后自动持久化到 DB，离线时从 DB 返回已有数据。scheduler 净值更新后自动拉取并持久化基准指数，确保离线可用。`BENCHMARK_INDICES` 提取到 `config.py` 共享
- 止盈止损提醒功能：净值更新完成后自动扫描持仓基金收益率，达到止盈/止损阈值时生成提醒。状态机防重复：触发后 `disarmed`，收益率回落到 `threshold × reset_ratio`（复位比例，默认 80%）以下后重新 `armed`，避免部分止盈后剩余份额收益率不变导致重复提醒。复用 `dividend_alerts` 表（加 `alert_type`/`triggered_return`/`threshold` 列），新增 `tp_sl_alert_states` 状态表。Settings 页新增配置卡片（总开关即时生效 + 止盈/止损独立开关 + 阈值 + 复位比例），Returns 页新增提醒列表（确认/忽略操作），Layout 红点拆分显示（Transactions 标分红提醒 / Returns 标止盈止损提醒）
- 基金详情顶栏新增「加入自选」按钮（`Star` 图标）：已加入时实心黄色高亮，点击切换添加/移除，toast 提示。对比按钮和自选按钮均改为纯图标（去掉文字），加 `title` tooltip
- 基金详情顶栏新增「定投」按钮（`Repeat` 图标）：跳转到交易管理页定投 tab，自动预填基金代码和渠道，弹窗自动打开
- 分红提醒删除接口：新增 `DELETE /api/dividends/alerts/{alert_id}` 端点 + `db.delete_dividend_alert()`，支持删除误报提醒（非仅标记 ignored）。DividendCheckDialog 每条提醒左侧加 `Trash2` 图标按钮直接删除
- 分红扫描响应新增 `cleaned` 字段：rescan 后 toast 提示自动清理的无效提醒数量，scheduler 日志/审计也包含清理计数

### Changed
- `docker-compose.yml` 的 `container_name` 改为环境变量 `${CONTAINER_NAME:-zfundpilot}`，同一机器运行多个实例时在 `.env` 设置不同 `CONTAINER_NAME` 即可避免容器名冲突。`.env.example` 新增 `CONTAINER_NAME` 说明，`DEPLOY.md` 新增多实例部署方式（独立目录 + 同源多 compose 文件）+ 容器名冲突故障排查

### Fixed
- 分红提醒幽灵数据自动清理：AkShare `fund_open_fund_info_em` 偶尔返回错误分红数据（后源数据修正但 DB 中提醒永久残留）。`check_dividends()` 抓取数据时同步收集 `fetched_ex_dates`/`fetched_funds`，校验现有 pending 提醒是否仍存在于源数据，不存在则自动标记为 ignored。仅校验成功获取非空数据的基金，避免网络错误误清有效提醒。扫描响应/scheduler 日志/审计均含清理计数，rescan 后 toast 提示清理数量。`_last_cleanup_count` 在函数入口重置为 0 防止 stale 值泄漏；cleanup 异常被 try/except 包裹不影响主流程
- 止盈止损提醒面板三问题修复：(1) 操作确认/忽略后整个面板卸载为 spinner 导致下方图表跳动闪烁，改为乐观更新（snapshot + setData）替代 reload()；(2) 已确认/已忽略的提醒占用空间，折叠为「已处理 (N) 条」可展开区域；(3) 已处理的提醒无法二次操作，新增「重新打开」按钮恢复为 pending 状态。`PUT /api/alerts/{id}` 新增 `pending` 状态支持，改回 pending 时清空 `resolved_at`。确认按钮改为跳转交易页预填卖出，交易保存后自动标记 confirmed。`resetForm()` 补 `setPendingTpSlAlertId(null)` 防止取消后手动保存误标记错误提醒
- 基金详情页分红方式标识圆点与文字间距修复：`button` 缺 `gap-1.5`（其他 Badge 均有），补齐后间距一致。加 `ChevronDown` 图标区分可点击修改的标识与不可点击的 Badge。下拉选项框 `align="start"` → `align="center"` 居中显示
- `get_dividend_alerts` 加 `alert_type='dividend'` 过滤，确保现有分红提醒页不受 tp_sl 数据污染
- `update_tp_sl_config` 布尔值存储格式修复：`str(True)` 产生 `"True"`（大写）但检查 `"true"`（小写）导致开关永远显示已暂停，改为 `isinstance(v, bool)` 时统一存 `"true"`/`"false"`
- `AutoInvestPlansPanel` 的 `useEffect` 依赖数组包含 `t.transactions.autoInvest`，切换语言时弹窗被意外重新打开；改为 `onPrefillConsumed` 回调模式消费后清除，依赖数组仅 `[prefillCode]`
- `update.sh` 提示信息补全「按 Enter 继续」（原仅提示「按 Ctrl+C 取消」缺少继续指引）+ 补充 `.env` 和 `docker-compose.override.yml` 不受 `git reset --hard` 影响说明
- 红点提醒可发现性修复：侧边栏红点原为分红+止盈止损合计数仅标在 Transactions，止盈止损提醒实际在 Returns 页导致指向错误。拆分为 Transactions 标分红 count / Returns 标止盈止损 count。Transactions 页「检查分红」按钮加数字红点 badge + 「单笔录入」tab trigger 加红点引导

## [0.18.0] - 2026-08-22

### Added
- 收益分析页日历视图支持周/月/年粒度：`PnLCalendar` 新增 `mode` 属性切换四种粒度——日（现有月历网格）/周（12 行月份，每行 5 列周 cell，按月分组）/月（4×3 月格，年导航）/年（所有年份平铺）。每周/月/年 cell 复用 5 级 gain/loss 色阶，归一化按当前粒度计算。模式切换不再强制切回柱状图，日历切换按钮在所有模式下均可见
- 基金对比页改为随时增减的对比篮模式：`CompareContext` 全局管理对比篮（localStorage 持久化），FundCompare 页头部显示已选基金 chips，支持 X 移除和清空。Screener/Watchlist 通过 `addToCompare` 直接加入（toast 提示不走跳转），FundDetail 顶栏加「加入对比」按钮，Layout 导航栏对比图标显示数量 badge
- 新增天天基金 fundgz 作为估值替补源：主源 `fund_value_estimation_em` 无数据时，逐只通过 fundgz API 补取（6 线程并行，30s 缓存），不替换主源，仅新增 fallback 链路。排除主源已有公布净值的基金（ok=False 且 gsz=0 才走替补）

### Fixed
- 收益分析页单基金明细表补显已清仓持仓：`getPositions(true)` 获取全部持仓，已清仓行 `opacity-60` + Badge 标识，汇总行 `realized_pnl`/`dividend_total` 改为累加全部持仓与顶部卡片一致
- 浮动收益率排序图基金名称截断修复：YAxis `width` 120→140 + `tickFormatter` 截断长名（>8 字加省略号）
- 收益分析页 tooltip 暗色模式不可读修复：组合曲线 + 收益率排序 tooltip 补 `background: hsl(var(--card))` + `labelStyle`/`itemStyle` 前景色，与 FundDetail/FundCompare 样式一致（Recharts 默认白底 + item 颜色 `#000` 在暗色模式下白底白字/黑底黑字）
- 对比页空篮提示不显示：条件不应依赖 `data.ok`（空篮时 `data` 为 null）
- PnLCalendar 周/月/年模式汇总文字 `{u}` 占位符未全局替换：`replace()` 只替换首个匹配，改用正则 `/g` 全局替换

## [0.17.1] - 2026-08-19

### Added
- 自选页持仓基金标识：自选列表中已持有的基金显示「持仓中」绿色 badge，数据来自持仓列表（排除已清仓）
- 交易详情弹窗新增「查看基金」按钮：点击跳转到该基金的详情页，仅在交易列表页弹窗中可见

### Changed
- README 截图区扩充至 15 张（中英双语），路径迁移 `docs/screenshots/` → `assets/readme/screenshots_{zh,en}/`，交易管理页拆 2×2 表格展示录入/流水/CSV/定投

### Performance
- README 截图压缩 PNG→WebP：`cwebp -q 85` 转换 30 张截图，全宽图缩放至 1600px、交易 2×2 图缩放至 1200px，总计 125MB→1.4MB，压缩率 99%

### Fixed
- card-hover 悬停效果修复：补默认边框 + hover 柔和高亮（border 50% 透明 + primary 25% + 阴影 8%），原定义因 Card 组件无 `border` 类导致 `border-color` 不可见
- 首页低对比文字可读性提升：5 处 `text-white/30` → `/40`~`/50`（bento 描述/版本号/免责声明/分隔符）
- Overview 数据元素移除 `fade-in-up`：`useApi.reload()` 设 `loading=true` 导致卡片卸载重挂、动画每次刷新重播，移除后刷新不再闪烁
- 首页 bento 导航按钮补 `cursor-pointer`，强化可点击暗示
- AI 对话页切回时滚动位置修复：`useLayoutEffect`（绘制前）依赖 `[configured]`，在滚动容器实际渲染后（`aiConfig` 加载完成）才触发 `scrollTop = scrollHeight` 瞬间跳底；`mountedRef` 区分挂载滚动（瞬间）vs 新消息滚动（smooth）。原 `useEffect([])` 在 `aiConfig` 未加载、容器未渲染时触发，ref 为 null 导致滚动从未执行
- CSV 导入解析修复：`parseCsv` 裸 `fetch` 未带 `Authorization` 头，后端 auth 中间件返回 401 导致 `result.transactions` 为 `undefined`，前端访问 `.length` 报 TypeError。补认证头 + 401/错误处理

## [0.17.0] - 2026-08-14

### Added
- 组合曲线叠加基准指数对比：支持沪深300/上证指数/创业板指 toggle 切换，虚线叠加在右轴(%)上，直观看出跑赢/跑输大盘
- 新增 API `GET /api/portfolio/benchmark?indices=000300,000001,399006`，返回基准累计收益率，按组合曲线日期 ffill 对齐
- `fetch_estimate.py` 新增 `fetch_index_history()` 获取指数历史收盘价（新浪源 `ak.stock_zh_index_daily`），1h 缓存

### Fixed
- NavLinks 双实例轮询提升到 Layout 层，消除 desktop+mobile 重复 60s 定时器
- DividendCheckDialog useEffect 加 active flag cleanup，防止弹窗关闭后 async 返回在已卸载组件上 setState
- Settings 偏好设置 tab Card 宽度与 account/ai 一致（移除 `max-w-4xl`）
- 渠道管理行布局：左 div `flex-1` 撑满，消除桌面端中间空白
- 外观主题 segmented control 宽度与涨跌颜色选择器一致（`w-full` + `flex-1`）
- 净值回填时自动拉取手续费：`backfill_transaction_navs` / `recalculate_t1_transactions` 在 `normalize` 前调 `calc_purchase_fee` / `calc_redemption_fee`，返回/审计日志 detail 新增 `fee` 字段

## [0.16.0] - 2026-08-12

### Added
- 分红自动检测功能（Phase 1）：交易页「检查分红」按钮，按基金并行调 `ak.fund_open_fund_info_em(indicator="分红送配详情")`，检测持仓基金的未记录分红事件，弹窗预填确认入账（`fetch_dividend.py` 新模块，ThreadPoolExecutor 3 线程 + 6h 缓存 + stale-if-error + 去重）
- `funds` 表新增 `dividend_method` 字段（`cash`/`reinvest`，默认 `cash`），FundDetail 页加分红方式选择器（segmented control）
- 新增 API：`GET /api/dividends/check`（检测未记录分红）、`PUT /api/funds/{code}/dividend-method`（设置分红方式）
- 分红操作审计日志（`dividend_check` / `update_dividend_method`）
- 分红提醒弹窗组件 `DividendCheckDialog.tsx`：按基金 `dividend_method` 预选 action，弹窗内切换仅影响本次预填
- 分红定时检测（Phase 2）：每天 09:30 自动扫描持仓基金分红事件，新发现的存入 `dividend_alerts` 表（status: pending/confirmed/ignored），启动时 bootstrap 补执行
- `dividend_alerts` 表 + CRUD（`add_dividend_alert` / `get_dividend_alerts` / `get_pending_alert_count` / `update_dividend_alert` / `dividend_alert_exists`），去重查所有状态（ignored 后不再重复提醒）
- 新增 API：`GET /api/dividends/alerts`（按状态过滤）、`GET /api/dividends/alerts/count`（红点轮询）、`PUT /api/dividends/alerts/{id}`（确认/忽略）、`POST /api/dividends/scan`（手动扫描存表）、`PUT /api/dividends/auto-check`（开关）
- 导航栏 Transactions 项红点提醒：60s 轮询 pending alerts 数量，collapsed 模式显示小圆点，展开模式显示数字 badge
- Settings 页分红自动检测开关卡片（`dividend_auto_check` preference key，默认关闭）
- DividendCheckDialog 改为 alerts 模式：打开即显示 pending alerts + 「重新扫描」按钮 + 每行「忽略」按钮 + 「确认入账」带 alert_id 跳转
- TransactionForm 确认回调：保存交易后自动标记 alert 为 confirmed（关联 tx_id）
- 分红扫描/提醒处理审计日志（`dividend_scan` / `dividend_alert_update` / `dividend_auto_check_toggle`）

### Changed
- AkShare 1.18.79 → 1.18.82（空响应不再抛 `no text parsed` 异常，改为返回空 DataFrame）
- `upsert_fund()` SQL：INSERT 含 `dividend_method`（新基金默认 cash），`ON CONFLICT DO UPDATE SET` 不含（避免元数据刷新重置用户设置）

### Fixed
- 分红金额解析：AkShare 返回 `"每10份派现金0.0500元"` 字符串格式，`_parse_per_share()` 正则提取金额 + `/10` 得每股分红
- 无分红记录的空响应降级为 debug 日志（避免刷屏 WARNING）
- TransactionForm prefill 扩展支持 `amount`/`date`/`note` URL 参数（从分红弹窗跳转预填）

## [0.15.1] - 2026-08-11

### Added
- `NOTICE.md` 数据来源与合规声明（中英双语），声明第三方数据源（东方财富/天天基金）版权与使用约定
- README 截图区新增交易管理页面（深色/浅色双主题合并图）

### Changed
- CI workflow 加固：后端 3 个 Python 版本并行运行（移除 `max-parallel: 1`）、`fail-fast: false` 防单版本故障取消其他 job、`concurrency` 取消同分支旧运行、`timeout-minutes: 20` 安全阀、前端改用 `working-directory` 替代 `cd` 链式

### Fixed
- `fetch_estimate._index_fallback` 移除 `est.dwjz > 0` 跳过条件，修复指数基金在东财估值表有数据行但当日估算列缺失时指数兜底不触发的 bug
- `pyproject.toml` `dependencies` 补全 `python-multipart`，修复 CI 用 `pip install -e ".[dev]"` 时 FastAPI `UploadFile` 路由收集失败（`requirements.txt` 已有，pyproject 遗漏）
- Settings 偏好设置 tab 布局优化：`max-w-4xl` 约束宽度解决桌面端右侧留白，渠道管理行/关键词自定义行 `flex-col sm:flex-row` 移动端拆双行，色块组 `flex-wrap`，触摸目标移动端增大
- TransactionDetailDialog 移动端适配：详情网格 `grid-cols-1 sm:grid-cols-2` 移动端单列，操作/日期栏加 `flex-wrap` 防溢出

## [0.15.0] - 2026-08-06

### Added
- 指数基金跟踪指数估值：`funds` 表新增 `tracking_index` 列，`fetch_fund.py` 按基金名称推断跟踪指数关键词（沪深300/中证500/创业板指/半导体材料设备/人工智能/纳指/标普/恒生等）
- `fetch_estimate.py` 新增 `fetch_index_quotes()` + `estimate_from_index()`：东财估值 API 不可用时，用跟踪指数/ETF 实时涨跌估算指数基金当日净值变动
- 指数行情数据源：`stock_zh_index_spot_sina()`（A 股 562 个）+ `index_global_spot_em()`（全球 56 个）+ `stock_hk_index_spot_em()`（港股 359 个）+ `fund_etf_spot_em()`（ETF 1566 只，行业/主题指数代理）
- 两级匹配策略：先查指数实时行情（~5s），未匹配的关键词再查 ETF 实时行情（~17s，仅按需触发）
- 前端展示跟踪指数：FundDetail header badge + Positions/Watchlist 板块列小字
- `Fund`/`Position`/`FundMeta`/`WatchlistItem` 类型加 `tracking_index` 字段
- `db.update_fund_tracking_index()` 函数 + `reset_sectors` 端点同时回填 tracking_index
- 自选关注列表分组功能：`watchlist` 表新增 `group_name` 列，支持按组管理自选基金
- AI 助手流式回答跨页面持久化：新 `ChatContext` 方案，`ChatProvider` 挂在 `<Routes>` 外层，切换页面不丢失对话

### Changed
- 基金对比页删除 FilterSection，与独立基金筛选器（Screener）去重，复用同一套筛选逻辑

### Fixed
- `get_fund_estimate()` 单只估值端点未检查当日净值已入库，导致用今日净值当 prev_nav 算出错误估值
- 审计日志 4 条操作（watchlist_add/watchlist_group/watchlist_remove/export_backup）漏加 i18n 标签，显示为英文
- Positions/Watchlist 跟踪指数展示位置与样式统一（板块列、outline badge、`items-start` 防撑满）
- Positions 加载失败改用 `ErrorState` 组件保持一致
- 添加自选后未清空分组输入框
- 清理 FundCompare 未使用的 import（useEffect/LogoSpinner/Badge）

## [0.14.0] - 2026-08-04

### Added
- 基金筛选器独立页面 `/screener`：全市场基金池按类型/板块/关键词筛选，Top 30 补充收益/风险指标（1年收益/最大回撤/波动率/规模/经理），列头可排序，一键加入对比或自选
- `fund_filter.py` 激活死代码 `_EXECUTOR`/`_MAX_METRICS_FUNDS`：`_enrich_with_metrics()` 复用 `compare.py` 指标计算函数，`filter_funds()` 新增 `with_metrics` 参数
- 自选关注列表功能：`watchlist` 表 + `POST/GET/DELETE /api/watchlist` 端点，新建 `/watchlist` 页面，支持追踪未持有基金
- 前端 `FundFilterItem` 类型补全 `returns`/`risk` 字段
- 全量数据备份导出 `GET /api/export/zip`：ZIP 含 5 个 CSV（交易/基金/自选/定投/偏好），Settings 页面加备份按钮，净值历史不含可重新拉取

### Changed
- 基金筛选器 UX 改进：筛选芯片自动搜索 + 代码搜索忽略类型/板块 + 两阶段加载指标（先基础后指标，非阻塞）+ 空结果友好提示

### Fixed
- `/api/risk` flags 序列化补回 `code` + `params` 字段（v0.12.1 引入 i18n code 体系时 API 层漏传，英文翻译表失效）
- `/api/rebalance` advice 序列化补回 `code` + `params` 字段，同上
- Risk.tsx 再平衡建议 `al(loading) && advice` 条件导致加载完成后永远走 `EmptyState`，建议从未显示；改为 loading/error/data/empty 四态分支

## [0.13.1] - 2026-08-03

### Added
- 基金详情顶栏新增风险等级色点 Badge，后端 `fund.eastmoney.com/{code}.html` 抓取风险等级（低风险~高风险）
- 前端 `RISK_LEVELS`/`RISK_LEVEL_DOT`/`FUND_TYPE_DOT`/`translateRiskLevel()` 工具函数

### Changed
- 基金详情顶栏元数据行重构：基金代码 · 类型色点 Badge · 板块 Badge · 渠道色点 Badge · 风险色点 Badge
- 侧边栏交换「交易管理」与「持仓明细」顺序

### Removed
- 移除未使用的 `profileRiskLevel` i18n key

## [0.13.0] - 2026-08-02

### Added
- 基金详情新增「持仓卡片」（Phase 1）：资产配置饼图 + 前十大重仓股表格，AkShare `fund_portfolio_hold_em`（`date_year` 改 `date` 参数 + 取最新季度），1h 缓存
- 基金详情净值走势 tooltip 新增当期收益率：`当日收益 +¥123.45 (+1.23%)`，`pnlReturn` 取 `(当前净值 - 前净值) / 前净值`
- 基金详情新增「同类排名走势」卡片：AkShare `fund_open_fund_info_em(indicator="同类排名百分比")`
  取每日排名百分位（越低越好），Recharts 折线图 Y 轴反转（0% 在顶），1h 缓存
- 基金详情新增「基金档案」信息栏：基金经理/从业年限/基金规模/任期收益/运作费率，
  数据源为天天基金 pingzhongdata（`Data_currentFundManager` + `Data_fluctuationScale`），单请求，1h 缓存
- 新增 API：`GET /api/funds/{code}/ranking`、`GET /api/funds/{code}/profile`
- 新增测试：`tests/test_fetch_fund.py`（11 个用例，覆盖排名解析/缓存/档案解析/边界情况）

### Fixed
- 交易详情弹窗头部栏去掉重复渠道、网格去掉重复操作类型，新增 `Clock` 图标 + `is_t1` 确认时间行
- 基金重仓股市值单位修正：`持仓市值`（万元）前端 `/10000` 显示 `亿`
- 资产配置饼图 tooltip 条目文字颜色 dark 模式下不可读：Recharts 默认 tooltip 给条目设内联 `color: entry.color`，加 `itemStyle.color: hsl(var(--foreground))` 覆盖
- 同类排名 tooltip 条目文字颜色 dark 模式下不可读：同上，为排名折线图 tooltip 补 `itemStyle.color`

## [0.12.2] - 2026-07-31

### Fixed
- 定投两步 DB 写合并为一次：`execute_plan()` 原子写入 `last_run` + `next_run`，不再分两次调用 `update_auto_invest_plan`
- 月度计划不跳过当月：`_next_month_day()` 检查当月 target_day 是否已过，未过则用当月而非直接跳到下月
- `_convert_dow` 步进值跳过：正则加 `(?<!/)` lookbehind，`*/2`/`0-6/2`/`0/2` 中的步进值不被当作日值转换
- `useCountUp` formatter 用 `ref` 存储：从 `useEffect` deps 移除，避免 formatter 变化导致动画重启
- `fetch_estimate` stale-if-error：API 失败时优先返回过期缓存，仅首次失败且无缓存时才返回空列表
- `gztime` 从估值列名提取日期：`est_nav_col` 列名中提取日期代替 `datetime.now()`，避免跨日数据时间戳错误

## [0.12.1] - 2026-07-30

### Added
- 时区可配置：新增 `ZFUNDPILOT_TIMEZONE` 环境变量（默认 `Asia/Shanghai`），影响定时任务触发时间、
  交易日期、审计日志时间戳。`config.py` 集中定义 `TIMEZONE`，同步设置 `os.environ["TZ"]` 供 SQLite 使用，
  各模块不再各自定义 `_TZ`。
- 后端 i18n 结构化：`RiskFlag`/`Advice`/`CalcFeeResult`/`FundMeta`/`FetchResult`/`FeeRates`/
  `FundEstimate`/`FundCompareItem`/`CompareResponse`/`FilterResponse` 新增 `code`（或 `msg_code`）字段，
  前端按 code 翻译，不再依赖中文文本字符串匹配。
- 前端翻译映射：新建 `lib/backendLabels.ts`（风险提示/建议/费率/消息 code → 中英文翻译）
  + `lib/taxonomyLabels.ts`（基金类型/板块/渠道 → 中英文翻译），
  Risk.tsx/NavUpdate.tsx/FeeBreakdownCard.tsx 等组件按 code 渲染。
- 前端残留 i18n 补全：Positions/FundDetail/FundCompare/Overview 调用 translateFundType/translateSector/translateChannel
  翻译类型/板块/渠道标签，Settings.tsx AI 供应商名双语，api/client.ts 401 错误消息双语。
- 定投计划 API 字段校验：`AutoInvestPlanCreate` 加 Pydantic `field_validator` + `model_validator`，
  cadence 限 4 种，week/biweek 需 day_of_week(0-6)，month 需 day_of_month(1-31)。
- CI/CD 工作流：新建 `.github/workflows/ci.yml`，push/PR 自动运行 ruff check + pytest（3.10/3.11/3.12 matrix）+ tsc + build。
- 测试基础设施：新建 `tests/conftest.py`，提供 `make_plan`/`make_tx_row` fixtures + `PatchAutoInvest` 共享类。

### Changed
- T+1 确认改用 `is_t1` 布尔字段：`transactions` 表新增 `is_t1 INTEGER DEFAULT 0` 列
  （迁移自动回填 `note LIKE '%T+1确认%'` 的存量数据），`auto_invest.py` 设置 `is_t1=True`
  而非追加中文标记到 note，`analysis.py` 查 `is_t1=1` 而非 `note LIKE '%T+1确认%'`。
- 删除冗余 lib 文件调用：`rangeLabels.ts`/`actionLabels.ts` 的调用方改用 `t().rangeLabels`/`t().actionLabels`。
- `CronTrigger` 显式传 `timezone=config.TIMEZONE`，不再依赖宿主机时区。
- `_run_auto_invest()` 加 `threading.Lock`，防 bootstrap/cron/API 三入口并发重复执行。
- `api.py` `TransactionCreate` 加 `is_t1` 字段，create/update 端点传导 `is_t1`，修复手动编辑交易清除 T+1 标记的 bug。
- `config.py` 加 `time.tzset()`，确保 `os.environ["TZ"]` 生效，SQLite 时区与 Python 一致。
- `models.py` `Transaction.from_row()` 转换 `is_t1` int→bool，确保 JSON 序列化输出 `true`/`false`。
- ruff 忽略 E501（行超长），`analysis.py` imports 移顶，`fetch_fund.py` 清理未用变量。

### Fixed
- 定投错过期不再追补：`calculate_next_run` 锚定 `max(next_run, today)`，跳过停机期间错过的期数。
- 交易日顺延对将来日期生效：`_next_trading_day` 无净值数据时跳过周末（周六日 → 周一）。
- 估值 API 失败时负面缓存：AkShare 宕机时写 30s 空缓存，防止 FastAPI 线程池耗尽。
- `add_transaction` SQL 占位符数不匹配（10 列 vs 11 个 `?`）。
- `FeeBreakdownCard` 的 `HIDDEN_CODES` 遗漏 `pending_nav` 和 `no_buy_record`，
  导致待确认/无买入记录状态错误显示"免手续费"徽章。
- `api.py` calc-fee 早期返回补齐 `amount` + `nav` 字段，与 `CalcFeeResponse` 类型一致。

## [0.12.0] - 2026-07-29

### Added
- 全站国际化（i18n）：新建 `LanguageContext` + `useLang()` hook + `zh.ts`/`en.ts`
  翻译文件，所有页面和共享组件支持中英文切换。侧边栏新增全局语言切换按钮。
  `format.ts` 的 `money()`/`formatRelativeTime()` 按 lang 选 `¥`/`$` 和对应语言文案；
  `actionLabels`/`rangeLabels` 改为函数按 lang 返回。
- 交易记录点击查看详情：新建 `TransactionDetailDialog` 共享组件，Transactions 和 FundDetail
  页面的交易列表行点击即可打开只读详情弹窗，展示所有交易字段，支持「编辑」跳转。
  暗色主题自动适配。

### Fixed
- 定投执行 T+1 判定 bug：`execute_plan()` 原先永远加 `T+1确认` 标记，
  导致 09:00 定时执行的定投错误使用次日净值。现改为按当前时间判断：
  15:00 前不加标记（用当天净值），15:00 后加 `T+1确认` 标记（用次日净值）。

## [0.11.0] - 2026-07-28

### Added
- 定投计划自动执行：新增 `auto_invest.py` 模块 + `auto_invest_plans` 表 + 6 个 API 端点。
  支持 4 种频率（每个交易日/每周/每双周/每月），遇非交易日自动顺延到最近交易日。
  每次执行自动计算手续费，交易留 NULL 等 T+1 回填。定时任务每天 09:00 检查到期计划。
  前端 Transactions 页新增第 4 个 Tab「定投计划」，支持卡片列表 + 弹窗表单 + 立即执行/暂停/删除。
- 审计日志补全：新增交易、修改交易、CSV 导入（追加模式）写入审计日志
- 审计日志前端可展开 detail：点击查看格式化 JSON，不再被截断
- 净值回填审计日志：`backfill_transaction_navs()` 手动/定时更新净值后写入 `nav_backfill` 审计日志

### Fixed
- T+1 交易净值回填 bug：`backfill_transaction_navs()` 对 T+1 交易（note 含 'T+1确认'）
  错误使用了交易当日净值，而非次日净值。现改为检测 T+1 标记后用 `date+1` 查净值。
- 历史 T+1 错误数据自动迁移：启动时检测已错误回填的 T+1 交易（nav 来自当日而非次日），
  用次日净值重新计算份额/金额。修复详情写入审计日志，一次性执行，幂等，通过 `preferences` 表标记完成。

### Performance
- Docker 构建优化：pip install 层改用 requirements.txt，源码变更不再触发依赖重装
- update.sh 移除 builder prune，保留 Docker 层缓存加速增量构建

## [0.10.0] - 2026-07-26

### Added
- 定投策略回测：新增 `backtest.py` 模块 + `POST /api/backtest/dca` 端点 + `/backtest` 页面。
  支持指定基金 + 时间区间 + 定投频率（月/双周/周）+ 金额，用历史净值回测期末资产，
  对比「定投 vs 一次性投入」双方案。计入申购费和赎回费（复用费率表），
  计算 XIRR 年化、最大回撤、夏普比率（无风险利率 3%）。净值缺失自动拉取。
- AI API key 加密存储：新增 `crypto.py` 模块（Fernet: AES-128-CBC + HMAC-SHA256），
  `ai_config.json` 中的 `api_key` 落盘前自动加密（`enc:` 前缀），加载时自动解密。
  主密钥独立存于 `data/secret.key`（首启自动生成，权限 0o600），旧版明文 API key 自动兼容迁移。
  新增 `cryptography>=42.0.0` 依赖。

### Changed
- DEPLOY.md 多实例部署文档完善：新增独立目录方式（推荐）、container_name 冲突警告、故障排查；
  修正密码哈希说明（SHA-256 → bcrypt）
- `.env.example` 密码哈希说明同步修正为 bcrypt

## [0.9.1] - 2026-07-24

### Fixed
- 待确认买入（T+1 份额未知）不再产生虚假亏损：Position 新增 `pending_buy_cost` 字段，
  待确认金额从 `total_cost` 分离，市值含 pending 但浮动盈亏不受影响（与 `build_portfolio_curve` 中已有的 `pending_value_delta` 逻辑对齐）
- DB 覆盖路径 `est_pnl` 用精确净值差 `shares*(gsz-dwjz)` 计算，
  消除 `gszzl` 四舍五入导致的与基金详情页差异
- 买入按钮预填渠道：FundDetail / Positions 单渠道时自动传递 `channel` 参数，
  与卖出按钮逻辑一致

### Changed
- 实时估值数据源由天天基金 fundgz API 迁移至 AkShare `fund_value_estimation_em()`，
  覆盖全市场基金，30s 批量缓存

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
