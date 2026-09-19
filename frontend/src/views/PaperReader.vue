<template>
  <div class="paper-reader-container">
    <header class="app-brand-bar">
      <div class="brand-lockup">
        <strong class="brand-mark">AI</strong>
        <span class="brand-name">AI 科研问答系统</span>
      </div>
      <div class="profile-summary">
        <span class="profile-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3"/><path d="M5.5 19c.8-3.3 3-5 6.5-5s5.7 1.7 6.5 5"/></svg>
        </span>
        <span>{{ currentNickname }}</span>
        <svg class="profile-chevron" viewBox="0 0 24 24" aria-hidden="true"><path d="m8 10 4 4 4-4"/></svg>
      </div>
    </header>

    <div class="conversation-bar">
      <button class="back-button" @click="goBack" aria-label="返回对话记录">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>
      </button>
      <h1 class="title">论文精读助手</h1>
      <div class="conversation-actions" aria-label="会话操作">
        <span class="toolbar-action"><svg viewBox="0 0 24 24"><path d="m4 20 4.2-1L19 8.2 15.8 5 5 15.8zM14.5 6.3l3.2 3.2"/></svg>重命名</span>
        <span class="toolbar-action"><svg viewBox="0 0 24 24"><path d="M4 7h16M9 4h6M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg>删除</span>
        <span class="more-action" aria-hidden="true">•••</span>
      </div>
    </div>
    
    <div class="content-wrapper" :class="{ 'document-open': activeDocument }">
      <div class="chat-area">
        <ChatRoom 
          :messages="messages" 
          :connection-status="connectionStatus"
          ai-type="paper"
          :enable-pdf-upload="true"
          :compact="Boolean(activeDocument)"
          @send-message="sendMessage"
          @open-document="openDocument"
        />
      </div>
      <aside v-if="activeDocument" class="document-panel" aria-label="PDF 全文预览">
        <header class="document-panel-header">
          <div class="document-heading">
            <span class="document-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24"><path d="M7 3h7l4 4v14H7z"/><path d="M14 3v5h5"/><path d="M9.5 13h5M9.5 16.5h5"/></svg>
            </span>
            <div>
              <strong>{{ activeDocument.name }}</strong>
              <span>PDF 全文</span>
            </div>
          </div>
          <button type="button" class="close-document" aria-label="关闭文档" title="关闭文档" @click="closeDocument">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18"/></svg>
          </button>
        </header>
        <iframe class="document-frame" :src="activeDocument.url" :title="`${activeDocument.name} 全文`"></iframe>
      </aside>
    </div>
    
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useHead } from '@vueuse/head'
import ChatRoom from '../components/ChatRoom.vue'
import { chatWithPaperPdf, chatWithPaperReader, getSessionMessages } from '../api'

// 设置页面标题和元数据
useHead({
  title: '论文精读助手 - AI 科研问答系统',
  meta: [
    {
      name: 'description',
      content: '论文精读助手是AI 科研问答系统的论文阅读助手，帮你精读计算机视觉与深度学习论文，梳理方法、实验与结论'
    },
    {
      name: 'keywords',
      content: '论文精读,论文阅读,计算机视觉论文,深度学习论文,文献阅读助手,AI科研助手,科研问答'
    }
  ]
})

const router = useRouter()
const route = useRoute()
const messages = ref([])
const sessionId = ref(route.params.sessionId || "")
const sidebarVisible = ref(true)
const connectionStatus = ref('disconnected')
const activeDocument = ref(null)
const documentUrls = new Set()
const currentNickname = computed(() => {
  try {
    return JSON.parse(localStorage.getItem('user') || '{}').nickname || '研究者'
  } catch {
    return '研究者'
  }
})
let eventSource = null

// 加载历史会话消息
async function loadSessionMessages(sid) {
  clearDocumentUrls()
  messages.value = []
  if (sid) {
    try {
      const res = await getSessionMessages(sid)
      if (res.code === 0 && res.data) {
        for (const m of res.data) {
          messages.value.push({
            content: m.content,
            isUser: m.role === 'user',
            time: new Date(m.created_at || Date.now()).getTime(),
            type: m.role === 'user' ? '' : 'ai-final'
          })
        }
      }
    } catch (e) { /* ignore */ }
  }
}

// 添加消息到列表
const addMessage = (content, isUser, extra = {}) => {
  messages.value.push({
    content,
    isUser,
    time: new Date().getTime(),
    ...extra
  })
}

const openDocument = (document) => {
  activeDocument.value = document
}

const closeDocument = () => {
  activeDocument.value = null
}

