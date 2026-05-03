/** Fired when active workspace / scan repo changes so App can re-read localStorage and refetch. */
export const WORKSPACE_CONTEXT_CHANGED = 'slca:workspace-context-changed'

export function notifyWorkspaceContextChanged(): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent(WORKSPACE_CONTEXT_CHANGED))
}

const LS_WORKSPACES = 'slca.workspaces'
const LS_ACTIVE_WORKSPACE_ID = 'slca.activeWorkspaceId'

/** True when localStorage has an active workspace id that exists in the saved workspace list. */
export function readHasValidActiveWorkspace(): boolean {
  if (typeof window === 'undefined') return false
  try {
    const id = window.localStorage.getItem(LS_ACTIVE_WORKSPACE_ID)?.trim()
    if (!id) return false
    const raw = window.localStorage.getItem(LS_WORKSPACES)
    if (!raw) return false
    const list = JSON.parse(raw) as unknown
    if (!Array.isArray(list) || list.length === 0) return false
    return list.some((w) => w && typeof w === 'object' && String((w as { id?: string }).id || '') === id)
  } catch {
    return false
  }
}
