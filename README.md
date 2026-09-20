# AI 科研问答系统

> 面向**计算机视觉（CV）与深度学习（DL）研究**的科研问答系统。

## 一、系统概览

系统提供两种对话模式：

| 模式 | 功能 | 技术实现 |
| :--- | :--- | :--- |
| **Chain 模式** | **论文精读助手** | LangChain LCEL 链式调用，轻量、逐 token 流式输出 |
| **Agent 模式** | **CV 科研问答智能体** | ReAct Agent + 工具调用 + RAG + Skills + MCP |

- **论文精读助手**：概念讲解、公式推导、段落翻译、方法梳理、审稿视角点评。适合「读懂一篇论文」的场景。
- **CV 科研问答智能体**：会自己查资料、调工具、按流程办事。支持方法选型、实验设计、方法对比矩阵、投稿前自审，并可直接检索 arXiv / Semantic Scholar。

## 二、技术栈

| 层级 | 技术 | 用途 |
| :--- | :--- | :--- |
| 后端框架 | Flask 3.1.3 | Web 服务、蓝图路由、SSE 流式响应 |
| AI 框架 | LangChain 0.3.28 | LLM 调用、ReAct Agent、LCEL 链、Prompt 管理 |
| LLM | DeepSeek Chat（OpenAI 兼容接口） | 底层大语言模型 |
| 数据库 | MySQL 8.4 + PyMySQL | 用户、会话、消息、摘要持久化 |
| 向量数据库 | ChromaDB 1.5.9 + BGE embedding | RAG 语义检索 |
| 关键词检索 | BM25（rank-bm25） | RAG 多路召回的关键词分支（中文 bigram 分词） |
| 重排序 | BGE Reranker（Cross-Encoder） | RAG 融合后的精排 |
| MCP 服务端 | FastMCP（streamable-http） | 学术论文检索工具服务 |
| 身份认证 | JWT（PyJWT，HS256） | Token 鉴权 |
| 密码加密 | Werkzeug security | 密码哈希存储 |
| 前端 | Vue 3 + Vue Router + Vite | 单页应用 |
| 前端通信 | Axios + 原生 EventSource | REST 请求 + SSE 流式对话 |

## 三、核心技术实现

### 1. 双引擎：Chain 与 Agent

```
Chain 模式（论文精读助手）
  GET /api/ai/paper_reader/chat/sse
    → build_context(session_id)                    取摘要 + 最近 50 条消息
    → save_message(session_id,"user",message)      先落库用户消息
    → make_chain(SYSTEM_PROMPT, context)           ChatPromptTemplate | llm | StrOutputParser
    → sse_response(stream_chain, ...)              逐 token 出流
    → 流结束后保存 assistant 消息 + 触发摘要

Agent 模式（CV 科研问答智能体）
  GET /api/ai/cv_agent/chat
    → build_context + save_message
    → 装配工具：get_time / calc / gpu_status / cv_rag_search
                / search_arxiv / search_semantic_scholar
                / list_skills / read_skill
    → create_react_agent + AgentExecutor
    → stream_agent 逐步产出 [THINK] / [STEP] / [FINAL]
```

ReAct 配置为：`max_iterations=15`、`max_execution_time=90s`、
`handle_parsing_errors=True`、`early_stopping_method="generate"`。

### 2. SSE 事件协议（前后端契约）

```
data: [THINKING]                    首帧心跳，防止前端超时
data: [THINK] 思考内容               Agent 的推理过程
data: [STEP] 工具: X 输入: Y 结果: Z  工具调用与观察结果
data: [FINAL] 最终答案               最终回复
data: [ERROR] 异常信息               标准化异常事件
data: [DONE]                        流结束
```

> 注意：`[STEP]`/`[FINAL]` 的内容可能包含换行（Markdown 表格），后端会拆成多条 `data:` 行，
> 浏览器 `EventSource` 会自动拼回一个事件。**用 Python 手写 SSE 客户端时必须按空行分帧**，
> 否则长回答会被截断（`tests/sse_client.py` 已按规范实现）。

### 3. RAG：双路召回 + 加权 RRF + 重排序

