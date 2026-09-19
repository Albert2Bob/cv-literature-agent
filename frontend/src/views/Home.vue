<template>
  <div class="home-container">
    <!-- User info bar -->
    <div class="user-bar" v-if="user">
      <div class="user-avatar">{{ user.nickname.charAt(0) }}</div>
      <div class="user-meta">
        <span class="user-nick">{{ user.nickname }}</span>
        <span class="user-name">@{{ user.username }}</span>
      </div>
      <button class="logout-btn" @click="handleLogout" title="退出登录">退出</button>
    </div>

    <div class="header">
      <div class="glitch-wrapper">
        <h1 class="glitch-title">AI 科研问答系统</h1>
      </div>
      <p class="subtitle">/ 探索计算机视觉与深度学习 /</p>
      <div class="cyber-line"></div>
    </div>
    
    <div class="apps-container">
      <div class="app-card" @click="navigateTo('/paper-reader')">
        <div class="card-glow"></div>
        <div class="app-icon paper-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M6.5 3.5h8l3 3v14h-11z"/><path d="M14.5 3.5v4h4M9.5 12h5M9.5 15.5h5"/></svg>
        </div>
        <div class="app-info">
          <div class="app-title">论文精读助手</div>
          <div class="app-desc">逐段精读CV与深度学习论文，梳理方法、实验与结论</div>
        </div>
        <div class="app-button">
          <span class="btn-text">立即体验</span>
          <span class="btn-icon">→</span>
        </div>
      </div>
      
      <div class="app-card" @click="navigateTo('/cv-agent')">
        <div class="card-glow"></div>
        <div class="app-icon robot-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M8 8.5h8a3 3 0 0 1 3 3v5a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3v-5a3 3 0 0 1 3-3Z"/><path d="M12 8.5V5.5M9 13h.01M15 13h.01M9 16.5h6"/></svg>
        </div>
        <div class="app-info">
          <div class="app-title">CV科研问答智能体</div>
          <div class="app-desc">面向计算机视觉的科研问答，解答模型、数据集与训练难题</div>
        </div>
        <div class="app-button">
          <span class="btn-text">立即体验</span>
          <span class="btn-icon">→</span>
        </div>
      </div>

      <div class="app-card" @click="navigateTo('/rag-documents')">
        <div class="card-glow"></div>
        <div class="app-icon rag-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M4 6c0-1.1 3.6-2 8-2s8 .9 8 2-3.6 2-8 2-8-.9-8-2Z"/><path d="M4 6v6c0 1.1 3.6 2 8 2s8-.9 8-2V6M4 12v6c0 1.1 3.6 2 8 2s8-.9 8-2v-6"/></svg>
        </div>
        <div class="app-info">
          <div class="app-title">RAG 文件管理</div>
          <div class="app-desc">管理知识库文档，支持上传、新建、编辑、检索与删除</div>
        </div>
        <div class="app-button">
          <span class="btn-text">管理文档</span>
          <span class="btn-icon">→</span>
        </div>
      </div>
    </div>
    
    <div class="cyber-circles">
      <div class="circle circle-1"></div>
      <div class="circle circle-2"></div>
      <div class="circle circle-3"></div>
    </div>
    
    <AppFooter />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useHead } from '@vueuse/head'
import AppFooter from '../components/AppFooter.vue'
import { logout } from '../api/index.js'

// 设置页面标题和元数据
useHead({
  title: 'AI 科研问答系统 - 首页',
  meta: [
    {
      name: 'description',
      content: 'AI 科研问答系统面向计算机视觉与深度学习研究，提供论文精读助手和CV科研问答智能体服务'
    },
    {
      name: 'keywords',
      content: '计算机视觉,深度学习,论文精读,科研问答,CV智能体,AI科研助手,首页'
    }
  ]
})

const router = useRouter()

const user = ref(null)

onMounted(() => {
  const raw = localStorage.getItem('user')
  if (raw) {
    try { user.value = JSON.parse(raw) } catch {}
  }
})

const navigateTo = (path) => {
  router.push(path)
}

