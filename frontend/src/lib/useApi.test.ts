import { afterEach, describe, expect, it, vi } from "vitest"
import { act, renderHook } from "@testing-library/react"
import { useApi } from "./useApi"

afterEach(() => {
  vi.useRealTimers()
})

function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

describe("useApi 请求代际守卫", () => {
  it("返回 API 形状保持不变", () => {
    const fetcher = vi.fn().mockResolvedValue("ok")
    const { result } = renderHook(() => useApi(fetcher, []))
    expect(Object.keys(result.current).sort()).toEqual(["data", "error", "loading", "reload", "setData"])
  })

  it("deps 变化后旧请求后到，不覆盖新数据（fake timers 模拟慢旧响应）", async () => {
    vi.useFakeTimers()
    const fetcher = vi
      .fn()
      .mockImplementationOnce(() => new Promise<string>((r) => setTimeout(() => r("old"), 100)))
      .mockImplementationOnce(() => new Promise<string>((r) => setTimeout(() => r("new"), 10)))
    const { result, rerender } = renderHook(({ dep }) => useApi(fetcher, [dep]), {
      initialProps: { dep: 1 },
    })
    expect(result.current.loading).toBe(true)

    rerender({ dep: 2 })
    await act(async () => {
      vi.advanceTimersByTime(10)
    })
    expect(result.current.data).toBe("new")
    expect(result.current.loading).toBe(false)
    expect(result.current.error).toBeNull()

    // 旧请求此时才返回，必须被丢弃
    await act(async () => {
      vi.advanceTimersByTime(100)
    })
    expect(result.current.data).toBe("new")
    expect(result.current.loading).toBe(false)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it("旧请求后到的失败不覆盖新数据", async () => {
    const d1 = deferred<string>()
    const d2 = deferred<string>()
    const fetcher = vi.fn().mockReturnValueOnce(d1.promise).mockReturnValueOnce(d2.promise)
    const { result, rerender } = renderHook(({ dep }) => useApi(fetcher, [dep]), {
      initialProps: { dep: "a" },
    })
    rerender({ dep: "b" })

    await act(async () => {
      d2.resolve("new")
    })
    expect(result.current.data).toBe("new")

    await act(async () => {
      d1.reject(new Error("旧请求失败"))
    })
    expect(result.current.data).toBe("new")
    expect(result.current.error).toBeNull()
    expect(result.current.loading).toBe(false)
  })

  it("旧请求后到的成功不清除新请求的错误", async () => {
    const d1 = deferred<string>()
    const d2 = deferred<string>()
    const fetcher = vi.fn().mockReturnValueOnce(d1.promise).mockReturnValueOnce(d2.promise)
    const { result, rerender } = renderHook(({ dep }) => useApi(fetcher, [dep]), {
      initialProps: { dep: "a" },
    })
    rerender({ dep: "b" })

    await act(async () => {
      d2.reject(new Error("新请求失败"))
    })
    expect(result.current.error).toBe("新请求失败")
    expect(result.current.loading).toBe(false)

    await act(async () => {
      d1.resolve("old")
    })
    expect(result.current.error).toBe("新请求失败")
    expect(result.current.data).toBeNull()
  })

  it("旧响应先到而新请求仍在途时，loading 保持 true 且不写入过期数据", async () => {
    const d1 = deferred<string>()
    const d2 = deferred<string>()
    const fetcher = vi.fn().mockReturnValueOnce(d1.promise).mockReturnValueOnce(d2.promise)
    const { result, rerender } = renderHook(({ dep }) => useApi(fetcher, [dep]), {
      initialProps: { dep: "a" },
    })
    rerender({ dep: "b" })

    await act(async () => {
      d1.resolve("old")
    })
    expect(result.current.data).toBeNull()
    expect(result.current.loading).toBe(true)

    await act(async () => {
      d2.resolve("new")
    })
    expect(result.current.data).toBe("new")
    expect(result.current.loading).toBe(false)
  })

  it("手动连续 reload 时只有最新一次请求生效", async () => {
    const d0 = deferred<string>()
    const d1 = deferred<string>()
    const d2 = deferred<string>()
    const fetcher = vi
      .fn()
      .mockReturnValueOnce(d0.promise)
      .mockReturnValueOnce(d1.promise)
      .mockReturnValueOnce(d2.promise)
    const { result } = renderHook(() => useApi(fetcher, []))

    act(() => {
      void result.current.reload()
      void result.current.reload()
    })
    await act(async () => {
      d2.resolve("latest")
    })
    expect(result.current.data).toBe("latest")
    expect(result.current.loading).toBe(false)

    await act(async () => {
      d1.resolve("middle")
      d0.resolve("first")
    })
    expect(result.current.data).toBe("latest")
    expect(result.current.loading).toBe(false)
  })

  it("卸载后在途请求完成不再 setState", async () => {
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {})
    const d = deferred<string>()
    const fetcher = vi.fn().mockReturnValueOnce(d.promise)
    const { unmount } = renderHook(() => useApi(fetcher, []))
    unmount()
    await act(async () => {
      d.resolve("late")
    })
    expect(errSpy).not.toHaveBeenCalled()
    errSpy.mockRestore()
  })
})
