import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import {fileURLToPath} from 'node:url'
import {frontendVersion} from './scripts/version.js'
const version=frontendVersion(fileURLToPath(new URL('.',import.meta.url)))
const releaseMetadata = {
  name: 'gold-etf-release-metadata',
  transformIndexHtml() {
    return [{tag: 'meta', attrs: {name: 'gold-etf-version', content: version}}]
  },
}
export default defineConfig({ plugins: [vue(), releaseMetadata], define:{__FRONTEND_VERSION__:JSON.stringify(version)}, base: '/static/', server: { proxy: { '/api': 'http://127.0.0.1:8000', '/health': 'http://127.0.0.1:8000' } }, build: { chunkSizeWarningLimit: 1100 } })
