# AI 科研问答系统前端

面向计算机视觉与深度学习研究的科研问答系统前端，基于 Vue 3 + Vite 开发，包含两个核心应用：

- 📄 **论文精读助手**：逐段精读论文、梳理方法与实验细节（Chain 模式，流式输出）
- 🤖 **CV 科研问答智能体**：面向计算机视觉 / 深度学习的专业问答，支持工具调用（Agent 模式）

## 技术栈

- Vue 3 + Vite
- Vue Router
- Axios
- SSE (Server-Sent Events)

## 运行说明

### 安装依赖

```bash
npm install
```

### 启动开发服务器（端口 3001）

```bash
npm run dev
```

访问 `http://localhost:3001`

### 构建

```bash
npm run build
```

构建产物输出到 `dist/`。

## 后端

前端默认连接本机后端：`http://localhost:8124/api`（开发环境直连；生产构建走同源 `/api`，由 `nginx.conf` 反向代理）。

主要接口：

- `POST /api/auth/register`、`POST /api/auth/login`、`GET /api/auth/userinfo`
- `GET /api/session/list?chat_type=doc|agent`
- `POST /api/session/create`、`PUT /api/session/rename`、`DELETE /api/session/<session_id>`
- `GET /api/session/<session_id>/messages`、`GET /api/session/<session_id>/summary`
- 论文精读助手（Chain 模式）SSE：`GET /api/ai/paper_reader/chat/sse?message=...&session_id=...`
- CV 科研问答智能体（Agent 模式）SSE：`GET /api/ai/cv_agent/chat?message=...&session_id=...`

### SSE 事件协议

```
data: [THINKING]     心跳，忽略
data: [THINK] ...    思考过程
data: [STEP] ...     工具调用
data: [FINAL] ...    最终回答
data: [ERROR] ...    错误信息（红色气泡）
data: [DONE]         结束
```

Chain 模式直接推送原始文本分片（无前缀）。
