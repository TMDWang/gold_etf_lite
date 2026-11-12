<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue';
const props = defineProps({
  request: Function
});
const emit = defineEmits(['settings', 'alert']);
const setup = ref(null),
  error = ref('');
let active = true;
let generation = 0;
async function load() {
  const token = ++generation;
  error.value = '';
  try {
    const value = await props.request('/account/setup/');
    if (active && generation === token) setup.value = value;
  } catch (e) {
    if (active && generation === token && e.code !== 'CANCELLED') error.value = e.message;
  }
}
onMounted(load);
onBeforeUnmount(() => {
  active = false;
});
</script>
<template>
  <section v-if="error||(setup&&!Object.values(setup).every(Boolean))" class="card setup-checklist">
    <div class="row">
      <h2>
        开始使用金笺
      </h2>
      <button class="text-button" @click="load">
        检查进度
      </button>
    </div>
    <p v-if="error" class="hint">
      {{error}}
    </p>
    <template v-if="setup">
      <p class="hint">
        完成自己的费用与通知设置后，提醒才方便使用。
      </p>
      <van-cell title="建立自己的账本" :value="setup.account_ready?'已完成':'待完成'"/>
      <van-cell title="设置券商费用" :value="setup.fees_ready?'已完成':'去设置'" is-link @click="emit('settings')"/>
      <van-cell title="绑定个人 PushPlus" :value="setup.push_ready?'已绑定':'去设置'" is-link @click="emit('settings')"/>
      <van-cell title="测试个人通知" :value="setup.test_ready?'服务已接收':'去测试'" is-link @click="emit('settings')"/>
      <van-cell title="添加自己的第一条提醒或计划" :value="setup.rule_ready?'已完成':'去添加'" is-link @click="emit('alert')"/>
    </template>
  </section>
</template>
