import {generateSW} from 'workbox-build'
import {readFile} from 'node:fs/promises'
import {createHash} from 'node:crypto'
import {shellCacheConfig} from './cache-config.js'
const revision=createHash('sha256').update(await readFile('dist/index.html')).digest('hex')
const result=await generateSW(shellCacheConfig('dist',revision))
if(result.warnings.length)throw new Error(result.warnings.join('\n'))
console.log(`Page shell cache built: ${result.count} resources; personal API responses excluded.`)