const clearDocumentUrls = () => {
  activeDocument.value = null
  documentUrls.forEach(url => URL.revokeObjectURL(url))
  documentUrls.clear()
}

// 发送消息
const sendMessage = (message, pdfAttachment = null) => {
  let attachment = null
  if (pdfAttachment) {
    const url = URL.createObjectURL(pdfAttachment.file)
    documentUrls.add(url)
    attachment = { name: pdfAttachment.name, size: pdfAttachment.size, url }
  }
  addMessage(message, true, attachment ? { attachment } : {})
  
  // 连接SSE
  if (eventSource) {
    eventSource.close()
  }
  
  // 创建一个空的AI回复消息
  const aiMessageIndex = messages.value.length
  addMessage('', false)
  
  connectionStatus.value = 'connecting'
  eventSource = pdfAttachment
    ? chatWithPaperPdf(pdfAttachment.file, message, sessionId.value)
    : chatWithPaperReader(message, sessionId.value)
  
  // 监听SSE消息（Chain 模式：直接推送原始文本分片）
  eventSource.onmessage = (event) => {
    const data = event.data

    if (data === '[THINKING]' || data.startsWith('[THINK]') || data.startsWith('[STEP]')) {
      return
    }

    // 错误消息：高亮红色气泡
    if (data.startsWith('[ERROR]')) {
      if (aiMessageIndex < messages.value.length) {
        messages.value[aiMessageIndex].type = 'ai-error'
        messages.value[aiMessageIndex].content += data.slice(7).trim()
      }
      connectionStatus.value = 'disconnected'
      eventSource.close()
      return
    }

    if (data && data !== '[DONE]') {
      // 更新最新的AI消息内容，而不是创建新消息
      if (aiMessageIndex < messages.value.length) {
        messages.value[aiMessageIndex].content += data
      }
    }
    
    if (data === '[DONE]') {
      connectionStatus.value = 'disconnected'
      eventSource.close()
    }
  }
  
  // 监听SSE错误
  eventSource.onerror = (error) => {
    console.error('SSE Error:', error)
    if (aiMessageIndex < messages.value.length && !messages.value[aiMessageIndex].content) {
      messages.value[aiMessageIndex].type = 'ai-error'
      messages.value[aiMessageIndex].content = error?.message || '连接失败，请稍后重试'
    }
    connectionStatus.value = 'error'
    eventSource.close()
  }
}

// 返回会话列表
const goBack = () => {
  router.push('/paper-reader')
}

// 页面加载时添加欢迎消息
watch(() => route.params.sessionId, (newSid) => {
  if (newSid) {
    sessionId.value = newSid
    loadSessionMessages(newSid)
  }
})

onMounted(() => {
  if (route.params.sessionId) {
    loadSessionMessages(route.params.sessionId)
  } else {
    addMessage('欢迎使用论文精读助手，请粘贴论文片段或提出精读需求，我会帮你梳理研究背景、方法设计与实验结论。', false)
  }
})

// 组件销毁前关闭SSE连接
onBeforeUnmount(() => {
  if (eventSource) {
    eventSource.close()
  }
  clearDocumentUrls()
})
</script>

<style scoped>
.paper-reader-container {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background-color: #f6fffc;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  background: linear-gradient(135deg, #14b8a6, #10b981);
  color: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  position: sticky;
  top: 0;
  z-index: 10;
}

.sidebar-toggle {
  font-size: 18px;
  cursor: pointer;
  background: none;
  border: none;
  color: white;
  padding: 4px 8px;
  margin-right: 4px;
  border-radius: 6px;
  transition: background 0.2s;
  line-height: 1;
}
.sidebar-toggle:hover {
  background: rgba(255,255,255,0.15);
}

.back-button {
  font-size: 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  transition: opacity 0.2s;
}

.back-button:hover {
  opacity: 0.8;
}

.back-button:before {
  content: '←';
  margin-right: 8px;
}

.title {
  font-size: 20px;
  font-weight: bold;
  margin: 0;
}

.session-label {
  font-size: 13px;
  opacity: 0.7;
}

