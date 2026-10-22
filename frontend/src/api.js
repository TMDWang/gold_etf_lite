export function createApiClient({fetchImpl = (...args) => globalThis.fetch(...args), readCookie = () => globalThis.document?.cookie || '', defaultTimeout = 12000} = {}) {
  return async function request(path, options = {}) {
    const {timeoutMs = defaultTimeout, signal: callerSignal, headers, body, ...rest} = options
    const controller = new AbortController()
    let timedOut = false
    const cancel = () => controller.abort()
    if (callerSignal?.aborted) throw Object.assign(new Error('请求已取消'), {code: 'CANCELLED'})
    callerSignal?.addEventListener('abort', cancel, {once: true})
    const timer = setTimeout(() => {timedOut = true; controller.abort()}, timeoutMs)
    try {
      const csrf = readCookie().split('; ').find(x => x.startsWith('csrftoken='))?.split('=')[1] || ''
      const response = await fetchImpl(`/api${path}`, {
        credentials: 'same-origin', ...rest, cache: 'no-store', signal: controller.signal,
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(csrf), ...headers},
        body: body === undefined ? undefined : JSON.stringify(body),
      })
      let data
      try {data = await response.json()} catch (error) {
        if (controller.signal.aborted) throw error
        throw new Error('服务暂时不可用，请稍后重试')
      }
      if (!response.ok) {
        const flatten = x => typeof x === 'string' ? x : Array.isArray(x) ? x.map(flatten).join('；') : Object.values(x || {}).map(flatten).join('；')
        throw Object.assign(new Error(flatten(data) || '操作失败'), {status: response.status})
      }
      return data
    } catch (error) {
      if (timedOut) {
        const writing = rest.method && !['GET', 'HEAD'].includes(rest.method.toUpperCase())
        throw Object.assign(new Error(writing ? '请求超时，操作可能已保存，请先刷新核对；重复确认原成交表单不会重复入账。' : '连接超时，请检查网络后重试'), {code: 'TIMEOUT'})
      }
      if (controller.signal.aborted) throw Object.assign(new Error('请求已取消'), {code: 'CANCELLED'})
      if (error instanceof TypeError) throw new Error('网络连接暂时不可用，请检查网络后重试')
      throw error
    } finally {clearTimeout(timer);callerSignal?.removeEventListener('abort', cancel)}
  }
}
export const api = createApiClient()
export const post = (path, body, key) => api(path, {method: 'POST', body, ...(key ? {headers: {'Idempotency-Key': key}} : {})})
