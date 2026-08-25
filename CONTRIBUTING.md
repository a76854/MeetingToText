# 贡献指南

本文件记录本仓库的编码约定与教学阅读顺序。写代码之前通读一遍，改完代码之后回来核实一遍。

---

## 语言与消息规范

**日志一律英文。** `logger.info` / `logger.warning` / `logger.exception` 的消息文本用英文，方便在英文日志平台检索。

**用户可见的校验错误和业务异常用中文。** 用户在浏览器里看到的错误提示（HTTPException detail、前端 toast）写中文，因为目标用户是中文普通话会议参与者。

**已知例外（本轮不改动）：**

| 位置 | 文案语言 | 原因 |
|------|----------|------|
| `deps.py` `_TASK_NOT_FOUND` = `"Task not found"` | 英文 | 资源标识符，API 稳定性要求，多路由共享常量 |
| `record.py` WS 协议诊断帧 `"invalid json"` / `"No audio recorded"` | 英文 | 开发者面向的协议帧，前端 wsRecorderClient.ts 按英文匹配 |
| `audio.py:27` `"音频文件不存在"` | 中文 | **合规范例**：用户可见的 404 提示，符合"用户面向用中文"规则 |

未来若有新的例外，必须在本小节的表格中登记，否则视为违规。

---

## API 响应约定

1. **JSON 端点使用 Pydantic `response_model`**（凡路由函数签名中声明了的地方）。
2. **所有 DELETE 端点返回 `{"status": "ok"}`**，不附带业务标识字段。前端 `client.ts` 的类型签名已与此对齐。
3. **错误通过 `HTTPException(detail=...)` 抛出**，detail 是人类可读的中文消息（见上节）。机器可读的错误码仅出现在 WebSocket 协议帧的 `"code"` 字段（如 `"session_busy"`），不在 REST 层重复。

---

## WebSocket 线协议契约

`/api/record/{task_id}` 端点的每一帧格式、方向、生产者和消费者位置，记录在
`backend/app/services/record_session.py` 模块 docstring 的 `## Wire protocol contract` 小节。

**为什么存在这份契约：** 前端 `frontend/src/services/wsRecorderClient.ts` 消费这些帧。任何帧格式变更必须同时更新契约文档和两端代码，否则前后端会静默不一致。契约文档是唯一的真相来源——不要在别处维护第二份帧列表。

---

## 配置项单一事实源

所有用户可设置的配置项定义在 `backend/app/config.py` 的 `SETTING_SPECS` 字典中。每个条目是一个 `SettingSpec(key, caster, default, sensitive, deletable)` 五元组。

**写入规则：** 修改 settings 单例的代码（settings 路由的 POST/DELETE、startup 加载）必须先获取 `settings_lock`（`config.py` 中的 `threading.RLock`）。

**读取规则：** 读侧不加锁。这是有意为之的契约：写入侧已用 RLock 串行化，Python 的 GIL 保证单次 `getattr` 原子性，读侧无需额外同步。如果未来引入非 GIL 的 Python 运行时，需要重新评估此决策。

**`schemas.py` 保持手写。** `SettingsUpdate` / `SettingsInfo` 的字段不从 `SETTING_SPECS` 自动生成——Pydantic 模型的默认值、描述、验证逻辑与 spec 的 caster/default 是不同关注点，强行生成会引入不必要的耦合。

---

## 教学阅读顺序

推荐给学生和新贡献者的代码阅读路径，按复杂度递增排列：

