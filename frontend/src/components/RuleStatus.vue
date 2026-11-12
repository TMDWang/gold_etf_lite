<script setup>
const props = defineProps({
  evaluation: Object,
  unit: {
    type: String,
    default: '元'
  }
});
const number = value => value == null ? '—' : Number(value).toLocaleString('zh-CN', {
  maximumFractionDigits: 4
});
const time = value => new Date(value).toLocaleString('zh-CN', {
  timeZone: 'Asia/Shanghai',
  hour12: false
});
</script>
<template>
  <div v-if="evaluation" class="rule-status">
    <p>
      {{evaluation.reason}}
    </p>
    <p v-if="evaluation.value!=null&&evaluation.target!=null" class="hint">
      当前 {{number(evaluation.value)}} {{unit}} · 距条件 {{number(evaluation.gap)}} {{unit}}
    </p>
    <p v-if="evaluation.net_percent!=null" class="hint">
      本笔预计扣费后净收益率 {{number(evaluation.net_percent)}}%
    </p>
    <p v-if="evaluation.net_gap!=null" class="hint">
      距净收益率目标 {{number(evaluation.net_gap)}} 个百分点
    </p>
    <p v-if="evaluation.snoozed_until&&evaluation.state==='SNOOZED'" class="hint">
      暂停至 {{time(evaluation.snoozed_until)}}
    </p>
    <p v-if="evaluation.delivery_reason" class="tiny">
      {{evaluation.delivery_reason}}
    </p>
  </div>
</template>
