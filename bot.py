import json
import logging
import os
from pathlib import Path
from uuid import uuid4

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# --- Конфигурация ---
TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.environ.get("PORT", 8000))
GOALS_FILE = "goals.json"

# Состояния для диалога добавления цели
ASK_NAME, ASK_THRESHOLD, ASK_TYPE = range(3)

# --- Работа с файлом целей ---
def load_goals():
    if Path(GOALS_FILE).exists():
        with open(GOALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_goals(goals):
    with open(GOALS_FILE, "w", encoding="utf-8") as f:
        json.dump(goals, f, ensure_ascii=False, indent=2)

def build_status_keyboard(goals_list):
    buttons = []
    for goal in goals_list:
        name = goal["name"]
        buttons.append([
            InlineKeyboardButton(f"▶️ + {name}", callback_data=f"inc_{goal['id']}"),
            InlineKeyboardButton(f"◀️ - {name}", callback_data=f"dec_{goal['id']}")
        ])
    buttons.append([InlineKeyboardButton("➕ Добавить цель", callback_data="add_goal")])
    return InlineKeyboardMarkup(buttons)

# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    goals = load_goals()
    if chat_id not in goals:
        goals[chat_id] = []
        save_goals(goals)
    await update.message.reply_text(
        "Привет! 🎯 Я помогаю отслеживать годовые цели.\n"
        "Используйте /status, чтобы увидеть прогресс и управлять целями."
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    goals = load_goals()
    chat_goals = goals.get(chat_id, [])
    if not chat_goals:
        await update.message.reply_text("Целей пока нет. Нажмите /add_goal, чтобы добавить.")
        return

    text = "📊 Ваши цели на год:\n\n"
    for goal in chat_goals:
        name = goal["name"]
        cur = goal["current"]
        thr = goal["threshold"]
        direction = "≥" if goal["type"] == "more_than" else "≤"
        text += f"• {name}: {cur} / {thr} ({direction})\n"

    keyboard = build_status_keyboard(chat_goals)
    await update.message.reply_text(text, reply_markup=keyboard)

# --- Добавление цели (диалог) ---
async def add_goal_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text("Введите название цели:")
    else:
        await update.message.reply_text("Введите название цели:")
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["goal_name"] = update.message.text.strip()
    await update.message.reply_text("Введите пороговое значение (целое число, например: 100):")
    return ASK_THRESHOLD

async def ask_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        thr = int(update.message.text.strip())
        if thr <= 0:
            raise ValueError
        context.user_data["goal_threshold"] = thr
    except (ValueError, AttributeError):
        await update.message.reply_text("Пожалуйста, введите положительное целое число.")
        return ASK_THRESHOLD

    await update.message.reply_text(
        "Выберите тип цели:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎯 Больше чем (≥)", callback_data="type_more")],
            [InlineKeyboardButton("📦 Меньше чем (≤)", callback_data="type_less")]
        ])
    )
    return ASK_TYPE

async def ask_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    goal_type = "more_than" if query.data == "type_more" else "less_than"
    context.user_data["goal_type"] = goal_type

    chat_id = str(update.effective_chat.id)
    goals = load_goals()
    if chat_id not in goals:
        goals[chat_id] = []

    new_goal = {
        "id": str(uuid4()),
        "name": context.user_data["goal_name"],
        "threshold": context.user_data["goal_threshold"],
        "current": 0,
        "type": goal_type
    }
    goals[chat_id].append(new_goal)
    save_goals(goals)

    await query.edit_message_text(f"✅ Цель добавлена: *{new_goal['name']}*!", parse_mode="Markdown")
    return ConversationHandler.END

# --- Обработка нажатий кнопок ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = str(update.effective_chat.id)
    data = query.data

    goals = load_goals()
    chat_goals = goals.get(chat_id, [])

    if data == "add_goal":
        await add_goal_start(update, context)
        return

    if data.startswith("inc_") or data.startswith("dec_"):
        goal_id = data.split("_", 1)[1]
        for goal in chat_goals:
            if goal["id"] == goal_id:
                if data.startswith("inc_"):
                    goal["current"] += 1
                else:
                    goal["current"] = max(0, goal["current"] - 1)
                save_goals(goals)
                # Обновляем сообщение
                text = "📊 Ваши цели на год:\n\n"
                for g in chat_goals:
                    name = g["name"]
                    cur = g["current"]
                    thr = g["threshold"]
                    direction = "≥" if g["type"] == "more_than" else "≤"
                    text += f"• {name}: {cur} / {thr} ({direction})\n"
                await query.edit_message_text(text, reply_markup=build_status_keyboard(chat_goals))
                return
        await query.edit_message_text("❌ Цель не найдена.")
        return

# --- Главная функция запуска (webhook) ---
def main():
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
    )

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(add_goal_start, pattern="^add_goal$"),
            CommandHandler("add_goal", add_goal_start),
        ],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_THRESHOLD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_threshold)],
            ASK_TYPE: [CallbackQueryHandler(ask_type, pattern="^type_")],
        },
        fallbacks=[],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler))

    # Запуск через webhook (обязательно для Render)
    WEBHOOK_URL = os.getenv("WEBHOOK_URL")
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{WEBHOOK_URL}/{TOKEN}",
        url_path=TOKEN,
    )

if __name__ == "__main__":
    if os.getenv("RENDER"):
        main()
    else:
        # Для локального запуска (не используется на Render)
        print("Для локального запуска установите BOT_TOKEN в коде.")