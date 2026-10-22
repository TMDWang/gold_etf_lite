export function resolveEpisodePlan(episode,plans) {
  return plans.find(p=>p.id===episode.plan&&p.version===episode.version&&p.side===episode.side&&p.status==='ACTIVE')||null
}

/** Direct action requests obey the same session boundary as background section requests. */
export function createSessionRequests({request,submit}) {
  let epoch=0
  const invoke=async(fn,args)=>{
    const owner=epoch
    try {
      const result=await fn(...args)
      if(owner!==epoch)throw Object.assign(new Error('登录状态已变化，请重新操作'),{code:'CANCELLED'})
      return result
    } catch(error) {
      if(owner!==epoch)throw Object.assign(new Error('登录状态已变化，请重新操作'),{code:'CANCELLED'})
      throw error
    }
  }
  return {request:(...args)=>invoke(request,args),submit:(...args)=>invoke(submit,args),invalidate(){epoch++}}
}

/** Independent sections, with response ownership across retries, logout and account changes. */
export function createSectionLoader({sections, onUnauthorized = () => {}}) {
  let epoch = 0
  const active = new Map()
  function reset() {
    epoch++
    for (const job of active.values()) job.controller.abort()
    active.clear()
    for (const section of Object.values(sections)) {
      section.state.pending = false;section.state.error = '';section.clear?.()
    }
  }
  function run(key, {force = false} = {}) {
    const section = sections[key]
    if (!section) throw new Error(`Unknown section: ${key}`)
    if (active.has(key) && !force) return active.get(key).promise
    active.get(key)?.controller.abort()
    const job = {controller: new AbortController(), epoch}
    active.set(key, job);section.state.pending = true;section.state.error = ''
    const owns = () => job.epoch === epoch && active.get(key) === job
    job.promise = (async () => {
      try {
        const value = await section.load({signal: job.controller.signal})
        if (owns()) section.apply(value)
      } catch (error) {
        if (!owns()) return
        if ([401, 403].includes(error.status)) {reset();onUnauthorized()}
        else if (error.code !== 'CANCELLED') section.state.error = error.message || '加载失败，请重试'
      } finally {
        if (owns()) {section.state.pending = false;active.delete(key)}
      }
    })()
    return job.promise
  }
  return {run, reset}
}
