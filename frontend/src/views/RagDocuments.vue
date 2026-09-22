<template>
  <div class="rag-page">
    <header class="rag-header">
      <button class="back-button" @click="router.push('/')" aria-label="返回首页">
        <svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg>
      </button>
      <div>
        <h1>RAG 文件管理</h1>
        <p>维护用于检索增强生成的知识库文档</p>
      </div>
      <div class="header-actions">
        <label class="secondary-button upload-button">
          <input type="file" accept=".md,.txt,.pdf,.doc,.docx" @change="handleUpload" />
          <svg viewBox="0 0 24 24"><path d="M12 16V4M7 9l5-5 5 5M5 20h14"/></svg>
          上传文件
        </label>
        <button class="primary-button" @click="openCreate">
          <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>
          新建文档
        </button>
      </div>
    </header>

    <main class="rag-main">
      <section class="overview-row">
        <div class="overview-copy">
          <strong>{{ documents.length }}</strong>
          <span>知识库文档</span>
        </div>
        <div class="overview-copy">
          <strong>{{ totalChunks }}</strong>
          <span>已索引片段</span>
        </div>
        <div class="search-box">
          <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6"/><path d="m16 16 4 4"/></svg>
          <input v-model="keyword" type="search" placeholder="搜索文档名称…" />
        </div>
      </section>

      <div v-if="notice" class="notice" :class="notice.type">{{ notice.text }}</div>

      <section class="document-panel">
        <div class="table-head">
          <span>文档</span>
          <span>格式</span>
          <span>大小</span>
          <span>索引片段</span>
          <span>更新时间</span>
          <span class="actions-title">操作</span>
        </div>

        <div v-if="loading" class="panel-state">
          <span class="spinner"></span>
          正在加载知识库文档…
        </div>

        <div v-else-if="filteredDocuments.length" class="document-list">
          <article v-for="doc in filteredDocuments" :key="doc.id" class="document-row">
            <div class="document-identity">
              <span class="file-icon" :class="fileTone(doc.extension)">
                <svg viewBox="0 0 24 24"><path d="M6.5 3.5h8l3 3v14h-11z"/><path d="M14.5 3.5v4h4M9.5 12h5M9.5 15.5h5"/></svg>
              </span>
              <div>
                <button class="document-title-button" @click="openDocument(doc)">{{ doc.title }}</button>
                <span>{{ doc.name }}</span>
              </div>
            </div>
            <span class="file-type">{{ doc.extension || '—' }}</span>
            <span>{{ formatSize(doc.size) }}</span>
            <span>{{ doc.chunkCount ?? '—' }}</span>
            <span>{{ formatDate(doc.updatedAt) }}</span>
            <div class="row-actions">
              <button title="查看文档切片" aria-label="查看文档切片" @click="openChunks(doc)">
                <svg viewBox="0 0 24 24"><path d="m12 3 8 4-8 4-8-4zM4 12l8 4 8-4M4 17l8 4 8-4"/></svg>
              </button>
              <button class="danger-action" title="删除文档" @click="pendingDelete = doc">
                <svg viewBox="0 0 24 24"><path d="M4 7h16M9 4h6M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg>
              </button>
            </div>
          </article>
        </div>

        <div v-else class="panel-state empty-state">
          <span class="empty-icon">
            <svg viewBox="0 0 24 24"><path d="M6.5 3.5h8l3 3v14h-11z"/><path d="M14.5 3.5v4h4M9 14h6"/></svg>
          </span>
          <strong>{{ keyword ? '没有匹配的文档' : '知识库还没有文档' }}</strong>
          <span>{{ keyword ? '请更换关键词后重试' : '上传文件或新建 Markdown 文档开始构建知识库' }}</span>
        </div>
      </section>
    </main>

    <div v-if="viewer.open" class="modal-backdrop" @click.self="closeViewer">
      <section class="viewer-modal" role="dialog" aria-modal="true" :aria-label="viewer.mode === 'document' ? '查看文档内容' : '查看文档切片'">
        <div class="modal-header viewer-header">
          <div>
            <span class="viewer-label">{{ viewer.mode === 'document' ? '完整文档' : '文档切片' }}</span>
            <h2>{{ viewer.title }}</h2>
            <p>{{ viewer.name }}<template v-if="viewer.mode === 'chunks'"> · 共 {{ viewer.chunks.length }} 个切片</template></p>
          </div>
          <button type="button" class="close-button" @click="closeViewer" aria-label="关闭">×</button>
        </div>

        <div v-if="viewer.loading" class="viewer-loading">
          <span class="spinner"></span>
          正在读取内容…
        </div>

        <div v-else-if="viewer.mode === 'document'" class="document-viewer">
          <MarkdownRenderer
            v-if="viewer.content"
            :content="viewer.content"
            class="readonly-markdown"
          />
          <p v-else class="viewer-empty">该文档暂无可显示的文本内容</p>
        </div>

        <div v-else class="chunks-viewer">
          <article v-for="chunk in viewer.chunks" :key="chunk.id" class="chunk-card">
            <div class="chunk-head">
              <strong>切片 {{ chunk.index + 1 }}</strong>
              <span>{{ chunk.length }} 字符</span>
            </div>
            <MarkdownRenderer
              :content="chunk.content"
              class="readonly-markdown chunk-markdown"
            />
            <div v-if="chunk.source || chunk.section" class="chunk-meta">
              <span v-if="chunk.section">章节：{{ chunk.section }}</span>
              <span v-if="chunk.source">来源：{{ chunk.source }}</span>
            </div>
          </article>
          <div v-if="!viewer.chunks.length" class="viewer-empty">该文档暂无切片</div>
        </div>
      </section>
    </div>

    <div v-if="editor.open" class="modal-backdrop" @click.self="closeEditor">
      <form class="editor-modal" @submit.prevent="saveDocument">
        <div class="modal-header">
          <div>
            <h2>新建文档</h2>
            <p>Markdown 内容保存后将由 RAG 系统重新索引</p>
          </div>
          <button type="button" class="close-button" @click="closeEditor" aria-label="关闭">×</button>
        </div>
        <label>
          <span>文档名称</span>
          <input v-model="editor.name" required placeholder="例如：vision-transformer.md" />
        </label>
        <label>
          <span>文档标题</span>
          <input v-model="editor.title" required placeholder="请输入知识文档标题" />
        </label>
        <label class="content-field">
          <span>Markdown 内容</span>
          <textarea v-model="editor.content" required placeholder="# 文档标题&#10;&#10;在这里编写知识库内容…"></textarea>
        </label>
        <div class="modal-footer">
          <button type="button" class="secondary-button" @click="closeEditor">取消</button>
          <button type="submit" class="primary-button" :disabled="saving">{{ saving ? '保存中…' : '保存文档' }}</button>
        </div>
      </form>
    </div>

    <div v-if="pendingDelete" class="modal-backdrop" @click.self="pendingDelete = null">
      <div class="confirm-modal">
        <span class="warning-icon">!</span>
        <h2>删除这个文档？</h2>
        <p>“{{ pendingDelete.title }}”将从 RAG 知识库中移除，此操作无法撤销。</p>
        <div class="modal-footer">
          <button class="secondary-button" @click="pendingDelete = null">取消</button>
          <button class="delete-button" :disabled="saving" @click="removeDocument">确认删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import MarkdownRenderer from '../components/MarkdownRenderer.vue'
