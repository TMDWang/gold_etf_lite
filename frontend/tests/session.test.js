import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createSessionRequests} from '../src/loading.js'
const deferred=()=>{let resolve;const promise=new Promise(a=>{resolve=a});return{promise,resolve}}
test('session invalidation rejects late direct settings and initialization results',async()=>{
  for(const method of ['request','submit']){
    const old=deferred();const scoped=createSessionRequests({request:()=>old.promise,submit:()=>old.promise})
    let popup='';const pending=scoped[method]('/settings/').then(()=>{popup='settings'})
    scoped.invalidate();old.resolve({oldAccount:true})
    await assert.rejects(pending,e=>e.code==='CANCELLED');assert.equal(popup,'')
  }
})