async function handleLogout() {
  try {
    await logout()
  } catch {
    // 服务端不可达时无法撤销远端会话，但不阻塞本地退出。
  } finally {
    // 即使网络暂时不可用，也要先结束当前浏览器里的登录状态。
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    router.push('/login')
  }
}
</script>

<style scoped>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;500;700&display=swap');

/* 全局样式变量 */
:root {
  --neon-blue: #00f0ff;
  --neon-purple: #9000ff;
  --neon-pink: #ff00d4;
  --cyber-black: #0a0a12;
  --cyber-dark: #111122;
  --cyber-light: #edf7ff;
}

.home-container {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  background-color: var(--cyber-dark);
  background-image: 
    linear-gradient(0deg, rgba(8, 17, 34, 0.9), rgba(5, 8, 20, 0.9)),
    url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><rect x="0" y="0" width="100" height="1" fill="%23111133" opacity="0.3"/><rect x="0" y="0" width="1" height="100" fill="%23111133" opacity="0.3"/></svg>');
  background-size: auto, 40px 40px;
  position: relative;
  overflow: hidden;
}

/* 赛博朋克风格标题 */
.header {
  padding: 50px 20px 50px;
  text-align: center;
  background-color: transparent;
  position: relative;
  z-index: 2;
}

.glitch-wrapper {
  position: relative;
  display: inline-block;
  margin-bottom: 20px;
}

.glitch-title {
  font-family: 'Orbitron', sans-serif;
  font-size: 3.2rem;
  font-weight: 700;
  color: var(--cyber-light);
  text-shadow: 
    0 0 5px rgba(0, 240, 255, 0.7),
    0 0 10px rgba(0, 240, 255, 0.5),
    0 0 20px rgba(0, 240, 255, 0.3);
  letter-spacing: 2px;
  position: relative;
  animation: glitch 3s infinite;
}

.glitch-title::before,
.glitch-title::after {
  content: 'AI 科研问答系统';
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  opacity: 0.8;
}

.glitch-title::before {
  color: var(--neon-pink);
  z-index: -1;
  animation: glitch-anim 2s infinite;
}

.glitch-title::after {
  color: var(--neon-blue);
  z-index: -2;
  animation: glitch-anim-2 3s infinite;
}

.subtitle {
  font-family: 'Orbitron', sans-serif;
  font-size: 1.2rem;
  color: rgba(255, 255, 255, 0.7);
  max-width: 600px;
  margin: 0 auto 20px;
  letter-spacing: 3px;
  text-transform: uppercase;
}

.cyber-line {
  height: 2px;
  width: 80%;
  max-width: 600px;
  margin: 0 auto;
  background: linear-gradient(90deg, transparent, var(--neon-blue), transparent);
  position: relative;
}

.cyber-line::before,
.cyber-line::after {
  content: '';
  position: absolute;
  top: 50%;
  width: 10px;
  height: 10px;
  background-color: var(--neon-blue);
  border-radius: 50%;
  transform: translateY(-50%);
  box-shadow: 0 0 10px 2px var(--neon-blue);
}

.cyber-line::before {
  left: 20%;
}

.cyber-line::after {
  right: 20%;
}

.apps-container {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 50px;
  max-width: 1200px;
  margin: 60px auto;
  padding: 0 20px;
  flex: 1;
  position: relative;
  z-index: 2;
}

.app-card {
  width: 340px;
  background-color: rgba(17, 23, 41, 0.7);
  backdrop-filter: blur(10px);
  border-radius: 16px;
  box-shadow: 
    0 8px 32px rgba(0, 240, 255, 0.2),
    inset 0 0 0 1px rgba(255, 255, 255, 0.1);
  padding: 30px;
  cursor: pointer;
  transition: all 0.4s cubic-bezier(0.175, 0.885, 0.32, 1.275);
  display: flex;
  flex-direction: column;
  align-items: center;
  position: relative;
  overflow: hidden;
}

