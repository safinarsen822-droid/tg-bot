import logging
from datetime import datetime, timedelta
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from config import BOT_TOKEN, DEFAULT_TIMEZONE, INTERVALS_DAYS, MAX_TITLE_LENGTH, DEFAULT_REMINDER_TIME
from db import db

logger = logging.getLogger(__name__)

# Router для обработчиков
router = Router()

# Состояния FSM
class TopicStates(StatesGroup):
    waiting_for_topic = State()
    waiting_for_timezone = State()

# Тексты сообщений
START_TEXT = """
👋 Привет! Я бот для интервального повторения.

Как это работает:
1. Вы присылаете мне любую информацию, которую хотите запомнить (тему, факт, формулу и т.д.)
2. Я напомню вам повторить её через оптимальные интервалы: 1 день → 3 дня → 7 дней → 14 дней → 30 дней
3. Каждый раз, когда вы повторяете тему, интервал увеличивается
4. Если вы забыли - прогресс сбрасывается и мы начинаем сначала

Команды:
/start - это сообщение
/help - подробная помощь
/list - список ваших тем
/timezone <часовой_пояс> - настроить ваш часовой пояс (например, Europe/Moscow)

Просто отправьте мне сообщение - и я сохраню его как тему для повторения!
"""

HELP_TEXT = """
📚 Как работает интервальное повторение:

Этот бот использует алгоритм интервального повторения для эффективного запоминания информации.

Когда вы добавляете тему:
- Первое повторение: через 1 день
- Второе повторение: через 3 дня после первого  
- Третье повторение: через 7 дней после второго
- Четвёртое повторение: через 14 дней после третьего
- Пятое повторение: через 30 дней после четвёртого
- После пятого повторения тема считается выученной

Кнопки под напоминанием:
✅ Повторил - вы успешно вспомнили материал, переходим к следующему интервалу
😓 Забыл(а) - вы не вспомнили, прогресс сбрасывается на первое повторение
⏰ Отложить на 1 час - напомню снова через час, этап не меняется

Команды:
/start - приветствие и инструкция
/help - эта справка
/list - показать все ваши активные темы
/delete <ID> - удалить тему по ID
/pause <ID> - приостановить напоминания для темы
/resume <ID> - возобновить напоминания для темы
/timezone <пояс> - установить ваш часовой пояс (например, Europe/London, UTC+5)

Часовой пояс по умолчанию: Europe/Moscow (UTC+3)
"""

def format_time_remaining(dt: datetime) -> str:
    """Форматирование времени до напоминания в человекочитаемый вид."""
    if dt is None:
        return "неизвестно"
        
    now = datetime.now()
    diff = dt - now
    
    if diff.total_seconds() <= 0:
        return "сейчас"
    
    days = diff.days
    hours, remainder = divmod(diff.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days} дн.")
    if hours > 0:
        parts.append(f"{hours} ч.")
    if minutes > 0 and not days:  # показываем минуты только если меньше дня
        parts.append(f"{minutes} мин.")
    
    return " ".join(parts) if parts else "< 1 мин."

def get_stage_text(stage: int) -> str:
    """Получить текстовое описание этапа."""
    if stage < 0:
        return "неизвестно"
    if stage >= len(INTERVALS_DAYS):
        return f"выучено (этап {stage + 1}/{len(INTERVALS_DAYS)})"
    return f"этап {stage + 1}/{len(INTERVALS_DAYS)}"

