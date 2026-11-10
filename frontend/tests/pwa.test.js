import {test} from 'node:test'
import assert from 'node:assert/strict'
import {shellCacheConfig} from '../scripts/cache-config.js'
import {registerShellWorker} from '../src/pwa.js'
test('worker caches only generic shell and static assets, never private API or other navigations',()=>{
  const config=shellCacheConfig('dist','abc')
  assert.ok(config.globIgnores.includes('assets/PriceChart-*.js'))
  const [navigation, chart]=config.runtimeCaching
  assert.equal(navigation.handler,'NetworkOnly')
  assert.equal(navigation.options.precacheFallback.fallbackURL,'/offline-shell.html')
  assert.equal(chart.handler,'CacheFirst')
  assert.equal(chart.urlPattern({url:new URL('https://example.test/static/assets/PriceChart-abc.js'),sameOrigin:true}),true)
  assert.equal(chart.urlPattern({url:new URL('https://example.test/api/account/'),sameOrigin:true}),false)
  assert.equal(chart.urlPattern({url:new URL('https://other.test/static/assets/PriceChart-abc.js'),sameOrigin:false}),false)
  assert.deepEqual(config.additionalManifestEntries,[{url:'/offline-shell.html',revision:'abc'}])
  assert.equal(config.skipWaiting,false)
  assert.equal(config.navigateFallback,undefined)
  const matches=(path,mode='navigate',sameOrigin=true)=>navigation.urlPattern({url:new URL(path,'https://example.test'),request:{mode},sameOrigin})
  assert.equal(matches('/'),true)
  assert.equal(matches('/?reload=1'),true)
  assert.equal(matches('/','cors'),false)
  assert.equal(matches('/','navigate',false),false)
  for(const path of ['/api/account/','/api/auth/login/','/api/entries/','/health/','/other/'])
    assert.equal(matches(path),false)
  assert.deepEqual(Object.keys(config.modifyURLPrefix),[''])
  assert.ok(config.globPatterns.every(glob=>!glob.includes('html')&&!glob.includes('api')))
})

test('detects an update already installing when registration resolves',async()=>{
  let updateNotice=0, onStateChange
  const worker={state:'installing',addEventListener(name,fn){if(name==='statechange')onStateChange=fn}}
  const reg={installing:worker,waiting:null,addEventListener(){},update:async()=>{}}
  const container={controller:{},addEventListener(){},removeEventListener(){},register:async()=>reg}
  const shell=registerShellWorker(()=>updateNotice++,{serviceWorker:container},{reload(){}})
  await Promise.resolve()
  reg.installing=null;reg.waiting=worker;worker.state='installed';onStateChange?.()
  assert.equal(updateNotice,1)
  shell.dispose()
})

test('a later update check detects an already waiting worker',async()=>{
  let updateNotice=0
  const reg={installing:null,waiting:null,addEventListener(){},update:async()=>{reg.waiting={}}}
  const container={controller:{},addEventListener(){},removeEventListener(){},register:async()=>reg}
  const shell=registerShellWorker(()=>updateNotice++,{serviceWorker:container},{reload(){}})
  await Promise.resolve();shell.check();await Promise.resolve();await Promise.resolve()
  assert.equal(updateNotice,1)
  shell.dispose()
})

test('a worker activation that completes while a form is open waits before reload',async()=>{
  let safe=true,reloads=0,onController
  const worker={postMessage(){}}
  const reg={installing:null,waiting:worker,addEventListener(){},update:async()=>{}}
  const container={controller:{},addEventListener(name,fn){if(name==='controllerchange')onController=fn},removeEventListener(){},register:async()=>reg}
  const shell=registerShellWorker(()=>{}, {serviceWorker:container}, {reload(){reloads++}}, ()=>safe)
  await Promise.resolve();shell.activate();safe=false;reg.waiting=null;onController()
  assert.equal(reloads,0);safe=true;shell.activate();assert.equal(reloads,1)
  shell.dispose()
})