.card-glow {
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: radial-gradient(
    circle at center,
    rgba(var(--neon-blue-rgb), 0.1) 0%,
    transparent 70%
  );
  opacity: 0;
  transition: opacity 0.5s;
  pointer-events: none;
}

.app-card:hover {
  transform: translateY(-15px) scale(1.03);
  box-shadow: 
    0 15px 50px rgba(0, 240, 255, 0.3),
    inset 0 0 0 1px rgba(0, 240, 255, 0.5);
}

.app-card:hover .card-glow {
  opacity: 1;
}

.app-icon {
  font-size: 4rem;
  margin-bottom: 25px;
  width: 90px;
  height: 90px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  position: relative;
  z-index: 1;
}

.paper-icon {
  background: linear-gradient(135deg, #14b8a6, #4ade80);
  box-shadow: 0 0 20px rgba(20, 184, 166, 0.5);
}

.robot-icon {
  background: linear-gradient(135deg, #00b2ff, #4f56ff);
  box-shadow: 0 0 20px rgba(0, 178, 255, 0.5);
}

.app-info {
  text-align: center;
  margin-bottom: 30px;
  width: 100%;
}

.app-title {
  font-family: 'Orbitron', sans-serif;
  font-size: 1.6rem;
  font-weight: bold;
  color: white;
  margin-bottom: 12px;
  text-shadow: 0 0 10px rgba(0, 240, 255, 0.5);
}

.app-desc {
  font-size: 1rem;
  color: rgba(255, 255, 255, 0.7);
  line-height: 1.6;
}

.app-button {
  background: linear-gradient(90deg, #0088ff, #00b2ff);
  color: white;
  padding: 12px 28px;
  border-radius: 30px;
  font-weight: 500;
  transition: all 0.3s;
  margin-top: auto;
  display: flex;
  align-items: center;
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(0, 240, 255, 0.3);
}

.app-button::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
  transition: left 0.7s;
}

.app-button:hover {
  box-shadow: 0 0 15px rgba(0, 178, 255, 0.7);
  transform: scale(1.05);
}

.app-button:hover::before {
  left: 100%;
}

.btn-text {
  margin-right: 8px;
  letter-spacing: 1px;
}

.btn-icon {
  font-size: 1.2rem;
  transition: transform 0.3s;
}

.app-button:hover .btn-icon {
  transform: translateX(4px);
}

/* 背景圆圈动画 */
.cyber-circles {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
  z-index: 1;
}

.circle {
  position: absolute;
  border-radius: 50%;
  opacity: 0.15;
}

.circle-1 {
  width: 300px;
  height: 300px;
  top: -100px;
  right: -100px;
  background: linear-gradient(135deg, var(--neon-blue), var(--neon-purple));
  animation: float 15s infinite alternate;
}

.circle-2 {
  width: 500px;
  height: 500px;
  bottom: -200px;
  left: -200px;
  background: linear-gradient(135deg, var(--neon-purple), var(--neon-pink));
  animation: float 20s infinite alternate-reverse;
}

.circle-3 {
  width: 200px;
  height: 200px;
  top: 40%;
  right: 15%;
  background: linear-gradient(135deg, var(--neon-pink), var(--neon-blue));
  animation: float 12s infinite alternate;
}

/* 动画效果 */
@keyframes float {
  0% {
    transform: translate(0, 0) rotate(0deg);
  }
  100% {
    transform: translate(50px, 50px) rotate(10deg);
  }
}

@keyframes glitch {
  0% {
    text-shadow: 
      0 0 5px rgba(0, 240, 255, 0.7),
      0 0 10px rgba(0, 240, 255, 0.5);
  }
  50% {
    text-shadow: 
      0 0 5px rgba(0, 240, 255, 0.7),
      0 0 10px rgba(0, 240, 255, 0.5),
      0 0 20px rgba(0, 240, 255, 0.3);
  }
  100% {
    text-shadow: 
      0 0 5px rgba(0, 240, 255, 0.7),
      0 0 10px rgba(0, 240, 255, 0.5);
  }
}

@keyframes glitch-anim {
  0%, 100% {
    transform: translate(0);
  }
  20% {
    transform: translate(-5px, 5px);
  }
  40% {
    transform: translate(-5px, -5px);
  }
  60% {
    transform: translate(5px, 5px);
  }
  80% {
    transform: translate(5px, -5px);
  }
}

@keyframes glitch-anim-2 {
  0%, 100% {
    transform: translate(0);
  }
  20% {
    transform: translate(3px, -3px);
  }
  40% {
    transform: translate(3px, 3px);
  }
  60% {
    transform: translate(-3px, -3px);
  }
  80% {
    transform: translate(-3px, 3px);
  }
}

/* 响应式设计 */
/* User info bar */
.user-bar {
  position: absolute;
  top: 16px;
  right: 20px;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(17, 23, 41, 0.75);
  backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 30px;
  padding: 6px 6px 6px 12px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  transition: box-shadow 0.3s;
}
.user-bar:hover {
  box-shadow: 0 4px 24px rgba(0, 240, 255, 0.15);
}
.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #00f0ff, #0088ff);
  color: #fff;
  font-size: 0.85rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 0 8px rgba(0, 240, 255, 0.4);
}
.user-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
}
.user-nick {
  color: #edf7ff;
  font-size: 0.85rem;
  font-weight: 600;
}
.user-name {
  color: rgba(255, 255, 255, 0.4);
  font-size: 0.7rem;
}
.logout-btn {
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 20px;
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.78rem;
  padding: 6px 14px;
  cursor: pointer;
  transition: all 0.25s;
  font-family: inherit;
}
.logout-btn:hover {
  background: rgba(255, 71, 87, 0.2);
  border-color: rgba(255, 71, 87, 0.4);
  color: #ff4757;
}
@media (max-width: 768px) {
  .user-meta { display: none; }
  .glitch-title {
    font-size: 2.5rem;
  }
  
  .subtitle {
    font-size: 1rem;
  }
  
  .apps-container {
    gap: 30px;
    margin: 40px auto;
  }
  
  .app-card {
    width: 100%;
    max-width: 420px;
    padding: 25px;
  }
  
  .app-icon {
    font-size: 3.5rem;
    width: 80px;
    height: 80px;
  }
}