```
用户查询
  → 向量检索 (Chroma + BAAI/bge-small-zh-v1.5)  top-10
  → BM25 关键词检索（中文 bigram 分词）           top-10
  → 动态加权 RRF 融合（短查询 BM25 权重 0.6，长查询向量 0.7）
  → Cross-Encoder 精排 (BAAI/bge-reranker-base)   取 top-5
  → 输出 top-3 参考片段
```

**知识库文档（5 篇，共 48 个片段）**

| 文件 | 覆盖内容 |
| :--- | :--- |
| `cnn.md` | 卷积原理、感受野公式、池化、ResNet/DenseNet/EfficientNet、归一化层、工程排查 |
| `transformer.md` | Self-Attention、位置编码、ViT/DeiT/Swin/PVT/ConvNeXt、选型建议 |
| `detection.md` | 两阶段/单阶段/Anchor-free/DETR、Focal Loss、标签分配、损失演进、NMS、mAP/mAP50-95 |
| `segmentation.md` | 语义/实例/全景分割、U-Net、Mask R-CNN、SAM、分割损失、mIoU/Dice/PQ |
| `training_tricks.md` | 优化器、学习率调度、数据增强、正则化、显存优化、迁移学习、消融实验规范、排查清单 |

**检索实现特点**：
1. **中文分词**：采用「中文 bigram + 英文词」分词，避免按空格切分中文时整句成为单个 token。
2. **索引指纹**：`chroma_db/lsb_index_meta.json` 记录 documents 的指纹，
   文档没变就复用磁盘上的向量库，不必每次启动重算 embedding。

### 3.1 RAG 文件管理（前端 `/rag-documents` 页面）

知识库文档可以在页面上直接维护，**一次解析 → 两次保存**：

```
上传/新建文件
   → 解析（.md/.txt 直接读；.pdf 用 pypdf；.docx 用 python-docx）
   → 切分
   ├─ ① ChromaDB : 切片向量（负责语义检索）
   └─ ② MySQL    : rag_documents 元信息 + rag_chunks 切片原文（负责管理界面与重建）
```

删除时反向执行：先从 Chroma 精确摘除该文档的全部向量，再删 MySQL 记录（切片级联删除），
两步都成功才返回，保证「前端显示删除成功」与「两处存储」始终一致。

| 接口 | 说明 |
| :--- | :--- |
| `GET /api/rag/documents` | 列表（含 `chunk_count` / `status` / `updated_at`） |
| `POST /api/rag/documents` | 新建或覆盖（同名即覆盖并重新索引） |
| `POST /api/rag/documents/upload` | 上传文件（multipart `file`） |
| `GET /api/rag/documents/<name>` | 全文 |
| `GET /api/rag/documents/<name>/chunks` | 切片明细（含章节与来源） |
| `DELETE /api/rag/documents/<name>` | 删除 |
| `POST /api/rag/documents/<name>/refresh` | 按 MySQL 原文重建单个文档 |
| `POST /api/rag/rebuild` | 全量重建 |
| `GET /api/rag/status` | 一致性自检（两边文档集合差异） |

**两张新表**

| 表 | 作用 |
| :--- | :--- |
| `rag_documents` | 文档级：名称/标题/格式/大小/切片数/全文/内容哈希/状态/失败原因 |
| `rag_chunks` | 切片级：所属文档/序号/正文/来源/章节（外键级联删除） |

**关键设计**

- **增量而非全量**：上传/删除只动该文档的切片。全量重建要重算全部 embedding，
  在管理页面上每传一个文件就重建一次是不可接受的。
- **索引标记**：集合里存一条 `__index_meta__` 记录（embedding 模型 + 切片数）。
  进程重启时若标记有效，只从 MySQL 把切片正文载回内存并重建 BM25，
  **不重算向量**，启动几乎瞬时完成。
- **不删集合**：索引有效时绝不调用 `delete_collection()`。Flask debug 重载会起两个进程，
  其中一个删集合会让另一个进程手里的句柄失效（曾导致 `Collection [...] does not exist`）。
  为此 `run.py` 默认**关闭自动重载**，需要时设 `FLASK_USE_RELOADER=1`。
