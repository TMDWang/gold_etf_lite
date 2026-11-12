<script setup>
import { ref, onBeforeUnmount } from 'vue';
const props = defineProps({
  request: Function
});
const open = ref(false),
  rows = ref([]),
  count = ref(0),
  page = ref(1),
  scope = ref('ALL'),
  busy = ref(false),
  error = ref('');
const labels = {
  OPEN: '条件已达到',
  CLOSED: '条件已解除或计划已结束',
  IGNORED: '已停止本轮',
  UNKNOWN: '送达结果未确认',
  FAILED: '发送失败'
};
const deliveryLabels = {
  SENT: 'PushPlus 已接收',
  SENDING: '发送中',
  FAILED: '发送失败',
  UNKNOWN: '结果未确认',
  SKIPPED: '已作废'
};
const time = value => new Date(value).toLocaleString('zh-CN', {
  timeZone: 'Asia/Shanghai',
  hour12: false
});
let active = true,
  generation = 0;
async function load() {
  const token = ++generation;
  busy.value = true;
  error.value = '';
  try {
    const result = await props.request(`/reminders/history/?page=${page.value}&scope=${scope.value}`);
    if (active && generation === token) {
      rows.value = result.results;
      count.value = result.count;
    }
  } catch (e) {
    if (active && generation === token && e.code !== 'CANCELLED') error.value = e.message;
  } finally {
    if (active && generation === token) busy.value = false;
  }
}
function toggle() {
  open.value = !open.value;
  if (open.value) load();
}
function filter() {
  page.value = 1;
  load();
}
onBeforeUnmount(() => {
  active = false;
  generation++;
});
</script>
<template>
  <section class="card reminder-history">
    <div class="row">
      <h2>
        提醒历史
      </h2>
      <button class="text-button" :aria-expanded="open" @click="toggle">
        {{open?'收起':'查看'}}
      </button>
    </div>
    <template v-if="open">
      <div class="button-row">
        <label class="filter-field">
          消息范围
          <select v-model="scope" @change="filter">
            <option value="ALL">
              全部
            </option>
            <option value="PERSONAL">
              个人
            </option>
            <option value="PUBLIC">
              公共群组
            </option>
          </select>
        </label>
        <van-button round plain size="small" :loading="busy" @click="load">
          刷新
        </van-button>
      </div>
      <p v-if="error" class="danger" role="status">
        {{error}}
      </p>
      <div v-for="item in rows" :key="item.id" class="entry-row">
        <div class="row">
          <strong>
            {{item.label}}
          </strong>
          <span class="tiny">
            {{item.scope==='PUBLIC'?'公共群组':'个人'}}
          </span>
        </div>
        <p>
          {{labels[item.status]||item.status}} · PushPlus 已接收 {{item.sent_count}} 次
        </p>
        <p class="hint">
          {{time(item.created_at)}} 触发
          <template v-if="item.context.price">
            · 参考价 ¥{{item.context.price}}
          </template>
        </p>
        <p class="hint">
          {{item.context.reason}}
        </p>
        <p v-if="item.delivery_status" class="hint">
          {{deliveryLabels[item.delivery_status]||item.delivery_status}} · {{item.delivery_detail}}
        </p>
        <p v-else-if="item.scope==='PUBLIC'" class="hint">
          {{item.delivery_detail}}
        </p>
        <p v-else class="tiny">
          尚无发送记录，请查看规则状态及个人通知配置。
        </p>
      </div>
      <van-empty v-if="!busy&&!rows.length" description="暂无提醒记录" :image-size="60"/>
      <van-pagination v-if="count>20" v-model="page" :total-items="count" :items-per-page="20" mode="simple" @change="load"/>
    </template>
  </section>
</template>
