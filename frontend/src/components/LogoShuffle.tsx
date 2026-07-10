import { useId } from "react"

/** B11 翻牌洗牌 — 四片花瓣像扑克牌依次翻面旋转 + Z 闪烁，适合加载状态 */
export default function LogoShuffle({ className = "h-12 w-12" }: { className?: string }) {
  const id = useId()
  return (
    <svg viewBox="0 0 64 64" className={className} aria-label="加载中">
      <defs>
        <linearGradient id={`shuffle-bg-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#0F1F3D" />
          <stop offset="100%" stopColor="#3B82F6" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="14" fill={`url(#shuffle-bg-${id})`} />
      <g className="la-shuffle-f1"><polygon points="32,6 36,27 32,32 28,27" fill="white" fillOpacity={0.42} /></g>
      <g className="la-shuffle-f2"><polygon points="58,32 37,36 32,32 37,28" fill="white" fillOpacity={0.42} /></g>
      <g className="la-shuffle-f3"><polygon points="32,58 28,37 32,32 36,37" fill="white" fillOpacity={0.34} /></g>
      <g className="la-shuffle-f4"><polygon points="6,32 27,28 32,32 27,36" fill="white" fillOpacity={0.34} /></g>
      <circle cx="32" cy="32" r="11" fill="white" />
      <circle cx="32" cy="32" r="12.5" fill="none" stroke="#F59E0B" strokeWidth={0.8} opacity={0.5} />
      <g className="la-shuffle-z">
        <path d="M 25 28 L 39 28 L 25 36 L 38 34" stroke="#F59E0B" strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </g>
    </svg>
  )
}