- **不留幽灵记录**：格式不支持或解析失败的文件不会写入 `rag_documents`，
  否则列表里会出现一个永远没有切片的文档，也让一致性检查永远失败。
- **文件名安全**：所有 `name` 都过 `normalize_name()`（去路径分隔符），防止目录穿越。

### 4. Skills：渐进式技能模板

Agent 先用 `list_skills` 查看有哪些技能，再用 `read_skill` 拉取完整指令，然后按指令执行。
当用户请求「模糊、复杂、需要多步骤结构化产出」时自动触发，无需特殊命令。

| 技能 | 触发场景 | 产出 |
| :--- | :--- | :--- |
| `paper_digest` | 「帮我精读这篇论文」 | 六段式报告：研究问题/核心方法/关键公式/实验设置/结论与局限/可复现要点 |
| `experiment_plan` | 「消融实验怎么设计」 | 七节方案：任务与指标/数据/基线/主实验/消融/算力预算/风险备选 |
| `method_compare` | 「A 和 B 哪个好」 | 8 列 Markdown 对比矩阵 + 分场景选型结论 + 对比争议点 |
| `paper_review` | 「这篇论文能中吗」 | 模拟审稿人：录用倾向/分项评级/主要质疑/次要问题/修改建议 |

### 5. MCP：学术论文检索服务

独立进程，基于 FastMCP 的 `streamable-http` 传输，监听 `http://127.0.0.1:8001/mcp`。

| 工具 | 数据源 | 返回 |
| :--- | :--- | :--- |
| `search_arxiv` | arXiv 官方 Atom API | 标题/作者/发布日期/摘要/arXiv ID/PDF 链接/分类 |
| `search_semantic_scholar` | Semantic Scholar Graph API | 标题/年份/会议/引用数/作者/摘要/链接 |

**实现要点**：
- arXiv 检索用 `httpx` + 标准库 `xml.etree` 直接解析 Atom，**不依赖第三方 `arxiv` 包**。
- Semantic Scholar 未配置 API Key 时限流很严（HTTP 429），此时返回可读提示并建议改用 `search_arxiv`，
  不会让 Agent 崩掉。配置 `SEMANTIC_SCHOLAR_API_KEY` 可提升额度。
- MCP 不可用时，Agent 会跳过这两个工具正常运行（降级保护），并在 30 秒后允许自动重连。

> **关于 ReAct 与 MCP 的兼容性（本项目踩到的坑）**
> ReAct 的 `Action Input` 只能是**字符串**，而 MCP 工具的 `args_schema` 是多参数 JSON Schema，
> 直接接入会报：
> `String tool inputs are not allowed when using tools with JSON schema args_schema.`
> 系统在 `app/llm/mcp_tools.py` 中把每个 MCP 工具**降维成单字符串输入**工具：
> description 中说明参数格式，调用时再把字符串解析回参数字典，两种写法都支持：
> - 纯查询词：`3D gaussian splatting`
> - JSON：`{"query": "3D gaussian splatting", "max_results": 3}`

### 6. 工具清单（Agent 模式共 8 个）

| 组 | 工具 | 作用 |
| :--- | :--- | :--- |
| 1 | `get_time` | 当前日期时间 |
| 2 | `calc` | 受限 AST 数学求值（参数量、FLOPs、显存换算） |
| 3 | `gpu_status` | 本机 GPU 型号 / 显存 / 利用率 |
| 4 | `cv_rag_search` | 检索本地 CV/DL 知识库 |
| 5 | `search_arxiv` | arXiv 论文检索（MCP） |
| 6 | `search_semantic_scholar` | Semantic Scholar 检索（MCP） |
| 7 | `list_skills` / `read_skill` | 渐进式技能路由 |

`gpu_status` 优先用 `pynvml` 读取，未安装时**自动回退到解析 `nvidia-smi`**，
因此只要有 NVIDIA 驱动就零依赖可用。

> 每组工具的**实测可触发提问**见 `工具清单与测试用例.md`；
> 批量验证脚本为 `test_tools.py`（实测 17/17 用例成功触发）。

### 7. 多轮对话与持久化记忆

