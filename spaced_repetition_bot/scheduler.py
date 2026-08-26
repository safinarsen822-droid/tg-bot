import asyncio
import logging
from datetime import datetime
from aiogram import Bot
from config import BOT_TOKEN, SCHEDULER_INTERVAL
from db import db
from handlers import send_reminder

logger = logging.getLogger(__name__)

async def reminder_scheduler(bot: Bot):
    """Фоновая задача для проверки и отправки напоминаний."""
    logger.info("Планировщик напоминаний запущен")
    
    while True:
        try:
            # Получаем темы, требующих повторения
            topics = await db.get_active_topics_for_review()
            
            if topics:
                logger.info(f"Найдено {len(topics)} тем для повторения")
                
                for topic in topics:
                    topic_id = topic[0]
                    user_id = topic[1]
                    title = topic[2]
                    
                    # Отправляем напоминание
                    await send_reminder(bot, topic_id)
                    
                    # Небольшая задержка между отправками, чтобы не превысить лимиты Telegram
                    await asyncio.sleep(0.1)
            else:
                # Если нет тем для повторения, просто ждем
                pass
                
        except Exception as e:
            logger.error(f"Ошибка в планировщике напоминаний: {e}")
        
        # Ждем перед следующей проверкой
        await asyncio.sleep(SCHEDULER_INTERVAL)

def start_scheduler(bot: Bot):
    """Запуск планировщика в фоновой задаче."""
    asyncio.create_task(reminder_scheduler(bot))
    logger.info("Планировщик напоминаний запущен в фоне")