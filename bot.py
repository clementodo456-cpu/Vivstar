import asyncio
import os
import json
import random
import logging
import html
from typing import Dict, Any, List

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from database import DatabaseManager

# Environment Setup
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "data/quiz_bot.db")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is missing!")

db = DatabaseManager(DB_PATH)

# Session & Question Management
QUESTIONS_DATA: List[Dict[str, Any]] = []
user_sessions: Dict[int, Dict[str, Any]] = {}

def load_questions():
    global QUESTIONS_DATA
    filepath = os.path.join(os.path.dirname(__file__), "questions.json")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            QUESTIONS_DATA = json.load(f)
        logger.info("Loaded %d questions.", len(QUESTIONS_DATA))
    except Exception as e:
        logger.error("Failed to load questions.json: %s", e)
        QUESTIONS_DATA = []

def get_categories() -> List[str]:
    return sorted(list({q["category"] for q in QUESTIONS_DATA}))

# Keyboards
def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 Start Quiz", callback_data="menu_start")],
        [InlineKeyboardButton("📚 Categories", callback_data="menu_categories"), InlineKeyboardButton("🏆 My Score", callback_data="menu_score")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="menu_leaderboard"), InlineKeyboardButton("ℹ️ Help", callback_data="menu_help")]
    ])

def build_categories_keyboard() -> InlineKeyboardMarkup:
    categories = get_categories()
    keyboard = [[InlineKeyboardButton("🎲 All Categories", callback_data="cat_ALL")]]
    
    row = []
    for cat in categories:
        row.append(InlineKeyboardButton(f"📁 {cat}", callback_data=f"cat_{cat}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
        
    keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")])
    return InlineKeyboardMarkup(keyboard)

# Core Logic
async def start_quiz_session(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str = "ALL"):
    user = update.effective_user
    if not user:
        return

    pool = QUESTIONS_DATA if category == "ALL" else [q for q in QUESTIONS_DATA if q["category"] == category]

    if not pool:
        msg = f"❌ No questions available for category: <b>{html.escape(category)}</b>"
        if update.callback_query:
            await update.callback_query.message.edit_text(msg, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())
        return

    selected_questions = random.sample(pool, min(len(pool), 10))
    processed_questions = []
    
    for q in selected_questions:
        opts = q["options"].copy()
        correct_text = opts[q["correct_option"]]
        random.shuffle(opts)
        processed_questions.append({
            "question": q["question"],
            "category": q["category"],
            "options": opts,
            "correct_option": opts.index(correct_text),
            "explanation": q["explanation"]
        })

    user_sessions[user.id] = {
        "category": category,
        "questions": processed_questions,
        "current_index": 0,
        "score": 0,
        "answered": False
    }

    await send_quiz_question(update, context, user.id)

async def send_quiz_question(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    session = user_sessions.get(user_id)
    if not session:
        return

    q_idx = session["current_index"]
    questions = session["questions"]
    q_data = questions[q_idx]
    session["answered"] = False

    text = (
        f"<b>Category:</b> {html.escape(q_data['category'])}\n"
        f"<b>Question {q_idx + 1}/{len(questions)}</b>\n\n"
        f"❓ <b>{html.escape(q_data['question'])}</b>"
    )

    keyboard = [[InlineKeyboardButton(f"{chr(65+i)}. {opt}", callback_data=f"ans_{i}")] for i, opt in enumerate(q_data["options"])]
    markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query and update.callback_query.message:
        await update.callback_query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await context.bot.send_message(chat_id=user_id, text=text, parse_mode=ParseMode.HTML, reply_markup=markup)

# Command Handlers
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        await db.get_or_create_user(user.id, user.first_name, user.last_name, user.username)

    welcome_text = (
        f"👋 Hello, <b>{html.escape(user.first_name if user else 'Friend')}</b>!\n\n"
        "Welcome to <b>@vivstartbot</b>!\nTest your knowledge across various subjects and climb the leaderboard."
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        await db.get_or_create_user(user.id, user.first_name, user.last_name, user.username)
    await start_quiz_session(update, context, category="ALL")

async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📚 <b>Select a Quiz Category:</b>", parse_mode=ParseMode.HTML, reply_markup=build_categories_keyboard())

async def cmd_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    stats = await db.get_user_stats(user.id)
    if not stats or stats["total_questions"] == 0:
        msg = "📊 <b>Your Statistics</b>\n\nYou haven't completed any quizzes yet!"
    else:
        avg_pct = round((stats["correct_answers"] / stats["total_questions"]) * 100, 1)
        msg = (
            f"📊 <b>Statistics for {html.escape(user.first_name)}</b>\n\n"
            f"🎯 <b>Total Quizzes Played:</b> {stats['total_quizzes']}\n"
            f"❓ <b>Questions Answered:</b> {stats['total_questions']}\n"
            f"✅ <b>Correct Answers:</b> {stats['correct_answers']}\n"
            f"🏅 <b>Best Quiz Score:</b> {stats['best_score']}/10\n"
            f"📈 <b>Average Accuracy:</b> {avg_pct}%"
        )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    leaders = await db.get_leaderboard(limit=10)
    if not leaders:
        msg = "🏆 <b>Leaderboard</b>\n\nNo records available yet."
    else:
        msg = "🏆 <b>Top Quiz Masters</b>\n\n"
        medals = ["🥇", "🥈", "🥉"]
        for idx, row in enumerate(leaders):
            rank_icon = medals[idx] if idx < 3 else f"<b>{idx+1}.</b>"
            name = html.escape(row["first_name"] or row["username"] or "Anonymous")
            msg += f"{rank_icon} {name} — Best: <b>{row['best_score']}</b>/10 | Total Correct: {row['correct_answers']}\n"
            
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "ℹ️ <b>Bot Help & Instructions</b>\n\n"
        "• /start — Open main menu\n"
        "• /quiz — Launch a quiz\n"
        "• /categories — Pick a topic\n"
        "• /score — View lifetime stats\n"
        "• /leaderboard — Global rankings\n"
        "• /cancel — Stop active quiz"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and user.id in user_sessions:
        del user_sessions[user.id]
        await update.message.reply_text("🛑 Quiz cancelled.", reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text("You don't have an active quiz session.", reply_markup=main_menu_keyboard())

async def cmd_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized access.")
        return

    admin_data = await db.get_admin_stats()
    msg = (
        "🔒 <b>Admin System Analytics</b>\n\n"
        f"👥 Registered Users: {admin_data['total_users']}\n"
        f"🎮 Quizzes Played: {admin_data['total_quizzes']}\n"
        f"❓ Questions Served: {admin_data['total_questions']}\n"
        f"✅ Correct Answers: {admin_data['total_correct']}"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

# Callbacks
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    data = query.data
    await db.get_or_create_user(user.id, user.first_name, user.last_name, user.username)

    if data == "menu_main":
        await query.message.edit_text(f"👋 Welcome back, <b>{html.escape(user.first_name)}</b>!", parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

    elif data == "menu_start":
        await start_quiz_session(update, context, category="ALL")

    elif data == "menu_categories":
        await query.message.edit_text("📚 <b>Select a Quiz Category:</b>", parse_mode=ParseMode.HTML, reply_markup=build_categories_keyboard())

    elif data == "menu_score":
        stats = await db.get_user_stats(user.id)
        if not stats or stats["total_questions"] == 0:
            msg = "📊 <b>Your Statistics</b>\n\nNo quizzes played yet!"
        else:
            avg_pct = round((stats["correct_answers"] / stats["total_questions"]) * 100, 1)
            msg = (
                f"📊 <b>Stats for {html.escape(user.first_name)}</b>\n\n"
                f"🎯 Quizzes: {stats['total_quizzes']}\n"
                f"❓ Questions: {stats['total_questions']}\n"
                f"✅ Correct: {stats['correct_answers']}\n"
                f"🏅 Best: {stats['best_score']}/10\n"
                f"📈 Accuracy: {avg_pct}%"
            )
        await query.message.edit_text(msg, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

    elif data == "menu_leaderboard":
        leaders = await db.get_leaderboard(limit=10)
        msg = "🏆 <b>Top Quiz Masters</b>\n\n" if leaders else "🏆 No records yet."
        medals = ["🥇", "🥈", "🥉"]
        for idx, row in enumerate(leaders):
            rank_icon = medals[idx] if idx < 3 else f"<b>{idx+1}.</b>"
            name = html.escape(row["first_name"] or row["username"] or "Anonymous")
            msg += f"{rank_icon} {name} — Best: <b>{row['best_score']}</b>/10\n"
        await query.message.edit_text(msg, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

    elif data == "menu_help":
        await query.message.edit_text("ℹ️ Select an option from the menu to play or check your score.", parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

    elif data.startswith("cat_"):
        await start_quiz_session(update, context, category=data.split("cat_")[1])

    elif data.startswith("ans_"):
        session = user_sessions.get(user.id)
        if not session or session.get("answered"):
            return

        session["answered"] = True
        selected_idx = int(data.split("ans_")[1])
        q_idx = session["current_index"]
        q_data = session["questions"][q_idx]

        is_correct = (selected_idx == q_data["correct_option"])
        if is_correct:
            session["score"] += 1
            result_header = "✅ <b>Correct!</b>"
        else:
            correct_val = q_data["options"][q_data["correct_option"]]
            result_header = f"❌ <b>Incorrect!</b>\nCorrect: <b>{html.escape(correct_val)}</b>"

        updated_text = (
            f"<b>Category:</b> {html.escape(q_data['category'])}\n"
            f"<b>Question {q_idx + 1}/{len(session['questions'])}</b>\n\n"
            f"❓ <b>{html.escape(q_data['question'])}</b>\n\n"
            f"{result_header}\n\n"
            f"💡 <i>{html.escape(q_data['explanation'])}</i>"
        )

        is_last = (q_idx + 1 >= len(session["questions"]))
        next_button_text = "🎉 View Results" if is_last else "➡️ Next Question"
        next_cb = "quiz_finish" if is_last else "next_question"

        await query.message.edit_text(updated_text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(next_button_text, callback_data=next_cb)]]))

    elif data == "next_question":
        session = user_sessions.get(user.id)
        if session:
            session["current_index"] += 1
            await send_quiz_question(update, context, user.id)

    elif data == "quiz_finish":
        session = user_sessions.get(user.id)
        if not session:
            return

        score, total_q = session["score"], len(session["questions"])
        pct = round((score / total_q) * 100)
        await db.update_quiz_results(user.id, score, total_q)

        finish_text = (
            "🎉 <b>Quiz Complete!</b>\n\n"
            f"🎯 Score: {score}/{total_q} ({pct}%)\n"
            f"✅ Correct: {score} | ❌ Wrong: {total_q - score}"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Play Again", callback_data="menu_start")],
            [InlineKeyboardButton("📚 Categories", callback_data="menu_categories")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")]
        ])

        del user_sessions[user.id]
        await query.message.edit_text(finish_text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def post_init(application: Application) -> None:
    await db.init_db()
    logger.info("Database initialized successfully.")

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled Exception:", exc_info=context.error)

def main():
    load_questions()

    # Explicitly instantiate and set the asyncio event loop for Python 3.14+
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    ptb_app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    ptb_app.add_handler(CommandHandler("start", cmd_start))
    ptb_app.add_handler(CommandHandler("quiz", cmd_quiz))
    ptb_app.add_handler(CommandHandler("categories", cmd_categories))
    ptb_app.add_handler(CommandHandler("score", cmd_score))
    ptb_app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    ptb_app.add_handler(CommandHandler("help", cmd_help))
    ptb_app.add_handler(CommandHandler("cancel", cmd_cancel))
    ptb_app.add_handler(CommandHandler("stats", cmd_admin_stats))
    ptb_app.add_handler(CallbackQueryHandler(handle_callback_query))
    ptb_app.add_error_handler(global_error_handler)

    logger.info("Starting bot in Polling mode...")
    ptb_app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
