import { getCurrentLang } from "@/i18n/LanguageContext"

type Bilingual = { zh: string; en: string }

// ── Fund types ──
export const FUND_TYPES: Record<string, Bilingual> = {
  "混合型": { zh: "混合型", en: "Hybrid" },
  "指数型": { zh: "指数型", en: "Index" },
  "债券型": { zh: "债券型", en: "Bond" },
  "股票型": { zh: "股票型", en: "Equity" },
  "QDII": { zh: "QDII", en: "QDII" },
  "其它": { zh: "其它", en: "Other" },
}

// ── Channels ──
export const CHANNELS: Record<string, Bilingual> = {
  "支付宝": { zh: "支付宝", en: "Alipay" },
  "理财通": { zh: "理财通", en: "Tencent Licaitong" },
  "天天基金": { zh: "天天基金", en: "Tiantian Fund" },
  "基金公司直销": { zh: "基金公司直销", en: "Direct" },
  "银行": { zh: "银行", en: "Bank" },
  "券商": { zh: "券商", en: "Broker" },
  "其它": { zh: "其它", en: "Other" },
}

// ── Sectors ──
export const SECTORS: Record<string, Bilingual> = {
  "人工智能": { zh: "人工智能", en: "AI" },
  "AI应用": { zh: "AI应用", en: "AI Applications" },
  "国产算力": { zh: "国产算力", en: "Domestic Computing" },
  "半导体材料设备": { zh: "半导体材料设备", en: "Semiconductor Materials" },
  "半导体": { zh: "半导体", en: "Semiconductors" },
  "通信": { zh: "通信", en: "Telecom" },
  "商业航天": { zh: "商业航天", en: "Commercial Aerospace" },
  "机器人": { zh: "机器人", en: "Robotics" },
  "PCB": { zh: "PCB", en: "PCB" },
  "大科技": { zh: "大科技", en: "Broad Tech" },
  "港股科技": { zh: "港股科技", en: "HK Tech" },
  "科技": { zh: "科技", en: "Technology" },
  "双创50": { zh: "双创50", en: "STAR/ChiNext 50" },
  "信息技术": { zh: "信息技术", en: "IT" },
  "电子": { zh: "电子", en: "Electronics" },
  "稀土永磁": { zh: "稀土永磁", en: "Rare Earth" },
  "有色金属": { zh: "有色金属", en: "Non-ferrous Metals" },
  "新能源": { zh: "新能源", en: "New Energy" },
  "创新药": { zh: "创新药", en: "Innovative Drugs" },
  "医药": { zh: "医药", en: "Healthcare" },
  "证券": { zh: "证券", en: "Securities" },
  "银行": { zh: "银行", en: "Bank" },
  "保险": { zh: "保险", en: "Insurance" },
  "消费": { zh: "消费", en: "Consumer" },
  "煤炭": { zh: "煤炭", en: "Coal" },
  "钢铁": { zh: "钢铁", en: "Steel" },
  "黄金": { zh: "黄金", en: "Gold" },
  "高端装备": { zh: "高端装备", en: "High-end Equipment" },
  "先进制造": { zh: "先进制造", en: "Advanced Manufacturing" },
  "电力设备": { zh: "电力设备", en: "Power Equipment" },
  "纳指": { zh: "纳指", en: "Nasdaq" },
  "标普": { zh: "标普", en: "S&P" },
  "港股": { zh: "港股", en: "HK Stocks" },
  "海外基金": { zh: "海外基金", en: "Overseas Funds" },
  "沪深300": { zh: "沪深300", en: "CSI 300" },
  "中证500": { zh: "中证500", en: "CSI 500" },
  "中证1000": { zh: "中证1000", en: "CSI 1000" },
  "创业板": { zh: "创业板", en: "ChiNext" },
  "北证50": { zh: "北证50", en: "BSE 50" },
  "军工": { zh: "军工", en: "Defense" },
  "房地产": { zh: "房地产", en: "Real Estate" },
  "化工": { zh: "化工", en: "Chemicals" },
  "传媒": { zh: "传媒", en: "Media" },
  "农业": { zh: "农业", en: "Agriculture" },
  "环保": { zh: "环保", en: "Environmental" },
  "电力": { zh: "电力", en: "Power" },
  "建筑建材": { zh: "建筑建材", en: "Construction Materials" },
  "交运物流": { zh: "交运物流", en: "Transport & Logistics" },
  "石油石化": { zh: "石油石化", en: "Petroleum & Petrochem" },
  "旅游": { zh: "旅游", en: "Tourism" },
  "其它": { zh: "其它", en: "Other" },
}

// ── Fund type dot colors (avoid green/red to not clash with gain/loss) ──
export const FUND_TYPE_DOT: Record<string, string> = {
  "混合型": "bg-amber-500",
  "指数型": "bg-teal-500",
  "债券型": "bg-sky-500",
  "股票型": "bg-violet-500",
  "QDII": "bg-indigo-500",
  "其它": "bg-zinc-400",
}

