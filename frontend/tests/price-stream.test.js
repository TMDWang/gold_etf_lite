import {test} from 'node:test'
import assert from 'node:assert/strict'
import {createPriceStream} from '../src/price-stream.js'

test('price stream reports live data and stops without applying stale events',()=>{
  const instances=[],received=[],states=[]
  class FakeSource {constructor(url){this.url=url;this.handlers={};instances.push(this)}addEventListener(k,v){this.handlers[k]=v}close(){this.closed=true}}
  const stream=createPriceStream({EventSourceImpl:FakeSource,onPrice:x=>received.push(x),onState:x=>states.push(x)})
  stream.start();assert.equal(instances.length,1);assert.equal(instances[0].url,'/api/quote/stream/')
  instances[0].onopen();instances[0].handlers.price({data:'{"quote":{"price":"4.000"}}'})
  assert.equal(states.at(-1),'live');assert.equal(received[0].quote.price,'4.000')
  stream.stop();instances[0].handlers.price({data:'{"quote":{"price":"5.000"}}'})
  assert.equal(received.length,1);assert.ok(instances[0].closed)
})
test('disconnection triggers one fallback and bounded reconnect',()=>{
  const instances=[],timers=[],states=[];let fallbacks=0
  class FakeSource {constructor(){this.handlers={};instances.push(this)}addEventListener(k,v){this.handlers[k]=v}close(){this.closed=true}}
  const stream=createPriceStream({EventSourceImpl:FakeSource,onState:x=>states.push(x),onFallback:()=>fallbacks++,schedule:(fn,ms)=>{timers.push({fn,ms});return timers.length},cancel(){}})
  stream.start();instances[0].onerror();instances[0].onerror()
  assert.equal(fallbacks,1);assert.equal(states.at(-1),'fallback');assert.equal(timers.at(-1).ms,30000)
  timers.at(-1).fn();assert.equal(instances.length,2);stream.stop();assert.ok(instances[1].closed)
})
test('a silently stalled connection falls back, while heartbeats keep it alive',()=>{
  const instances=[],timers=new Map();let next=0,fallbacks=0
  class FakeSource {constructor(){this.handlers={};instances.push(this)}addEventListener(k,v){this.handlers[k]=v}close(){this.closed=true}}
  const stream=createPriceStream({EventSourceImpl:FakeSource,onFallback:()=>fallbacks++,schedule:(fn,ms)=>{const id=++next;timers.set(id,{fn,ms});return id},cancel:id=>timers.delete(id)})
  stream.start();instances[0].onopen()
  assert.equal(timers.size,1);const first=[...timers.keys()][0]
  instances[0].handlers.heartbeat({data:'{}'});assert.equal(timers.has(first),false)
  const watchdog=[...timers.values()][0];assert.ok(watchdog.ms>=30000);watchdog.fn()
  assert.equal(fallbacks,1);assert.ok(instances[0].closed)
  stream.stop()
})