@media (max-width: 480px) {
  .user-meta { display: none; }
  .header {
    padding: 50px 15px 40px;
  }
  
  .glitch-title {
    font-size: 2rem;
  }
  
  .subtitle {
    font-size: 0.9rem;
    letter-spacing: 2px;
  }
  
  .apps-container {
    margin: 30px auto;
    padding: 0 15px;
  }
  
  .app-card {
    padding: 20px;
  }
  
  .app-icon {
    font-size: 3rem;
    margin-bottom: 20px;
    width: 70px;
    height: 70px;
  }
  
  .app-title {
    font-size: 1.4rem;
  }
  
  .app-desc {
    font-size: 0.9rem;
  }
  
  .circle-1, .circle-2, .circle-3 {
    opacity: 0.1;
  }
}
</style>

<style scoped>
.home-container {
  min-height: 100vh;
  color: var(--ink);
  background:
    radial-gradient(circle at 50% 0%, rgba(23, 105, 232, 0.08), transparent 36rem),
    var(--canvas);
  overflow: visible;
}

.user-bar {
  position: absolute;
  top: 26px;
  right: max(28px, calc((100vw - 1180px) / 2));
  gap: 10px;
  padding: 5px 5px 5px 8px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: var(--shadow-sm);
  backdrop-filter: none;
}

.user-avatar {
  width: 34px;
  height: 34px;
  color: #1552aa;
  background: #eaf2ff;
  box-shadow: none;
}

.user-nick { color: var(--ink); font-size: 13px; }
.user-name { color: var(--subtle); font-size: 11px; }

.logout-btn {
  color: var(--muted);
  background: #f7f9fc;
  border: 1px solid transparent;
  border-radius: 8px;
  font-size: 12px;
  padding: 7px 11px;
}