- **持久化**：`sessions` / `chat_messages` / `chat_summaries` 三张表存 MySQL。
- **摘要压缩**：每 5 轮对话，或累计字符数估算 token 超过 4000 时，自动调用 LLM 更新摘要
  （科研语境提示词，保留研究方向、核心问题、已给结论、未决问题，术语保留英文）。
- **上下文构建**：`【对话摘要】 + 【最近 50 条消息】`，既保留长期记忆又控制窗口长度。
- **自动命名**：会话标题按首条用户消息自动生成，同时支持手动改名。

## 四、项目结构

```
lsb-ai-agent/
├── 开发计划.md                     分阶段开发计划
├── README.md                       本文档
├── 部署说明.md                     启动、配置与排错
│
├── backend/           后端 Flask 应用
│   ├── app/
│   │   ├── __init__.py             Flask 应用工厂 + 请求日志中间件 + 全局错误处理
│   │   ├── config.py               全局配置（从 .env 读取）
│   │   ├── logging_conf.py         日志系统（分级/双通道/链路追踪/脱敏）
│   │   ├── auth.py                 JWT + Redis 认证（注册/登录/退出/鉴权）
│   │   ├── redis_store.py          Redis 连接池与登录会话存储
│   │   ├── chat_history.py         会话/消息/摘要 + 上下文构建
│   │   ├── rag_store.py            RAG 文档元数据与切片（MySQL 侧）
│   │   ├── rag_manager.py          RAG 编排：多格式解析 + 双写 + 启动同步
│   │   ├── llm/
│   │   │   ├── __init__.py         共享 ChatOpenAI 实例
│   │   │   ├── chain.py            论文精读助手（LCEL 链）
│   │   │   ├── agent.py            ReAct Agent + 工具 + 流式执行
│   │   │   ├── rag.py              RAG 引擎 + cv_rag_search 工具
│   │   │   ├── skill_middleware.py Skills 渐进式技能中间件
│   │   │   └── mcp_tools.py        MCP 工具适配器（异步→同步 + 单字符串输入）
│   │   ├── routes/
│   │   │   ├── paper_reader.py     /api/ai/paper_reader/chat/sse
│   │   │   ├── cv_agent.py         /api/ai/cv_agent/chat
│   │   │   ├── rag.py              RAG 文件管理（9 个接口）
│   │   │   └── session.py          会话 CRUD
│   │   └── utils/
│   │       ├── sse.py              SSE 响应封装
│   │       └── console.py          Windows 控制台 UTF-8 兼容
│   ├── documents/                   RAG 知识库（初始 5 篇，可在页面维护）
│   ├── skills/                      Skills 技能模板（4 个）
│   ├── tests/                       分阶段验证脚本
│   ├── logs/                        运行日志（backend.log / error.log，自动生成）
│   ├── chroma_db/                   向量库持久化（自动生成）
│   ├── .env / .env.example          环境变量
│   ├── requirements.txt
│   └── run.py                       启动入口（端口 8124）
│
├── frontend/          Vue3 前端（端口 3001）
│   └── src/{api,router,components,views}/
│
└── mcp_server/                 MCP 学术检索服务（端口 8001）
    ├── server.py                   FastMCP 服务端
    ├── mcp_helper.py               stdio 调试客户端
    └── requirements.txt
```

## 五、快速开始

```powershell
# 1. 数据库与 Redis
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS lsb_agent_db DEFAULT CHARSET utf8mb4 COLLATE utf8mb4_unicode_ci;"
# 请同时确保 Redis 已监听 127.0.0.1:6379

# 2. 后端
cd backend
Copy-Item .env.example .env      # 然后填写 DEEPSEEK_API_KEY 与 MySQL 密码
python run.py                    # http://localhost:8124

# 3. MCP 学术检索服务（另开一个终端）
cd mcp_server
python server.py                 # http://127.0.0.1:8001/mcp

# 4. 前端（再开一个终端）
cd frontend
npm install
npm run dev                      # http://localhost:3001
```

环境要求：**Python 3.11**（langchain 0.3.x 不支持 3.13+）、MySQL 8.x、Redis 6+、Node 18+。
依赖安装与虚拟环境细节见 `部署说明.md`。

## 六、日志系统

