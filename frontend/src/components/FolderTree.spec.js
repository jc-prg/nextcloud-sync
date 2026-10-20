import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

vi.mock('@/api/browse', () => ({ browseApi: { list: vi.fn() } }))

const { browseApi } = await import('@/api/browse')
const { default: FolderTree } = await import('@/components/FolderTree.vue')

const dir = (path) => ({ name: path.replace(/\/$/, '').split('/').pop(), path, is_dir: true })
const file = (path) => ({ name: path.split('/').pop(), path, is_dir: false })

// Server tree: folder path → entries
const TREE = {
  '/': [dir('/A/'), file('/top.txt'), dir('/B/')],
  '/A/': [dir('/A/A1/'), dir('/A/A2/'), file('/A/x.txt')],
  '/A/A1/': [dir('/A/A1/deep/')],
  '/B/': [],
}

beforeEach(() => {
  vi.clearAllMocks()
  browseApi.list.mockImplementation(async (_accountId, path) => ({ path, entries: TREE[path] }))
})

async function mountTree(props = {}) {
  const wrapper = mount(FolderTree, { props: { accountId: 1, modelValue: null, ...props } })
  await flushPromises()
  return wrapper
}

const names = (w) => w.findAll('.folder-name').map((n) => n.text())
const node = (w, name) => w.findAll('.tree-node').find((n) => n.find('.folder-name').text() === name)

async function toggle(w, name) {
  await node(w, name).find('.expand-btn').trigger('click')
  await flushPromises()
}

describe('FolderTree', () => {
  it('shows only the folders of the root', async () => {
    const w = await mountTree()
    expect(browseApi.list).toHaveBeenCalledWith(1, '/')
    expect(names(w)).toEqual(['A', 'B'])
  })

  it('inserts children right below an expanded folder, indented one level', async () => {
    const w = await mountTree()
    await toggle(w, 'A')
    expect(browseApi.list).toHaveBeenLastCalledWith(1, '/A/')
    expect(names(w)).toEqual(['A', 'A1', 'A2', 'B'])
    expect(node(w, 'A').attributes('style')).toContain('padding-left: 8px')
    expect(node(w, 'A1').attributes('style')).toContain('padding-left: 24px')
    expect(node(w, 'A').find('.expand-btn').attributes('aria-label')).toBe('Collapse')
  })

  it('collapsing removes all descendants, including expanded subfolders', async () => {
    const w = await mountTree()
    await toggle(w, 'A')
    await toggle(w, 'A1')
    expect(names(w)).toEqual(['A', 'A1', 'deep', 'A2', 'B'])

    await toggle(w, 'A')
    expect(names(w)).toEqual(['A', 'B'])
  })

  it('refresh reloads the children without duplicating them', async () => {
    const w = await mountTree()
    await toggle(w, 'A')
    TREE['/A/'] = [dir('/A/A1/'), dir('/A/A2/'), dir('/A/A3/')]
    await node(w, 'A').find('.refresh-btn').trigger('click')
    await flushPromises()
    expect(names(w)).toEqual(['A', 'A1', 'A2', 'A3', 'B'])
    TREE['/A/'] = [dir('/A/A1/'), dir('/A/A2/'), file('/A/x.txt')]
  })

  it('selecting a folder emits its path and highlights the selected one', async () => {
    const w = await mountTree({ modelValue: '/B/' })
    await node(w, 'A').find('.folder-btn').trigger('click')
    expect(w.emitted('update:modelValue')).toEqual([['/A/']])
    expect(node(w, 'B').classes()).toContain('selected')
    expect(node(w, 'A').classes()).not.toContain('selected')
  })

  it('shows a root error with a working retry', async () => {
    browseApi.list.mockRejectedValueOnce({ response: { data: { detail: 'WebDAV error: boom' } } })
    const w = await mountTree()
    expect(w.find('.tree-error').text()).toContain('WebDAV error: boom')

    await w.find('.tree-error button').trigger('click')
    await flushPromises()
    expect(names(w)).toEqual(['A', 'B'])
  })

  it('shows an error on a folder that fails to expand', async () => {
    const w = await mountTree()
    browseApi.list.mockRejectedValueOnce(new Error('timeout'))
    await toggle(w, 'A')
    expect(node(w, 'A').find('.node-error').text()).toContain('timeout')
    expect(names(w)).toEqual(['A', 'B'])
  })

  it('says so when there are no folders', async () => {
    browseApi.list.mockResolvedValueOnce({ path: '/', entries: [file('/only.txt')] })
    const w = await mountTree()
    expect(w.text()).toContain('No folders found')
  })

  it('reloads when the account changes', async () => {
    const w = await mountTree()
    await toggle(w, 'A')
    await w.setProps({ accountId: 2 })
    await flushPromises()
    expect(browseApi.list).toHaveBeenLastCalledWith(2, '/')
    expect(names(w)).toEqual(['A', 'B'])
  })
})
