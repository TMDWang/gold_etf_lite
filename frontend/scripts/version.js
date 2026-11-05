import {readFileSync} from 'node:fs'
import {resolve} from 'node:path'
import {isSemver} from '../src/semver.js'

export function packageVersion(metadata) {
  const version=metadata?.version
  if(!isSemver(version))throw new Error('前端版本必须符合语义化版本规范')
  return version
}

export function frontendVersion(root) {
  return packageVersion(JSON.parse(readFileSync(resolve(root,'package.json'),'utf8')))
}
