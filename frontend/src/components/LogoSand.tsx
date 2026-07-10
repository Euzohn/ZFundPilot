import { useId } from "react"

/** B12 金砂成型 — 金砂颗粒逐个掉落堆积 + 组装成完整 Logo + 持续星点闪烁 */
export default function LogoSand({ className = "h-16 w-16" }: { className?: string }) {
  const id = useId()
  return (
    <svg viewBox="0 0 64 64" className={className} aria-label="ZFundPilot">
      <defs>
        <linearGradient id={`sand-bg-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#0F1F3D" />
          <stop offset="100%" stopColor="#3B82F6" />
        </linearGradient>
      </defs>
      <g className="la-sand-bg"><rect width="64" height="64" rx="14" fill={`url(#sand-bg-${id})`} /></g>
      <g className="la-sand-d1"><polygon points="32,6 36,27 32,32 28,27" fill="white" fillOpacity={0.42} /></g>
      <g className="la-sand-d2"><polygon points="58,32 37,36 32,32 37,28" fill="white" fillOpacity={0.42} /></g>
      <g className="la-sand-d3"><polygon points="32,58 28,37 32,32 36,37" fill="white" fillOpacity={0.34} /></g>
      <g className="la-sand-d4"><polygon points="6,32 27,28 32,32 27,36" fill="white" fillOpacity={0.34} /></g>
      <g className="la-sand-c"><circle cx="32" cy="32" r="11" fill="white" /></g>
      <g className="la-sand-ring"><circle cx="32" cy="32" r="12.5" fill="none" stroke="#F59E0B" strokeWidth={0.8} opacity={0.5} /></g>
      <g className="la-sand-z"><path d="M 25 28 L 39 28 L 25 36 L 38 34" stroke="#F59E0B" strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round" fill="none" /></g>
      <circle cx="20" cy="18" r="1" fill="#FBBF24" className="la-sand-s1" />
      <circle cx="44" cy="22" r="1" fill="#FBBF24" className="la-sand-s2" />
      <circle cx="38" cy="46" r="1" fill="#FBBF24" className="la-sand-s3" />
      <circle cx="26" cy="48" r="0.8" fill="#FCD34D" className="la-sand-s1" style={{ animationDelay: "2s" }} />
      <circle cx="48" cy="38" r="0.8" fill="#FCD34D" className="la-sand-s2" style={{ animationDelay: "2.1s" }} />
    </svg>
  )
}
