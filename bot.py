# -*- coding: utf-8 -*-
"""
Бот канала «Авто Жизнь с Мирой» — приём заявок.
Stateless: состояние диалога кодируется в тексте сообщения, поэтому перезапуск
сервера ничего не теряет. Заявки уходят сразу в Telegram (в личку админа и,
если задан LEAD_CHAT_ID, в отдельный чат-канал).
"""
import os, json, hmac, hashlib, requests
from flask import Flask, request, jsonify

TOK = os.environ["BOT_TOKEN"]
BASE = f"https://api.telegram.org/bot{TOK}"
ADMIN = int(os.environ.get("ADMIN_ID", "1213874390"))
LEAD_CHAT = os.environ.get("LEAD_CHAT_ID", "").strip()
LANDING = os.environ.get("LANDING_URL", "https://avtozhizn-svyazka-wtdaf6ev.agent.mira.tg")
CHECKLIST = os.environ.get("CHECKLIST_URL", "https://chek-list-avtomatizaciya-wtdaf6ev.agent.mira.tg")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
PUBLIC_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")

Q = [
    ("process", "Что отнимает больше всего времени и повторяется?",
     ["Заявки и входящие письма", "Отчёты и сводки", "Напоминания и дедлайны", "Другое"]),
    ("tools", "Какими сервисами пользуетесь?",
     ["Почта и мессенджеры", "Таблицы и CRM", "Всё вручную", "Другое"]),
    ("pain", "Что будет, если не сделать вовремя?",
     ["Клиент ждёт и уходит", "Штрафы и бонусы", "Срыв сроков", "Ничего страшного"]),
    ("tried", "Что уже пробовали?",
     ["Пробовал, не вышло", "Пробовал, но дорого", "Не пробовал", "Нужна помощь"]),
]

HELLO = ("👋 Привет! Я бот канала «Авто Жизнь с Мирой».\n\n"
         "Помогу за 10 минут понять, что в вашем процессе стоит автоматизировать первым.\n\n"
         "Ответьте на пару вопросов — и я передам заявку Ольге, она свяжется с вами.")

app = Flask(__name__)


def api(method, **kw):
    try:
        r = requests.post(f"{BASE}/{method}", timeout=25, data=kw)
        j = r.json()
        if not j.get("ok"):
            print("api error", method, j.get("description"))
        return j.get("result")
    except Exception as e:
        print("api fail", method, e)
        return None


def send(chat_id, text, buttons=None):
    kw = {"chat_id": chat_id, "text": text}
    if buttons:
        kw["reply_markup"] = json.dumps({"inline_keyboard": buttons}, ensure_ascii=False)
    return api("sendMessage", **kw)


def edit(chat_id, message_id, text, buttons=None):
    kw = {"chat_id": chat_id, "message_id": message_id, "text": text}
    if buttons:
        kw["reply_markup"] = json.dumps({"inline_keyboard": buttons}, ensure_ascii=False)
    else:
        kw["reply_markup"] = json.dumps({"inline_keyboard": []}, ensure_ascii=False)
    return api("editMessageText", **kw)


def keyboard(step):
    return [[{"text": o, "callback_data": f"a|{step}|{i}"}] for i, o in enumerate(Q[step][2])]


def state_text(answers, step):
    """Состояние диалога хранится в тексте сообщения — сервер stateless."""
    payload = "|".join(f"{k}={answers.get(k,'')}" for k, _, _ in Q)
    if step < len(Q):
        return f"[state:{step}:{payload}]\n\n❓ **{Q[step][1]}**"
    return f"[state:{step}:{payload}]"


def parse_state(text):
    """Восстанавливает состояние из текста сообщения."""
    if not text or "[state:" not in text:
        return 0, {}
    try:
        head = text.split("]", 1)[0].replace("[state:", "")
        step_s, payload = head.split(":", 1)
        step = int(step_s)
    except Exception:
        return 0, {}
    answers = {}
    for part in payload.split("|"):
        if "=" in part:
            k, v = part.split("=", 1)
            answers[k.strip()] = v.strip()
    return step, answers


def fmt_lead(chat_id, name, username, answers):
    lines = ["🔥 Новая заявка", "", f"Имя: {name or '—'}"]
    if username:
        lines.append(f"Username: @{username}")
    lines += [f"chat_id: {chat_id}", ""]
    for k, q, _ in Q:
        lines.append(f"→ {q}\n   {answers.get(k, '—')}")
    lines += ["", f"Ссылка: {LANDING}", f"Чек-лист: {CHECKLIST}"]
    return "\n".join(lines)


def deliver(chat_id, name, username, answers):
    text = fmt_lead(chat_id, name, username, answers)
    send(ADMIN, text)
    if LEAD_CHAT:
        send(LEAD_CHAT, text)
    print("LEAD", chat_id, name, answers)


def handle_update(u):
    if "callback_query" in u:
        cq = u["callback_query"]
        data = cq.get("data", "")
        msg = cq.get("message") or {}
        cid = msg.get("chat", {}).get("id")
        if not cid or not data.startswith("a|"):
            return
        _, step_s, val_s = data.split("|", 2)
        step = int(step_s)
        val = Q[step][2][int(val_s)]
        _, answers = parse_state(msg.get("text", ""))
        answers[Q[step][0]] = val
        step += 1
        if step >= len(Q):
            frm = cq.get("from", {}) or {}
            deliver(cid, frm.get("first_name", ""), frm.get("username", ""), answers)
            edit(cid, msg.get("message_id"),
                 "✅ Готово, заявка принята.\n\nОльга свяжется с вами и разберёт ваш процесс.\n\n"
                 f"Чек-лист «Что автоматизировать первым»:\n{CHECKLIST}\n\n"
                 f"Страница с примером связки:\n{LANDING}")
        else:
            edit(cid, msg.get("message_id"), state_text(answers, step), keyboard(step))
        api("answerCallbackQuery", callback_query_id=cq.get("id"))
        return

    m = u.get("message") or {}
    cid = m.get("chat", {}).get("id")
    text = m.get("text") or ""
    if not cid:
        return
    if text.startswith("/start") or text.startswith("/checklist"):
        send(cid, HELLO, keyboard(0))
    elif text.startswith("/help"):
        send(cid, "Нажмите /start — и я задам 4 коротких вопроса о вашем процессе.")


@app.route("/webhook", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET:
        h = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(h, WEBHOOK_SECRET):
            return "forbidden", 403
    u = request.get_json(silent=True) or {}
    try:
        handle_update(u)
    except Exception as e:
        print("handler error", e)
    return "ok", 200


@app.route("/health", methods=["GET"])
def health():
    return "ok", 200


@app.route("/setwebhook", methods=["GET"])
def setwebhook():
    if not PUBLIC_URL:
        return "no PUBLIC_URL", 400
    if WEBHOOK_SECRET:
        api("setWebhook", url=f"{PUBLIC_URL}/webhook", secret_token=WEBHOOK_SECRET,
            allowed_updates=["message", "callback_query"])
    else:
        api("setWebhook", url=f"{PUBLIC_URL}/webhook", allowed_updates=["message", "callback_query"])
    return "webhook set: " + PUBLIC_URL, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
