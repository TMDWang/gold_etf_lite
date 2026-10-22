import { test } from 'node:test'
import assert from 'node:assert/strict'
import { money, signed, tradePreview, beijingInput, backupSummary } from '../src/display.js'
test('missing prices are not displayed as zero profit', () => {
  assert.equal(money(null), '—')
  assert.equal(signed('0.00'), '0.00')
  assert.equal(signed('-12.3'), '-12.30')
})
test('trade preview includes fee and direction', () => {
  assert.equal(tradePreview({side:'BUY', quantity:100, price:'5',fee:'1'}), '现金 -501.00 · 份额 +100')
  assert.equal(tradePreview({side:'SELL', quantity:100, price:'5',fee:'1'}), '现金 +499.00 · 份额 -100')
})
test('default datetime input matches native minute step and Beijing timezone', () => {
  assert.equal(beijingInput('2026-10-21T11:46:10Z'), '2026-10-21T19:46')
})
test('backup failure remains visible even after a prior success', () => {
  const status = backupSummary({ok:false,last_success:'2026-10-20',last_failure:'2026-10-21',message:'备份未成功'})
  assert.match(status,/失败/)
  assert.match(status,/2026-10-21/)
  assert.match(status,/2026-10-20/)
})
