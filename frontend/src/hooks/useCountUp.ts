import { useState, useEffect, useRef } from "react"
import { animate } from "animejs"

export function useCountUp(
  target: number,
  formatter: (n: number) => string,
  duration = 800,
): string {
  const [display, setDisplay] = useState(() => formatter(0))
  const currentRef = useRef(0)
  const formatterRef = useRef(formatter)
  formatterRef.current = formatter

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setDisplay(formatterRef.current(target))
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
        setDisplay(formatterRef.current(obj.val))
      },
      onComplete: () => {
        currentRef.current = target
        setDisplay(formatterRef.current(target))
      },
    })

    return () => {
      anim.pause()
    }
  }, [target, duration])

  return display
}