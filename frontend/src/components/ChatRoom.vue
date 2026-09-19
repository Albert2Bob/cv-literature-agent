<template>
  <div class="chat-container" :class="{ compact }">
    <!-- 聊天记录区域 -->
    <div class="chat-messages" ref="messagesContainer">
      <div v-for="(msg, index) in messages" :key="index" class="message-wrapper">
        <!-- AI消息 -->
        <div v-if="!msg.isUser" 
             class="message ai-message" 
             :class="[msg.type]">
          <div class="avatar ai-avatar">
            <AiAvatarFallback :type="aiType" />
          </div>
          <div class="message-bubble">
            <div class="message-content">
              <MarkdownRenderer :content="msg.content" />
              <span v-if="connectionStatus === 'connecting' && index === messages.length - 1" class="typing-indicator">▋</span>
            </div>
            <div class="message-time">{{ formatTime(msg.time) }}</div>
          </div>
        </div>
        
        <!-- 用户消息 -->
        <div v-else class="message user-message" :class="[msg.type]">
          <div class="message-bubble">
            <div class="message-content">{{ msg.content }}</div>
            <button
              v-if="msg.attachment"
              type="button"
              class="message-attachment"
              :title="`在右侧查看 ${msg.attachment.name}`"
              @click="emit('open-document', msg.attachment)"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M7 3h7l4 4v14H7z"/><path d="M14 3v5h5"/><path d="M9.5 13h5M9.5 16.5h5"/>
              </svg>
              <span>{{ msg.attachment.name }}</span>
              <svg class="attachment-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>
            </button>
            <div class="message-time">{{ formatTime(msg.time) }}</div>
          </div>
          <div class="avatar user-avatar">
            <div class="avatar-placeholder">我</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区域 -->
    <div class="chat-input-container">
      <div class="chat-input">
        <div v-if="enablePdfUpload" class="pdf-control" :class="{ expanded: pdfStatus.fileName }">
          <input
            ref="pdfInput"
            class="pdf-file-input"
            type="file"
            accept="application/pdf,.pdf"
            @change="handlePdfSelection"
          />
          <button
            type="button"
            class="pdf-upload-button"
            :class="{ ready: pdfAttachment, failed: pdfStatus.error }"
            :disabled="connectionStatus === 'connecting'"
            :title="pdfButtonTitle"
            @click="openPdfPicker"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M7 3h7l4 4v14H7z"/><path d="M14 3v5h5M9.5 15.5h5M9.5 12.5h5"/>
            </svg>
            <span v-if="pdfStatus.fileName" class="pdf-summary">
              <strong>{{ pdfStatus.fileName }}</strong>
              <small>{{ pdfStatusMessage }}</small>
            </span>
          </button>
          <button
            v-if="pdfStatus.fileName"
            type="button"
            class="pdf-remove-button"
            aria-label="移除 PDF"
            title="移除 PDF"
            @click="clearPdf"
          >×</button>
        </div>
        <div class="composer-field">
          <textarea 
            v-model="inputMessage" 
            @keydown.enter.prevent="sendMessage"
            placeholder="请输入你的问题..." 
            class="input-box"
            :disabled="connectionStatus === 'connecting'"
          ></textarea>
          <span class="composer-hint">Shift + Enter 换行，Enter 发送</span>
        </div>
        <button 
          @click="sendMessage" 
          class="send-button"
          :disabled="connectionStatus === 'connecting' || (!inputMessage.trim() && !pdfAttachment)"
        >发送</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick, watch, computed } from 'vue'
import AiAvatarFallback from './AiAvatarFallback.vue'
import MarkdownRenderer from './MarkdownRenderer.vue'

