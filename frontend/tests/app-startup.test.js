import {test} from 'node:test'
import assert from 'node:assert/strict'
import {readFile} from 'node:fs/promises'
import {ref,reactive,computed,watch,defineAsyncComponent} from 'vue'
import {createSectionLoader,createSessionRequests,resolveEpisodePlan} from '../src/loading.js'
const deferred=()=>{let resolve;const promise=new Promise(a=>{resolve=a});return{promise,resolve}}
const source=(await readFile(new URL('../src/App.vue',import.meta.url),'utf8')).split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm,'')
function app(request,submit=async()=>({})){const deps={ref,reactive,computed,watch,defineAsyncComponent,onMounted(){},onBeforeUnmount(){},createSectionLoader,createSessionRequests,resolveEpisodePlan,registerShellWorker(){},rawApi:request,rawPost:submit,showToast(){},showSuccessToast(){},showConfirmDialog:async()=>{},closeDialog(){}};return new Function('deps',`const {${Object.keys(deps).join(',')}}=deps;${source};return {me,account,popup,settings,form,sectionState,loader,initialize,refresh,openSettings,openEpisode,resetPrivate}`)(deps)}
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
