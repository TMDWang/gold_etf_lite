import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createSectionLoader} from '../src/loading.js'
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
