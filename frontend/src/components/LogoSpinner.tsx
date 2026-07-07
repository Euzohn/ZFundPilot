import { useId } from "react"

export default function LogoSpinner({ className = "h-12 w-12" }: { className?: string }) {
  const id = useId()
  return (
    <svg viewBox="0 0 64 64" className={className} aria-label="加载中">
      <defs>
        <linearGradient id={`spinner-bg-${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#0F1F3D" />
          <stop offset="100%" stopColor="#3B82F6" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="14" fill={`url(#spinner-bg-${id})`} />
      <g style={{ transformBox: "fill-box", transformOrigin: "center", animation: "logo-spin 2.5s linear infinite" }}>
        <polygon points="32,6 36,27 32,32 28,27" fill="white" fillOpacity={0.55} />
        <polygon points="58,32 37,36 32,32 37,28" fill="white" fillOpacity={0.55} />
        <polygon points="32,58 28,37 32,32 36,37" fill="white" fillOpacity={0.25} />
        <polygon points="6,32 27,28 32,32 27,36" fill="white" fillOpacity={0.25} />
      </g>
      <circle cx="32" cy="32" r="10" fill="white" />
      <path d="M 25 28 L 39 28 L 25 36 L 39 36" stroke="#1E40AF" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" fill="none" />
    </svg>
  )
}
