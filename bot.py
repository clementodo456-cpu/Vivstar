import os
import json
import random
import logging
import html
from typing import Dict, Any, List

from dotenv import load_dotenv
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from database import DatabaseManager

# Environment & Setup
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PORT = int(os.getenv("PORT", "10000"))
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

# Questions Storage & Active Session State
QUESTIONS_DATA: List[Dict[str, Any]] = []
user_sessions: Dict[int, Dict[str, Any]] = {}

def load_questions():
    global QUESTIONS_DATA
    filepath = os.path.join(os.path.dirname(__file__), "questions.json")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            QUESTIONS_DATA = json.load(f)
        logger.info("Loaded %d questions successfully.", len(QUESTIONS_DATA))
    except Exception as e:
        logger.error("Error loading questions.json: %s", e)
        QUESTIONS_DATA = []

def get_categories() -> List[str]:
    categories = sorted(list({q["category"] for q in QUESTIONS_DATA}))
    return categories

# Helper UI Components
def main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("🎯 Start Quiz", callback_data="menu_start")],
        [InlineKeyboardButton("📚 Categories", callback_data="menu_categories"), InlineKeyboardButton("🏆 My Score", callback_data="menu_score")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="menu_leaderboard"), InlineKeyboardButton("ℹ️ Help", callback_data="menu_help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def build_categories_keyboard() -> InlineKeyboardMarkup:
    categories = get_categories()
    keyboard = []
    keyboard.append([InlineKeyboardButton("🎲 All Categories", callback_data="cat_ALL")])
    
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

# Core Quiz Logic
async def start_quiz_session(update: Update, context: ContextTypes.DEFAULT_TYPE, category: str = "ALL"):
    user = update.effective_user
    if not user:
        return

    # Filter & Shuffle Questions
    if category == "ALL":
        pool = QUESTIONS_DATA.copy()
    else:
        pool = [q for q in QUESTIONS_DATA if q["category"] == category]

    if not pool:
        msg = f"❌ No questions available for category: <b>{html.escape(category)}</b>"
        if update.callback_query:
            await update.callback_query.message.edit_text(msg, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())
        return

    # Select up to 10 questions
    selected_questions = random.sample(pool, min(len(pool), 10))
    
    # Process options for randomization per question
    processed_questions = []
    for q in selected_questions:
        opts = q["options"].copy()
        correct_text = opts[q["correct_option"]]
        random.shuffle(opts)
        new_correct_idx = opts.index(correct_text)
        
        processed_questions.append({
            "question": q["question"],
            "category": q["category"],
            "options": opts,
            "correct_option": new_correct_idx,
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

    total_q = len(questions)
    text = (
        f"<b>Category:</b> {html.escape(q_data['category'])}\n"
        f"<b>Question {q_idx + 1}/{total_q}</b>\n\n"
        f"❓ <b>{html.escape(q_data['question'])}</b>"
    )

    keyboard = []
    for idx, opt in enumerate(q_data["options"]):
        keyboard.append([InlineKeyboardButton(f"{chr(65+idx)}. {opt}", callback_data=f"ans_{idx}")])

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
        "Welcome to <b>@vivstartbot</b> — your interactive quiz platform!\n"
        "Test your knowledge across various subjects, track performance, and climb the leaderboard.\n\n"
        "Tap a button below to begin:"
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

async def cmd_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user:
        await db.get_or_create_user(user.id, user.first_name, user.last_name, user.username)
    await start_quiz_session(update, context, category="ALL")

async def cmd_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📚 <b>Select a Quiz Category:</b>\nChoose a subject to test your knowledge or select <i>All Categories</i>."
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=build_categories_keyboard())

async def cmd_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return

    stats = await db.get_user_stats(user.id)
    if not stats or stats["total_questions"] == 0:
        msg = "📊 <b>Your Statistics</b>\n\nYou haven't completed any quizzes yet! Start a quiz to track your score."
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
        msg = "🏆 <b>Leaderboard</b>\n\nNo records yet. Be the first to complete a quiz!"
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
        "• <b>/start</b> — Open main menu\n"
        "• <b>/quiz</b> — Instantly launch a quiz\n"
        "• <b>/categories</b> — Pick a specific topic\n"
        "• <b>/score</b> — Check your lifetime stats\n"
        "• <b>/leaderboard</b> — View top players\n"
        "• <b>/cancel</b> — Stop your active quiz\n\n"
        "<i>Each quiz consists of 10 randomized multiple-choice questions. Select your answer and view detailed explanations immediately!</i>"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and user.id in user_sessions:
        del user_sessions[user.id]
        await update.message.reply_text("🛑 Quiz cancelled. Returning to main menu.", reply_markup=main_menu_keyboard())
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
        f"👥 <b>Total Registered Users:</b> {admin_data['total_users']}\n"
        f"🎮 <b>Total Quizzes Played:</b> {admin_data['total_quizzes']}\n"
        f"❓ <b>Total Questions Served:</b> {admin_data['total_questions']}\n"
        f"✅ <b>Total Correct Answers:</b> {admin_data['total_correct']}"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

# Callback Router
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    data = query.data

    await db.get_or_create_user(user.id, user.first_name, user.last_name, user.username)

    if data == "menu_main":
        welcome_text = f"👋 Welcome back, <b>{html.escape(user.first_name)}</b>! Choose an option:"
        await query.message.edit_text(welcome_text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

    elif data == "menu_start":
        await start_quiz_session(update, context, category="ALL")

    elif data == "menu_categories":
        text = "📚 <b>Select a Quiz Category:</b>"
        await query.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=build_categories_keyboard())

    elif data == "menu_score":
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
        await query.message.edit_text(msg, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

    elif data == "menu_leaderboard":
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
        await query.message.edit_text(msg, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

    elif data == "menu_help":
        help_text = (
            "ℹ️ <b>Bot Help & Instructions</b>\n\n"
            "• 🎯 <b>Start Quiz</b>: Quick 10-question random quiz.\n"
            "• 📚 <b>Categories</b>: Pick your favorite subject.\n"
            "• 🏆 <b>Leaderboard</b>: Check top scores globally.\n\n"
            "<i>Use /cancel at any time during a quiz to return home.</i>"
        )
        await query.message.edit_text(help_text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

    elif data.startswith("cat_"):
        cat_name = data.split("cat_")[1]
        await start_quiz_session(update, context, category=cat_name)

    elif data.startswith("ans_"):
        session = user_sessions.get(user.id)
        if not session:
            await query.answer("⚠️ This session has expired. Please start a new quiz.", show_alert=True)
            return

        if session.get("answered"):
            await query.answer("You have already answered this question!", show_alert=True)
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
            correct_letter = chr(65 + q_data["correct_option"])
            correct_val = q_data["options"][q_data["correct_option"]]
            result_header = f"❌ <b>Incorrect!</b>\nCorrect Answer: <b>{correct_letter}. {html.escape(correct_val)}</b>"

        explanation = f"\n💡 <i>Explanation: {html.escape(q_data['explanation'])}</i>"
        
        updated_text = (
            f"<b>Category:</b> {html.escape(q_data['category'])}\n"
            f"<b>Question {q_idx + 1}/{len(session['questions'])}</b>\n\n"
            f"❓ <b>{html.escape(q_data['question'])}</b>\n\n"
            f"{result_header}\n"
            f"{explanation}"
        )

        is_last = (q_idx + 1 >= len(session["questions"]))
        next_button_text = "🎉 View Final Results" if is_last else "➡️ Next Question"
        next_cb = "quiz_finish" if is_last else "next_question"

        kb = InlineKeyboardMarkup([[InlineKeyboardButton(next_button_text, callback_data=next_cb)]])
        await query.message.edit_text(updated_text, parse_mode=ParseMode.HTML, reply_markup=kb)

    elif data == "next_question":
        session = user_sessions.get(user.id)
        if not session:
            await query.answer("Session expired. Please start a new quiz.", show_alert=True)
            return

        session["current_index"] += 1
        await send_quiz_question(update, context, user.id)

    elif data == "quiz_finish":
        session = user_sessions.get(user.id)
        if not session:
            await query.answer("Session expired.", show_alert=True)
            return

        score = session["score"]
        total_q = len(session["questions"])
        wrong = total_q - score
        pct = round((score / total_q) * 100)

        # Performance evaluation message
        if pct >= 90:
            perf = "🌟 Outstanding! You're a true genius!"
        elif pct >= 70:
            perf = "🎉 Great job! Keep up the good work!"
        elif pct >= 50:
            perf = "👍 Good effort! Practice to improve further."
        else:
            perf = "📘 Keep learning and try again!"

        # Save to SQLite
        await db.update_quiz_results(user.id, score, total_q)

        finish_text = (
            "🎉 <b>Quiz Complete!</b>\n\n"
            f"🎯 <b>Score:</b> {score}/{total_q}\n"
            f"✅ <b>Correct:</b> {score}\n"
            f"❌ <b>Wrong:</b> {wrong}\n"
            f"📊 <b>Percentage:</b> {pct}%\n\n"
            f"<i>{perf}</i>"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Play Again", callback_data="menu_start")],
            [InlineKeyboardButton("📚 Choose Category", callback_data="menu_categories")],
            [InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")]
        ])

        del user_sessions[user.id]
        await query.message.edit_text(finish_text, parse_mode=ParseMode.HTML, reply_markup=kb)

# Webhook & Health Check Server
async def init_web_app(ptb_app: Application):
    web_app = web.Application()

    async def health_check(request):
        return web.Response(text="Bot running cleanly.", status=200)

    async def telegram_webhook(request):
        data = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        await ptb_app.update_queue.put(update)
        return web.Response(text="OK", status=200)

    web_app.router.add_get("/", health_check)
    web_app.router.add_get("/health", health_check)
    web_app.router.add_post(f"/webhook/{BOT_TOKEN}", telegram_webhook)
    return web_app

# Error Handling
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled Exception while processing update:", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ An unexpected error occurred while processing your request. Please try again."
            )
        except Exception:
            pass

# Main Entry Point
def main():
    load_questions()

    ptb_app = Application.builder().token(BOT_TOKEN).build()

    # Handlers Registration
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

    async def on_startup(app: web.Application):
        await db.init_db()
        await ptb_app.initialize()
        await ptb_app.start()
        
        full_webhook_url = f"{WEBHOOK_URL.rstrip('/')}/webhook/{BOT_TOKEN}"
        await ptb_app.bot.set_webhook(url=full_webhook_url)
        logger.info("Set Telegram webhook to: %s", full_webhook_url)

    async def on_shutdown(app: web.Application):
        logger.info("Shutting down application...")
        await ptb_app.bot.delete_webhook()
        await ptb_app.stop()
        await ptb_app.shutdown()

    web_app = ptb_app.run_async if False else None  # Setup via custom runner below

    async def run():
        web_app = await init_web_app(ptb_app)
        web_app.on_startup.append(on_startup)
        web_app.on_shutdown.append(on_shutdown)
        
        runner = web.AppRunner(web_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", PORT)
        logger.info("Starting web server on port %d...", PORT)
        await site.start()
        
        # Keep app alive
        import asyncio
        await asyncio.Event().wait()

    import asyncio
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")

if __name__ == "__main__":
    main()
