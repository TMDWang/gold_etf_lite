import {test} from 'node:test'
import assert from 'node:assert/strict'
import {packageVersion} from '../scripts/version.js'

test('frontend version comes from package metadata in semantic version form',()=>{
  assert.equal(packageVersion({version:'0.2.0'}),'0.2.0')
  assert.equal(packageVersion({version:'1.0.0-rc.1+build.5'}),'1.0.0-rc.1+build.5')
  assert.throws(()=>packageVersion({version:'hash123'}))
  assert.throws(()=>packageVersion({version:'01.2.3'}))
  assert.throws(()=>packageVersion({version:'1.0.0-01'}))
})