# Обработчики команд
@router.message(CommandStart())
async def cmd_start(message: Message):
    """Обработчик команды /start."""
    if not message.text:
        await message.answer("Ошибка: пустое сообщение")
        return
        
    await message.answer(START_TEXT)
    # Регистрируем пользователя в БД
    await db.add_user(message.from_user.id)

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help."""
    if not message.text:
        await message.answer("Ошибка: пустое сообщение")
        return
        
    await message.answer(HELP_TEXT)

@router.message(Command("list"))
async def cmd_list(message: Message):
    """Обработчик команды /list - показать список тем."""
    if not message.text:
        await message.answer("Ошибка: пустое сообщение")
        return
        
    user_id = message.from_user.id
    topics = await db.get_user_topics(user_id)
    
    if not topics:
        await message.answer("📭 У вас пока нет тем для повторения. Отправьте мне любое сообщение - и я сохраню его как тему!")
        return
    
    active_topics = [t for t in topics if t[4] == 'active']  # status
    paused_topics = [t for t in topics if t[4] == 'paused']
    completed_topics = [t for t in topics if t[4] == 'completed']
    
    text = "📋 Ваши темы:\n\n"
    
    if active_topics:
        text += "🟢 Активные:\n"
        for topic in active_topics:
            topic_id, title, stage, next_review_at, status = topic
            try:
                next_review = datetime.fromisoformat(next_review_at)
                time_left = format_time_remaining(next_review)
                text += f"• {title}\n  {get_stage_text(stage)}, повторение: {time_left}\n\n"
            except (ValueError, TypeError):
                text += f"• {title}\n  {get_stage_text(stage)}, повторение: ошибка даты\n\n"
    
    if paused_topics:
        text += "⏸️ Приостановленные:\n"
        for topic in paused_topics:
            topic_id, title, stage, next_review_at, status = topic
            text += f"• {title} ({get_stage_text(stage)})\n"
        text += "\n"
    
    if completed_topics:
        text += "✅ Выученные:\n"
        for topic in completed_topics:
            topic_id, title, stage, next_review_at, status = topic
            text += f"• {title} (выучено)\n"
        text += "\n"
    
    text += "Используйте /delete <ID>, /pause <ID> или /resume <ID> для управления темами."
    
    await message.answer(text)

@router.message(Command("timezone"))
async def cmd_timezone(message: Message, command: Command):
    """Обработчик команды /timezone."""
    if not message.text:
        await message.answer("Ошибка: пустое сообщение")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Пожалуйста, укажите часовой пояс. Например:\n"
            "/timezone Europe/Moscow\n"
            "/timezone UTC+5\n"
            "/timezone America/New_York"
        )
        return
    
    timezone = args[1].strip()
    # Простая валидация - в реальном боте лучше использовать pytz или zoneinfo
    await db.add_user(message.from_user.id, timezone)
    await message.answer(f"✅ Часовой пояс установлен: {timezone}")

@router.message(Command("delete"))
async def cmd_delete(message: Message, command: Command):
    """Обработчик команды /delete."""
    if not message.text:
        await message.answer("Ошибка: пустое сообщение")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Пожалуйста, укажите ID темы для удаления: /delete <ID>")
        return
    
    try:
        topic_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом")
        return
    
    topic = await db.get_topic_by_id(topic_id)
    if topic is None:
        await message.answer(f"Тема с ID {topic_id} не найдена")
        return
    
    if topic[1] != message.from_user.id:  # user_id
        await message.answer("Вы можете удалять только свои темы")
        return
    
    await db.delete_topic(topic_id)
    await message.answer(f"🗑️ Тема с ID {topic_id} удалена")

@router.message(Command("pause"))
async def cmd_pause(message: Message, command: Command):
    """Обработчик команды /pause."""
    if not message.text:
        await message.answer("Ошибка: пустое сообщение")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Пожалуйста, укажите ID темы для приостановки: /pause <ID>")
        return
    
    try:
        topic_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом")
        return
    
    topic = await db.get_topic_by_id(topic_id)
    if topic is None:
        await message.answer(f"Тема с ID {topic_id} не найдена")
        return
    
    if topic[1] != message.from_user.id:  # user_id
        await message.answer("Вы можете приостанавливать только свои темы")
        return
    
    await db.pause_topic(topic_id)
    await message.answer(f"⏸️ Тема с ID {topic_id} приостановлена")

@router.message(Command("resume"))
async def cmd_resume(message: Message, command: Command):
    """Обработчик команды /resume."""
    if not message.text:
        await message.answer("Ошибка: пустое сообщение")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Пожалуйста, укажите ID темы для возобновления: /resume <ID>")
        return
    
    try:
        topic_id = int(args[1])
    except ValueError:
        await message.answer("ID должен быть числом")
        return
    
    topic = await db.get_topic_by_id(topic_id)
    if topic is None:
        await message.answer(f"Тема с ID {topic_id} не найдена")
        return
    
    if topic[1] != message.from_user.id:  # user_id
        await message.answer("Вы можете возобновлять только свои темы")
        return
    
    await db.resume_topic(topic_id)
    await message.answer(f"▶️ Тема с ID {topic_id} возобновлена")

# Обработчик обычных сообщений (добавление тем)
@router.message(F.text & ~F.text.startswith('/'))
async def handle_topic(message: Message):
    """Обработчик обычных текстовых сообщений - добавление новой темы."""
    if not message.text:
        await message.answer("Пожалуйста, отправьте непустое сообщение")
        return
    
    user_id = message.from_user.id
    title = message.text.strip()
    
    if not title:
        await message.answer("Пожалуйста, отправьте непустое сообщение")
        return
    
    if len(title) > MAX_TITLE_LENGTH:
        await message.answer(f"Тема слишком длинная. Максимум {MAX_TITLE_LENGTH} символов")
        return
    
    # Регистрируем пользователя
    await db.add_user(user_id)
    
    # Добавляем тему
    topic_id = await db.add_topic(user_id, title)
    
    # Вычисляем время первого повторения
    now = datetime.now()
    next_review = now.replace(hour=DEFAULT_REMINDER_TIME[0], minute=DEFAULT_REMINDER_TIME[1], second=0, microsecond=0)
    if next_review <= now:
        next_review += timedelta(days=1)
    next_review += timedelta(days=INTERVALS_DAYS[0])
    
    time_str = next_review.strftime("%d %B, %H:%M")
    await message.answer(
        f"✅ Добавил тему «{title}»\n"
        f"Первое повторение: {time_str}"
    )

# Обработчики callback-запросов от inline-кнопок
@router.callback_query(F.data.startswith("repeat_"))
async def handle_repeat(callback: CallbackQuery):
    """Обработчик кнопки 'Повторил'."""
    await callback.answer()
    
    try:
        topic_id = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка: неверный ID темы", show_alert=True)
        return
    
    topic = await db.get_topic_by_id(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    
    if topic[1] != callback.from_user.id:  # user_id
        await callback.answer("Это не ваша тема", show_alert=True)
        return
    
    current_stage = topic[4]  # stage
    
    # Обновляем этап
    await db.update_topic_stage(topic_id, current_stage + 1)
    
    # Получаем обновленную информацию
    updated_topic = await db.get_topic_by_id(topic_id)
    if updated_topic is not None:
        new_stage = updated_topic[4]
        new_status = updated_topic[6]
        
        if new_status == 'completed':
            try:
                await callback.message.edit_text(
                    f"🎉 Поздравляем! Тема «{topic[2]}» выучена!\n"
                    f"Вы успешно прошли все этапов повторения."
                )
            except Exception:
                # Если не удалось отредактировать сообщение, отправляем новое
                await callback.message.answer(
                    f"🎉 Поздравляем! Тема «{topic[2]}» выучена!\n"
                    f"Вы успешно прошли все этапов повторения."
                )
        else:
            now = datetime.now()
            next_review = now.replace(hour=DEFAULT_REMINDER_TIME[0], minute=DEFAULT_REMINDER_TIME[1], second=0, microsecond=0)
            if next_review <= now:
                next_review += timedelta(days=1)
            next_review += timedelta(days=INTERVALS_DAYS[new_stage])
            
            time_str = next_review.strftime("%d %B, %H:%M")
            try:
                await callback.message.edit_text(
                    f"✅ Отлично! Тема «{topic[2]}» повторена.\n"
                    f"Следующее повторение: {time_str}\n"
                    f"Этап: {get_stage_text(new_stage)}"
                )
            except Exception:
                # Если не удалось отредактировать сообщение, отправляем новое
                await callback.message.answer(
                    f"✅ Отлично! Тема «{topic[2]}» повторена.\n"
                    f"Следующее повторение: {time_str}\n"
                    f"Этап: {get_stage_text(new_stage)}"
                )
    else:
        try:
            await callback.message.edit_text("✅ Тема повторена!")
        except Exception:
            await callback.message.answer("✅ Тема повторена!")

@router.callback_query(F.data.startswith("forgot_"))
async def handle_forgot(callback: CallbackQuery):
    """Обработчик кнопки 'Забыл(а)'."""
    await callback.answer()
    
    try:
        topic_id = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка: неверный ID темы", show_alert=True)
        return
    
    topic = await db.get_topic_by_id(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    
    if topic[1] != callback.from_user.id:  # user_id
        await callback.answer("Это не ваша тема", show_alert=True)
        return
    
    # Сбрасываем этап на 0
    await db.reset_topic_stage(topic_id)
    
    try:
        await callback.message.edit_text(
            f"😓 Тема «{topic[2]}» отмечена как забытая.\n"
            f"Прогресс сброшен. Следующее повторение будет через 1 день."
        )
    except Exception:
        # Если не удалось отредактировать сообщение, отправляем новое
        await callback.message.answer(
            f"😓 Тема «{topic[2]}» отмечена как забытая.\n"
            f"Прогресс сброшен. Следующее повторение будет через 1 день."
        )

@router.callback_query(F.data.startswith("delay_"))
async def handle_delay(callback: CallbackQuery):
    """Обработчик кнопки 'Отложить на 1 час'."""
    await callback.answer()
    
    try:
        topic_id = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка: неверный ID темы", show_alert=True)
        return
    
    topic = await db.get_topic_by_id(topic_id)
    if topic is None:
        await callback.answer("Тема не найдена", show_alert=True)
        return
    
    if topic[1] != callback.from_user.id:  # user_id
        await callback.answer("Это не ваша тема", show_alert=True)
        return
    
    current_stage = topic[4]  # stage
    
    # Откладываем на 1 час, этап не меняется
    now = datetime.now()
    next_review = now + timedelta(hours=1)
    
    async with aiosqlite.connect(db.db_path) as db_conn:
        await db_conn.execute(
            f"UPDATE {db.TOPICS_TABLE} SET next_review_at = ? WHERE id = ?",
            (next_review.isoformat(), topic_id)
        )
        await db_conn.commit()
    
    time_str = next_review.strftime("%d %B, %H:%M")
    try:
        await callback.message.edit_text(
            f"⏰ Тема «{topic[2]}» отложена.\n"
            f"Следующее напоминание: {time_str}\n"
            f"Этап остался: {get_stage_text(current_stage)}"
        )
    except Exception:
        # Если не удалось отредактировать сообщение, отправляем новое
        await callback.message.answer(
            f"⏰ Тема «{topic[2]}» отложена.\n"
            f"Следующее напоминание: {time_str}\n"
            f"Этап остался: {get_stage_text(current_stage)}"
        )

# Функция для отправки напоминаний (будет вызываться из scheduler.py)
async def send_reminder(bot, topic_id: int):
    """Отправка напоминания о необходимости повторить тему."""
    topic = await db.get_topic_by_id(topic_id)
    if topic is None:
        logger.warning(f"Тема {topic_id} не найдена при отправке напоминания")
        return
    
    user_id = topic[1]  # user_id
    title = topic[2]    # title
    stage = topic[4]    # stage
    
    # Проверяем, не выучена ли уже тема
    if stage >= len(INTERVALS_DAYS):
        await db.mark_topic_completed(topic_id)
        return
    
    # Создаем inline-клавиатуру
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Повторил", callback_data=f"repeat_{topic_id}"),
            InlineKeyboardButton(text="😓 Забыл(а)", callback_data=f"forgot_{topic_id}"),
            InlineKeyboardButton(text="⏰ Отложить на 1 час", callback_data=f"delay_{topic_id}")
        ]
    ])
    
    try:
        await bot.send_message(
            user_id,
            f"🔁 Пора повторить: «{title}»",
            reply_markup=keyboard
        )
        logger.info(f"Отправлено напоминание для темы {topic_id} пользователю {user_id}")
    except Exception as e:
        logger.error(f"Не удалось отправить напоминание пользователю {user_id}: {e}")
        # Если пользователь заблокировал бота, помечаем тему как проблемную?
        # Пока просто логируем и продолжаем