// Helpers for a device's simulated folder tree: a flat list of
// { path, account_id, account_path } entries with absolute paths ("/Documents/Work").

export const segments = (p) => (p || '').split('/').filter(Boolean)
export const normPath = (p) => '/' + segments(p).join('/')
export const depth = (p) => segments(p).length - 1
export const baseName = (p) => segments(p).at(-1) ?? ''
export const parentPath = (p) => normPath(segments(p).slice(0, -1).join('/'))
export const isWithin = (p, root) => p === root || p.startsWith(root + '/')

// Parents directly before their children, siblings alphabetically
export function sortFolders(folders) {
  const key = (f) => segments(f.path).map((s) => s.toLowerCase())
  return [...folders].sort((a, b) => {
    const ka = key(a), kb = key(b)
    for (let i = 0; i < Math.min(ka.length, kb.length); i++) {
      if (ka[i] !== kb[i]) return ka[i] < kb[i] ? -1 : 1
    }
    return ka.length - kb.length
  })
}

export function validName(name) {
  const n = (name || '').trim()
  return n !== '' && n !== '.' && n !== '..' && !n.includes('/')
}

// Adds `name` below `parent` ("/" for top level); returns null if it is invalid or exists
export function addFolder(folders, parent, name) {
  if (!validName(name)) return null
  const path = normPath(`${parent}/${name.trim()}`)
  if (folders.some((f) => f.path === path)) return null
  return sortFolders([...folders, { path, account_id: null, account_path: null }])
}

// Removes the folder and everything below it
export function removeFolder(folders, path) {
  return folders.filter((f) => !isWithin(f.path, path))
}

// Renames the folder (and moves its descendants along); returns null if invalid or taken
export function renameFolder(folders, path, name) {
  if (!validName(name)) return null
  const target = normPath(`${parentPath(path)}/${name.trim()}`)
  if (target === path) return folders
  if (folders.some((f) => f.path === target)) return null
  return sortFolders(
    folders.map((f) => (isWithin(f.path, path) ? { ...f, path: target + f.path.slice(path.length) } : f)),
  )
}
