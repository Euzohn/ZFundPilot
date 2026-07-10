import { useId } from "react"

/** B1 金光入场 — 花瓣飞入 → 圆形弹出 → 金环描绘 → Z 金光绘制 + 持续辉光 */
export default function LogoSplash({ className = "h-16 w-16" }: { className?: string }) {
  const id = useId()
  return (
    <svg viewBox="0 0 64 64" className={className} aria-label="ZFundPilot">
      <defs>
        <linearGradient id={`splash-bg-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#0F1F3D" />
          <stop offset="100%" stopColor="#3B82F6" />
        </linearGradient>
      </defs>
      <g className="la-splash-bg" style={{ transformBox: "fill-box", transformOrigin: "center" }}>
        <rect width="64" height="64" rx="14" fill={`url(#splash-bg-${id})`} />
      </g>
      <g className="la-splash-d1" style={{ transformBox: "fill-box", transformOrigin: "center" }}><polygon points="32,6 36,27 32,32 28,27" fill="white" fillOpacity={0.42} /></g>
      <g className="la-splash-d2" style={{ transformBox: "fill-box", transformOrigin: "center" }}><polygon points="58,32 37,36 32,32 37,28" fill="white" fillOpacity={0.42} /></g>
      <g className="la-splash-d3" style={{ transformBox: "fill-box", transformOrigin: "center" }}><polygon points="32,58 28,37 32,32 36,37" fill="white" fillOpacity={0.34} /></g>
      <g className="la-splash-d4" style={{ transformBox: "fill-box", transformOrigin: "center" }}><polygon points="6,32 27,28 32,32 27,36" fill="white" fillOpacity={0.34} /></g>
      <g className="la-splash-c" style={{ transformBox: "fill-box", transformOrigin: "center" }}><circle cx="32" cy="32" r="11" fill="white" /></g>
      <circle cx="32" cy="32" r="12.5" fill="none" stroke="#F59E0B" strokeWidth={0.8} className="la-splash-ring" />
      <g className="la-splash-z la-splash-zg">
        <path d="M 25 28 L 39 28 L 25 36 L 38 34" stroke="#F59E0B" strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </g>
    </svg>
  )
}
