<script setup>
import { ref, onBeforeUnmount } from 'vue';
import { money, signed } from '../display.js';
const props = defineProps({
  request: Function,
  submit: Function
});
const check = ref(null),
  reports = ref([]),
  versions = ref([]),
  open = ref(false),
  busy = ref(false),
  error = ref(''),
  page = ref(1),
  count = ref(0);
let active = true,
  generation = 0;
const time = value => value ? new Date(value).toLocaleString('zh-CN', {
  timeZone: 'Asia/Shanghai',
  hour12: false
}) : '暂无';
const fieldLabels = {
  cash: '现金',
  shares: '份额',
  cost_basis: '持仓成本',
  realized: '卖出净收益'
};
async function run(task) {
  if (busy.value) return;
  const token = ++generation;
  busy.value = true;
  error.value = '';
  try {
    const apply = await task();
    if (active && token === generation) apply();
  } catch (e) {
    if (active && token === generation && e.code !== 'CANCELLED') error.value = e.message || '读取未完成，请重试';
  } finally {
    if (active && token === generation) busy.value = false;
  }
}
function reconcile() {
  return run(async () => {
    const result = await props.request('/account/reconciliation/');
    return () => {
      check.value = result;
    };
  });
}
function load(refresh = false) {
  return run(async () => {
    const result = refresh ? await props.submit('/account/reports/', {}) : await props.request(`/account/reports/?page=${page.value}`);
    return () => {
      reports.value = result.results;
      count.value = result.count;
      if (refresh) page.value = 1;
      versions.value = [];
    };
  });
}
function toggle() {
  open.value = !open.value;
  if (open.value) load();
}
function changePage(value) {
  page.value = value;
  load();
}
function showVersions(day) {
  return run(async () => {
    const result = await props.request(`/account/reports/?day=${day}`);
    return () => {
      versions.value = result.results;
    };
  });
}
onBeforeUnmount(() => {
  active = false;
  generation++;
});
</script>
<template>
  <section class="card account-tools">
    <div class="row">
      <h2>
        账目核对
      </h2>
      <van-button round plain size="small" :loading="busy" @click="reconcile">
        检查账目
      </van-button>
    </div>
    <p class="hint">
      从期初和有效流水重新计算，与当前现金、份额、成本及卖出收益核对。
    </p>
    <div v-if="check" role="status">
      <p :class="check.consistent?'success-text':'danger'">
        {{check.consistent?'账目一致':'发现差异，请核对流水后联系维护者'}}
      </p>
      <p class="tiny">
        检查于 {{time(check.checked_at)}}
      </p>
      <div v-for="(difference,key) in check.differences" :key="key" class="hint">
        {{fieldLabels[key]||key}} · 保存值 {{difference.stored}} · 流水重算 {{difference.calculated}}
      </div>
    </div>
    <p v-if="error" class="danger" role="status">
      {{error}}
    </p>
  </section>
  <section class="card report-card">
    <div class="row">
      <h2>
        每日资产与收益
      </h2>
      <button class="text-button" :aria-expanded="open" @click="toggle">
        {{open?'收起':'查看'}}
      </button>
    </div>
    <template v-if="open">
      <p class="hint">
        北京时间收盘后生成，按记账日期归属。补录计入登记日，纠错保留报表修订。持仓估值采用收盘附近采样，未扣未来卖出费用。
      </p>
      <van-button round plain size="small" :loading="busy" @click="load(true)">
        重新核对并生成日报
      </van-button>
      <div v-for="report in reports" :key="report.id" class="entry-row">
        <div class="row">
          <strong>
            {{report.day}}
          </strong>
          <button class="text-button" :disabled="busy" @click="showVersions(report.day)">
            第 {{report.revision}} 版
          </button>
        </div>
        <div class="metrics">
          <div>
            <span>
              总资产
            </span>
            <strong>
              ¥{{money(report.equity)}}
            </strong>
          </div>
          <div>
            <span>
              当日净收益
            </span>
            <strong>
              {{signed(report.daily_profit)}}
            </strong>
          </div>
        </div>
        <p class="tiny">
          现金 ¥{{money(report.cash)}} · {{report.shares}} 份 · 市值 ¥{{money(report.market_value)}}
        </p>
        <p v-if="report.valuation_status==='MISSING_CLOSE'" class="hint">
          缺少有效收盘附近行情，资产及相关收益待补。
        </p>
        <p v-else-if="report.close_quote" class="tiny">
          {{report.close_quote.source}} · {{time(report.close_quote.at)}} · 采样价 ¥{{report.close_quote.price}}
        </p>
        <p v-if="report.unclassified_count" class="hint">
          有 {{report.unclassified_count}} 笔未分类资金，累计投资收益待核对。
        </p>
        <p v-if="report.daily_profit==null" class="hint">
          当日收益待核对，需相邻交易日的有效估值和明确的期间资金分类。
        </p>
      </div>
      <van-empty v-if="!busy&&!reports.length" description="暂无收盘日报" :image-size="60"/>
      <van-pagination v-if="count>20" :model-value="page" :total-items="count" :items-per-page="20" mode="simple" @change="changePage"/>
      <div v-if="versions.length" class="preview">
        <h3>
          {{versions[0].day}} 的报表修订
        </h3>
        <p v-for="version in versions" :key="version.id" class="hint">
          第 {{version.revision}} 版 · 总资产 ¥{{money(version.equity)}} · 当日收益 {{signed(version.daily_profit)}}
          <br>
          {{time(version.created_at)}} 生成
        </p>
      </div>
    </template>
  </section>
</template>
