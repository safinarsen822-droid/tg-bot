import aiosqlite
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from config import DEFAULT_TIMEZONE, INTERVALS_DAYS

logger = logging.getLogger(__name__)

# Имена таблиц
TOPICS_TABLE = "topics"
USERS_TABLE = "users"

class Database:
    def __init__(self, db_path: str = "spaced_repetition.db"):
        self.db_path = db_path

    async def init_db(self):
        """Инициализация базы данных и создание таблиц, если они не существуют."""
        async with aiosqlite.connect(self.db_path) as db:
            # Таблица пользователей
            await db.execute(f"""
                CREATE TABLE IF NOT EXISTS {USERS_TABLE} (
                    user_id INTEGER PRIMARY KEY,
                    timezone TEXT NOT NULL,
                    created_at DATETIME NOT NULL
                )
            """)
            
            # Таблица тем
            await db.execute(f"""
                CREATE TABLE IF NOT EXISTS {TOPICS_TABLE} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    stage INTEGER NOT NULL DEFAULT 0,
                    next_review_at DATETIME NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    FOREIGN KEY (user_id) REFERENCES {USERS_TABLE} (user_id)
                )
            """)
            
            # Индексы для ускорения запросов
            await db.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_topics_user_id ON {TOPICS_TABLE} (user_id)
            """)
            await db.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_topics_next_review ON {TOPICS_TABLE} (next_review_at)
            """)
            await db.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_topics_status ON {TOPICS_TABLE} (status)
            """)
            
            await db.commit()
            logger.info("База данных инициализирована")

    async def add_user(self, user_id: int, timezone: str = DEFAULT_TIMEZONE):
        """Добавление нового пользователя или обновление его часового пояса."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(f"""
                INSERT OR REPLACE INTO {USERS_TABLE} (user_id, timezone, created_at)
                VALUES (?, ?, COALESCE((SELECT created_at FROM {USERS_TABLE} WHERE user_id = ?), ?))
            """, (user_id, timezone, user_id, datetime.now()))
            await db.commit()
            logger.debug(f"Пользователь {user_id} добавлен/обновлен с timezone {timezone}")

    async def get_user_timezone(self, user_id: int) -> str:
        """Получение часового пояса пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(f"""
                SELECT timezone FROM {USERS_TABLE} WHERE user_id = ?
            """, (user_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row and row[0] is not None else DEFAULT_TIMEZONE

    async def add_topic(self, user_id: int, title: str) -> int:
        """Добавление новой темы и возврат её ID."""
        now = datetime.now()
        # Первый повтор через INTERVALS_DAYS[0] дней в DEFAULT_REMINDER_TIME
        from config import DEFAULT_REMINDER_TIME
        next_review = now.replace(hour=DEFAULT_REMINDER_TIME[0], minute=DEFAULT_REMINDER_TIME[1], second=0, microsecond=0)
        if next_review <= now:
            next_review += timedelta(days=1)
        next_review += timedelta(days=INTERVALS_DAYS[0])
        
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(f"""
                INSERT INTO {TOPICS_TABLE} (user_id, title, created_at, stage, next_review_at, status)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, title, now, 0, next_review, 'active'))
            await db.commit()
            topic_id = cursor.lastrowid
            if topic_id is None:
                raise RuntimeError("Не удалось получить ID добавленной темы")
            logger.info(f"Добавлена тема '{title}' для пользователя {user_id} с ID {topic_id}")
            return topic_id

    async def get_active_topics_for_review(self) -> List[Tuple]:
        """Получение тем, требующих повторения прямо сейчас."""
        now = datetime.now()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(f"""
                SELECT id, user_id, title, stage, next_review_at
                FROM {TOPICS_TABLE}
                WHERE status = 'active' AND next_review_at <= ?
            """, (now,)) as cursor:
                rows = await cursor.fetchall()
                return [tuple(row) for row in rows] if rows else []

    async def get_topic_by_id(self, topic_id: int) -> Optional[Tuple]:
        """Получение темы по ID."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(f"""
                SELECT id, user_id, title, created_at, stage, next_review_at, status
                FROM {TOPICS_TABLE}
                WHERE id = ?
            """, (topic_id,)) as cursor:
                row = await cursor.fetchone()
                return tuple(row) if row else None

    async def get_user_topics(self, user_id: int, status: str = None) -> List[Tuple]:
        """Получение всех тем пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            if status:
                async with db.execute(f"""
                    SELECT id, title, stage, next_review_at, status
                    FROM {TOPICS_TABLE}
                    WHERE user_id = ? AND status = ?
                    ORDER BY created_at DESC
                """, (user_id, status)) as cursor:
                    rows = await cursor.fetchall()
                    return [tuple(row) for row in rows] if rows else []
            else:
                async with db.execute(f"""
                    SELECT id, title, stage, next_review_at, status
                    FROM {TOPICS_TABLE}
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                """, (user_id,)) as cursor:
                    rows = await cursor.fetchall()
                    return [tuple(row) for row in rows] if rows else []

    async def update_topic_stage(self, topic_id: int, new_stage: int):
        """Обновление этапа темы и расчёт следующего повторения."""
        async with aiosqlite.connect(self.db_path) as db:
            # Получаем текущую тему для расчёта next_review_at
            async with db.execute(f"""
                SELECT stage FROM {TOPICS_TABLE} WHERE id = ?
            """, (topic_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    logger.warning(f"Тема с ID {topic_id} не найдена")
                    return
                
                current_stage = row[0]
                # Если этап не изменился, ничего не делаем
                if current_stage == new_stage:
                    return
                    
                # Рассчитываем следующее повторение
                from config import DEFAULT_REMINDER_TIME
                now = datetime.now()
                next_review = now.replace(hour=DEFAULT_REMINDER_TIME[0], minute=DEFAULT_REMINDER_TIME[1], second=0, microsecond=0)
                if next_review <= now:
                    next_review += timedelta(days=1)
                
                # Добавляем интервалы дней в зависимости от нового этапа
                if new_stage < len(INTERVALS_DAYS):
                    # Ещё есть интервалы для повторения
                    days_to_add = INTERVALS_DAYS[new_stage]
                    next_review += timedelta(days=days_to_add)
                    new_status = 'active'
                else:
                    # Все интервалы пройдены - тема выучена
                    new_status = 'completed'
                    # Дляcompleted тем next_review_at можно не обновлять, но оставим текущее
                    # либо можно установить далеко в будущее
                    next_review = now + timedelta(days=365*10)  # 10 лет вперёд
                
                await db.execute(f"""
                    UPDATE {TOPICS_TABLE}
                    SET stage = ?, next_review_at = ?, status = ?
                    WHERE id = ?
                """, (new_stage, next_review, new_status, topic_id))
                await db.commit()
                logger.debug(f"Тема {topic_id} обновлена: stage={new_stage}, status={new_status}")

    async def reset_topic_stage(self, topic_id: int):
        """Сброс этапа темы на ноль (когда пользователь забыл)."""
        await self.update_topic_stage(topic_id, 0)

    async def pause_topic(self, topic_id: int):
        """Приостановка напоминаний для темы."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(f"""
                UPDATE {TOPICS_TABLE}
                SET status = 'paused'
                WHERE id = ?
            """, (topic_id,))
            await db.commit()
            logger.debug(f"Тема {topic_id} приостановлена")

    async def resume_topic(self, topic_id: int):
        """Возобновление напоминаний для темы."""
        async with aiosqlite.connect(self.db_path) as db:
            # Получаем текущий этап
            async with db.execute(f"""
                SELECT stage FROM {TOPICS_TABLE} WHERE id = ?
            """, (topic_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    stage = row[0]
                    # Рассчитываем следующее повторение с текущего этапа
                    from config import DEFAULT_REMINDER_TIME
                    now = datetime.now()
                    next_review = now.replace(hour=DEFAULT_REMINDER_TIME[0], minute=DEFAULT_REMINDER_TIME[1], second=0, microsecond=0)
                    if next_review <= now:
                        next_review += timedelta(days=1)
                    
                    if stage < len(INTERVALS_DAYS):
                        days_to_add = INTERVALS_DAYS[stage]
                        next_review += timedelta(days=days_to_add)
                        await db.execute(f"""
                            UPDATE {TOPICS_TABLE}
                            SET status = 'active', next_review_at = ?
                            WHERE id = ?
                        """, (next_review, topic_id))
                    else:
                        # Если все этапы пройдены, помечаем как completed
                        await db.execute(f"""
                            UPDATE {TOPICS_TABLE}
                            SET status = 'completed'
                            WHERE id = ?
                        """, (topic_id,))
                    await db.commit()
                    logger.debug(f"Тема {topic_id} возобновлена с этапом {stage}")

    async def delete_topic(self, topic_id: int):
        """Удаление темы."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(f"""
                DELETE FROM {TOPICS_TABLE}
                WHERE id = ?
            """, (topic_id,))
            await db.commit()
            logger.debug(f"Тема {topic_id} удалена")

    async def mark_topic_completed(self, topic_id: int):
        """Пометка темы как выученной (завершённой)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(f"""
                UPDATE {TOPICS_TABLE}
                SET status = 'completed'
                WHERE id = ?
            """, (topic_id,))
            await db.commit()
            logger.debug(f"Тема {topic_id} помечена как completed")

# Глобальный экземпляр базы данных
db = Database()