import {
  createRagDocument,
  deleteRagDocument,
  getRagDocument,
  getRagDocumentChunks,
  listRagDocuments,
  uploadRagDocument,
} from '../api'

const router = useRouter()
const documents = ref([])
const isDemoMode = ref(false)
const keyword = ref('')
const loading = ref(true)
const saving = ref(false)
const pendingDelete = ref(null)
const notice = ref(null)
const editor = reactive({ open: false, mode: 'create', originalName: '', name: '', title: '', content: '' })
const viewer = reactive({ open: false, loading: false, mode: 'document', name: '', title: '', content: '', chunks: [] })

const DEMO_DOCUMENTS = [
  {
    id: 'vision-transformer.md',
    name: 'vision-transformer.md',
    title: 'Vision Transformer 原理与实践',
    extension: 'MD',
    size: 28672,
    chunkCount: 42,
    updatedAt: '2026-09-12T14:28:00+08:00',
    content: '# Vision Transformer 原理与实践\n\nVision Transformer 将图像切分为固定大小的图像块，并使用 Transformer 编码器建模全局关系。\n\n## 核心要点\n\n- Patch Embedding\n- 位置编码\n- 多头自注意力',
  },
  {
    id: 'object-detection-guide.pdf',
    name: 'object-detection-guide.pdf',
    title: '目标检测方法选型指南',
    extension: 'PDF',
    size: 2474639,
    chunkCount: 128,
    updatedAt: '2026-09-11T10:16:00+08:00',
    content: '# 目标检测方法选型指南\n\n对 Faster R-CNN、RetinaNet、FCOS、DETR 等主流方法进行比较。',
  },
  {
    id: 'image-segmentation.md',
    name: 'image-segmentation.md',
    title: '图像分割实验手册',
    extension: 'MD',
    size: 45056,
    chunkCount: 64,
    updatedAt: '2026-09-10T17:42:00+08:00',
    content: '# 图像分割实验手册\n\n整理语义分割与实例分割的常用数据集、指标和训练策略。',
  },
  {
    id: 'training-tricks.txt',
    name: 'training-tricks.txt',
    title: '深度学习训练调优经验',
    extension: 'TXT',
    size: 18432,
    chunkCount: 31,
    updatedAt: '2026-09-08T09:30:00+08:00',
    content: '# 深度学习训练调优经验\n\n包含学习率、正则化、数据增强和混合精度训练的实用建议。',
  },
  {
    id: 'cnn-foundations.md',
    name: 'cnn-foundations.md',
    title: '卷积神经网络基础',
    extension: 'MD',
    size: 33792,
    chunkCount: 48,
    updatedAt: '2026-09-05T16:05:00+08:00',
    content: '# 卷积神经网络基础\n\n介绍卷积、池化、感受野、归一化和残差连接。',
  },
  {
    id: 'dataset-notes.docx',
    name: 'dataset-notes.docx',
    title: '常用视觉数据集笔记',
    extension: 'DOCX',
    size: 358400,
    chunkCount: 76,
    updatedAt: '2026-09-02T11:48:00+08:00',
    content: '# 常用视觉数据集笔记\n\nCOCO、ImageNet、Cityscapes 与 ADE20K 的任务和标注特点。',
  },
]

