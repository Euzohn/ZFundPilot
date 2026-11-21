import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import type { ReactNode } from "react"
import { MemoryRouter } from "react-router-dom"
import { LanguageProvider } from "@/i18n/LanguageContext"
import { toast } from "sonner"
import type {
  AgentTokenInfo,
  BackupPreview,
  KeywordMaps,
  SchedulerStatus,
  TpSlConfig,
} from "@/api/types"
import Settings from "./Settings"

const mocks = vi.hoisted(() => ({
  getPreferences: vi.fn(),
  getSchedulerStatus: vi.fn(),
  getTpSlConfig: vi.fn(),
  getAuthStatus: vi.fn(),
  getMe: vi.fn(),
  getAIConfig: vi.fn(),
  getVisionConfig: vi.fn(),
  getAIUsage: vi.fn(),
  getAIUsageDaily: vi.fn(),
  getKeywordMaps: vi.fn(),
  saveKeywordMaps: vi.fn(),
  getAgentWriteSettings: vi.fn(),
  getAgentTokens: vi.fn(),
  createAgentToken: vi.fn(),
  revokeAgentToken: vi.fn(),
  getAuditLogs: vi.fn(),
  preflightBackup: vi.fn(),
  restoreBackup: vi.fn(),
  updateTpSlConfig: vi.fn(),
  savePreferences: vi.fn(),
}))

vi.mock("@/api/client", () => ({ api: mocks }))
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}))

// jsdom 无布局尺寸，recharts 用桩组件替代
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children?: ReactNode }) => <div data-testid="chart">{children}</div>,
  LineChart: () => <div data-testid="line" />,
  Line: () => null,
}))

function keywordMaps(overrides: Partial<KeywordMaps> = {}): KeywordMaps {
  return {
    type_defaults: [{ keyword: "债券型", mapped: "债券" }],
    sector_defaults: [{ keyword: "新能源", mapped: "新能源" }],
    type_custom: [{ keyword: "自定义类型", mapped: "股票" }],
    sector_custom: [{ keyword: "白酒", mapped: "消费" }, { keyword: "半导体", mapped: "科技" }],
    available_types: ["股票", "债券", "货币"],
    available_sectors: ["消费", "科技", "新能源"],
    ...overrides,
  }
}

function schedulerStatus(overrides: Partial<SchedulerStatus> = {}): SchedulerStatus {
  return {
    enabled: true,
    cron: "0 21 * * 1-5",
    next_run: null,
    last_run: null,
    last_results: null,
    dividend_enabled: true,
    dividend_last_run: null,
    tp_sl_enabled: true,
    tp_sl_last_run: null,
    ...overrides,
  }
}

function tpSlConfig(overrides: Partial<TpSlConfig> = {}): TpSlConfig {
  return {
    enabled: "true",
    take_profit_enabled: "true",
    stop_loss_enabled: "true",
    take_profit: "0.2",
    stop_loss: "-0.15",
    reset_ratio: "0.8",
    ...overrides,
  }
}

function tokenInfo(overrides: Partial<AgentTokenInfo> = {}): AgentTokenInfo {
  return {
    id: 1,
    name: "claude-desktop",
    token_prefix: "zf_abcd",
    scopes: "portfolio:read funds:read health:read",
    created_at: "2026-11-20T10:00:00+08:00",
    expires_at: null,
    last_used_at: null,
    revoked_at: null,
    active: true,
    ...overrides,
  }
}

function backupPreview(): BackupPreview {
  return {
    format: "zfundpilot-backup",
    format_version: 2,
    app_version: "0.28.1",
    created_at: "2026-11-20T10:00:00+08:00",
    tables: { transactions: { rows: 10, current_rows: 5 } },
    total_rows: 10,
    current_total_rows: 5,
    replace_all: true,
    can_restore: true,
    warnings: [],
    excluded: {},
    excluded_secrets: {},
    safety_backup: "safety.zip",
  }
}

function renderPage(initialEntry = "/?tab=prefs") {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <LanguageProvider>
        <Settings />
      </LanguageProvider>
    </MemoryRouter>,
  )
}

