<script setup>
import { ref, watch } from 'vue'
import { showToast } from 'vant'
import { money, signed } from '../display'

const props = defineProps({
  price: [String, Number],
  account: { type: Object, required: true },
  submit: { type: Function, required: true },
})
const newLeg = (quantity = '') => ({ price: props.price ?? '', quantity, fee: '' })
const legs = ref([newLeg('100'), newLeg(String(Math.min(100, props.account.shares - 100)))])
const result = ref(null), loading = ref(false)
let revision = 0

watch(() => [legs.value, props.account.shares, props.account.cash, props.account.cost_basis], () => {
  revision++
  result.value = null
}, {deep:true, flush:'sync'})

async function calculate() {
  if (loading.value) return
  loading.value = true
  const current = revision
  const body = {legs:legs.value.map(({price,quantity,fee}) => ({price,quantity,...(fee===''?{}:{fee})}))}
  try {
    const preview = await props.submit('/account/sell-batch-preview/', body)
    if (current === revision) result.value = preview
  } catch(error) {
    if (error.code !== 'CANCELLED') showToast(error.message?.includes('可能已保存')?'连接中断，试算未完成，请重试':error.message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <h2>分批卖出试算</h2>
  <p class="hint">按输入顺序试算 2 至 5 批卖出，每批分别计算手续费和结转成本。当前持仓 {{account.shares}} 份。</p>
  <van-form @submit="calculate">
    <div v-for="(leg,index) in legs" :key="index" class="entry-row">
      <div class="row"><strong>第 {{index+1}} 批</strong><button v-if="legs.length>2" class="text-button" type="button" @click="legs.splice(index,1)">移除</button></div>
      <van-field v-model="leg.price" label="成交价 / 元" type="number" required/>
      <van-field v-model="leg.quantity" label="卖出份额" type="digit" required/>
      <van-field v-model="leg.fee" label="手续费 / 元" type="number" placeholder="留空按设置估算"/>
    </div>
    <van-button v-if="legs.length<5" block round plain native-type="button" @click="legs.push(newLeg())">＋ 增加一批</van-button>
    <van-button block round type="primary" native-type="submit" :loading="loading">试算合计</van-button>
  </van-form>
  <div v-if="result" class="preview" aria-live="polite">
    <strong>预计净到账 ¥{{money(result.net)}} · 净盈亏 {{signed(result.realized)}} 元</strong>
    <p v-for="(leg,index) in result.legs" :key="index" class="hint">第 {{index+1}} 批 {{leg.quantity}} 份 · 净到账 ¥{{money(leg.net)}} · 手续费 ¥{{money(leg.fee)}} · 剩余 {{leg.shares_after}} 份</p>
    <p class="hint">试算后现金 ¥{{money(result.after.cash)}}，剩余持仓成本 ¥{{money(result.after.cost_basis)}}。实际成交后请逐笔核对入账。</p>
  </div>
</template>
