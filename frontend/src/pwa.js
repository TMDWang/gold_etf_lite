/** Page-shell caching only. No account data, session tokens or mutation queues are stored. */
export function registerShellWorker(onUpdate, navigatorImpl = globalThis.navigator, locationImpl = globalThis.location) {
  const container=navigatorImpl?.serviceWorker
  if (!container) return {check(){},activate(){},dispose(){}}
  let registration,disposed=false,requested=false,lastCheck=0
  const onController=()=>{if(requested&&!disposed)locationImpl.reload()}
  container.addEventListener('controllerchange',onController)
  container.register('/sw.js',{scope:'/',updateViaCache:'none'}).then(reg=>{
    if(disposed)return
    registration=reg
    if(reg.waiting&&container.controller)onUpdate()
    reg.addEventListener('updatefound',()=>{
      const worker=reg.installing
      worker?.addEventListener('statechange',()=>{
        if(!disposed&&worker.state==='installed'&&container.controller)onUpdate()
      })
    })
  }).catch(()=>{/* The ordinary online app remains available when installation is unavailable. */})
  return {
    check(){const now=Date.now();if(registration&&!disposed&&now-lastCheck>60000){lastCheck=now;registration.update().catch(()=>{})}},
    activate(){if(registration?.waiting){requested=true;registration.waiting.postMessage({type:'SKIP_WAITING'})}},
    dispose(){disposed=true;container.removeEventListener('controllerchange',onController)},
  }
}
