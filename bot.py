import json
import os
from pathlib import Path
from uuid import uuid4
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)

# === CONFIG ===
TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # Например: https://your-bot.up.railway.app
PORT = int(os.getenv("PORT", 8000))

# Используем /tmp — Railway сохраняет его между перезапусками
GOALS_FILE = "/tmp/goals.json"

# === STATES ===
ASK_NAME, ASK_THRESHOLD, ASK_TYPE = range(3)
EDIT_SELECT, EDIT_ACTION, EDIT_FIELD, EDIT_VALUE = range(3, 7)

# === DATA UTILS ===
def load_goals():
    if Path(GOALS_FILE).exists():
        with open(GOALS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_goals(data):
    with open(GOALS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def format_goals(goals):
    if not goals:
        return "🎯 Целей пока нет."
    text = "📊 Ваши цели:\n\n"
    for g in goals:
        name = g["name"]
        cur = g["current"]
        thr = g["threshold"]
        if g["type"] == "more_than":
            text += f"• {name}: {cur} из {thr}\n"
        else:
            remaining = max(0, thr - cur)
            text += f"• {name}: осталось {remaining} из {thr}\n"
    return text

def kb_main(goals):
    b = []
    for g in goals:
        n = g["name"]
        b.append([
            InlineKeyboardButton(f"➕ + {n}", callback_data=f"inc_{g['id']}"),
            InlineKeyboardButton(f"➖ - {n}", callback_data=f"dec_{g['id']}")
        ])
    b.append([InlineKeyboardButton("🆕 Добавить цель", callback_data="add_goal")])
    if goals:
        b.append([InlineKeyboardButton("✏️ Управление целями", callback_data="edit_start")])
    return InlineKeyboardMarkup(b)

# === HANDLERS ===
async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    chat_id = str(u.effective_chat.id)
    all_goals = load_goals()
    if chat_id not in all_goals:
        all_goals[chat_id] = []
        save_goals(all_goals)
    text = format_goals(all_goals[chat_id])
    await u.message.reply_text(text, reply_markup=kb_main(all_goals[chat_id]))

async def status(u: Update, c: ContextTypes.DEFAULT_TYPE):
    chat_id = str(u.effective_chat.id)
    goals = load_goals().get(chat_id, [])
    await u.message.reply_text(format_goals(goals), reply_markup=kb_main(goals))

# --- ADD ---
async def add_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    if q:
        await q.answer()
        await q.message.delete()
    await u.effective_chat.send_message("Название цели:")
    return ASK_NAME

async def ask_name(u: Update, c: ContextTypes.DEFAULT_TYPE):
    c.user_data["name"] = u.message.text.strip()
    await u.message.reply_text("Порог (целое число):")
    return ASK_THRESHOLD

async def ask_thr(u: Update, c: ContextTypes.DEFAULT_TYPE):
    try:
        thr = int(u.message.text.strip())
        c.user_data["thr"] = thr
    except:
        await u.message.reply_text("Число!")
        return ASK_THRESHOLD
    await u.message.reply_text("Тип:", reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Больше чем", callback_data="more")],
        [InlineKeyboardButton("📦 Меньше чем", callback_data="less")]
    ]))
    return ASK_TYPE

async def ask_type(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    typ = "more_than" if q.data == "more" else "less_than"
    chat_id = str(q.message.chat.id)
    all_goals = load_goals()
    if chat_id not in all_goals:
        all_goals[chat_id] = []
    all_goals[chat_id].append({
        "id": str(uuid4()),
        "name": c.user_data["name"],
        "threshold": c.user_data["thr"],
        "current": 0,
        "type": typ
    })
    save_goals(all_goals)
    goals = all_goals[chat_id]
    await q.message.chat.send_message(format_goals(goals), reply_markup=kb_main(goals))
    return ConversationHandler.END

# --- EDIT / DELETE ---
async def edit_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    chat_id = str(u.effective_chat.id)
    goals = load_goals().get(chat_id, [])
    if not goals:
        await q.edit_message_text("Нет целей.")
        return ConversationHandler.END
    buttons = [[InlineKeyboardButton(g["name"], callback_data=f"edit_select_{g['id']}")] for g in goals]
    buttons.append([InlineKeyboardButton("❌ Отмена", callback_data="edit_cancel")])
    await q.edit_message_text("Выберите цель:", reply_markup=InlineKeyboardMarkup(buttons))
    return EDIT_SELECT

async def edit_select(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    if q.data == "edit_cancel":
        await q.edit_message_text("Отменено.")
        return ConversationHandler.END
    goal_id = q.data.split("_", 2)[2]
    c.user_data["edit_goal_id"] = goal_id
    buttons = [
        [InlineKeyboardButton("✏️ Редактировать", callback_data="action_edit")],
        [InlineKeyboardButton("🗑️ Удалить", callback_data="action_delete")],
        [InlineKeyboardButton("❌ Отмена", callback_data="edit_cancel")]
    ]
    await q.edit_message_text("Что сделать?", reply_markup=InlineKeyboardMarkup(buttons))
    return EDIT_ACTION

async def edit_action(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    action = q.data
    if action == "edit_cancel":
        await q.edit_message_text("Отменено.")
        return ConversationHandler.END
    goal_id = c.user_data["edit_goal_id"]
    chat_id = str(q.message.chat.id)
    all_goals = load_goals()
    goals = all_goals.get(chat_id, [])
    if action == "action_delete":
        all_goals[chat_id] = [g for g in goals if g["id"] != goal_id]
        save_goals(all_goals)
        new_goals = all_goals[chat_id]
        await q.edit_message_text("✅ Цель удалена!", reply_markup=kb_main(new_goals))
        return ConversationHandler.END
    elif action == "action_edit":
        buttons = [
            [InlineKeyboardButton("🔤 Название", callback_data="field_name")],
            [InlineKeyboardButton("🔢 Порог", callback_data="field_threshold")],
            [InlineKeyboardButton("🔄 Тип", callback_data="field_type")],
            [InlineKeyboardButton("❌ Отмена", callback_data="edit_cancel")]
        ]
        await q.edit_message_text("Что изменить?", reply_markup=InlineKeyboardMarkup(buttons))
        return EDIT_FIELD

async def edit_field(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    if q.data == "edit_cancel":
        await q.edit_message_text("Отменено.")
        return ConversationHandler.END
    field = q.data.split("_", 1)[1]
    c.user_data["edit_field"] = field
    if field == "name":
        await q.edit_message_text("Введите новое название:")
        return EDIT_VALUE
    elif field == "threshold":
        await q.edit_message_text("Введите новый порог (целое число):")
        return EDIT_VALUE
    elif field == "type":
        await q.edit_message_text(
            "Выберите новый тип:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎯 Больше чем", callback_data="newtype_more")],
                [InlineKeyboardButton("📦 Меньше чем", callback_data="newtype_less")]
            ])
        )
        return EDIT_VALUE

