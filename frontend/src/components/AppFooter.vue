<template>
  <footer class="app-footer">
    <div class="footer-content">
      <div class="footer-section">
        <div class="footer-logo">
          <h3>AI 科研问答系统</h3>
        </div>
        <div class="footer-links">
          <a href="#">《用户协议》</a>
          <a href="#">《隐私政策》</a>
        </div>
      </div>
      
      <div class="footer-section">
        <h4>科研资源</h4>
        <div class="footer-links">
          <a href="https://arxiv.org/" target="_blank">arXiv 论文库</a>
          <a href="https://paperswithcode.com/" target="_blank">Papers with Code</a>
          <a href="https://opencv.org/" target="_blank">OpenCV 文档</a>
        </div>
      </div>
      
      <div class="footer-section">
        <h4>联系我们</h4>
        <div class="footer-links">
          <a href="#">商务合作</a>
          <a href="#">技术支持</a>
        </div>
      </div>
    </div>
    
    <div class="footer-bottom">
      <p>© {{ currentYear }} AI 科研问答系统 - 让AI助力计算机视觉研究</p>
    </div>
  </footer>
</template>

<script setup>
import { computed } from 'vue'

// 计算当前年份
const currentYear = computed(() => new Date().getFullYear())
</script>

<style scoped>
.app-footer {
  background-color: #fff;
  padding: 40px 0 20px;
  color: #666;
  border-top: 1px solid #eee;
  width: 100%;
  margin-top: auto;
  position: relative;
  z-index: 2;
}

.footer-content {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  padding: 0 20px;
}

.footer-section {
  flex: 1;
  min-width: 200px;
  margin-bottom: 30px;
  padding: 0 15px;
}

.footer-logo h3 {
  font-size: 1.25rem;
  margin-bottom: 15px;
  color: #333;
}

.footer-section h4 {
  font-size: 1rem;
  margin-bottom: 15px;
  color: #333;
}

.footer-links {
  display: flex;
  flex-direction: column;
}

.footer-links a {
  margin-bottom: 10px;
  color: #666;
  text-decoration: none;
  transition: color 0.2s;
}

.footer-links a:hover {
  color: #007bff;
}

.qrcode {
  display: flex;
  align-items: center;
}

.qrcode-container {
  text-align: center;
}

.qrcode-placeholder {
  width: 90px;
  height: 90px;
  background-color: #f5f5f5;
  margin: 0 auto 10px;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 2rem;
}

.qrcode-placeholder:after {
  content: '🤖';
}

.footer-bottom {
  text-align: center;
  padding-top: 20px;
  margin-top: 20px;
  border-top: 1px solid #eee;
  color: #999;
  font-size: 0.9rem;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .footer-content {
    flex-direction: column;
  }
  
  .footer-section {
    width: 100%;
    margin-bottom: 20px;
    padding: 0;
  }
}

@media (max-width: 480px) {
  .app-footer {
    padding: 30px 0 15px;
  }
  
  .footer-section h4 {
    font-size: 0.95rem;
  }
  
  .footer-links a {
    font-size: 0.9rem;
  }
  
  .qrcode-placeholder {
    width: 80px;
    height: 80px;
  }
}
</style>

<style scoped>
.app-footer {
  padding: 34px 0 18px;
  color: var(--muted);
  background: #fff;
  border-top: 1px solid var(--line);
}
.footer-content {
  max-width: 1180px;
  gap: 48px;
  padding: 0 24px;
}
.footer-section { min-width: 180px; margin-bottom: 20px; padding: 0; }
.footer-logo h3 { margin: 0 0 12px; color: var(--ink); font-size: 15px; letter-spacing: -.01em; }
.footer-section h4 { margin: 0 0 12px; color: #43526a; font-size: 13px; }
.footer-links { gap: 8px; }
.footer-links a { margin: 0; color: var(--muted); font-size: 12px; }
.footer-links a:hover { color: var(--primary); }
.footer-bottom { margin-top: 4px; padding: 18px 24px 0; color: var(--subtle); border-top-color: #edf1f6; font-size: 11px; }
.footer-bottom p { margin: 0; }
@media (max-width: 768px) {
  .app-footer { padding-top: 28px; }
  .footer-content { gap: 0; }
  .footer-section { margin-bottom: 18px; }
}
</style>
