# MeetingToText

会议录音转写与纪要生成系统 —— 中文普通话会议（中英混合），CPU 环境运行。

## 功能

- **语音转文字**：支持上传音频文件或浏览器实时录音
- **说话人分离**：FunASR 内置 CAM++ 模型，无需外部依赖
- **会议纪要生成**：基于 LLM API 生成结构化会议纪要
- **多种模板**：标准会议纪要、行动计划、简要纪要

## 技术栈

| 层 | 技术 |
|---|---|
| ASR + 说话人分离 | FunASR (SenseVoice + CAM++) |
| 纪要生成 | OpenAI 兼容 API（DeepSeek / OpenAI / Ollama 等） |
| 后端 | FastAPI + SSE + WebSocket |
| 前端 | Vue 3 + Vite + TypeScript + Pinia |

## 快速开始

### 1. 安装后端依赖

```bash
pip install -e .
```

### 2. 安装前端依赖

```bash
cd frontend && npm install && cd ..
```

### 3. 配置

```bash
cp .env.example .env
vim .env   # 填入 LLM API Key
```

### 4. 启动

```bash
cd frontend && npm run build && cd ..
python main.py
# 访问 http://localhost:8000
```

开发模式（前端热更新）：

```bash
# 终端 1 - 后端
python main.py

# 终端 2 - 前端
cd frontend && npm run dev
# 访问 http://localhost:5173
```

## 使用流程

1. **上传文件**：拖拽或选择音频文件（WAV/MP3/M4A/FLAC/OGG 等）
2. **实时录音**：使用浏览器麦克风录制会议
3. **自动转写**：系统自动执行 VAD → ASR + 说话人分离
4. **校对转录**：查看带说话人标签的转写结果
5. **生成纪要**：选择模板 → LLM 生成会议纪要

## 配置项

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `MTT_LLM_BASE_URL` | `https://api.deepseek.com` | LLM API 地址 |
| `MTT_LLM_API_KEY` | - | API Key |
| `MTT_LLM_MODEL` | `deepseek-chat` | 模型名称 |
| `MTT_ASR_MODEL_TYPE` | `sensevoice` | ASR 引擎：`sensevoice` / `paraformer` |
