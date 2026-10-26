/**
 * 复制文本到剪贴板，返回是否成功。
 *
 * 优先使用异步 Clipboard API，但它只在安全上下文（HTTPS / localhost）可用；
 * 通过局域网 IP 以 HTTP 访问自部署实例时会抛错或根本不存在。此时退回
 * `document.execCommand("copy")`，仍失败则由调用方选中文本让用户手动复制。
 *
 * 传入 `fallbackTarget` 时优先在页面上已有的输入框内选中复制：不必插入隐藏
 * 节点，移动端兼容性更好，失败时用户也能直接看到明文处于选中状态。
 */
export async function copyText(
  text: string,
  fallbackTarget?: HTMLInputElement | HTMLTextAreaElement | null,
): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // 权限被拒或浏览器策略限制，继续尝试兜底方案
    }
  }

  if (fallbackTarget && fallbackTarget.value === text) {
    return copySelection(fallbackTarget)
  }

  const textarea = document.createElement("textarea")
  const previousFocus = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null
  try {
    textarea.value = text
    textarea.setAttribute("readonly", "")
    textarea.style.position = "fixed"
    textarea.style.left = "-9999px"
    textarea.style.opacity = "0"
    // 避免 iOS 聚焦小字号输入框时自动缩放页面
    textarea.style.fontSize = "16px"
    document.body.appendChild(textarea)
    return copySelection(textarea)
  } catch {
    return false
  } finally {
    textarea.remove()
    // 回退复制会把焦点移到临时节点；恢复焦点但不要让清理异常覆盖已成功的复制结果。
    try {
      if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true })
    } catch {
      // 已执行的复制不能因恢复焦点失败而误报失败
    }
  }
}

function copySelection(target: HTMLInputElement | HTMLTextAreaElement): boolean {
  try {
    target.focus()
    target.select()
    target.setSelectionRange(0, target.value.length)
    return document.execCommand("copy")
  } catch {
    return false
  }
}
