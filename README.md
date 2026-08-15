# @vivstartbot - Telegram Quiz Bot

A fully functional, asynchronous Telegram Quiz Bot built with Python, `python-telegram-bot` (v21), `aiosqlite`, and `aiohttp`.

## Features
- 🎯 **Interactive Quizzes**: Randomized 10-question quiz rounds with instant evaluation and explanations.
- 📚 **Category Filtering**: General Knowledge, Science, Technology, History, Geography, Sports, Entertainment, and Math.
- 📊 **User Tracking**: Persistent SQLite storage tracking total quizzes, question counts, accuracies, and high scores.
- 🏆 **Global Leaderboard**: Ranking top players based on performance.
- 🔒 **Admin Command**: `/stats` command restricted to configured `ADMIN_ID`.
- 🚀 **Render Webhook Ready**: Built-in `aiohttp` web server with `/health` check support.

---

## Deployment Steps on Render.com

### 1. Bot Setup via BotFather
1. Open Telegram and search for `@BotFather`.
2. Send `/newbot` and follow the instructions to create `@vivstartbot`.
3. Copy the **HTTP API Token**.

### 2. Push Code to GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin [https://github.com/yourusername/vivstartbot.git](https://github.com/yourusername/vivstartbot.git)
git push -u origin main