const filteredDocuments = computed(() => {
  const query = keyword.value.trim().toLowerCase()
  if (!query) return documents.value
  return documents.value.filter(doc => `${doc.title} ${doc.name}`.toLowerCase().includes(query))
})

const totalChunks = computed(() => documents.value.reduce((sum, doc) => sum + (Number(doc.chunkCount) || 0), 0))

function normalizeDocument(item) {
  const name = item.name || item.filename || item.file_name || item.id || '未命名文档.md'
  return {
    id: item.id || name,
    name,
    title: item.title || name.replace(/\.[^.]+$/, ''),
    extension: (item.extension || name.split('.').pop() || '').toUpperCase(),
    size: item.size ?? item.file_size ?? 0,
    chunkCount: item.chunk_count ?? item.chunks ?? item.chunkCount ?? 0,
    updatedAt: item.updated_at || item.modified_at || item.updatedAt || '',
    content: item.content || '',
  }
}

async function loadDocuments() {
  loading.value = true
  try {
    const res = await listRagDocuments()
    const data = res?.data?.items || res?.data || res?.items || []
    documents.value = Array.isArray(data) ? data.map(normalizeDocument) : []
    isDemoMode.value = false
    notice.value = null
  } catch (error) {
    documents.value = DEMO_DOCUMENTS.map(item => ({ ...item }))
    isDemoMode.value = true
    showNotice('当前展示的是前端演示数据；RAG 文档接口可用后会自动切换为真实数据', 'demo')
  } finally {
    loading.value = false
  }
}

