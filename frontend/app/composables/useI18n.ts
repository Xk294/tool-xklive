import { useState } from '#app'
import vi from '../../locales/vi'
import en from '../../locales/en'

type Lang = 'vi' | 'en'

type NestedRecord = { [key: string]: string | NestedRecord }

const catalogs: Record<Lang, NestedRecord> = { vi, en }

const STORAGE_KEY = 'xk_lang'

function getNestedValue(obj: NestedRecord, path: string): string | undefined {
  const parts = path.split('.')
  let cur: string | NestedRecord | undefined = obj
  for (const part of parts) {
    if (cur == null || typeof cur === 'string') return undefined
    cur = (cur as NestedRecord)[part]
  }
  return typeof cur === 'string' ? cur : undefined
}

function interpolate(template: string, params: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (_, k) => String(params[k] ?? `{${k}}`))
}

export function useI18n() {
  const lang = useState<Lang>('lang', () => {
    if (import.meta.server) return 'vi'
    try {
      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored === 'vi' || stored === 'en') return stored
    } catch {
      // localStorage unavailable
    }
    return 'vi'
  })

  if (typeof document !== 'undefined') {
    document.documentElement.lang = lang.value
  }

  function setLang(next: Lang) {
    lang.value = next
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // ignore
    }
    if (typeof document !== 'undefined') {
      document.documentElement.lang = next
    }
  }

  function t(key: string, params?: Record<string, string | number>): string {
    const catalog = catalogs[lang.value]
    let value = getNestedValue(catalog, key)
    if (value == null) {
      value = getNestedValue(catalogs.en, key)
    }
    if (value == null) return key
    return params ? interpolate(value, params) : value
  }

  return { lang, setLang, t }
}
