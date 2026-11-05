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
test('read requests recover from a brief network failure or gateway error',async()=>{
  let attempts=0
  const api=createApiClient({retryDelay:0,fetchImpl:async()=>{attempts++;if(attempts===1)throw new TypeError('Failed to fetch');return{ok:true,json:async()=>({ok:true})}}})
  assert.deepEqual(await api('/market/'),{ok:true});assert.equal(attempts,2)
  attempts=0
  const gateway=createApiClient({retryDelay:0,fetchImpl:async()=>++attempts===1?{ok:false,status:502}:{ok:true,json:async()=>({ok:true})}})
  assert.deepEqual(await gateway('/account/'),{ok:true});assert.equal(attempts,2)
})
test('writes are not retried on network or gateway failure',async()=>{
  let attempts=0
  const api=createApiClient({retryDelay:0,fetchImpl:async()=>{attempts++;throw new TypeError('Failed to fetch')}})
  await assert.rejects(api('/entries/',{method:'POST',body:{}}),/可能已保存/);assert.equal(attempts,1)
  attempts=0
  const gateway=createApiClient({retryDelay:0,fetchImpl:async()=>{attempts++;return{ok:false,status:502,json:async()=>{throw new SyntaxError('HTML')}}}})
  await assert.rejects(gateway('/cash/',{method:'POST',body:{}}),/可能已保存/);assert.equal(attempts,1)
})
test('caller cancellation during retry delay does not issue a second request',async()=>{
  let attempts=0;const c=new AbortController()
  const api=createApiClient({retryDelay:1000,fetchImpl:async()=>{attempts++;return{ok:false,status:502}}})
  const pending=api('/market/',{signal:c.signal});await Promise.resolve();c.abort()
  await assert.rejects(pending,e=>e.code==='CANCELLED');assert.equal(attempts,1)
})
test('mixed network and gateway errors never cause more than one retry',async()=>{
  let attempts=0
  const api=createApiClient({retryDelay:0,fetchImpl:async()=>{attempts++;if(attempts===1)throw new TypeError('network');return{ok:false,status:502,json:async()=>{throw new SyntaxError('HTML')}}}})
  await assert.rejects(api('/market/'),/服务暂时不可用/);assert.equal(attempts,2)
})
