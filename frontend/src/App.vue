<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch, defineAsyncComponent } from 'vue'
import { showToast, showSuccessToast, showConfirmDialog, closeDialog } from 'vant'
import SectionStatus from './components/SectionStatus.vue'
import ThemePicker from './components/ThemePicker.vue'
import { createSectionLoader, createSessionRequests, resolveEpisodePlan, networkNotice } from './loading'
import { registerShellWorker } from './pwa'
import { createPriceStream } from './price-stream'
import { api as rawApi, post as rawPost } from './api'
import { money, signed, tradePreview, beijingInput, backupSummary, formatRelease } from './display'

const PriceChart=defineAsyncComponent(()=>import('./components/PriceChart.vue'))
const HoldingCostChart=defineAsyncComponent(()=>import('./components/HoldingCostChart.vue'))
const SellBatchPreview=defineAsyncComponent(()=>import('./components/SellBatchPreview.vue'))
const AccountTools=defineAsyncComponent(()=>import('./components/AccountTools.vue'))
const ReminderHistory=defineAsyncComponent(()=>import('./components/ReminderHistory.vue'))
const SetupChecklist=defineAsyncComponent(()=>import('./components/SetupChecklist.vue'))
const EntryFilters=defineAsyncComponent(()=>import('./components/EntryFilters.vue'))
const RuleStatus=defineAsyncComponent(()=>import('./components/RuleStatus.vue'))
const SystemDiagnostics=defineAsyncComponent(()=>import('./components/SystemDiagnostics.vue'))
const frontendVersion=typeof __FRONTEND_VERSION__==='string'?__FRONTEND_VERSION__:'开发模式'
const loading=ref(true), startupError=ref(''), busy=ref(false), me=ref(null), account=ref(null), market=ref({points:[]}), plans=ref([]), episodes=ref([]), entries=ref([]), deliveries=ref([]), updateAvailable=ref(false)
const holdingHistory=ref({points:[]}), historyShown=ref(false)
const marketDays=ref(1), marketHistory=ref(null)
const alertLabels={PRICE:'目标价格',PCT_CLOSE:'相对昨收涨跌幅',PCT_COST:'相对持仓成本涨跌幅',PCT_OPEN:'相对今日首个采样涨跌幅',DRAWDOWN:'自今日已采样高点回撤',MOVE_10M:'近10分钟价格变化'}
const alertUnit=kind=>['PRICE','MOVE_10M'].includes(kind)?' 元':'%'
const alerts=ref([]), publicAlerts=ref([]), publicRules=ref([])
const tab=ref('home'), popup=ref(''), authMode=ref('login'), entryPage=ref(1), entryCount=ref(0), admins=ref([]), system=ref(null), invite=ref(''), authError=ref('')
const credentials=reactive({username:'',password:'',code:''}), init=reactive({budget:'',cash:'',shares:'0',unit_cost:'0'}), settings=reactive({fee_rate:'',fee_minimum:'',fee_extra:'',reminder_minutes:30,reminder_max:3,push_token:''})
const groupSettings=reactive({topic:'',token:'',token_bound:false})
const form=reactive({}), entryKey=ref(''), cashForm=reactive({amount:'',reason:'',category:'DEPOSIT'}), passwords=reactive({old_password:'',new_password:''})
const previewForm=reactive({price:'',quantity:'100',fee:'',mode:'quantity',budget:'',target_profit:''}), previewResult=ref(null)
const entryFilters=reactive({kind:'ALL',start:'',end:''}),entrySummary=ref(null),filterEditing=ref(false),previewNotice=ref('')
const entryQuery=computed(()=>{const query=new URLSearchParams({kind:entryFilters.kind});if(entryFilters.start)query.set('start',entryFilters.start);if(entryFilters.end)query.set('end',entryFilters.end);return query.toString()})
const previewIsSell=computed(()=>popup.value==='sell-preview')
const previewTitle=computed(()=>previewIsSell.value?'卖出预览':'买入预览')
let previewRevision=0
let timer
let streamNeedsMarket=false
let shellWorker,quoteStream,latestPriceEvent=null,bootstrapVersion=0
const requests=createSessionRequests({request:rawApi,submit:rawPost})
const api=(...args)=>requests.request(...args)
const post=(...args)=>requests.submit(...args)
const sectionState=reactive(Object.fromEntries(['account','market','marketHistory','quote','plans','episodes','entries','history','alerts','publicAlerts'].map(k=>[k,{pending:false,error:''}])))
const streamState=ref('stopped')
const networkKeys=computed(()=>networkNotice(sectionState,tab.value==='holdings'?(historyShown.value?['account','entries','history']:['account','entries']):tab.value==='alerts'?['account','alerts','publicAlerts']:tab.value==='plans'?['account','plans']:(marketDays.value>1?['account','market','marketHistory','quote','plans','episodes']:['account','market','quote','plans','episodes'])))
function displayState(key){const state=sectionState[key];return networkKeys.value.includes(key)?{...state,error:''}:state}
function retryNetwork(){for(const key of networkKeys.value)void loader.run(key,{force:true})}
const sections={
  account:{state:sectionState.account,load:opts=>api('/account/',opts),apply:v=>{account.value=v},clear:()=>{account.value=null}},
  market:{state:sectionState.market,load:opts=>api('/market/',opts),apply:applyMarketSnapshot,clear:()=>{market.value={points:[]};latestPriceEvent=null}},
  marketHistory:{state:sectionState.marketHistory,load:opts=>api(`/market/history/?days=${marketDays.value}`,opts),apply:value=>{marketHistory.value=value},clear:()=>{marketHistory.value=null;marketDays.value=1}},
  quote:{state:sectionState.quote,load:opts=>api('/quote/',opts),apply:syncQuote},
  plans:{state:sectionState.plans,load:opts=>api('/plans/',opts),apply:v=>{plans.value=v},clear:()=>{plans.value=[]}},
  episodes:{state:sectionState.episodes,load:opts=>api('/episodes/',opts),apply:v=>{episodes.value=v},clear:()=>{episodes.value=[]}},
  entries:{state:sectionState.entries,load:opts=>api(`/entries/?page=${entryPage.value}&${entryQuery.value}`,opts),apply:v=>{entries.value=v.results;entryCount.value=v.count;entrySummary.value=v.summary||null},clear:()=>{entries.value=[];entryCount.value=0}},
  history:{state:sectionState.history,load:opts=>api('/account/holding-history/',opts),apply:value=>{holdingHistory.value=value},clear:()=>{holdingHistory.value={points:[]};historyShown.value=false}},
  alerts:{state:sectionState.alerts,load:opts=>api('/alerts/',opts),apply:v=>{alerts.value=v},clear:()=>{alerts.value=[]}},
  publicAlerts:{state:sectionState.publicAlerts,load:opts=>api('/public-alerts/',opts),apply:v=>{publicAlerts.value=v},clear:()=>{publicAlerts.value=[]}},
}
const loader=createSectionLoader({sections,onUnauthorized(){requests.invalidate();me.value=null;clearPrivateForms();showToast('登录已过期或账号已停用，请重新登录')}})
function clearPrivateForms(){closeDialog();popup.value='';deliveries.value=[];admins.value=[];publicRules.value=[];Object.assign(groupSettings,{topic:'',token:'',token_bound:false});system.value=null;invite.value='';Object.keys(form).forEach(k=>delete form[k]);Object.assign(settings,{fee_rate:'',fee_minimum:'',fee_extra:'',reminder_minutes:30,reminder_max:3,push_token:'',token_bound:false});Object.assign(init,{budget:'',cash:'',shares:'0',unit_cost:'0'});Object.assign(previewForm,{price:'',quantity:'100',fee:'',mode:'quantity',budget:'',target_profit:''});previewResult.value=null;previewRevision++;cashForm.amount='';cashForm.reason='';cashForm.category='DEPOSIT';entrySummary.value=null;Object.assign(entryFilters,{kind:'ALL',start:'',end:''});filterEditing.value=false;previewNotice.value='';passwords.old_password='';passwords.new_password='';credentials.password='';entryPage.value=1;tab.value='home'}
function resetPrivate(){quoteStream?.stop();requests.invalidate();loader.reset();clearPrivateForms()}
const visibleMarketPoints=computed(()=>{
  if(marketDays.value===1)return market.value.points
  if(marketHistory.value?.days!==marketDays.value)return []
  const merged=new Map(marketHistory.value.points.map(point=>[Date.parse(point.at),point]))
  for(const point of market.value.points)merged.set(Date.parse(point.at),point)
  return [...merged.values()].sort((a,b)=>Date.parse(a.at)-Date.parse(b.at))
})
function chooseMarketDays(days){
  if(days===marketDays.value)return
  marketDays.value=days
  if(days>1)void loader.run('marketHistory',{force:true})
  else loader.dismiss('marketHistory')
}
const effectiveEntries=computed(()=>entries.value.map(entry=>({...entry,original_payload:entry.payload,payload:entry.effective_payload||entry.payload})))
const activePlans=computed(()=>plans.value.filter(p=>p.status==='ACTIVE'))
const price=computed(()=>{const a=account.value?.reference_quote,m=market.value.quote;if(!m)return a?.price;if(!a)return m.price;return Date.parse(m.source_at)>=Date.parse(a.source_at)?m.price:a.price})
const holdingValue=computed(()=>price.value!=null&&account.value?Number(price.value)*Number(account.value.shares):account.value?.market_value)
const holdingFloating=computed(()=>holdingValue.value!=null&&account.value?Number(holdingValue.value)-Number(account.value.cost_basis):null)
const holdingTotal=computed(()=>holdingFloating.value!=null&&account.value?holdingFloating.value+Number(account.value.realized):null)
const holdingInvestment=computed(()=>account.value?.unclassified_count?null:holdingTotal.value==null?null:holdingTotal.value+Number(account.value?.cash_result||0))
const holdingEquity=computed(()=>holdingValue.value==null?null:holdingValue.value+Number(account.value?.cash||0))
const pnlClass=v=>Number(v)>0?'gain':Number(v)<0?'loss':''
const fmtTime=v=>v?new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'暂无'
const initialized=computed(()=>!!account.value?.initialized_at)
const liveEpisodes=computed(()=>episodes.value.filter(e=>['OPEN','UNKNOWN'].includes(e.status)))
function applyMarketSnapshot(value){
  if(value.curve_date && market.value.curve_date && value.curve_date<market.value.curve_date)return
  market.value=value
  if(latestPriceEvent)applyPrice(latestPriceEvent)
}
function syncQuote(value, fromStream=false){
  const previous=market.value
  applyPrice(value)
  if(market.value===previous || value.unavailable)return
  const reconnected=fromStream && streamNeedsMarket
  if(fromStream){
    loader.dismiss('quote')
    streamNeedsMarket=false
  }
  const priceChanged=!!value.quote && previous.quote?.price!==value.quote.price
  const sessionChanged=previous.session_open!==undefined && previous.session_open!==market.value.session_open
  const dateChanged=previous.curve_date && previous.curve_date!==market.value.curve_date
  if(tab.value==='home' && (priceChanged || sessionChanged || reconnected))void loader.run('market',{force:true})
  if(tab.value==='home' && marketDays.value>1 && dateChanged)void loader.run('marketHistory',{force:true})
}
function acceptStreamPrice(value){syncQuote(value,true)}
function applyPrice(value){
  if(!me.value||!value||typeof value!=='object')return
  if(market.value.curve_date&&value.curve_date&&value.curve_date<market.value.curve_date)return
  if(value.status_only){
    const changedDay=market.value.curve_date&&value.curve_date&&market.value.curve_date!==value.curve_date
    market.value={...market.value,...value,points:changedDay?[]:market.value.points}
    if(changedDay)latestPriceEvent=null
    else if(latestPriceEvent)latestPriceEvent={...latestPriceEvent,...value,status_only:false}
    if(changedDay&&tab.value==='home')void loader.run('market',{force:true})
    return
  }
  if(value.unavailable){market.value={...market.value,fresh:false,message:value.message||'行情暂不可用'};return}
  const old=market.value.quote, incoming=value.quote
  if(old&&incoming&&Date.parse(incoming.source_at)<Date.parse(old.source_at))return
  latestPriceEvent=value
  const previousDate=market.value.curve_date, changedDay=previousDate&&value.curve_date&&previousDate!==value.curve_date
  let points=changedDay?[]:[...(market.value.points||[])]
  const point=value.latest_point
  if(point&&(!previousDate||!value.curve_date||previousDate===value.curve_date)){
    const at=Date.parse(point.at),last=points.at(-1),lastAt=last?Date.parse(last.at):null
    if(Number.isFinite(at)){if(lastAt===at)points[points.length-1]=point;else if(lastAt===null||at>lastAt)points.push(point)}
  }
  market.value={...market.value,...value,points}
  if(changedDay&&tab.value==='home')void loader.run('market',{force:true})
}
async function action(fn) { if(busy.value)return;busy.value=true;try{await fn()}catch(e){if(e!=='cancel'&&e!=='close'&&e.code!=='CANCELLED')showToast({message:e.message||'操作未完成，请重试',duration:4000})}finally{busy.value=false} }
function refresh({force=false}={}) {
  if (!me.value) return
  if(force)loader.invalidate()
  const keys=tab.value==='holdings'?(historyShown.value?['account','entries','history']:['account','entries']):tab.value==='alerts'?['account','alerts','publicAlerts']:tab.value==='plans'?['account','plans']:['account','market','plans','episodes']
  if(tab.value==='home' && marketDays.value>1)keys.push('marketHistory')
  const ages={account:15000,market:20000,episodes:20000,plans:60000,entries:60000,alerts:60000,publicAlerts:60000}
  for(const key of keys)void loader.run(key,{force,maxAgeMs:ages[key]})
}
async function bootstrap(){const version=++bootstrapVersion;loading.value=true;startupError.value='';try{const [,user]=await Promise.all([api('/auth/csrf/'),api('/me/')]);if(version!==bootstrapVersion)return;resetPrivate();me.value=user;refresh()}catch(e){if(version!==bootstrapVersion)return;if(![401,403].includes(e.status))startupError.value=e.message;me.value=null}finally{if(version===bootstrapVersion)loading.value=false}}
async function authenticate(){await action(async()=>{authError.value='';await api('/auth/csrf/');await post(`/auth/${authMode.value}/`,credentials);const user=await api('/me/');resetPrivate();me.value=user;refresh()})}
async function initialize(){await action(async()=>{account.value=await post('/account/initialize/',init);refresh({force:true});showSuccessToast('已建立期初账本')})}
function openEpisode(e){const plan=resolveEpisodePlan(e,plans.value);if(!plan){showToast('计划尚未就绪或已变化，请刷新后确认');void loader.run('plans',{force:true});return}openTrade(e.side,plan)}
function openPlan(side,p=null){if(!initialized.value){showToast('请先完成账本初始化');return}Object.keys(form).forEach(k=>delete form[k]);Object.assign(form,p?{...p}:{side,direction:'BELOW',target_price:'',target_profit:'',amount:'',quantity:'',sell_all:false});popup.value='plan'}
function planBody(){return{side:form.side,direction:form.direction,target_price:form.target_price||null,target_profit:form.side==='SELL'&&form.target_profit!==''&&form.target_profit!=null?form.target_profit:null,amount:form.side==='BUY'?form.amount:null,quantity:form.side==='SELL'&&!form.sell_all?form.quantity:null,sell_all:form.side==='SELL'&&form.sell_all}}
async function savePlan(){await action(async()=>{if(price.value&&((form.side==='BUY'&&(form.direction==='BELOW'?Number(price.value)<=Number(form.target_price):Number(price.value)>=Number(form.target_price)))||(form.side==='SELL'&&form.target_price&&Number(price.value)>=Number(form.target_price))))await showConfirmDialog({title:'当前参考价已达到价格条件',message:'保存后会在交易时段按有效行情和账户状态检查，可能很快触发提醒。'});if(form.id)await api(`/plans/${form.id}/`,{method:'PATCH',body:planBody()});else await post('/plans/',planBody());popup.value='';await refresh({force:true});showSuccessToast('计划已保存')})}
async function cancelPlan(p){await action(async()=>{await showConfirmDialog({title:'取消这条计划？',message:'取消后停止监测，账目不受影响。'});await post(`/plans/${p.id}/cancel/`,{});await refresh({force:true})})}
function openTrade(side='BUY',p=null,correction=null){if(!initialized.value){showToast('账户尚未就绪，请先重试加载账户');return}Object.keys(form).forEach(k=>delete form[k]);const payload=correction?.payload;Object.assign(form,{side:payload?.side||side,quantity:payload?.quantity|| (p?.side==='SELL'?(p.sell_all?account.value.shares:p.quantity):100),price:payload?.price||price.value||'',fee:payload?.fee??'',occurred_at:payload?.occurred_at?localInput(payload.occurred_at):localInput(new Date()),plan_id:p?.id,plan_version:p?.version,correction:correction?.id,reason:''});entryKey.value=crypto.randomUUID();popup.value='trade'}
function localInput(v){return beijingInput(v)}
async function estimateFee(){
  await action(async()=>{
    const key=entryKey.value,price=form.price,quantity=form.quantity
    const result=await post('/account/fee-preview/',{price,quantity})
    if(popup.value==='trade'&&entryKey.value===key&&form.price===price&&form.quantity===quantity)form.fee=result.fee
    else showToast('成交输入已变化，请重新估算手续费')
  })
}
async function saveTrade(){
  await action(async()=>{
    const tradeKey=entryKey.value,formSnapshot=JSON.stringify(form)
    const correction=form.correction,reason=form.reason
    function ensureCurrentForm(){
      if(popup.value!=='trade'||entryKey.value!==tradeKey||JSON.stringify(form)!==formSnapshot)throw new Error('表单已变化，请重新查看成交影响后确认')
    }
    const trade={side:form.side,quantity:form.quantity,price:form.price,fee:form.fee,occurred_at:`${form.occurred_at}+08:00`}
    if(form.plan_id){trade.plan_id=form.plan_id;trade.plan_version=form.plan_version}
    const impact=await post('/account/entry-preview/',{...trade,confirmation_key:tradeKey,...(correction?{correction_id:correction,correction_reason:reason}:{})})
    ensureCurrentForm()
    if(impact.already_recorded){popup.value='';await refresh({force:true});showSuccessToast('上次确认已入账');return}
    const warning=impact.backdated?'\n这是补录的较早成交，将按当前记账位置计算。':''
    await showConfirmDialog({title:correction?'确认纠错并重算？':'确认实际成交',message:`${trade.side==='BUY'?'买入':'卖出'} ${trade.quantity} 份 · 成交价 ¥${trade.price} · 手续费 ¥${money(trade.fee)}\n持仓 ${impact.before.shares} → ${impact.after.shares} 份\n每份成本 ${impact.before.unit_cost==null?'—':Number(impact.before.unit_cost).toFixed(4)} → ${impact.after.unit_cost==null?'—':Number(impact.after.unit_cost).toFixed(4)}\n可用现金 ${money(impact.before.cash)} → ${money(impact.after.cash)}${warning}\n请以券商成交记录为准。`})
    ensureCurrentForm()
    trade.ledger_revision=impact.ledger_revision
    if(correction)await post(`/entries/${correction}/correct/`,{reason,replacement:trade},tradeKey)
    else await post('/entries/',trade,tradeKey)
    if(entryKey.value===tradeKey&&JSON.stringify(form)===formSnapshot)popup.value=''
    await refresh({force:true});showSuccessToast('已入账')
  })
}
function openTradePreview(side){
  const sell=side==='SELL'
  if(sell && !account.value?.shares)return
  previewRevision++
  Object.assign(previewForm,{price:price.value||'',quantity:sell?String(Math.min(100,account.value.shares)):'100',fee:'',mode:'quantity',budget:'',target_profit:''})
  previewResult.value=null
  previewNotice.value=''
  popup.value=sell?'sell-preview':'buy-preview'
}
async function calculatePreview(){
  await action(async()=>{
    const revision=previewRevision
    const owner=popup.value
    const body={price:previewForm.price}
    if(!previewIsSell.value && previewForm.mode==='budget')body.budget=previewForm.budget
    else body.quantity=previewForm.quantity
    if(previewForm.fee!=='')body.fee=previewForm.fee
    if(previewIsSell.value && previewForm.target_profit!=='')body.target_profit=previewForm.target_profit
    try {
      const result=await post(`/account/${previewIsSell.value?'sell':'buy'}-preview/`,body)
      if(revision===previewRevision && popup.value===owner)previewResult.value=result
    } catch(e) {
      if(e.message?.includes('可能已保存'))throw new Error('连接中断，预览未完成，请重试')
      throw e
    }
  })
}
function usePreview(){
  if(!previewResult.value || previewResult.value.cash_sufficient===false)return
  const values={quantity:String(previewResult.value.quantity),price:previewForm.price,fee:previewResult.value.fee}
  openTrade(previewIsSell.value?'SELL':'BUY')
  Object.assign(form,values)
}
function toggleHoldingHistory(){
  historyShown.value=!historyShown.value
  if(historyShown.value)void loader.run('history',{force:true})
}
function openCash(){cashForm.amount='';cashForm.reason='';cashForm.category='DEPOSIT';entryKey.value=crypto.randomUUID();popup.value='cash'}
async function saveCash(){await action(async()=>{await post('/cash/',cashForm,entryKey.value);popup.value='';await refresh({force:true});showSuccessToast('资金变动已记录')})}
async function ignore(e){await action(async()=>{await post(`/episodes/${e.id}/ignore/`,{});await refresh({force:true});showToast('本轮提醒已停止，计划继续保留')})}
function openAlert(a=null){Object.keys(form).forEach(k=>delete form[k]);Object.assign(form,a?{...a}:{kind:'PRICE',direction:'BELOW',threshold:'',interval:30,repeat_max:3,label:''});popup.value='alert'}
function alertBody(){return {kind:form.kind,direction:form.kind==='DRAWDOWN'?'ABOVE':form.direction,threshold:form.threshold,interval:form.interval,repeat_max:form.repeat_max,label:form.label||''}}
async function saveAlert(){await action(async()=>{if(form.id)await api(`/alerts/${form.id}/`,{method:'PATCH',body:alertBody()});else await post('/alerts/',alertBody());popup.value='';await loader.run('alerts',{force:true});showSuccessToast('行情提醒已保存')})}
async function toggleAlert(a){await action(async()=>{await api(`/alerts/${a.id}/`,{method:'PATCH',body:{enabled:!a.enabled}});await loader.run('alerts',{force:true})})}
async function deleteAlert(a){await action(async()=>{await showConfirmDialog({title:'删除这条提醒？',message:'删除后将停止监测此规则。'});await api(`/alerts/${a.id}/`,{method:'DELETE'});await loader.run('alerts',{force:true})})}
async function pauseRule(rule,scope){await action(async()=>{await post(`/plans/${rule.id}/pause/`,{scope,minutes:60});await refresh({force:true});showToast(scope==='RESUME'?'已恢复原规则检查':'提醒暂停设置已保存')})}
async function ignoreAlert(a){await action(async()=>{await post(`/alerts/${a.id}/ignore/`,{});await loader.run('alerts',{force:true});showToast('本轮提醒已停止')})}
async function saveGroupSettings(){await action(async()=>{const body={topic:groupSettings.topic};if(groupSettings.token)body.token=groupSettings.token;const result=await api('/admin/group-push/',{method:'PATCH',body});Object.assign(groupSettings,result,{token:''});showSuccessToast('群组配置已保存')})}
function openPublicRule(a=null){Object.keys(form).forEach(k=>delete form[k]);Object.assign(form,a?{...a}:{kind:'PRICE',direction:'BELOW',threshold:'',interval:30,repeat_max:3,label:''});popup.value='public-rule'}
async function savePublicRule(){await action(async()=>{if(form.id)await api(`/admin/public-alerts/${form.id}/`,{method:'PATCH',body:alertBody()});else await post('/admin/public-alerts/',alertBody());publicRules.value=await api('/admin/public-alerts/');popup.value='admin';await loader.run('publicAlerts',{force:true});showSuccessToast('公共提醒已保存')})}
async function deletePublicRule(a){await action(async()=>{await showConfirmDialog({title:'删除公共提醒？',message:'所有用户将停止接收这条公共规则。'});await api(`/admin/public-alerts/${a.id}/`,{method:'DELETE'});publicRules.value=await api('/admin/public-alerts/');await loader.run('publicAlerts',{force:true})})}
async function openSettings(){await action(async()=>{const s=await api('/settings/');Object.assign(settings,s,{push_token:''});deliveries.value=await api('/deliveries/');popup.value='settings'})}
async function saveSettings(){await action(async()=>{const body={...settings};delete body.token_bound;if(!body.push_token)delete body.push_token;for(const k of ['fee_rate','fee_minimum','fee_extra'])if(body[k]==='')body[k]=null;await api('/settings/',{method:'PATCH',body});me.value=await api('/me/');showSuccessToast('设置已保存')})}
async function removeToken(){await action(async()=>{await api('/settings/',{method:'PATCH',body:{push_token:''}});settings.token_bound=false;showToast('已解除绑定')})}
async function testPush(){await action(async()=>{await showConfirmDialog({title:'向自己的微信发送测试？',message:'请先保存密钥；本次将实际调用 PushPlus。'});const r=await post('/settings/test-push/',{});showToast(r.detail);deliveries.value=await api('/deliveries/')})}
async function changePassword(){await action(async()=>{await post('/auth/password/',passwords);passwords.old_password='';passwords.new_password='';showSuccessToast('密码已更新')})}
async function logout(){await action(async()=>{await post('/auth/logout/',{});bootstrapVersion++;resetPrivate();me.value=null})}
async function openAdmin(){await action(async()=>{const [users,sys,rules,group]=await Promise.all([api('/admin/users/'),api('/admin/system/'),api('/admin/public-alerts/'),api('/admin/group-push/')]);admins.value=users;system.value=sys;publicRules.value=rules;Object.assign(groupSettings,group,{token:''});popup.value='admin'})}
async function newInvite(){await action(async()=>{invite.value=(await post('/admin/invites/',{})).code})}
async function toggleUser(u){await action(async()=>{await api(`/admin/users/${u.id}/`,{method:'PATCH',body:{is_active:!u.is_active}});admins.value=await api('/admin/users/')})}
async function budget(){await action(async()=>{Object.keys(form).forEach(k=>delete form[k]);form.budget=account.value.budget;popup.value='budget'})}
async function saveBudget(){await action(async()=>{await api('/account/',{method:'PATCH',body:{budget:form.budget}});popup.value='';await refresh({force:true})})}
function applyEntryFilters(value){Object.assign(entryFilters,value);filterEditing.value=false;entryPage.value=1;void loader.run('entries',{force:true})}
async function changePage(p){entryPage.value=p;await loader.run('entries',{force:true})}
function onVisible(){if(document.visibilityState==='visible'){if(me.value){refresh({force:true});quoteStream?.start()}else if(startupError.value&&!loading.value)void bootstrap();shellWorker?.check()}else quoteStream?.stop()}
function onOnline(){if(me.value){refresh({force:true});quoteStream?.start()}else if(!loading.value)void bootstrap()}
function applyUpdate(){if(!popup.value&&!busy.value)shellWorker?.activate()}
const safeToUpdate=computed(()=>{
  const loginDirty=!me.value&&Object.values(credentials).some(Boolean)
  const setupDirty=!!me.value&&!!account.value&&!initialized.value&&(!!init.budget||!!init.cash||!['','0'].includes(String(init.shares))||!['','0'].includes(String(init.unit_cost)))
  return updateAvailable.value&&!loading.value&&!busy.value&&!popup.value&&!loginDirty&&!setupDirty&&!filterEditing.value
})
watch(safeToUpdate,ready=>{if(ready)applyUpdate()})
watch(()=>[previewForm.price,previewForm.quantity,previewForm.fee,previewForm.mode,previewForm.budget,previewForm.target_profit,account.value?.cash,account.value?.shares,account.value?.cost_basis,account.value?.ledger_revision,settings.fee_rate,settings.fee_minimum,settings.fee_extra],()=>{previewRevision++;if(previewResult.value)previewNotice.value='输入、账户或费用已变化，请重新计算';previewResult.value=null},{flush:'sync'})
watch(tab,()=>refresh({force:true}))
watch(me,user=>{if(!quoteStream)return;if(!user)quoteStream.stop();else if(document.visibilityState==='visible')quoteStream.start()})
onMounted(()=>{shellWorker=registerShellWorker(()=>{updateAvailable.value=true},undefined,undefined,()=>safeToUpdate.value);quoteStream=createPriceStream({onPrice:acceptStreamPrice,onHeartbeat:value=>{if(value.collection)applyPrice({...value,status_only:true})},onState:value=>{streamState.value=value},onFallback:()=>{void loader.run('quote',{force:true})},onOpen:()=>{streamNeedsMarket=true}});void bootstrap();timer=setInterval(()=>{if(document.visibilityState==='visible')shellWorker?.check()},30000);document.addEventListener('visibilitychange',onVisible);window.addEventListener('online',onOnline)})
onBeforeUnmount(()=>{bootstrapVersion++;quoteStream?.stop();loader.reset();shellWorker?.dispose();clearInterval(timer);document.removeEventListener('visibilitychange',onVisible);window.removeEventListener('online',onOnline)})
</script>