async def edit_value(u: Update, c: ContextTypes.DEFAULT_TYPE):
    chat_id = str(u.effective_chat.id)
    all_goals = load_goals()
    goals = all_goals.get(chat_id, [])
    goal_id = c.user_data["edit_goal_id"]
    field = c.user_data["edit_field"]
    target = next((g for g in goals if g["id"] == goal_id), None)
    if not target:
        await u.effective_chat.send_message("Цель не найдена.")
        return ConversationHandler.END
    if field == "name":
        target["name"] = u.message.text.strip()
    elif field == "threshold":
        try:
            thr = int(u.message.text.strip())
            if thr <= 0:
                raise ValueError
            target["threshold"] = thr
        except:
            await u.effective_chat.send_message("Неверное число. Изменения отменены.")
            return ConversationHandler.END
    elif field == "type":
        q = u.callback_query
        await q.answer()
        new_type = "more_than" if q.data == "newtype_more" else "less_than"
        target["type"] = new_type
        await q.edit_message_text("✅ Тип изменён!")
    save_goals(all_goals)
    await u.effective_chat.send_message(format_goals(goals), reply_markup=kb_main(goals))
    return ConversationHandler.END

# --- BUTTONS ---
async def button(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    chat_id = str(u.effective_chat.id)
    data = q.data
    all_goals = load_goals()
    goals = all_goals.get(chat_id, [])
    if data == "add_goal":
        await add_start(u, c)
        return
    if data == "edit_start":
        await edit_start(u, c)
        return
    if data.startswith("edit_select_") or data in ("edit_cancel", "action_edit", "action_delete"):
        return
    if data.startswith("field_") or data.startswith("newtype_"):
        return
    if data.startswith("inc_") or data.startswith("dec_"):
        gid = data.split("_", 1)[1]
        for g in goals:
            if g["id"] == gid:
                g["current"] += 1 if data.startswith("inc_") else -1
                g["current"] = max(0, g["current"])
                save_goals(all_goals)
                await q.edit_message_text(format_goals(goals), reply_markup=kb_main(goals))
                return
        await q.edit_message_text("❌ Цель не найдена.")
        return

# === MAIN ===
def main():
    app = Application.builder().token(TOKEN).build()

    conv_add = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_start, pattern="^add_goal$")],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT, ask_name)],
            ASK_THRESHOLD: [MessageHandler(filters.TEXT, ask_thr)],
            ASK_TYPE: [CallbackQueryHandler(ask_type, pattern="^(more|less)$")]
        },
        fallbacks=[]
    )

    conv_edit = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_start, pattern="^edit_start$")],
        states={
            EDIT_SELECT: [CallbackQueryHandler(edit_select, pattern="^edit_select_|edit_cancel$")],
            EDIT_ACTION: [CallbackQueryHandler(edit_action, pattern="^action_(edit|delete)|edit_cancel$")],
            EDIT_FIELD: [CallbackQueryHandler(edit_field, pattern="^field_|edit_cancel$")],
            EDIT_VALUE: [
                MessageHandler(filters.TEXT, edit_value),
                CallbackQueryHandler(edit_value, pattern="^newtype_(more|less)$")
            ]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(conv_add)
    app.add_handler(conv_edit)
    app.add_handler(CallbackQueryHandler(button))

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}"
    )

if __name__ == "__main__":
    main()
