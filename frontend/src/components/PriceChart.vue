<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { tradingChartData } from '../price-chart'
echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])
const props = defineProps({ points: { type: Array, default: () => [] } })
const el = ref(null)
let chart, observer
function render() {
  if (!chart) return
  const {times, prices} = tradingChartData(props.points)
  chart.setOption({ animation: false, grid: { left: 46, right: 12, top: 12, bottom: 28 }, tooltip: { trigger: 'axis', valueFormatter: v => v == null ? '缺少数据' : Number(v).toFixed(3) }, xAxis: { type: 'category', boundaryGap: false, data: times, axisLine: { lineStyle: { color: '#e6e3da' } }, axisLabel: { color: '#8c8a7f', interval: (_i, value) => ['09:30','10:30','11:30','14:00','15:00'].includes(value), hideOverlap: true }, splitLine: { show: false } }, yAxis: { type: 'value', scale: true, axisLabel: { color: '#8c8a7f', formatter: v => Number(v).toFixed(3) }, splitLine: { lineStyle: { color: '#eeece6', type: 'dashed' } } }, series: [{ type: 'line', showSymbol: false, connectNulls: false, data: prices, lineStyle: { color: '#ae8132', width: 2 }, areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: '#d8b56e42' }, { offset: 1, color: '#d8b56e00' }]) } }] })
}
onMounted(() => { chart = echarts.init(el.value); observer = new ResizeObserver(() => chart.resize()); observer.observe(el.value); render() })
watch(() => props.points, render, { deep: true })
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
</script>
<template><div ref="el" class="chart" role="img" :aria-label="`今日价格曲线，已取得 ${points.length} 个数据点`"></div></template>
