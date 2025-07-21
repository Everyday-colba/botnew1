import random
import config
import os

def format_caption(text, custom_name=None):
    emoji = random.choice(config.EMOJIS)
    
    if custom_name:
        name_emoji = random.choice(["📛", "🏷️", "🏷", "🔖", "📌"])
        name_part = f"{name_emoji} <b>{custom_name}</b>\n\n"
    else:
        name_part = ""
    
    formatted = f"{name_part}{emoji} {text.capitalize()} {emoji}"
    return formatted

def format_project_name(display_name):
    return f"📁 {display_name.strip()}"

def format_pack_name(display_name):
    emoji = random.choice(config.PACK_EMOJIS)
    return f"{emoji} {display_name.strip()}"

def generate_code():
    import string
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def safe_filename(filename):
    keepcharacters = ('.', '_', '-')
    return "".join(c for c in filename if c.isalnum() or c in keepcharacters).rstrip()

def safe_project_filename(filename):
    name, ext = os.path.splitext(filename)
    safe_name = safe_filename(name)
    return f"{safe_name}{ext}"

def safe_pack_filename(filename):
    name, ext = os.path.splitext(filename)
    safe_name = safe_filename(name)
    return f"{safe_name}{ext}"
