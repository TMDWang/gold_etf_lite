import {test} from 'node:test'
import assert from 'node:assert/strict'
import {tradingChartData,chartExtremes,extremeMarkers} from '../src/price-chart.js'

test('markers use actual visible extrema and remain inside the chart edges',()=>{
  const chart=tradingChartData([{at:'2026-11-05T09:30:00+08:00',price:'4.9'},{at:'2026-11-05T15:00:00+08:00',price:'5.2'}])
  const markers=extremeMarkers(chart)
  assert.deepEqual(markers.map(x=>x.coord),[['09:30',4.9],['15:00',5.2]])
  assert.equal(markers[0].label.formatter,'最低 4.900');assert.equal(markers[0].label.align,'left')
  assert.equal(markers[1].label.formatter,'最高 5.200');assert.equal(markers[1].label.align,'right')
})

test('equal extrema use one combined marker and empty data has none',()=>{
  assert.deepEqual(extremeMarkers(tradingChartData([])),[])
  const markers=extremeMarkers(tradingChartData([{at:'2026-11-05T10:00:00+08:00',price:'5'}]))
  assert.equal(markers.length,1);assert.equal(markers[0].label.formatter,'最高/最低 5.000')
})

test('highest and lowest are derived only from visible sampled prices',()=>{
  const points=[{at:'2026-11-05T09:30:00+08:00',price:'5.003'},{at:'2026-11-05T10:00:00+08:00',price:'5.123'},{at:'2026-11-05T11:45:00+08:00',price:'8.000'},{at:'2026-11-05T14:00:00+08:00',price:'4.991'}]
  assert.deepEqual(chartExtremes(points),{high:5.123,low:4.991})
  assert.deepEqual(chartExtremes([]),{high:null,low:null})
})

test('compresses lunch while preserving trading-minute gaps',()=>{
  const result=tradingChartData([
    {at:'2026-11-05T11:29:00+08:00',price:'5.000'},
    {at:'2026-11-05T11:30:00+08:00',price:'5.001'},
    {at:'2026-11-05T13:00:00+08:00',price:'5.010'},
    {at:'2026-11-05T13:02:00+08:00',price:'5.020'},
  ])
  const before=result.times.indexOf('11:30'),after=result.times.indexOf('13:00')
  assert.equal(after,before+1)
  assert.deepEqual(result.prices.slice(before,after+3),[5.001,5.010,null,5.020])
  assert.equal(result.times.includes('12:00'),false)
})

test('converts UTC timestamps to Beijing time and excludes non-trading and bad values',()=>{
  const result=tradingChartData([
    {at:'2026-11-05T05:00:00Z',price:'5.100'},
    {at:'2026-11-05T04:00:00Z',price:'5.200'},
    {at:'invalid',price:'4'},
    {at:'2026-11-05T05:01:00Z',price:'bad'},
  ])
  assert.equal(result.prices[result.times.indexOf('13:00')],5.1)
  assert.equal(result.prices[result.times.indexOf('13:01')],null)
  assert.equal(result.prices.filter(x=>x!==null).length,1)
})

test('connects the usual 11:30 and 13:01 observations without inventing a 13:00 point',()=>{
  const result=tradingChartData([
    {at:'2026-11-05T11:30:00+08:00',price:'5.001'},
    {at:'2026-11-05T13:01:00+08:00',price:'5.010'},
  ])
  const before=result.times.indexOf('11:30'),after=result.times.indexOf('13:01')
  assert.equal(after,before+1)
  assert.equal(result.times.includes('13:00'),false)
  assert.deepEqual(result.prices.slice(before,after+1),[5.001,5.010])
})