.logout-btn:hover {
  color: var(--danger);
  background: #fff2f2;
  border-color: #ffdada;
}

.header {
  width: min(1180px, calc(100% - 48px));
  margin: 0 auto;
  padding: 116px 0 42px;
  text-align: left;
}

.glitch-wrapper { margin: 0 0 18px; }

.glitch-title {
  max-width: 760px;
  margin: 0;
  color: var(--ink);
  font-family: inherit;
  font-size: clamp(2.7rem, 5.4vw, 4.8rem);
  font-weight: 750;
  line-height: 1.08;
  letter-spacing: -0.055em;
  text-shadow: none;
  animation: none;
}

.glitch-title::before,
.glitch-title::after { display: none; }

.subtitle {
  max-width: 680px;
  margin: 0;
  color: var(--muted);
  font-family: inherit;
  font-size: 17px;
  line-height: 1.7;
  letter-spacing: 0.08em;
}

.cyber-line { display: none; }

.apps-container {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
  width: min(1180px, calc(100% - 48px));
  margin: 0 auto 100px;
  padding: 0;
}

.app-card {
  width: auto;
  min-height: 330px;
  align-items: flex-start;
  padding: 36px;
  color: var(--ink);
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 18px;
  box-shadow: var(--shadow-sm);
  transition: transform .22s ease, border-color .22s ease, box-shadow .22s ease;
}

.app-card:first-child { border-top: 3px solid var(--paper); }
.app-card:nth-child(2) { border-top: 3px solid var(--primary); }
.app-card:nth-child(3) { border-top: 3px solid #7c5ce5; }

.app-card:hover {
  transform: translateY(-4px);
  border-color: #c8d5e7;
  box-shadow: var(--shadow-md);
}

.card-glow { display: none; }

.app-icon {
  width: 56px;
  height: 56px;
  margin-bottom: 56px;
  border-radius: 14px;
  box-shadow: none;
}

.app-icon svg {
  width: 27px;
  height: 27px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.paper-icon { color: #087f79; background: #e8f7f5; }
.robot-icon { color: #155ecf; background: #eaf2ff; }
.rag-icon { color: #6543c5; background: #f0ecff; }

.app-info { margin: 0 0 28px; text-align: left; }

.app-title {
  margin-bottom: 10px;
  color: var(--ink);
  font-family: inherit;
  font-size: 24px;
  line-height: 1.3;
  letter-spacing: -0.02em;
  text-shadow: none;
}

.app-desc { max-width: 420px; color: var(--muted); font-size: 15px; line-height: 1.75; }

.app-button {
  padding: 0;
  color: var(--primary);
  background: transparent;
  border: 0;
  border-radius: 0;
  font-size: 14px;
  font-weight: 650;
}

.app-card:first-child .app-button { color: var(--paper); }
.app-card:nth-child(3) .app-button { color: #6543c5; }
.app-button:hover { box-shadow: none; transform: none; }
.app-button::before { display: none; }
.btn-icon { margin-left: 2px; }
.cyber-circles { display: none; }

@media (max-width: 768px) {
  .user-bar { top: 18px; right: 18px; }
  .header { width: min(100% - 36px, 620px); padding: 104px 0 34px; }
  .glitch-title { font-size: clamp(2.35rem, 11vw, 3.6rem); }
  .subtitle { font-size: 14px; letter-spacing: .04em; }
  .apps-container { grid-template-columns: 1fr; width: min(100% - 36px, 620px); margin-bottom: 56px; }
  .app-card { min-height: 270px; padding: 28px; }
  .app-icon { margin-bottom: 36px; }
}

@media (min-width: 769px) {
  .apps-container { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .app-card { min-height: 360px; padding: 30px; }
  .app-icon { margin-bottom: 46px; }
  .app-title { font-size: 21px; }
}

@media (max-width: 480px) {
  .user-meta { display: none; }
  .header { padding-top: 94px; }
  .glitch-title { font-size: 2.2rem; }
  .app-card { min-height: 250px; padding: 24px; }
  .app-title { font-size: 21px; }
}
</style>