1. **`frontend/src/utils/*`** — 纯函数工具（日期格式化、剪贴板、下载），零副作用，最简单的入口点。
2. **`backend/app/templates/presets.py`** — 纯数据：会议纪要模板定义，理解"模板"这个核心领域概念。
3. **`backend/app/templates/prompts.py`** — 纯字符串拼装：模板数据如何变成 LLM messages，无 I/O。
4. **`backend/app/models/schemas.py`** — Pydantic 数据模型：TaskInfo、TranscriptSegment 等，全仓库的数据契约。
5. **`frontend/src/api/client.ts`** — 前端 HTTP 层：所有后端调用的唯一出口，理解前后端的接口边界。
6. **`backend/app/services/exporters.py`**（+ `tests/golden/test_export.py`）— 纯函数导出器 + 字节级快照测试，理解"golden test"如何锁定格式不变。
7. **`backend/app/services/recorder.py`** — 录音管理器：active/suspended 两状态 FSM，理解录音会话的生命周期。
8. **`backend/app/routers/transcribe.py`** — 转录路由：SSE 流式响应、任务状态轮询，理解异步流式 API。
9. **`backend/app/services/store.py`** — 任务存储：SQLite CRUD，理解数据持久化层。
10. **`backend/app/services/pipeline.py`** — 转录流水线：VAD → ASR → 说话人分离，理解核心处理链路。
11. **`backend/app/services/asr_parse.py`** — ASR 结果解析：FunASR 输出归一化，理解模型输出的多形状问题。
12. **`backend/app/services/asr_patch.py`** — FunASR vendor patch：理解为什么需要猴子补丁以及上游缺陷。
13. **`backend/app/services/record_session.py`** — 录音会话服务：grace timer、finalize 编排，理解重连策略。
14. **`backend/app/routers/record.py`** — WebSocket 录音端点：帧处理、重连、liveness 检测，最复杂的单文件。

---

## 部署安全要点

### 绑定地址策略

| 场景 | 默认行为 | 说明 |
|------|----------|------|
| `meetingtotext serve`（无 --host） | `127.0.0.1` | 仅本机可达，开发环境安全 (`cli.py:42`) |
| `--host 0.0.0.0` 或 `MTT_HOST=0.0.0.0` | 所有接口 | **仅限容器/局域网部署** |

**0.0.0.0 绑定注意事项：** 暴露到公网前必须配合以下任一措施：防火墙只放行受信 IP、反向代理（nginx/Caddy）前端鉴权、或 VPN/Tailscale 等零信任网络。裸跑 `--host 0.0.0.0` 等于把 FastAPI 无认证接口直接暴露给互联网。

环境变量 `MTT_HOST` 可覆盖默认绑定地址（`cli.py:42`），`MTT_PORT` 覆盖端口（默认 8000，`cli.py:43`）。

### 密钥明文落盘风险

LLM API Key 以**明文**存储在 SQLite `app_settings` 表中（`store.py:29-33`，`value TEXT NOT NULL`）。

**为什么明文：** 本项目是单用户教学应用，不引入 KMS/Vault 等外部密钥管理系统——超出教学范围。加密落盘需要额外依赖和运维复杂度，对"课上跑通"场景收益不高。

**风险：** `data/meetingtotext.db` 文件泄露即暴露 API Key。攻击者可凭此调用 LLM 产生费用。

**已实现的缓解措施：**

| 措施 | 位置 | 说明 |
|------|------|------|
| `MTT_LLM_API_KEY` 环境变量 | `config.py:33` (`env_prefix="MTT_"`) + `:54` | 环境变量优先级高于 DB 存储；客户端启动时自动注入，Key 不经 DB |
| GET `/api/settings` 脱敏 | `routers/settings.py:36` | 返回 `llm_api_key_set` 布尔值，**不返回原始 Key** |
| SettingSpec `sensitive=True` | `config.py:131-132` | 标记为敏感字段，供 UI 层区分展示 |

**运维建议：** 生产部署优先使用 `MTT_LLM_API_KEY` 环境变量而非 Web 界面保存。若必须存 DB，确保 `data/` 目录权限为 `700`（`chmod 700 data/`）。

### 已内置的安全加固清单

以下加固措施已随代码交付（截至 HEAD 3b7ff6a）：

| 加固项 | 提交 | 位置 |
|--------|------|------|
| 上传 Content-Length 预检 + 魔数校验 | `b465261` | `routers/upload.py:71-86`（Content-Length 预检 :71-81；8 字节魔数嗅探 :83-86） |
| 真就绪探针（DB + 磁盘） | `c8190e1` | `routers/health.py:21-70`（DB SELECT 1 :25-32；disk_usage 低于阈值 :35-52 返回 503） |
| argparse CLI 安全默认值 | `cli.py` | 默认 `127.0.0.1:8000`、`reload=False`、`workers=1`、`MTT_HEALTH_MIN_DISK_MB=100` |

**尚未实现（后续 TODO）：** API 限流（rate limiting）、CORS 可配置白名单。这两项会各自带独立提交与文档扩展。
