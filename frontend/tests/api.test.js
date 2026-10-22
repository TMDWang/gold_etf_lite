import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createApiClient} from '../src/api.js'
test('requests use current csrf and do not cache private responses',async()=>{
  let cookie='csrftoken=first';const seen=[]
  const api=createApiClient({readCookie:()=>cookie,fetchImpl:async(url,opts)=>{seen.push(opts);return{ok:true,json:async()=>({ok:true})}}})
  await api('/account/');cookie='csrftoken=rotated';await api('/cash/',{method:'POST',body:{amount:'1'},headers:{'Idempotency-Key':'unchanged-key'}})
  assert.equal(seen[0].cache,'no-store');assert.equal(seen[1].headers['X-CSRFToken'],'rotated')
  assert.equal(seen[1].headers['Idempotency-Key'],'unchanged-key');assert.equal(seen[1].body,'{"amount":"1"}')
})
test('a stalled response body times out; writes are never automatically retried',async()=>{
  let attempts=0
  const api=createApiClient({defaultTimeout:15,fetchImpl:async(url,opts)=>{attempts++;return{ok:true,json:()=>new Promise((resolve,reject)=>opts.signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError')),{once:true}))}}})
  await assert.rejects(api('/entries/',{method:'POST',body:{},headers:{'Idempotency-Key':'same'}}),e=>e.code==='TIMEOUT'&&e.message.includes('核对'))
  assert.equal(attempts,1)
})
test('offline failure is readable and caller cancellation remains distinct',async()=>{
  const api=createApiClient({fetchImpl:async()=>{throw new TypeError('Failed to fetch')}})
  await assert.rejects(api('/account/'),/网络连接/)
  const c=new AbortController();c.abort()
  await assert.rejects(api('/account/',{signal:c.signal}),e=>e.code==='CANCELLED')
})
