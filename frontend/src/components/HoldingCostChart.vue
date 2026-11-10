<script setup>
import { computed, ref, watch } from 'vue'
import { beijingInput } from '../display'

const props = defineProps({ points: { type: Array, required: true } })
const index = ref(0)
watch(() => props.points, points => { index.value = Math.max(0, points.length - 1) }, { immediate: true })

const cost = point => point?.unit_cost == null ? null : Number(point.unit_cost)
const selected = computed(() => props.points[index.value])
const formatCost = point => cost(point) == null ? '—' : cost(point).toFixed(4)
const graph = computed(() => {
  const values = props.points.map(cost).filter(value => value != null)
  const min = values.length ? Math.min(...values) : 0
  const span = values.length ? Math.max(...values) - min : 0
  const dots = props.points.map((point, i) => {
    const value = cost(point)
    const x = 12 + 336 * i / Math.max(1, props.points.length - 1)
    return { x, y: value == null ? null : span ? 110 - 96 * (value - min) / span : 62 }
  })
  let drawing = false
  const line = dots.map(({ x, y }) => {
    if (y == null) { drawing = false; return '' }
    const command = drawing ? 'L' : 'M'
    drawing = true
    return `${command}${x},${y}`
  }).join(' ')
  return { dots, line }
})

const label = point => point.side === 'INITIAL' ? '期初' : `${point.side === 'BUY' ? '买入' : '卖出'} ${point.quantity} 份`
</script>

<template>
  <div v-if="selected" class="holding-history">
    <svg viewBox="0 0 360 124" role="img" aria-label="按记账顺序显示每份持仓成本">
      <path d="M12 110H348 M12 62H348 M12 14H348" fill="none" stroke="#ede8dc" stroke-dasharray="4 4"/>
      <path :d="graph.line" fill="none" stroke="#a37a30" stroke-width="2.5"/>
      <template v-for="(dot, i) in graph.dots" :key="i">
        <circle v-if="dot.y!=null" :cx="dot.x" :cy="dot.y" :r="i===index?5:3" :fill="points[i].side==='SELL'?'#37856b':'#a37a30'" @click="index=i">
          <title>{{label(points[i])}} · 每份成本 {{formatCost(points[i])}}</title>
        </circle>
      </template>
    </svg>
    <div class="row">
      <button class="text-button" type="button" :disabled="index===0" @click="index--">上一笔</button>
      <span class="tiny">{{index+1}} / {{points.length}}</span>
      <button class="text-button" type="button" :disabled="index===points.length-1" @click="index++">下一笔</button>
    </div>
    <p class="muted">{{label(selected)}} · {{beijingInput(new Date(selected.at)).replace('T',' ')}}（北京时间）</p>
    <p class="hint">持有 {{selected.shares}} 份 · 每份成本 {{formatCost(selected)}} · 现金 ¥{{Number(selected.cash).toFixed(2)}}</p>
    <p class="tiny">按记账顺序排列，清仓时不显示每份成本。</p>
  </div>
</template>

<style scoped>
.holding-history svg{display:block;width:100%;height:auto;margin-top:12px}
.holding-history circle{cursor:pointer}
.holding-history button:disabled{opacity:.4;cursor:default}
.holding-history .hint{margin-top:3px}
</style>
