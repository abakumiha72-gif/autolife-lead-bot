# -*- coding: utf-8 -*-
"""
Бот канала «Авто Жизнь с Мирой» — приём заявок.
Режим long polling: не нужен внешний HTTPS-адрес, состояние диалога кодируется
в тексте сообщения (stateless). Заявки уходят сразу в Telegram — их нельзя потерять.
"""
import os, json, time, requests


def read_token():
    t = os.environ.get("BOT_TOKEN", "").strip()
    if t:
        return t
    here = os.path.dirname(os.path.abspath(__file__))
    for path in ("/app/token.txt", "/app/data/token.txt",
                 os.path.join(here, "token.txt")):
        try:
            with open(path, encoding="utf-8") as f:
                v = f.read().strip()
                if v:
                    return v
        except Exception:
            continue
    raise RuntimeError("BOT_TOKEN не найден: env-переменная или файл token.txt")


TOK = read_token()
BASE = f"https://api.telegram.org/bot{TOK}"
ADMIN = int(os.environ.get("ADMIN_ID", "1213874390"))
LEAD_CHAT = os.environ.get("LEAD_CHAT_ID", "").strip()
LANDING = os.environ.get("LANDING_URL", "https://avtozhizn-svyazka-wtdaf6ev.agent.mira.tg")
CHECKLIST = os.environ.get("CHECKLIST_URL", "https://chek-list-avtomatizaciya-wtdaf6ev.agent.mira.tg")

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


def api(method, **kw):
    try:
        r = requests.post(f"{BASE}/{method}", timeout=60, data=kw)
        j = r.json()
        if not j.get("ok"):
            print("api error", method, j.get("description"), flush=True)
        return j.get("result")
    except Exception as e:
        print("api fail", method, e, flush=True)
        return None


def send(chat_id, text, buttons=None):
    kw = {"chat_id": chat_id, "text": text}
    if buttons:
        kw["reply_markup"] = json.dumps({"inline_keyboard": buttons}, ensure_ascii=False)
    return api("sendMessage", **kw)


def edit(chat_id, message_id, text, buttons=None):
    kw = {"chat_id": chat_id, "message_id": message_id, "text": text}
    kw["reply_markup"] = json.dumps({"inline_keyboard": buttons or []}, ensure_ascii=False)
    return api("editMessageText", **kw)


def keyboard(step):
    return [[{"text": o, "callback_data": f"a|{step}|{i}"}] for i, o in enumerate(Q[step][2])]


def state_text(answers, step):
    payload = "|".join(f"{k}={answers.get(k,'')}" for k, _, _ in Q)
    return f"[state:{step}:{payload}]\n\n❓ **{Q[step][1]}**"


def parse_state(text):
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
    print("LEAD", chat_id, name, answers, flush=True)


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
    if text.strip().lower() in ("start", "/start", "/checklist", "начать"):
        send(cid, HELLO, keyboard(0))
    elif text.startswith("/help"):
        send(cid, "Нажмите /start — и я задам 4 коротких вопроса о вашем процессе.")


DATA_DIR = os.environ.get("DATA_DIR", "/app/data")


def start_offset():
    """Продолжаем с последнего обработанного апдейта, чтобы не переигрывать
    старые сообщения при перезапуске."""
    try:
        with open(os.path.join(DATA_DIR, "offset.txt"), encoding="utf-8") as f:
            return int(f.read().strip())
    except Exception:
        pass
    last = api("getUpdates", offset=-1, timeout=0, limit=1) or []
    if last:
        return last[-1]["update_id"] + 1
    return 0


def notify_alive():
    """Пишем Ольге при каждом старте: так видно, что контейнер жив."""
    try:
        send(ADMIN, "✅ Бот запущен (Bothost). Проверка связи — если вы видите это сообщение, "
                    "бот работает и принимает заявки.")
    except Exception as e:
        print("notify fail", e, flush=True)


def main():
    api("deleteWebhook", drop_pending_updates="false")
    offset = start_offset()
    print("bot started (long polling), offset =", offset, flush=True)
    print("admin =", ADMIN, "| data_dir =", DATA_DIR, "| lead_chat =", bool(LEAD_CHAT), flush=True)
    notify_alive()
    while True:
        try:
            ups = api("getUpdates", offset=offset, timeout=30) or []
            if ups:
                print("got", len(ups), "update(s)", flush=True)
            for u in ups:
                offset = u["update_id"] + 1
                try:
                    handle_update(u)
                except Exception as e:
                    print("handler error", e, flush=True)
                try:
                    os.makedirs(DATA_DIR, exist_ok=True)
                    with open(os.path.join(DATA_DIR, "offset.txt"), "w", encoding="utf-8") as f:
                        f.write(str(offset))
                except Exception:
                    pass
        except Exception as e:
            print("poll error", e, flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
