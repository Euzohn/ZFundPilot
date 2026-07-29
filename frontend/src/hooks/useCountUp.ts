import { useState, useEffect, useRef } from "react"
import { animate } from "animejs"

export function useCountUp(
  target: number,
  formatter: (n: number) => string,
  duration = 800,
): string {
  const [display, setDisplay] = useState(() => formatter(0))
  const currentRef = useRef(0)

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setDisplay(formatter(target))
      currentRef.current = target
      return
    }

    const obj = { val: currentRef.current }

    const anim = animate(obj, {
      val: target,
      duration,
      ease: "outExpo",
      onUpdate: () => {
        currentRef.current = obj.val
        setDisplay(formatter(obj.val))
      },
      onComplete: () => {
        currentRef.current = target
        setDisplay(formatter(target))
      },
    })

    return () => {
      anim.pause()
    }
  }, [target, duration, formatter])

  return display
}