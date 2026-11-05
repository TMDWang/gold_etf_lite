import {createHash} from 'node:crypto'
import {readdirSync,readFileSync,existsSync} from 'node:fs'
import {resolve,relative,sep} from 'node:path'

export function fingerprintEntries(entries) {
  const hash=createHash('sha256')
  for (const [name,content] of [...entries].sort((a,b)=>a[0]<b[0]?-1:a[0]>b[0]?1:0)) {
    const nameBytes=Buffer.from(name), length=Buffer.alloc(8)
    length.writeBigUInt64BE(BigInt(nameBytes.length));hash.update(length);hash.update(nameBytes)
    const size=Buffer.alloc(8);size.writeBigUInt64BE(BigInt(content.length));hash.update(size);hash.update(content)
  }
  return hash.digest('hex').slice(0,10)
}

export function frontendVersion(root) {
  const entries=[]
  function walk(path) {
    if(!existsSync(path))return
    for(const item of readdirSync(path,{withFileTypes:true})) {
      const full=resolve(path,item.name)
      if(item.isDirectory())walk(full)
      else if(item.isFile())entries.push([relative(root,full).split(sep).join('/'),readFileSync(full)])
    }
  }
  for(const dir of ['src','public','scripts'])walk(resolve(root,dir))
  for(const name of ['package.json','pnpm-lock.yaml','pnpm-workspace.yaml','vite.config.js']) {
    const path=resolve(root,name);if(existsSync(path))entries.push([name,readFileSync(path)])
  }
  return fingerprintEntries(entries)
}
