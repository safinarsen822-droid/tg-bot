import os
from dotenv import load_dotenv

load_dotenv()

# Конфигурация бота
BOT_TOKEN = os.getenv("BOT_TOKEN")
if BOT_TOKEN is None:
    raise ValueError("BOT_TOKEN не найден в переменных окружения. Создайте .env файл с BOT_TOKEN=your_token_here")

# Часовой пояс по умолчанию (можно изменить через /timezone)
DEFAULT_TIMEZONE = "Europe/Moscow"

# Интервалы повторения в днях (исключены 90 и 180 дней как requested)
INTERVALS_DAYS = [1, 3, 7, 14, 30]

# Время суток для первых напоминаний (час, минута)
DEFAULT_REMINDER_TIME = (6, 0)  # 06:00

# Интервал опроса БД для проверки напоминаний (секунды)
SCHEDULER_INTERVAL = 60  # проверять каждую минуту

# Максимальная длина названия темы
MAX_TITLE_LENGTH = 200