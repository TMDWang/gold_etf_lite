export function createApiClient({fetchImpl = (...args) => globalThis.fetch(...args), readCookie = () => globalThis.document?.cookie || '', defaultTimeout = 12000, retryDelay = 350} = {}) {
  return async function request(path, options = {}) {
    const {timeoutMs = defaultTimeout, signal: callerSignal, headers, body, ...rest} = options
    const writing = !!rest.method && !['GET', 'HEAD'].includes(rest.method.toUpperCase())
    const controller = new AbortController()
    let timedOut = false
    const cancel = () => controller.abort()
    if (callerSignal?.aborted) throw Object.assign(new Error('请求已取消'), {code: 'CANCELLED'})
    callerSignal?.addEventListener('abort', cancel, {once: true})
    const timer = setTimeout(() => {timedOut = true; controller.abort()}, timeoutMs)
    try {
      const csrf = readCookie().split('; ').find(x => x.startsWith('csrftoken='))?.split('=')[1] || ''
      const options = {
        credentials: 'same-origin', ...rest, cache: 'no-store', signal: controller.signal,
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': decodeURIComponent(csrf), ...headers},
        body: body === undefined ? undefined : JSON.stringify(body),
      }
      const delay = () => new Promise((resolve, reject) => {
        if (controller.signal.aborted) return reject(new DOMException('aborted','AbortError'))
        const abort=()=>{clearTimeout(id);reject(new DOMException('aborted','AbortError'))}
        const id=setTimeout(()=>{controller.signal.removeEventListener('abort',abort);resolve()},retryDelay)
        controller.signal.addEventListener('abort',abort,{once:true})
      })
      let response,retried=false
      try {response=await fetchImpl(`/api${path}`,options)}
      catch (error) {
        if (writing || !(error instanceof TypeError) || controller.signal.aborted) throw error
        await delay();retried=true;response=await fetchImpl(`/api${path}`,options)
      }
      if (!writing && !retried && [502,503,504,520,521,522,523,524].includes(response.status)) {
        await delay();response=await fetchImpl(`/api${path}`,options)
      }
      if (writing && [502,503,504,520,521,522,523,524].includes(response.status)) {
        throw new Error('服务连接中断，操作可能已保存，请先刷新核对')
      }
      let data
      try {data = await response.json()} catch (error) {
        if (controller.signal.aborted) throw error
        throw new Error(writing?'服务连接中断，操作可能已保存，请先刷新核对':'服务暂时不可用，请稍后重试')
      }
      if (!response.ok) {
        const flatten = x => typeof x === 'string' ? x : Array.isArray(x) ? x.map(flatten).join('；') : Object.values(x || {}).map(flatten).join('；')
        throw Object.assign(new Error(flatten(data) || '操作失败'), {status: response.status})
      }
      return data
    } catch (error) {
      if (timedOut) {
        throw Object.assign(new Error(writing ? '请求超时，操作可能已保存，请先刷新核对；重复确认原成交表单不会重复入账。' : '连接超时，请检查网络后重试'), {code: 'TIMEOUT'})
      }
      if (controller.signal.aborted) throw Object.assign(new Error('请求已取消'), {code: 'CANCELLED'})
      if (error instanceof TypeError) throw new Error(writing?'网络连接中断，操作可能已保存，请先刷新核对':'网络连接暂时不可用，请检查网络后重试')
      throw error
    } finally {clearTimeout(timer);callerSignal?.removeEventListener('abort', cancel)}
  }
}
export const api = createApiClient()
export const post = (path, body, key) => api(path, {method: 'POST', body, ...(key ? {headers: {'Idempotency-Key': key}} : {})})
