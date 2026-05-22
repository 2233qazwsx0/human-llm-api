#!/usr/bin/env python3
"""
Human LLM API - 人类版LLM API服务
让你自己变成一个可被调用的API！好友通过OpenAI格式调用你，
你收到提醒后可以回复，还有趣味token计费系统。

用法: python human_llm_api.py
"""

import asyncio
import json
import os
import random
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

DB_PATH = "human_llm.db"

FRIENDS = {
    "sk-friend-alice-2024": {
        "name": "爱丽丝",
        "listening_tokens": 100,
        "action_tokens": 50,
        "monthly_plan": False,
        "monthly_expire": None,
    },
    "sk-friend-bob-2024": {
        "name": "鲍勃",
        "listening_tokens": 100,
        "action_tokens": 50,
        "monthly_plan": False,
        "monthly_expire": None,
    },
    "sk-friend-charlie-2024": {
        "name": "查理",
        "listening_tokens": 100,
        "action_tokens": 50,
        "monthly_plan": False,
        "monthly_expire": None,
    },
}

RECHARGE_METHODS = {
    "compliment": {"tokens": 10, "desc": "发送一句夸赞", "type": "listening"},
    "cat_pic": {"tokens": 15, "desc": "分享一张猫图", "type": "listening"},
    "snack": {"tokens": 20, "desc": "投喂零食", "type": "listening"},
    "hug": {"tokens": 5, "desc": "给一个拥抱", "type": "action"},
    "milk_tea": {"tokens": 25, "desc": "请一杯奶茶", "type": "listening"},
}

MODELS = [
    {"id": "human-v1", "object": "model", "created": 1700000000, "owned_by": "me-myself-and-i"},
    {"id": "human-caffeinated-v2", "object": "model", "created": 1700000001, "owned_by": "me-after-coffee"},
    {"id": "human-sleepy-v0.5", "object": "model", "created": 1700000002, "owned_by": "me-before-coffee"},
]

HUMOR_402_MESSAGES = [
    "余额不足，请向作者投喂零食 🍪",
    "你的友情积分已耗尽！请发送猫图或奶茶来充值 🧋",
    "对不起，您的账户已被'懒惰税'清空，请用夸赞充值 💸",
    "此人类已进入省电模式，请投喂能量（零食/奶茶/猫图）🔋",
    "友情余额不足！建议：请该人类喝一杯奶茶恢复服务 🧋",
    "您的token已用完，就像我的咖啡一样——空了 ☕",
]