// ── Risk levels ──
export const RISK_LEVELS: Record<string, Bilingual> = {
  "低风险": { zh: "低风险", en: "Low" },
  "中低风险": { zh: "中低风险", en: "Low-Medium" },
  "中风险": { zh: "中风险", en: "Medium" },
  "中高风险": { zh: "中高风险", en: "Medium-High" },
  "高风险": { zh: "高风险", en: "High" },
}

export const RISK_LEVEL_DOT: Record<string, string> = {
  "低风险": "bg-emerald-500",
  "中低风险": "bg-teal-500",
  "中风险": "bg-amber-500",
  "中高风险": "bg-orange-500",
  "高风险": "bg-rose-500",
}

// ── 行业分类（证监会 CSRC + GICS 全球行业分类，基金行业配置数据源）──
// CSRC ~19 类用于境内基金；GICS 11 类用于 QDII 基金（两套分类可能在同一基金数据中混合出现）
export const INDUSTRIES: Record<string, Bilingual> = {
  // ── CSRC 证监会 ──
  "农、林、牧、渔业": { zh: "农、林、牧、渔业", en: "Agriculture" },
  "采矿业": { zh: "采矿业", en: "Mining" },
  "制造业": { zh: "制造业", en: "Manufacturing" },
  "电力、热力、燃气及水生产和供应业": { zh: "公用事业", en: "Utilities" },
  "建筑业": { zh: "建筑业", en: "Construction" },
  "批发和零售业": { zh: "批发零售", en: "Wholesale & Retail" },
  "交通运输、仓储和邮政业": { zh: "交通运输", en: "Transportation" },
  "住宿和餐饮业": { zh: "住宿餐饮", en: "Accommodation & Food" },
  "信息传输、软件和信息技术服务业": { zh: "信息技术", en: "IT & Software" },
  "金融业": { zh: "金融业", en: "Financials" },
  "房地产业": { zh: "房地产", en: "Real Estate" },
  "租赁和商务服务业": { zh: "租赁商务", en: "Leasing & Business" },
  "科学研究和技术服务业": { zh: "科研技术", en: "Scientific Research" },
  "水利、环境和公共设施管理业": { zh: "环境设施", en: "Environment & Utilities" },
  "居民服务、修理和其他服务业": { zh: "居民服务", en: "Resident Services" },
  "教育": { zh: "教育", en: "Education" },
  "卫生和社会工作": { zh: "卫生社会工作", en: "Healthcare" },
  "文化、体育和娱乐业": { zh: "文体娱乐", en: "Culture & Sports" },
  "综合": { zh: "综合", en: "Conglomerate" },
  // ── GICS 全球行业分类（QDII 基金）──
  "非必需消费品": { zh: "非必需消费品", en: "Consumer Discretionary" },
  "必需消费品": { zh: "必需消费品", en: "Consumer Staples" },
  "医疗保健": { zh: "医疗保健", en: "Health Care" },
  "信息技术": { zh: "信息技术", en: "Information Technology" },
  "通信服务": { zh: "通信服务", en: "Communication Services" },
  "能源": { zh: "能源", en: "Energy" },
  "材料": { zh: "材料", en: "Materials" },
  "工业": { zh: "工业", en: "Industrials" },
  "公用事业": { zh: "公用事业", en: "Utilities" },
  // ── 别名/变体 ──
  "非日常生活消费品": { zh: "非必需消费品", en: "Consumer Discretionary" },
  "日常生活消费品": { zh: "必需消费品", en: "Consumer Staples" },
  "信息科技": { zh: "信息技术", en: "Information Technology" },
  "科技": { zh: "科技", en: "Technology" },
  "电信服务": { zh: "电信服务", en: "Telecommunications" },
  "通讯": { zh: "通讯", en: "Telecom" },
  "金融": { zh: "金融业", en: "Financials" },
  "房地产": { zh: "房地产", en: "Real Estate" },
}

// ── Helper functions ──
export function translateFundType(type: string): string {
  const lang = getCurrentLang()
  return FUND_TYPES[type]?.[lang] ?? type
}

export function translateChannel(channel: string): string {
  const lang = getCurrentLang()
  return CHANNELS[channel]?.[lang] ?? channel
}

export function translateSector(sector: string): string {
  const lang = getCurrentLang()
  return SECTORS[sector]?.[lang] ?? sector
}

export function translateRiskLevel(level: string): string {
  const lang = getCurrentLang()
  return RISK_LEVELS[level]?.[lang] ?? level
}

export function translateIndustry(industry: string): string {
  const lang = getCurrentLang()
  return INDUSTRIES[industry]?.[lang] ?? industry
}