.content-wrapper {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.chat-area {
  flex: 1;
  padding: 16px;
  overflow: hidden;
  position: relative;
  /* 设置最小高度确保内容显示正常 */
  min-height: calc(100vh - 56px - 180px);
  margin-bottom: 16px;
}

.footer-container {
  margin-top: auto;
}

/* 响应式样式 */
@media (max-width: 768px) {
  .header {
    padding: 12px 16px;
  }
  
  .title {
    font-size: 18px;
  }
  
  .chat-id {
    font-size: 12px;
  }
  
  .chat-area {
    padding: 12px;
    min-height: calc(100vh - 48px - 160px); /* 调整计算值 */
    margin-bottom: 12px;
  }
}

@media (max-width: 480px) {
  .header {
    padding: 10px 12px;
  }
  
  .back-button {
    font-size: 14px;
  }
  
  .title {
    font-size: 16px;
  }
  
  .chat-id {
    display: none;
  }
  
  .chat-area {
    padding: 8px;
    min-height: calc(100vh - 42px - 150px); /* 再次调整计算值 */
    margin-bottom: 8px;
  }
}
</style>

<style scoped>
.paper-reader-container { height: 100vh; min-height: 640px; overflow: hidden; background: #fff; }
.content-wrapper { width: 100%; height: calc(100vh - 124px); margin: 0; }
.chat-area { height: 100%; min-height: 0; margin: 0; padding: 0; }
@media (max-width: 640px) {
  .paper-reader-container { min-height: 560px; }
  .content-wrapper { width: 100%; height: calc(100vh - 114px); }
  .chat-area { padding: 0; }
}
</style>

<style scoped>
.paper-reader-container { height: 100vh; min-height: 640px; overflow: hidden; background: #fff; }
.header {
  position: sticky;
  top: 0;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  min-height: 68px;
  padding: 0 max(24px, calc((100vw - 1180px) / 2));
  color: var(--ink);
  background: rgba(255,255,255,.94);
  border-bottom: 1px solid var(--line);
  box-shadow: none;
  backdrop-filter: blur(12px);
}
.back-button {
  width: fit-content;
  color: var(--muted);
  font-size: 14px;
  font-weight: 550;
}
.back-button:hover { color: var(--ink); }
.back-button:before { margin-right: 7px; }
.title { color: var(--ink); font-size: 18px; font-weight: 700; letter-spacing: -.02em; }
.session-label { justify-self: end; color: var(--subtle); font-size: 12px; opacity: 1; }
.content-wrapper { display: grid; grid-template-columns: minmax(0, 1fr); width: 100%; height: calc(100vh - 124px); margin: 0; }
.content-wrapper.document-open { grid-template-columns: minmax(460px, 52%) minmax(420px, 48%); }
.chat-area { height: 100%; min-height: 0; margin: 0; padding: 0; }
.document-panel { display: flex; min-width: 0; min-height: 0; flex-direction: column; background: #f5f7fa; border-left: 1px solid #dfe6f0; }
.document-panel-header { display: flex; height: 58px; flex: 0 0 auto; padding: 0 14px 0 16px; align-items: center; justify-content: space-between; background: #fff; border-bottom: 1px solid #dfe6f0; }
.document-heading { display: flex; min-width: 0; align-items: center; gap: 10px; }
.document-icon { display: grid; width: 34px; height: 34px; flex: 0 0 auto; place-items: center; color: #1769e8; background: #edf4ff; border-radius: 8px; }
.document-icon svg { width: 19px; height: 19px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.document-heading div { display: flex; min-width: 0; flex-direction: column; }
.document-heading strong { overflow: hidden; color: #172e51; font-size: 13px; font-weight: 680; text-overflow: ellipsis; white-space: nowrap; }
.document-heading span:not(.document-icon) { margin-top: 2px; color: #8493a8; font-size: 10px; }
.close-document { display: grid; width: 34px; height: 34px; flex: 0 0 auto; padding: 0; place-items: center; color: #667991; background: transparent; border: 0; border-radius: 8px; cursor: pointer; }
.close-document:hover { color: #24466f; background: #f0f4f9; }
.close-document svg { width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; }
.document-frame { width: 100%; min-height: 0; flex: 1; background: #eef1f5; border: 0; }
.footer-container { margin-top: auto; }
@media (max-width: 960px) {
  .content-wrapper.document-open { grid-template-columns: minmax(380px, 48%) minmax(380px, 52%); }
}
@media (max-width: 768px) {
  .header { min-height: 62px; padding: 0 16px; }
  .title { font-size: 16px; }
  .content-wrapper { width: 100%; }
  .chat-area { padding: 0; }
  .content-wrapper.document-open { position: relative; display: block; }
  .content-wrapper.document-open .chat-area { height: 100%; }
  .document-panel { position: absolute; z-index: 20; inset: 0; border-left: 0; }
}
@media (max-width: 480px) {
  .header { grid-template-columns: auto 1fr; gap: 12px; }
  .title { text-align: right; }
  .session-label { display: none; }
  .back-button { font-size: 13px; }
  .content-wrapper { height: calc(100vh - 114px); }
}
</style>