统一使用 `app/logging_conf.py`，**不再使用 `print()`**（仅保留命令行自检脚本的输出）。

### 六个等级

在标准四级之上增加了 `SUCCESS`，用来把「成功事件」从 INFO 噪音里拎出来。

| 等级 | 数值 | 用于 |
| :--- | :--- | :--- |
| `DEBUG` | 10 | 检索细节、双路召回条数、工具入参、MCP 参数解析、SQL 级信息 |
| `INFO` | 20 | 正常流程节点：请求完成、会话创建、文档列表查询、模型加载 |
| `SUCCESS` | 25 | 成功且值得记录：登录成功、文档入库、检索命中、启动就绪 |
| `WARNING` | 30 | 可恢复降级：鉴权失败、MCP 未启动、Semantic Scholar 限流、重排序不可用 |
| `ERROR` | 40 | 操作失败：解析失败、LLM 调用异常、未捕获异常（带堆栈） |
| `CRITICAL` | 50 | 进程级问题：数据库不可用、配置缺失、端口被占用 |

### 双通道输出

| 通道 | 位置 | 等级 | 格式 |
| :--- | :--- | :--- | :--- |
| 控制台 | stdout，彩色 | 由 `LOG_LEVEL` 决定（默认 INFO） | `时间 等级 request_id 模块 \| 消息 (上下文)` |
| 全量文件 | `logs/backend.log`，按天切分保留 14 天 | DEBUG 及以上 | 完整时间戳 + 文件:行号 |
| 错误文件 | `logs/error.log`，按天切分保留 30 天 | **WARNING 及以上** | 同上，体量小便于快速定位 |

### 请求链路追踪

每个请求自动分配短 ID（如 `r0062949`），并贯穿该请求产生的全部日志——
包括 SSE 流式阶段（生成器在响应返回后才消费，代码里显式传递了该 ID）。

```
17:51:13.080 DEBUG   [r0062949] app:108          | → GET /api/ai/paper_reader/chat/sse 参数=message='用一句话解释池化'
17:51:13.081 INFO    [r0062949] routes.paper_reader:45 | 论文精读（单轮，无会话历史）: 问题='用一句话解释池化'
17:51:13.081 SUCCESS [r0062949] app:66           | ← GET /api/ai/paper_reader/chat/sse 200 流式响应已建立 (1ms)
17:51:13.082 DEBUG   [r0062949] llm.chain:88     | Chain 调用开始: session=(无) 问题='用一句话解释池化'
17:51:14.216 SUCCESS [r0062949] llm.chain:66     | Chain 生成完成: 输出=148 字 耗时=1.1s 速率=130 字/秒
17:51:14.216 INFO    [r0062949] utils.sse:59     | SSE 流结束: 共 68 个数据块，耗时 1.1s
```

登录后还会自动把 `user=xxx` 并入上下文，会话相关操作带上 `session=xxx`。

### 敏感信息保护

- **密码/token 一律掩码**，日志里只会出现 `password=***`
- **API Key 掩码**：`sk-826badae...f4c` → `sk-826...3f4c`
- **不记录正文**：用户提问只记前 40 字 + 总长度，文档内容只记字数
- **压制 OpenAI SDK 的请求体转储**：该库在 DEBUG 下会打印完整 prompt（含系统提示词与用户消息），
  已把 `openai` / `openai._base_client` 抬到 WARNING
- 第三方噪音库统一降噪：httpx / httpcore / chromadb / transformers / werkzeug / mcp 等

### 配置

```ini
LOG_LEVEL=INFO          # 控制台等级；排查问题时改 DEBUG
LOG_TO_FILE=1           # 是否写日志文件
LOG_DIR=                # 留空则用 backend/logs
LOG_REQUEST_BODY=1      # 是否记录请求参数摘要
```

### 验证

```powershell
python tests/verify_logging.py    # 24 项：等级/双通道/链路/脱敏/防泄露
```

