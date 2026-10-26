/**
 * 复制文本到剪贴板，返回是否成功。
 *
 * 优先使用异步 Clipboard API，但它只在安全上下文（HTTPS / localhost）可用；
 * 通过局域网 IP 以 HTTP 访问自部署实例时会抛错或根本不存在。此时退回
 * `document.execCommand("copy")`，仍失败则由调用方选中文本让用户手动复制。
 */
export async function copyText(text: string): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // 权限被拒或浏览器策略限制，继续尝试兜底方案
    }
  }

  const textarea = document.createElement("textarea")
  const previousFocus = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null
  try {
    textarea.value = text
    textarea.setAttribute("readonly", "")
    textarea.style.position = "fixed"
    textarea.style.top = "0"
    textarea.style.opacity = "0"
    document.body.appendChild(textarea)
    textarea.select()
    textarea.setSelectionRange(0, text.length)
    return document.execCommand("copy")
  } catch {
    return false
  } finally {
    textarea.remove()
    // 回退复制可能把焦点移到临时元素；不要让清理异常覆盖已成功的复制结果。
    try {
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true })
    } catch {
      // 已执行的复制不能因恢复焦点失败而误报失败
    }
  }
}
