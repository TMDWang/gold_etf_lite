const key = 'gold-etf-theme'
const choices = ['system','light','dark']
const media = typeof globalThis.matchMedia === 'function' ? globalThis.matchMedia('(prefers-color-scheme: dark)') : null

export function getTheme() {
  try {
    const value = globalThis.localStorage.getItem(key)
    return choices.includes(value) ? value : 'light'
  } catch {
    return 'light'
  }
}

let selected = getTheme()
function apply() {
  const dark = selected === 'dark' || (selected === 'system' && media?.matches)
  const root = document.documentElement
  root.dataset.theme = dark ? 'dark' : 'light'
  root.classList.toggle('van-theme-dark', !!dark)
}

export function setTheme(value) {
  if (!choices.includes(value)) return
  selected = value
  try { globalThis.localStorage.setItem(key, value) } catch {}
  apply()
}

export function initializeTheme() {
  apply()
  media?.addEventListener?.('change', apply)
}
