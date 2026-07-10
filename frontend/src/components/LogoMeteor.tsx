import { useId } from "react"

/** B10 流星环 — 金色流星沿椭圆轨道环绕 Logo 公转 + 坠尾拖曳 + Z 辉光 */
export default function LogoMeteor({ className = "h-12 w-12" }: { className?: string }) {
  const id = useId()
  return (
    <svg viewBox="0 0 64 64" className={className} aria-label="同步中">
      <defs>
        <linearGradient id={`meteor-bg-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#0F1F3D" />
          <stop offset="100%" stopColor="#3B82F6" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="14" fill={`url(#meteor-bg-${id})`} />
      <polygon points="32,6 36,27 32,32 28,27" fill="white" fillOpacity={0.42} />
      <polygon points="58,32 37,36 32,32 37,28" fill="white" fillOpacity={0.42} />
      <polygon points="32,58 28,37 32,32 36,37" fill="white" fillOpacity={0.34} />
      <polygon points="6,32 27,28 32,32 27,36" fill="white" fillOpacity={0.34} />
      <circle cx="32" cy="32" r="11" fill="white" />
      <g className="la-meteor-orb">
        <circle cx="52" cy="32" r="2.5" fill="#FBBF24" className="la-meteor-m1" />
      </g>
      <g className="la-meteor-orb">
        <circle cx="52" cy="32" r="2" fill="#F59E0B" className="la-meteor-m2" />
      </g>
      <g className="la-meteor-orb">
        <circle cx="52" cy="32" r="2" fill="#FBBF24" className="la-meteor-m3" />
      </g>
      <g className="la-meteor-orb2">
        <circle cx="12" cy="32" r="1.5" fill="#FCD34D" className="la-meteor-m1" style={{ animationDelay: "0.4s" }} />
      </g>
      <circle cx="32" cy="32" r="12.5" fill="none" stroke="#F59E0B" strokeWidth={0.8} opacity={0.5} />
      <g className="la-meteor-z">
        <path d="M 25 28 L 39 28 L 25 36 L 38 34" stroke="#F59E0B" strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </g>
    </svg>
  )
}
