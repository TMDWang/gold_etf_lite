import {test} from 'node:test'
import assert from 'node:assert/strict'
import {shellCacheConfig} from '../scripts/cache-config.js'
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
