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
  textarea.value = text
  textarea.setAttribute("readonly", "")
  textarea.style.position = "fixed"
  textarea.style.top = "-9999px"
  textarea.style.opacity = "0"
  document.body.appendChild(textarea)
  const selection = document.getSelection()
  const previousRange = selection && selection.rangeCount > 0
    ? selection.getRangeAt(0)
    : null
  try {
    textarea.select()
    textarea.setSelectionRange(0, text.length)
    return document.execCommand("copy")
  } catch {
    return false
  } finally {
    document.body.removeChild(textarea)
    if (previousRange && selection) {
      selection.removeAllRanges()
      selection.addRange(previousRange)
    }
  }
}
