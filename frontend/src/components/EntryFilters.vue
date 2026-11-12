<script setup>
import { reactive, onBeforeUnmount } from 'vue';
import { money, signed } from '../display.js';
const props = defineProps({
  filters: Object,
  summary: Object,
  busy: Boolean
});
const emit = defineEmits(['apply', 'editing']);
const draft = reactive({
  ...props.filters
});
function apply() {
  emit('editing', false);
  emit('apply', {
    ...draft
  });
}
function reset() {
  Object.assign(draft, {
    kind: 'ALL',
    start: '',
    end: ''
  });
  apply();
}
onBeforeUnmount(() => emit('editing', false));
</script>
<template>
  <section class="card entry-filters">
    <details>
      <summary>
        筛选交易与资金流水
      </summary>
      <form class="filter-form" @input="emit('editing',true)" @change="emit('editing',true)" @submit.prevent="apply">
        <label class="filter-field">
          类型
          <select v-model="draft.kind">
            <option value="ALL">
              全部记录
            </option>
            <option value="BUY">
              买入
            </option>
            <option value="SELL">
              卖出
            </option>
            <option value="CASH">
              资金变动
            </option>
            <option value="CORRECTED">
              有纠错的成交
            </option>
            <option value="CORRECTION">
              纠错记录
            </option>
          </select>
        </label>
        <label class="filter-field">
          记账起始日期
          <input v-model="draft.start" type="date">
        </label>
        <label class="filter-field">
          记账结束日期
          <input v-model="draft.end" type="date">
        </label>
        <div class="button-row">
          <van-button size="small" round type="primary" native-type="submit" :loading="busy">
            应用筛选
          </van-button>
          <van-button size="small" round plain native-type="button" :disabled="busy" @click="reset">
            重置
          </van-button>
        </div>
      </form>
    </details>
    <p v-if="summary" class="hint">
      所选记录合计 · 买入 ¥{{money(summary.buy_amount)}} · 卖出 ¥{{money(summary.sell_amount)}}
      <br>
      交易手续费 ¥{{money(summary.fees)}} · 资金净变动 {{signed(summary.cash_change)}} 元
    </p>
    <p class="tiny">
      按记账日期筛选，金额采用当前有效值，纠错记录不会重复计入。
    </p>
  </section>
</template>
