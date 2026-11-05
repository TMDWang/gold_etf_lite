/** Page-shell caching only. No account data, session tokens or mutation queues are stored. */
export function registerShellWorker(onUpdate, navigatorImpl = globalThis.navigator, locationImpl = globalThis.location) {
  const container=navigatorImpl?.serviceWorker
  if (!container) return {check(){},activate(){},dispose(){}}
  let registration,disposed=false,requested=false,lastCheck=0
  const observed=new WeakSet()
  const notifyWaiting=()=>{if(!disposed&&registration?.waiting&&container.controller)onUpdate()}
  const observe=worker=>{
    if(!worker||observed.has(worker))return
    observed.add(worker)
    worker.addEventListener('statechange',()=>{if(worker.state==='installed')notifyWaiting()})
    if(worker.state==='installed')notifyWaiting()
  }
  const onController=()=>{if(requested&&!disposed)locationImpl.reload()}
  container.addEventListener('controllerchange',onController)
  container.register('/sw.js',{scope:'/',updateViaCache:'none'}).then(reg=>{
    if(disposed)return
    registration=reg
    reg.addEventListener('updatefound',()=>observe(reg.installing))
    observe(reg.installing)
    notifyWaiting()
  }).catch(()=>{/* The ordinary online app remains available when installation is unavailable. */})
  return {
    check(){const now=Date.now();if(registration&&!disposed&&now-lastCheck>60000){lastCheck=now;registration.update().then(()=>{observe(registration.installing);notifyWaiting()},notifyWaiting)}},
    activate(){if(registration?.waiting){requested=true;registration.waiting.postMessage({type:'SKIP_WAITING'})}},
    dispose(){disposed=true;container.removeEventListener('controllerchange',onController)},
  }
}