// 关键词映射卡片（偏好设置 tab 内），用于把查询限定在本卡片，避免与渠道管理等同名按钮冲突
function keywordCard(): HTMLElement {
  return screen.getByText("关键词映射").closest(".rounded-xl") as HTMLElement
}

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset()
  mocks.getPreferences.mockResolvedValue({})
  mocks.getSchedulerStatus.mockResolvedValue(schedulerStatus())
  mocks.getTpSlConfig.mockResolvedValue(tpSlConfig())
  mocks.getAuthStatus.mockResolvedValue({ required: true, version: "0.28.1" })
  mocks.getMe.mockResolvedValue({ username: "admin" })
  mocks.getAIConfig.mockResolvedValue({ base_url: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k", has_key: true, web_search: true, custom_prompt: "" })
  mocks.getVisionConfig.mockResolvedValue({ base_url: "https://open.bigmodel.cn/v1", model: "glm-4v-plus", has_key: true })
  mocks.getAIUsage.mockResolvedValue({ today: 0, total: 0, recent: [] })
  mocks.getAIUsageDaily.mockResolvedValue([])
  mocks.getKeywordMaps.mockResolvedValue(keywordMaps())
  mocks.saveKeywordMaps.mockResolvedValue({ ok: true })
  mocks.getAgentWriteSettings.mockResolvedValue({ enabled: false, locked: false, can_enable: true, source: "settings" })
  mocks.getAgentTokens.mockResolvedValue({ tokens: [], scopes: [] })
  mocks.createAgentToken.mockResolvedValue({ token: "zf_secret_plaintext", token_info: tokenInfo(), message: "ok" })
  mocks.revokeAgentToken.mockResolvedValue({ ok: true })
  mocks.getAuditLogs.mockResolvedValue([])
  mocks.preflightBackup.mockResolvedValue(backupPreview())
  mocks.restoreBackup.mockResolvedValue({ ok: true, restored: {}, total_rows: 10, safety_backup: "safety.zip", replace_all: true })
  mocks.updateTpSlConfig.mockResolvedValue({ ok: true })
  mocks.savePreferences.mockResolvedValue({ ok: true })
})

describe("Settings 自定义关键词保存失败处理", () => {
  it("新增保存失败：toast.error 并回滚本地状态，保留用户输入", async () => {
    mocks.saveKeywordMaps.mockRejectedValueOnce(new Error("网络错误"))
    renderPage()
    await screen.findByText("关键词映射")
    const card = keywordCard()

    fireEvent.change(within(card).getByPlaceholderText("如 新能源车"), { target: { value: "新能源车" } })
    fireEvent.change(within(card).getByRole("combobox"), { target: { value: "科技" } })
    fireEvent.click(within(card).getByRole("button", { name: "新增" }))

    await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalledWith(expect.stringContaining("保存失败")))
    // 回滚：乐观新增的条目不应残留
    expect(within(card).queryByText("新能源车")).not.toBeInTheDocument()
    expect(within(card).getByText("白酒")).toBeInTheDocument()
    // 失败时保留输入便于重试
    expect(within(card).getByPlaceholderText("如 新能源车")).toHaveValue("新能源车")
    // 确实尝试持久化了新增条目
    expect(mocks.saveKeywordMaps).toHaveBeenCalledTimes(1)
    expect(mocks.saveKeywordMaps.mock.calls[0][1]).toContain("新能源车")
  })

  it("新增保存成功：清空输入并保留新条目，不报错", async () => {
    renderPage()
    await screen.findByText("关键词映射")
    const card = keywordCard()

    fireEvent.change(within(card).getByPlaceholderText("如 新能源车"), { target: { value: "新能源车" } })
    fireEvent.change(within(card).getByRole("combobox"), { target: { value: "科技" } })
    fireEvent.click(within(card).getByRole("button", { name: "新增" }))

    await waitFor(() => expect(mocks.saveKeywordMaps).toHaveBeenCalledTimes(1))
    expect(within(card).getByText("新能源车")).toBeInTheDocument()
    expect(within(card).getByPlaceholderText("如 新能源车")).toHaveValue("")
    expect(vi.mocked(toast.error)).not.toHaveBeenCalled()
  })

  it("删除保存失败：toast.error 并回滚，被删条目仍在", async () => {
    mocks.saveKeywordMaps.mockRejectedValueOnce(new Error("500"))
    renderPage()
    await screen.findByText("关键词映射")
    const card = keywordCard()

    fireEvent.click(within(card).getAllByTitle("删除")[0])

    await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalledWith(expect.stringContaining("保存失败")))
    expect(within(card).getByText("白酒")).toBeInTheDocument()
    expect(within(card).getByText("半导体")).toBeInTheDocument()
    // 尝试持久化的是删除后的列表（不含白酒）
    expect(mocks.saveKeywordMaps.mock.calls[0][1]).not.toContain("白酒")
  })

  it("排序保存失败：toast.error 并回滚到原顺序", async () => {
    mocks.saveKeywordMaps.mockRejectedValueOnce(new Error("500"))
    renderPage()
    await screen.findByText("关键词映射")
    const card = keywordCard()

    const listBefore = screen.getByText("自定义关键词（2 个）").parentElement!
    expect(listBefore.textContent!.indexOf("白酒")).toBeLessThan(listBefore.textContent!.indexOf("半导体"))

    // 第一行下移 → 试图变为 [半导体, 白酒]
    fireEvent.click(within(card).getAllByTitle("下移")[0])

    await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalledWith(expect.stringContaining("保存失败")))
    expect(mocks.saveKeywordMaps.mock.calls[0][1].indexOf("半导体")).toBeLessThan(mocks.saveKeywordMaps.mock.calls[0][1].indexOf("白酒"))
    // 回滚后 UI 恢复原顺序
    const listAfter = screen.getByText("自定义关键词（2 个）").parentElement!
    expect(listAfter.textContent!.indexOf("白酒")).toBeLessThan(listAfter.textContent!.indexOf("半导体"))
  })

  it("重置保存失败：toast.error 并回滚，自定义关键词不被清空", async () => {
    mocks.saveKeywordMaps.mockRejectedValueOnce(new Error("500"))
    renderPage()
    await screen.findByText("关键词映射")
    const card = keywordCard()

    fireEvent.click(within(card).getByRole("button", { name: "重置自定义" }))
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "确认" }))

    await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalledWith(expect.stringContaining("保存失败")))
    expect(mocks.saveKeywordMaps).toHaveBeenCalledWith("[]", "[]")
    expect(within(card).getByText("白酒")).toBeInTheDocument()
    expect(within(card).getByText("半导体")).toBeInTheDocument()
  })

  it("重置保存成功：toast.success 并清空自定义关键词", async () => {
    renderPage()
    await screen.findByText("关键词映射")
    const card = keywordCard()

    fireEvent.click(within(card).getByRole("button", { name: "重置自定义" }))
    fireEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "确认" }))

    await waitFor(() => expect(vi.mocked(toast.success)).toHaveBeenCalledWith("已重置所有自定义关键词"))
    expect(mocks.saveKeywordMaps).toHaveBeenCalledWith("[]", "[]")
    expect(within(card).queryByText("白酒")).not.toBeInTheDocument()
  })
})

