import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from db import db
from handlers import router
from scheduler import start_scheduler

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Основная функция запуска бота."""
    # Инициализация бота и диспетчера
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    # Регистрация роутера с обработчиками
    dp.include_router(router)
    
    # Инициализация базы данных
    await db.init_db()
    logger.info("База данных инициализирована")
    
    # Запуск планировщика напоминаний
    start_scheduler(bot)
    logger.info("Планировщик напоминаний запущен")
    
    # Запуск бота
    logger.info("Бот запущен и готов к работе")
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")