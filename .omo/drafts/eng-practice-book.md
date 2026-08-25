---
slug: eng-practice-book
status: awaiting-approval
intent: unclear
review_required: true
plan_path: .omo/plans/eng-practice-book.md
plan_sha256: null
review_round_id: null
pending-action: write and review .omo/plans/eng-practice-book.md
review:
  momus:
    status: pending
    workspace_root: null
    runtime_home: null
    target: .omo/plans/eng-practice-book.md
    round_id: null
    plan_sha256: null
    launch_id: null
    session: null
    result: null
  independent:
    status: pending
    workspace_root: null
    runtime_home: null
    target: .omo/plans/eng-practice-book.md
    round_id: null
    plan_sha256: null
    launch_id: null
    session: null
    result: null
approach: 写一本 d2l 式中文教材《算法编程与工程实践》，以 MeetingToText 项目为贯穿全书的教学主线（增量重建），16 周螺旋式课纲，14 个单元 + 3 个里程碑 Demo。Jupyter Book 构建为可运行的网页版教材。
---

# Draft: eng-practice-book

## Components (topology ledger)
<!-- Lock the SHAPE before depth. One row per top-level component that can succeed or fail independently. -->
<!-- id | outcome (one line) | status: active|deferred | evidence path -->

- C1 课纲与单元设计 | 一份决策完整的 16 周教学大纲（14 单元+3 里程碑），含每单元学习目标/先修/难度/映射到应用功能与工程概念 | active | 本书草稿 ## Decisions
- C2 著书基础设施 | Git 仓库 + Jupyter Book 构建链 + CI（构建网页/PDF、执行笔记本校验），可一键重建全书 | active | d2l 先例（librarian 报告 §1）
- C3 教学参考实现 | 可运行、按章节增量重建的 MeetingToText 教学版 + 精简 helper 库（`m2t` 教学包，对应 d2l 的 `d2l` 包） | active | 现仓库 backend/ frontend/ 为"完整参考实现"
- C4 章节内容撰写 | 每单元：动机→概念→最简可运行代码→"改动并预测"实验，文字/代码交错 | active | d2l 原则 1/2/3
- C5 习题与评测 | 每单元习题 + 3 个里程碑项目 + 自动评测（含"跑学生测试打击 buggy 实现"）+ 代码评审 | active | 6.031 PS1 / CS110L 项目
- C6 教学交付物 | 每单元论坛主题、课件、教师指南、AI 使用政策 | active | d2l/Discourse 模式

## Open assumptions (announced defaults)
<!-- Intent is UNCLEAR: research resolves ambiguity, defaults are adopted (not asked), and each is surfaced in the plan's human TL;DR for veto. -->
<!-- assumption | adopted default | rationale | reversible? -->

- 教材语言 | 中文 | 授课对象为中国本科一二年级；d2l 中文版先例 | 是
- 教学内容载体 | 一本可运行的在线教材（Markdown/Jupyter 笔记 + Jupyter Book/Sphinx 构建成 HTML/PDF） | d2l 本体即"每节一个可执行 notebook"，避免文字与代码漂移 | 是（可换 Quarto/MyST）
- 课纲结构 | 16 周螺旋式：概念只在应用需要时引入，应用从第 1 周即可运行 | d2l 螺旋 + CS110L 里程碑 皆印证"尽早跑起来"对新手动机最关键 | 是
- 贯穿实例 | 增量重建 MeetingToText（而非直接讲授完整现仓库） | "learn by building" 优于"读成品代码"；现仓库作为完整参考实现 | 是
- 目标读者前置知识 | 已学 C/Python 基础 + 数据结构，未接触工程化/框架 | 用户明确说明 | 否（用户给定）
- 评测方式 | 自动评测 + 人工代码评审 + 里程碑 Demo（不设笔试） | CS110L 弃笔试改项目；6.031 用"跑学生测试打击 buggy 实现"验测试质量 | 是
- 习题风格 | d2l"改动并预测"实验 + Crafting Interpreters"挑战"（开放式延伸） | 双先例一致指向"可控折腾出直觉" | 是
- 精简 helper 库 | 提供 `m2t` 教学工具包隐藏样板代码 | d2l 的 `d2l` 包 / `#@save` 模式 | 是

## Findings (cited - path:lines)

