from telegram import ReplyKeyboardMarkup
import database

def main_menu():
    return ReplyKeyboardMarkup([
        ["🔍 Ввести код камеры"],
        ["📁 Проекты"],
        ["📦 Паки камер"],
        ["🔐 Вход для админа"],
        ["📢 Наш канал"]
    ], resize_keyboard=True)

def admin_menu(is_master=False):
    buttons = [
        ["📤 Загрузить скриншот"],
        ["📦 Управление паками"],
        ["🔐 Сменить пароль"],
        ["✉️ Рассылка"],
        ["🚪 Выйти"]
    ]
    
    # Кнопка "Мои камеры" только для обычных админов
    if not is_master:
        buttons.insert(1, ["📷 Мои камеры"])
    else:
        buttons.insert(1, ["👑 Управление админами"])
        buttons.insert(2, ["📂 Управление вкладками"])
        buttons.insert(3, ["🚫 Управление банами"])
        buttons.insert(4, ["🔑 Коды от камер"])
        buttons.insert(5, ["🗑️ Удалить камеру"])
        buttons.insert(6, ["👥 Список пользователей"])
        buttons.insert(7, ["📁 Управление проектами"])
        buttons.insert(8, ["📊 Статистика рассылок"])
    
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)

def category_keyboard():
    categories = database.get_all_categories()
    keyboard = [categories[i:i+2] for i in range(0, len(categories), 2)]
    keyboard.append(["🔙 Назад"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_management_keyboard():
    return ReplyKeyboardMarkup([
        ["➕ Добавить админа", "➖ Удалить админа"],
        ["👥 Список админов"],
        ["🔙 Назад"]
    ], resize_keyboard=True)

def category_management_keyboard():
    return ReplyKeyboardMarkup([
        ["➕ Добавить вкладку", "➖ Удалить вкладку"],
        ["🔙 Назад"]
    ], resize_keyboard=True)

def ban_management_keyboard():
    return ReplyKeyboardMarkup([
        ["🚫 Забанить", "✅ Разбанить"],
        ["👥 Список забаненных"],
        ["🔙 Назад"]
    ], resize_keyboard=True)

def camera_codes_menu():
    return ReplyKeyboardMarkup([
        ["📊 Статистика по категориям"],
        ["📝 Список всех кодов"],
        ["🔙 Назад"]
    ], resize_keyboard=True)

def back_only_keyboard():
    return ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True)

def projects_menu():
    return ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True)

def project_management_keyboard():
    return ReplyKeyboardMarkup([
        ["📤 Загрузить проект"],
        ["📝 Список проектов"],
        ["🗑️ Удалить проект"],
        ["🔙 Назад"]
    ], resize_keyboard=True)

def packs_menu():
    return ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True)

def pack_management_keyboard(is_master=False):
    buttons = []
    buttons.append(["📤 Загрузить пак"])
    if is_master:
        buttons.append(["📦 Все паки"])
        buttons.append(["🗑️ Удалить пак"])
    else:
        buttons.append(["📦 Мои паки"])
    buttons.append(["🔙 Назад"])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)
