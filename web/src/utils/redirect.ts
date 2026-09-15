/**
 * 站内重定向目标的过滤（P1-5-4）。
 *
 * `redirect` 参数来自地址栏（`/login?redirect=...`），因此是**用户可控输入**。
 * 直接把它交给 `router.push()` 会让登录页变成开放重定向：
 * `/login?redirect=//evil.example` 这种协议相对地址会被浏览器当成另一个站点。
 * 这里只接受以单个 `/` 开头的站内相对路径，其余一律回落到工作台。
 */

/** 登录成功、或 `redirect` 不可信时的默认落点。 */
export const DEFAULT_REDIRECT = '/workspace'

/** 把 `route.query.redirect` 收敛成一个可以安全 `push` 的站内路径。 */
export function safeRedirect(value: unknown): string {
  if (typeof value !== 'string') return DEFAULT_REDIRECT
  // 必须是站内绝对路径：`//host` 与 `/\host` 都会被浏览器解析成协议相对地址。
  if (!value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) {
    return DEFAULT_REDIRECT
  }
  return value
}
