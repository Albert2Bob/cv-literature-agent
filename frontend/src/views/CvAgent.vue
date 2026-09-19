<template>
  <div class="cv-agent-container">
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
      <h1 class="title">CV科研问答智能体</h1>
      <div class="conversation-actions" aria-label="会话操作">
        <span class="toolbar-action"><svg viewBox="0 0 24 24"><path d="m4 20 4.2-1L19 8.2 15.8 5 5 15.8zM14.5 6.3l3.2 3.2"/></svg>重命名</span>
        <span class="toolbar-action"><svg viewBox="0 0 24 24"><path d="M4 7h16M9 4h6M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg>删除</span>
        <span class="more-action" aria-hidden="true">•••</span>
      </div>
    </div>
    
    <div class="content-wrapper">
      <div class="chat-area">
        <ChatRoom 
          :messages="messages" 
          :connection-status="connectionStatus"
          ai-type="cv"
          @send-message="sendMessage"
        />
      </div>
    </div>
    
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onBeforeUnmount, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useHead } from '@vueuse/head'
import ChatRoom from '../components/ChatRoom.vue'
import { chatWithCvAgent, getSessionMessages } from '../api'

useHead({
  title: 'CV科研问答智能体 - AI 科研问答系统',
  meta: [
    {
      name: 'description',
      content: 'CV科研问答智能体是AI 科研问答系统面向计算机视觉与深度学习的专业问答助手，能解答模型、数据集与训练相关问题'
    },
    {
      name: 'keywords',
      content: 'CV科研问答,计算机视觉,深度学习,目标检测,图像分割,科研助手,AI科研助手'
    }
  ]
})

const router = useRouter()
const route = useRoute()
const messages = ref([])
const sessionId = ref(route.params.sessionId || "")
const connectionStatus = ref('disconnected')
const currentNickname = computed(() => {
  try {
    return JSON.parse(localStorage.getItem('user') || '{}').nickname || '研究者'
  } catch {
    return '研究者'
  }
})
let eventSource = null

async function loadSessionMessages(sid) {
  sessionId.value = sid
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
            type: m.role === 'user' ? '' : 'ai-final',
          })
        }
      }
    } catch (e) { /* ignore */ }
  }
}

const addMessage = (content, isUser, type) => {
  messages.value.push({
    content,
    isUser,
    type: type || '',
    time: new Date().getTime()
  })
}

const sendMessage = (message) => {
  addMessage(message, true, 'user-question')

  if (eventSource) {
    eventSource.close()
  }

  connectionStatus.value = 'connecting'

  eventSource = chatWithCvAgent(message, sessionId.value)

  // 先创建 EventSource，再挂载 onmessage
  eventSource.onmessage = (event) => {
    const data = event.data
    if (data === '[THINKING]') return
    if (data === '[DONE]') {
      connectionStatus.value = 'disconnected'
      eventSource.close()
      return
    }
    if (!data) return

    if (data.startsWith('[THINK]')) {
      addMessage(data.slice(7).trim(), false, 'ai-think')
    } else if (data.startsWith('[STEP]')) {
      addMessage(data.slice(6).trim(), false, 'ai-step')
    } else if (data.startsWith('[FINAL]')) {
      addMessage(data.slice(7).trim(), false, 'ai-final')
    } else if (data.startsWith('[ERROR]')) {
      addMessage(data.slice(7).trim(), false, 'ai-error')
      connectionStatus.value = 'disconnected'
      eventSource.close()
    }
  }

  eventSource.onerror = (error) => {
    console.error('SSE Error:', error)
    connectionStatus.value = 'error'
    eventSource.close()
  }
}

const goBack = () => {
  router.push('/cv-agent')
}

watch(() => route.params.sessionId, (newSid) => {
  if (newSid && newSid !== sessionId.value) {
    sessionId.value = newSid
    loadSessionMessages(newSid)
  }
})

