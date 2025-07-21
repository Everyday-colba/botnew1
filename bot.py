import logging
import asyncio
from telegram import Update, ReplyKeyboardRemove, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler
)
import database
import keyboards
import utils
import config
import os
import sqlite3
from telegram.error import TimedOut, NetworkError
import time
from collections import defaultdict
import datetime

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния
(
    SUBSCRIPTION_CHECK,
    LOGIN, PASSWORD, ADMIN_MENU,
    UPLOAD_CATEGORY, UPLOAD_PHOTO, UPLOAD_CAPTION, UPLOAD_CUSTOM_NAME,
    ADD_ADMIN, DEL_ADMIN,
    ADD_CATEGORY, DEL_CATEGORY,
    PARTICIPANT_CODE, NEW_PASSWORD,
    BAN_MANAGEMENT, BAN_USER_ID, UNBAN_USER_ID,
    CAMERA_CODES_MENU, STATS_VIEW, ALL_CODES_VIEW,
    DELETE_CAMERA, USER_LIST_VIEW, CATEGORY_MANAGEMENT,
    ADMIN_MANAGEMENT, ADD_ADMIN_NAME, ADD_ADMIN_PASSWORD,
    PROJECTS_MENU, PROJECT_MANAGEMENT, 
    UPLOAD_PROJECT_FILE, UPLOAD_PROJECT_CAPTION, UPLOAD_PROJECT_NAME,
    DELETE_PROJECT,
    PACKS_MENU, UPLOAD_PACK_FILE, UPLOAD_PACK_CAPTION, 
    UPLOAD_PACK_NAME, PACK_MANAGEMENT, DELETE_PACK,
    BROADCAST_MESSAGE, BROADCAST_HISTORY
) = range(40)

sessions = {}
message_counters = defaultdict(lambda: {'count': 0, 'last_reset': time.time(), 'blocked_until': 0})