const props = defineProps({
  messages: {
    type: Array,
    default: () => []
  },
  connectionStatus: {
    type: String,
    default: 'disconnected'
  },
  aiType: {
    type: String,
    default: 'default'  // 'paper' 或 'cv'
  },
  enablePdfUpload: {
    type: Boolean,
    default: false
  },
  compact: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['send-message', 'open-document'])

const inputMessage = ref('')
const messagesContainer = ref(null)
const pdfInput = ref(null)
const pdfAttachment = ref(null)
const pdfStatus = reactive({
  fileName: '',
  error: ''
})
const MAX_PDF_BYTES = 30 * 1024 * 1024

const pdfStatusMessage = computed(() => {
  if (pdfStatus.error) return pdfStatus.error
  if (!pdfAttachment.value) return ''
  const megabytes = pdfAttachment.value.size / 1024 / 1024
  return `${megabytes.toFixed(megabytes >= 10 ? 0 : 1)} MB · 已就绪`
})

const pdfButtonTitle = computed(() => {
  if (pdfAttachment.value) return `已选择 ${pdfStatus.fileName}，发送后由服务器解析`
  if (pdfStatus.error) return pdfStatus.error
  return '选择 PDF，发送后由服务器解析全文'
})

// 根据AI类型选择不同头像
const aiAvatar = computed(() => {
  return props.aiType === 'paper'
    ? '/ai-paper-avatar.png'  // 论文精读助手头像
    : '/ai-cv-avatar.png'     // CV科研问答智能体头像
})

// 发送消息
const sendMessage = () => {
  const question = inputMessage.value.trim()
    || (pdfAttachment.value ? '请对这篇论文进行系统精读，梳理研究背景、核心方法、实验设计、主要结论与局限性。' : '')
  if (!question) return

  const attachment = pdfAttachment.value ? { ...pdfAttachment.value } : null
  emit('send-message', question, attachment)
  inputMessage.value = ''
  clearPdf()
}

const openPdfPicker = () => {
  if (props.connectionStatus !== 'connecting') {
    pdfInput.value?.click()
  }
}

const clearPdf = () => {
  pdfAttachment.value = null
  Object.assign(pdfStatus, {
    fileName: '',
    error: ''
  })
  if (pdfInput.value) pdfInput.value.value = ''
}

const handlePdfSelection = (event) => {
  const file = event.target.files?.[0]
  if (!file) return

  pdfAttachment.value = null
  Object.assign(pdfStatus, {
    fileName: file.name,
    error: ''
  })

  const isPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf')
  if (!isPdf) {
    pdfStatus.error = '仅支持 PDF 文件'
    return
  }
  if (file.size > MAX_PDF_BYTES) {
    pdfStatus.error = 'PDF 不能超过 30 MB'
    return
  }

  pdfAttachment.value = {
    name: file.name,
    file,
    size: file.size
  }
}

// 格式化时间
const formatTime = (timestamp) => {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

// 自动滚动到底部
const scrollToBottom = async () => {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

// 监听消息变化与内容变化，自动滚动
watch(() => props.messages.length, () => {
  scrollToBottom()
})

watch(() => props.messages.map(m => m.content).join(''), () => {
  scrollToBottom()
})

onMounted(() => {
  scrollToBottom()
})
</script>

<style scoped>
.chat-container {
  display: flex;
  flex-direction: column;
  height: 70vh;
  min-height: 600px;
  background-color: #f5f5f5;
  border-radius: 8px;
  overflow: hidden;
  position: relative;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  padding-bottom: 80px; /* 为输入框留出空间 */
  display: flex;
  flex-direction: column;
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 72px; /* 与输入框高度相匹配 */
}

.message-wrapper {
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  width: 100%;
}

.message {
  display: flex;
  align-items: flex-start;
  max-width: 85%;
  margin-bottom: 8px;
}

.user-message {
  margin-left: auto; /* 用户消息靠右 */
  flex-direction: row; /* 正常顺序，先气泡后头像 */
}

.ai-message {
  margin-right: auto; /* AI消息靠左 */
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  overflow: hidden;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-avatar {
  margin-left: 8px; /* 用户头像在右侧，左边距 */
}

.ai-avatar {
  margin-right: 8px; /* AI头像在左侧，右边距 */
}

.avatar-placeholder {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #007bff;
  color: white;
  font-weight: bold;
}

.message-bubble {
  padding: 12px;
  border-radius: 18px;
  position: relative;
  word-wrap: break-word;
  min-width: 100px; /* 最小宽度 */
}

.user-message .message-bubble {
  background-color: #007bff;
  color: white;
  border-bottom-right-radius: 4px;
  text-align: left;
}

.ai-message .message-bubble {
  background-color: #e9e9eb;
  color: #333;
  border-bottom-left-radius: 4px;
  text-align: left;
}

.message-content {
  font-size: 16px;
  line-height: 1.5;
}

.message-time {
  font-size: 12px;
  opacity: 0.7;
  margin-top: 4px;
  text-align: right;
}

.chat-input-container {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  background-color: white;
  border-top: 1px solid #e0e0e0;
  z-index: 100;
  height: 72px; /* 固定高度 */
  box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.05);
}

.chat-input {
  display: flex;
  padding: 16px;
  height: 100%;
  box-sizing: border-box;
  align-items: center;
}

.input-box {
  flex-grow: 1;
  border: 1px solid #ddd;
  border-radius: 20px;
  padding: 10px 16px;
  font-size: 16px;
  resize: none;
  min-height: 20px;
  max-height: 40px; /* 限制高度 */
  outline: none;
  transition: border-color 0.3s;
  overflow-y: auto;
  scrollbar-width: none; /* Firefox */
  -ms-overflow-style: none; /* IE & Edge */
}

/* 隐藏Webkit浏览器的滚动条 */
.input-box::-webkit-scrollbar {
  display: none;
}

.input-box:focus {
  border-color: #007bff;
}

.send-button {
  margin-left: 12px;
  background-color: #007bff;
  color: white;
  border: none;
  border-radius: 20px;
  padding: 0 20px;
  font-size: 16px;
  cursor: pointer;
  transition: background-color 0.3s;
  height: 40px;
  align-self: center;
}

.send-button:hover:not(:disabled) {
  background-color: #0069d9;
}

.typing-indicator {
  display: inline-block;
  animation: blink 0.7s infinite;
  margin-left: 2px;
}

@keyframes blink {
  0% { opacity: 0; }
  50% { opacity: 1; }
  100% { opacity: 0; }
}

.input-box:disabled, .send-button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .message {
    max-width: 95%;
  }
  
  .message-content {
    font-size: 15px;
  }
  
  .chat-input {
    padding: 12px;
  }
  
  .input-box {
    padding: 8px 12px;
  }
  
  .send-button {
    padding: 0 15px;
    font-size: 14px;
  }
}

@media (max-width: 480px) {
  .avatar {
    width: 32px;
    height: 32px;
  }
  
  .message-bubble {
    padding: 10px;
  }
  
  .message-content {
    font-size: 14px;
  }
  
  .chat-input-container {
    height: 64px;
  }
  
  .chat-messages {
    bottom: 64px;
  }
}

/* 新增：不同类型消息的样式 */
.ai-answer {
  animation: fadeIn 0.3s ease-in-out;
}

/* 错误信息：高亮红色气泡 */
.ai-error {
  background-color: #ffcdd2;    /* 浅红（Material Design 红 100） */
  color: #b71c1c;
}

.ai-think {
  font-style: italic;
  background-color: #b3c6ff;   /* 较深的天蓝 */
}

.ai-step {
  background-color: #81c784;    /* 中绿色（Material Design 绿） */
}

.ai-final {
  background-color: #ffb74d;    /* 橙色（偏亮橙） */
}

.user-question {
  /* 用户提问的特殊样式 */
}

/* 连续消息气泡样式 */
.ai-message + .ai-message {
  margin-top: 4px;
}

.ai-message + .ai-message .avatar {
  visibility: hidden;
}

.ai-message + .ai-message .message-bubble {
  border-top-left-radius: 10px;
}
</style>

<style scoped>
.chat-container {
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #fff;
  border: 0;
  border-radius: 0;
  box-shadow: none;
}
.chat-messages {
  position: absolute;
  inset: 0 0 94px;
  gap: 0;
  padding: 22px max(18px, calc((100vw - 960px) / 2)) 36px;
  background: #fff;
}
.message-wrapper { margin-bottom: 20px; }
.message { width: fit-content; max-width: min(78%, 720px); }
.ai-message,
.user-message { background: transparent; }
.ai-final,
.ai-step,
.ai-think,
.ai-error { background: transparent; }
.avatar {
  width: 38px;
  height: 38px;
  border-radius: 50%;
}
.ai-avatar { margin-right: 12px; }
.user-avatar { margin-left: 12px; }
.avatar-placeholder { color: #1769e8; background: #eaf2ff; font-size: 12px; font-weight: 700; }
.message-bubble {
  min-width: 0;
  padding: 15px 17px;
  border: 0;
  border-radius: 12px;
}
.user-message .message-bubble {
  color: #163761;
  background: #e7f1ff;
  border: 0;
  border-bottom-right-radius: 4px;
}
.ai-message .message-bubble,
.ai-final .message-bubble {
  color: #263b5b;
  background: #f2f5f8;
  border: 0;
  border-bottom-left-radius: 4px;
}
.ai-think .message-bubble { color: #52647d; background: #f5f7fa; }
.ai-step .message-bubble { color: #19645f; background: #eaf8f6; }
.ai-error .message-bubble { color: #a32930; background: #fff1f2; }
.message-content { font-size: 14px; line-height: 1.72; }
.message-time { margin-top: 6px; color: #8797ad; font-size: 11px; }
.message-attachment {
  display: flex;
  width: 100%;
  min-width: 220px;
  margin-top: 10px;
  padding: 9px 10px;
  align-items: center;
  gap: 8px;
  color: #285c98;
  background: rgba(255,255,255,.72);
  border: 1px solid rgba(66,119,181,.2);
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: color .18s ease, background .18s ease, border-color .18s ease;
}
.message-attachment:hover { color: #1553a1; background: #fff; border-color: rgba(39,100,174,.38); }
.message-attachment svg { width: 18px; height: 18px; flex: 0 0 auto; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.message-attachment span { min-width: 0; overflow: hidden; font-size: 12px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.message-attachment .attachment-arrow { width: 15px; height: 15px; margin-left: auto; }
.chat-container.compact .chat-messages { padding-right: 24px; padding-left: 24px; }
.chat-container.compact .message { max-width: min(90%, 680px); }
.chat-container.compact .chat-input-container { padding-right: 12px; padding-left: 12px; }
.chat-container.compact .pdf-upload-button.ready,
.chat-container.compact .pdf-upload-button.failed { width: 50px; padding: 0; justify-content: center; }
.chat-container.compact .pdf-summary { display: none; }
.chat-input-container {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 94px;
  padding: 12px max(10px, calc((100vw - 1120px) / 2));
  background: rgba(255,255,255,.98);
  border-top: 0;
  box-shadow: 0 -12px 30px rgba(33,56,88,.035);
}
.chat-input {
  display: flex;
  gap: 10px;
  height: 70px;
  padding: 9px;
  align-items: center;
  background: #fff;
  border: 1px solid #dde5ef;
  border-radius: 11px;
  box-shadow: 0 4px 16px rgba(29,52,84,.055);
}
.composer-field { position: relative; height: 100%; flex: 1; min-width: 0; }
.input-box {
  width: 100%;
  height: 100%;
  min-height: 0;
  max-height: none;
  padding: 10px 14px 22px;
  color: var(--ink);
  background: #fff;
  border: 1px solid #e0e6ef;
  border-radius: 8px;
  font-size: 13px;
  line-height: 20px;
}
.input-box:focus { background: #fff; border-color: #b9c9df; box-shadow: none; }
.composer-hint {
  position: absolute;
  right: 12px;
  bottom: 5px;
  color: #93a1b5;
  font-size: 10px;
  pointer-events: none;
}
.send-button {
  width: 92px;
  height: 50px;
  flex: 0 0 auto;
  margin: 0;
  padding: 0;
  color: #fff;
  background: #176de5;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 650;
}
.send-button:hover:not(:disabled) { background: #0f5cc9; }
.pdf-control { position: relative; display: flex; height: 50px; flex: 0 0 auto; align-items: center; }
.pdf-file-input { position: absolute; width: 1px; height: 1px; overflow: hidden; opacity: 0; pointer-events: none; }
.pdf-upload-button {
  display: flex;
  width: 50px;
  height: 50px;
  min-width: 50px;
  padding: 0;
  align-items: center;
  justify-content: center;
  gap: 9px;
  color: #2b6f9f;
  background: #f0f8fd;
  border: 1px solid #cfe3f0;
  border-radius: 8px;
  cursor: pointer;
  transition: border-color .18s ease, background .18s ease, color .18s ease;
}
.pdf-upload-button:hover:not(:disabled) { color: #155c91; background: #e7f4fb; border-color: #9fc9e2; }
.pdf-upload-button.ready { width: min(240px, 23vw); padding: 0 30px 0 12px; justify-content: flex-start; color: #14756e; background: #edf9f7; border-color: #bce3de; }
.pdf-upload-button.failed { width: min(240px, 23vw); padding: 0 30px 0 12px; justify-content: flex-start; color: #a33a43; background: #fff4f4; border-color: #efc9cd; }
.pdf-upload-button:disabled { cursor: wait; opacity: .76; }
.pdf-upload-button svg { width: 22px; height: 22px; flex: 0 0 auto; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.pdf-summary { display: flex; min-width: 0; flex-direction: column; align-items: flex-start; text-align: left; }
.pdf-summary strong { display: block; width: 100%; overflow: hidden; color: currentColor; font-size: 11px; font-weight: 650; line-height: 16px; text-overflow: ellipsis; white-space: nowrap; }
.pdf-summary small { display: block; width: 100%; overflow: hidden; color: #71859d; font-size: 9px; line-height: 14px; text-overflow: ellipsis; white-space: nowrap; }
.pdf-remove-button { position: absolute; top: 4px; right: 5px; width: 20px; height: 20px; padding: 0; color: #7d8da1; background: transparent; border: 0; border-radius: 50%; font-size: 17px; line-height: 18px; cursor: pointer; }
.pdf-remove-button:hover { color: #a12c36; background: rgba(161,44,54,.08); }
@media (max-width: 640px) {
  .chat-messages { bottom: 84px; padding: 18px 12px 26px; }
  .message { max-width: 92%; }
  .avatar { width: 32px; height: 32px; }
  .message-bubble { padding: 12px 14px; }
  .message-content { font-size: 13px; }
  .chat-input-container { height: 84px; padding: 8px; }
  .chat-input { height: 68px; }
  .composer-hint { display: none; }
  .input-box { padding-bottom: 10px; }
  .pdf-upload-button.ready, .pdf-upload-button.failed { width: 50px; padding: 0; justify-content: center; }
  .pdf-summary { display: none; }
  .pdf-remove-button { top: -5px; right: -5px; color: #a12c36; background: #fff; box-shadow: 0 1px 5px rgba(40,60,85,.16); }
  .send-button { width: 68px; height: 48px; }
  .message-attachment { min-width: 190px; }
}
</style>