<template>
  <main v-if="loading || (!me && startupError)" class="startup-shell">
    <div class="brand"><span class="brand-small">金</span><strong>金笺</strong></div>
    <template v-if="loading"><p class="muted">正在连接你的账本…</p><section class="card"><van-skeleton title :row="4" /></section><section class="card"><van-skeleton title :row="3" /></section></template>
    <section v-else class="card startup-error"><h2>暂时无法连接账本</h2><p class="muted">{{startupError}}</p><p class="hint">页面可以打开，但登录、最新行情和记账需要连接服务器。不会离线提交成交。</p><van-button block round type="primary" @click="bootstrap">重新连接</van-button></section>
  </main>
  <main v-else-if="!me" class="auth-shell">
    <div class="brand-mark">金</div><p class="eyebrow">GOLD · SIMPLE · PERSONAL</p><h1>金笺</h1><p class="auth-intro">一份清楚的黄金账本<br>在你关心的价格，提醒你。</p>
    <section class="card auth-card"><h2>{{authMode==='login'?'欢迎回来':'使用邀请加入'}}</h2><van-form @submit="authenticate">
      <van-field v-if="authMode==='register'" v-model="credentials.code" label="邀请码" placeholder="由管理员提供" required />
      <van-field v-model="credentials.username" label="用户名" autocomplete="username" required :rules="[{required:true,message:'请输入用户名'}]" />
      <van-field v-model="credentials.password" type="password" label="密码" :autocomplete="authMode==='login'?'current-password':'new-password'" required :rules="[{required:true,message:'请输入密码'}]" />
      <p v-if="authMode==='register'" class="hint">密码至少 10 位，避免常用或纯数字密码。</p><p v-if="authError" class="danger">{{authError}}</p>
      <van-button block round type="primary" native-type="submit" :loading="busy">{{authMode==='login'?'登录':'创建我的账号'}}</van-button>
    </van-form><button class="text-button auth-switch" @click="authMode=authMode==='login'?'register':'login'">{{authMode==='login'?'有邀请码？创建账号':'已有账号，返回登录'}}</button></section>
    <p class="footnote">仅关注 518880 · 自己决策，自己成交<br>忘记密码可联系 NAS 维护者协助恢复。</p>
  </main>
  <div v-else class="app-shell">
    <header class="topbar"><div class="brand"><span class="brand-small">金</span><div><strong>金笺</strong><span>黄金 ETF · 518880</span></div></div><button class="avatar" aria-label="个人设置" @click="openSettings">{{me.username.slice(0,1).toUpperCase()}}</button></header>
    <main class="content">
      <div v-if="networkKeys.length" class="section-error" role="status"><span>部分数据暂未更新，请检查网络后重试</span><button class="text-button" @click="retryNetwork">重试</button></div>
      <div v-if="updateAvailable && !popup && !busy" class="update-banner" role="status"><span>有新版页面可用</span><button class="text-button" @click="applyUpdate">更新页面</button></div>
      <section v-if="!account" class="card account-pending"><h2>我的账本</h2><SectionStatus :state="displayState('account')" label="账户" @retry="loader.run('account',{force:true})"/><van-skeleton v-if="sectionState.account.pending" :row="2" /></section>
      <section v-if="account && !initialized" class="card onboarding"><p class="eyebrow">第一步 · 建立自己的起点</p><h1>把现有资金记清楚</h1><p class="muted">只记录此刻的现金和持仓，不补造过去交易。没有持仓可填 0。</p><van-form @submit="initialize">
        <van-field v-model="init.budget" label="计划预算" type="number" placeholder="例如 20000" required /><van-field v-model="init.cash" label="可用现金" type="number" placeholder="实际可用金额" required /><van-field v-model="init.shares" label="现有份额" type="digit" required /><van-field v-model="init.unit_cost" label="每份成本" type="number" required />
        <van-button block round type="primary" native-type="submit" :loading="busy">建立账本</van-button></van-form><p class="hint">预算用于安排计划，不会自动增加可用现金。成本请参考券商记录。</p></section>
      <template v-else>
        <template v-if="tab==='home'">
          <div class="page-heading"><div><p class="eyebrow">照看黄金，也照顾节奏</p><h1>我的黄金</h1></div><span class="status-pill" :class="market.fresh?'online':''"><i></i>{{market.fresh?'行情有效':market.session_open?'行情待更新':'休市 / 非交易时段'}}</span></div>
          <section class="card price-card"><SectionStatus :state="displayState('market')" label="行情" @retry="loader.run('market',{force:true})"/><div class="row"><span class="muted">华安黄金 ETF <small>518880</small></span><span class="tiny">{{market.quote?.source||'暂无来源'}}</span></div><div class="price-row"><strong class="price">{{price?Number(price).toFixed(3):'—'}}<small>元</small></strong><span v-if="market.change_percent!=null" class="change" :class="pnlClass(market.change_percent)">{{signed(market.change_percent)}}%</span></div><p class="tiny">源数据时间 {{fmtTime(market.quote?.source_at)}}</p><p class="tiny">后台最近成功采集 {{fmtTime(market.collection?.last_success_at)}} · {{streamState==='live'?'实时连接正常':streamState==='fallback'?'正在恢复实时连接':'连接准备中'}}</p>
            <details class="market-hours"><summary>交易与休市时间 <span>北京时间</span></summary><div class="market-hours-content"><p><strong>交易日：</strong>通常为周一至周五，周末及交易所公告休市日休市。</p><p><strong>交易时间：</strong>9:15–9:25 开盘集合竞价；9:30–11:30、13:00–15:00 交易。</p><p><strong>午间休市：</strong>11:30–13:00。</p><p><strong>本应用提醒：</strong>交易日的 9:30–11:30、13:00–15:00，且行情有效时检查；开盘集合竞价不监测。日历不保证覆盖临时停牌或临时休市，请以交易所公告为准。</p><a href="https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml" target="_blank" rel="noopener noreferrer">查看上交所交易规则 ↗</a></div></details>
            <div class="chart-caption"><strong>{{marketDays===1?'今日分时':`近 ${marketDays} 天行情`}}</strong><span>北京时间</span></div>
            <div class="row market-range"><div class="holding-preview-actions" aria-label="行情范围">
              <van-button v-for="days in [1,3,7]" :key="days" size="mini" round :type="marketDays===days?'primary':'default'" @click="chooseMarketDays(days)">{{days===1?'今日':`近 ${days} 天`}}</van-button>
            </div><a class="text-button" :href="`/api/market/history.csv?days=${marketDays}`" download>导出行情</a></div>
            <SectionStatus v-if="marketDays>1" :state="displayState('marketHistory')" label="历史行情" @retry="loader.run('marketHistory',{force:true})"/>
            <PriceChart v-if="visibleMarketPoints.length" :points="visibleMarketPoints" :days="marketDays" /><div v-else class="chart-empty"><van-icon name="chart-trending-o" size="30"/><span>所选范围暂无行情</span><small>收到有效行情后显示，不补画缺失区间</small></div><p class="hint curve-note">午间休市已压缩。{{marketDays===1?(market.curve_note||'显示已取得的数据，缺口留空。'):'最多显示最近 7 个自然日内的已采集分钟数据。'}}</p>
            <div v-if="streamState==='fallback' && !networkKeys.length" class="subtle-notice">实时连接暂不可用，正在通过普通请求获取行情并尝试重连。</div><SectionStatus :state="displayState('quote')" label="行情连接" @retry="loader.run('quote',{force:true})"/><div v-if="me.is_app_admin && market.calendar_valid && market.calendar_notice" class="subtle-notice">{{market.calendar_notice}}</div><div v-if="!market.fresh" class="subtle-notice">{{market.message||'行情尚未就绪，到价提醒暂停。记账仍可使用。'}}</div>
          </section>
          <SectionStatus :state="displayState('episodes')" label="提醒" @retry="loader.run('episodes',{force:true})"/><section v-if="liveEpisodes.length" class="alert-stack"><article v-for="e in liveEpisodes" :key="e.id" class="card alert-card"><div class="row"><strong>{{e.side==='BUY'?'买入':'卖出'}}条件已达到</strong><span class="status-pill">{{e.status==='UNKNOWN'?'推送结果未确认':'待处理'}}</span></div><p>{{e.context.reason}} · 参考价 {{e.context.price}}</p><div class="button-row"><van-button size="small" type="primary" round :disabled="!resolveEpisodePlan(e,plans)" @click="openEpisode(e)">确认实际成交</van-button><van-button size="small" plain round @click="ignore(e)">暂不操作</van-button></div></article></section>

          <SetupChecklist :request="api" @settings="openSettings" @alert="openAlert()"/><section class="card next-card"><SectionStatus :state="displayState('plans')" label="计划" @retry="loader.run('plans',{force:true})"/><div class="row"><h2>接下来的一笔</h2><button class="text-button" @click="tab='plans'">管理计划 →</button></div><p v-if="!activePlans.length && !sectionState.plans.pending && !sectionState.plans.error" class="muted">先写下自己关心的价格，剩下交给提醒。</p><div v-for="p in activePlans" :key="p.id" class="mini-plan"><span class="side-badge" :class="p.side==='SELL'?'sell':''">{{p.side==='BUY'?'买':'卖'}}</span><div><strong>{{p.side==='BUY'?(p.direction==='BELOW'?'跌到':'涨到'):'涨到'}} {{p.target_price||'收益目标'}}</strong><p>{{p.side==='BUY'?`含费上限 ¥${money(p.amount)}`:p.sell_all?'卖出全部持仓':`卖出 ${p.quantity} 份`}}</p></div><span class="tiny">{{p.evaluation?.state==='SNOOZED'?'暂时停用':p.evaluation?.state==='CLOSED'?'休市待检查':'监测中'}}</span></div></section>
          <p class="version-info" aria-label="当前版本">前端 {{frontendVersion==='开发模式'?frontendVersion:formatRelease(frontendVersion)}} · 后端 {{formatRelease(market.backend_version)}}<span v-if="sectionState.market.error">（上次获取）</span></p>
        </template>
        <template v-if="tab==='holdings' && initialized"><div class="page-heading"><div><p class="eyebrow">你的黄金账本</p><h1>我的持仓</h1></div><div class="holding-preview-actions"><van-button size="small" round plain @click="openTradePreview('BUY')">买入预览</van-button><van-button size="small" round plain :disabled="!account.shares" @click="openTradePreview('SELL')">卖出预览</van-button></div></div>
          <section class="card account-card"><SectionStatus :state="displayState('account')" label="账户" @retry="loader.run('account',{force:true})"/><div class="row"><h2>持仓概览</h2><span class="tiny">截至当前记录</span></div><div class="holding-main"><div><span class="muted">持有份额</span><strong>{{account.shares.toLocaleString()}}<small>份</small></strong></div><div><span class="muted">每份成本</span><strong>{{account.unit_cost==null?'—':Number(account.unit_cost).toFixed(4)}}<small>元</small></strong></div></div><div class="metrics"><div><span>可用现金</span><strong>¥{{money(account.cash)}}</strong></div><div><span>持仓市值</span><strong>¥{{money(holdingValue)}}</strong></div><div><span>当前浮盈亏</span><strong  :class="pnlClass(holdingFloating)">{{signed(holdingFloating)}}</strong></div><div><span>累计投资净收益</span><strong :class="pnlClass(holdingInvestment)">{{account.unclassified_count?'待核对':signed(holdingInvestment)}}</strong></div><div><span>总资产</span><strong>¥{{money(holdingEquity)}}</strong></div><div><span>期初后净转入</span><strong>¥{{money(account.net_contributions)}}</strong></div></div><p class="hint">浮盈亏未扣未来卖出费用。收益自 {{fmtTime(account.initialized_at)}} 期初录入起算，不包含未录入的历史已卖出收益。行情过期时资产为最后行情估值。</p><p v-if="account.unclassified_count" class="hint">有 {{account.unclassified_count}} 笔历史资金未分类，累计投资收益待核对。交易浮盈亏及卖出净收益仍可查看。</p></section>
          <section class="card">
            <div class="row"><h2>持仓成本走势</h2><button class="text-button" :aria-expanded="historyShown" @click="toggleHoldingHistory">{{historyShown?'收起':'查看'}}</button></div>
            <template v-if="historyShown">
              <SectionStatus :state="displayState('history')" label="持仓走势" @retry="loader.run('history',{force:true})"/>
              <HoldingCostChart v-if="holdingHistory.points.length" :points="holdingHistory.points"/>
              <p v-if="holdingHistory.truncated" class="hint">显示最近 120 个记账时点。</p>
            </template>
          </section>
        </template>
        <template v-if="tab==='plans' && initialized"><SectionStatus :state="displayState('plans')" label="计划" @retry="loader.run('plans',{force:true})"/><SectionStatus :state="displayState('account')" label="账户" @retry="loader.run('account',{force:true})"/><div class="page-heading"><div><p class="eyebrow">把想法写下来</p><h1>购买计划</h1></div></div><section class="card budget-card"><div><span class="muted">计划预算</span><strong>¥{{money(account.budget)}}</strong></div><button class="text-button" @click="budget">修改</button><p class="hint">现金 ¥{{money(account.cash)}} · 当前成本占用 ¥{{money(account.cost_basis)}}<br>预算剩余额度按预算减持仓成本估算，不代表现金。</p></section>
          <section v-for="side in ['BUY','SELL']" :key="side" class="card plan-card"><div class="row"><h2>{{side==='BUY'?'下一笔买入':'下一笔卖出'}}</h2><span class="side-badge" :class="side==='SELL'?'sell':''">{{side==='BUY'?'买':'卖'}}</span></div><template v-if="activePlans.find(p=>p.side===side)"><template v-for="p in activePlans.filter(p=>p.side===side)" :key="p.id"><div class="plan-target"><small>{{side==='BUY'?(p.direction==='BELOW'?'价格跌到或低于':'价格涨到或高于'):'目标价 / 本笔目标净收益率'}}</small><strong>{{p.target_price?`¥${p.target_price}`:'—'}}<span v-if="side==='SELL'&&p.target_profit!=null"> / {{p.target_profit}}%</span></strong></div><p class="muted">{{side==='BUY'?`含费金额上限 ¥${money(p.amount)}`:p.sell_all?'全部持仓':`${p.quantity} 份`}}</p><RuleStatus :evaluation="p.evaluation"/><p v-if="p.evaluation?.quantity" class="tiny">参考 {{p.evaluation.quantity}} 份</p><div class="button-row"><button class="text-button" @click="pauseRule(p,'TODAY')">今日不提醒</button><button class="text-button" @click="pauseRule(p,'LATER')">暂停 1 小时</button><button v-if="p.evaluation?.state==='SNOOZED'" class="text-button" @click="pauseRule(p,'RESUME')">恢复检查</button></div><div class="button-row"><van-button size="small" round type="primary" @click="openTrade(side,p)">已实际成交</van-button><van-button size="small" round plain @click="openPlan(side,p)">编辑</van-button><button class="text-button muted" @click="cancelPlan(p)">取消计划</button></div></template></template><template v-else-if="!sectionState.plans.pending && !sectionState.plans.error"><p class="empty-text">{{side==='BUY'?'安排下一笔，按自己的节奏积累。':'设置你愿意卖出的价格或净收益。'}}</p><van-button round block plain @click="openPlan(side)">＋ {{side==='BUY'?'添加买入计划':'添加卖出计划'}}</van-button></template><p class="hint">{{side==='BUY'?'计划跨天保留；不会自动下单。':'目标价与净收益率任一满足，且预计扣费后不亏损，才提醒。'}}</p></section>
        </template>
        <template v-if="tab==='alerts' && initialized"><div class="page-heading"><div><p class="eyebrow">按自己的关注设置</p><h1>行情提醒</h1></div><button class="text-button" @click="openAlert()">＋ 添加</button></div><SectionStatus :state="displayState('alerts')" label="行情提醒" @retry="loader.run('alerts',{force:true})"/><section class="card"><p class="hint">仅观察 518880 行情，不构成买卖建议，也不会自动交易。交易时段使用有效行情检查；个人通知需在设置绑定自己的 PushPlus；公共群通知需加入对应的 PushPlus 群组。相对持仓成本不包含未来交易费用。</p><van-button round block plain @click="openAlert()">＋ 添加行情提醒</van-button></section><SectionStatus :state="displayState('publicAlerts')" label="公共提醒" @retry="loader.run('publicAlerts',{force:true})"/><section v-if="publicAlerts.length" class="card"><h2>公共行情提醒</h2><p class="hint">管理员统一设置，发送至 PushPlus 群组。加入、退出或关闭群消息请在 PushPlus 操作；公共内容不包含个人持仓。</p><div v-for="a in publicAlerts" :key="a.id" class="entry-row"><strong>{{a.label||'公共行情提醒'}}</strong><p>{{alertLabels[a.kind]}} {{a.direction==='ABOVE'?'达到或高于':'达到或低于'}} {{a.threshold}}{{alertUnit(a.kind)}}</p><p class="hint">每 {{a.interval}} 分钟，单轮最多 {{a.repeat_max}} 次</p><RuleStatus :evaluation="a.evaluation" :unit="alertUnit(a.kind)"/></div></section><ReminderHistory :request="api"/><h2 v-if="alerts.length">我的个人提醒</h2><section v-for="a in alerts" :key="a.id" class="card"><div class="row"><h2>{{a.label||'行情提醒'}}</h2><span class="status-pill">{{a.evaluation?.state==='SNOOZED'?'暂时停用':a.enabled?'监测中':'已暂停'}}</span></div><p>{{alertLabels[a.kind]}} {{a.direction==='ABOVE'?'达到或高于':'达到或低于'}} {{a.threshold}}{{alertUnit(a.kind)}}</p><p class="hint">每 {{a.interval}} 分钟，单轮最多 {{a.repeat_max}} 次<span v-if="a.episode"> · {{a.episode.status==='UNKNOWN'?'推送结果未确认':a.episode.status==='OPEN'?'条件已达到':a.episode.status==='IGNORED'?'本轮已停止':'等待下一轮'}}</span></p><RuleStatus :evaluation="a.evaluation" :unit="alertUnit(a.kind)"/><div v-if="a.enabled" class="button-row"><button class="text-button" @click="pauseRule(a,'TODAY')">今日不提醒</button><button class="text-button" @click="pauseRule(a,'LATER')">暂停 1 小时</button><button v-if="a.evaluation?.state==='SNOOZED'" class="text-button" @click="pauseRule(a,'RESUME')">恢复检查</button></div><div class="button-row"><van-button size="small" round plain @click="openAlert(a)">编辑</van-button><van-button size="small" round plain @click="toggleAlert(a)">{{a.enabled?'暂停':'启用'}}</van-button><van-button v-if="a.episode && ['OPEN','UNKNOWN'].includes(a.episode.status)" size="small" round plain @click="ignoreAlert(a)">停止本轮</van-button><button class="text-button" @click="deleteAlert(a)">删除</button></div></section></template>
        <template v-if="tab==='holdings' && initialized"><SectionStatus :state="displayState('entries')" label="记录" @retry="loader.run('entries',{force:true})"/><SectionStatus :state="displayState('account')" label="账户" @retry="loader.run('account',{force:true})"/><div class="page-heading"><div><p class="eyebrow">每一笔，都有来处</p><h2>交易记录</h2></div><div class="holding-preview-actions"><button class="text-button" @click="openCash">资金变动</button><a class="text-button"  :href="`/api/entries/export.csv?${entryQuery}`" download>导出流水</a></div></div><div class="button-row history-actions"><van-button round type="primary" @click="openTrade('BUY')">记一笔买入</van-button><van-button round plain @click="openTrade('SELL')">记一笔卖出</van-button></div><section class="card"><div class="row"><h2>已记录卖出净收益</h2><strong :class="pnlClass(account.realized)">{{signed(account.realized)}}</strong></div><p class="hint">按记账顺序计算移动平均成本；成交时间是记录信息。补录更早交易请核对顺序。纠错保留原记录并重算。</p></section><AccountTools :request="api" :submit="post"/><EntryFilters :filters="entryFilters" :summary="entrySummary" :busy="sectionState.entries.pending" @apply="applyEntryFilters" @editing="filterEditing=$event"/><section class="card entries"><div v-for="e in effectiveEntries" :key="e.id" class="entry-row"><div class="row"><div class="entry-title"><span class="side-badge" :class="e.payload.side==='SELL'?'sell':''">{{e.kind==='TRADE'?(e.payload.side==='BUY'?'买':'卖'):e.kind==='CASH'?'资':'改'}}</span><strong>{{e.kind==='TRADE'?(e.payload.side==='BUY'?'买入':'卖出')+' 518880':e.kind==='CASH'?'资金变动':'账目纠错'}}</strong></div><strong>{{e.kind==='TRADE'?`${e.payload.quantity} 份`:e.kind==='CASH'?signed(e.payload.amount):`#${e.corrects}`}}</strong></div><p v-if="e.kind==='TRADE'">成交价 ¥{{e.payload.price}} · 手续费 ¥{{money(e.payload.fee)}}</p><p v-if="e.corrected">原记录：{{e.original_payload.side==='BUY'?'买入':'卖出'}} {{e.original_payload.quantity}} 份 · ¥{{e.original_payload.price}} · 手续费 ¥{{money(e.original_payload.fee)}}</p><p v-if="e.reason">{{e.reason}}</p><p v-if="e.kind==='CASH'" class="tiny">{{({DEPOSIT:'转入资金',WITHDRAW:'转出资金',INCOME:'分红收入',EXPENSE:'账户费用',UNCLASSIFIED:'未分类'})[e.payload.category||'UNCLASSIFIED']}}</p><div class="row"><span class="tiny">{{fmtTime(e.payload.occurred_at||e.created_at)}}<template v-if="e.corrected"> · 已有纠错</template></span><button v-if="e.kind==='TRADE'" class="text-button" @click="openTrade(e.payload.side,null,{...e,payload:e.effective_payload||e.payload})">纠错</button><button v-if="e.kind==='CASH'" class="text-button" @click="openCash">以反向流水修正</button></div></div><van-empty v-if="!entries.length && !sectionState.entries.pending && !sectionState.entries.error" description="还没有成交记录" :image-size="70"/><van-pagination v-if="entryCount>20" :model-value="entryPage" :total-items="entryCount" :items-per-page="20" mode="simple" @change="changePage"/></section><section class="card initial-card"><h2>期初快照</h2><p class="muted">现金 ¥{{money(account.initial_cash)}} · {{account.initial_shares}} 份<br>初始持仓成本 ¥{{money(account.initial_cost)}}</p><p class="tiny">{{fmtTime(account.initialized_at)}} 建立，不作为历史成交。</p></section></template>
      </template>
      <footer class="page-footer">按自己的计划，慢慢来。<br><span>仅做提醒与记账，实际交易以券商记录为准。</span></footer>
    </main>
    <van-tabbar v-model="tab" active-color="#936d28" inactive-color="#97968e" safe-area-inset-bottom>
      <van-tabbar-item name="home" :icon="tab==='home'?'wap-home':'wap-home-o'">首页</van-tabbar-item>
      <van-tabbar-item :disabled="!initialized" name="holdings" :icon="tab==='holdings'?'gold-coin':'gold-coin-o'">持仓</van-tabbar-item>
      <van-tabbar-item :disabled="!initialized" name="plans" :icon="tab==='plans'?'todo-list':'todo-list-o'">计划</van-tabbar-item>
      <van-tabbar-item :disabled="!initialized" name="alerts">
        <template #icon="{ active }"><svg class="tab-bell" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a6 6 0 0 0-6 6v3.5c0 .9-.4 1.7-1.1 2.3l-.9.7V17h16v-1.5l-.9-.7c-.7-.6-1.1-1.4-1.1-2.3V9a6 6 0 0 0-6-6Z" :fill="active?'currentColor':'none'" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M10 19a2 2 0 0 0 4 0" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></template>提醒
      </van-tabbar-item>
    </van-tabbar>
  </div>

  <van-popup :show="!!popup" position="bottom" round closeable :close-on-click-overlay="!busy" @update:show="v=>{if(!v&&!busy)popup=''}" class="form-popup" safe-area-inset-bottom>
    <template v-if="popup==='buy-preview' || popup==='sell-preview'">
      <div class="row"><h2>{{previewTitle}}</h2><button v-if="previewIsSell && account.shares>100" class="text-button" type="button" @click="popup='sell-batch-preview'">分批卖出试算</button></div>
      <p class="hint">按输入的价格和份额估算成交结果。默认参考价取最近行情，请自行核对。</p>
      <van-form @submit="calculatePreview">
        <van-field v-model="previewForm.price" label="预计成交价 / 元" type="number" placeholder="最多三位小数" required/>
        <van-field v-if="!previewIsSell" label="试算方式">
          <template #input><van-radio-group v-model="previewForm.mode" direction="horizontal"><van-radio name="quantity">按份额</van-radio><van-radio name="budget">按预算</van-radio></van-radio-group></template>
        </van-field>
        <van-field v-if="!previewIsSell && previewForm.mode==='budget'" v-model="previewForm.budget" label="含费预算 / 元" type="number" required/>
        <van-field v-else v-model="previewForm.quantity" label="预计份额" type="digit" :placeholder="previewIsSell?'整手或全部持仓':'100 的整数倍'" required>
          <template v-if="previewIsSell" #button><button type="button" class="text-button" @click="previewForm.quantity=String(account.shares)">全部份额</button></template>
        </van-field>
        <van-field v-if="previewIsSell" v-model="previewForm.target_profit" label="目标净收益率 / %" type="number" placeholder="可选，填写正数"/>
        <van-field v-model="previewForm.fee" label="预计手续费 / 元" type="number" placeholder="留空按个人设置估算"/>
        <p class="hint">手续费可手动填写，实际费用以券商为准。</p>
        <van-button block round type="primary" native-type="submit" :loading="busy">计算{{previewIsSell?'卖出':'买入'}}后变化</van-button>
      </van-form>
      <p v-if="previewNotice" class="hint" role="status">{{previewNotice}}</p><div v-if="previewResult" class="preview buy-preview-result" aria-live="polite">
        <div class="row"><strong>{{previewIsSell?'预计净到账':'预计总支出'}} ¥{{money(previewIsSell?previewResult.net:previewResult.total)}}</strong><span>手续费 ¥{{money(previewResult.fee)}}{{previewResult.fee_estimated?'（估算）':''}}</span></div>
        <p class="tiny">试算于 {{fmtTime(previewResult.calculated_at)}} · 使用价格 ¥{{previewResult.reference_price}} · 费用来自{{previewResult.fee_source}}</p><p v-if="!previewIsSell">预计买入 {{previewResult.quantity}} 份</p>
        <p v-if="previewIsSell" :class="pnlClass(previewResult.realized)">本笔预计净盈亏 {{signed(previewResult.realized)}} 元<span v-if="previewResult.return_pct!=null"> · {{signed(previewResult.return_pct)}}%</span></p>
        <p v-if="previewIsSell" class="hint">回本价 ¥{{previewResult.breakeven_price??'—'}}<template v-if="previewForm.target_profit!==''"> · 目标价 ¥{{previewResult.target_price??'—'}}</template></p>
        <p v-if="previewResult.cash_sufficient===false" class="danger">当前可用现金不足，无法按这个预览结果入账。</p>
        <table>
          <thead><tr><th>项目</th><th>成交前</th><th>成交后</th></tr></thead>
          <tbody>
            <tr><th>持有份额</th><td>{{previewResult.before.shares}}</td><td>{{previewResult.after.shares}}</td></tr>
            <tr><th>持仓成本</th><td>¥{{money(previewResult.before.cost_basis)}}</td><td>¥{{money(previewResult.after.cost_basis)}}</td></tr>
            <tr><th>每份成本</th><td>{{previewResult.before.unit_cost==null?'—':Number(previewResult.before.unit_cost).toFixed(4)}}</td><td>{{previewResult.after.unit_cost==null?'—':Number(previewResult.after.unit_cost).toFixed(4)}}</td></tr>
            <tr><th>可用现金</th><td>¥{{money(previewResult.before.cash)}}</td><td>¥{{money(previewResult.after.cash)}}</td></tr>
          </tbody>
        </table>
        <van-button v-if="previewResult.cash_sufficient!==false" block round plain @click="usePreview">带入成交表单</van-button>
        <p class="hint">请按券商实际成交核对价格、份额和手续费，再确认入账。</p>
      </div>
    </template>
    <SellBatchPreview v-if="popup==='sell-batch-preview' && account" :account="account" :price="price" :submit="post"/>
    <template v-if="popup==='alert' || popup==='public-rule'"><h2>{{form.id?'编辑':'添加'}}{{popup==='public-rule'?'公共':'个人'}}行情提醒</h2><van-form @submit="popup==='public-rule'?savePublicRule():saveAlert()"><van-field label="提醒类型"><template #input><van-radio-group v-model="form.kind"><template v-for="(label,kind) in alertLabels" :key="kind"><van-radio v-if="kind!=='PCT_COST' || popup!=='public-rule'" :name="kind">{{label}}</van-radio></template></van-radio-group></template></van-field><van-field v-if="form.kind!=='DRAWDOWN'" label="触发条件"><template #input><van-radio-group v-model="form.direction" direction="horizontal"><van-radio name="ABOVE">达到或高于</van-radio><van-radio name="BELOW">达到或低于</van-radio></van-radio-group></template></van-field><van-field v-model="form.threshold" label="目标数值" type="text" inputmode="decimal" :placeholder="form.kind==='PRICE'?'例如 4.500 元':form.kind==='DRAWDOWN'?'例如 3 表示回撤 3%':form.kind==='MOVE_10M'?'例如 -0.05 元':'例如 5 或 -3，单位 %'" required/><p class="hint">涨跌幅上涨填正数，下跌填负数，例如 -3 表示下跌 3%。持仓成本基准需要先记录有效持仓成本。</p><van-field v-model="form.label" label="备注（可选）" maxlength="80"/><van-field v-model="form.interval" label="重复间隔 / 分钟" type="digit" required/><van-field v-model="form.repeat_max" label="每轮最多次数" type="digit" required/><p class="hint">间隔 20–1440 分钟，每轮 1–10 次。条件解除后再次达到才开始新一轮。</p><van-button block round type="primary" native-type="submit" :loading="busy">保存提醒</van-button></van-form></template>
    <template v-if="popup==='plan'"><h2>{{form.id?'编辑':'添加'}}{{form.side==='BUY'?'买入':'卖出'}}计划</h2><van-form @submit="savePlan"><van-field v-if="form.side==='BUY'" label="买入方向"><template #input><van-radio-group v-model="form.direction" direction="horizontal"><van-radio name="BELOW">跌到买</van-radio><van-radio name="ABOVE">涨到买</van-radio></van-radio-group></template></van-field><van-field v-model="form.target_price" label="目标价格" type="number" placeholder="精确到 0.001 元" :required="form.side==='BUY'"/><van-field v-if="form.side==='BUY'" v-model="form.amount" label="含费金额上限" type="number" required/><template v-else><van-field v-model="form.target_profit" label="本笔净收益率" type="number" placeholder="例如 5，表示 5%"><template #right-icon>%</template></van-field><p class="hint">目标价、净收益率至少填一项；都填时任一达标即可，但预计扣费后须不亏损。</p><van-cell title="卖出全部持仓"><template #right-icon><van-switch v-model="form.sell_all" size="22"/></template></van-cell><van-field v-if="!form.sell_all" v-model="form.quantity" label="卖出份额" type="digit" required/></template><van-button block round type="primary" native-type="submit" :loading="busy">保存计划</van-button></van-form></template>
    <template v-if="popup==='trade'"><h2>{{form.correction?'纠正成交记录':'确认实际成交'}}</h2><p class="hint">填写券商实际成交数据。手动录入允许记录实际发生的亏损卖出。</p><van-form @submit="saveTrade"><van-field label="买卖方向"><template #input><van-radio-group v-model="form.side" direction="horizontal" :disabled="!!form.plan_id"><van-radio name="BUY">买入</van-radio><van-radio name="SELL">卖出</van-radio></van-radio-group></template></van-field><van-field v-model="form.price" label="实际价格" type="number" required/><van-field v-model="form.quantity" label="实际份额" type="digit" required/><van-field v-model="form.fee" label="实际手续费" type="number" required placeholder="可填 0，但不可留空"><template #button><button type="button" class="text-button" @click="estimateFee">按设置估算</button></template></van-field><van-field v-model="form.occurred_at" type="datetime-local" label="成交时间" required/><p class="hint">北京时间；更早补录按记账顺序计算，请核对成本。</p><van-field v-if="form.correction" v-model="form.reason" label="纠错原因" required/><div class="preview">{{tradePreview(form)}}</div><van-button block round type="primary" native-type="submit" :loading="busy">{{form.correction?'保留原记录并纠错':'核对无误，确认入账'}}</van-button></van-form></template>
    <template v-if="popup==='cash'"><h2>记录资金变动</h2><p class="hint">转入填正数，取出填负数；修正错误资金流水时写明原流水编号。不会改变投资预算。</p><van-form @submit="saveCash"><van-field label="资金类型"><template #input><select v-model="cashForm.category" class="cash-category"><option value="UNCLASSIFIED">未分类</option><option value="DEPOSIT">转入资金</option><option value="WITHDRAW">转出资金</option><option value="INCOME">分红收入</option><option value="EXPENSE">账户费用</option></select></template></van-field><p class="hint">转入和分红填写正数，转出和费用填写负数。未分类资金会使相关投资收益待核对。</p><van-field v-model="cashForm.amount" label="变动金额" type="text" inputmode="decimal" required/><van-field v-model="cashForm.reason" label="原因" required/><van-button block round type="primary" native-type="submit" :loading="busy">记录变动</van-button></van-form></template>
    <template v-if="popup==='budget'"><h2>调整计划预算</h2><p class="hint">调整预算不会增加或减少可用现金。</p><van-form @submit="saveBudget"><van-field v-model="form.budget" label="计划预算" type="number" required/><van-button block round type="primary" native-type="submit" :loading="busy">保存预算</van-button></van-form></template>
    <template v-if="popup==='settings'"><p class="eyebrow">{{me.username}} · {{me.is_app_admin?'应用管理员':'我的账号'}}</p><h2>个人设置</h2><ThemePicker/><van-form @submit="saveSettings"><h3>券商费用估算</h3><p class="hint">费率用小数表示：万分之 0.5 填 0.00005。请按自己券商的 ETF 收费规则填写，未知时留空，系统暂停相关到价提醒。</p><van-field v-model="settings.fee_rate" label="手续费率" type="number" placeholder="例如 0.00005"/><van-field v-model="settings.fee_minimum" label="最低收费 / 元" type="number" placeholder="无最低收费填 0"/><van-field v-model="settings.fee_extra" label="每笔额外费用" type="number" placeholder="没有请填 0"/><h3>微信提醒</h3><p class="hint">每人使用自己的 PushPlus 密钥并按服务要求实名认证。密钥只写入，不回显。</p><van-field v-model="settings.push_token" label="PushPlus 密钥" type="password" :placeholder="settings.token_bound?'已绑定；留空保持不变':'尚未绑定'" autocomplete="off"/><van-field v-model="settings.reminder_minutes" label="重复间隔 / 分钟" type="digit"/><van-field v-model="settings.reminder_max" label="每轮最多次数" type="digit"/><p class="hint">间隔 20–1440 分钟，每轮 1–10 次。跨天不会清零；暂不操作可停止本轮。</p><van-button block round type="primary" native-type="submit" :loading="busy">保存设置</van-button></van-form><div class="button-row"><van-button size="small" round plain @click="testPush" :loading="busy">向自己发送测试</van-button><button v-if="settings.token_bound" class="text-button" @click="removeToken">解除绑定</button></div><div v-if="deliveries.length" class="delivery-list"><h3>最近推送</h3><p v-for="d in deliveries.slice(0,5)" :key="d.id" class="hint">{{fmtTime(d.created_at)}} · {{d.label}}<br>{{d.detail}}</p></div><h3>修改密码</h3><van-form @submit="changePassword"><van-field v-model="passwords.old_password" type="password" label="当前密码" autocomplete="current-password" required/><van-field v-model="passwords.new_password" type="password" label="新密码" autocomplete="new-password" required/><van-button block round plain native-type="submit" :loading="busy">更新密码</van-button></van-form><van-cell v-if="me.is_app_admin" title="管理邀请码与账号" is-link @click="openAdmin"/><van-button block round plain @click="logout" :loading="busy">退出登录</van-button></template>
    <template v-if="popup==='admin'"><h2>应用管理</h2><p class="hint">此处仅管理加入和启停，不提供他人资金、密钥或代登录功能。</p><van-button round type="primary" @click="newInvite" :loading="busy">生成一次性邀请码</van-button><div v-if="invite" class="invite-box"><strong>{{invite}}</strong><p class="hint">有效期 7 天，仅显示本次，请复制给亲友。</p></div><h3>PushPlus 群通知配置</h3><p class="hint">填入有权向目标 PushPlus 群组发送的令牌和群组编码。令牌加密保存，不回显；群成员在 PushPlus 自行加入或退出。群消息仅含公共行情。</p><van-form @submit="saveGroupSettings"><van-field v-model="groupSettings.topic" label="群组编码" placeholder="PushPlus 群组编码" required/><van-field v-model="groupSettings.token" label="群发令牌" type="password" :placeholder="groupSettings.token_bound?'已设置；留空保持不变':'填写群组发送令牌'" autocomplete="off"/><van-button block round plain native-type="submit" :loading="busy">保存群通知配置</van-button></van-form><h3>公共行情提醒</h3><p class="hint">统一发送到 PushPlus 群组。规则只使用公开行情，不涉及用户持仓。</p><van-button size="small" round plain @click="openPublicRule()">＋ 添加公共提醒</van-button><div v-for="a in publicRules" :key="a.id" class="entry-row"><strong>{{a.label||'公共行情提醒'}}</strong><p class="hint">{{alertLabels[a.kind]}} {{a.direction==='ABOVE'?'达到或高于':'达到或低于'}} {{a.threshold}}{{alertUnit(a.kind)}}</p><div class="button-row"><van-button size="small" round plain @click="openPublicRule(a)">编辑</van-button><button class="text-button" @click="deletePublicRule(a)">删除</button></div></div><h3>账号</h3><van-cell v-for="u in admins" :key="u.id" :title="u.username" :label="u.is_app_admin?'应用管理员':u.is_active?'正常使用':'已停用'"><template #right-icon><van-switch v-if="!u.is_app_admin" :model-value="u.is_active" size="22" @change="toggleUser(u)"/></template></van-cell><SystemDiagnostics :data="system?.diagnostics"/><h3>系统运行</h3><p class="hint">监测进程 {{system?.worker_ok?'正常':'尚未就绪 / 心跳过期'}}<br>行情状态：{{system?.market?.message||'暂无'}}<br>备份状态：{{backupSummary(system?.backup)}}</p><p class="hint">整库备份及密码恢复由 NAS 维护者操作。备份不可通过应用管理下载。</p></template>
  </van-popup>
</template>