async def send_photo_with_retry(update, photo_path, caption, max_retries=3):
    for attempt in range(max_retries):
        try:
            with open(photo_path, 'rb') as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=caption,
                    parse_mode='HTML'
                )
                return True
        except (TimedOut, NetworkError) as e:
            logger.warning(f"Ошибка при отправке фото (попытка {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
            else:
                logger.error(f"Не удалось отправить фото после {max_retries} попыток")
                return False
    return False

async def is_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Проверяет подписку пользователя на канал"""
    try:
        member = await context.bot.get_chat_member(
            chat_id=config.CHANNEL_ID, 
            user_id=user_id
        )
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

def check_rate_limit(user_id: int) -> bool:
    """Проверяет ограничение скорости (6 сообщений/секунду)"""
    current_time = time.time()
    counter = message_counters[user_id]
    
    # Сброс счетчика если прошло больше 1 секунды
    if current_time - counter['last_reset'] > 1:
        counter['count'] = 0
        counter['last_reset'] = current_time
    
    # Проверка блокировки
    if counter['blocked_until'] > current_time:
        return False
    
    # Увеличиваем счетчик
    counter['count'] += 1
    
    # Если превышен лимит - блокируем на 10 секунд
    if counter['count'] > 6:
        counter['blocked_until'] = current_time + 10
        return False
    
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Очищаем данные текущей сессии
    chat_id = update.effective_chat.id
    if chat_id in sessions:
        del sessions[chat_id]
    context.user_data.clear()
    
    user = update.effective_user
    user_id = user.id
    
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ConversationHandler.END
    
    database.add_user(
        user_id, 
        user.username, 
        user.first_name, 
        user.last_name
    )
    
    if database.is_banned(user_id):
        await update.message.reply_text("🚫 Вы заблокированы и не можете использовать бота.")
        return ConversationHandler.END
    
    # Проверка подписки
    if not await is_subscribed(user_id, context):
        await update.message.reply_text(
            "📢 Для использования бота необходимо подписаться на наш канал!\n"
            f"Ссылка: {config.CHANNEL_LINK}\n\n"
            "После подписки нажмите кнопку ниже 👇",
            reply_markup=ReplyKeyboardMarkup([["✅ Я подписался"]], resize_keyboard=True),
            disable_web_page_preview=True
        )
        return SUBSCRIPTION_CHECK
    
    await update.message.reply_text(
        "👋 Добро пожаловать в систему слива и выдачи камер!",
        reply_markup=keyboards.main_menu()
    )
    return PARTICIPANT_CODE

async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет подписку после нажатия кнопки"""
    user_id = update.effective_user.id
    
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return SUBSCRIPTION_CHECK
    
    if await is_subscribed(user_id, context):
        await update.message.reply_text(
            "✅ Отлично! Теперь вам доступны все функции бота!",
            reply_markup=keyboards.main_menu()
        )
        return PARTICIPANT_CODE
    else:
        await update.message.reply_text(
            "❌ Вы ещё не подписались на канал!\n"
            f"Ссылка: {config.CHANNEL_LINK}\n\n"
            "После подписки нажмите кнопку 👇",
            reply_markup=ReplyKeyboardMarkup([["✅ Я подписался"]], resize_keyboard=True),
            disable_web_page_preview=True
        )
        return SUBSCRIPTION_CHECK

async def show_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет ссылку на канал"""
    user_id = update.effective_user.id
    
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return PARTICIPANT_CODE
    
    await update.message.reply_text(
        f"📢 Наш канал: {config.CHANNEL_LINK}\n\n"
        "Подпишитесь, чтобы получать обновления и важную информацию!",
        disable_web_page_preview=True
    )
    return PARTICIPANT_CODE

async def participant_code_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return PARTICIPANT_CODE
    
    # Проверка подписки
    if not await is_subscribed(user_id, context):
        await update.message.reply_text(
            "❌ Для использования бота необходимо подписаться на наш канал!\n"
            f"Ссылка: {config.CHANNEL_LINK}\n\n"
            "После подписки нажмите кнопку 👇",
            reply_markup=ReplyKeyboardMarkup([["✅ Я подписался"]], resize_keyboard=True),
            disable_web_page_preview=True
        )
        return SUBSCRIPTION_CHECK
    
    await update.message.reply_text("🔢 Введите код камеры:")
    return PARTICIPANT_CODE

async def participant_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return PARTICIPANT_CODE
    
    # Проверка подписки
    if not await is_subscribed(user_id, context):
        await update.message.reply_text(
            "❌ Для использования бота необходимо подписаться на наш канал!\n"
            f"Ссылка: {config.CHANNEL_LINK}\n\n"
            "После подписки нажмите кнопку 👇",
            reply_markup=ReplyKeyboardMarkup([["✅ Я подписался"]], resize_keyboard=True),
            disable_web_page_preview=True
        )
        return SUBSCRIPTION_CHECK
    
    if database.is_banned(user_id):
        await update.message.reply_text("🚫 Вы заблокированы и не можете использовать бота.")
        return ConversationHandler.END
    
    text = update.message.text
    
    if text == "🔐 Вход для админа":
        return await admin_login(update, context)
    
    if text == "📢 Наш канал":
        return await show_channel(update, context)
    
    if text == "📁 Проекты":
        return await projects_menu(update, context)
    
    if text == "📦 Паки камер":
        return await packs_menu(update, context)
    
    code = text.strip().upper()
    camera = database.get_camera(code)
    
    if camera:
        image_path, caption, custom_name = camera
        try:
            formatted_caption = utils.format_caption(caption, custom_name)
            caption_text = f"📸 Камера: {code}\n\n{formatted_caption}"
            
            success = await send_photo_with_retry(update, image_path, caption_text)
            
            if not success:
                await update.message.reply_text(
                    "⚠️ Не удалось отправить фото. Попробуйте позже или обратитесь к администратору."
                )
                
        except FileNotFoundError:
            await update.message.reply_text("❌ Изображение не найдено. Обратитесь к администратору.")
    else:
        await update.message.reply_text("❌ Код не найден. Попробуйте еще раз.")
    
    return PARTICIPANT_CODE

async def admin_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return PARTICIPANT_CODE
    
    # Проверка подписки
    if not await is_subscribed(user_id, context):
        await update.message.reply_text(
            "❌ Для использования бота необходимо подписаться на наш канал!\n"
            f"Ссылка: {config.CHANNEL_LINK}\n\n"
            "После подписки нажмите кнопку 👇",
            reply_markup=ReplyKeyboardMarkup([["✅ Я подписался"]], resize_keyboard=True),
            disable_web_page_preview=True
        )
        return SUBSCRIPTION_CHECK
    
    await update.message.reply_text(
        "🔐 Введите ваш логин:",
        reply_markup=ReplyKeyboardRemove()
    )
    return LOGIN

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return LOGIN
    
    context.user_data['username'] = update.message.text
    await update.message.reply_text("🔑 Введите ваш пароль:")
    return PASSWORD

async def password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return PASSWORD
    
    username = context.user_data['username']
    password = update.message.text
    
    admin_exists = database.admin_exists(username)
    
    if admin_exists and database.verify_admin(username, password):
        is_master = database.is_master_admin(username)
        sessions[update.effective_chat.id] = username
        await update.message.reply_text(
            f"✅ Успешный вход, {'главный ' if is_master else ''}админ {username}!",
            reply_markup=keyboards.admin_menu(is_master)
        )
        return ADMIN_MENU
    else:
        if username in config.MASTER_ADMINS and not admin_exists:
            database.add_admin(username, password, is_master=True, display_name=username)
            sessions[update.effective_chat.id] = username
            await update.message.reply_text(
                f"🎉 Вы успешно зарегистрированы как главный админ {username}!",
                reply_markup=keyboards.admin_menu(True)
            )
            return ADMIN_MENU
        
        await update.message.reply_text("❌ Неверные данные. Попробуйте снова /start")
        return ConversationHandler.END

async def upload_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = sessions[update.effective_chat.id]
    is_master = database.is_master_admin(username)
    
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADMIN_MENU
    
    categories = database.get_all_categories()
    keyboard = [categories[i:i+2] for i in range(0, len(categories), 2)]
    keyboard.append(["🔙 Назад"])
    
    await update.message.reply_text(
        "📂 Выберите категорию для загрузки:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return UPLOAD_CATEGORY

async def upload_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return UPLOAD_CATEGORY
    
    text = update.message.text
    
    if text == "🔙 Назад":
        username = sessions[update.effective_chat.id]
        is_master = database.is_master_admin(username)
        await update.message.reply_text(
            "🔙 Возвращаемся в меню админа",
            reply_markup=keyboards.admin_menu(is_master))
        return ADMIN_MENU
    
    categories = database.get_all_categories()
    if text not in categories:
        await update.message.reply_text("❌ Выберите категорию из списка.")
        return UPLOAD_CATEGORY
    
    context.user_data['category'] = text
    await update.message.reply_text(
        "📤 Отправьте скриншот камеры:",
        reply_markup=ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True))
    return UPLOAD_PHOTO

async def upload_photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return UPLOAD_PHOTO
    
    if update.message.text == "🔙 Назад":
        return await back_to_admin_menu_from_upload(update, context)
    
    photo = await update.message.photo[-1].get_file()
    category = context.user_data['category']
    
    category_dir = f"cameras/{category}"
    os.makedirs(category_dir, exist_ok=True)
    
    file_id = utils.safe_filename(update.message.photo[-1].file_id)
    filename = f"{category_dir}/{file_id}.jpg"
    
    await photo.download_to_drive(filename)
    context.user_data['image_path'] = filename
    await update.message.reply_text(
        "✏️ Введите подпись для скриншота:",
        reply_markup=ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True))
    return UPLOAD_CAPTION

async def upload_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return UPLOAD_CAPTION
    
    if update.message.text == "🔙 Назад":
        return await back_to_admin_menu_from_upload(update, context)
    
    context.user_data['caption'] = update.message.text
    await update.message.reply_text(
        "🏷️ Хотите добавить специальное название для этой камеры? (если нет, отправьте 'нет')",
        reply_markup=ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True))
    return UPLOAD_CUSTOM_NAME

async def upload_custom_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return UPLOAD_CUSTOM_NAME
    
    if update.message.text == "🔙 Назад":
        return await back_to_admin_menu_from_upload(update, context)
    
    custom_name = None
    if update.message.text.lower() != 'нет':
        custom_name = update.message.text
    
    caption = context.user_data['caption']
    username = sessions[update.effective_chat.id]
    image_path = context.user_data['image_path']
    category = context.user_data['category']
    
    code = database.add_camera(username, category, image_path, caption, custom_name)
    is_master = database.is_master_admin(username)
    
    response = f"✅ Скриншот загружен!\n🔢 Код для доступа: {code}\n📂 Категория: {category}"
    if custom_name:
        response += f"\n🏷️ Название: {custom_name}"
    
    await update.message.reply_text(
        response,
        reply_markup=keyboards.admin_menu(is_master))
    return ADMIN_MENU

async def change_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADMIN_MENU
    
    await update.message.reply_text("🔑 Введите новый пароль:")
    return NEW_PASSWORD

async def new_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return NEW_PASSWORD
    
    new_password = update.message.text
    username = sessions[update.effective_chat.id]
    
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE admins SET password = ? WHERE username = ?', (new_password, username))
    conn.commit()
    conn.close()
    
    is_master = database.is_master_admin(username)
    await update.message.reply_text(
        "✅ Пароль успешно изменен!",
        reply_markup=keyboards.admin_menu(is_master))
    return ADMIN_MENU

async def admin_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADMIN_MENU
    
    await update.message.reply_text(
        "👑 Управление администраторами:",
        reply_markup=keyboards.admin_management_keyboard())
    return ADMIN_MANAGEMENT

async def add_admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADMIN_MANAGEMENT
    
    await update.message.reply_text("👤 Введите имя нового админа (видимое главным админам):")
    return ADD_ADMIN_NAME

async def add_admin_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADD_ADMIN_NAME
    
    context.user_data['new_admin_name'] = update.message.text
    await update.message.reply_text("👤 Введите логин нового админа:")
    return ADD_ADMIN

async def add_admin_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADD_ADMIN
    
    context.user_data['new_admin_username'] = update.message.text
    await update.message.reply_text("🔑 Введите пароль нового админа:")
    return ADD_ADMIN_PASSWORD

async def add_admin_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADD_ADMIN_PASSWORD
    
    password = update.message.text
    admin_name = context.user_data['new_admin_name']
    username = context.user_data['new_admin_username']
    
    # Добавляем админа как обычного (не главного)
    database.add_admin(username, password, display_name=admin_name)
    
    await update.message.reply_text(
        f"✅ Админ {admin_name} (@{username}) успешно добавлен!",
        reply_markup=keyboards.admin_management_keyboard())
    return ADMIN_MANAGEMENT

async def del_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADMIN_MANAGEMENT
    
    admins = database.get_all_admins()
    if not admins:
        await update.message.reply_text("❌ Нет других админов для удаления.")
        return await back_to_admin_menu(update, context)
    
    admins_text = "\n".join([f"- {admin[1]} (@{admin[0]})" for admin in admins])
    await update.message.reply_text(
        f"👥 Список админов:\n{admins_text}\n\n"
        "➖ Введите логин админа для удаления:",
        reply_markup=keyboards.back_only_keyboard())
    return DEL_ADMIN

async def del_admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return DEL_ADMIN
    
    if update.message.text == "🔙 Назад":
        return await back_to_admin_menu(update, context)
    
    admin_to_delete = update.message.text
    username = sessions[update.effective_chat.id]
    
    if admin_to_delete in config.MASTER_ADMINS:
        await update.message.reply_text("❌ Нельзя удалить главного админа!")
    elif admin_to_delete == username:
        await update.message.reply_text("❌ Нельзя удалить самого себя!")
    else:
        database.delete_admin(admin_to_delete)
        await update.message.reply_text(f"✅ Админ {admin_to_delete} удален!")
    
    return await back_to_admin_menu(update, context)

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADMIN_MANAGEMENT
    
    admins = database.get_all_admins()
    if not admins:
        await update.message.reply_text("👥 Список админов пуст.")
        return ADMIN_MANAGEMENT
    
    master_admins = config.MASTER_ADMINS
    admins_list = []
    for admin in admins:
        username, display_name = admin
        if username in master_admins:
            admins_list.append(f"👑 {display_name} (@{username}) - главный")
        else:
            admins_list.append(f"👤 {display_name} (@{username})")
    
    message = "👥 Список администраторов:\n\n" + "\n".join(admins_list)
    await update.message.reply_text(message)
    return ADMIN_MANAGEMENT

async def category_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADMIN_MENU
    
    await update.message.reply_text(
        "📂 Управление вкладками:",
        reply_markup=keyboards.category_management_keyboard())
    return CATEGORY_MANAGEMENT

async def add_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return CATEGORY_MANAGEMENT
    
    await update.message.reply_text("➕ Введите название новой вкладки:")
    return ADD_CATEGORY

async def add_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADD_CATEGORY
    
    new_category = update.message.text
    if database.add_category(new_category):
        await update.message.reply_text(
            f"✅ Вкладка '{new_category}' создана!",
            reply_markup=keyboards.category_management_keyboard())
        return CATEGORY_MANAGEMENT
    else:
        await update.message.reply_text(
            "❌ Такая вкладка уже существует!",
            reply_markup=keyboards.category_management_keyboard())
        return CATEGORY_MANAGEMENT

async def del_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return CATEGORY_MANAGEMENT
    
    categories = database.get_all_categories()
    if not categories:
        await update.message.reply_text("❌ Нет вкладок для удаления.")
        return await category_management(update, context)
    
    categories_text = "\n".join([f"- {cat}" for cat in categories])
    await update.message.reply_text(
        f"📂 Список вкладок:\n{categories_text}\n\n"
        "➖ Введите название вкладки для удаления:",
        reply_markup=keyboards.back_only_keyboard())
    return DEL_CATEGORY

async def del_category_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return DEL_CATEGORY
    
    text = update.message.text
    
    if text == "🔙 Назад":
        return await category_management(update, context)
    
    if database.delete_category(text):
        await update.message.reply_text(
            f"✅ Вкладка '{text}' удалена!",
            reply_markup=keyboards.category_management_keyboard())
        return CATEGORY_MANAGEMENT
    else:
        await update.message.reply_text(
            "❌ Не удалось удалить вкладку. Проверьте название.",
            reply_markup=keyboards.category_management_keyboard())
        return CATEGORY_MANAGEMENT

async def ban_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADMIN_MENU
    
    await update.message.reply_text(
        "🚫 Управление банами пользователей:",
        reply_markup=keyboards.ban_management_keyboard())
    return BAN_MANAGEMENT

async def ban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return BAN_MANAGEMENT
    
    await update.message.reply_text(
        "🚫 Введите ID пользователя для блокировки:",
        reply_markup=keyboards.back_only_keyboard())
    return BAN_USER_ID

async def unban_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return BAN_MANAGEMENT
    
    await update.message.reply_text(
        "✅ Введите ID пользователя для разблокировки:",
        reply_markup=keyboards.back_only_keyboard())
    return UNBAN_USER_ID

async def list_banned_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return BAN_MANAGEMENT
    
    banned_users = database.get_banned_users()
    
    if not banned_users:
        await update.message.reply_text("✅ Нет забаненных пользователей.")
    else:
        users_list = "\n".join([f"🆔 {user_id}" for user_id in banned_users])
        message = "🚫 Забаненные пользователи:\n\n" + users_list
        await update.message.reply_text(message)
    
    return BAN_MANAGEMENT

async def ban_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return BAN_USER_ID
    
    if update.message.text == "🔙 Назад":
        return await ban_management(update, context)
    
    try:
        user_id = int(update.message.text)
        database.ban_user(user_id)
        await update.message.reply_text(f"✅ Пользователь {user_id} заблокирован!")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Введите числовой ID.")
    
    return await ban_management(update, context)

async def unban_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return UNBAN_USER_ID
    
    if update.message.text == "🔙 Назад":
        return await ban_management(update, context)
    
    try:
        user_id = int(update.message.text)
        database.unban_user(user_id)
        await update.message.reply_text(f"✅ Пользователь {user_id} разблокирован!")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Введите числовой ID.")
    
    return await ban_management(update, context)

async def camera_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADMIN_MENU
    
    username = sessions[update.effective_chat.id]
    is_master = database.is_master_admin(username)
    
    if is_master:
        await update.message.reply_text(
            "🔑 Меню кодов от камер:",
            reply_markup=keyboards.camera_codes_menu())
        return CAMERA_CODES_MENU
    else:
        return await my_codes(update, context)

async def camera_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return CAMERA_CODES_MENU
    
    stats = database.get_camera_stats()
    if not stats:
        await update.message.reply_text("📭 Пока нет ни одной камеры.")
        return await camera_codes(update, context)
    
    stats_text = "📊 Статистика по категориям:\n\n"
    for category, count in stats:
        stats_text += f"📂 {category}: {count} камер\n"
    
    await update.message.reply_text(stats_text)
    return CAMERA_CODES_MENU

async def all_codes_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return CAMERA_CODES_MENU
    
    cameras = database.get_cameras_with_admin()
    if not cameras:
        await update.message.reply_text("📭 Пока нет ни одной камеры.")
        return await camera_codes(update, context)
    
    message = "📝 Список всех камер:\n\n"
    for code, category, custom_name, admin in cameras:
        cam_info = f"🔑 {code}\n📂 Категория: {category}\n👤 Админ: {admin}\n"
        if custom_name:
            cam_info += f"🏷️ Название: {custom_name}\n"
        cam_info += "\n"
        
        if len(message) + len(cam_info) > 4000:
            await update.message.reply_text(message)
            message = ""
        message += cam_info
    
    if message:
        await update.message.reply_text(message)
    
    return CAMERA_CODES_MENU

async def my_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADMIN_MENU
    
    username = sessions[update.effective_chat.id]
    cameras = database.get_cameras_by_admin(username)
    
    if not cameras:
        await update.message.reply_text("📭 У вас пока нет ни одной камеры.")
        return await back_to_admin_menu(update, context)
    
    message = "📝 Ваши камеры:\n\n"
    for code, category, custom_name in cameras:
        cam_info = f"🔑 {code}\n📂 Категория: {category}\n"
        if custom_name:
            cam_info += f"🏷️ Название: {custom_name}\n"
        cam_info += "\n"
        
        if len(message) + len(cam_info) > 4000:
            await update.message.reply_text(message)
            message = ""
        message += cam_info
    
    if message:
        await update.message.reply_text(message)
    
    return ADMIN_MENU

async def delete_camera_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADMIN_MENU
    
    await update.message.reply_text(
        "🗑️ Введите код камеры для удаления:",
        reply_markup=keyboards.back_only_keyboard())
    return DELETE_CAMERA

async def delete_camera_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return DELETE_CAMERA
    
    if update.message.text == "🔙 Назад":
        return await back_to_admin_menu(update, context)
    
    code = update.message.text.strip().upper()
    image_path = database.delete_camera(code)
    
    if image_path:
        try:
            if os.path.exists(image_path):
                os.remove(image_path)
        except Exception as e:
            logger.error(f"Ошибка при удалении файла: {e}")
        
        await update.message.reply_text(f"✅ Камера {code} успешно удалена!")
    else:
        await update.message.reply_text("❌ Камера с таким кодом не найдена.")
    
    return await back_to_admin_menu(update, context)

async def user_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADMIN_MENU
    
    users = database.get_all_users()
    
    if not users:
        await update.message.reply_text("📭 Нет зарегистрированных пользователей.")
        return await back_to_admin_menu(update, context)
    
    message = "👥 Список пользователей:\n\n"
    for user_id, username, first_name, last_name, is_banned in users:
        user_info = (
            f"🆔 ID: {user_id}\n"
            f"👤 Имя: {first_name or ''} {last_name or ''}\n"
            f"📛 Username: @{username or 'нет'}\n"
            f"🚫 Статус: {'Забанен' if is_banned else 'Активен'}\n"
            "────────────────────\n"
        )
        
        if len(message) + len(user_info) > 4000:
            await update.message.reply_text(message)
            message = ""
        message += user_info
    
    if message:
        await update.message.reply_text(
            message,
            reply_markup=keyboards.admin_menu(True))
    
    return ADMIN_MENU

async def back_to_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = sessions[update.effective_chat.id]
    is_master = database.is_master_admin(username)
    await update.message.reply_text(
        "🔙 Возвращаемся в меню админа",
        reply_markup=keyboards.admin_menu(is_master))
    return ADMIN_MENU

async def back_to_admin_menu_from_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Очищаем временные данные загрузки
    keys_to_remove = ['category', 'image_path', 'caption']
    for key in keys_to_remove:
        if key in context.user_data:
            del context.user_data[key]
    
    return await back_to_admin_menu(update, context)

async def back_to_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔙 Возвращаемся в главное меню",
        reply_markup=keyboards.main_menu())
    return PARTICIPANT_CODE

async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADMIN_MENU
    
    if update.effective_chat.id in sessions:
        del sessions[update.effective_chat.id]
    await update.message.reply_text(
        "👋 Вы вышли из системы админа.",
        reply_markup=keyboards.main_menu())
    return PARTICIPANT_CODE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return PARTICIPANT_CODE
    
    await update.message.reply_text(
        "Действие отменено.",
        reply_markup=keyboards.main_menu())
    return PARTICIPANT_CODE

# ====== ФУНКЦИИ ДЛЯ ПРОЕКТОВ ======

async def projects_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню проектов"""
    user_id = update.effective_user.id
    
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return PARTICIPANT_CODE
    
    projects = database.get_all_projects()
    if not projects:
        await update.message.reply_text(
            "📭 Пока нет проектов.",
            reply_markup=keyboards.projects_menu()
        )
        return PROJECTS_MENU
    
    # Сохраняем проекты в контексте для дальнейшего использования
    context.user_data['projects'] = {}
    keyboard = []
    
    for project in projects:
        project_id, display_name, caption, file_path = project
        formatted_name = utils.format_project_name(display_name)
        context.user_data['projects'][formatted_name] = project
        keyboard.append([formatted_name])
    
    keyboard.append(["🔙 Назад"])
    
    await update.message.reply_text(
        "📁 Выберите проект:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return PROJECTS_MENU

async def send_project(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет выбранный проект"""
    user_id = update.effective_user.id
    
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return PROJECTS_MENU
    
    text = update.message.text.strip()
    projects = context.user_data.get('projects', {})
    
    logger.info(f"Поиск проекта: '{text}'")
    logger.info(f"Доступные проекты: {list(projects.keys())}")
    
    # Получаем проект по отформатированному имени
    if text in projects:
        project_id, display_name, caption, file_path = projects[text]
        try:
            # Убедимся, что файл существует
            if not os.path.exists(file_path):
                logger.error(f"Файл проекта не найден: {file_path}")
                await update.message.reply_text("❌ Файл проекта не найден. Обратитесь к администратору.")
                return PROJECTS_MENU
            
            # Отправляем файл (ИСПРАВЛЕННЫЙ КОД)
            with open(file_path, 'rb') as file:
                await update.message.reply_document(
                    document=file,
                    caption=caption,
                    filename=os.path.basename(file_path)
                )
            logger.info(f"Проект '{display_name}' отправлен пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки проекта: {e}", exc_info=True)
            await update.message.reply_text("❌ Не удалось отправить проект. Обратитесь к администратору.")
    else:
        logger.warning(f"Проект не найден: '{text}'")
        await update.message.reply_text("❌ Проект не найден. Пожалуйста, выберите проект из списка.")
    
    return PROJECTS_MENU

async def project_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню управления проектами для главных админов"""
    username = sessions[update.effective_chat.id]
    if not database.is_master_admin(username):
        return await back_to_admin_menu(update, context)
    
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return ADMIN_MENU
    
    await update.message.reply_text(
        "📁 Управление проектами:",
        reply_markup=keyboards.project_management_keyboard())
    return PROJECT_MANAGEMENT

async def upload_project_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс загрузки проекта"""
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return PROJECT_MANAGEMENT
    
    await update.message.reply_text(
        "📤 Отправьте файл проекта (архив, документ):",
        reply_markup=ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True))
    return UPLOAD_PROJECT_FILE

async def upload_project_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает файл проекта"""
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return UPLOAD_PROJECT_FILE
    
    if not update.message.document:
        await update.message.reply_text("❌ Пожалуйста, отправьте файл как документ.")
        return UPLOAD_PROJECT_FILE
    
    # Получаем файл
    file = await update.message.document.get_file()
    
    # Создаем папку для проектов
    os.makedirs("projects", exist_ok=True)
    
    # Генерируем безопасное имя файла
    original_name = update.message.document.file_name
    safe_name = utils.safe_project_filename(original_name)
    file_path = f"projects/{safe_name}"
    
    # Скачиваем файл
    await file.download_to_drive(file_path)
    
    # Сохраняем путь к файлу
    context.user_data['project_file_path'] = file_path
    await update.message.reply_text("✏️ Введите подпись для проекта:")
    return UPLOAD_PROJECT_CAPTION

async def upload_project_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает подпись проекта"""
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return UPLOAD_PROJECT_CAPTION
    
    context.user_data['project_caption'] = update.message.text
    await update.message.reply_text("✏️ Введите название проекта (будет отображаться в меню):")
    return UPLOAD_PROJECT_NAME

async def upload_project_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает загрузку проекта"""
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return UPLOAD_PROJECT_NAME
    
    display_name = update.message.text
    file_path = context.user_data['project_file_path']
    caption = context.user_data['project_caption']
    
    # Сохраняем проект в базу
    database.add_project(file_path, caption, display_name)
    
    username = sessions[update.effective_chat.id]
    is_master = database.is_master_admin(username)
    await update.message.reply_text(
        f"✅ Проект '{display_name}' успешно загружен!",
        reply_markup=keyboards.admin_menu(is_master))
    return ADMIN_MENU

async def list_projects_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список проектов для админа"""
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return PROJECT_MANAGEMENT
    
    projects = database.get_all_projects()
    if not projects:
        await update.message.reply_text("📭 Пока нет проектов.")
        return PROJECT_MANAGEMENT
    
    message = "📁 Список проектов:\n\n"
    for project in projects:
        project_id, display_name, caption, file_path = project
        message += f"🆔 ID: {project_id}\n"
        message += f"📌 {display_name}\n"
        message += f"ℹ️ {caption}\n"
        message += f"📂 Файл: {os.path.basename(file_path)}\n"
        message += "────────────────────\n"
    
    await update.message.reply_text(message)
    return PROJECT_MANAGEMENT

async def delete_project_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс удаления проекта"""
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return PROJECT_MANAGEMENT
    
    await update.message.reply_text(
        "🗑️ Введите ID проекта для удаления:",
        reply_markup=keyboards.back_only_keyboard())
    return DELETE_PROJECT

async def delete_project_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает удаление проекта"""
    user_id = update.effective_user.id
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return DELETE_PROJECT
    
    if update.message.text == "🔙 Назад":
        return await back_to_project_management(update, context)
    
    try:
        project_id = int(update.message.text)
        project = database.get_project(project_id)
        
        if project:
            file_path = project[3]  # file_path находится на 4-й позиции
            database.delete_project(project_id)
            
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.error(f"Ошибка при удалении файла проекта: {e}")
            
            await update.message.reply_text(f"✅ Проект ID:{project_id} успешно удалён!")
        else:
            await update.message.reply_text("❌ Проект с таким ID не найден.")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Введите числовой ID проекта.")
    
    return await back_to_project_management(update, context)

async def back_to_projects_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню проектов"""
    await update.message.reply_text(
        "🔙 Возвращаемся в меню проектов",
        reply_markup=keyboards.projects_menu())
    return PROJECTS_MENU

async def back_to_project_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню управления проектами"""
    await update.message.reply_text(
        "🔙 Возвращаемся в управление проектами",
        reply_markup=keyboards.project_management_keyboard())
    return PROJECT_MANAGEMENT

# ====== ФУНКЦИИ ДЛЯ ПАКОВ КАМЕР ======

async def packs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню паков"""
    user_id = update.effective_user.id
    
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return PARTICIPANT_CODE
    
    packs = database.get_all_packs()
    if not packs:
        await update.message.reply_text(
            "📭 Пока нет паков камер.",
            reply_markup=keyboards.packs_menu()
        )
        return PACKS_MENU
    
    # Сохраняем паки в контексте
    context.user_data['packs'] = {}
    keyboard = []
    
    for pack in packs:
        pack_id, display_name, caption, file_path, admin_username = pack
        formatted_name = utils.format_pack_name(display_name)
        context.user_data['packs'][formatted_name] = pack
        keyboard.append([formatted_name])
    
    keyboard.append(["🔙 Назад"])
    
    await update.message.reply_text(
        "📦 Выберите пак камер:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return PACKS_MENU

async def send_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет выбранный пак"""
    user_id = update.effective_user.id
    
    # Проверка ограничения скорости
    if not check_rate_limit(user_id):
        await update.message.reply_text("⏳ Вы превысили лимит сообщений в секунду. Пожалуйста, подождите 10 секунд.")
        return PACKS_MENU
    
    text = update.message.text.strip()
    packs = context.user_data.get('packs', {})
    
    if text in packs:
        pack_id, display_name, caption, file_path, admin_username = packs[text]
        try:
            # Проверяем существование файла
            if not os.path.exists(file_path):
                await update.message.reply_text("❌ Файл пака не найден. Обратитесь к администратору.")
                return PACKS_MENU
            
            # Отправляем файл пака
            with open(file_path, 'rb') as file:
                await update.message.reply_document(
                    document=file,
                    caption=caption,
                    filename=os.path.basename(file_path))
        except Exception as e:
            logger.error(f"Ошибка отправки пака: {e}", exc_info=True)
            await update.message.reply_text("❌ Не удалось отправить пак. Обратитесь к администратору.")
    else:
        await update.message.reply_text("❌ Пак не найден. Пожалуйста, выберите пак из списка.")
    
    return PACKS_MENU

async def pack_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню управления паками"""
    username = sessions[update.effective_chat.id]
    is_master = database.is_master_admin(username)
    await update.message.reply_text(
        "📦 Управление паками камер:",
        reply_markup=keyboards.pack_management_keyboard(is_master))
    return PACK_MANAGEMENT

async def upload_pack_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает загрузку пака"""
    await update.message.reply_text(
        "📤 Отправьте файл пака камер (архив):",
        reply_markup=ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True))
    return UPLOAD_PACK_FILE

async def upload_pack_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает файл пака"""
    if not update.message.document:
        await update.message.reply_text("❌ Пожалуйста, отправьте файл как документ.")
        return UPLOAD_PACK_FILE
    
    file = await update.message.document.get_file()
    os.makedirs("packs", exist_ok=True)
    
    original_name = update.message.document.file_name
    safe_name = utils.safe_pack_filename(original_name)
    file_path = f"packs/{safe_name}"
    
    await file.download_to_drive(file_path)
    context.user_data['pack_file_path'] = file_path
    await update.message.reply_text("✏️ Введите описание для пака:")
    return UPLOAD_PACK_CAPTION

async def upload_pack_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает описание пака"""
    context.user_data['pack_caption'] = update.message.text
    await update.message.reply_text("✏️ Введите название пака (будет отображаться в меню):")
    return UPLOAD_PACK_NAME

async def upload_pack_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает загрузку пака"""
    display_name = update.message.text
    file_path = context.user_data['pack_file_path']
    caption = context.user_data['pack_caption']
    username = sessions[update.effective_chat.id]
    
    database.add_pack(file_path, caption, display_name, username)
    
    is_master = database.is_master_admin(username)
    await update.message.reply_text(
        f"✅ Пак '{display_name}' успешно загружен!",
        reply_markup=keyboards.admin_menu(is_master))
    return ADMIN_MENU

async def list_my_packs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список паков текущего админа"""
    username = sessions[update.effective_chat.id]
    packs = database.get_packs_by_admin(username)
    
    if not packs:
        await update.message.reply_text("📭 У вас пока нет паков.")
        return PACK_MANAGEMENT
    
    message = "📦 Ваши паки:\n\n"
    for pack in packs:
        pack_id, display_name, caption, file_path = pack
        message += f"🆔 ID: {pack_id}\n"
        message += f"📌 {display_name}\n"
        message += f"ℹ️ {caption}\n"
        message += f"📂 Файл: {os.path.basename(file_path)}\n"
        message += "────────────────────\n"
    
    await update.message.reply_text(message)
    return PACK_MANAGEMENT

async def list_all_packs_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список всех паков (для главных админов)"""
    packs = database.get_all_packs()
    if not packs:
        await update.message.reply_text("📭 Пока нет паков.")
        return PACK_MANAGEMENT
    
    message = "📦 Все паки:\n\n"
    for pack in packs:
        pack_id, display_name, caption, file_path, admin_username = pack
        message += f"🆔 ID: {pack_id}\n"
        message += f"📌 {display_name}\n"
        message += f"👤 Автор: {admin_username}\n"
        message += f"ℹ️ {caption}\n"
        message += f"📂 Файл: {os.path.basename(file_path)}\n"
        message += "────────────────────\n"
    
    await update.message.reply_text(message)
    return PACK_MANAGEMENT

async def delete_pack_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает удаление пака"""
    await update.message.reply_text(
        "🗑️ Введите ID пака для удаления:",
        reply_markup=keyboards.back_only_keyboard())
    return DELETE_PACK

async def delete_pack_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает удаление пака"""
    if update.message.text == "🔙 Назад":
        return await back_to_pack_management(update, context)
    
    try:
        pack_id = int(update.message.text)
        file_path = database.delete_pack(pack_id)
        
        if file_path:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                logger.error(f"Ошибка при удалении файла пака: {e}")
            
            await update.message.reply_text(f"✅ Пак ID:{pack_id} успешно удалён!")
        else:
            await update.message.reply_text("❌ Пак с таким ID не найден.")
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID. Введите числовой ID пака.")
    
    return await back_to_pack_management(update, context)

async def back_to_packs_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню паков"""
    await update.message.reply_text(
        "🔙 Возвращаемся в меню паков",
        reply_markup=keyboards.packs_menu())
    return PACKS_MENU

async def back_to_pack_management(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню управления паками"""
    username = sessions[update.effective_chat.id]
    is_master = database.is_master_admin(username)
    await update.message.reply_text(
        "🔙 Возвращаемся в управление паками",
        reply_markup=keyboards.pack_management_keyboard(is_master))
    return PACK_MANAGEMENT

# ====== ФУНКЦИЯ РАССЫЛКИ СООБЩЕНИЙ ======

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает рассылку сообщения"""
    await update.message.reply_text(
        "✉️ Введите сообщение для рассылки:",
        reply_markup=keyboards.back_only_keyboard())
    return BROADCAST_MESSAGE

async def broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выполняет рассылку сообщения"""
    username = sessions[update.effective_chat.id]
    is_master = database.is_master_admin(username)
    
    message_text = update.message.text
    
    users = database.get_active_users()
    
    await update.message.reply_text(f"⏳ Начинаю рассылку для {len(users)} пользователей...")
    
    success = 0
    errors = 0
    for user_id in users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📢 Важное сообщение!\n\n{message_text}"
            )
            success += 1
            await asyncio.sleep(0.1)  # Задержка для избежания ограничений
        except Exception as e:
            errors += 1
            logger.error(f"Ошибка рассылки для {user_id}: {e}")
    
    # Сохраняем запись о рассылке
    database.add_broadcast_record(username, message_text)
    
    await update.message.reply_text(
        f"✅ Рассылка завершена!\n"
        f"✔️ Успешно: {success}\n"
        f"❌ Ошибки: {errors}"
    )
    return await back_to_admin_menu(update, context)

async def broadcast_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает историю рассылок"""
    username = sessions[update.effective_chat.id]
    if not database.is_master_admin(username):
        return await back_to_admin_menu(update, context)

    history = database.get_broadcast_history()
    if not history:
        await update.message.reply_text("📭 История рассылок пуста.")
        return await back_to_admin_menu(update, context)

    message = "📊 История рассылок:\n\n"
    for record in history:
        record_id, admin_username, message_text, timestamp = record
        # Форматируем дату
        formatted_time = timestamp.split('.')[0] if isinstance(timestamp, str) else timestamp
        message += (
            f"⏱️ <b>Время:</b> {formatted_time}\n"
            f"👤 <b>Админ:</b> @{admin_username}\n"
            f"✉️ <b>Сообщение:</b>\n{message_text}\n"
            f"────────────────────\n"
        )

    # Разбиваем сообщение, если слишком длинное
    if len(message) > 4000:
        for x in range(0, len(message), 4000):
            await update.message.reply_text(message[x:x+4000], parse_mode='HTML')
    else:
        await update.message.reply_text(message, parse_mode='HTML')

    return await back_to_admin_menu(update, context)

# ====== ОСНОВНАЯ ФУНКЦИЯ ======

def main():
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SUBSCRIPTION_CHECK: [
                MessageHandler(filters.Regex(r'^✅ Я подписался$'), check_subscription)
            ],
            PARTICIPANT_CODE: [
                MessageHandler(filters.Regex(r'^🔍 Ввести код камеры$'), participant_code_input),
                MessageHandler(filters.Regex(r'^🔐 Вход для админа$'), admin_login),
                MessageHandler(filters.Regex(r'^📢 Наш канал$'), show_channel),
                MessageHandler(filters.Regex(r'^📁 Проекты$'), projects_menu),
                MessageHandler(filters.Regex(r'^📦 Паки камер$'), packs_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, participant_code)
            ],
            LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, login)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, password)],
            ADMIN_MENU: [
                MessageHandler(filters.Regex(r'^📤 Загрузить скриншот$'), upload_photo),
                MessageHandler(filters.Regex(r'^📷 Мои камеры$'), my_codes),  # Исправлено
                MessageHandler(filters.Regex(r'^📦 Управление паками$'), pack_management),
                MessageHandler(filters.Regex(r'^🔐 Сменить пароль$'), change_password),
                MessageHandler(filters.Regex(r'^✉️ Рассылка$'), broadcast_start),
                MessageHandler(filters.Regex(r'^🚪 Выйти$'), logout),
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_admin_menu),
                MessageHandler(filters.Regex(r'^👑 Управление админами$'), admin_management),
                MessageHandler(filters.Regex(r'^📂 Управление вкладками$'), category_management),
                MessageHandler(filters.Regex(r'^🚫 Управление банами$'), ban_management),
                MessageHandler(filters.Regex(r'^🔑 Коды от камер$'), camera_codes),
                MessageHandler(filters.Regex(r'^🗑️ Удалить камеру$'), delete_camera_start),
                MessageHandler(filters.Regex(r'^👥 Список пользователей$'), user_list),
                MessageHandler(filters.Regex(r'^📁 Управление проектами$'), project_management),
                MessageHandler(filters.Regex(r'^📊 Статистика рассылок$'), broadcast_history),
            ],
            ADMIN_MANAGEMENT: [
                MessageHandler(filters.Regex(r'^➕ Добавить админа$'), add_admin_handler),
                MessageHandler(filters.Regex(r'^➖ Удалить админа$'), del_admin),
                MessageHandler(filters.Regex(r'^👥 Список админов$'), list_admins),
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_admin_menu),
            ],
            ADD_ADMIN_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin_name)],
            ADD_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin_username)],
            ADD_ADMIN_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_admin_password)],
            UPLOAD_CATEGORY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, upload_category)
            ],
            UPLOAD_PHOTO: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_admin_menu_from_upload),  # Добавлено
                MessageHandler(filters.PHOTO, upload_photo_handler)
            ],
            UPLOAD_CAPTION: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_admin_menu_from_upload),  # Добавлено
                MessageHandler(filters.TEXT & ~filters.COMMAND, upload_caption)
            ],
            UPLOAD_CUSTOM_NAME: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_admin_menu_from_upload),  # Добавлено
                MessageHandler(filters.TEXT & ~filters.COMMAND, upload_custom_name)
            ],
            NEW_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, new_password)],
            DEL_ADMIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, del_admin_handler)],
            ADD_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_category_handler)],
            DEL_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, del_category_handler)],
            BAN_MANAGEMENT: [
                MessageHandler(filters.Regex(r'^🚫 Забанить$'), ban_user),
                MessageHandler(filters.Regex(r'^✅ Разбанить$'), unban_user),
                MessageHandler(filters.Regex(r'^👥 Список забаненных$'), list_banned_users),
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_admin_menu),
            ],
            BAN_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ban_user_handler)],
            UNBAN_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, unban_user_handler)],
            CAMERA_CODES_MENU: [
                MessageHandler(filters.Regex(r'^📊 Статистика по категориям$'), camera_stats),
                MessageHandler(filters.Regex(r'^📝 Список всех кодов$'), all_codes_list),
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_admin_menu),
            ],
            DELETE_CAMERA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, delete_camera_handler)
            ],
            CATEGORY_MANAGEMENT: [
                MessageHandler(filters.Regex(r'^➕ Добавить вкладку$'), add_category),
                MessageHandler(filters.Regex(r'^➖ Удалить вкладку$'), del_category),
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_admin_menu),
            ],
            PROJECTS_MENU: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_main_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, send_project)
            ],
            PROJECT_MANAGEMENT: [
                MessageHandler(filters.Regex(r'^📤 Загрузить проект$'), upload_project_start),
                MessageHandler(filters.Regex(r'^📝 Список проектов$'), list_projects_admin),
                MessageHandler(filters.Regex(r'^🗑️ Удалить проект$'), delete_project_start),
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_admin_menu),
            ],
            UPLOAD_PROJECT_FILE: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_project_management),
                MessageHandler(filters.Document.ALL, upload_project_file)
            ],
            UPLOAD_PROJECT_CAPTION: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_project_management),
                MessageHandler(filters.TEXT & ~filters.COMMAND, upload_project_caption)
            ],
            UPLOAD_PROJECT_NAME: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_project_management),
                MessageHandler(filters.TEXT & ~filters.COMMAND, upload_project_name)
            ],
            DELETE_PROJECT: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_project_management),
                MessageHandler(filters.TEXT & ~filters.COMMAND, delete_project_handler)
            ],
            PACKS_MENU: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_main_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, send_pack)
            ],
            PACK_MANAGEMENT: [
                MessageHandler(filters.Regex(r'^📤 Загрузить пак$'), upload_pack_start),
                MessageHandler(filters.Regex(r'^📦 Мои паки$'), list_my_packs),
                MessageHandler(filters.Regex(r'^📦 Все паки$'), list_all_packs_admin),
                MessageHandler(filters.Regex(r'^🗑️ Удалить пак$'), delete_pack_start),
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_admin_menu),
            ],
            UPLOAD_PACK_FILE: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_pack_management),
                MessageHandler(filters.Document.ALL, upload_pack_file)
            ],
            UPLOAD_PACK_CAPTION: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_pack_management),
                MessageHandler(filters.TEXT & ~filters.COMMAND, upload_pack_caption)
            ],
            UPLOAD_PACK_NAME: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_pack_management),
                MessageHandler(filters.TEXT & ~filters.COMMAND, upload_pack_name)
            ],
            DELETE_PACK: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_pack_management),
                MessageHandler(filters.TEXT & ~filters.COMMAND, delete_pack_handler)
            ],
            BROADCAST_MESSAGE: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_admin_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_message)
            ],
            BROADCAST_HISTORY: [
                MessageHandler(filters.Regex(r'^🔙 Назад$'), back_to_admin_menu),
            ],
        },
        fallbacks=[
            CommandHandler('start', start),  # Обработка в любом состоянии
            CommandHandler('cancel', cancel)
        ]
    )
    
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)
    application.run_polling()

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    
    try:
        if update and update.effective_chat:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="⚠️ Произошла ошибка при обработке вашего запроса. Пожалуйста, попробуйте позже."
            )
    except:
        pass

if __name__ == '__main__':
    main()