function openCreate() {
  Object.assign(editor, { open: true, mode: 'create', originalName: '', name: '', title: '', content: '' })
}

async function openDocument(doc) {
  Object.assign(viewer, { open: true, loading: true, mode: 'document', name: doc.name, title: doc.title, content: '', chunks: [] })
  try {
    if (isDemoMode.value) {
      viewer.content = doc.content || ''
      return
    }
    const res = await getRagDocument(doc.name)
    const data = res?.data || res || {}
    viewer.title = data.title || doc.title
    viewer.content = data.content || ''
  } catch (error) {
    closeViewer()
    showNotice(error.response?.data?.msg || '读取完整文档失败', 'error')
  } finally {
    viewer.loading = false
  }
}

async function openChunks(doc) {
  Object.assign(viewer, { open: true, loading: true, mode: 'chunks', name: doc.name, title: doc.title, content: '', chunks: [] })
  try {
    if (isDemoMode.value) {
      viewer.chunks = createDemoChunks(doc)
      return
    }
    const res = await getRagDocumentChunks(doc.name)
    const data = res?.data?.items || res?.data || res?.items || []
    viewer.chunks = Array.isArray(data) ? data.map(normalizeChunk) : []
  } catch (error) {
    closeViewer()
    showNotice(error.response?.data?.msg || '读取文档切片失败', 'error')
  } finally {
    viewer.loading = false
  }
}

function normalizeChunk(item, index) {
  const content = item.content || item.text || item.page_content || ''
  const metadata = item.metadata || {}
  return {
    id: item.id || item.chunk_id || `${viewer.name}-${index}`,
    index: item.index ?? item.chunk_index ?? index,
    content,
    length: item.length ?? content.length,
    source: item.source || metadata.source || '',
    section: item.section || metadata.section || metadata.heading || '',
  }
}

function createDemoChunks(doc) {
  const paragraphs = (doc.content || doc.title).split(/\n\s*\n/).filter(Boolean)
  const count = Math.max(1, Number(doc.chunkCount) || paragraphs.length)
  return Array.from({ length: count }, (_, index) => normalizeChunk({
    id: `${doc.id}-chunk-${index}`,
    index,
    content: paragraphs[index % paragraphs.length] + (count > paragraphs.length ? `\n\n（演示切片 ${index + 1}）` : ''),
    source: doc.name,
    section: index === 0 ? '文档概要' : `知识片段 ${index + 1}`,
  }, index))
}

function closeViewer() {
  viewer.open = false
}

function closeEditor() {
  editor.open = false
}

async function saveDocument() {
  saving.value = true
  try {
    const rawName = editor.name.trim()
    const payload = { name: /\.[a-z0-9]+$/i.test(rawName) ? rawName : `${rawName}.md`, title: editor.title.trim(), content: editor.content }
    if (isDemoMode.value) {
      const demoItem = normalizeDocument({
        ...payload,
        id: payload.name,
        size: new Blob([payload.content]).size,
        chunk_count: Math.max(1, Math.ceil(payload.content.length / 480)),
        updated_at: new Date().toISOString(),
      })
      documents.value.unshift(demoItem)
      closeEditor()
      showNotice('演示文档已创建', 'demo')
      return
    }
    await createRagDocument(payload)
    closeEditor()
    await loadDocuments()
    showNotice('文档已创建并提交索引')
  } catch (error) {
    showNotice(error.response?.data?.msg || '保存文档失败', 'error')
  } finally {
    saving.value = false
  }
}

async function handleUpload(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  saving.value = true
  try {
    if (isDemoMode.value) {
      documents.value.unshift(normalizeDocument({
        id: file.name,
        name: file.name,
        title: file.name.replace(/\.[^.]+$/, ''),
        size: file.size,
        chunk_count: Math.max(1, Math.ceil(file.size / 1200)),
        updated_at: new Date().toISOString(),
        content: `# ${file.name.replace(/\.[^.]+$/, '')}\n\n这是上传文件的前端演示记录。`,
      }))
      showNotice(`“${file.name}”已加入演示列表`, 'demo')
      return
    }
    await uploadRagDocument(file)
    await loadDocuments()
    showNotice(`“${file.name}”已上传并提交索引`)
  } catch (error) {
    showNotice(error.response?.data?.msg || '上传文件失败', 'error')
  } finally {
    saving.value = false
  }
}

