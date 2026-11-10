<script setup>
import { ref } from 'vue'
import { getTheme, setTheme } from '../theme'
const choice = ref(getTheme())
</script>

<template>
  <label class="theme-picker"><span>外观</span><select v-model="choice" @change="setTheme(choice)" aria-label="外观主题">
    <option value="system">跟随系统</option>
    <option value="light">浅色</option>
    <option value="dark">深色</option>
  </select></label>
</template>

<style scoped>
.theme-picker{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:12px 0}
.theme-picker select{font:inherit;color:inherit;background:var(--van-background-2,#fff);border:1px solid var(--van-border-color,#ddd9cc);border-radius:8px;padding:5px}
</style>