onMounted(() => {
  if (route.params.sessionId) {
    loadSessionMessages(route.params.sessionId)
  } else {
    addMessage('你好，我是CV科研问答智能体。我专注于计算机视觉与深度学习方向的科研问答，可以帮你分析模型结构、数据集、训练策略与实验现象，请问有什么可以帮助你的吗？', false, '')
  }
})

onBeforeUnmount(() => {
  if (eventSource) {
    eventSource.close()
  }
})
</script>

<style scoped>
.cv-agent-container {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background-color: #f9fbff;
}

.header {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  padding: 16px 24px;
  background-color: #3f51b5;
  color: white;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  position: sticky;
  top: 0;
  z-index: 10;
}

.back-button {
  font-size: 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  transition: opacity 0.2s;
  justify-self: start;
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
  text-align: center;
  justify-self: center;
}

.placeholder {
  width: 1px;
  justify-self: end;
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
  min-height: calc(100vh - 56px - 180px);
  margin-bottom: 16px;
}

.footer-container {
  margin-top: auto;
}

@media (max-width: 768px) {
  .header {
    padding: 12px 16px;
  }
  
  .title {
    font-size: 18px;
  }
  
  .chat-area {
    padding: 12px;
    min-height: calc(100vh - 48px - 160px);
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
  
  .chat-area {
    padding: 8px;
    min-height: calc(100vh - 42px - 150px);
    margin-bottom: 8px;
  }
}
</style>

<style scoped>
.cv-agent-container { height: 100vh; min-height: 640px; overflow: hidden; background: #fff; }
.content-wrapper { width: 100%; height: calc(100vh - 124px); margin: 0; }
.chat-area { height: 100%; min-height: 0; margin: 0; padding: 0; }
@media (max-width: 640px) {
  .cv-agent-container { min-height: 560px; }
  .content-wrapper { width: 100%; height: calc(100vh - 114px); }
  .chat-area { padding: 0; }
}
</style>

<style scoped>
.cv-agent-container {
  height: 100vh;
  min-height: 640px;
  overflow: hidden;
  background: #fff;
}
.content-wrapper {
  width: 100%;
  height: calc(100vh - 124px);
  margin: 0;
}
.chat-area {
  height: 100%;
  min-height: 0;
  margin: 0;
  padding: 0;
}
@media (max-width: 640px) {
  .cv-agent-container { min-height: 560px; }
  .content-wrapper { width: 100%; height: calc(100vh - 114px); }
  .chat-area { padding: 0; }
}
</style>

<style scoped>
.cv-agent-container { height: 100vh; min-height: 640px; overflow: hidden; background: #fff; }
.header {
  position: sticky;
  top: 0;
  min-height: 72px;
  padding: 0 max(24px, calc((100vw - 1180px) / 2));
  color: var(--ink);
  background: rgba(255,255,255,.94);
  border-bottom: 1px solid var(--line);
  box-shadow: none;
  backdrop-filter: blur(12px);
}
.back-button { width: fit-content; color: var(--muted); font-size: 14px; font-weight: 550; }
.back-button:hover { color: var(--ink); opacity: 1; }
.back-button:before { margin-right: 7px; }
.title { color: var(--ink); font-size: 18px; font-weight: 700; letter-spacing: -.02em; }
.session-label { justify-self: end; color: var(--subtle); font-size: 12px; opacity: 1; }
.content-wrapper { width: 100%; height: calc(100vh - 124px); margin: 0; }
.chat-area { height: 100%; min-height: 0; margin: 0; padding: 0; }
.footer-container { margin-top: auto; }
@media (max-width: 768px) {
  .header { min-height: 62px; padding: 0 16px; }
  .title { font-size: 16px; }
  .content-wrapper { width: 100%; }
  .chat-area { padding: 0; }
}
@media (max-width: 480px) {
  .header { grid-template-columns: auto 1fr; gap: 12px; }
  .title { text-align: right; }
  .session-label { display: none; }
  .back-button { font-size: 13px; }
  .content-wrapper { height: calc(100vh - 114px); }
}
</style>