## 七、API 清单
| 方法 | 路径 | 鉴权 | 说明 |
| :--- | :--- | :--- | :--- |
| GET | `/api/health` | — | 健康检查，返回系统名与模式 |
| POST | `/api/auth/register` | — | 注册 |
| POST | `/api/auth/login` | — | 登录，返回 JWT |
| POST | `/api/auth/logout` | ✅ | 退出当前设备并撤销 Redis 会话 |
| GET | `/api/auth/verify` | ✅ | 校验 Token |
| GET | `/api/auth/userinfo` | ✅ | 当前用户信息 |
| GET | `/api/session/list?chat_type=doc\|agent` | ✅ | 会话列表 |
| POST | `/api/session/create` | ✅ | 新建会话 |
| PUT | `/api/session/rename` | ✅ | 重命名会话 |
| DELETE | `/api/session/<id>` | ✅ | 删除会话 |
| GET | `/api/session/<id>/messages` | ✅ | 会话消息（历史回显） |
| GET | `/api/session/<id>/summary` | ✅ | 会话当前摘要（调试） |
| GET | `/api/ai/paper_reader/chat/sse` | — | Chain 模式流式对话 |
| GET | `/api/ai/cv_agent/chat` | — | Agent 模式流式对话 |
| GET | `/api/rag/documents` | ✅ | RAG 文档列表 |
| POST | `/api/rag/documents` | ✅ | 新建/覆盖文档（JSON）并索引 |
| POST | `/api/rag/documents/upload` | ✅ | 上传文件（multipart，字段名 `file`）并索引 |
| GET | `/api/rag/documents/<name>` | ✅ | 单个文档（含全文） |
| GET | `/api/rag/documents/<name>/chunks` | ✅ | 文档切片明细 |
| DELETE | `/api/rag/documents/<name>` | ✅ | 删除文档（向量库 + MySQL 同步清除） |
| POST | `/api/rag/documents/<name>/refresh` | ✅ | 按 MySQL 原文重建该文档索引 |
| POST | `/api/rag/rebuild` | ✅ | 全量重建整个向量库 |
| GET | `/api/rag/status` | ✅ | 知识库一致性自检 |

### JWT + Redis 登录态

登录成功后，后端签发带 `jti`（唯一会话 ID）的 JWT，同时写入一个 Redis 键：

```text
lsb:auth:token:<jti> -> user_id    TTL = JWT 剩余有效期
```

客户端后续仍通过 `Authorization: Bearer <JWT>` 访问。鉴权先验证 JWT 的签名和过期时间，
再确认 Redis 中的会话键存在且属于同一用户；任一项失败均拒绝访问。退出登录删除当前
`jti` 对应的键，因此该 JWT 会立即失效，其他设备的独立会话不受影响。Redis 只保存
随机会话 ID 和用户 ID，不保存完整 JWT；键到期后由 Redis 自动清理。

这是一次不兼容的登录态升级：部署后，旧版未携带 `jti`、也未登记到 Redis 的 JWT
会返回 401，用户重新登录一次即可。

## 八、分阶段验证脚本

`backend/tests/` 下每个阶段都有独立验证脚本，可重复运行：

| 脚本 | 验证内容 |
| :--- | :--- |
| `verify_stage2.py` | Chain 逐 token 流式 + Agent 工具调用 + 消息落库 + 错误路径 |
| `verify_stage3.py` | 5 轮对话触发自动摘要 + 第 6 轮记忆回溯 |
| `verify_stage4.py` | 8 个检索用例命中率 + 索引复用 + 重排序加载 |
| `verify_stage5.py` | 4 个技能被发现 + 技能自动路由 + 对比表格产出 + 落库完整性 |
| `verify_stage6.py` | MCP 连通 + 工具加载 + 真实论文返回 + Agent 端到端调用 |
| `verify_rag_manage.py` | RAG 文件管理：列表/新建/上传(.md/.txt/.docx/.pdf)/覆盖/删除/一致性/重建/鉴权（36 项） |
| `verify_logging.py` | 日志系统：六个等级/双通道/链路追踪/脱敏/防提示词泄露（24 项） |
| `sse_client.py` | 严格按 SSE 规范分帧的客户端（其他脚本共用） |

运行方式（需后端与 MCP 服务端已启动）：

```powershell
cd backend
$env:PYTHONIOENCODING='utf-8'
python tests/verify_stage4.py
```

## 九、许可

仅用于学习与研究。
