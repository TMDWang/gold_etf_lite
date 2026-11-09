import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createSectionLoader,networkNotice} from '../src/loading.js'
test('repeated connection failures are combined without hiding other errors',()=>{
 const states={market:{error:'网络连接暂时不可用，请检查网络后重试'},plans:{error:'连接超时，请检查网络后重试'},episodes:{error:'数据格式错误'}}
 assert.deepEqual(networkNotice(states,['market','plans','episodes']),['market','plans'])
 assert.deepEqual(networkNotice(states,['episodes']),[])
})
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return{promise,resolve,reject}}
function section(load){return{state:{pending:false,error:''},load,values:[],apply(v){this.values.push(v)},clear(){this.values=[]}}}

test('fast section renders without waiting for a slow or failed sibling',async()=>{
  const slow=deferred(),account=section(()=>slow.promise),market=section(async()=>({price:'8.4'}))
  const loader=createSectionLoader({sections:{account,market}})
  const a=loader.run('account');await loader.run('market')
  assert.deepEqual(market.values,[{price:'8.4'}]);assert.equal(account.state.pending,true)
  slow.reject(new Error('连接超时'));await a
  assert.equal(account.state.error,'连接超时');assert.equal(market.values.length,1)
})
test('reset discards late private responses from the previous account',async()=>{
  const old=deferred(),account=section(()=>old.promise)
  const loader=createSectionLoader({sections:{account}})
  const pending=loader.run('account');loader.reset();old.resolve({cash:'999'})
  await pending;assert.deepEqual(account.values,[]);assert.equal(account.state.pending,false)
})
test('post-write reload prevents a pending pre-write snapshot overwriting initialized account',async()=>{
  const old=deferred();let calls=0;let displayed=null
  const account=section(()=>++calls===1?old.promise:Promise.resolve({initialized_at:'now',cash:'900'}))
  account.apply=v=>{displayed=v}
  const loader=createSectionLoader({sections:{account}})
  const pending=loader.run('account')
  displayed={initialized_at:'now',cash:'900'}
  await loader.run('account',{force:true})
  old.resolve({initialized_at:null,cash:'0'});await pending
  assert.equal(displayed.cash,'900');assert.equal(displayed.initialized_at,'now')
})
test('repeated refresh shares request and force retry discards older response',async()=>{
  const first=deferred(),second=deferred();let calls=0
  const account=section(()=>++calls===1?first.promise:second.promise)
  const loader=createSectionLoader({sections:{account}})
  const a=loader.run('account');const b=loader.run('account');assert.equal(calls,1)
  const c=loader.run('account',{force:true});second.resolve('new');await c
  first.resolve('old');await Promise.all([a,b]);assert.deepEqual(account.values,['new'])
})
test('session expiry clears private state and prevents sibling late writes',async()=>{
  const later=deferred(),account=section(async()=>{throw Object.assign(new Error('登录失效'),{status:403})}),plans=section(()=>later.promise)
  let expired=0
  const loader=createSectionLoader({sections:{account,plans},onUnauthorized(){expired++}})
  plans.values.push('old private data')
  const pending=loader.run('plans');await loader.run('account');later.resolve('private response');await pending
  assert.equal(expired,1);assert.deepEqual(plans.values,[])
})
test('invalidating pending requests preserves displayed values and prevents stale results',async()=>{
 const late=deferred(),account=section(()=>late.promise);account.values.push('displayed')
 const loader=createSectionLoader({sections:{account}});const pending=loader.run('account')
 loader.invalidate();assert.deepEqual(account.values,['displayed']);assert.equal(account.state.pending,false)
 late.resolve('stale');await pending;assert.deepEqual(account.values,['displayed'])
})
test('recent successful section data is reused only until expiry, and force bypasses reuse',async()=>{
 let now=1000,calls=0;const account=section(async()=>++calls)
 const loader=createSectionLoader({sections:{account},now:()=>now})
 await loader.run('account',{maxAgeMs:5000});now+=4000
 await loader.run('account',{maxAgeMs:5000});assert.equal(calls,1)
 await loader.run('account',{maxAgeMs:5000,force:true});assert.equal(calls,2)
 now+=5001;await loader.run('account',{maxAgeMs:5000});assert.equal(calls,3)
 loader.reset();await loader.run('account',{maxAgeMs:5000});assert.equal(calls,4)
})
test('failed refresh is surfaced and is not hidden by a recent cached value',async()=>{
 let calls=0,now=1000;const account=section(async()=>{calls++;if(calls===2)throw Error('offline');return calls})
 const loader=createSectionLoader({sections:{account},now:()=>now})
 await loader.run('account',{maxAgeMs:5000});await loader.run('account',{force:true,maxAgeMs:5000})
 assert.equal(account.state.error,'offline');await loader.run('account',{maxAgeMs:5000});assert.equal(calls,3);assert.equal(account.state.error,'')
})