- 项目为全栈应用：FastAPI+SSE+WebSocket 后端，Vue3+Vite+TS 前端，ASR(FunASR/SenseVoice)+LLM(OpenAI 兼容) 集成。README.md:12-20
- 并发：单工作线程 ThreadPoolExecutor + Future 跟踪 + 协作式取消。backend/app/services/pipeline.py:42-74
- 安全范例：路径穿越防御 backend/app/server.py:85-99；XSS 消毒（DOMPurify）frontend/src/utils/sanitize.ts:1-13
- 健壮性：音频质量校验（时长/削波/静音）+ 重采样回退。backend/app/services/pipeline.py:171-213
- 已有 10 个测试文件（含并发、路径穿越、重连、流式）。tests/ 目录
- 打包：pyproject.toml（setuptools，dev 依赖 pytest/httpx）。pyproject.toml:26-42
- 教学法依据（librarian 报告，公网来源）：d2l 原则 8 条；MIT Missing Semester / Stanford CS110L / MIT 6.031 / Software Design by Example / Crafting Interpreters / OSSU / TeachYourselfCS 对比；哈工大《软件构造》本地化 6.031 先例。
- eng-tooling-deploy 计划已落地工程配套：Makefile/ruff+mypy/eslint+vitest/四层测试/CLI 守护进程/日志轮转/docker 两容器+CI/安全加固（见 .omo/plans/eng-tooling-deploy.md Success criteria 全绿记录）

## Decisions (with rationale)

**核心决策：16 周课纲（14 单元 + 3 里程碑 Demo），螺旋围绕 MeetingToText 增量重建。**

| 周 | 单元 | 工程概念 | 应用落点 |
|---|---|---|---|
| 1 | 工程环境与项目骨架 | venv/npm、仓库结构、一键跑通 | 运行教学版骨架；不引入 Python 锁文件——教 npm/uv/miniforge 等环境管理工具安装，拿到任何项目都能跑起来 |
| 2 | Shell 与脚本自动化 | 管道/重定向/find/grep/awk | 批量处理音频文件 |
| 3 | Git 与协作工作流 | 提交/分支/PR/冲突 | 首次特性分支；主线教协作工作流，git hooks 记选学附录、不预置 |
| 4 | 代码质量：类型与静态检查 | 类型标注/ruff/格式化/评审 | 重构 upload 模块 |
| 5 | 测试的思维与工程 | pytest/参数化/覆盖/测试先行 | 测转写解析器 |
| 6 | **里程碑 M1：CLI 转写工具** | 集成 1-5 | 演示+评审 |
| 7 | HTTP 与 REST API | 路由/校验/状态码/OpenAPI | 暴露 /transcribe |
| 8 | 数据持久化与 SQL | SQLite/表设计/事务 | 存储会议与设置 |
| 9 | 调试与性能剖析 | 断点/日志/profiler | 定位真实热点 |
| 10 | 并发与异步 | asyncio/线程池/竞态/任务队列 | 后台转写任务 |
| 11 | **里程碑 M2：可用 Web API** | 集成 7-10 | 演示+评审 |
| 12 | 前端基础：Vue3 | 组件/状态/fetch | 消费 API 的页面 |
| 13 | 外部服务集成：ASR+LLM | key 管理/超时重试/流式/mock | 纪要生成 |
| 14 | 打包、部署与 CI | Docker/推送即测/发布 | 一键部署；参考成品已具备 docker/ 两容器（后端 CPU-only torch + nginx 反代）+ GitHub Actions CI + 根目录 Makefile |
| 15 | 健壮性与安全基础 | 校验/token/密钥/限流/穿越/XSS | 加固全应用；参考成品已内置限流/上传魔数校验/CORS 白名单/真健康探针/LLM 超时重试脱敏，认证授权留作学生作业 |
| 16 | **里程碑 M3 + 答辩复盘** | 文档/README/复盘论文 | Demo 日 |

依据：d2l"压缩前置-螺旋上升"（§1 原则 8）；CS110L 弃笔试改项目里程碑；6.031 测试先行 + PS1 验测试质量。详见 librarian 报告 §4 Skeleton A。

## Scope IN

- 一本中文在线教材（可运行），14 单元 + 3 里程碑
- 教学参考实现（增量重建的 MeetingToText + `m2t` 教学包）
- 每周习题 + 3 个里程碑项目 + 自动评测脚手架
- 著书基建（Git 仓库 + Jupyter Book 构建 + CI）
- 教学交付物（论坛主题/课件/教师指南/AI 政策）
- 每单元均可运行验证（全书构建即测试）

## Scope OUT (Must NOT have)

- 不改动现有 MeetingToText 生产代码（作为参考实现，只读引用）
- 不编写大规模新算法/ML 理论（学生只有数据结构基础；算法只在应用需要处点到为止）
- 不做视频课/慕课平台托管（不在本次请求内）
- 不开发新的评测平台/自研判题系统（复用 pytest + CI + 代码评审）
- 不撰写英文版/印刷出版流程（在线版优先，出版为后续可选项）

## Open questions

（无——UNCLEAR 路线下已全部以最佳实践默认值填平，用户可在审批环节逐条否决。）

## Approval gate
status: awaiting-approval
<!-- When exploration is exhausted and unknowns are answered, set status: awaiting-approval. -->
<!-- That durable record is the loop guard: on a later turn read it and resume at the gate instead of re-running exploration. -->