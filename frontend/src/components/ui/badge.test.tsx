import { describe, expect, it } from "vitest"
import { render, screen } from "@testing-library/react"
import { Badge, badgeVariants } from "./badge"

describe("Badge success/warning 变体类名", () => {
  it("语义 token 半透明底 + 暗色提亮语义文字色，不再硬编码浅底", () => {
    const success = badgeVariants({ variant: "success" })
    expect(success).toContain("bg-success/15")
    expect(success).toContain("text-green-800")
    expect(success).toContain("dark:text-success")
    expect(success).not.toContain("bg-green-100")
    const warning = badgeVariants({ variant: "warning" })
    expect(warning).toContain("bg-warning/15")
    expect(warning).toContain("text-amber-800")
    expect(warning).toContain("dark:text-warning")
    expect(warning).not.toContain("bg-amber-100")
  })

  it("渲染带上对应类名", () => {
    render(<Badge variant="success">有效</Badge>)
    expect(screen.getByText("有效").className).toContain("bg-success/15")
    render(<Badge variant="warning">即将过期</Badge>)
    expect(screen.getByText("即将过期").className).toContain("bg-warning/15")
  })
})

// ---- WCAG 对比度回归 ----
// token 数值镜像 src/index.css（:root 与 .dark 的 --success/--warning）。
// 徽章可能落在 background 或 card 上：亮色两者皆白；暗色取较亮的 card 作保守基底。
// 亮色文字为 text-green-800/#166534、text-amber-800/#92400e（Tailwind 调色板），
// 暗色文字为提亮后的语义色。要求两种主题、常态(15%)/悬停(25%) 均 ≥ 4.5:1（AA 小字号）。
type RGB = [number, number, number]

function hsl(h: number, s: number, l: number): RGB {
  const sn = s / 100
  const ln = l / 100
  const c = (1 - Math.abs(2 * ln - 1)) * sn
  const hp = h / 60
  const x = c * (1 - Math.abs((hp % 2) - 1))
  const [r, g, b] =
    hp < 1 ? [c, x, 0] : hp < 2 ? [x, c, 0] : hp < 3 ? [0, c, x] :
    hp < 4 ? [0, x, c] : hp < 5 ? [x, 0, c] : [c, 0, x]
  const m = ln - c / 2
  return [(r + m) * 255, (g + m) * 255, (b + m) * 255]
}

function hex(value: string): RGB {
  return [
    parseInt(value.slice(1, 3), 16),
    parseInt(value.slice(3, 5), 16),
    parseInt(value.slice(5, 7), 16),
  ]
}

function luminance([r, g, b]: RGB): number {
  const f = (v: number) => {
    const c = v / 255
    return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
  }
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
}

function over(fg: RGB, bg: RGB, alpha: number): RGB {
  return [
    alpha * fg[0] + (1 - alpha) * bg[0],
    alpha * fg[1] + (1 - alpha) * bg[1],
    alpha * fg[2] + (1 - alpha) * bg[2],
  ]
}

function contrast(a: RGB, b: RGB): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const WHITE: RGB = [255, 255, 255]
const DARK_CARD = hsl(240, 6, 10) // .dark --card

const THEMES = {
  light: {
    surface: WHITE,
    success: { text: hex("#166534"), token: hsl(142, 71, 45) },
    warning: { text: hex("#92400e"), token: hsl(38, 92, 50) },
  },
  dark: {
    surface: DARK_CARD,
    success: { text: hsl(142, 71, 50), token: hsl(142, 71, 50) },
    warning: { text: hsl(38, 92, 55), token: hsl(38, 92, 55) },
  },
} as const

const rows = (Object.keys(THEMES) as Array<keyof typeof THEMES>).flatMap((theme) =>
  (["success", "warning"] as const).flatMap((variant) =>
    [0.15, 0.25].map((alpha) => ({
      theme,
      variant,
      alpha,
      surface: THEMES[theme].surface as RGB,
      text: THEMES[theme][variant].text as RGB,
      token: THEMES[theme][variant].token as RGB,
    })),
  ),
)

describe("Badge success/warning 对比度（亮/暗主题）", () => {
  it.each(rows)(
    "$theme $variant 背景透明度 $alpha 对比度 ≥ 4.5:1",
    ({ text, token, surface, alpha }) => {
      expect(contrast(text, over(token, surface, alpha))).toBeGreaterThanOrEqual(4.5)
    },
  )
})