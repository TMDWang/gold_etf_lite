export const money = value => value === null || value === undefined || value === '' ? '—' : Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const signed = value => value === null || value === undefined ? '—' : `${Number(value) > 0 ? '+' : ''}${money(value)}`
export function beijingInput(value) {
  return new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value)).replace(' ', 'T')
}
export function backupSummary(backup) {
  if (!backup?.last_success && !backup?.last_failure) return '尚未备份'
  if (backup.ok === false) return `失败：${backup.last_failure || '时间未知'}；${backup.message || '请检查 NAS'}；上次成功 ${backup.last_success || '暂无'}`
  return `最近成功 ${backup.last_success}`
}
export function tradePreview(t) {
  const amount = Number(t.quantity) * Number(t.price)
  const cash = t.side === 'BUY' ? -amount - Number(t.fee) : amount - Number(t.fee)
  return `现金 ${signed(cash)} · 份额 ${t.side === 'BUY' ? '+' : '-'}${t.quantity}`
}
