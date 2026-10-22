<script setup>
defineProps({state: {type: Object, required: true}, label: {type: String, required: true}})
defineEmits(['retry'])
</script>
<template>
  <div v-if="state.error" class="section-error" role="status"><span>{{label}}暂未更新：{{state.error}}</span><button class="text-button" @click="$emit('retry')">重试</button></div>
  <div v-else-if="state.pending" class="section-pending" role="status"><van-loading size="12"/> 正在更新{{label}}…</div>
</template>
