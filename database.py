import sqlite3
import os
import config
import random
import string
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        is_master BOOLEAN DEFAULT 0,
        display_name TEXT
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS cameras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        category TEXT NOT NULL,
        image_path TEXT NOT NULL,
        caption TEXT NOT NULL,
        custom_name TEXT,
        admin_id INTEGER NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (admin_id) REFERENCES admins(id)
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS banned_users (
        user_id INTEGER PRIMARY KEY
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS categories (
        name TEXT PRIMARY KEY
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT NOT NULL,
        caption TEXT NOT NULL,
        display_name TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS packs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_path TEXT NOT NULL,
        caption TEXT NOT NULL,
        display_name TEXT NOT NULL,
        admin_username TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Удаляем старую таблицу broadcasts, если она есть, и создаем новую
    cursor.execute('DROP TABLE IF EXISTS broadcasts')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS broadcasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_username TEXT NOT NULL,
        message_text TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    default_categories = ['PTZ', 'Динамики', 'Для слива']
    for category in default_categories:
        cursor.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (category,))
    
    conn.commit()
    conn.close()
    
    for category in default_categories:
        os.makedirs(f"cameras/{category}", exist_ok=True)
    
    os.makedirs("projects", exist_ok=True)
    os.makedirs("packs", exist_ok=True)

def add_admin(username, password, is_master=False, display_name=None):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO admins (username, password, is_master, display_name) 
            VALUES (?, ?, ?, ?)
        ''', (username, password, int(is_master), display_name))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def verify_admin(username, password):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM admins WHERE username = ? AND password = ?', (username, password))
    admin = cursor.fetchone()
    conn.close()
    return bool(admin)

def is_master_admin(username):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT is_master FROM admins WHERE username = ?', (username,))
    result = cursor.fetchone()
    conn.close()
    return bool(result[0]) if result else False

def admin_exists(username):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM admins WHERE username = ?', (username,))
    result = cursor.fetchone()
    conn.close()
    return bool(result)

def add_camera(admin_username, category, image_path, caption, custom_name=None):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    
    cursor.execute('SELECT id FROM admins WHERE username = ?', (admin_username,))
    admin_id = cursor.fetchone()[0]
    
    cursor.execute('''
    INSERT INTO cameras (code, category, image_path, caption, custom_name, admin_id)
    VALUES (?, ?, ?, ?, ?, ?)
    ''', (code, category, image_path, caption, custom_name, admin_id))
    
    conn.commit()
    conn.close()
    return code

def get_camera(code):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
    SELECT image_path, caption, custom_name 
    FROM cameras 
    WHERE code = ?
    ''', (code,))
    result = cursor.fetchone()
    conn.close()
    return result

def get_all_admins():
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT username, display_name FROM admins')
    result = cursor.fetchall()
    conn.close()
    return result

def delete_admin(username):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM admins WHERE username = ?', (username,))
    conn.commit()
    conn.close()

def get_camera_stats():
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT category, COUNT(*) as count 
        FROM cameras 
        GROUP BY category
    ''')
    stats = cursor.fetchall()
    conn.close()
    return stats

def get_cameras_with_admin():
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT cameras.code, cameras.category, cameras.custom_name, admins.username 
        FROM cameras 
        JOIN admins ON cameras.admin_id = admins.id
    ''')
    cameras = cursor.fetchall()
    conn.close()
    return cameras

def get_cameras_by_admin(username):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT cameras.code, cameras.category, cameras.custom_name 
        FROM cameras 
        JOIN admins ON cameras.admin_id = admins.id
        WHERE admins.username = ?
    ''', (username,))
    cameras = cursor.fetchall()
    conn.close()
    return cameras

def delete_camera(code):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT image_path FROM cameras WHERE code = ?', (code,))
    result = cursor.fetchone()
    image_path = result[0] if result else None
    
    cursor.execute('DELETE FROM cameras WHERE code = ?', (code,))
    conn.commit()
    conn.close()
    
    return image_path

def ban_user(user_id):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)', (user_id,))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM banned_users WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def is_banned(user_id):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM banned_users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return bool(result)

def get_banned_users():
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM banned_users')
    result = [row[0] for row in cursor.fetchall()]
    conn.close()
    return result

def add_user(user_id, username, first_name, last_name):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO users (user_id, username, first_name, last_name)
        VALUES (?, ?, ?, ?)
    ''', (user_id, username, first_name, last_name))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.user_id, u.username, u.first_name, u.last_name, 
               CASE WHEN b.user_id IS NOT NULL THEN 1 ELSE 0 END AS is_banned
        FROM users u
        LEFT JOIN banned_users b ON u.user_id = b.user_id
    ''')
    users = cursor.fetchall()
    conn.close()
    return users

def add_category(category_name):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO categories (name) VALUES (?)', (category_name,))
        conn.commit()
        os.makedirs(f"cameras/{category_name}", exist_ok=True)
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_category(category_name):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM categories WHERE name = ?', (category_name,))
    conn.commit()
    conn.close()
    return True

def get_all_categories():
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT name FROM categories')
    categories = [row[0] for row in cursor.fetchall()]
    conn.close()
    return categories

def add_project(file_path, caption, display_name):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO projects (file_path, caption, display_name)
        VALUES (?, ?, ?)
    ''', (file_path, caption, display_name))
    conn.commit()
    conn.close()

def get_all_projects():
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, display_name, caption, file_path FROM projects')
    projects = cursor.fetchall()
    conn.close()
    return projects

def get_project(project_id):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM projects WHERE id = ?', (project_id,))
    project = cursor.fetchone()
    conn.close()
    return project

def delete_project(project_id):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT file_path FROM projects WHERE id = ?', (project_id,))
    result = cursor.fetchone()
    file_path = result[0] if result else None
    
    cursor.execute('DELETE FROM projects WHERE id = ?', (project_id,))
    conn.commit()
    conn.close()
    
    return file_path

def add_pack(file_path, caption, display_name, admin_username):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO packs (file_path, caption, display_name, admin_username)
        VALUES (?, ?, ?, ?)
    ''', (file_path, caption, display_name, admin_username))
    conn.commit()
    conn.close()

def get_packs_by_admin(admin_username):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, display_name, caption, file_path FROM packs WHERE admin_username = ?', (admin_username,))
    packs = cursor.fetchall()
    conn.close()
    return packs

def get_all_packs():
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, display_name, caption, file_path, admin_username FROM packs')
    packs = cursor.fetchall()
    conn.close()
    return packs

def delete_pack(pack_id):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT file_path FROM packs WHERE id = ?', (pack_id,))
    result = cursor.fetchone()
    file_path = result[0] if result else None
    
    cursor.execute('DELETE FROM packs WHERE id = ?', (pack_id,))
    conn.commit()
    conn.close()
    
    return file_path

def get_active_users():
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id FROM users 
        WHERE user_id NOT IN (SELECT user_id FROM banned_users)
    ''')
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def add_broadcast_record(admin_username, message_text):
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO broadcasts (admin_username, message_text)
            VALUES (?, ?)
        ''', (admin_username, message_text))
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Ошибка при добавлении записи рассылки: {e}")
    finally:
        conn.close()

def get_broadcast_history():
    conn = sqlite3.connect('camera_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM broadcasts ORDER BY timestamp DESC')
    history = cursor.fetchall()
    conn.close()
    return history

init_db()
