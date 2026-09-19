import { createRouter, createWebHistory } from 'vue-router'

const publicRoutes = ['Login', 'Register']

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
    meta: { title: '登录 - AI 科研问答系统' }
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('../views/Register.vue'),
    meta: { title: '注册 - AI 科研问答系统' }
  },
  {
    path: '/paper-reader',
    name: 'PaperSessions',
    component: () => import('../views/SessionList.vue'),
    meta: { title: '论文精读助手 - AI 科研问答系统' }
  },
  {
    path: '/paper-reader/:sessionId',
    name: 'PaperReader',
    component: () => import('../views/PaperReader.vue'),
    meta: { title: '论文精读助手 - AI 科研问答系统' }
  },
  {
    path: '/cv-agent',
    name: 'AgentSessions',
    component: () => import('../views/SessionList.vue'),
    meta: { title: 'CV科研问答智能体 - AI 科研问答系统' }
  },
  {
    path: '/cv-agent/:sessionId',
    name: 'CvAgent',
    component: () => import('../views/CvAgent.vue'),
    meta: { title: 'CV科研问答智能体 - AI 科研问答系统' }
  },
  {
    path: '/rag-documents',
    name: 'RagDocuments',
    component: () => import('../views/RagDocuments.vue'),
    meta: { title: 'RAG 文件管理 - AI 科研问答系统' }
  },
  {
    path: '/',
    name: 'Home',
    component: () => import('../views/Home.vue'),
    meta: {
      title: '首页 - AI 科研问答系统',
      description: 'AI 科研问答系统面向计算机视觉与深度学习研究，提供论文精读助手和CV科研问答智能体服务'
    }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  if (to.meta.title) {
    document.title = to.meta.title
  }
  const token = localStorage.getItem('token')
  if (!publicRoutes.includes(to.name)) {
    if (!token) {
      return next({ name: 'Login', query: { redirect: to.fullPath } })
    }
  } else {
    if (token) {
      return next({ name: 'Home' })
    }
  }
  next()
})

export default router