describe("Settings 备份恢复后刷新已加载配置", () => {
  it("恢复成功后重新拉取调度/止盈止损/AI/视觉/关键词配置与偏好", async () => {
    mocks.getPreferences.mockResolvedValue({
      channels: JSON.stringify(["支付宝", "银行"]),
      channel_colors: JSON.stringify({ "支付宝": "#3b82f6" }),
      color_theme: "china",
    })
    const { container } = renderPage()
    await screen.findByText("关键词映射")

    // 挂载时各配置已加载一次
    expect(mocks.getSchedulerStatus).toHaveBeenCalledTimes(1)
    expect(mocks.getTpSlConfig).toHaveBeenCalledTimes(1)
    expect(mocks.getAIConfig).toHaveBeenCalledTimes(1)
    expect(mocks.getVisionConfig).toHaveBeenCalledTimes(1)
    expect(mocks.getKeywordMaps).toHaveBeenCalledTimes(1)

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(["backup"], "backup.zip", { type: "application/zip" })
    fireEvent.change(fileInput, { target: { files: [file] } })

    fireEvent.click(await screen.findByRole("button", { name: "恢复此备份" }))
    fireEvent.click(await screen.findByRole("button", { name: "确认恢复" }))

    await waitFor(() => expect(mocks.restoreBackup).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(vi.mocked(toast.success)).toHaveBeenCalledWith(expect.stringContaining("恢复完成")))

    // 各 useApi 配置重新加载
    await waitFor(() => expect(mocks.getSchedulerStatus).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(mocks.getTpSlConfig).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(mocks.getAIConfig).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(mocks.getVisionConfig).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(mocks.getKeywordMaps).toHaveBeenCalledTimes(2))
    // 偏好（渠道/颜色）经 save* 回写刷新缓存
    await waitFor(() => expect(mocks.savePreferences).toHaveBeenCalled())
    expect(mocks.savePreferences.mock.calls.some((c) => JSON.stringify(c[0]).includes("银行"))).toBe(true)
  })

  it("恢复失败：toast.error 且不触发配置重载", async () => {
    mocks.restoreBackup.mockRejectedValueOnce(new Error("恢复失败，当前数据已回滚"))
    const { container } = renderPage()
    await screen.findByText("关键词映射")

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(fileInput, { target: { files: [new File(["x"], "b.zip", { type: "application/zip" })] } })
    fireEvent.click(await screen.findByRole("button", { name: "恢复此备份" }))
    fireEvent.click(await screen.findByRole("button", { name: "确认恢复" }))

    await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalledWith(expect.stringContaining("恢复失败")))
    expect(mocks.getSchedulerStatus).toHaveBeenCalledTimes(1)
    expect(mocks.getKeywordMaps).toHaveBeenCalledTimes(1)
  })
})

