import {test} from 'node:test'
import assert from 'node:assert/strict'
import {shellCacheConfig} from '../scripts/cache-config.js'
import {registerShellWorker} from '../src/pwa.js'
test('worker caches only generic shell and static assets, never private API or other navigations',()=>{
  const config=shellCacheConfig('dist','abc')
  assert.deepEqual(config.runtimeCaching,[])
  assert.deepEqual(config.additionalManifestEntries,[{url:'/',revision:'abc'}])
  assert.equal(config.skipWaiting,false)
  assert.equal(config.navigateFallback,'/')
  for(const path of ['/api/account/','/api/auth/login/','/api/entries/','/health/','/other/'])
    assert.equal(config.navigateFallbackAllowlist.some(re=>re.test(path)),false)
  assert.equal(config.navigateFallbackAllowlist.some(re=>re.test('/')),true)
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
