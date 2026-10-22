<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])
const props = defineProps({ points: { type: Array, default: () => [] } })
const el = ref(null)
let chart, observer
function render() {
  if (!chart) return
  const points = []
  let previous
  for (const p of props.points) {
    const at = new Date(p.at).getTime()
    if (previous && at - previous > 90000) points.push([previous + 60000, null])
    points.push([at, Number(p.price)])
    previous = at
  }
  chart.setOption({ animation: false, grid: { left: 46, right: 12, top: 12, bottom: 28 }, tooltip: { trigger: 'axis', valueFormatter: v => v == null ? '缺少数据' : Number(v).toFixed(3) }, xAxis: { type: 'time', axisLine: { lineStyle: { color: '#e6e3da' } }, axisLabel: { color: '#8c8a7f', formatter: v => new Date(v).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Shanghai' }) }, splitLine: { show: false } }, yAxis: { type: 'value', scale: true, axisLabel: { color: '#8c8a7f', formatter: v => Number(v).toFixed(3) }, splitLine: { lineStyle: { color: '#eeece6', type: 'dashed' } } }, series: [{ type: 'line', showSymbol: false, connectNulls: false, data: points, lineStyle: { color: '#ae8132', width: 2 }, areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [{ offset: 0, color: '#d8b56e42' }, { offset: 1, color: '#d8b56e00' }]) } }] })
}
onMounted(() => { chart = echarts.init(el.value); observer = new ResizeObserver(() => chart.resize()); observer.observe(el.value); render() })
watch(() => props.points, render, { deep: true })
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
</script>
<template><div ref="el" class="chart" role="img" :aria-label="`今日价格曲线，已取得 ${points.length} 个数据点`"></div></template>
