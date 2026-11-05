/** One visible-page SSE connection; failed streams fall back without retry storms. */
export function createPriceStream({EventSourceImpl=globalThis.EventSource,onPrice=()=>{},onState=()=>{},onFallback=()=>{},onOpen=()=>{},schedule=setTimeout,cancel=clearTimeout}={}) {
  let active=false,source=null,timer=null,watchdog=null,generation=0
  function clearWatchdog(){if(watchdog!==null)cancel(watchdog);watchdog=null}
  function connect() {
    if(!active)return
    const current=++generation
    if(!EventSourceImpl){onState('fallback');onFallback();timer=schedule(connect,30000);return}
    try {source=new EventSourceImpl('/api/quote/stream/')}
    catch {onState('fallback');onFallback();timer=schedule(connect,30000);return}
    const own=source
    function fail(){
      if(!active||generation!==current)return
      clearWatchdog();generation++;own.close();source=null;onState('fallback');onFallback();timer=schedule(connect,30000)
    }
    function alive(){clearWatchdog();watchdog=schedule(fail,45000)}
    alive()
    own.onopen=()=>{if(active&&generation===current){alive();onState('live');onOpen()}}
    own.addEventListener('price',event=>{
      if(!active||generation!==current)return
      alive()
      try{const value=JSON.parse(event.data);if(value&&typeof value==='object')onPrice(value)}catch{}
    })
    own.addEventListener('heartbeat',()=>{if(active&&generation===current)alive()})
    own.onerror=fail
  }
  return {
    start(){if(active)return;active=true;connect()},
    stop(){active=false;generation++;if(timer!==null)cancel(timer);timer=null;clearWatchdog();source?.close();source=null;onState('stopped')},
  }
}
