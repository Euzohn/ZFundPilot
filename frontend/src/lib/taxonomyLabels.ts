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
