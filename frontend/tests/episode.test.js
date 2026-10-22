import {test} from 'node:test'
import assert from 'node:assert/strict'
import {resolveEpisodePlan} from '../src/loading.js'
test('episode confirmation requires exact loaded active plan; never silently becomes manual',()=>{
  const episode={plan:7,version:3,side:'BUY'}
  assert.equal(resolveEpisodePlan(episode,[]),null)
  assert.equal(resolveEpisodePlan(episode,[{id:7,version:2,side:'BUY',status:'ACTIVE'}]),null)
  assert.equal(resolveEpisodePlan(episode,[{id:7,version:3,side:'BUY',status:'COMPLETED'}]),null)
  const plan={id:7,version:3,side:'BUY',status:'ACTIVE'}
  assert.equal(resolveEpisodePlan(episode,[plan]),plan)
})
