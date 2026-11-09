import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {ref,reactive,computed,watch,defineAsyncComponent,nextTick} from 'vue'
import {createSectionLoader,createSessionRequests,resolveEpisodePlan,networkNotice} from '../src/loading.js'
const deferred=()=>{let resolve;const promise=new Promise(a=>{resolve=a});return{promise,resolve}}
const source=(await readFile(new URL('../src/App.vue',import.meta.url),'utf8')).split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm,'')
function app(request,submit=async()=>({})){const deps={ref,reactive,computed,watch,defineAsyncComponent,onMounted(){},onBeforeUnmount(){},createSectionLoader,createSessionRequests,resolveEpisodePlan,networkNotice,registerShellWorker(){},createPriceStream(){},rawApi:request,rawPost:submit,showToast(){},showSuccessToast(){},showConfirmDialog:async()=>{},closeDialog(){}};return new Function('deps',`const {${Object.keys(deps).join(',')}}=deps;${source};return {me,account,market,popup,tab,settings,form,sectionState,loader,initialize,refresh,openSettings,openEpisode,resetPrivate,loading,busy,credentials,init,updateAvailable,buyPreviewForm,buyPreviewResult,openBuyPreview,calculateBuyPreview,applyPrice,acceptStreamPrice,holdingValue,holdingFloating,setWorker(w){shellWorker=w}}`)(deps)}
test('actual initialize flow forces a post-write account reload over pending old snapshot',async()=>{
 const old=deferred();let calls=0
 const state=app(async path=>path==='/account/'?(++calls===1?old.promise:{initialized_at:'now',cash:'900'}):path==='/market/'?{points:[]}:[],async()=>({initialized_at:'now',cash:'900'}))
 state.me.value={id:1};const pending=state.loader.run('account');await state.initialize()
 old.resolve({initialized_at:null,cash:'0'});await pending;await Promise.resolve()
 assert.equal(state.account.value.initialized_at,'now');assert.ok(calls>=2)
})
test('actual late settings flow cannot reopen popup after background session expiry',async()=>{
 const late=deferred()
 const state=app(async path=>path==='/settings/'?late.promise:path==='/account/'?Promise.reject(Object.assign(new Error('expired'),{status:403})):[])
 state.me.value={id:1};const pending=state.openSettings();await state.loader.run('account');late.resolve({fee_rate:'0.1'});await pending
 assert.equal(state.me.value,null);assert.equal(state.popup.value,'');assert.equal(state.settings.fee_rate,'')
})
test('actual episode action cannot open an unlinked manual trade when plans are absent',()=>{
 const state=app(async()=>[]);state.me.value={id:1};state.account.value={initialized_at:'now',shares:100}
 state.openEpisode({plan:7,version:3,side:'BUY'})
 assert.equal(state.popup.value,'');assert.equal(state.form.plan_id,undefined)
})
test('new version waits for active forms and requests, then activates automatically',async()=>{
 let count=0;const s=app(async()=>[]);s.setWorker({activate(){count++}});s.me.value={id:1};s.loading.value=false;s.popup.value='trade';s.updateAvailable.value=true
 await nextTick();assert.equal(count,0)
 s.busy.value=true;s.popup.value='';await nextTick();assert.equal(count,0)
 s.busy.value=false;await nextTick();assert.equal(count,1)
})
test('new version does not interrupt login or first account setup',async()=>{
 let count=0;const s=app(async()=>[]);s.setWorker({activate(){count++}});s.loading.value=false;s.credentials.username='alice';s.updateAvailable.value=true
 await nextTick();assert.equal(count,0)
 s.me.value={id:1};s.account.value={initialized_at:null};s.init.budget='500';await nextTick();assert.equal(count,0)
 s.init.budget='';await nextTick();assert.equal(count,1)
})
test('an old buy preview response is discarded after the inputs change',async()=>{
 const pending=deferred();const s=app(async()=>[],async()=>pending.promise)
 s.me.value={id:1};s.account.value={initialized_at:'now',shares:100,cash:'500',cost_basis:'400'}
 s.openBuyPreview();s.buyPreviewForm.price='4';const task=s.calculateBuyPreview();s.buyPreviewForm.price='5'
 pending.resolve({after:{shares:200}});await task
 assert.equal(s.buyPreviewResult.value,null)
})
test('reset clears any personal buy preview',()=>{
 const s=app(async()=>[]);s.buyPreviewForm.price='4';s.buyPreviewResult.value={after:{cash:'10'}}
 s.resetPrivate();assert.equal(s.buyPreviewForm.price,'');assert.equal(s.buyPreviewResult.value,null)
})
test('holdings refresh does not download unused intraday curve',()=>{
 const paths=[];const s=app(async path=>{paths.push(path);return path.startsWith('/entries/')?{results:[],count:0}:{initialized_at:'now'}})
 s.me.value={id:1};s.tab.value='holdings';s.refresh()
 assert.ok(paths.includes('/account/'));assert.ok(paths.some(x=>x.startsWith('/entries/')));assert.ok(!paths.includes('/market/'))
})
test('post-write refresh fetches only visible page data',()=>{
 const paths=[];const s=app(async path=>{paths.push(path);return path==='/account/'?{initialized_at:'now'}:path==='/market/'?{points:[]}:[]})
 s.me.value={id:1};s.refresh({force:true})
 assert.ok(paths.includes('/account/'));assert.ok(paths.includes('/market/'));assert.ok(!paths.some(x=>x.startsWith('/entries/')));assert.ok(!paths.includes('/public-alerts/'))
})
test('a price event updates the curve and display valuation without mutating the ledger',()=>{
 const s=app(async()=>[]);s.me.value={id:1};s.account.value={initialized_at:'now',shares:100,cash:'500',cost_basis:'400',realized:'3',reference_quote:{price:'4',source_at:'2026-11-05T02:00:00Z'}}
 s.market.value={curve_date:'2026-11-05',points:[{at:'2026-11-05T02:00:00Z',price:'4'}]}
 s.applyPrice({quote:{price:'4.5',source_at:'2026-11-05T02:01:00Z'},fresh:true,curve_date:'2026-11-05',latest_point:{at:'2026-11-05T02:01:00Z',price:'4.5'}})
 assert.equal(s.market.value.points.length,2);assert.equal(s.holdingValue.value,450);assert.equal(s.holdingFloating.value,50)
 assert.equal(s.account.value.cash,'500');assert.equal(s.account.value.cost_basis,'400')
})
test('a delayed event from an earlier trading day cannot overwrite a newer chart',()=>{
 const s=app(async()=>[]);s.me.value={id:1}
 s.market.value={curve_date:'2026-11-06',quote:{price:'4',source_at:'2026-11-05T07:00:00Z'},points:[]}
 s.applyPrice({curve_date:'2026-11-05',quote:{price:'4',source_at:'2026-11-05T07:00:00Z'},latest_point:{at:'2026-11-05T07:00:00Z',price:'4'}})
 assert.equal(s.market.value.curve_date,'2026-11-06');assert.deepEqual(s.market.value.points,[])
})
test('a status-only event updates availability without changing the displayed price',()=>{
 const s=app(async()=>({}));s.me.value={id:1}
 s.market.value={quote:{price:'4.000',source_at:'2026-11-05T02:00:00Z'},fresh:true,session_open:true,curve_date:'2026-11-05',points:[]}
 s.applyPrice({status_only:true,fresh:false,session_open:false,curve_date:'2026-11-05',message:'休市'})
 assert.equal(s.market.value.quote.price,'4.000');assert.equal(s.market.value.fresh,false);assert.equal(s.market.value.message,'休市')
})