describe("Settings Agent 令牌明文切 tab 不丢失", () => {
  it("签发后切到其它 tab 再切回，明文仍可见可复制", async () => {
    renderPage("/?tab=agent")
    // 等待 authRequired 解析后 agent 面板挂载
    const createBtn = await screen.findByRole("button", { name: "签发令牌" })

    fireEvent.change(screen.getByPlaceholderText("例如：claude-desktop"), { target: { value: "claude-desktop" } })
    fireEvent.click(createBtn)

    await waitFor(() => expect(mocks.createAgentToken).toHaveBeenCalledTimes(1))
    expect(await screen.findByDisplayValue("zf_secret_plaintext")).toBeInTheDocument()

    // 切到偏好设置 tab：agent 面板卸载，明文输入框消失
    // Radix Tabs 通过 onMouseDown 激活，fireEvent.click 不触发切换
    const prefsTab = screen.getByRole("tab", { name: /偏好设置/ })
    fireEvent.mouseDown(prefsTab)
    fireEvent.click(prefsTab)
    await waitFor(() => expect(screen.queryByDisplayValue("zf_secret_plaintext")).not.toBeInTheDocument())

    // 切回 agent tab：明文仍在（状态提升到父级）
    const agentTab = screen.getByRole("tab", { name: /Agent 接入/ })
    fireEvent.mouseDown(agentTab)
    fireEvent.click(agentTab)
    expect(await screen.findByDisplayValue("zf_secret_plaintext")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "复制" })).toBeInTheDocument()
  })

  it("撤销当前令牌后明文展示清除", async () => {
    mocks.getAgentTokens.mockResolvedValue({ tokens: [tokenInfo()], scopes: [] })
    renderPage("/?tab=agent")
    await screen.findByRole("button", { name: "签发令牌" })

    fireEvent.change(screen.getByPlaceholderText("例如：claude-desktop"), { target: { value: "claude-desktop" } })
    fireEvent.click(screen.getByRole("button", { name: "签发令牌" }))
    expect(await screen.findByDisplayValue("zf_secret_plaintext")).toBeInTheDocument()

    // 撤销列表中的同 id 令牌
    fireEvent.click(screen.getByRole("button", { name: /撤销/ }))
    const dialog = await screen.findByRole("alertdialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "撤销" }))

    await waitFor(() => expect(mocks.revokeAgentToken).toHaveBeenCalledWith(1))
    await waitFor(() => expect(screen.queryByDisplayValue("zf_secret_plaintext")).not.toBeInTheDocument())
  })
})

describe("Settings 止盈止损保存路径（B6 后端契约：负 stop_loss 合法）", () => {
  it("保存时把止损百分比转为负值提交，成功后重载配置", async () => {
    renderPage()
    const card = (await screen.findByText("止盈止损提醒")).closest(".rounded-xl") as HTMLElement

    const stopLossInput = within(card).getByDisplayValue("15")
    fireEvent.change(stopLossInput, { target: { value: "10" } })
    fireEvent.click(within(card).getByRole("button", { name: "保存" }))

    await waitFor(() => expect(mocks.updateTpSlConfig).toHaveBeenCalledTimes(1))
    expect(mocks.updateTpSlConfig).toHaveBeenCalledWith(expect.objectContaining({
      take_profit: "0.2",
      stop_loss: "-0.1",
      reset_ratio: "0.8",
    }))
    await waitFor(() => expect(vi.mocked(toast.success)).toHaveBeenCalledWith("止盈止损配置已保存"))
    await waitFor(() => expect(mocks.getTpSlConfig).toHaveBeenCalledTimes(2))
  })

  it("保存失败：toast.error 提示", async () => {
    mocks.updateTpSlConfig.mockRejectedValueOnce(new Error("422"))
    renderPage()
    const card = (await screen.findByText("止盈止损提醒")).closest(".rounded-xl") as HTMLElement

    fireEvent.click(within(card).getByRole("button", { name: "保存" }))

    await waitFor(() => expect(vi.mocked(toast.error)).toHaveBeenCalledWith(expect.stringContaining("保存失败")))
  })
})