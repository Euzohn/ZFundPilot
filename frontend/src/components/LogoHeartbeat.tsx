import { useId } from "react"

/** B9 心跳脉动 — Logo 像心跳一样双拍搏动 + 心电曲线绘制 + Z 辉光脉动 */
export default function LogoHeartbeat({ className = "h-12 w-12" }: { className?: string }) {
  const id = useId()
  return (
    <svg viewBox="0 0 64 64" className={className} aria-label="加载中">
      <defs>
        <linearGradient id={`heartbeat-bg-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#0F1F3D" />
          <stop offset="100%" stopColor="#3B82F6" />
        </linearGradient>
      </defs>
      <g className="la-heartbeat-beat">
        <rect width="64" height="64" rx="14" fill={`url(#heartbeat-bg-${id})`} />
        <polygon points="32,6 36,27 32,32 28,27" fill="white" fillOpacity={0.42} />
        <polygon points="58,32 37,36 32,32 37,28" fill="white" fillOpacity={0.42} />
        <polygon points="32,58 28,37 32,32 36,37" fill="white" fillOpacity={0.34} />
        <polygon points="6,32 27,28 32,32 27,36" fill="white" fillOpacity={0.34} />
        <circle cx="32" cy="32" r="11" fill="white" />
        <circle cx="32" cy="32" r="12.5" fill="none" stroke="#F59E0B" strokeWidth={0.8} className="la-heartbeat-ring" />
      </g>
      <g className="la-heartbeat-z">
        <path d="M 25 28 L 39 28 L 25 36 L 38 34" stroke="#F59E0B" strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </g>
      <path
        d="M 8 50 L 16 50 L 20 38 L 24 50 L 28 50 L 32 42 L 36 50 L 40 50 L 44 38 L 48 50 L 56 50"
        stroke="#F87171" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" fill="none"
        className="la-heartbeat-ecg" opacity={0.5}
      />
    </svg>
  )
}
