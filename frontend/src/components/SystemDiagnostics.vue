<script setup>
defineProps({
  data: Object
});
const time = value => value ? new Date(value).toLocaleString('zh-CN', {
  timeZone: 'Asia/Shanghai',
  hour12: false
}) : '暂无';
</script>
<template>
  <section v-if="data?.checked_at" class="system-diagnostics">
    <h3>
      维护检查
    </h3>
    <p class="tiny">
      检查于 {{time(data.checked_at)}} · 备份目录可用 {{data.disk_free_gb}} GB
    </p>
    <p v-for="(check,key) in data.checks" :key="key" :class="check.ok?'hint':'danger'">
      {{check.label}} · {{check.ok?'正常':'需要检查'}}
    </p>
    <p class="hint">
      最近成功采集 {{time(data.last_collection_at)}}
    </p>
    <details v-if="data.events?.length">
      <summary>
        故障与恢复记录
      </summary>
      <p v-for="(event,index) in data.events" :key="index" class="hint">
        {{time(event.at)}} · {{event.label}} · {{event.recovered?'已恢复':'需要检查'}}
      </p>
    </details>
  </section>
</template>