async function removeDocument() {
  if (!pendingDelete.value) return
  saving.value = true
  const title = pendingDelete.value.title
  try {
    if (isDemoMode.value) {
      documents.value = documents.value.filter(item => item.id !== pendingDelete.value.id)
      pendingDelete.value = null
      showNotice(`“${title}”已从演示列表删除`, 'demo')
      return
    }
    await deleteRagDocument(pendingDelete.value.name)
    pendingDelete.value = null
    await loadDocuments()
    showNotice(`“${title}”已删除`)
  } catch (error) {
    showNotice(error.response?.data?.msg || '删除文档失败', 'error')
  } finally {
    saving.value = false
  }
}

function showNotice(text, type = 'success') {
  notice.value = { text, type }
}

function formatSize(bytes) {
  const value = Number(bytes)
  if (!value) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function fileTone(extension) {
  return ['MD', 'TXT'].includes(extension) ? 'teal' : extension === 'PDF' ? 'red' : 'blue'
}

onMounted(loadDocuments)
</script>

<style scoped>
.rag-page { min-height: 100vh; color: var(--ink); background: var(--canvas); }
.rag-header {
  display: grid;
  grid-template-columns: 44px minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  min-height: 92px;
  padding: 18px max(28px, calc((100vw - 1180px) / 2));
  background: #fff;
  border-bottom: 1px solid var(--line);
}
.back-button { display: grid; width: 36px; height: 36px; padding: 0; place-items: center; color: #36506f; background: transparent; border: 0; border-radius: 9px; }
.back-button:hover { background: #eef3f8; }
.back-button svg, .header-actions svg { width: 19px; height: 19px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.rag-header h1 { margin: 0 0 5px; font-size: 22px; letter-spacing: -.025em; }
.rag-header p { margin: 0; color: var(--muted); font-size: 13px; }
.header-actions { display: flex; gap: 10px; }
.primary-button, .secondary-button, .delete-button {
  display: inline-flex; min-height: 40px; padding: 0 16px; align-items: center; justify-content: center; gap: 8px;
  border-radius: 9px; font-size: 13px; font-weight: 650; cursor: pointer;
}
.primary-button { color: #fff; background: var(--primary); border: 1px solid var(--primary); }
.primary-button:hover { background: var(--primary-dark); }
.secondary-button { color: #3c506c; background: #fff; border: 1px solid #d6deea; }
.secondary-button:hover { background: #f7f9fc; }
.delete-button { color: #fff; background: var(--danger); border: 1px solid var(--danger); }
.upload-button input { display: none; }
.rag-main { width: min(1180px, calc(100% - 48px)); margin: 0 auto; padding: 34px 0 70px; }
.overview-row { display: flex; align-items: center; gap: 42px; margin-bottom: 22px; }
.overview-copy { display: flex; flex-direction: column; gap: 2px; }
.overview-copy strong { color: #17335d; font-size: 24px; line-height: 1.1; }
.overview-copy span { color: var(--muted); font-size: 12px; }
.search-box { display: flex; width: min(360px, 100%); height: 42px; margin-left: auto; align-items: center; gap: 9px; padding: 0 13px; background: #fff; border: 1px solid #d9e1ec; border-radius: 10px; }
.search-box:focus-within { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(23,105,232,.08); }
.search-box svg { width: 18px; color: #8391a5; fill: none; stroke: currentColor; stroke-width: 1.7; }
.search-box input { width: 100%; color: var(--ink); background: transparent; border: 0; outline: 0; font-size: 13px; }
.notice { margin-bottom: 16px; padding: 11px 14px; color: #17665f; background: #e9f8f5; border: 1px solid #caece7; border-radius: 9px; font-size: 13px; }
.notice.error { color: #a83238; background: #fff1f2; border-color: #ffd4d7; }
.notice.demo { color: #5940a8; background: #f2efff; border-color: #dfd8ff; }
.document-panel { overflow: hidden; background: #fff; border: 1px solid var(--line); border-radius: 14px; box-shadow: var(--shadow-sm); }
.table-head, .document-row { display: grid; grid-template-columns: minmax(260px, 2fr) .55fr .65fr .7fr .9fr 86px; gap: 18px; align-items: center; }
.table-head { min-height: 46px; padding: 0 20px; color: #7d8ba0; background: #f8fafc; border-bottom: 1px solid var(--line); font-size: 11px; font-weight: 650; }
.actions-title { text-align: right; }
.document-row { min-height: 76px; padding: 12px 20px; color: #52627a; border-bottom: 1px solid #edf1f6; font-size: 12px; }
.document-row:last-child { border-bottom: 0; }
.document-row:hover { background: #fbfcfe; }
.document-identity { display: flex; align-items: center; gap: 12px; min-width: 0; }
.document-identity > div { min-width: 0; }
.document-identity span { display: block; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.document-title-button { display: block; max-width: 100%; margin: 0 0 4px; padding: 0; overflow: hidden; color: #1e3455; background: transparent; border: 0; font-size: 13px; font-weight: 700; text-align: left; white-space: nowrap; text-overflow: ellipsis; cursor: pointer; }
.document-title-button:hover { color: var(--primary); text-decoration: underline; text-underline-offset: 3px; }
.document-identity span { color: #8b98aa; font-size: 11px; }
.file-icon { display: grid; width: 40px; height: 40px; flex: 0 0 auto; place-items: center; color: #2466c2; background: #eaf2ff; border-radius: 10px; }
.file-icon.teal { color: #0b817b; background: #e7f7f5; }
.file-icon.red { color: #c14349; background: #fff0f1; }
.file-icon svg, .row-actions svg, .empty-icon svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.file-type { width: fit-content; padding: 4px 7px; color: #51647f; background: #eef2f7; border-radius: 5px; font-size: 10px; font-weight: 700; }
.row-actions { display: flex; justify-content: flex-end; gap: 5px; }
.row-actions button, .close-button { display: grid; width: 32px; height: 32px; padding: 0; place-items: center; color: #60728c; background: transparent; border: 0; border-radius: 8px; }
.row-actions button:hover { color: var(--primary); background: #eaf2ff; }
.row-actions .danger-action:hover { color: var(--danger); background: #fff0f1; }
.panel-state { display: flex; min-height: 280px; align-items: center; justify-content: center; gap: 10px; color: var(--muted); font-size: 13px; }
.spinner { width: 18px; height: 18px; border: 2px solid #dce5f0; border-top-color: var(--primary); border-radius: 50%; animation: spin .8s linear infinite; }
.empty-state { flex-direction: column; gap: 7px; }
.empty-state strong { color: #314662; font-size: 15px; }
.empty-state > span:last-child { color: #909db0; }
.empty-icon { display: grid; width: 52px; height: 52px; margin-bottom: 8px; place-items: center; color: #67809f; background: #eef3f8; border-radius: 14px; }
.modal-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; padding: 20px; place-items: center; background: rgba(17,31,54,.38); backdrop-filter: blur(3px); }
.editor-modal, .viewer-modal, .confirm-modal { width: min(680px, 100%); padding: 26px; background: #fff; border: 1px solid var(--line); border-radius: 16px; box-shadow: 0 26px 70px rgba(16,33,63,.22); }
.editor-modal { display: flex; max-height: calc(100vh - 40px); flex-direction: column; gap: 18px; }
.viewer-modal { display: flex; width: min(820px, 100%); height: min(760px, calc(100vh - 40px)); flex-direction: column; overflow: hidden; }
.modal-header { display: flex; justify-content: space-between; gap: 20px; }
.modal-header h2, .confirm-modal h2 { margin: 0 0 6px; color: #1a3153; font-size: 20px; }
.modal-header p, .confirm-modal p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.7; }
.close-button { color: #718198; font-size: 25px; }
.viewer-header { flex: 0 0 auto; padding-bottom: 18px; border-bottom: 1px solid #e6ebf2; }
.viewer-label { display: block; margin-bottom: 7px; color: var(--primary); font-size: 10px; font-weight: 750; letter-spacing: .14em; }
.viewer-loading { display: flex; flex: 1; align-items: center; justify-content: center; gap: 10px; color: var(--muted); font-size: 13px; }
.document-viewer, .chunks-viewer { flex: 1; min-height: 0; overflow-y: auto; }
.document-viewer { padding: 22px 4px 8px; }
.document-viewer :deep(.markdown-body) { color: #2a3d5a; font-size: 14px; line-height: 1.85; }
.chunk-card :deep(.markdown-body) { color: #2a3d5a; font-size: 13px; line-height: 1.8; }
.document-viewer :deep(.markdown-body > :first-child), .chunk-card :deep(.markdown-body > :first-child) { margin-top: 0; }
.document-viewer :deep(.markdown-body > :last-child), .chunk-card :deep(.markdown-body > :last-child) { margin-bottom: 0; }
.chunks-viewer { display: flex; flex-direction: column; gap: 12px; padding: 18px 4px 6px; }
.chunk-card { padding: 16px 18px; background: #f7f9fc; border: 1px solid #e2e8f1; border-radius: 10px; }
.chunk-head { display: flex; margin-bottom: 12px; align-items: center; justify-content: space-between; gap: 16px; }
.chunk-head strong { color: #1c385f; font-size: 12px; }
.chunk-head span { color: #8694a8; font-size: 10px; }
.chunk-meta { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 12px; padding-top: 10px; color: #8391a5; border-top: 1px solid #e4e9f0; font-size: 10px; }
.viewer-empty { display: grid; min-height: 220px; margin: 0; place-items: center; color: var(--muted); font-size: 13px; text-align: center; }
.editor-modal label { display: flex; flex-direction: column; gap: 7px; color: #3b4f6b; font-size: 12px; font-weight: 650; }
.editor-modal input, .editor-modal textarea { width: 100%; color: var(--ink); background: #fff; border: 1px solid #d7e0eb; border-radius: 9px; outline: 0; font-size: 13px; }
.editor-modal input { height: 42px; padding: 0 12px; }
.editor-modal input:disabled { color: #7d8b9f; background: #f3f6f9; }
.content-field { min-height: 260px; flex: 1; }
.editor-modal textarea { min-height: 240px; flex: 1; padding: 13px; resize: vertical; line-height: 1.7; }
.editor-modal input:focus, .editor-modal textarea:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(23,105,232,.08); }
.modal-footer { display: flex; justify-content: flex-end; gap: 10px; }
.confirm-modal { width: min(420px, 100%); text-align: center; }
.warning-icon { display: grid; width: 44px; height: 44px; margin: 0 auto 16px; place-items: center; color: #b83238; background: #fff0f1; border-radius: 50%; font-size: 20px; font-weight: 800; }
.confirm-modal .modal-footer { margin-top: 24px; justify-content: center; }
button:disabled { cursor: not-allowed; opacity: .58; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 860px) {
  .rag-header { grid-template-columns: 40px minmax(0, 1fr); }
  .header-actions { grid-column: 1 / -1; padding-left: 56px; }
  .overview-row { flex-wrap: wrap; }
  .search-box { width: 100%; margin-left: 0; order: 3; }
  .table-head { display: none; }
  .document-row { grid-template-columns: minmax(0, 1fr) auto; gap: 10px; }
  .document-row > span { display: none; }
}
@media (max-width: 520px) {
  .rag-header { padding: 16px; }
  .rag-header h1 { font-size: 19px; }
  .header-actions { padding-left: 0; }
  .header-actions > * { flex: 1; padding: 0 10px; }
  .rag-main { width: calc(100% - 28px); padding-top: 24px; }
  .overview-row { gap: 28px; }
  .document-row { padding: 12px; }
  .editor-modal { padding: 20px; }
  .viewer-modal { height: calc(100vh - 28px); padding: 20px; }
}
</style>
