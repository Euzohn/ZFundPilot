import { useId } from "react"

export default function Logo({ className = "h-9 w-9" }: { className?: string }) {
  const id = useId()
  return (
    <svg viewBox="0 0 64 64" className={className} aria-label="ZFundPilot">
      <defs>
        <linearGradient id={`logo-bg-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#0F1F3D" />
          <stop offset="100%" stopColor="#3B82F6" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="14" fill={`url(#logo-bg-${id})`} />
      <polygon points="32,6 36,27 32,32 28,27" fill="white" fillOpacity={0.42} />
      <polygon points="58,32 37,36 32,32 37,28" fill="white" fillOpacity={0.42} />
      <polygon points="32,58 28,37 32,32 36,37" fill="white" fillOpacity={0.34} />
      <polygon points="6,32 27,28 32,32 27,36" fill="white" fillOpacity={0.34} />
      <circle cx="32" cy="32" r="11" fill="white" />
      <circle cx="32" cy="32" r="12.5" fill="none" stroke="#F59E0B" strokeWidth={0.8} opacity={0.5} />
      <path d="M 25 28 L 39 28 L 25 36 L 38 34" stroke="#F59E0B" strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  )
}
