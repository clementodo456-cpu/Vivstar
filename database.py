import os
import aiosqlite
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    async def init_db(self):
        """Initialize SQLite database tables."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    last_name TEXT,
                    username TEXT,
                    total_quizzes INTEGER DEFAULT 0,
                    total_questions INTEGER DEFAULT 0,
                    correct_answers INTEGER DEFAULT 0,
                    best_score INTEGER DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()
            logger.info("Database initialized successfully at %s", self.db_path)

    async def get_or_create_user(self, user_id: int, first_name: str, last_name: str, username: str):
        """Fetch or register a user upon interaction."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                
            if not row:
                await db.execute(
                    """INSERT INTO users (user_id, first_name, last_name, username) 
                       VALUES (?, ?, ?, ?)""",
                    (user_id, first_name or "", last_name or "", username or "")
                )
            else:
                await db.execute(
                    """UPDATE users SET first_name = ?, last_name = ?, username = ? 
                       WHERE user_id = ?""",
                    (first_name or "", last_name or "", username or "", user_id)
                )
            await db.commit()

    async def update_quiz_results(self, user_id: int, score: int, questions_count: int = 10):
        """Update user performance statistics after a completed quiz."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT best_score FROM users WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                current_best = row[0] if row else 0

            new_best = max(current_best, score)

            await db.execute(
                """UPDATE users 
                   SET total_quizzes = total_quizzes + 1,
                       total_questions = total_questions + ?,
                       correct_answers = correct_answers + ?,
                       best_score = ?,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE user_id = ?""",
                (questions_count, score, new_best, user_id)
            )
            await db.commit()

    async def get_user_stats(self, user_id: int):
        """Retrieve individual user performance summary."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                return await cursor.fetchone()

    async def get_leaderboard(self, limit: int = 10):
        """Get top performing users sorted by best score and correct answers."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """SELECT first_name, username, best_score, correct_answers, total_quizzes 
                   FROM users 
                   ORDER BY best_score DESC, correct_answers DESC 
                   LIMIT ?""",
                (limit,)
            ) as cursor:
                return await cursor.fetchall()

    async def get_admin_stats(self):
        """Get platform-wide analytics for administration."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT 
                    COUNT(user_id) as total_users,
                    COALESCE(SUM(total_quizzes), 0) as total_quizzes,
                    COALESCE(SUM(total_questions), 0) as total_questions,
                    COALESCE(SUM(correct_answers), 0) as total_correct
                FROM users
            """) as cursor:
                row = await cursor.fetchone()
                return {
                    "total_users": row[0],
                    "total_quizzes": row[1],
                    "total_questions": row[2],
                    "total_correct": row[3]
                }
