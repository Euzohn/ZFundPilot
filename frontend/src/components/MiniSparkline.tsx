import { ResponsiveContainer, LineChart, Line } from "recharts"

/** 列表用迷你净值走势（归一化序列，首值=1）；不足 2 点降级为「—」。 */
export default function MiniSparkline({
  data,
  height = 28,
  title,
}: {
  data: number[]
  height?: number
  title?: string
}) {
  if (!data || data.length < 2) {
    return <span className="text-xs text-muted-foreground">—</span>
  }
  const chartData = data.map((v, i) => ({ i, v }))
  const rising = data[data.length - 1] >= data[0]
  return (
    <div style={{ height }} title={title} aria-label={title}>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={chartData} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
          <Line
            type="monotone"
            dataKey="v"
            stroke={rising ? "var(--gain-600)" : "var(--loss-600)"}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}