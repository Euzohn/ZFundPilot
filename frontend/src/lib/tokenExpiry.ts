// Agent token 临期阈值（天）。仅前端本地提示，不影响后端鉴权与过期判定。
export const TOKEN_EXPIRING_SOON_DAYS = 7

/**
 * 判断 token 是否「尚未过期但将在 N 天内过期」。
 *
 * @param expiresAt ISO 时间串；空值表示不过期，返回 false。
 * @param days 阈值天数，默认 7 天。
 * @param now 当前时间戳（毫秒），便于测试注入。
 */
export function isTokenExpiringSoon(
  expiresAt: string | null | undefined,
  days = TOKEN_EXPIRING_SOON_DAYS,
  now = Date.now(),
): boolean {
  if (!expiresAt) return false
  const expires = new Date(expiresAt).getTime()
  if (Number.isNaN(expires)) return false
  const remaining = expires - now
  return remaining > 0 && remaining <= days * 24 * 60 * 60 * 1000
}