import { createContext, useCallback, useContext, useMemo, useState } from 'react'

export type ToastKind = 'success' | 'error' | 'info'

export interface ToastItem {
  id: string
  kind: ToastKind
  title: string
  message?: string
}

interface ToastContextValue {
  push: (t: Omit<ToastItem, 'id'>) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])

  const push = useCallback((t: Omit<ToastItem, 'id'>) => {
    const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`
    const item: ToastItem = { id, ...t }
    setItems((prev) => [item, ...prev].slice(0, 5))
    window.setTimeout(() => {
      setItems((prev) => prev.filter((x) => x.id !== id))
    }, 3200)
  }, [])

  const value = useMemo(() => ({ push }), [push])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed right-4 top-4 z-110 flex w-[min(420px,calc(100vw-2rem))] flex-col gap-2">
        {items.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto rounded-xl border px-4 py-3 shadow-xl shadow-black/25 backdrop-blur ${
              t.kind === 'success'
                ? 'border-emerald-500/25 bg-emerald-500/12 text-emerald-50'
                : t.kind === 'error'
                ? 'border-rose-500/25 bg-rose-500/12 text-rose-50'
                : 'border-(--border) bg-(--panel) text-(--text) shadow-(color:--shadow)'
            }`}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">{t.title}</p>
                {t.message && <p className="mt-1 text-xs opacity-85">{t.message}</p>}
              </div>
              <span className="text-lg leading-none opacity-80">
                {t.kind === 'success' ? '✓' : t.kind === 'error' ? '⚠' : 'ⓘ'}
              </span>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

