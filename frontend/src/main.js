import { createApp } from 'vue'
import Vant from 'vant'
import 'vant/lib/index.css'
import './style.css'
import App from './App.vue'
import { initializeTheme } from './theme'
initializeTheme()
createApp(App).use(Vant).mount('#app')
