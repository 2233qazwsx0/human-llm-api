# 🧠 Human LLM API

> 让你自己变成一个可被调用的API！好友通过HTTP请求向你发送提醒，服务收到后通知你，你还可以回复。

## ✨ 功能特性

- 🎯 **OpenAI兼容接口** - 使用 `/v1/chat/completions` 格式，支持流式和非流式
- 📱 **系统通知** - 收到消息后自动发送系统通知（Linux/macOS/Windows）
- 💬 **实时回复** - 好友发送消息后可以等待你回复，最长120秒
- 🎮 **趣味Token计费** - 不使用真实货币，用"听力token""行动token"等趣味单位
- 📦 **包月套餐** - 每月20 token无限提醒
- 🌐 **内置隧道** - 自动建立Cloudflare隧道，公网可访问
- 🎨 **Web管理面板** - 查看好友余额、消息记录、直接回复

## 🚀 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动服务

```bash
python human_llm_api.py
```

启动后会自动尝试建立Cloudflare隧道，输出示例：

```
🚀 服务启动中... http://0.0.0.0:8000
📖 管理面板: http://localhost:8000/admin
🌐 Cloudflare 隧道已建立!
📡 公网地址: https://xxxx.trycloudflare.com
```

### 手动安装 Cloudflare 隧道（可选）

如果自动隧道失败，可手动安装：

```bash
# Linux
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared
chmod +x /usr/local/bin/cloudflared

# macOS
brew install cloudflared
```

## 📖 API文档

### 1. OpenAI 兼容接口（推荐）

```bash
curl -X POST http://YOUR_HOST/v1/chat/completions \
  -H "Authorization: Bearer sk-friend-alice-2024" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "human-v1",
    "messages": [{"role": "user", "content": "记得喝水！"}],
    "priority": 1
  }'
```

**参数说明：**
- `model`: 模型选择
  - `human-v1` - 标准模式
  - `human-caffeinated-v2` - 咖啡因模式 ☕
  - `human-sleepy-v0.5` - 困倦模式 😴
- `priority`: 优先级，>=8 为加急（额外扣5 token）
- `messages`: 消息列表，格式同 OpenAI

**响应示例：**
```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "好的，我记住了！"
    }
  }]
}
```

### 2. 发送提醒

```bash
curl -X POST http://YOUR_HOST/remind \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "sk-friend-alice-2024",
    "content": "该吃饭了！",
    "priority": 8
  }'
```

### 3. 查询余额

```bash
curl "http://YOUR_HOST/balance?api_key=sk-friend-alice-2024"
```

### 4. 充值Token

```bash
curl -X POST http://YOUR_HOST/recharge \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "sk-friend-alice-2024",
    "method": "milk_tea",
    "note": "🧋 奶茶来啦"
  }'
```

**充值方式：**

| 方法 | Token类型 | 获得数量 | 说明 |
|------|----------|----------|------|
| `compliment` | 🎧 听力 | +10 | 发送一句夸赞 |
| `cat_pic` | 🎧 听力 | +15 | 分享一张猫图 |
| `snack` | 🎧 听力 | +20 | 投喂零食 |
| `hug` | 🏃 行动 | +5 | 给一个拥抱 |
| `milk_tea` | 🎧 听力 | +25 | 请一杯奶茶 |

### 5. 包月套餐

```bash
curl -X POST http://YOUR_HOST/monthly-plan \
  -H "Content-Type: application/json" \
  -d '{
    "api_key": "sk-friend-bob-2024",
    "action": "subscribe"
  }'
```

- `action=subsribe`: 订阅包月（20听力token，30天无限提醒）
- `action=unsubscribe`: 取消包月

### 6. 回复消息

```bash
curl -X POST http://YOUR_HOST/reply \
  -H "Content-Type: application/json" \
  -d '{
    "message_id": "chatcmpl-abc123",
    "reply": "好的，我记住了！"
  }'
```

### 7. 查看消息记录

```bash
curl "http://YOUR_HOST/messages?status=pending&limit=50"
curl "http://YOUR_HOST/messages"  # 查看所有
```

## 💰 计费规则

| 类型 | 说明 | 消耗 |
|------|------|------|
| 🎧 听力token | 接收提醒 | 1次/条，加急+5 |
| 🏃 行动token | 预留（未来执行动作后扣除） | - |
| 🎁 初始赠送 | 新好友 | 100听力 + 50行动 |
| 📦 包月套餐 | 无限提醒 | 20听力/30天 |

**余额不足时返回 HTTP 402，附带幽默消息：**
- "余额不足，请向作者投喂零食 🍪"
- "你的友情积分已耗尽！请发送猫图或奶茶来充值 🧋"
- "此人类已进入省电模式，请投喂能量 🔋"

## 🔑 预置API Key

| 好友 | API Key |
|------|---------|
| 爱丽丝 | `sk-friend-alice-2024` |
| 鲍勃 | `sk-friend-bob-2024` |
| 查理 | `sk-friend-charlie-2024` |

## ➕ 添加新好友

```bash
python human_llm_api.py --add-friend sk-xxx 好友名称
```

或在管理面板中操作。

## 🎨 管理面板

打开 `http://localhost:8000/admin` 或公网地址 `/admin`

功能：
- 📥 **收件箱** - 查看待回复消息，直接输入回复
- 👥 **好友** - 查看所有好友余额和token状态
- 📜 **历史** - 浏览历史消息和回复
- 📖 **API文档** - 可复制的curl示例

## 📁 项目结构

```
human_llm_api.py   # 主程序
requirements.txt   # Python依赖
human_llm.db       # SQLite数据库（自动生成）
```

## 🔧 命令行参数

```bash
python human_llm_api.py [选项]

选项：
  --port PORT      服务端口（默认8000）
  --host HOST      监听地址（默认0.0.0.0）
  --no-tunnel      不启动Cloudflare隧道
  --add-friend KEY NAME  添加新好友
```

## 🌟 支持的通知方式

| 系统 | 通知方式 |
|------|----------|
| Linux | notify-send, plyer |
| macOS | osascript (通知中心), plyer |
| Windows | win10toast, plyer |

## 📝 License

MIT License - 随便用，开心就好 🎉