app = FastAPI(title="Human LLM API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS friends (
            api_key TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            listening_tokens INTEGER DEFAULT 100,
            action_tokens INTEGER DEFAULT 50,
            monthly_plan INTEGER DEFAULT 0,
            monthly_expire TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            friend_key TEXT NOT NULL,
            friend_name TEXT NOT NULL,
            content TEXT NOT NULL,
            priority INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',
            reply TEXT,
            created_at TEXT NOT NULL,
            replied_at TEXT,
            tokens_charged INTEGER DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS recharge_log (
            id TEXT PRIMARY KEY,
            friend_key TEXT NOT NULL,
            method TEXT NOT NULL,
            tokens_added INTEGER NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )
    """)
    for key, info in FRIENDS.items():
        c.execute(
            "SELECT api_key FROM friends WHERE api_key = ?",
            (key,),
        )
        if not c.fetchone():
            c.execute(
                "INSERT INTO friends VALUES (?, ?, ?, ?, ?, ?)",
                (
                    key,
                    info["name"],
                    info["listening_tokens"],
                    info["action_tokens"],
                    int(info["monthly_plan"]),
                    info["monthly_expire"],
                ),
            )
    conn.commit()
    conn.close()


def authenticate(api_key: str) -> Optional[dict]:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM friends WHERE api_key = ?", (api_key,))
    row = c.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def check_monthly(friend: dict) -> dict:
    if friend["monthly_plan"]:
        expire = friend["monthly_expire"]
        if expire:
            try:
                expire_dt = datetime.fromisoformat(expire)
                if datetime.now() > expire_dt:
                    conn = get_db()
                    c = conn.cursor()
                    c.execute(
                        "UPDATE friends SET monthly_plan = 0, monthly_expire = NULL WHERE api_key = ?",
                        (friend["api_key"],),
                    )
                    conn.commit()
                    conn.close()
                    friend["monthly_plan"] = 0
                    friend["monthly_expire"] = None
            except Exception:
                pass
    return friend


def deduct_tokens(friend: dict, listening: int = 0, action: int = 0) -> bool:
    if friend["monthly_plan"] and listening > 0:
        return True
    new_listening = friend["listening_tokens"] - listening
    new_action = friend["action_tokens"] - action
    if new_listening < 0 or new_action < 0:
        return False
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "UPDATE friends SET listening_tokens = ?, action_tokens = ? WHERE api_key = ?",
        (new_listening, new_action, friend["api_key"]),
    )
    conn.commit()
    conn.close()
    friend["listening_tokens"] = new_listening
    friend["action_tokens"] = new_action
    return True


def send_notification(title: str, message: str, priority: int = 1):
    prefix = "🔴 加急" if priority >= 8 else "💬 提醒"
    full_title = f"{prefix}: {title}"
    try:
        if sys.platform == "linux":
            urgency = "critical" if priority >= 8 else "normal"
            subprocess.run(
                ["notify-send", "-u", urgency, full_title, message],
                timeout=5,
            )
        elif sys.platform == "darwin":
            script = f'display notification "{message}" with title "{full_title}"'
            subprocess.run(["osascript", "-e", script], timeout=5)
        elif sys.platform == "win32":
            try:
                from win10toast import ToastNotifier
                toaster = ToastNotifier()
                toaster.show_toast(full_title, message, duration=10)
            except ImportError:
                pass
    except Exception:
        pass
    try:
        from plyer import notification as plyer_notif
        plyer_notif.notify(title=full_title, message=message, timeout=10)
    except Exception:
        pass
    print(f"\n{'='*50}")
    print(f"  {full_title}")
    print(f"  {message}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "human-v1"
    messages: list[ChatMessage]
    temperature: float = 1.0
    max_tokens: Optional[int] = None
    stream: bool = False
    priority: int = 1


class RemindRequest(BaseModel):
    api_key: str
    content: str
    priority: int = 1


class RechargeRequest(BaseModel):
    api_key: str
    method: str
    note: str = ""


class MonthlyPlanRequest(BaseModel):
    api_key: str
    action: str = "subscribe"


class ReplyRequest(BaseModel):
    message_id: str
    reply: str


pending_replies = {}


def make_sse_chunk(msg_id: str, model: str, delta: dict, finish_reason: Optional[str] = None):
    chunk = {
        "id": msg_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"


async def stream_response(msg_id: str, model: str, friend: dict, content: str, priority: int, listening_cost: int):
    yield make_sse_chunk(msg_id, model, {"role": "assistant", "content": ""})

    ack_text = f"📨 消息已送达！人类（{friend['name']}的好友）正在等待回复...\n\n"
    for char in ack_text:
        yield make_sse_chunk(msg_id, model, {"content": char})
        await asyncio.sleep(0.02)

    reply_event = asyncio.Event()
    pending_replies[msg_id] = {"event": reply_event, "reply": None}

    got_reply = False
    try:
        await asyncio.wait_for(reply_event.wait(), timeout=120.0)
        reply_content = pending_replies[msg_id]["reply"]
        status = "replied"
        got_reply = True
    except asyncio.TimeoutError:
        reply_content = "⏰ 人类暂时没有回复（可能在忙/摸鱼/喝咖啡），请稍后再来～"
        status = "timeout"
    finally:
        pending_replies.pop(msg_id, None)

    conn = get_db()
    c = conn.cursor()
    replied_at = datetime.now().isoformat() if got_reply else None
    c.execute(
        "UPDATE messages SET status = ?, reply = ?, replied_at = ? WHERE id = ?",
        (status, reply_content, replied_at, msg_id),
    )
    conn.commit()
    conn.close()

    for char in reply_content:
        yield make_sse_chunk(msg_id, model, {"content": char})
        await asyncio.sleep(0.03)

    yield make_sse_chunk(msg_id, model, {}, finish_reason="stop")
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest, request: Request):
    auth_header = request.headers.get("Authorization", "")
    api_key = ""
    if auth_header.startswith("Bearer "):
        api_key = auth_header[7:]
    if not api_key:
        raise HTTPException(status_code=401, detail={"message": "缺少API Key，请在Authorization头中传入Bearer token", "type": "invalid_request_error", "code": "invalid_api_key"})
    friend = authenticate(api_key)
    if not friend:
        raise HTTPException(status_code=401, detail={"message": "无效的API Key！你确定你是我的朋友吗？🤔", "type": "invalid_request_error", "code": "invalid_api_key"})
    friend = check_monthly(friend)
    last_msg = req.messages[-1] if req.messages else None
    if not last_msg:
        raise HTTPException(status_code=400, detail={"message": "消息不能为空！你总得说点什么吧？", "type": "invalid_request_error"})
    content = last_msg.content
    priority = req.priority
    listening_cost = 1
    if priority >= 8:
        listening_cost += 5
    if not deduct_tokens(friend, listening=listening_cost):
        raise HTTPException(status_code=402, detail={"message": random.choice(HUMOR_402_MESSAGES), "type": "insufficient_quota", "code": "insufficient_quota"})
    msg_id = f"chatcmpl-{uuid.uuid4().hex[:29]}"
    now = datetime.now().isoformat()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (msg_id, friend["api_key"], friend["name"], content, priority, "pending", None, now, None, listening_cost),
    )
    conn.commit()
    conn.close()
    model_name = req.model
    send_notification(
        f"来自 {friend['name']} 的消息",
        content,
        priority,
    )

    if req.stream:
        return StreamingResponse(
            stream_response(msg_id, model_name, friend, content, priority, listening_cost),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    reply_event = asyncio.Event()
    pending_replies[msg_id] = {"event": reply_event, "reply": None}
    try:
        await asyncio.wait_for(reply_event.wait(), timeout=120.0)
        reply_content = pending_replies[msg_id]["reply"]
        status = "replied"
    except asyncio.TimeoutError:
        reply_content = "⏰ 人类暂时没有回复（可能在忙/摸鱼/喝咖啡），请稍后再来～"
        status = "timeout"
    finally:
        pending_replies.pop(msg_id, None)
    conn = get_db()
    c = conn.cursor()
    replied_at = datetime.now().isoformat() if status == "replied" else None
    c.execute(
        "UPDATE messages SET status = ?, reply = ?, replied_at = ? WHERE id = ?",
        (status, reply_content, replied_at, msg_id),
    )
    conn.commit()
    conn.close()
    response = {
        "id": msg_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply_content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": len(content),
            "completion_tokens": len(reply_content),
            "total_tokens": len(content) + len(reply_content),
        },
    }
    return response


@app.get("/v1/models")
async def list_models():
    return {"object": "list", "data": MODELS}


@app.post("/remind")
async def remind(req: RemindRequest):
    friend = authenticate(req.api_key)
    if not friend:
        raise HTTPException(status_code=401, detail="无效的API Key！你是谁？我不认识你！👀")
    friend = check_monthly(friend)
    listening_cost = 1
    if req.priority >= 8:
        listening_cost += 5
    if not deduct_tokens(friend, listening=listening_cost):
        raise HTTPException(status_code=402, detail=get_humor_402())
    msg_id = f"remind-{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (msg_id, friend["api_key"], friend["name"], req.content, req.priority, "pending", None, now, None, listening_cost),
    )
    conn.commit()
    conn.close()
    send_notification(
        f"来自 {friend['name']} 的提醒",
        req.content,
        req.priority,
    )
    return {
        "status": "delivered",
        "message_id": msg_id,
        "tokens_charged": listening_cost,
        "remaining_listening_tokens": friend["listening_tokens"],
        "hint": "提醒已送达！人类已收到通知～" if req.priority < 8 else "🚨 加急提醒已送达！人类已被强制唤醒！",
    }


@app.get("/balance")
async def balance(api_key: str):
    friend = authenticate(api_key)
    if not friend:
        raise HTTPException(status_code=401, detail="无效的API Key！查无此人！🔍")
    friend = check_monthly(friend)
    return {
        "friend_name": friend["name"],
        "listening_tokens": friend["listening_tokens"],
        "action_tokens": friend["action_tokens"],
        "monthly_plan": bool(friend["monthly_plan"]),
        "monthly_expire": friend["monthly_expire"],
        "currency_name": {"listening": "听力token 🎧", "action": "行动token 🏃"},
        "exchange_rate": "1听力token = 1次提醒, 加急+5, 包月20/月无限",
    }


@app.post("/recharge")
async def recharge(req: RechargeRequest):
    friend = authenticate(req.api_key)
    if not friend:
        raise HTTPException(status_code=401, detail="无效的API Key！充值需认证！🔒")
    if req.method not in RECHARGE_METHODS:
        valid = ", ".join(f'"{k}": {v["desc"]}' for k, v in RECHARGE_METHODS.items())
        raise HTTPException(
            status_code=400,
            detail=f"未知充值方式！可选方式: {valid}",
        )
    method_info = RECHARGE_METHODS[req.method]
    token_type = method_info["type"]
    tokens_added = method_info["tokens"]
    conn = get_db()
    c = conn.cursor()
    if token_type == "listening":
        c.execute(
            "UPDATE friends SET listening_tokens = listening_tokens + ? WHERE api_key = ?",
            (tokens_added, friend["api_key"]),
        )
    else:
        c.execute(
            "UPDATE friends SET action_tokens = action_tokens + ? WHERE api_key = ?",
            (tokens_added, friend["api_key"]),
        )
    log_id = f"recharge-{uuid.uuid4().hex[:8]}"
    now = datetime.now().isoformat()
    c.execute(
        "INSERT INTO recharge_log VALUES (?, ?, ?, ?, ?, ?)",
        (log_id, friend["api_key"], req.method, tokens_added, req.note, now),
    )
    conn.commit()
    c.execute("SELECT * FROM friends WHERE api_key = ?", (friend["api_key"],))
    updated = dict(c.fetchone())
    conn.close()
    return {
        "status": "recharged",
        "method": req.method,
        "method_desc": method_info["desc"],
        "tokens_added": tokens_added,
        "token_type": token_type,
        "new_balance": {
            "listening_tokens": updated["listening_tokens"],
            "action_tokens": updated["action_tokens"],
        },
        "message": f"充值成功！{friend['name']}通过「{method_info['desc']}」获得了{tokens_added}个{token_type}token！🎉",
    }


@app.post("/monthly-plan")
async def monthly_plan(req: MonthlyPlanRequest):
    friend = authenticate(req.api_key)
    if not friend:
        raise HTTPException(status_code=401, detail="无效的API Key！")
    friend = check_monthly(friend)
    conn = get_db()
    c = conn.cursor()
    if req.action == "subscribe":
        if friend["monthly_plan"]:
            return {"status": "already_subscribed", "message": "你已经订阅了包月套餐！别重复花钱～💰"}
        cost = 20
        if friend["listening_tokens"] < cost:
            raise HTTPException(status_code=402, detail=f"包月需要{cost}听力token，你只有{friend['listening_tokens']}个！先充值吧～")
        expire = (datetime.now() + timedelta(days=30)).isoformat()
        c.execute(
            "UPDATE friends SET listening_tokens = listening_tokens - ?, monthly_plan = 1, monthly_expire = ? WHERE api_key = ?",
            (cost, expire, friend["api_key"]),
        )
        conn.commit()
        conn.close()
        return {
            "status": "subscribed",
            "cost": cost,
            "expire": expire,
            "message": f"包月订阅成功！30天内无限提醒！到期时间: {expire[:10]} 🎉",
        }
    elif req.action == "unsubscribe":
        c.execute(
            "UPDATE friends SET monthly_plan = 0, monthly_expire = NULL WHERE api_key = ?",
            (friend["api_key"],),
        )
        conn.commit()
        conn.close()
        return {"status": "unsubscribed", "message": "已取消包月。我们会想念你的...的token的 😢"}
    else:
        raise HTTPException(status_code=400, detail="action只能是subscribe或unsubscribe")


@app.post("/reply")
async def reply_message(req: ReplyRequest):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM messages WHERE id = ?", (req.message_id,))
    msg = c.fetchone()
    if not msg:
        conn.close()
        raise HTTPException(status_code=404, detail="消息不存在！")
    now = datetime.now().isoformat()
    c.execute(
        "UPDATE messages SET status = 'replied', reply = ?, replied_at = ? WHERE id = ?",
        (req.reply, now, req.message_id),
    )
    conn.commit()
    conn.close()
    if req.message_id in pending_replies:
        pending_replies[req.message_id]["reply"] = req.reply
        pending_replies[req.message_id]["event"].set()
    return {"status": "replied", "message_id": req.message_id, "reply": req.reply}


@app.get("/messages")
async def get_messages(status: str = "", limit: int = 50):
    conn = get_db()
    c = conn.cursor()
    if status:
        c.execute(
            "SELECT * FROM messages WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )
    else:
        c.execute("SELECT * FROM messages ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return {"messages": rows}


@app.get("/friends")
async def get_friends():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM friends")
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return {"friends": rows}


@app.get("/recharge-log")
async def get_recharge_log(limit: int = 50):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM recharge_log ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(row) for row in c.fetchall()]
    conn.close()
    return {"logs": rows}


ADMIN_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Human LLM API - 控制面板</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background: #0f0f1a; color: #e0e0e0; min-height: 100vh; }
.header { background: linear-gradient(135deg, #1a1a2e, #16213e); padding: 20px 30px; border-bottom: 2px solid #e94560; display: flex; justify-content: space-between; align-items: center; }
.header h1 { font-size: 24px; color: #e94560; }
.header h1 span { color: #0f3460; background: #e94560; padding: 2px 8px; border-radius: 4px; font-size: 14px; margin-left: 10px; }
.header .status { display: flex; gap: 15px; align-items: center; }
.header .status .dot { width: 10px; height: 10px; border-radius: 50%; background: #00ff88; animation: pulse 2s infinite; }
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
.container { max-width: 1400px; margin: 0 auto; padding: 20px; }
.tabs { display: flex; gap: 5px; margin-bottom: 20px; flex-wrap: wrap; }
.tab { padding: 10px 20px; background: #1a1a2e; border: 1px solid #333; border-radius: 8px 8px 0 0; cursor: pointer; transition: all 0.3s; color: #888; }
.tab:hover { color: #e94560; border-color: #e94560; }
.tab.active { background: #16213e; color: #e94560; border-color: #e94560; border-bottom-color: #16213e; }
.panel { display: none; background: #16213e; border: 1px solid #333; border-radius: 0 8px 8px 8px; padding: 20px; }
.panel.active { display: block; }
.card { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 12px; padding: 20px; margin-bottom: 15px; transition: transform 0.2s; }
.card:hover { transform: translateY(-2px); border-color: #e94560; }
.card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.card-header h3 { color: #e94560; font-size: 18px; }
.badge { padding: 3px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; }
.badge-pending { background: #ff6b3520; color: #ff6b35; border: 1px solid #ff6b35; }
.badge-replied { background: #00ff8820; color: #00ff88; border: 1px solid #00ff88; }
.badge-timeout { background: #ffd70020; color: #ffd700; border: 1px solid #ffd700; }
.badge-monthly { background: #e9456020; color: #e94560; border: 1px solid #e94560; }
.token-bar { background: #0f0f1a; border-radius: 8px; height: 24px; overflow: hidden; margin: 5px 0; }
.token-fill { height: 100%; border-radius: 8px; transition: width 0.5s; display: flex; align-items: center; padding-left: 8px; font-size: 11px; font-weight: bold; }
.token-listening .token-fill { background: linear-gradient(90deg, #0f3460, #e94560); }
.token-action .token-fill { background: linear-gradient(90deg, #16213e, #00ff88); }
.reply-box { width: 100%; background: #0f0f1a; border: 1px solid #2a2a4a; border-radius: 8px; padding: 10px; color: #e0e0e0; font-size: 14px; resize: vertical; min-height: 60px; }
.reply-box:focus { outline: none; border-color: #e94560; }
.btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: bold; transition: all 0.2s; }
.btn-primary { background: #e94560; color: white; }
.btn-primary:hover { background: #c73650; }
.btn-secondary { background: #0f3460; color: #e0e0e0; }
.btn-secondary:hover { background: #1a4a80; }
.msg-content { background: #0f0f1a; padding: 12px; border-radius: 8px; margin: 8px 0; border-left: 3px solid #e94560; }
.msg-reply { background: #0f0f1a; padding: 12px; border-radius: 8px; margin: 8px 0; border-left: 3px solid #00ff88; }
.meta { font-size: 12px; color: #666; margin-top: 5px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 15px; }
.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin-bottom: 20px; }
.stat-card { background: #1a1a2e; border: 1px solid #2a2a4a; border-radius: 12px; padding: 15px; text-align: center; }
.stat-card .number { font-size: 28px; font-weight: bold; color: #e94560; }
.stat-card .label { font-size: 12px; color: #888; margin-top: 5px; }
.api-doc { background: #0f0f1a; border-radius: 8px; padding: 15px; margin: 10px 0; font-family: 'Fira Code', monospace; font-size: 13px; overflow-x: auto; }
.api-doc .method { display: inline-block; padding: 2px 8px; border-radius: 4px; font-weight: bold; margin-right: 10px; }
.method-post { background: #00ff8820; color: #00ff88; }
.method-get { background: #0f346020; color: #5bc0eb; }
.copy-btn { float: right; background: #2a2a4a; border: none; color: #888; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 11px; }
.copy-btn:hover { color: #e94560; }
.refresh-btn { background: none; border: 1px solid #333; color: #888; padding: 5px 12px; border-radius: 6px; cursor: pointer; }
.refresh-btn:hover { border-color: #e94560; color: #e94560; }
.empty { text-align: center; padding: 40px; color: #555; }
.empty .emoji { font-size: 48px; margin-bottom: 10px; }
</style>
</head>
<body>
<div class="header">
  <h1>🧠 Human LLM API <span>v1.0</span></h1>
  <div class="status">
    <span id="tunnel-status" style="font-size:13px;color:#888;">检查隧道状态中...</span>
    <div class="dot"></div>
    <span style="font-size:13px;">在线</span>
    <button class="refresh-btn" onclick="refreshAll()">🔄 刷新</button>
  </div>
</div>
<div class="container">
  <div class="tabs">
    <div class="tab active" onclick="switchTab('inbox')">📥 收件箱</div>
    <div class="tab" onclick="switchTab('friends')">👥 好友</div>
    <div class="tab" onclick="switchTab('history')">📜 历史</div>
    <div class="tab" onclick="switchTab('docs')">📖 API文档</div>
  </div>

  <div id="panel-inbox" class="panel active">
    <div class="stats" id="inbox-stats"></div>
    <div id="inbox-list"></div>
  </div>

  <div id="panel-friends" class="panel">
    <div class="grid" id="friends-list"></div>
  </div>

  <div id="panel-history" class="panel">
    <div id="history-list"></div>
  </div>

  <div id="panel-docs" class="panel">
    <h3 style="color:#e94560;margin-bottom:15px;">📖 API文档 - 供好友调用参考</h3>
    <div id="api-docs-content"></div>
  </div>
</div>

<script>
const BASE = '';
let currentTab = 'inbox';

function switchTab(tab) {
  currentTab = tab;
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('panel-' + tab).classList.add('active');
  refreshAll();
}

async function api(path) {
  const r = await fetch(BASE + path);
  return r.json();
}

async function postApi(path, body) {
  const r = await fetch(BASE + path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  return r.json();
}

async function refreshAll() {
  if (currentTab === 'inbox') await refreshInbox();
  else if (currentTab === 'friends') await refreshFriends();
  else if (currentTab === 'history') await refreshHistory();
  else if (currentTab === 'docs') renderDocs();
}

async function refreshInbox() {
  const data = await api('/messages?status=pending&limit=50');
  const msgs = data.messages || [];
  const allData = await api('/messages?limit=1000');
  const all = allData.messages || [];
  const pending = all.filter(m => m.status === 'pending').length;
  const replied = all.filter(m => m.status === 'replied').length;
  const timeout = all.filter(m => m.status === 'timeout').length;

  document.getElementById('inbox-stats').innerHTML = `
    <div class="stat-card"><div class="number">${pending}</div><div class="label">待回复</div></div>
    <div class="stat-card"><div class="number">${replied}</div><div class="label">已回复</div></div>
    <div class="stat-card"><div class="number">${timeout}</div><div class="label">超时</div></div>
    <div class="stat-card"><div class="number">${all.length}</div><div class="label">总消息</div></div>
  `;

  if (msgs.length === 0) {
    document.getElementById('inbox-list').innerHTML = '<div class="empty"><div class="emoji">📭</div><div>暂无待回复消息，先喝杯咖啡吧～</div></div>';
    return;
  }

  let html = '';
  msgs.forEach(m => {
    const priorityTag = m.priority >= 8 ? '<span style="color:#ff6b35;font-weight:bold;">🔴 加急</span>' : '';
    html += `<div class="card">
      <div class="card-header">
        <h3>👤 ${m.friend_name} ${priorityTag}</h3>
        <span class="badge badge-${m.status}">${m.status}</span>
      </div>
      <div class="msg-content">${m.content}</div>
      <div class="meta">⏰ ${new Date(m.created_at).toLocaleString('zh-CN')} | 💰 扣除 ${m.tokens_charged} token</div>
      <div style="margin-top:10px;">
        <textarea class="reply-box" id="reply-${m.id}" placeholder="在这里输入你的回复..."></textarea>
        <div style="margin-top:8px;text-align:right;">
          <button class="btn btn-primary" onclick="sendReply('${m.id}')">📤 回复</button>
        </div>
      </div>
    </div>`;
  });
  document.getElementById('inbox-list').innerHTML = html;
}

async function sendReply(msgId) {
  const textarea = document.getElementById('reply-' + msgId);
  const reply = textarea.value.trim();
  if (!reply) return;
  await postApi('/reply', { message_id: msgId, reply: reply });
  textarea.value = '';
  refreshInbox();
}

async function refreshFriends() {
  const data = await api('/friends');
  const friends = data.friends || [];
  if (friends.length === 0) {
    document.getElementById('friends-list').innerHTML = '<div class="empty"><div class="emoji">👻</div><div>还没有好友...</div></div>';
    return;
  }
  let html = '';
  friends.forEach(f => {
    const listeningPct = Math.min(f.listening_tokens / 100 * 100, 100);
    const actionPct = Math.min(f.action_tokens / 50 * 100, 100);
    const monthlyBadge = f.monthly_plan ? '<span class="badge badge-monthly">包月</span>' : '';
    html += `<div class="card">
      <div class="card-header">
        <h3>👤 ${f.name} ${monthlyBadge}</h3>
        <span style="font-size:11px;color:#555;">${f.api_key.substring(0,16)}...</span>
      </div>
      <div>
        <div style="display:flex;justify-content:space-between;font-size:13px;">
          <span>🎧 听力token</span><span>${f.listening_tokens}</span>
        </div>
        <div class="token-bar token-listening">
          <div class="token-fill" style="width:${listeningPct}%">${f.listening_tokens}</div>
        </div>
      </div>
      <div>
        <div style="display:flex;justify-content:space-between;font-size:13px;">
          <span>🏃 行动token</span><span>${f.action_tokens}</span>
        </div>
        <div class="token-bar token-action">
          <div class="token-fill" style="width:${actionPct}%">${f.action_tokens}</div>
        </div>
      </div>
      ${f.monthly_plan ? `<div class="meta" style="margin-top:8px;">📅 包月到期: ${f.monthly_expire ? f.monthly_expire.substring(0,10) : 'N/A'}</div>` : ''}
    </div>`;
  });
  document.getElementById('friends-list').innerHTML = html;
}

async function refreshHistory() {
  const data = await api('/messages?limit=100');
  const msgs = data.messages || [];
  if (msgs.length === 0) {
    document.getElementById('history-list').innerHTML = '<div class="empty"><div class="emoji">📜</div><div>暂无历史记录</div></div>';
    return;
  }
  let html = '';
  msgs.forEach(m => {
    const priorityTag = m.priority >= 8 ? '🔴 ' : '';
    html += `<div class="card">
      <div class="card-header">
        <h3 style="font-size:15px;">${priorityTag}👤 ${m.friend_name}</h3>
        <span class="badge badge-${m.status}">${m.status}</span>
      </div>
      <div class="msg-content">${m.content}</div>
      ${m.reply ? `<div class="msg-reply">💬 ${m.reply}</div>` : ''}
      <div class="meta">⏰ ${new Date(m.created_at).toLocaleString('zh-CN')} | 💰 ${m.tokens_charged} token | ID: ${m.id}</div>
    </div>`;
  });
  document.getElementById('history-list').innerHTML = html;
}

function renderDocs() {
  document.getElementById('api-docs-content').innerHTML = `
    <div class="api-doc">
      <span class="method method-post">POST</span> <code>/v1/chat/completions</code> - OpenAI兼容接口
      <button class="copy-btn" onclick="copyCode('doc1')">复制</button>
      <pre id="doc1" style="margin-top:10px;color:#aaa;">
curl -X POST http://YOUR_HOST/v1/chat/completions \\
  -H "Authorization: Bearer sk-friend-alice-2024" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "human-v1",
    "messages": [{"role": "user", "content": "记得喝水！"}],
    "priority": 1
  }'</pre>
      <p style="color:#888;margin-top:5px;">💡 priority >= 8 为加急，额外扣5 token。模型可选: human-v1, human-caffeinated-v2, human-sleepy-v0.5</p>
    </div>

    <div class="api-doc">
      <span class="method method-get">GET</span> <code>/v1/models</code> - 查看可用模型
      <button class="copy-btn" onclick="copyCode('doc2')">复制</button>
      <pre id="doc2" style="margin-top:10px;color:#aaa;">
curl http://YOUR_HOST/v1/models \\
  -H "Authorization: Bearer sk-friend-alice-2024"</pre>
    </div>

    <div class="api-doc">
      <span class="method method-post">POST</span> <code>/remind</code> - 发送提醒
      <button class="copy-btn" onclick="copyCode('doc3')">复制</button>
      <pre id="doc3" style="margin-top:10px;color:#aaa;">
curl -X POST http://YOUR_HOST/remind \\
  -H "Content-Type: application/json" \\
  -d '{
    "api_key": "sk-friend-alice-2024",
    "content": "该吃饭了！",
    "priority": 8
  }'</pre>
    </div>

    <div class="api-doc">
      <span class="method method-get">GET</span> <code>/balance?api_key=YOUR_KEY</code> - 查询余额
      <button class="copy-btn" onclick="copyCode('doc4')">复制</button>
      <pre id="doc4" style="margin-top:10px;color:#aaa;">
curl "http://YOUR_HOST/balance?api_key=sk-friend-alice-2024"</pre>
    </div>

    <div class="api-doc">
      <span class="method method-post">POST</span> <code>/recharge</code> - 充值token
      <button class="copy-btn" onclick="copyCode('doc5')">复制</button>
      <pre id="doc5" style="margin-top:10px;color:#aaa;">
curl -X POST http://YOUR_HOST/recharge \\
  -H "Content-Type: application/json" \\
  -d '{
    "api_key": "sk-friend-alice-2024",
    "method": "cat_pic",
    "note": "🐱 喵喵喵"
  }'</pre>
      <p style="color:#888;margin-top:5px;">💡 充值方式: compliment(+10🎧), cat_pic(+15🎧), snack(+20🎧), hug(+5🏃), milk_tea(+25🎧)</p>
    </div>

    <div class="api-doc">
      <span class="method method-post">POST</span> <code>/monthly-plan</code> - 包月套餐
      <button class="copy-btn" onclick="copyCode('doc6')">复制</button>
      <pre id="doc6" style="margin-top:10px;color:#aaa;">
curl -X POST http://YOUR_HOST/monthly-plan \\
  -H "Content-Type: application/json" \\
  -d '{
    "api_key": "sk-friend-alice-2024",
    "action": "subscribe"
  }'</pre>
      <p style="color:#888;margin-top:5px;">💡 包月20听力token/月，无限提醒！action可选: subscribe, unsubscribe</p>
    </div>

    <div style="margin-top:20px;padding:15px;background:#0f0f1a;border-radius:8px;border:1px solid #2a2a4a;">
      <h4 style="color:#e94560;">🔑 预置API Key</h4>
      <table style="width:100%;margin-top:10px;font-size:13px;">
        <tr style="color:#888;"><td>好友</td><td>API Key</td></tr>
        <tr><td>爱丽丝</td><td style="font-family:monospace;">sk-friend-alice-2024</td></tr>
        <tr><td>鲍勃</td><td style="font-family:monospace;">sk-friend-bob-2024</td></tr>
        <tr><td>查理</td><td style="font-family:monospace;">sk-friend-charlie-2024</td></tr>
      </table>
    </div>

    <div style="margin-top:15px;padding:15px;background:#0f0f1a;border-radius:8px;border:1px solid #2a2a4a;">
      <h4 style="color:#e94560;">💰 计费规则</h4>
      <ul style="margin-top:10px;font-size:13px;line-height:2;color:#aaa;">
        <li>🎧 听力token: 每次提醒扣1个，加急(priority≥8)额外扣5个</li>
        <li>🏃 行动token: 预留，未来人类真正执行动作后扣除</li>
        <li>🎁 初始赠送: 100听力token + 50行动token</li>
        <li>📦 包月套餐: 20听力token/月，无限提醒</li>
        <li>❌ 余额不足返回 HTTP 402 + 幽默提示</li>
      </ul>
    </div>
  `;
}

function copyCode(id) {
  const el = document.getElementById(id);
  navigator.clipboard.writeText(el.textContent.trim());
}

async function checkTunnel() {
  try {
    const r = await fetch('/tunnel-url');
    if (r.ok) {
      const data = await r.json();
      document.getElementById('tunnel-status').innerHTML =
        '🌐 <a href="' + data.url + '" target="_blank" style="color:#00ff88;">' + data.url + '</a>';
    } else {
      document.getElementById('tunnel-status').textContent = '🌐 仅局域网';
    }
  } catch(e) {
    document.getElementById('tunnel-status').textContent = '🌐 仅局域网';
  }
}

refreshAll();
checkTunnel();
setInterval(() => { if (currentTab === 'inbox') refreshInbox(); }, 5000);
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
async def admin_panel():
    return ADMIN_HTML


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel_alias():
    return ADMIN_HTML


tunnel_url_store = {"url": None}


@app.get("/tunnel-url")
async def get_tunnel_url():
    if tunnel_url_store["url"]:
        return {"url": tunnel_url_store["url"]}
    raise HTTPException(status_code=404, detail="No tunnel active")


def start_cloudflare_tunnel(port: int = 8000):
    try:
        result = subprocess.run(
            ["which", "cloudflared"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            print("⚠️  cloudflared 未安装，跳过隧道")
            print("   安装方法: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")
            return None
    except Exception:
        return None

    try:
        proc = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        import threading
        def read_output():
            while True:
                line = proc.stderr.readline()
                if not line:
                    break
                if "https://" in line and ".trycloudflare.com" in line:
                    import re
                    match = re.search(r'https://[a-zA-Z0-9\-]+\.trycloudflare\.com', line)
                    if match:
                        url = match.group(0)
                        tunnel_url_store["url"] = url
                        print(f"\n{'='*60}")
                        print(f"  🌐 Cloudflare 隧道已建立!")
                        print(f"  📡 公网地址: {url}")
                        print(f"  📖 API文档: {url}/admin")
                        print(f"{'='*60}\n")
        t = threading.Thread(target=read_output, daemon=True)
        t.start()
        return proc
    except Exception as e:
        print(f"⚠️  启动隧道失败: {e}")
        return None


def add_friend(api_key: str, name: str, listening: int = 100, action: int = 50):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT api_key FROM friends WHERE api_key = ?", (api_key,))
    if c.fetchone():
        conn.close()
        return False
    c.execute(
        "INSERT INTO friends VALUES (?, ?, ?, ?, 0, NULL)",
        (api_key, name, listening, action),
    )
    conn.commit()
    conn.close()
    return True


@app.post("/add-friend")
async def add_friend_api(api_key: str, name: str, listening_tokens: int = 100, action_tokens: int = 50):
    if add_friend(api_key, name, listening_tokens, action_tokens):
        return {"status": "ok", "message": f"好友 {name} 已添加！API Key: {api_key}"}
    return {"status": "exists", "message": f"API Key {api_key} 已存在"}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Human LLM API - 人类版LLM API服务")
    parser.add_argument("--port", type=int, default=8000, help="服务端口 (默认8000)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址 (默认0.0.0.0)")
    parser.add_argument("--no-tunnel", action="store_true", help="不启动Cloudflare隧道")
    parser.add_argument("--add-friend", nargs=2, metavar=("API_KEY", "NAME"), help="添加好友")
    args = parser.parse_args()

    init_db()

    if args.add_friend:
        key, name = args.add_friend
        if add_friend(key, name):
            print(f"✅ 好友 {name} 已添加! API Key: {key}")
        else:
            print(f"⚠️  API Key {key} 已存在")
        return

    print("""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   🧠  Human LLM API  -  人类版LLM API服务               ║
║                                                          ║
║   让你自己变成一个可被调用的API！                          ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
    """)

    if not args.no_tunnel:
        start_cloudflare_tunnel(args.port)

    import uvicorn
    print(f"🚀 服务启动中... http://{args.host}:{args.port}")
    print(f"📖 管理面板: http://localhost:{args.port}/admin")
    print(f"📋 API端点: http://localhost:{args.port}/v1/chat/completions")
    print()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