test('a recovered price stream replaces the old fallback failure but preserves account errors',async()=>{
 let rejectQuote
 const quote=new Promise((_,reject)=>{rejectQuote=reject})
 const s=app(async path=>path==='/quote/'?quote:{points:[]})
 s.me.value={id:1}
 s.sectionState.account.error='账户读取失败'
 const fallback=s.loader.run('quote')
 s.acceptStreamPrice({quote:{price:'4.500',source_at:'2026-11-05T02:00:00Z'},curve_date:'2026-11-05'})
 rejectQuote(new Error('旧连接失败'))
 await fallback
 assert.equal(s.sectionState.quote.error,'')
 assert.equal(s.sectionState.quote.pending,false)
 assert.equal(s.sectionState.account.error,'账户读取失败')
})

test('a changed price reconciles the real same-price points missed by the stream',async()=>{
 const at=minute=>`2026-11-05T02:0${minute}:00Z`
 const points=[{at:at(0),price:'4.500'},{at:at(1),price:'4.500'},{at:at(2),price:'4.501'}]
 const snapshot={curve_date:'2026-11-05',points,quote:{price:'4.501',source_at:at(2)}}
 const s=app(async()=>snapshot)
 s.me.value={id:1}
 s.market.value={curve_date:'2026-11-05',points:points.slice(0,1),quote:{price:'4.500',source_at:at(0)}}
 s.acceptStreamPrice({...snapshot,points:undefined,latest_point:points[2]})
 await Promise.resolve()
 await Promise.resolve()
 assert.deepEqual(s.market.value.points,points)
})
