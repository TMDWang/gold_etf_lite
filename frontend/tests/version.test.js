import {test} from 'node:test'
import assert from 'node:assert/strict'
import {fingerprintEntries} from '../scripts/version.js'

test('frontend fingerprint is stable across traversal order and changes with content',()=>{
  const items=[['src/a.js',Buffer.from('one')],['public/icon.svg',Buffer.from('two')]]
  assert.match(fingerprintEntries(items),/^[0-9a-f]{10}$/)
  assert.equal(fingerprintEntries(items),fingerprintEntries([...items].reverse()))
  assert.notEqual(fingerprintEntries(items),fingerprintEntries([['src/a.js',Buffer.from('changed')],items[1]]))
})
