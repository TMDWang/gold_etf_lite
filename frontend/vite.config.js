import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import {fileURLToPath} from 'node:url'
import {frontendVersion} from './scripts/version.js'
const version=frontendVersion(fileURLToPath(new URL('.',import.meta.url)))
export default defineConfig({ plugins: [vue()], define:{__FRONTEND_VERSION__:JSON.stringify(version)}, base: '/static/', server: { proxy: { '/api': 'http://127.0.0.1:8000', '/health': 'http://127.0.0.1:8000' } }, build: { chunkSizeWarningLimit: 1100 } })
