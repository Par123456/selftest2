import time
import asyncio
import paramiko
import random
import jdatetime
import re
import pytz
import json
import os
import sqlite3
import tempfile
import traceback
from telethon.tl import functions, types
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, events, functions, errors
from telethon.extensions import markdown
from telethon.tl.functions.messages import DeleteHistoryRequest
from telethon.tl.functions.channels import LeaveChannelRequest, GetParticipantRequest
from telethon.tl.functions.stories import GetStoriesByIDRequest
from telethon.tl.types import Channel, Chat, ChannelParticipantAdmin, ChannelParticipantCreator, Message, PeerUser, SendMessageTypingAction, SendMessageGamePlayAction, SendMessageRecordAudioAction, SendMessageRecordRoundAction, ChatParticipantAdmin, ChatParticipantCreator
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ToggleDialogPinRequest, SetTypingRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.photos import GetUserPhotosRequest, UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.utils import get_display_name

# --- Configuration Section ---
# It's recommended to load sensitive data from environment variables or a separate config file
# For this comprehensive response, we'll keep it within the script but advise externalization.

API_ID = 29042268
API_HASH = '54a7b377dd4a04a58108639febe2f443'
SESSION_NAME = 'selfbot'

DEVICE_MODEL = "Xiaomi Poco X3 Pro"
SYSTEM_VERSION = "Android 12"
APP_VERSION = "11.13.2 (6060)"
LANG_CODE = "en"

DOWNLOAD_FOLDER = 'downloads'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

SETTINGS_FILE = 'settings.json'
EXPIRE_FILE = "expire.json"
MESSAGES_DB = 'messages.db'

# --- Global State & Settings (Managed by SettingsManager) ---
# These will be loaded from SETTINGS_FILE and saved periodically/on change.
# Initial defaults are set here, but actual values come from `load_settings()`.

class BotSettings:
    def __init__(self):
        self.name_list = []
        self.rotate_enabled = False
        self.current_index = 0
        self.time_font = 1
        self.date_font = 1

        self.bio_list = []
        self.rotate_bio_enabled = False
        self.current_bio_index = 0
        self.time_font_bio = 1
        self.date_font_bio = 1

        self.family_list = []
        self.rotate_family_enabled = False
        self.current_family_index = 0
        self.time_font_family = 1
        self.date_font_family = 1

        self.admin_list = []
        self.stay_online = False
        self.time_format_12h = False # False means 24h
        self.date_type = "jalali" # "jalali" or "gregorian"
        self.current_halat = None # e.g., "bold", "italic"

        self.profile_enabled = False
        self.profile_channel_id = None
        self.profile_interval_minutes = 30
        self.profile_max_count = 1
        self.used_profile_photo_ids = [] # To avoid repeating recent photos

        self.pv_lock_enabled = False
        self.pv_warned_users = set() # Store user IDs as set for efficiency

        self.save_view_once_enabled = False
        self.anti_login_enabled = False # This feature requires external handling, bot shutdown
        
        self.last_youtube_time = 0
        self.last_instagram_time = 0
        self.last_gpt_time = 0

        self.auto_read_private = False
        self.auto_read_channel = False
        self.auto_read_group = False
        self.auto_read_bot = False

        self.enemy_list = []
        self.insult_list = [
            "کس اون مادر جندت", "مادرتو گاییدم خارکسه", "دیشب با مادرت داشتم حال میکردم",
            "کس ننت", "مادرقحبه ی ولد زنا", "چهل پدره مادر کسده"
        ]
        self.insult_queue = [] # Shuffled copy of insult_list

        self.media_channel = None # Channel for deleted/edited messages
        self.track_deletions = False
        self.track_edits = False

        self.auto_reply_enabled = False
        self.auto_reply_message_info = None # Stores {'chat_id': int, 'message_id': int}
        self.auto_reply_interval = 10 * 60 # seconds
        self.last_auto_reply_times = {} # {user_id: timestamp}

        self.auto_react = {} # {user_id: emoji}
        self.the_gap = -1002893393924 # Placeholder, should ideally be dynamically set or user-defined

        self.comment_channels = set() # Channel IDs for auto-comment
        self.comment_content = None # Text for auto-comment

        self.last_self_text = None # For random_self_message to avoid repetition
        self.admin_prefix = "+ "

        self.typing_mode_private = False
        self.typing_mode_group = False
        self.game_mode_private = False
        self.game_mode_group = False
        self.voice_mode_private = False
        self.voice_mode_group = False
        self.video_mode_private = False
        self.video_mode_group = False
        self.self_enabled = True # Master switch for the bot's outgoing commands

        self.pv_mute_list = [] # List of user IDs to mute in PVs

settings = BotSettings()

# --- Utility Functions ---

# Custom Markdown for spoiler/emoji handling
class CustomMarkdown:
    @staticmethod
    def parse(text):
        text, entities = markdown.parse(text)
        for i, e in enumerate(entities):
            if isinstance(e, types.MessageEntityTextUrl):
                if e.url == 'spoiler':
                    entities[i] = types.MessageEntitySpoiler(e.offset, e.length)
                elif e.url.startswith('emoji/'):
                    # Custom emoji parsing needs a document_id, which isn't directly in URL in this format
                    # For simplicity, we'll assume it's a placeholder for now or remove if not fully supported.
                    # Proper custom emoji handling requires document_id.
                    pass # entities[i] = types.MessageEntityCustomEmoji(e.offset, e.length, int(e.url.split('/')[1]))
        return text, entities

    @staticmethod
    def unparse(text, entities):
        for i, e in enumerate(entities or []):
            if isinstance(e, types.MessageEntityCustomEmoji):
                # document_id is needed for re-creating the URL for unparsing
                pass # entities[i] = types.MessageEntityTextUrl(e.offset, e.length, f'emoji/{e.document_id}')
            if isinstance(e, types.MessageEntitySpoiler):
                entities[i] = types.MessageEntityTextUrl(e.offset, e.length, 'spoiler')
        return markdown.unparse(text, entities)

# Tehran Time Conversion
def to_tehran_time(dt):
    tehran_tz = pytz.timezone('Asia/Tehran')
    tehran_dt = dt.astimezone(tehran_tz)
    jdt = jdatetime.datetime.fromgregorian(datetime=tehran_dt)
    jalali_date = jdt.strftime("%Y/%m/%d")
    time_str = tehran_dt.strftime("%H:%M:%S")
    return f"{jalali_date} {time_str}"

# Font Styling
FONTS = {
    1: {"0": "0", "1": "1", "2": "2", "3": "3", "4": "4", "5": "5", "6": "6", "7": "7", "8": "8", "9": "9", ":": ":"},
    2: {"0": "۰", "1": "۱", "2": "۲", "3": "۳", "4": "۴", "5": "۵", "6": "۶", "7": "۷", "8": "۸", "9": "۹", ":": ":"},
    3: {"0": "𝟶", "1": "𝟷", "2": "𝟸", "3": "𝟹", "4": "𝟺", "5": "𝟻", "6": "𝟼", "7": "𝟽", "8": "𝟾", "9": "𝟿", ":": ":"},
    4: {"0": "₀", "1": "¹", "2": "₂", "3": "³", "4": "₄", "5": "⁵", "6": "₆", "7": "⁷", "8": "₈", "9": "⁹", ":": ":"},
    5: {"0": "𝟬", "1": "𝟭", "2": "𝟮", "3": "𝟯", "4": "𝟰", "5": "𝟱", "6": "𝟲", "7": "𝟳", "8": "𝟴", "9": "𝟵", ":": ":"},
    6: {"0": "𝟎", "1": "𝟏", "2": "𝟐", "3": "𝟑", "4": "𝟒", "5": "𝟓", "6": "𝟔", "7": "𝟕", "8": "𝟖", "9": "𝟗", ":": ":"},
    7: {"0": "𝟢", "1": "𝟣", "2": "𝟤", "3": "𝟥", "4": "𝟦", "5": "𝟧", "6": "𝟨", "7": "𝟩", "8": "𝟪", "9": "𝟫", ":": ":"},
    8: [1, 2, 3, 4, 5, 6, 7] # For random font selection
}

def random_font(text):
    chosen_font_num = random.choice(FONTS[8])
    return ''.join(FONTS[chosen_font_num].get(ch, ch) for ch in text)

def stylize_text_with_font(text, font_number):
    if font_number == 8:
        return random_font(text)
    return ''.join(FONTS[font_number].get(ch, ch) for ch in text)

# Safely respond to events
async def safe_respond(event, text, edit_msg=None, reply_to_msg_id=None, parse_mode=None):
    try:
        # Check if it's a FakeEvent from admin_command_router
        if hasattr(event, "_original") and event._original:
            if edit_msg:
                # Can't edit a message from a FakeEvent directly, reply to original
                return await event._original.reply(text, reply_to=reply_to_msg_id, parse_mode=parse_mode)
            else:
                return await event._original.reply(text, reply_to=reply_to_msg_id, parse_mode=parse_mode)
        elif edit_msg:
            return await edit_msg.edit(text, parse_mode=parse_mode)
        else:
            return await event.edit(text, parse_mode=parse_mode)
    except errors.MessageNotModifiedError:
        pass # Ignore if message content is identical
    except errors.RPCError as e:
        if "MESSAGE_AUTHOR_REQUIRED" in str(e):
            # If `event.edit` fails because it's not our message (e.g., in groups)
            return await event.reply(text, parse_mode=parse_mode)
        else:
            print(f"Error in safe_respond: {e}")
            return await event.reply(text, parse_mode=parse_mode)
    except Exception as e:
        print(f"Generic error in safe_respond: {e}")
        return await event.reply(text, parse_mode=parse_mode)

async def resolve_user_id(client, identifier):
    """Resolves a user ID from a username, ID, or reply."""
    try:
        if isinstance(identifier, int):
            return identifier
        if isinstance(identifier, str):
            if identifier.isdigit():
                return int(identifier)
            if identifier.startswith('@'):
                identifier = identifier[1:]
            entity = await client.get_entity(identifier)
            return entity.id
        return None
    except Exception as e:
        print(f"Error resolving user ID for {identifier}: {e}")
        return None

# --- Persistence Manager ---
class SettingsManager:
    def __init__(self, settings_obj, file_path):
        self.settings = settings_obj
        self.file_path = file_path
        self._save_task = None
        self._client = None # Will be set after client is initialized

    def set_client(self, client_obj):
        self._client = client_obj

    async def load_settings(self):
        if not os.path.exists(self.file_path):
            print("Settings file not found, using defaults.")
            await self.save_settings() # Save defaults
            return

        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            for key, value in data.items():
                if hasattr(self.settings, key):
                    if key == "pv_warned_users" or key == "comment_channels":
                        setattr(self.settings, key, set(value))
                    elif key == "auto_reply_message_info" and value:
                        # For auto_reply_message_info, we need to fetch the message object later
                        setattr(self.settings, key, value)
                    elif key == "last_auto_reply_times":
                        # Convert string keys (user IDs) to int for consistency
                        setattr(self.settings, key, {int(k): v for k, v in value.items()})
                    else:
                        setattr(self.settings, key, value)
            print("Settings loaded successfully.")
            # After loading, initialize insult_queue
            self.settings.insult_queue = self.settings.insult_list.copy()
            random.shuffle(self.settings.insult_queue)

        except Exception as e:
            print(f"Error loading settings: {e}")
            traceback.print_exc()

    async def save_settings(self):
        data = {}
        for key in vars(self.settings):
            value = getattr(self.settings, key)
            if key == "pv_warned_users" or key == "comment_channels":
                data[key] = list(value) # Convert sets to lists for JSON
            elif key == "auto_reply_message_info":
                data[key] = value # Store the dict directly
            elif key == "last_auto_reply_times":
                # Convert int keys (user IDs) to string for JSON
                data[key] = {str(k): v for k, v in value.items()}
            elif key == "insult_queue":
                continue # Don't save the shuffled queue, it's derived
            else:
                data[key] = value

        try:
            with open(self.file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # print("Settings saved.") # Too verbose for frequent saves
        except Exception as e:
            print(f"Error saving settings: {e}")
            traceback.print_exc()

    def schedule_save(self, delay=5):
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
        self._save_task = asyncio.create_task(self._delayed_save(delay))

    async def _delayed_save(self, delay):
        await asyncio.sleep(delay)
        await self.save_settings()

settings_manager = SettingsManager(settings, SETTINGS_FILE)

# --- Telegram Client Initialization ---
client = TelegramClient(
    SESSION_NAME,
    API_ID,
    API_HASH,
    device_model=DEVICE_MODEL,
    system_version=SYSTEM_VERSION,
    app_version=APP_VERSION,
    lang_code=LANG_CODE
)

# --- Database Setup (for deleted/edited messages) ---
conn = sqlite3.connect(MESSAGES_DB)
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS messages (
    message_id INTEGER PRIMARY KEY,
    user_id INTEGER,
    username TEXT,
    chat_id INTEGER,
    content TEXT,
    date TEXT,
    deleted INTEGER DEFAULT 0,
    media_type TEXT,
    media_link TEXT
)
''')
conn.commit()

# --- Command Patterns and Handlers (Consolidated) ---
# A single dictionary to hold all command patterns and their corresponding handler functions
COMMAND_HANDLERS = {
    r'^آپدیت$': "update_handler",
    r'^پینگ$': "ping_handler",
    r'^راهنما$': "help_handler",
    r'^فونت$': "font_handler",
    r'^ادمین$': "admin_handler",
    r'^پروفایل$': "profile_handler",
    r'^کاربردی$': "tools_handler",
    r'^متغیر$': "x_handler",
    r'^دشمن$': "enemy_handler",
    r'^منشی$': "sec_handler",
    r'^سیستم$': "system_handler",
    r'^حالت متن$': "mess_handler",
    r'^سرگرمی$': "fun_handler",
    r'^ری اکشن$': "react_handler",
    r'^کامنت اول$': "comment_handler",
    r'^حالت اکشن$': "action_handler",

    r'^اسم روشن$': "enable_name_rotation",
    r'^اسم خاموش$': "disable_name_rotation",
    r'^تنظیم اسم (.+)$': "set_name_handler",
    r'^حذف اسم (.+)$': "del_name_handler",
    r'^پاکسازی لیست اسم$': "clear_name_list_handler",
    r'^لیست اسم$': "list_names_handler",
    r'^فونت ساعت اسم (\d+)$': "set_time_font_name",
    r'^فونت تاریخ اسم (\d+)$': "set_date_font_name",

    r'^فامیل روشن$': "enable_family_rotation",
    r'^فامیل خاموش$': "disable_family_rotation",
    r'^تنظیم فامیل (.+)$': "set_family_handler",
    r'^حذف فامیل (.+)$': "del_family_handler",
    r'^پاکسازی لیست فامیل$': "clear_family_list_handler",
    r'^لیست فامیل$': "list_family_handler",
    r'^فونت ساعت فامیل (\d+)$': "set_time_font_family",
    r'^فونت تاریخ فامیل (\d+)$': "set_date_font_family",

    r'^بیو روشن$': "enable_bio_rotation",
    r'^بیو خاموش$': "disable_bio_rotation",
    r'^تنظیم بیو (.+)$': "set_bio_handler",
    r'^حذف بیو (.+)$': "del_bio_handler",
    r'^پاکسازی لیست بیو$': "clear_bio_list_handler",
    r'^لیست بیو$': "list_bios_handler",
    r'^فونت ساعت بیو (\d+)$': "set_time_font_bio",
    r'^فونت تاریخ بیو (\d+)$': "set_date_font_bio",

    r'^تنظیم ادمین(?: (.+))?$': "add_admin_handler",
    r'^حذف ادمین(?: (.+))?$': "remove_admin_handler",
    r'^پاکسازی لیست ادمین$': "clear_admin_list_handler",
    r'^لیست ادمین$': "list_admins_handler",
    r'^وضعیت ادمین\s*\{(.+?)\}$': "change_admin_prefix",

    r'^آنلاین روشن$': "enable_online",
    r'^آنلاین خاموش$': "disable_online",
    r'^تنظیم زمان 24$': "set_24h_clock",
    r'^تنظیم زمان 12$': "set_12h_clock",
    r'^تنظیم تاریخ (.+)$': "set_date_type",
    r'^وضعیت$': "status_handler",
    r'^ریست$': "reset_handler",
    r'^ربات روشن$': "enable_bot",
    r'^ربات خاموش$': "disable_bot",

    r'^دانلود استوری (.+)$': "download_story_handler",
    r'^دریافت استوری(?: |$)(.*)': "get_stories_handler",
    r'^قفل پیوی روشن$': "enable_pv_lock",
    r'^قفل پیوی خاموش$': "disable_pv_lock",
    r'^تنظیم پروفایل$': "set_profile_channel",
    r'^پروفایل روشن$': "enable_profile_rotation",
    r'^پروفایل خاموش$': "disable_profile_rotation",
    r'^تنظیم زمان پروفایل (\d+)$': "set_profile_interval",
    r'^تنظیم تعداد پروفایل (\d+)$': "set_profile_max_count",
    r'^لفت همگانی کانال$': "leave_all_channels",
    r'^لفت همگانی گروه$': "leave_all_groups",
    r'^ذخیره زماندار روشن$': "enable_save_view_once",
    r'^ذخیره زماندار خاموش$': "disable_save_view_once",
    r'^آنتی لاگین روشن$': "enable_anti_login",
    r'^آنتی لاگین خاموش$': "disable_anti_login",
    r'^ذخیره(?: (https://t\.me/(?:c/\d+|[\w]+)/\d+))?$': "save_message",
    r'^دانلود یوتیوب (.+)$': "youtube_download_handler",
    r'^دانلود اینستا (.+)$': "instagram_download_handler",
    r'^هوش مصنوعی (.+)$': "gpt4_bot_handler",
    r'^سین خودکار پیوی روشن$': "enable_auto_read_private",
    r'^سین خودکار پیوی خاموش$': "disable_auto_read_private",
    r'^سین خودکار کانال روشن$': "enable_auto_read_channel",
    r'^سین خودکار کانال خاموش$': "disable_auto_read_channel",
    r'^سین خودکار گروه روشن$': "enable_auto_read_group",
    r'^سین خودکار گروه خاموش$': "disable_auto_read_group",
    r'^سین خودکار ربات روشن$': "enable_auto_read_bot",
    r'^سین خودکار ربات خاموش$': "disable_auto_read_bot",
    r'^اسپم(?: (.+))? (\d+)$': "spam_handler",
    r'^پاکسازی من (.+)$': "clear_my_messages",
    r'^امروز$': "today_handler",
    r'^\+?مشخصات(?: ([^\n]+))?$': "user_info_handler",

    r'^تنظیم دشمن(?: (.+))?$': "add_enemy",
    r'^حذف دشمن(?: (.+))?$': "remove_enemy",
    r'^پاکسازی لیست دشمن$': "clear_enemies",
    r'^لیست دشمن$': "list_enemies",
    r'^تنظیم فحش (.+)$': "add_insult",
    r'^حذف فحش (.+)$': "remove_insult",
    r'^پاکسازی لیست فحش$': "clear_insults",
    r'^لیست فحش$': "list_insults",
    r'^تنظیم لیست فحش$': "import_insult_file",

    r'^ذخیره ویرایش روشن$': "enable_savedit",
    r'^ذخیره ویرایش خاموش$': "disable_savedit",
    r'^ذخیره حذف روشن$': "enable_savedel",
    r'^ذخیره حذف خاموش$': "disable_savedel",
    r'^تنظیم ذخیره (.+)$': "set_media_channel",

    r'^منشی روشن$': "enable_auto_reply",
    r'^منشی خاموش$': "disable_auto_reply",
    r'^تنظیم منشی$': "set_auto_reply",
    r'^تنظیم زمان منشی (\d+)$': "set_auto_reply_interval",
    r'^دریافت بکاپ$': "backup_handler",
    r'^اجرای بکاپ$': "restore_backup",

    r'^تنظیم حالت (.+)$': "set_text_halat", # New handler for `تنظیم حالت <حالت>`
    r'^حالت متن خاموش$': "disable_text_halat", # New handler for `حالت متن خاموش`

    r'^تنظیم ری اکشن(?: (.+))?$': "set_react_handler",
    r'^حذف ری اکشن(?: (.+))?$': "remove_react_handler",
    r'^لیست ری اکشن$': "list_react_handler",
    r'^پاکسازی لیست ری اکشن$': "remove_all_react_handler",

    r'^تنظیم کامنت اول (.+)$': "add_comment_channel",
    r'^حذف کامنت اول (.+)$': "remove_comment_channel",
    r'^تنظیم کامنت$': "set_comment_message",
    r'^لیست کامنت$': "list_comment_channels",
    r'^پاکسازی لیست کامنت$': "clear_comment_channels",

    r'^حالت چت پیوی روشن$': "enable_typing_private",
    r'^حالت چت پیوی خاموش$': "disable_typing_private",
    r'^حالت چت گروه روشن$': "enable_typing_group",
    r'^حالت چت گروه خاموش$': "disable_typing_group",
    r'^حالت بازی پیوی روشن$': "enable_game_private",
    r'^حالت بازی پیوی خاموش$': "disable_game_private",
    r'^حالت بازی گروه روشن$': "enable_game_group",
    r'^حالت بازی گروه خاموش$': "disable_game_group",
    r'^حالت ویس پیوی روشن$': "enable_voice_private",
    r'^حالت ویس پیوی خاموش$': "disable_voice_private",
    r'^حالت ویس گروه روشن$': "enable_voice_group",
    r'^حالت ویس گروه خاموش$': "disable_voice_group",
    r'^حالت ویدیو مسیج پیوی روشن$': "enable_video_private",
    r'^حالت ویدیو مسیج پیوی خاموش$': "disable_video_private",
    r'^حالت ویدیو مسیج گروه روشن$': "enable_video_group",
    r'^حالت ویدیو مسیج گروه خاموش$': "disable_video_group",
    
    r'^سکوت پیوی(?: (.+))?$': "mute_pv_user",
    r'^حذف سکوت پیوی(?: (.+))?$': "unmute_pv_user",
    r'^لیست سکوت پیوی$': "list_muted_pv_users",
    r'^پاکسازی لیست سکوت پیوی$': "clear_muted_pv_users",
    r'^pannel$': "send_inline_panel",
}

# --- Event Handlers (Decorated with client.on) ---

@client.on(events.NewMessage(outgoing=True, pattern=r'^آپدیت$'))
async def update_handler(event):
    if not settings.self_enabled: return
    if event.sender_id in settings.admin_list:
        return await safe_respond(event, "╮ ادمین مجاز به استفاده از این دستور نیست!", reply_to_msg_id=event.id)

    msg = await safe_respond(event, "╮ لطفاً صبر کنید...")

    source_ip = "141.8.192.217"
    username = "a1159341"
    password = "uvmiartira"
    remote_path = "/home/a1159341/bot/file/self.py"
    local_path = "index.py" # Changed from self.py to index.py

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(source_ip, username=username, password=password)

        sftp = ssh.open_sftp()
        sftp.get(remote_path, local_path)
        sftp.close()
        ssh.close()

        await safe_respond(event, "╮ با موفقیت آپدیت شد، چند لحظه صبر کنید!", edit_msg=msg)
        await settings_manager.save_settings() # Save settings before restarting
        os._exit(0) # Exit and rely on process manager to restart

    except Exception as e:
        print(f"Update error: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در فرآیند آپدیت!", edit_msg=msg)

@client.on(events.NewMessage(outgoing=True, pattern=r'^پینگ$'))
async def ping_handler(event):
    if not settings.self_enabled: return
    start = time.perf_counter()
    await client(functions.help.GetConfigRequest())
    end = time.perf_counter()
    ping_ms = int((end - start) * 1000)
    await safe_respond(event, f"`{ping_ms}ms`")

@client.on(events.NewMessage(outgoing=True, pattern=r'^راهنما$'))
async def help_handler(event):
    if not settings.self_enabled: return
    help_text = (
'''
راهنمای سلف:

╮ `راهنما`
│ `سیستم`
│ `فونت`
│ `ادمین`
│ `پروفایل`
│ `کاربردی`
│ `متغیر`
│ `دشمن`
│ `منشی`
│ `حالت متن`
│ `سرگرمی`
│ `ری اکشن`
│ `کامنت اول`
╯ `حالت اکشن`
'''
    )
    await safe_respond(event, help_text)

@client.on(events.NewMessage(outgoing=True, pattern=r'^فونت$'))
async def font_handler(event):
    if not settings.self_enabled: return
    font_text = (
'''
شماره فونت ها:

╮ `1` : 0 1 2 3 4 5 6 7 8 9
│ `2` : ۰ ۱ ۲ ۳ ۴ ۵ ۶ ۷ ۸ ۹
│ `3` : 𝟶 𝟷 𝟸 𝟹 𝟺 𝟻 𝟼 𝟽 𝟾 𝟿 
│ `4` : ₀ ¹ ₂ ³ ₄ ⁵ ₆ ⁷ ₈ ⁹
│ `5` : 𝟬 𝟭 𝟮 𝟯 𝟰 𝟱 𝟲 𝟳 𝟴 𝟵
│ `6` : 𝟎 𝟏 𝟐 𝟑 𝟒 𝟓 𝟔 𝟕 𝟖 𝟗
│ `7` : 𝟢 𝟣 𝟤 𝟥 𝟦 𝟧 𝟨 𝟩 𝟪 𝟫
╯ `8` : Random
'''
    )
    await safe_respond(event, font_text)

@client.on(events.NewMessage(outgoing=True, pattern=r'^ادمین$'))
async def admin_handler(event):
    if not settings.self_enabled: return
    admin_text = (
'''
راهنمای ادمین:

╮ `تنظیم ادمین` [یوزرنیم][ریپلای][آیدی]
│ `حذف ادمین` [یوزرنیم][ریپلای][آیدی]
│ `پاکسازی لیست ادمین`
│ `لیست ادمین`
╯ `وضعیت ادمین` {[نماد][عدد][حروف]}

مثال: `+ راهنما`

توجه: ادمین مجاز به ارسال این دستورات نیست!
'''
    )
    await safe_respond(event, admin_text)

@client.on(events.NewMessage(outgoing=True, pattern=r'^پروفایل$'))
async def profile_handler(event):
    if not settings.self_enabled: return
    profile_text = (
'''
راهنمای پروفایل:

╮ `تنظیم پروفایل` [ریپلای]
│ `پروفایل` [روشن/خاموش]
│ `تنظیم زمان پروفایل` [10-60]
╯ `تنظیم تعداد پروفایل` [1-100]
╮ `تنظیم اسم` [اسم]
│ `حذف اسم` [اسم]
│ `لیست اسم`
│ `پاکسازی لیست اسم`
│ `فونت ساعت اسم` [شماره فونت]
│ `فونت تاریخ اسم` [شماره فونت]
╯ `اسم` [روشن/خاموش]
╮ `تنظیم فامیل` [فامیل]
│ `حذف فامیل` [فامیل]
│ `لیست فامیل`
│ `پاکسازی لیست فامیل`
│ `فونت ساعت فامیل` [شماره فونت]
│ `فونت تاریخ فامیل` [شماره فونت]
╯ `فامیل` [روشن/خاموش]
╮ `تنظیم بیو` [بیو]
│ `حذف بیو` [بیو]
│ `لیست بیو`
│ `پاکسازی لیست بیو`
│ `فونت ساعت بیو` [شماره فونت]
│ `فونت تاریخ بیو` [شماره فونت]
│ `بیو` [روشن/خاموش]
╮ `تنظیم زمان` [24/12]
╯ `تنظیم تاریخ` [شمسی/میلادی]
'''
    )
    await safe_respond(event, profile_text)

@client.on(events.NewMessage(outgoing=True, pattern=r'^کاربردی$'))
async def tools_handler(event):
    if not settings.self_enabled: return
    tools_text = (
'''
راهنمای کاربردی:

╮ `آنلاین` [روشن/خاموش]
│ `دریافت استوری` [یوزرنیم][ریپلای][آیدی]
│ `دانلود استوری` [یوزرنیم][ریپلای][آیدی]
│ `لفت همگانی کانال`
│ `لفت همگانی گروه`
│ `قفل پیوی` [روشن/خاموش]
│ `ذخیره زماندار` [روشن/خاموش]
│ `آنتی لاگین` [روشن/خاموش]
│ `ذخیره` [ریپلای][لینک]
│ `دانلود اینستا` [لینک]
│ `دانلود یوتیوب` [لینک]
│ `هوش مصنوعی` [سوال]
│ `سین خودکار پیوی` [روشن/خاموش]
│ `سین خودکار کانال` [روشن/خاموش]
│ `سین خودکار گروه` [روشن/خاموش]
│ `سین خودکار ربات` [روشن/خاموش]
│ `اسپم` [ریپلای/متن][تعداد]
│ `ذخیره حذف` [روشن/خاموش]
│ `ذخیره ویرایش` [روشن/خاموش]
│ `تنظیم ذخیره`  [لینک کانال خصوصی]
│ `پاکسازی من` [همه/عدد]
│ `امروز`
│ `مشخصات` [ریپلای][آیدی][یوزرنیم]
│ `سکوت پیوی` [ریپلای][آیدی][یوزرنیم]
│ `حذف سکوت پیوی` [ریپلای][آیدی][یوزرنیم]
│ `لیست سکوت پیوی`
╯ `پاکسازی لیست سکوت پیوی`
'''
    )
    await safe_respond(event, tools_text)

@client.on(events.NewMessage(outgoing=True, pattern=r'^متغیر$'))
async def x_handler(event):
    if not settings.self_enabled: return
    x_text = (
'''
راهنمای متغیر:

╮ `[ساعت]`
╯ `[تاریخ]`
'''
    )
    await safe_respond(event, x_text)

@client.on(events.NewMessage(outgoing=True, pattern=r'^دشمن$'))
async def enemy_handler(event):
    if not settings.self_enabled: return
    enemy_text = (
'''
راهنمای دشمن:

╮ `تنظیم دشمن` [ریپلای][یوزرنیم][آیدی]
│ `حذف دشمن`  [ریپلای][یوزرنیم][آیدی]
│ `پاکسازی لیست دشمن`
│ `لیست دشمن`
│ `تنظیم فحش` [متن]
│ `حذف فحش` [متن]
│ `پاکسازی لیست فحش`
│ `لیست فحش`
╯ `تنظیم لیست فحش` [ریپلای به لیست فحش]
'''
    )
    await safe_respond(event, enemy_text)

@client.on(events.NewMessage(outgoing=True, pattern=r'^منشی$'))
async def sec_handler(event):
    if not settings.self_enabled: return
    sec_text = (
'''
راهنمای منشی:

╮ `منشی` [روشن/خاموش]
│ `تنظیم منشی` [ریپلای]
╯ `تنظیم زمان منشی` [5-60]
'''
    )
    await safe_respond(event, sec_text)

@client.on(events.NewMessage(outgoing=True, pattern=r'^سیستم$'))
async def system_handler(event):
    if not settings.self_enabled: return
    system_text = (
'''
راهنمای سیستم:

╮ `وضعیت`
│ `آپدیت`
│ `ریست`
│ `پینگ`
│ `دریافت بکاپ`
│ `اجرای بکاپ` [ریپلای به فایل بکاپ]
╯ `ربات` [روشن/خاموش]

توجه: ادمین مجاز به ارسال دستورات { `ریست` } و { `آپدیت` } نیست!
'''
    )
    await safe_respond(event, system_text)

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت متن$'))
async def mess_handler(event):
    if not settings.self_enabled: return
    mess_text = (
'''
راهنمای حالت متن:

╮ `تنظیم حالت` [حالت]
╯ `حالت متن خاموش`

حالت ها:

╮ `بولد`
│ `ایتالیک`
│ `زیرخط`
│ `کدینگ`
│ `اسپویلر`
╯ `استرایک`

توجه: ادمین مجاز به ارسال این دستورات نیست!
'''
    )
    await safe_respond(event, mess_text)

@client.on(events.NewMessage(outgoing=True, pattern=r'^سرگرمی$'))
async def fun_handler(event):
    if not settings.self_enabled: return
    fun_text = (
'''
راهنمای سرگرمی:

╮ `ربات`
'''
    )
    await safe_respond(event, fun_text)

@client.on(events.NewMessage(outgoing=True, pattern=r'^ری اکشن$'))
async def react_handler(event):
    if not settings.self_enabled: return
    react_text = (
'''
راهنمای ری اکشن:

╮ `تنظیم ری اکشن` [ایموجی][ریپلای][یوزرنیم][آیدی]
│ `حذف ری اکشن` [ریپلای][یوزرنیم][آیدی]
│ `لیست ری اکشن`
╯ `پاکسازی لیست ری اکشن`
'''
    )
    await safe_respond(event, react_text)

@client.on(events.NewMessage(outgoing=True, pattern=r'^کامنت اول$'))
async def comment_handler(event):
    if not settings.self_enabled: return
    comment_text = (
'''
راهنمای کامنت اول:

╮ `تنظیم کامنت اول` [یوزرنیم][آیدی]
│ `حذف کامنت اول` [یوزرنیم][آیدی]
│ `لیست کامنت`
╯ `پاکسازی لیست کامنت`
'''
    )
    await safe_respond(event, comment_text)

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت اکشن$'))
async def action_handler(event):
    if not settings.self_enabled: return
    action_text = (
'''
راهنمای حالت اکشن:

╮ `حالت چت` [پیوی/گروه][روشن/خاموش]
│ `حالت بازی` [پیوی/گروه][روشن/خاموش]
│ `حالت ویس` [پیوی/گروه][روشن/خاموش]
╯ `حالت ویدیو مسیج` [پیوی/گروه][روشن/خاموش]
'''
    )
    await safe_respond(event, action_text)

@client.on(events.NewMessage(outgoing=True, pattern=r'^اسم روشن$'))
async def enable_name_rotation(event):
    if not settings.self_enabled: return
    settings.rotate_enabled = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^اسم خاموش$'))
async def disable_name_rotation(event):
    if not settings.self_enabled: return
    settings.rotate_enabled = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم اسم (.+)$'))
async def set_name_handler(event):
    if not settings.self_enabled: return
    name = event.pattern_match.group(1).strip()
    if name in settings.name_list:
        await safe_respond(event, "╮ وجود دارد!")
    else:
        settings.name_list.append(name)
        await settings_manager.save_settings()
        await safe_respond(event, f'''╮ اضافه شد:
`{name}`''')

@client.on(events.NewMessage(outgoing=True, pattern=r'^حذف اسم (.+)$'))
async def del_name_handler(event):
    if not settings.self_enabled: return
    name = event.pattern_match.group(1).strip()
    if name in settings.name_list:
        settings.name_list.remove(name)
        await settings_manager.save_settings()
        await safe_respond(event, f'''╮ حذف شد:
`{name}`''')
    else:
        await safe_respond(event, "╮ وجود ندارد!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^پاکسازی لیست اسم$'))
async def clear_name_list_handler(event):
    if not settings.self_enabled: return
    settings.name_list.clear()
    settings.current_index = 0
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خالی شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^لیست اسم$'))
async def list_names_handler(event):
    if not settings.self_enabled: return
    if not settings.name_list:
        await safe_respond(event, "╮ خالی!")
        return

    result = "╮ لیست اسم:\n\n"
    result += "\n———\n".join(settings.name_list)
    await safe_respond(event, f"{result}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^فامیل روشن$'))
async def enable_family_rotation(event):
    if not settings.self_enabled: return
    settings.rotate_family_enabled = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^فامیل خاموش$'))
async def disable_family_rotation(event):
    if not settings.self_enabled: return
    settings.rotate_family_enabled = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم فامیل (.+)$'))
async def set_family_handler(event):
    if not settings.self_enabled: return
    fam = event.pattern_match.group(1).strip()
    if fam in settings.family_list:
        await safe_respond(event, "╮ وجود دارد!")
    else:
        settings.family_list.append(fam)
        await settings_manager.save_settings()
        await safe_respond(event, f'''╮ اضافه شد:
`{fam}`''')

@client.on(events.NewMessage(outgoing=True, pattern=r'^حذف فامیل (.+)$'))
async def del_family_handler(event):
    if not settings.self_enabled: return
    fam = event.pattern_match.group(1).strip()
    if fam in settings.family_list:
        settings.family_list.remove(fam)
        await settings_manager.save_settings()
        await safe_respond(event, f'''╮ حذف شد:
`{fam}`''')
    else:
        await safe_respond(event, "╮ وجود ندارد!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^پاکسازی لیست فامیل$'))
async def clear_family_list_handler(event):
    if not settings.self_enabled: return
    settings.family_list.clear()
    settings.current_family_index = 0
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خالی شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^لیست فامیل$'))
async def list_family_handler(event):
    if not settings.self_enabled: return
    if not settings.family_list:
        await safe_respond(event, "╮ خالی!")
        return

    result = "لیست فامیل:\n\n"
    result += "\n———\n".join(settings.family_list)
    await safe_respond(event, f"{result}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^بیو روشن$'))
async def enable_bio_rotation(event):
    if not settings.self_enabled: return
    settings.rotate_bio_enabled = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^بیو خاموش$'))
async def disable_bio_rotation(event):
    if not settings.self_enabled: return
    settings.rotate_bio_enabled = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم بیو (.+)$'))
async def set_bio_handler(event):
    if not settings.self_enabled: return
    bio = event.pattern_match.group(1).strip()
    if bio in settings.bio_list:
        await safe_respond(event, "╮ وجود دارد!")
    else:
        settings.bio_list.append(bio)
        await settings_manager.save_settings()
        await safe_respond(event, f'''╮ اضافه شد:
`{bio}`''')

@client.on(events.NewMessage(outgoing=True, pattern=r'^حذف بیو (.+)$'))
async def del_bio_handler(event):
    if not settings.self_enabled: return
    bio = event.pattern_match.group(1).strip()
    if bio in settings.bio_list:
        settings.bio_list.remove(bio)
        await settings_manager.save_settings()
        await safe_respond(event, f'''╮ حذف شد:
`{bio}`''')
    else:
        await safe_respond(event, "╮ وجود ندارد!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^پاکسازی لیست بیو$'))
async def clear_bio_list_handler(event):
    if not settings.self_enabled: return
    settings.bio_list.clear()
    settings.current_bio_index = 0
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خالی شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^لیست بیو$'))
async def list_bios_handler(event):
    if not settings.self_enabled: return
    if not settings.bio_list:
        await safe_respond(event, "╮ خالی!")
        return

    result = "لیست بیو:\n\n"
    result += "\n———\n".join(settings.bio_list)
    await safe_respond(event, f"{result}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^فونت ساعت اسم (\d+)$'))
async def set_time_font_name(event):
    if not settings.self_enabled: return
    num = int(event.pattern_match.group(1))
    if num in FONTS:
        settings.time_font = num
        await settings_manager.save_settings()
        await safe_respond(event, f'''╮ تنظیم شد:
`{num}`''')
    else:
        await safe_respond(event, "╮ نامعتبر!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^فونت تاریخ اسم (\d+)$'))
async def set_date_font_name(event):
    if not settings.self_enabled: return
    num = int(event.pattern_match.group(1))
    if num in FONTS:
        settings.date_font = num
        await settings_manager.save_settings()
        await safe_respond(event, f'''╮ تنظیم شد:
`{num}`''')
    else:
        await safe_respond(event, "╮ نامعتبر!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^فونت ساعت فامیل (\d+)$'))
async def set_time_font_family(event):
    if not settings.self_enabled: return
    num = int(event.pattern_match.group(1))
    if num in FONTS:
        settings.time_font_family = num
        await settings_manager.save_settings()
        await safe_respond(event, f'''╮ تنظیم شد:
`{num}`''')
    else:
        await safe_respond(event, "╮ نامعتبر!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^فونت تاریخ فامیل (\d+)$'))
async def set_date_font_family(event):
    if not settings.self_enabled: return
    num = int(event.pattern_match.group(1))
    if num in FONTS:
        settings.date_font_family = num
        await settings_manager.save_settings()
        await safe_respond(event, f'''╮ تنظیم شد:
`{num}`''')
    else:
        await safe_respond(event, "╮ نامعتبر!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^فونت ساعت بیو (\d+)$'))
async def set_time_font_bio(event):
    if not settings.self_enabled: return
    num = int(event.pattern_match.group(1))
    if num in FONTS:
        settings.time_font_bio = num
        await settings_manager.save_settings()
        await safe_respond(event, f'''╮ تنظیم شد:
`{num}`''')
    else:
        await safe_respond(event, "╮ نامعتبر!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^فونت تاریخ بیو (\d+)$'))
async def set_date_font_bio(event):
    if not settings.self_enabled: return
    num = int(event.pattern_match.group(1))
    if num in FONTS:
        settings.date_font_bio = num
        await settings_manager.save_settings()
        await safe_respond(event, f'''╮ تنظیم شد:
`{num}`''')
    else:
        await safe_respond(event, "╮ نامعتبر!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم ادمین(?: (.+))?$'))
async def add_admin_handler(event):
    if not settings.self_enabled: return
    input_arg = event.pattern_match.group(1)

    user_id = None
    reply = await event.get_reply_message() if not hasattr(event, "_original") else await event._original.get_reply_message()

    if reply:
        user_id = reply.sender_id
    elif input_arg:
        user_id = await resolve_user_id(client, input_arg)
    else:
        await safe_respond(event, "╮ با استفاده از ریپلای، یوزرنیم یا آیدی عددی استفاده کنید!")
        return

    if user_id is None:
        await safe_respond(event, "╮ کاربر نامعتبر!")
        return

    if user_id in settings.admin_list:
        await safe_respond(event, "╮ وجود دارد!")
    else:
        settings.admin_list.append(user_id)
        await settings_manager.save_settings()
        await safe_respond(event, "╮ اضافه شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حذف ادمین(?: (.+))?$'))
async def remove_admin_handler(event):
    if not settings.self_enabled: return
    input_arg = event.pattern_match.group(1)

    user_id = None
    reply = await event.get_reply_message() if not hasattr(event, "_original") else await event._original.get_reply_message()

    if reply:
        user_id = reply.sender_id
    elif input_arg:
        user_id = await resolve_user_id(client, input_arg)
    else:
        await safe_respond(event, "╮ با استفاده از ریپلای، یوزرنیم یا آیدی عددی استفاده کنید!")
        return

    if user_id is None:
        await safe_respond(event, "╮ کاربر نامعتبر!")
        return

    if user_id in settings.admin_list:
        settings.admin_list.remove(user_id)
        await settings_manager.save_settings()
        await safe_respond(event, "╮ حذف شد.")
    else:
        await safe_respond(event, "╮ وجود ندارد!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^پاکسازی لیست ادمین$'))
async def clear_admin_list_handler(event):
    if not settings.self_enabled: return
    settings.admin_list.clear()
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خالی شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^لیست ادمین$'))
async def list_admins_handler(event):
    if not settings.self_enabled: return
    if not settings.admin_list:
        await safe_respond(event, "╮ خالی!")
        return

    mentions = []
    for user_id in settings.admin_list:
        try:
            user = await client.get_entity(user_id)
            name = get_display_name(user) if get_display_name(user) else "کاربر"
            mentions.append(f"> [{name}](tg://user?id={user.id})")
        except Exception as e:
            print(f"Error getting admin entity {user_id}: {e}")
            mentions.append(f"> [ناشناس](tg://user?id={user_id})")

    result = "لیست ادمین:\n\n" + "\n".join(mentions)
    await safe_respond(event, result)

@client.on(events.NewMessage(outgoing=True, pattern=r'^آنلاین روشن$'))
async def enable_online(event):
    if not settings.self_enabled: return
    settings.stay_online = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^آنلاین خاموش$'))
async def disable_online(event):
    if not settings.self_enabled: return
    settings.stay_online = False
    await settings_manager.save_settings()
    await client(functions.account.UpdateStatusRequest(offline=True))
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم زمان 12$'))
async def set_12h_clock(event):
    if not settings.self_enabled: return
    settings.time_format_12h = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ تنظیم شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم زمان 24$'))
async def set_24h_clock(event):
    if not settings.self_enabled: return
    settings.time_format_12h = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ تنظیم شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^وضعیت$'))
async def status_handler(event):
    if not settings.self_enabled: return
    status_items = []

    status_items.append(f"ربات : {'✔️' if settings.self_enabled else '✖️'}")
    if settings.stay_online: status_items.append("آنلاین ✔️")
    if settings.pv_lock_enabled: status_items.append("قفل پیوی ✔️")
    if settings.save_view_once_enabled: status_items.append("ذخیره زماندار ✔️")
    if settings.anti_login_enabled: status_items.append("آنتی لاگین ✔️")
    if settings.rotate_enabled: status_items.append("اسم ✔️")
    if settings.rotate_family_enabled: status_items.append("فامیل ✔️")
    if settings.rotate_bio_enabled: status_items.append("بیو ✔️")
    if settings.profile_enabled: status_items.append("پروفایل ✔️")
    if settings.auto_read_private: status_items.append("سین خودکار پیوی ✔️")
    if settings.auto_read_channel: status_items.append("سین خودکار کانال ✔️")
    if settings.auto_read_group: status_items.append("سین خودکار گروه ✔️")
    if settings.auto_read_bot: status_items.append("سین خودکار ربات ✔️")
    if settings.track_deletions: status_items.append("ذخیره حذف ✔️")
    if settings.track_edits: status_items.append("ذخیره ویرایش ✔️")
    if settings.auto_reply_enabled: status_items.append("منشی ✔️")
    if settings.typing_mode_private: status_items.append("حالت چت پیوی ✔️")
    if settings.typing_mode_group: status_items.append("حالت چت گروه ✔️")
    if settings.game_mode_private: status_items.append("حالت بازی پیوی ✔️")
    if settings.game_mode_group: status_items.append("حالت بازی گروه ✔️")
    if settings.voice_mode_private: status_items.append("حالت ویس پیوی ✔️")
    if settings.voice_mode_group: status_items.append("حالت ویس گروه ✔️")
    if settings.video_mode_private: status_items.append("حالت ویدیو مسیج پیوی ✔️")
    if settings.video_mode_group: status_items.append("حالت ویدیو مسیج گروه ✔️")

    show_time_format = any('[ساعت]' in item for item in settings.name_list + settings.family_list + settings.bio_list)
    if show_time_format:
        status_items.append(f"زمان : `{'12H' if settings.time_format_12h else '24H'}`")
    
    show_date_format = any('[تاریخ]' in item for item in settings.name_list + settings.family_list + settings.bio_list)
    if show_date_format:
        status_items.append(f"تاریخ : `{'شمسی' if settings.date_type == 'jalali' else 'میلادی'}`")

    status_items.append(f"وضعیت ادمین: {{`{settings.admin_prefix}`}}")

    result_header = "❈ وضعیت"
    if not status_items:
        result_body = "قابلیتی فعال نیست!"
    else:
        result_body = ""
        for i, item in enumerate(status_items):
            if i == 0: result_body += f"╮ {item}\n"
            elif i == len(status_items) - 1: result_body += f"╯ {item}"
            else: result_body += f"│ {item}\n"

    expire_days = 30
    now_dt = datetime.now(pytz.timezone('Asia/Tehran'))

    expire_str = "Uncertain!"
    try:
        if os.path.exists(EXPIRE_FILE):
            with open(EXPIRE_FILE, "r") as f:
                data = json.load(f)
                start_str = data.get("start")
                start_dt = datetime.strptime(start_str, "%Y/%m/%d %H:%M")
                start_dt = pytz.timezone('Asia/Tehran').localize(start_dt)
                
                expire_time = start_dt + timedelta(days=expire_days)
                remaining = expire_time - now_dt

                if remaining.total_seconds() < 0:
                    expire_str = "Expired!"
                else:
                    days = remaining.days
                    hours = remaining.seconds // 3600
                    minutes = (remaining.seconds % 3600) // 60
                    expire_str = f"{days} Days, {hours:02}:{minutes:02}"
        else:
            now_dt_tehran = datetime.now(pytz.timezone('Asia/Tehran'))
            start_expire_str = now_dt_tehran.strftime("%Y/%m/%d %H:%M")
            with open(EXPIRE_FILE, "w") as f:
                json.dump({"start": start_expire_str}, f)
            expire_str = "Initialized!"

    except Exception as e:
        print(f"Error checking expiration: {e}")
        expire_str = "Error!"

    final_result = f"{result_header}\n\n{result_body}" if status_items else f"{result_header}\n\n{result_body}"
    final_result += "\n\n"
    final_result += "❈ Creator : @AnishtayiN\n"
    final_result += "❈ Bot : @Selfsazfree7_bot\n"
    final_result += "❈ Version : 2.0 (Beta)\n"
    final_result += f"❈ Expire : {expire_str}"

    await safe_respond(event, final_result)

@client.on(events.NewMessage(outgoing=True, pattern=r'^دانلود استوری (.+)$'))
async def download_story_handler(event):
    if not settings.self_enabled: return
    is_admin = hasattr(event, "_original") # Check if it's a FakeEvent

    msg = await safe_respond(event, "╮ لطفا صبر کنید...")

    try:
        story_url = event.pattern_match.group(1).strip()
        if not story_url.startswith('https://t.me/'):
            return await safe_respond(event, "╮ لینک نامعتبر!", edit_msg=msg)

        parts = story_url.split('/')
        username_or_id = None
        story_id = None

        # Example format: https://t.me/username/s/123 or https://t.me/c/12345/s/678
        if '/s/' in story_url:
            idx = parts.index('s')
            if idx > 0 and idx + 1 < len(parts):
                username_or_id = parts[idx - 1]
                story_id = parts[idx + 1]

        if not username_or_id or not story_id:
            return await safe_respond(event, "╮ فرمت لینک نامعتبر!", edit_msg=msg)

        try:
            story_id = int(story_id)
        except ValueError:
            return await safe_respond(event, "╮ شناسه استوری باید عددی باشد!", edit_msg=msg)

        entity = None
        try:
            if username_or_id.startswith('c/'):
                channel_id = int(username_or_id[2:])
                entity = await client.get_entity(channel_id)
            else:
                entity = await client.get_entity(username_or_id)
        except ValueError:
            return await safe_respond(event, "╮ استوری یافت نشد (کاربر/کانال نامعتبر)!", edit_msg=msg)
        except Exception as e:
            print(f"Error getting entity for story download: {e}")
            return await safe_respond(event, "╮ استوری یافت نشد!", edit_msg=msg)

        stories = await client(GetStoriesByIDRequest(
            peer=entity,
            id=[story_id]
        ))

        if not stories.stories:
            return await safe_respond(event, "╮ استوری یافت نشد!", edit_msg=msg)

        story = stories.stories[0]

        if not hasattr(story, 'media') or not story.media:
            return await safe_respond(event, "╮ استوری رسانه‌ای نیست!", edit_msg=msg)

        downloaded_file = await client.download_media(story.media, file=DOWNLOAD_FOLDER)

        if downloaded_file and os.path.exists(downloaded_file):
            caption_text = f"╮ استوری از @{entity.username or entity.id}"
            await client.send_file(event.chat_id, downloaded_file, caption=caption_text, supports_streaming=True)
            os.remove(downloaded_file)
        else:
            await safe_respond(event, "╮ دریافت فایل با شکست مواجه شد.", edit_msg=msg)
            return
        
        await msg.delete() # Delete the "لطفا صبر کنید" message

    except Exception as e:
        print(f"Error in download_story_handler: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در دانلود استوری!", edit_msg=msg)

@client.on(events.NewMessage(outgoing=True, pattern=r'^دریافت استوری(?: |$)(.*)'))
async def get_stories_handler(event):
    if not settings.self_enabled: return
    is_admin = hasattr(event, "_original")
    input_arg = event.pattern_match.group(1).strip()

    msg = await safe_respond(event, "╮ لطفا صبر کنید...")

    reply = await event.get_reply_message() if not is_admin else await event._original.get_reply_message()
    entity = None

    try:
        if reply:
            user = await reply.get_sender()
            entity = await client.get_entity(user.id)
        elif input_arg:
            entity = await client.get_entity(input_arg)
        else:
            return await safe_respond(event, "╮ لطفاً به درستی از دستور استفاده کنید (یوزرنیم، آیدی یا ریپلای)!", edit_msg=msg)
        
        if not entity:
             return await safe_respond(event, "╮ کاربر/کانال یافت نشد!", edit_msg=msg)

        mention_name = get_display_name(entity) or str(entity.id)
        result = f"╮ استوری های [{mention_name}](tg://user?id={entity.id}):\n\n"
        base_url = f"https://t.me/{entity.username or ('c/' + str(entity.id) if entity.broadcast else 's/' + str(entity.id))}/s/"

        all_story_links = []

        # Active stories
        try:
            active_stories = await client(functions.stories.GetPeerStoriesRequest(peer=entity))
            if hasattr(active_stories, 'stories') and active_stories.stories.stories:
                for story in active_stories.stories.stories:
                    all_story_links.append(f"{base_url}{story.id}")
        except Exception as e:
            print(f"Error fetching active stories for {entity.id}: {e}")

        # Pinned stories
        try:
            pinned_stories = await client(functions.stories.GetPinnedStoriesRequest(
                peer=entity,
                offset_id=0,
                limit=999999
            ))
            if hasattr(pinned_stories, 'stories') and pinned_stories.stories:
                for story in pinned_stories.stories:
                    all_story_links.append(f"{base_url}{story.id}")
        except Exception as e:
            print(f"Error fetching pinned stories for {entity.id}: {e}")

        if not all_story_links:
            return await safe_respond(event, "╮ استوری ای وجود ندارد!", edit_msg=msg)

        result += "\n".join(all_story_links)
        await safe_respond(event, result, edit_msg=msg, parse_mode='md')

    except Exception as e:
        print(f"Error in get_stories_handler: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در دریافت استوری ها!", edit_msg=msg)

@client.on(events.NewMessage(outgoing=True, pattern=r'^پروفایل روشن$'))
async def enable_profile_rotation(event):
    if not settings.self_enabled: return
    settings.profile_enabled = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^پروفایل خاموش$'))
async def disable_profile_rotation(event):
    if not settings.self_enabled: return
    settings.profile_enabled = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم زمان پروفایل (\d+)$'))
async def set_profile_interval(event):
    if not settings.self_enabled: return
    minutes = int(event.pattern_match.group(1))
    if 10 <= minutes <= 60:
        settings.profile_interval_minutes = minutes
        await settings_manager.save_settings()
        await safe_respond(event, "╮ تنظیم شد.")
    else:
        await safe_respond(event, "╮ عدد باید 10 الی 60 باشد!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم تعداد پروفایل (\d+)$'))
async def set_profile_max_count(event):
    if not settings.self_enabled: return
    count = int(event.pattern_match.group(1))
    if 1 <= count <= 100:
        settings.profile_max_count = count
        await settings_manager.save_settings()
        await safe_respond(event, "╮ تنظیم شد.")
    else:
        await safe_respond(event, "╮ عدد باید 1 الی 100 باشد!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم پروفایل$'))
async def set_profile_channel(event):
    if not settings.self_enabled: return
    try:
        reply = await event.get_reply_message() if not hasattr(event, "_original") else await event._original.get_reply_message()

        if not reply or not reply.forward or not reply.forward.chat:
            await safe_respond(event, "╮ پیام باید از کانال فوروارد شده باشد!")
            return

        channel = reply.forward.chat
        settings.profile_channel_id = channel.id
        settings.used_profile_photo_ids.clear() # Reset used photos for new channel
        await settings_manager.save_settings()
        await safe_respond(event, "╮ تنظیم شد.")

    except Exception as e:
        print(f"Error setting profile channel: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در تنظیم پروفایل!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^قفل پیوی روشن$'))
async def enable_pv_lock(event):
    if not settings.self_enabled: return
    settings.pv_lock_enabled = True
    settings.pv_warned_users.clear() # Clear warnings on activation
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^قفل پیوی خاموش$'))
async def disable_pv_lock(event):
    if not settings.self_enabled: return
    settings.pv_lock_enabled = False
    settings.pv_warned_users.clear() # Clear warnings on deactivation
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(incoming=True))
async def pv_lock_handler(event):
    if not settings.self_enabled: return
    if not settings.pv_lock_enabled:
        return

    if event.is_private and event.sender_id != (await client.get_me()).id:
        user_id = event.sender_id

        if user_id in settings.admin_list: # Admins are exempt
            return

        if user_id not in settings.pv_warned_users:
            settings.pv_warned_users.add(user_id)
            settings_manager.schedule_save() # Schedule save for updated set

            try:
                await event.delete()
            except errors.MessageDeleteForbiddenError:
                # Can't delete opponent's message, but still warn
                pass
            except Exception as e:
                print(f"Error deleting message in pv_lock_handler: {e}")

            try:
                warn_msg = await client.send_message(user_id, "قفل پیوی روشن است، پیام ها حذف خواهند شد!")
                await asyncio.sleep(30) # Allow user to read warning
                await warn_msg.delete()
            except errors.UserIsBlockedError:
                # User blocked the bot, can't send warning
                pass
            except Exception as e:
                print(f"Error sending/deleting warning in pv_lock_handler: {e}")
        else:
            try:
                # If already warned, delete all messages from this user in PV
                await client(DeleteHistoryRequest(
                    peer=user_id,
                    max_id=0, # Deletes all messages
                    revoke=True # Delete for both sides
                ))
            except Exception as e:
                print(f"Error deleting history in pv_lock_handler: {e}")

@client.on(events.NewMessage(outgoing=True, pattern=r'^لفت همگانی کانال$'))
async def leave_all_channels(event):
    if not settings.self_enabled: return
    msg = await safe_respond(event, "╮ لطفا صبر کنید...")

    me = await client.get_me()
    left_count = 0
    tasks = []

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, Channel) and not entity.megagroup: # Filter for channels (not groups)
            async def _leave_channel_task(ent):
                nonlocal left_count
                try:
                    # Check if bot is admin/creator, then skip
                    participant = await client(functions.channels.GetParticipantRequest(channel=ent, participant=me.id))
                    if isinstance(participant.participant, (ChannelParticipantAdmin, ChannelParticipantCreator)):
                        return # Skip leaving if admin/creator
                except errors.UserNotParticipantError:
                    pass # Not a participant, nothing to do
                except Exception as e:
                    print(f"Error checking channel participant {ent.id}: {e}")
                    # Continue to try leaving even if check fails, might be just a regular member

                try:
                    await client(LeaveChannelRequest(ent))
                    left_count += 1
                except Exception as e:
                    print(f"Error leaving channel {ent.id}: {e}")
            tasks.append(_leave_channel_task(entity))

    await asyncio.gather(*tasks) # Run all leave tasks concurrently
    await safe_respond(event, f"╮ تعداد {left_count} کانال لفت داده شد.", edit_msg=msg)

@client.on(events.NewMessage(outgoing=True, pattern=r'^لفت همگانی گروه$'))
async def leave_all_groups(event):
    if not settings.self_enabled: return
    msg = await safe_respond(event, "╮ لطفا صبر کنید...")

    me = await client.get_me()
    left_count = 0
    tasks = []

    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        # Filter for chats (legacy groups) or megagroups (supergroups/channels used as groups)
        if isinstance(entity, (Chat, Channel)) and (isinstance(entity, Chat) or (isinstance(entity, Channel) and entity.megagroup)):
            async def _leave_group_task(ent):
                nonlocal left_count
                try:
                    # Check if bot is admin/creator, then skip
                    participant = await client.get_participant(ent, me.id)
                    if isinstance(participant.participant, (ChatParticipantAdmin, ChatParticipantCreator, ChannelParticipantAdmin, ChannelParticipantCreator)):
                        return # Skip leaving if admin/creator
                except errors.UserNotParticipantError:
                    pass # Not a participant, nothing to do
                except Exception as e:
                    print(f"Error checking group participant {ent.id}: {e}")

                try:
                    await client(LeaveChannelRequest(ent) if isinstance(ent, Channel) else functions.messages.DeleteChatUserRequest(chat_id=ent.id, user_id=me.id))
                    left_count += 1
                except Exception as e:
                    print(f"Error leaving group {ent.id}: {e}")
            tasks.append(_leave_group_task(entity))

    await asyncio.gather(*tasks)
    await safe_respond(event, f"╮ تعداد {left_count} گروه لفت داده شد.", edit_msg=msg)

@client.on(events.NewMessage(outgoing=True, pattern=r'^ذخیره زماندار روشن$'))
async def enable_save_view_once(event):
    if not settings.self_enabled: return
    settings.save_view_once_enabled = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^ذخیره زماندار خاموش$'))
async def disable_save_view_once(event):
    if not settings.self_enabled: return
    settings.save_view_once_enabled = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(incoming=True))
async def handle_view_once_media(event):
    if not settings.self_enabled: return
    if not settings.save_view_once_enabled:
        return

    if not event.is_private:
        return

    sender = await event.get_sender()
    me = await client.get_me()
    if sender.id == me.id: # Don't save our own view-once messages
        return

    media = event.media
    if media and getattr(media, "ttl_seconds", None):
        try:
            file_path = await client.download_media(media, file=DOWNLOAD_FOLDER)
            caption = f"╮ مدیا از [{sender.id}](tg://user?id={sender.id}) ذخیره شد."
            await client.send_file("me", file_path, caption=caption)
            os.remove(file_path)
        except Exception as e:
            print(f"Error saving view-once media: {e}")
            traceback.print_exc()
            await client.send_message("me", f"╮ خطا در ذخیره مدیا از {sender.id}!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^آنتی لاگین روشن$'))
async def enable_anti_login(event):
    if not settings.self_enabled: return
    settings.anti_login_enabled = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^آنتی لاگین خاموش$'))
async def disable_anti_login(event):
    if not settings.self_enabled: return
    settings.anti_login_enabled = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.UserUpdate)
async def anti_login_detector(event):
    if not settings.self_enabled: return
    if not settings.anti_login_enabled:
        return

    me = await client.get_me()
    if event.user_id == me.id and event.phone_calls_available is not None:
        if event.phone_calls_available: # Indicates a new login session might have started
            print("Potential new login detected! Shutting down bot.")
            try:
                await client.send_message("me", "╮ هشدار! ورود جدید به حساب شما تشخیص داده شد. برای جلوگیری از دسترسی غیرمجاز، سلف خاموش شد.")
            except Exception as e:
                print(f"Failed to send anti-login warning: {e}")
            finally:
                os._exit(0) # Emergency shutdown

@client.on(events.NewMessage(outgoing=True, pattern=r'^ذخیره(?: (https://t\.me/(?:c/\d+|[\w]+)/\d+))?$'))  
async def save_message(event):
    if not settings.self_enabled: return
    is_admin = hasattr(event, "_original")
    
    reply = await event.get_reply_message() if not is_admin else await event._original.get_reply_message()  
    link = event.pattern_match.group(1)  
      
    msg = await safe_respond(event, "╮ لطفاً صبر کنید...")  
  
    target_msg = None  
  
    if reply:  
        target_msg = reply  
    elif link:  
        try:  
            match = re.match(r'https://t\.me/(c/\d+|[\w]+)/(\d+)', link)  
            if not match:  
                return await safe_respond(event, "╮ لینک نامعتبر!", edit_msg=msg)  
            
            entity_part = match.group(1)  
            msg_id = int(match.group(2))

            entity = None
            if entity_part.startswith('c/'):
                chat_id_num = int(entity_part.split('/')[1])
                try:
                    entity = await client.get_entity(types.PeerChannel(chat_id_num))
                except Exception as e:
                    print(f"Error getting channel entity for link: {e}")
                    return await safe_respond(event, "╮ کانال پیدا نشد!", edit_msg=msg)
            else:
                try:
                    entity = await client.get_entity(entity_part)
                except Exception as e:
                    print(f"Error getting user/chat entity for link: {e}")
                    return await safe_respond(event, "╮ کاربر/گروه/کانال پیدا نشد!", edit_msg=msg)
  
            target_msg = await client.get_messages(entity, ids=msg_id)  
            if not target_msg:  
                return await safe_respond(event, "╮ پیام پیدا نشد!", edit_msg=msg)  
        except Exception as e:
            print(f"Error parsing link or getting message: {e}")
            traceback.print_exc()
            return await safe_respond(event, "╮ خطا در پیدا کردن پیام!", edit_msg=msg)  
    else:  
        return await safe_respond(event, "╮ استفاده نادرست! (ریپلای یا لینک)", edit_msg=msg)  
  
    try:  
        if target_msg.media:  
            await client.send_file("me", target_msg.media, caption=target_msg.text if target_msg.text else None)  
        elif target_msg.text:  
            await client.send_message("me", target_msg.text)  
        else:  
            return await safe_respond(event, "╮ پیام محتوایی برای ذخیره ندارد!", edit_msg=msg)  
  
        await safe_respond(event, "╮ ذخیره شد.", edit_msg=msg)  
    except Exception as e:
        print(f"Error saving message to 'me': {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در ذخیره پیام!", edit_msg=msg)

@client.on(events.NewMessage(outgoing=True, pattern=r'^دانلود یوتیوب (.+)$'))
async def youtube_download_handler(event):
    if not settings.self_enabled: return
    
    yt_url = event.pattern_match.group(1).strip()
    bot_username = "JetDL_bot" # Renamed from @youtubedl_bot for consistency, as per original code

    if not re.match(r'^https?://(www\.)?(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)', yt_url):
        return await safe_respond(event, "╮ لینک معتبر یوتیوب نیست!")

    current_time = time.time()
    if current_time - settings.last_youtube_time < 30:
        return await safe_respond(event, "╮ لطفاً ۳۰ ثانیه صبر کنید و دوباره تلاش کنید.")
    settings.last_youtube_time = current_time
    settings_manager.schedule_save()

    msg = await safe_respond(event, "╮ لطفاً صبر کنید...")

    try:
        await client.send_message(bot_username, "/start")
        await asyncio.sleep(1) # Give bot a moment
        await client.send_message(bot_username, yt_url)

        found = False
        for _ in range(20): # Try multiple times over 30 seconds
            await asyncio.sleep(1.5)
            async for message in client.iter_messages(bot_username, limit=3):
                if message.video or message.document:
                    await client.send_file(event.chat_id, message.media, caption="╮ ویدئو از یوتیوب دانلود شد!")
                    found = True
                    break
            if found:
                break

        if not found:
            await safe_respond(event, "╮ فایل یافت نشد. لطفاً بعداً دوباره تلاش کنید.", edit_msg=msg)
            return

        # Clean up bot chat history
        try:
            await client(DeleteHistoryRequest(peer=bot_username, max_id=0, revoke=True))
        except Exception as e:
            print(f"Error cleaning YouTube bot history: {e}")

        await msg.delete()

    except Exception as e:
        print(f"Error in youtube_download_handler: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در دانلود از یوتیوب!", edit_msg=msg)

@client.on(events.NewMessage(outgoing=True, pattern=r'^دانلود اینستا (.+)$'))
async def instagram_download_handler(event):
    if not settings.self_enabled: return

    insta_url = event.pattern_match.group(1).strip()
    bot_username = "SaveAsBot"

    if not re.match(r'^https?://(www\.)?(instagram\.com/(reel|p|tv)/[A-Za-z0-9_-]+)', insta_url):
        return await safe_respond(event, "╮ لینک معتبر اینستاگرام نیست!")

    current_time = time.time()
    if current_time - settings.last_instagram_time < 30:
        return await safe_respond(event, "╮ لطفاً ۳۰ ثانیه صبر کنید و دوباره تلاش کنید.")
    settings.last_instagram_time = current_time
    settings_manager.schedule_save()

    msg = await safe_respond(event, "╮ لطفا صبر کنید...")

    try:
        await client.send_message(bot_username, "/start")
        await asyncio.sleep(1.2)
        await client.send_message(bot_username, insta_url)

        found = False
        for _ in range(25): # Try multiple times over ~50 seconds
            await asyncio.sleep(2)
            async for message in client.iter_messages(bot_username, limit=4):
                if message.video or message.document or message.photo:
                    caption_text = "╮ ویدئو/عکس از اینستاگرام دریافت شد!"
                    if message.text and message.text.strip(): # If bot also sends text description
                        caption_text += f"\n\n{message.text}"
                    await client.send_file(event.chat_id, message.media, caption=caption_text)
                    found = True
                    break
            if found:
                break

        if not found:
            await safe_respond(event, "╮ فایل یافت نشد. لطفاً چند دقیقه بعد دوباره تلاش کنید.", edit_msg=msg)
            return

        # Clean up bot chat history
        try:
            await client(DeleteHistoryRequest(peer=bot_username, max_id=0, revoke=True))
        except Exception as e:
            print(f"Error cleaning Instagram bot history: {e}")

        await msg.delete()

    except Exception as e:
        print(f"Error in instagram_download_handler: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در دانلود از اینستاگرام!", edit_msg=msg)

@client.on(events.NewMessage(outgoing=True, pattern=r'^هوش مصنوعی (.+)$'))
async def gpt4_bot_handler(event):
    if not settings.self_enabled: return
    question = event.pattern_match.group(1).strip()
    bot_username = "GPT4Telegrambot"
    temp_channel = "@perplexity_ai" # Use a more reliable public channel if available, or just omit joining if not strictly needed by the bot

    current_time = time.time()
    if current_time - settings.last_gpt_time < 59:
        return await safe_respond(event, "╮ لطفاً یک دقیقه صبر کنید و دوباره تلاش کنید.")
    settings.last_gpt_time = current_time
    settings_manager.schedule_save()

    msg = await safe_respond(event, "╮ لطفاً صبر کنید...")

    try:
        # Joining a channel might not be necessary for most GPT bots.
        # Original code used @perplexity, but it's a channel, not a bot for direct interaction.
        # If the bot _requires_ being in a specific channel to function, then handle it.
        # Assuming direct interaction with GPT4Telegrambot.

        await client.send_message(bot_username, "/start")
        await asyncio.sleep(1.5) # Give bot time to process /start
        await client.send_message(bot_username, question)

        last_response_text = None
        for _ in range(25): # Poll for response for about 45 seconds
            await asyncio.sleep(1.8)
            async for message in client.iter_messages(bot_username, limit=2):
                if not message.text:
                    continue
                # Filter out system messages or initial prompts from the bot itself
                if message.text.startswith("⏳") or message.text.strip() == question or message.text.startswith("/start"):
                    continue
                
                # Check if it's a new, meaningful response
                if message.text != last_response_text:
                    last_response_text = message.text
                    break
            if last_response_text:
                break

        if last_response_text:
            await safe_respond(event, f"╮ پاسخ هوش مصنوعی:\n\n{last_response_text}", edit_msg=msg)
        else:
            await safe_respond(event, "╮ پاسخ دریافت نشد، لطفاً کمی بعد دوباره تلاش کنید.", edit_msg=msg)

        # Clean up bot chat history
        try:
            await client(DeleteHistoryRequest(peer=bot_username, max_id=0, revoke=True))
        except Exception as e:
            print(f"Error cleaning GPT bot history: {e}")

        # Leaving channel (if joined)
        # try:
        #     await client(functions.channels.LeaveChannelRequest(channel=temp_channel))
        # except Exception as e:
        #     print(f"Error leaving temp channel: {e}")

    except Exception as e:
        print(f"Error in gpt4_bot_handler: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در دریافت پاسخ از هوش مصنوعی!", edit_msg=msg)

@client.on(events.NewMessage(outgoing=True, pattern=r'^سین خودکار پیوی روشن$'))
async def enable_auto_read_private(event):
    if not settings.self_enabled: return
    settings.auto_read_private = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^سین خودکار پیوی خاموش$'))
async def disable_auto_read_private(event):
    if not settings.self_enabled: return
    settings.auto_read_private = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^سین خودکار کانال روشن$'))
async def enable_auto_read_channel(event):
    if not settings.self_enabled: return
    settings.auto_read_channel = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^سین خودکار کانال خاموش$'))
async def disable_auto_read_channel(event):
    if not settings.self_enabled: return
    settings.auto_read_channel = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^سین خودکار گروه روشن$'))
async def enable_auto_read_group(event):
    if not settings.self_enabled: return
    settings.auto_read_group = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^سین خودکار گروه خاموش$'))
async def disable_auto_read_group(event):
    if not settings.self_enabled: return
    settings.auto_read_group = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^سین خودکار ربات روشن$'))
async def enable_auto_read_bot(event):
    if not settings.self_enabled: return
    settings.auto_read_bot = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^سین خودکار ربات خاموش$'))
async def disable_auto_read_bot(event):
    if not settings.self_enabled: return
    settings.auto_read_bot = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(incoming=True))
async def auto_read_handler(event):
    if not settings.self_enabled: return
    if event.out: # Don't auto-read outgoing messages
        return

    try:
        if settings.auto_read_private and event.is_private:
            sender = await event.get_sender()
            if not sender.bot: # Don't mark bot messages as read if auto_read_bot is off
                await event.mark_read()

        if settings.auto_read_bot and event.is_private:
            sender = await event.get_sender()
            if sender.bot:
                await event.mark_read()

        if settings.auto_read_group:
            chat = await event.get_chat()
            if getattr(chat, 'megagroup', False) and not event.is_private: # Ensure it's a group, not private
                await event.mark_read()

        if settings.auto_read_channel:
            chat = await event.get_chat()
            if getattr(chat, 'broadcast', False) and not event.is_private: # Ensure it's a channel, not private
                await event.mark_read()

    except Exception as e:
        print(f"Error in auto_read_handler: {e}")
        traceback.print_exc()

@client.on(events.NewMessage(outgoing=True, pattern=r'^اسپم(?: (.+))? (\d+)$'))
async def spam_handler(event):
    if not settings.self_enabled: return
    args = event.pattern_match.group(1)
    count = int(event.pattern_match.group(2))

    if count > 300:
        return await safe_respond(event, "╮ حداکثر اسپم 300 عدد می‌باشد!")

    reply = None
    is_admin = hasattr(event, "_original")
    if is_admin:
        reply = await event._original.get_reply_message()
    elif event.is_reply:
        reply = await event.get_reply_message()

    try:
        if not is_admin: # Delete our own command if not an admin command
            await event.delete()
    except Exception as e:
        print(f"Error deleting spam command: {e}")

    if reply:
        for _ in range(count):
            try:
                await client.send_message(event.chat_id, reply)
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Error sending spam reply: {e}")
                break
    elif args:
        text = args.strip()
        for _ in range(count):
            try:
                await client.send_message(event.chat_id, text)
                await asyncio.sleep(0.2)
            except Exception as e:
                print(f"Error sending spam text: {e}")
                break
    else:
        await safe_respond(event, "╮ لطفاً ریپلای کنید یا متن وارد کنید!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^ریست$'))
async def reset_handler(event):
    if not settings.self_enabled: return
    if event.sender_id in settings.admin_list:
        return await safe_respond(event, "╮ ادمین مجاز به استفاده از این دستور نیست!", reply_to_msg_id=event.id)

    # Reinitialize settings to default
    global settings
    settings = BotSettings() # Create a fresh settings object with defaults
    await settings_manager.save_settings() # Save the reset settings
    await safe_respond(event, "╮ تنظیمات باموفقیت ریست شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم دشمن(?: (.+))?$'))
async def add_enemy(event):
    if not settings.self_enabled: return
    user_input = event.pattern_match.group(1)
    user_id = None

    reply = await event.get_reply_message() if not hasattr(event, "_original") else await event._original.get_reply_message()

    try:
        if reply:
            user_id = reply.sender_id
        elif user_input:
            user_id = await resolve_user_id(client, user_input)
        else:
            await safe_respond(event, "╮ استفاده نادرست از دستور!")
            return

        if user_id is None:
            await safe_respond(event, "╮ کاربر نامعتبر!")
            return

        if user_id not in settings.enemy_list:
            settings.enemy_list.append(user_id)
            await settings_manager.save_settings()
            await safe_respond(event, "╮ اضافه شد.")
        else:
            await safe_respond(event, "╮ از قبل وجود دارد!")
    except Exception as e:
        print(f"Error adding enemy: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در تنظیم دشمن!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حذف دشمن(?: (.+))?$'))
async def remove_enemy(event):
    if not settings.self_enabled: return
    user_input = event.pattern_match.group(1)
    user_id = None

    reply = await event.get_reply_message() if not hasattr(event, "_original") else await event._original.get_reply_message()

    try:
        if reply:
            user_id = reply.sender_id
        elif user_input:
            user_id = await resolve_user_id(client, user_input)
        else:
            await safe_respond(event, "╮ استفاده نادرست از دستور!")
            return

        if user_id is None:
            await safe_respond(event, "╮ کاربر نامعتبر!")
            return

        if user_id in settings.enemy_list:
            settings.enemy_list.remove(user_id)
            await settings_manager.save_settings()
            await safe_respond(event, "╮ حذف شد.")
        else:
            await safe_respond(event, "╮ در لیست وجود ندارد!")
    except Exception as e:
        print(f"Error removing enemy: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در حذف دشمن!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^پاکسازی لیست دشمن$'))
async def clear_enemies(event):
    if not settings.self_enabled: return
    settings.enemy_list.clear()
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خالی شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم فحش (.+)$'))
async def add_insult(event):
    if not settings.self_enabled: return
    insult = event.pattern_match.group(1).strip()
    if insult not in settings.insult_list:
        settings.insult_list.append(insult)
        # Re-shuffle insult queue to include new insult
        settings.insult_queue = settings.insult_list.copy()
        random.shuffle(settings.insult_queue)
        await settings_manager.save_settings()
        await safe_respond(event, f"""╮ اضافه شد:
`{insult}`""")
    else:
        await safe_respond(event, "╮ وجود دارد!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حذف فحش (.+)$'))
async def remove_insult(event):
    if not settings.self_enabled: return
    insult = event.pattern_match.group(1).strip()
    if insult in settings.insult_list:
        settings.insult_list.remove(insult)
        # Re-shuffle insult queue after removal
        settings.insult_queue = settings.insult_list.copy()
        random.shuffle(settings.insult_queue)
        await settings_manager.save_settings()
        await safe_respond(event, f"""╮ حذف شد:
`{insult}`""")
    else:
        await safe_respond(event, "╮ وجود ندارد!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^پاکسازی لیست فحش$'))
async def clear_insults(event):
    if not settings.self_enabled: return
    settings.insult_list.clear()
    settings.insult_queue.clear()
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خالی شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^لیست فحش$'))
async def list_insults(event):
    if not settings.self_enabled: return
    if not settings.insult_list:
        await safe_respond(event, "╮ خالی!")
        return

    # Create a temporary file to send the list
    temp_file_path = os.path.join(tempfile.gettempdir(), "insults_list.txt")
    try:
        with open(temp_file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(settings.insult_list))

        await client.send_file(event.chat_id, temp_file_path, caption="╮ لیست فحش:")
    except Exception as e:
        print(f"Error listing insults: {e}")
        await safe_respond(event, "╮ خطا در دریافت لیست فحش!")
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)

@client.on(events.NewMessage(outgoing=True, pattern=r'^لیست دشمن$'))
async def list_enemies(event):
    if not settings.self_enabled: return
    if not settings.enemy_list:
        await safe_respond(event, "╮ خالی!")
        return

    result = "╮ لیست دشمن:\n\n"
    for user_id in settings.enemy_list:
        try:
            user = await client.get_entity(user_id)
            name = get_display_name(user) or "?"
            mention = f"[{name}](tg://user?id={user_id})"
            result += f"> {mention}\n"
        except Exception as e:
            print(f"Error getting enemy entity {user_id}: {e}")
            result += f"> [کاربر ناشناس](tg://user?id={user_id})\n"

    await safe_respond(event, result, parse_mode='md')

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم لیست فحش$'))
async def import_insult_file(event):
    if not settings.self_enabled: return
    
    reply = await event.get_reply_message() if not hasattr(event, "_original") else await event._original.get_reply_message()

    if not reply or not reply.file or not reply.file.name.endswith(".txt"):
        return await safe_respond(event, "╮ لطفاً به فایل .txt ریپلای کنید!")

    temp_path = await reply.download_media(file=tempfile.gettempdir())
    try:
        with open(temp_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        if not lines:
            return await safe_respond(event, "╮ فایل خالی است!")

        settings.insult_list.clear()
        settings.insult_list.extend(lines)
        settings.insult_queue = settings.insult_list.copy() # Re-initialize queue
        random.shuffle(settings.insult_queue)
        await settings_manager.save_settings()
        await safe_respond(event, f"╮ تعداد {len(settings.insult_list)} فحش تنظیم شد.")
    except Exception as e:
        print(f"Error importing insult file: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در تنظیم لیست!")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@client.on(events.NewMessage(incoming=True))
async def auto_insult(event):
    if not settings.self_enabled: return
    if not settings.insult_list or not settings.enemy_list:
        return

    me = await client.get_me()
    if event.sender_id == me.id: # Don't insult ourselves
        return

    # Check if it's a private chat with an enemy or a group/channel message from an enemy
    if event.is_private and event.sender_id in settings.enemy_list:
        pass # Allow insult
    elif event.is_group or event.is_channel:
        if event.sender_id in settings.enemy_list:
            pass # Allow insult
        else:
            return # Not an enemy in group/channel
    else:
        return # Not an enemy and not a private chat

    # Don't insult in the gap channel or if the message is a command
    if event.chat_id == settings.the_gap or event.raw_text.startswith(settings.admin_prefix):
        return

    if not settings.insult_queue:
        settings.insult_queue = settings.insult_list.copy()
        random.shuffle(settings.insult_queue)
        settings_manager.schedule_save() # Save state if queue was refilled

    if settings.insult_queue:
        insult = settings.insult_queue.pop(0) # Use pop(0) for a queue-like behavior
        settings_manager.schedule_save() # Save updated queue state
        try:
            await event.reply(insult)
        except Exception as e:
            print(f"Error sending auto-insult: {e}")
            traceback.print_exc()

@client.on(events.NewMessage(incoming=True))
async def handle_new_message_db_save(event):
    if not settings.self_enabled: return
    # Only track private messages for now, as specified by original code's `PeerUser` check logic.
    # To track group/channel messages, remove the `PeerUser` check or add more conditions.
    if not isinstance(event.message.peer_id, PeerUser) and not (event.is_private and event.sender_id != (await client.get_me()).id):
        return

    msg: Message = event.message
    sender = await msg.get_sender()
    username = sender.username or get_display_name(sender) or "Unknown"

    content = msg.message or ''
    media_type = None
    media_link = None
    file_path = None

    try:
        if msg.media:
            media_type = msg.file.mime_type or msg.file.ext or "media"
            file_path = await msg.download_media(file=os.path.join(DOWNLOAD_FOLDER, str(msg.id)))
            
            if settings.media_channel and client:
                try:
                    sent_msg = await client.send_file(settings.media_channel, file_path, caption=f"╮ مدیا از {username} (عددی: {sender.id})", force_document=True) # force_document to ensure link is generated
                    if isinstance(sent_msg.peer_id, types.PeerChannel) and str(sent_msg.peer_id.channel_id).startswith("-100"): # Check if it's a channel message
                        media_link = f"https://t.me/c/{str(sent_msg.peer_id.channel_id)[4:]}/{sent_msg.id}"
                    elif isinstance(sent_msg.peer_id, types.PeerChannel): # Regular channel ID
                         media_link = f"https://t.me/c/{sent_msg.peer_id.channel_id}/{sent_msg.id}"
                except Exception as e:
                    print(f"Error sending media to media_channel: {e}")
                    media_link = "Error generating link"
        
        tehran_time = to_tehran_time(msg.date)

        cursor.execute('''
            INSERT INTO messages (message_id, user_id, username, chat_id, content, date, media_type, media_link)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            msg.id, sender.id, username, msg.chat_id, content,
            tehran_time, media_type, media_link
        ))
        conn.commit()

    except Exception as e:
        print(f"Error in handle_new_message_db_save: {e}")
        traceback.print_exc()
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path) # Clean up downloaded media

@client.on(events.MessageEdited())
async def handle_edited_message(event):
    if not settings.self_enabled: return
    if not settings.track_edits:
        return

    # Only track private messages for now, matching `handle_new_message_db_save`
    if not isinstance(event.message.peer_id, PeerUser) and not (event.is_private and event.sender_id != (await client.get_me()).id):
        return

    msg: Message = event.message
    new_content = msg.message or ''
    edit_time = to_tehran_time(msg.edit_date or msg.date)

    cursor.execute('SELECT content, date, username, user_id FROM messages WHERE message_id=?', (msg.id,))
    row = cursor.fetchone()

    if row:
        old_content, original_date, username, user_id = row
        if old_content != new_content:
            cursor.execute('UPDATE messages SET content=? WHERE message_id=?', (new_content, msg.id))
            conn.commit()

            text = (
                f"╮ پیام ویرایش شده!\n"
                f"│ کاربر: `{username}` (عددی: `{user_id}`)\n"
                f"│ زمان ارسال: `{original_date}`\n"
                f"│ زمان ویرایش: `{edit_time}`\n"
                f"│ پیام قدیمی: `{old_content or '[No content]'}`\n"
                f"╯ پیام جدید: `{new_content or '[No content]'}`\n"
            )
            if settings.media_channel:
                try:
                    await client.send_message(settings.media_channel, text, link_preview=False)
                except Exception as e:
                    print(f"Error sending edited message to media_channel: {e}")
                    traceback.print_exc()
    else:
        # Message not found in DB, potentially edited before bot started tracking or missed
        sender = await msg.get_sender()
        username = sender.username or get_display_name(sender) or "Unknown"
        user_id = sender.id
        text = (
            f"╮ پیام ویرایش شده (جدید)!\n"
            f"│ کاربر: `{username}` (عددی: `{user_id}`)\n"
            f"│ زمان ویرایش: `{edit_time}`\n"
            f"╯ پیام جدید: `{new_content or '[No content]'}`\n"
        )
        if settings.media_channel:
            try:
                await client.send_message(settings.media_channel, text, link_preview=False)
            except Exception as e:
                print(f"Error sending newly edited message to media_channel: {e}")
                traceback.print_exc()

@client.on(events.MessageDeleted())
async def handle_deleted_message(event):
    if not settings.self_enabled: return
    if not settings.track_deletions:
        return

    # To ensure we only process messages that were originally tracked,
    # we rely on the database.
    
    for msg_id in event.deleted_ids:
        cursor.execute('SELECT * FROM messages WHERE message_id=?', (msg_id,))
        row = cursor.fetchone()

        if row and row[6] == 0: # row[6] is 'deleted' flag (0 for not deleted)
            cursor.execute('UPDATE messages SET deleted=1 WHERE message_id=?', (msg_id,))
            conn.commit()

            deleted_text = (
                f"╮ پیام حذف شده!\n"
                f"│ کاربر: `{row[2]}` (عددی: `{row[1]}`)\n"
                f"│ زمان: `{row[5]}`\n"
            )

            if row[4]: # content
                deleted_text += f"│ پیام: `{row[4]}`\n"
            
            if row[7] and row[8]: # media_type and media_link
                deleted_text += f"│ نوع مدیا: `{row[7]}`\n"
                deleted_text += f"╯ مدیا: [مشاهده مدیا]({row[8]})\n"
            else:
                deleted_text += "╯ (بدون مدیا یا لینک مدیا ناموجود)\n"

            if settings.media_channel:
                try:
                    await client.send_message(settings.media_channel, deleted_text, link_preview=False, parse_mode='markdown')
                except Exception as e:
                    print(f"Error sending deleted message to media_channel: {e}")
                    traceback.print_exc()

@client.on(events.NewMessage(outgoing=True, pattern=r'^ذخیره حذف روشن$'))
async def enable_savedel(event):
    if not settings.self_enabled: return
    settings.track_deletions = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^ذخیره حذف خاموش$'))
async def disable_savedel(event):
    if not settings.self_enabled: return
    settings.track_deletions = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^ذخیره ویرایش روشن$'))
async def enable_savedit(event):
    if not settings.self_enabled: return
    settings.track_edits = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^ذخیره ویرایش خاموش$'))
async def disable_savedit(event):
    if not settings.self_enabled: return
    settings.track_edits = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم ذخیره (.+)$'))
async def set_media_channel(event):
    if not settings.self_enabled: return
    
    link = event.pattern_match.group(1).strip()
    
    # Try to resolve entity from link
    entity = None
    try:
        # Expecting a channel username or invite link (e.g., https://t.me/channel_name)
        # or c/-100XXXXXXXXXX
        if link.startswith('https://t.me/c/'):
            parts = link.split('/')
            if len(parts) >= 5:
                channel_id_str = parts[4]
                if channel_id_str.isdigit():
                    entity = await client.get_entity(int(channel_id_str))
        elif link.startswith('https://t.me/'):
            username = link.split('/')[-1]
            entity = await client.get_entity(username)
        else: # Maybe a direct username or ID
            entity = await client.get_entity(link)

        if not isinstance(entity, types.Channel) or not entity.broadcast:
            return await safe_respond(event, "╮ لینک/آیدی وارد شده مربوط به کانال نیست!")

        settings.media_channel = entity.id # Store channel ID
        await settings_manager.save_settings()
        await safe_respond(event, f"╮ کانال ذخیره روی `{entity.title}` تنظیم شد.")
    except Exception as e:
        print(f"Error setting media channel: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در تنظیم کانال ذخیره! لینک/آیدی نامعتبر یا کانال یافت نشد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^منشی روشن$'))
async def enable_auto_reply(event):
    if not settings.self_enabled: return
    settings.auto_reply_enabled = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^منشی خاموش$'))
async def disable_auto_reply(event):
    if not settings.self_enabled: return
    settings.auto_reply_enabled = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم منشی$'))
async def set_auto_reply(event):
    if not settings.self_enabled: return
    
    reply = await event.get_reply_message() if not hasattr(event, "_original") else await event._original.get_reply_message()

    if not reply:
        return await safe_respond(event, "╮ استفاده نادرست از دستور! (باید به یک پیام ریپلای کنید)")

    # Store info to retrieve message later
    settings.auto_reply_message_info = {
        'chat_id': reply.chat_id,
        'message_id': reply.id
    }
    await settings_manager.save_settings()
    await safe_respond(event, "╮ تنظیم شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم زمان منشی (\d+)$'))
async def set_auto_reply_interval(event):
    if not settings.self_enabled: return
    minutes = int(event.pattern_match.group(1))
    if minutes < 5 or minutes > 60:
        return await safe_respond(event, "╮ فقط اعداد 5 الی 60 دقیقه مجاز می‌باشد!")

    settings.auto_reply_interval = minutes * 60 # Convert to seconds
    await settings_manager.save_settings()
    await safe_respond(event, "╮ تنظیم شد.")

@client.on(events.NewMessage(incoming=True))
async def auto_reply_handler(event):
    if not settings.self_enabled: return
    if not event.is_private or not settings.auto_reply_enabled or not settings.auto_reply_message_info:
        return

    try:
        sender = await event.get_sender()
        if getattr(sender, "bot", False) or sender.id == (await client.get_me()).id:
            return # Don't reply to bots or self

        me = await client.get_me()
        if isinstance(me.status, types.UserStatusOnline) and me.status.was_online is None:
            # If user is explicitly online and not just "recently online", don't auto-reply
            return
    except Exception as e:
        print(f"Error checking sender/status in auto_reply_handler: {e}")
        return

    user_id = event.sender_id
    now = time.time()
    last_time = settings.last_auto_reply_times.get(user_id)

    if last_time and (now - last_time) < settings.auto_reply_interval:
        return # Too soon to reply again

    # Retrieve the auto-reply message
    reply_msg = None
    try:
        reply_msg = await client.get_messages(
            settings.auto_reply_message_info['chat_id'],
            ids=settings.auto_reply_message_info['message_id']
        )
    except Exception as e:
        print(f"Error fetching auto_reply_message: {e}")
        settings.auto_reply_message_info = None # Invalidate if not found
        settings_manager.schedule_save()
        return

    if reply_msg:
        try:
            if reply_msg.media:
                await client.send_file(
                    event.chat_id,
                    file=reply_msg.media,
                    caption=reply_msg.message or "",
                    reply_to=event.id
                )
            elif reply_msg.message:
                await event.reply(reply_msg.message)

            settings.last_auto_reply_times[user_id] = now
            settings_manager.schedule_save()
        except Exception as e:
            print(f"Error sending auto-reply: {e}")
            traceback.print_exc()

@client.on(events.NewMessage(outgoing=True, pattern=r'^دریافت بکاپ$'))
async def backup_handler(event):
    if not settings.self_enabled: return
    # Use the settings_manager to get the latest state
    await settings_manager.save_settings() # Ensure all current settings are saved to file first

    # The backup process will just send the settings.json file
    temp_backup_file = os.path.join(tempfile.gettempdir(), "selfbot_backup.json")
    try:
        # Read from settings.json and ensure it's properly formatted for external backup
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f_read:
            backup_data = json.load(f_read)
        
        # Add a signature and version to the backup for validation during restore
        backup_data["backup_signature"] = "alfred_selfbot_backup_v2" # Updated version
        backup_data["backup_version"] = 2.0
        backup_data["timestamp"] = datetime.now(pytz.timezone('Asia/Tehran')).strftime("%Y/%m/%d %H:%M:%S")

        with open(temp_backup_file, 'w', encoding='utf-8') as f_write:
            json.dump(backup_data, f_write, ensure_ascii=False, indent=2)

        reply_id = None
        if hasattr(event, "_original") and hasattr(event._original, "id"):
            reply_id = event._original.id
        
        await client.send_file(event.chat_id, temp_backup_file, caption="╮ بکاپ ایجاد شد!", reply_to=reply_id)
    except Exception as e:
        print(f"Error creating backup: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در ایجاد بکاپ!")
    finally:
        if os.path.exists(temp_backup_file):
            os.remove(temp_backup_file)

@client.on(events.NewMessage(outgoing=True, pattern=r'^اجرای بکاپ$'))
async def restore_backup(event):
    if not settings.self_enabled: return
    
    msg = await safe_respond(event, "╮ لطفاً صبر کنید تا بکاپ بازیابی شود...")

    reply = await event.get_reply_message() if not hasattr(event, "_original") else await event._original.get_reply_message()

    if not reply or not reply.file or not reply.file.name.endswith(".json"):
        return await safe_respond(event, "╮ استفاده نادرست از دستور! (به فایل بکاپ .json ریپلای کنید)", edit_msg=msg)

    temp_path = await reply.download_media(file=tempfile.gettempdir())
    try:
        with open(temp_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if data.get("backup_signature") != "alfred_selfbot_backup_v2" and \
           data.get("backup_signature") != "alfred_selfbot_backup_v1": # Allow restoring older versions if compatible
            return await safe_respond(event, "╮ این فایل بکاپ معتبر نیست!", edit_msg=msg)

        # Restore all settings
        for key, value in data.items():
            if hasattr(settings, key):
                if key == "pv_warned_users" or key == "comment_channels":
                    setattr(settings, key, set(value))
                elif key == "last_auto_reply_times":
                    setattr(settings, key, {int(k): v for k, v in value.items()})
                else:
                    setattr(settings, key, value)
        
        # Re-initialize insult_queue after restoring insult_list
        settings.insult_queue = settings.insult_list.copy()
        random.shuffle(settings.insult_queue)

        await settings_manager.save_settings() # Save the restored settings
        await safe_respond(event, "╮ بکاپ با موفقیت اجرا شد.", edit_msg=msg)
    except Exception as e:
        print(f"Error restoring backup: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در اجرای بکاپ!", edit_msg=msg)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@client.on(events.NewMessage(outgoing=True, pattern=r'^امروز$'))
async def today_handler(event):
    if not settings.self_enabled: return
    try:
        tehran_tz = pytz.timezone('Asia/Tehran')
        now_utc = datetime.now(timezone.utc)
        now_tehran = now_utc.astimezone(tehran_tz)

        miladi_time = now_tehran.strftime("%H:%M")
        utc_time = now_utc.strftime("%H:%M")

        miladi_date = now_tehran.strftime("%Y/%m/%d")
        miladi_day = now_tehran.strftime("%A")

        jalali_now = jdatetime.datetime.fromgregorian(datetime=now_tehran)
        jalali_date = jalali_now.strftime("%Y/%m/%d")
        jalali_day = jalali_now.strftime("%A")

        week_days_fa = {
            "Saturday": "شنبه", "Sunday": "یکشنبه", "Monday": "دوشنبه",
            "Tuesday": "سه‌شنبه", "Wednesday": "چهارشنبه", "Thursday": "پنجشنبه",
            "Friday": "جمعه"
        }
        miladi_day_fa = week_days_fa.get(miladi_day, miladi_day)
        jalali_day_fa = week_days_fa.get(jalali_day, jalali_day)

        # Norooz calculation
        current_j_year = jalali_now.year
        # Norooz is always Farvardin 1st
        next_norooz_j = jdatetime.datetime(current_j_year + 1 if jalali_now.month >= 1 and (jalali_now.month > 1 or jalali_now.day >= 1) else current_j_year, 1, 1, 0, 0, 0, tzinfo=tehran_tz)
        if now_tehran > next_norooz_j.togregorian().replace(tzinfo=tehran_tz):
             next_norooz_j = jdatetime.datetime(current_j_year + 1, 1, 1, 0, 0, 0, tzinfo=tehran_tz)
        
        next_norooz_g = next_norooz_j.togregorian().replace(tzinfo=tehran_tz)
        delta_norooz = next_norooz_g - now_tehran
        days_n = delta_norooz.days
        hours_n, remainder_n = divmod(int(delta_norooz.total_seconds() % (3600*24)), 3600)
        minutes_n = remainder_n // 60

        # Christmas calculation
        current_m_year = now_tehran.year
        christmas = datetime(current_m_year, 12, 25, 0, 0, 0, tzinfo=tehran_tz)
        if now_tehran > christmas:
            christmas = christmas.replace(year=current_m_year + 1)
        delta_christmas = christmas - now_tehran
        days_c = delta_christmas.days
        hours_c, remainder_c = divmod(int(delta_christmas.total_seconds() % (3600*24)), 3600)
        minutes_c = remainder_c // 60

        text = f"""اطلاعات امروز:

╮ ساعت (تهران) : {miladi_time}
│ تاریخ (شمسی) : {jalali_day_fa} - {jalali_date}
╯ باقی مانده تا نوروز : {days_n} روز و {hours_n} ساعت و {minutes_n} دقیقه

╮ ساعت (جهانی) : {utc_time}
│ تاریخ (میلادی) : {miladi_day_fa} - {miladi_date}
╯ باقی مانده تا کریسمس : {days_c} روز و {hours_c} ساعت و {minutes_c} دقیقه"""

        await safe_respond(event, text)

    except Exception as e:
        print(f"Error in today_handler: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در دریافت تاریخ و زمان!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^پاکسازی من (.+)$'))
async def clear_my_messages(event):
    if not settings.self_enabled: return
    try:
        arg = event.pattern_match.group(1).strip()
        me = await client.get_me()
        my_id = me.id

        is_admin = hasattr(event, "_original")

        chat_id = event.chat_id if not is_admin else event._original.chat_id
        ref_msg_id = event.id if not is_admin else event._original.id

        if not is_admin: # Delete command message if not admin
            try:
                await event.delete()
            except errors.MessageDeleteForbiddenError:
                pass # Can't delete if too old or not allowed
            except Exception as e:
                print(f"Error deleting clear_my_messages command: {e}")


        if arg == "همه":
            # For "همه", iterate and delete in chunks to avoid rate limits
            total_deleted = 0
            while True:
                messages_to_delete = []
                async for msg in client.iter_messages(chat_id, limit=100):
                    if msg.sender_id == my_id:
                        messages_to_delete.append(msg.id)
                
                if not messages_to_delete:
                    break # No more messages to delete

                try:
                    await client.delete_messages(chat_id, messages_to_delete)
                    total_deleted += len(messages_to_delete)
                    await asyncio.sleep(1) # Small delay to respect rate limits
                except Exception as e:
                    print(f"Error deleting batch of messages: {e}")
                    # If an error occurs, try deleting individually or break
                    for msg_id_single in messages_to_delete:
                        try:
                            await client.delete_messages(chat_id, msg_id_single)
                            total_deleted += 1
                        except Exception as e_single:
                            print(f"Error deleting single message {msg_id_single}: {e_single}")
                    break # Stop trying to delete if errors persist
            
            await safe_respond(event, f"╮ تعداد {total_deleted} پیام از شما پاکسازی شد.", reply_to_msg_id=ref_msg_id)
            return

        if arg.isdigit():
            limit = int(arg)
            deleted_count = 0
            messages_to_delete = []

            # Fetch more messages than 'limit' to ensure we find our messages among others
            async for msg in client.iter_messages(chat_id, limit=limit + 50, max_id=ref_msg_id):
                if msg.sender_id == my_id:
                    messages_to_delete.append(msg.id)
                    deleted_count += 1
                    if deleted_count >= limit:
                        break
            
            if messages_to_delete:
                try:
                    await client.delete_messages(chat_id, messages_to_delete)
                except Exception as e:
                    print(f"Error deleting specified number of messages: {e}")
                    # Fallback to individual deletions if batch fails
                    for msg_id_single in messages_to_delete:
                        try:
                            await client.delete_messages(chat_id, msg_id_single)
                        except Exception as e_single:
                            print(f"Error deleting single message {msg_id_single}: {e_single}")
            
            await safe_respond(event, f"╮ تعداد {deleted_count} پیام از شما پاکسازی شد.", reply_to_msg_id=ref_msg_id)
            return

        await safe_respond(event, "╮ استفاده نادرست از دستور! (باید 'همه' یا یک عدد وارد کنید)", reply_to_msg_id=ref_msg_id)

    except Exception as e:
        print(f"[clear_my_messages error] {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در پاکسازی!", reply_to_msg_id=event.id if not is_admin else event._original.id)

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم تاریخ (.+)$'))
async def set_date_type(event):
    if not settings.self_enabled: return
    arg = event.pattern_match.group(1).strip().lower()

    if arg in ["شمسی", "jalali"]:
        settings.date_type = "jalali"
        await settings_manager.save_settings()
        await safe_respond(event, "╮ تنظیم شد.")
    elif arg in ["میلادی", "gregorian"]:
        settings.date_type = "gregorian"
        await settings_manager.save_settings()
        await safe_respond(event, "╮ تنظیم شد.")
    else:
        await safe_respond(event, "╮ استفاده نادرست از دستور! (شمسی/میلادی)")

# Replaced original halat_handler to separate command setting from message formatting logic
@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم حالت (.+)$'))
async def set_text_halat(event):
    if not settings.self_enabled: return
    if event.sender_id in settings.admin_list and not hasattr(event, "_original"):
        return await safe_respond(event, "╮ ادمین مجاز به استفاده از این دستور نیست!", reply_to_msg_id=event.id)

    fa_halat = event.pattern_match.group(1).strip()
    halat_map = {
        "بولد": "bold", "ایتالیک": "italic", "زیرخط": "underline",
        "استرایک": "strikethrough", "کدینگ": "mono", "اسپویلر": "spoiler"
    }
    
    halating = halat_map.get(fa_halat)

    if not halating:
        await safe_respond(event, "╮ حالت نامعتبر!")
    else:
        settings.current_halat = halating
        await settings_manager.save_settings()
        await safe_respond(event, "╮ تنظیم شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت متن خاموش$'))
async def disable_text_halat(event):
    if not settings.self_enabled: return
    if event.sender_id in settings.admin_list and not hasattr(event, "_original"):
        return await safe_respond(event, "╮ ادمین مجاز به استفاده از این دستور نیست!", reply_to_msg_id=event.id)

    settings.current_halat = None
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, func=lambda e: e.text and not any(re.fullmatch(p, e.text) for p in COMMAND_HANDLERS.keys())))
async def format_outgoing_message_with_halat(event):
    # This handler only formats *new* outgoing messages that are *not* recognized as commands.
    if not settings.self_enabled: return
    if not settings.current_halat:
        return # No formatting needed

    message = event.message
    if not message.text: # Only format text messages
        return

    text_to_format = message.text
    formatted = text_to_format

    if settings.current_halat == "bold":
        formatted = f"<b>{formatted}</b>"
        await message.edit(formatted, parse_mode="html")
    elif settings.current_halat == "italic":
        formatted = f"<i>{formatted}</i>"
        await message.edit(formatted, parse_mode="html")
    elif settings.current_halat == "strikethrough":
        formatted = f"<s>{formatted}</s>"
        await message.edit(formatted, parse_mode="html")
    elif settings.current_halat == "underline":
        formatted = f"<u>{formatted}</u>"
        await message.edit(formatted, parse_mode="html")
    elif settings.current_halat == "mono":
        formatted = f"<code>{formatted}</code>"
        await message.edit(formatted, parse_mode="html")
    elif settings.current_halat == "spoiler":
        # Telethon's markdown.parse can handle [text](spoiler)
        formatted_text = f"[{text_to_format}](spoiler)"
        text, entities = CustomMarkdown.parse(formatted_text)
        await message.edit(text, formatting_entities=entities)

@client.on(events.NewMessage(outgoing=True, pattern=r'^\+?مشخصات(?: ([^\n]+))?$'))
async def user_info_handler(event):
    if not settings.self_enabled: return
    is_admin = hasattr(event, "_original")
    
    reply = await event.get_reply_message() if not is_admin else await event._original.get_reply_message()
    arg = event.pattern_match.group(1)
    user = None
    
    msg = await safe_respond(event, "╮ لطفاً صبر کنید...")

    try:
        if reply:
            user = await client.get_entity(reply.sender_id)
        elif arg:
            user_id_resolved = await resolve_user_id(client, arg)
            if user_id_resolved:
                user = await client.get_entity(user_id_resolved)
        else:
            return await safe_respond(event, "╮ استفاده نادرست از دستور! (ریپلای، یوزرنیم یا آیدی)", edit_msg=msg)
    
        if not user:
            return await safe_respond(event, "╮ کاربر یافت نشد!", edit_msg=msg)

        user_id = user.id
        username = f"@{user.username}" if user.username else "-"
        first_name = get_display_name(user)
        mention = f"[{first_name}](tg://user?id={user_id})"

        photos = await client(GetUserPhotosRequest(user_id, offset=0, max_id=0, limit=1)) # Only get the latest photo
        profile_photo = photos.photos[0] if photos.photos else None
        
        # Get total photo count
        full_user = await client(GetFullUserRequest(user_id))
        photo_count = full_user.full_user.photos_count if full_user and full_user.full_user else 0


        caption = f"""اطلاعات کاربر:

╮ نام کاربر : {mention}
│ آیدی عددی : `{user_id}`
│ یوزرنیم : {username}
╯ تعداد تصاویر پروفایل : {photo_count} عدد
"""
        if profile_photo:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmpfile:
                file_path = tmpfile.name
            await client.download_media(profile_photo, file=file_path)

            await client.send_file(
                event.chat_id,
                file=file_path,
                caption=caption,
                parse_mode="md",
                reply_to=(reply.id if reply else (event._original.id if is_admin else None))
            )
            os.remove(file_path)
            await msg.delete() # Delete the "لطفا صبر کنید" message

        else:
            await safe_respond(event, caption, edit_msg=msg, parse_mode="md")

    except Exception as e:
        print(f"Error in user_info_handler: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در دریافت اطلاعات کاربر!", edit_msg=msg)

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم ری اکشن(?: (.+))?$'))
async def set_react_handler(event):
    if not settings.self_enabled: return
    is_admin = hasattr(event, "_original")
    reply = await event.get_reply_message() if not is_admin else await event._original.get_reply_message()

    args = event.pattern_match.group(1)
    
    target_user_id = None
    emoji = None

    if reply and args: # Command like `تنظیم ری اکشن 👍` and replying
        emoji = args.strip().split()[0] # First word is emoji
        target_user_id = reply.sender_id
    elif not reply and args and len(args.split()) >= 2: # Command like `تنظیم ری اکشن 👍 @username` or `👍 12345`
        parts = args.split()
        emoji = parts[0]
        user_identifier = parts[1]
        target_user_id = await resolve_user_id(client, user_identifier)
    else:
        return await safe_respond(event, "╮ استفاده نادرست از دستور! (مثال: `تنظیم ری اکشن 👍 @user` یا ریپلای و `تنظیم ری اکشن 👍`)")
    
    if target_user_id and emoji:
        settings.auto_react[target_user_id] = emoji
        await settings_manager.save_settings()
        await safe_respond(event, "╮ تنظیم شد.")
    else:
        await safe_respond(event, "╮ کاربر یا ایموجی نامعتبر!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^لیست ری اکشن$'))
async def list_react_handler(event):
    if not settings.self_enabled: return
    if not settings.auto_react:
        await safe_respond(event, "╮ لیست خالی است.")
    else:
        lines = []
        for uid, emoji in settings.auto_react.items():
            try:
                user = await client.get_entity(uid)
                name = get_display_name(user) or str(uid)
                lines.append(f"[{name}](tg://user?id={uid}) : {emoji}")
            except Exception:
                lines.append(f"`{uid}` : {emoji} (کاربر ناشناس)")

        await safe_respond(event, "╮ لیست ری‌اکشن:\n" + "\n".join(lines), parse_mode='md')

@client.on(events.NewMessage(outgoing=True, pattern=r'^حذف ری اکشن(?: (.+))?$'))
async def remove_react_handler(event):
    if not settings.self_enabled: return
    is_admin = hasattr(event, "_original")
    reply = await event.get_reply_message() if not is_admin else await event._original.get_reply_message()
    arg = event.pattern_match.group(1)

    target_user_id = None

    if reply and not arg: # Reply to a user
        target_user_id = reply.sender_id
    elif arg: # Username or ID directly
        target_user_id = await resolve_user_id(client, arg)
    
    if target_user_id and target_user_id in settings.auto_react:
        settings.auto_react.pop(target_user_id)
        await settings_manager.save_settings()
        await safe_respond(event, "╮ حذف شد.")
    else:
        await safe_respond(event, "╮ خطا در حذف ری اکشن! (کاربر در لیست نیست یا نامعتبر است)")

@client.on(events.NewMessage(outgoing=True, pattern=r'^پاکسازی لیست ری اکشن$'))
async def remove_all_react_handler(event):
    if not settings.self_enabled: return
    settings.auto_react.clear()
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خالی شد.")

@client.on(events.NewMessage(incoming=True))
async def react(event):
    if not settings.self_enabled: return
    if event.chat_id == settings.the_gap: # Skip specific chat
        return

    me = await client.get_me()
    if event.sender_id == me.id: # Don't react to our own messages
        return

    if event.sender_id in settings.auto_react:
        emoji = settings.auto_react[event.sender_id]
        try:
            await client(functions.messages.SendReactionRequest(
                peer=event.chat_id,
                msg_id=event.id,
                reaction=[types.ReactionEmoji(emoticon=emoji)],
                big=False # Big reaction is often premium only
            ))
        except errors.MessageAuthorRequiredError:
            print(f"Cannot react to message {event.id}: Message author required (not in group/channel?)")
        except errors.MessageIdInvalidError:
            print(f"Cannot react to message {event.id}: Message ID invalid (already deleted?)")
        except errors.ReactionInvalidError:
            print(f"Cannot react to message {event.id}: Invalid reaction emoji '{emoji}'")
        except Exception as e:
            print(f"Error sending auto-reaction for {event.sender_id}: {e}")
            traceback.print_exc()

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم کامنت اول (.+)$'))
async def add_comment_channel(event):
    if not settings.self_enabled: return
    try:
        arg = event.pattern_match.group(1).strip()
        entity = await client.get_entity(arg)

        if not isinstance(entity, types.Channel) or not entity.broadcast:
            return await safe_respond(event, "╮ آیدی/یوزرنیم مربوط به کانال نیست!")

        settings.comment_channels.add(entity.id)
        await settings_manager.save_settings()
        await safe_respond(event, "╮ تنظیم شد.")
    except Exception as e:
        print(f"Error adding comment channel: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ کانال یافت نشد یا نامعتبر است!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حذف کامنت اول (.+)$'))
async def remove_comment_channel(event):
    if not settings.self_enabled: return
    try:
        arg = event.pattern_match.group(1).strip()
        entity = await client.get_entity(arg)

        if not isinstance(entity, types.Channel) or not entity.broadcast:
            return await safe_respond(event, "╮ آیدی/یوزرنیم مربوط به کانال نیست!")

        if entity.id in settings.comment_channels:
            settings.comment_channels.discard(entity.id)
            await settings_manager.save_settings()
            await safe_respond(event, "╮ حذف شد.")
        else:
            await safe_respond(event, "╮ کانال در لیست وجود ندارد!")
    except Exception as e:
        print(f"Error removing comment channel: {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ کانال یافت نشد یا نامعتبر است!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^تنظیم کامنت$'))
async def set_comment_message(event):
    if not settings.self_enabled: return
    is_admin = hasattr(event, "_original")
    reply = await event.get_reply_message() if not is_admin else await event._original.get_reply_message()

    if not reply:
        return await safe_respond(event, "╮ استفاده نادرست از دستور! (باید به یک پیام ریپلای کنید)")

    if reply.media:
        return await safe_respond(event, "╮ فقط متن مجاز است!")

    if reply.text:
        settings.comment_content = reply.text
        await settings_manager.save_settings()
        await safe_respond(event, "╮ تنظیم شد.")
    else:
        await safe_respond(event, "╮ پیام خالی است!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^لیست کامنت$'))
async def list_comment_channels(event):
    if not settings.self_enabled: return
    if not settings.comment_channels:
        return await safe_respond(event, "╮ خالی!")

    result = "╮ لیست کانال‌های کامنت:\n\n"
    for cid in settings.comment_channels:
        try:
            entity = await client.get_entity(cid)
            title = entity.title or "Unknown Channel"
            result += f"> [{title}](https://t.me/c/{cid})\n"
        except Exception:
            result += f"> `{cid}` (کانال ناشناس)\n"
    
    await safe_respond(event, result, parse_mode='md')

@client.on(events.NewMessage(outgoing=True, pattern=r'^پاکسازی لیست کامنت$'))
async def clear_comment_channels(event):
    if not settings.self_enabled: return
    settings.comment_channels.clear()
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خالی شد.")

@client.on(events.NewMessage(incoming=True, forwards=True))
async def auto_comment_handler(event):
    if not settings.self_enabled: return
    fwd = event.forward
    if not fwd or not fwd.chat:
        return

    chan_id = fwd.chat.id
    if chan_id not in settings.comment_channels:
        return
    
    if not settings.comment_content:
        return # No comment content set

    try:
        await client.send_message(
            event.chat_id,
            message=settings.comment_content,
            reply_to=event.id
        )
    except Exception as e:
        print(f"Error sending auto-comment: {e}")
        traceback.print_exc()

@client.on(events.NewMessage(outgoing=True, pattern=r'^ربات$'))
async def random_self_message(event):
    if not settings.self_enabled: return
    responses = [
        "چته خیرُاللّه؟",
        "هنوز زنده‌ام.",
        "ما که مُردیم!"
    ]

    options = [r for r in responses if r != settings.last_self_text]
    if not options: # If all options have been used sequentially
        options = responses.copy()
        
    selected = random.choice(options)
    settings.last_self_text = selected
    await settings_manager.save_settings() # Save to persist last_self_text
    await safe_respond(event, selected)

@client.on(events.NewMessage(outgoing=True, pattern=r'^وضعیت ادمین\s*\{(.+?)\}$'))
async def change_admin_prefix(event):
    if not settings.self_enabled: return
    new_prefix = event.pattern_match.group(1)
    if not new_prefix:
        return await safe_respond(event, "╮ استفاده نادرست از دستور! (مثال: `وضعیت ادمین {+ }`)")

    settings.admin_prefix = new_prefix
    await settings_manager.save_settings()
    await safe_respond(event, "╮ تنظیم شد.")

# --- Typing/Action Modes ---
@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت چت پیوی روشن$'))
async def enable_typing_private(event):
    if not settings.self_enabled: return
    settings.typing_mode_private = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت چت پیوی خاموش$'))
async def disable_typing_private(event):
    if not settings.self_enabled: return
    settings.typing_mode_private = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت چت گروه روشن$'))
async def enable_typing_group(event):
    if not settings.self_enabled: return
    settings.typing_mode_group = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت چت گروه خاموش$'))
async def disable_typing_group(event):
    if not settings.self_enabled: return
    settings.typing_mode_group = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت بازی پیوی روشن$'))
async def enable_game_private(event):
    if not settings.self_enabled: return
    settings.game_mode_private = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت بازی پیوی خاموش$'))
async def disable_game_private(event):
    if not settings.self_enabled: return
    settings.game_mode_private = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت بازی گروه روشن$'))
async def enable_game_group(event):
    if not settings.self_enabled: return
    settings.game_mode_group = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت بازی گروه خاموش$'))
async def disable_game_group(event):
    if not settings.self_enabled: return
    settings.game_mode_group = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت ویس پیوی روشن$'))
async def enable_voice_private(event):
    if not settings.self_enabled: return
    settings.voice_mode_private = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت ویس پیوی خاموش$'))
async def disable_voice_private(event):
    if not settings.self_enabled: return
    settings.voice_mode_private = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت ویس گروه روشن$'))
async def enable_voice_group(event):
    if not settings.self_enabled: return
    settings.voice_mode_group = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت ویس گروه خاموش$'))
async def disable_voice_group(event):
    if not settings.self_enabled: return
    settings.voice_mode_group = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت ویدیو مسیج پیوی روشن$'))
async def enable_video_private(event):
    if not settings.self_enabled: return
    settings.video_mode_private = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت ویدیو مسیج پیوی خاموش$'))
async def disable_video_private(event):
    if not settings.self_enabled: return
    settings.video_mode_private = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت ویدیو مسیج گروه روشن$'))
async def enable_video_group(event):
    if not settings.self_enabled: return
    settings.video_mode_group = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حالت ویدیو مسیج گروه خاموش$'))
async def disable_video_group(event):
    if not settings.self_enabled: return
    settings.video_mode_group = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(incoming=True))
async def activity_simulator(event):
    if not settings.self_enabled: return
    chat_id = event.chat_id

    if chat_id == settings.the_gap:
        return

    is_private = event.is_private
    is_group = event.is_group or event.is_channel # Telethon treats megagroups as channels too, check both

    actions = []

    if (settings.typing_mode_private and is_private) or (settings.typing_mode_group and is_group):
        actions.append(SendMessageTypingAction())

    if (settings.game_mode_private and is_private) or (settings.game_mode_group and is_group):
        actions.append(SendMessageGamePlayAction())

    if (settings.voice_mode_private and is_private) or (settings.voice_mode_group and is_group):
        actions.append(SendMessageRecordAudioAction())

    if (settings.video_mode_private and is_private) or (settings.video_mode_group and is_group):
        actions.append(SendMessageRecordRoundAction())

    # Only perform action if there's at least one action set and it's not our own message
    if actions and event.sender_id != (await client.get_me()).id:
        try:
            # Randomly pick one action if multiple are enabled, or send all sequentially with delays
            action_to_send = random.choice(actions)
            await client(SetTypingRequest(peer=chat_id, action=action_to_send))
            await asyncio.sleep(random.uniform(2, 5)) # Simulate human-like delay
        except errors.FloodWaitError as e:
            print(f"Flood wait in activity simulator: {e}")
            await asyncio.sleep(e.seconds + 1)
        except Exception as e:
            print(f"Error in activity simulator: {e}")
            traceback.print_exc()

@client.on(events.NewMessage(outgoing=True, pattern=r'^ربات خاموش$'))
async def disable_bot(event):
    settings.self_enabled = False
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خاموش شد.")

@client.on(events.NewMessage(outgoing=True, pattern=r'^ربات روشن$'))
async def enable_bot(event):
    settings.self_enabled = True
    await settings_manager.save_settings()
    await safe_respond(event, "╮ روشن شد.")

# --- PV Mute Feature ---
@client.on(events.NewMessage(outgoing=True, pattern=r'^سکوت پیوی(?: (.+))?$'))
async def mute_pv_user(event):
    if not settings.self_enabled: return
    user_input = event.pattern_match.group(1)
    reply = await event.get_reply_message() if not hasattr(event, "_original") else await event._original.get_reply_message()
    user_id = None

    if reply:
        user_id = reply.sender_id
    elif user_input:
        user_id = await resolve_user_id(client, user_input)
    else:
        return await safe_respond(event, "╮ استفاده نادرست از دستور! (ریپلای، یوزرنیم یا آیدی)")

    if user_id:
        if user_id not in settings.pv_mute_list:
            settings.pv_mute_list.append(user_id)
            await settings_manager.save_settings()
            await safe_respond(event, "╮ تنظیم شد.")
        else:
            await safe_respond(event, "╮ وجود دارد!")
    else:
        await safe_respond(event, "╮ کاربر نامعتبر!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^حذف سکوت پیوی(?: (.+))?$'))
async def unmute_pv_user(event):
    if not settings.self_enabled: return
    user_input = event.pattern_match.group(1)
    reply = await event.get_reply_message() if not hasattr(event, "_original") else await event._original.get_reply_message()
    user_id = None

    if reply:
        user_id = reply.sender_id
    elif user_input:
        user_id = await resolve_user_id(client, user_input)
    else:
        return await safe_respond(event, "╮ استفاده نادرست از دستور! (ریپلای، یوزرنیم یا آیدی)")

    if user_id:
        if user_id in settings.pv_mute_list:
            settings.pv_mute_list.remove(user_id)
            await settings_manager.save_settings()
            await safe_respond(event, "╮ حذف شد.")
        else:
            await safe_respond(event, "╮ وجود ندارد!")
    else:
        await safe_respond(event, "╮ کاربر نامعتبر!")

@client.on(events.NewMessage(outgoing=True, pattern=r'^لیست سکوت پیوی$'))
async def list_muted_pv_users(event):
    if not settings.self_enabled: return
    if not settings.pv_mute_list:
        return await safe_respond(event, "╮ خالی!")

    text = "╮ لیست سکوت پیوی:\n\n"
    for uid in settings.pv_mute_list:
        try:
            user = await client.get_entity(uid)
            mention = f"[{get_display_name(user) or str(uid)}](tg://user?id={uid})"
        except Exception:
            mention = f"`{uid}` (کاربر ناشناس)"
        text += f"> {mention}\n"

    await safe_respond(event, text, parse_mode='md')

@client.on(events.NewMessage(outgoing=True, pattern=r'^پاکسازی لیست سکوت پیوی$'))
async def clear_muted_pv_users(event):
    if not settings.self_enabled: return
    settings.pv_mute_list.clear()
    await settings_manager.save_settings()
    await safe_respond(event, "╮ خالی شد.")

@client.on(events.NewMessage(incoming=True))
async def delete_muted_pv_messages(event):
    if not settings.self_enabled: return
    # If the message is private, from a muted user, and not from ourselves
    me = await client.get_me()
    if event.is_private and event.sender_id in settings.pv_mute_list and event.sender_id != me.id:
        try:
            await event.delete()
        except errors.MessageDeleteForbiddenError:
            # Cannot delete other user's message, but still mute by deleting our replies
            pass
        except Exception as e:
            print(f"Error deleting muted PV message: {e}")
            traceback.print_exc()

@client.on(events.NewMessage(outgoing=True, pattern=r'^pannel$'))
async def send_inline_panel(event):
    if not settings.self_enabled: return
    try:
        sender = await event.get_sender()
        bot_username = "AlfredsHelperBot" # Assuming this is a separate helper bot
        query_text = f"pannel:{sender.id}"
        results = await client.inline_query(bot_username, query_text)

        if results:
            # The original code's logic for admin vs. self event seems a bit off here for inline
            # For simplicity, if it's an outgoing command from the self-bot directly, delete it
            # and send the inline result. If it's an admin command (FakeEvent), reply to original.
            if hasattr(event, "_original") and event._original: # Admin command
                await results[0].click(event._original.chat_id, reply_to=event._original.id)
            else: # Self-bot command
                await event.delete()
                await results[0].click(event.chat_id)
        else:
            await safe_respond(event, "╮ خطا در دریافت پنل!")
    except Exception as e:
        print(f"[Panel Error] {e}")
        traceback.print_exc()
        await safe_respond(event, "╮ خطا در ارتباط با پنل!")

@client.on(events.NewMessage(incoming=True))
async def admin_command_router(event):
    if not settings.self_enabled: return # Master switch check
    sender = await event.get_sender()
    if sender.id not in settings.admin_list:
        return # Not an admin, ignore

    text = event.raw_text

    if not text.startswith(settings.admin_prefix):
        return # Not an admin command prefix

    command_text = text[len(settings.admin_prefix):].strip() # Get command after prefix

    # Create a FakeEvent to mimic an outgoing message event for handlers
    class FakeEvent:
        def __init__(self, original_event, raw_text, pattern_match):
            self.message = original_event.message
            self.client = original_event.client
            self.raw_text = raw_text # The matched command text, not the full message
            self.text = raw_text
            self.sender = original_event.sender
            self.chat_id = original_event.chat_id
            self.id = original_event.id # Original message ID
            self.pattern_match = pattern_match
            self._original = original_event # Reference to the actual event object

        async def edit(self, *args, **kwargs):
            # Admin commands don't edit the admin's message, they reply.
            return await self._original.reply(*args, **kwargs)

        async def reply(self, *args, **kwargs):
            return await self._original.reply(*args, **kwargs)

        async def get_reply_message(self):
            return await self._original.get_reply_message() # Get reply to original admin message

        async def get_sender(self):
            return await self._original.get_sender()

        @property
        def is_reply(self):
            return self._original.is_reply
        
        @property
        def out(self): # Indicate this is conceptually an "outgoing" command
            return True


    for pattern, handler_name in COMMAND_HANDLERS.items():
        match = re.match(pattern, command_text)
        if match:
            # Check for commands restricted to non-admins
            restricted_commands = ["update_handler", "reset_handler", "set_text_halat", "disable_text_halat"]
            if handler_name in restricted_commands:
                await event.reply("╮ ادمین مجاز به استفاده از این دستور نیست!")
                return

            handler = globals().get(handler_name)
            if handler:
                fake_event = FakeEvent(event, command_text, match)
                try:
                    await handler(fake_event)
                except Exception as e:
                    print(f"Error handling admin command '{command_text}': {e}")
                    traceback.print_exc()
                    await event.reply(f"╮ خطا در اجرای دستور `{command_text}`: {e}")
                return # Command handled

    # If no pattern matched
    # await event.reply("╮ دستور ادمین نامعتبر!") # Maybe too noisy, remove for silent failure

# --- Background Tasks ---
async def rotate_name_task():
    while True:
        if not settings.self_enabled:
            await asyncio.sleep(5)
            continue
        
        # Calculate time until next minute starts to align updates
        now_tehran = datetime.now(pytz.timezone('Asia/Tehran'))
        seconds_to_next_minute = 60 - now_tehran.second - now_tehran.microsecond / 1_000_000
        await asyncio.sleep(max(1, seconds_to_next_minute)) # Ensure at least 1 second wait

        if settings.rotate_enabled and settings.name_list:
            name_template = settings.name_list[settings.current_index]

            now_dt = datetime.now(pytz.timezone('Asia/Tehran'))
            time_str = now_dt.strftime("%I:%M") if settings.time_format_12h else now_dt.strftime("%H:%M")
            
            if settings.date_type == "jalali":
                current_date = jdatetime.datetime.now().strftime("%Y/%m/%d")
            else:
                current_date = now_dt.strftime("%Y/%m/%d")

            styled_time = stylize_text_with_font(time_str, settings.time_font)
            styled_date = stylize_text_with_font(current_date, settings.date_font)

            final_name = name_template.replace("[ساعت]", styled_time)
            final_name = final_name.replace("[تاریخ]", styled_date)

            try:
                await client(functions.account.UpdateProfileRequest(first_name=final_name))
            except Exception as e:
                print(f"[rotate_name_task error] {e}")
                traceback.print_exc()

            settings.current_index = (settings.current_index + 1) % len(settings.name_list)
            settings_manager.schedule_save() # Save current_index

async def rotate_family_task():
    while True:
        if not settings.self_enabled:
            await asyncio.sleep(5)
            continue
        
        now_tehran = datetime.now(pytz.timezone('Asia/Tehran'))
        seconds_to_next_minute = 60 - now_tehran.second - now_tehran.microsecond / 1_000_000
        await asyncio.sleep(max(1, seconds_to_next_minute))

        if settings.rotate_family_enabled and settings.family_list:
            fam_template = settings.family_list[settings.current_family_index]

            now_dt = datetime.now(pytz.timezone('Asia/Tehran'))
            time_str = now_dt.strftime("%I:%M") if settings.time_format_12h else now_dt.strftime("%H:%M")
            
            if settings.date_type == "jalali":
                current_date = jdatetime.datetime.now().strftime("%Y/%m/%d")
            else:
                current_date = now_dt.strftime("%Y/%m/%d")

            styled_time = stylize_text_with_font(time_str, settings.time_font_family)
            styled_date = stylize_text_with_font(current_date, settings.date_font_family)

            final_fam = fam_template.replace("[ساعت]", styled_time)
            final_fam = final_fam.replace("[تاریخ]", styled_date)

            try:
                await client(functions.account.UpdateProfileRequest(last_name=final_fam))
            except Exception as e:
                print(f"[rotate_family_task error] {e}")
                traceback.print_exc()

            settings.current_family_index = (settings.current_family_index + 1) % len(settings.family_list)
            settings_manager.schedule_save()

async def rotate_bio_task():
    while True:
        if not settings.self_enabled:
            await asyncio.sleep(5)
            continue

        now_tehran = datetime.now(pytz.timezone('Asia/Tehran'))
        seconds_to_next_minute = 60 - now_tehran.second - now_tehran.microsecond / 1_000_000
        await asyncio.sleep(max(1, seconds_to_next_minute))

        if settings.rotate_bio_enabled and settings.bio_list:
            bio_template = settings.bio_list[settings.current_bio_index]

            now_dt = datetime.now(pytz.timezone('Asia/Tehran'))
            time_str = now_dt.strftime("%I:%M") if settings.time_format_12h else now_dt.strftime("%H:%M")
            
            if settings.date_type == "jalali":
                current_date = jdatetime.datetime.now().strftime("%Y/%m/%d")
            else:
                current_date = now_dt.strftime("%Y/%m/%d")

            styled_time = stylize_text_with_font(time_str, settings.time_font_bio)
            styled_date = stylize_text_with_font(current_date, settings.date_font_bio)

            final_bio = bio_template.replace("[ساعت]", styled_time)
            final_bio = final_bio.replace("[تاریخ]", styled_date)

            try:
                await client(functions.account.UpdateProfileRequest(about=final_bio))
            except Exception as e:
                print(f"[rotate_bio_task error] {e}")
                traceback.print_exc()

            settings.current_bio_index = (settings.current_bio_index + 1) % len(settings.bio_list)
            settings_manager.schedule_save()

async def keep_online_task():
    while True:
        if not settings.self_enabled:
            await asyncio.sleep(5)
            continue
        if settings.stay_online:
            try:
                # UpdateStatusRequest with offline=False makes user always online
                await client(functions.account.UpdateStatusRequest(offline=False))
            except Exception as e:
                print(f"[keep_online_task error] {e}")
                traceback.print_exc()
        await asyncio.sleep(60) # Run every minute

async def rotate_profile_photo_task():
    while True:
        if not settings.self_enabled:
            await asyncio.sleep(settings.profile_interval_minutes * 60) # Wait full interval if disabled
            continue
        
        # Calculate time until next rotation
        now = datetime.now(pytz.timezone('Asia/Tehran'))
        next_interval_time = now + timedelta(minutes=settings.profile_interval_minutes)
        wait_seconds = (next_interval_time - now).total_seconds()
        
        await asyncio.sleep(max(1, wait_seconds)) # Ensure at least 1 second wait

        if not settings.profile_enabled or not settings.profile_channel_id:
            continue

        try:
            # Fetch up to 100 messages from the profile channel
            # This ensures we have a pool of photos to pick from.
            photos_messages = await client.get_messages(settings.profile_channel_id, limit=100)
            
            # Filter for messages that actually contain a photo
            available_photos = [p for p in photos_messages if p.photo]

            # Filter out photos that have been used recently
            eligible_photos = [p for p in available_photos if p.id not in settings.used_profile_photo_ids]

            if not eligible_photos:
                # If all eligible photos have been used, reset the used list
                settings.used_profile_photo_ids.clear()
                settings_manager.schedule_save()
                eligible_photos = available_photos # Use all available photos again

            if not eligible_photos:
                print(f"No photos found in channel {settings.profile_channel_id} for profile rotation.")
                continue

            selected_photo_message = random.choice(eligible_photos)
            
            # Download the photo to a temporary file
            temp_photo_path = await client.download_media(selected_photo_message.photo, file=DOWNLOAD_FOLDER)

            if not temp_photo_path or not os.path.exists(temp_photo_path):
                print(f"Failed to download photo {selected_photo_message.id}.")
                continue

            # Upload and set as profile photo
            await client(UploadProfilePhotoRequest(
                file=await client.upload_file(temp_photo_path)
            ))

            # Add to used list and manage its size
            settings.used_profile_photo_ids.append(selected_photo_message.id)
            if len(settings.used_profile_photo_ids) > 500: # Keep list manageable
                settings.used_profile_photo_ids = settings.used_profile_photo_ids[-500:]
            settings_manager.schedule_save()

            # Delete old profile photos if count exceeds max_count
            profile_photos = await client.get_profile_photos('me')
            if len(profile_photos) > settings.profile_max_count:
                # Delete oldest photos until max_count is reached
                photos_to_delete = profile_photos[settings.profile_max_count:]
                await client(DeletePhotosRequest(id=[p.id for p in photos_to_delete]))

            os.remove(temp_photo_path) # Clean up temp file

        except Exception as e:
            print(f"[rotate_profile_photo_task error] {e}")
            traceback.print_exc()

async def check_membership_and_pin_chat():
    # Only run this task once at startup as it's not a frequently changing state.
    # Or, if you intend it to re-check, ensure it runs less frequently.
    # Original sleep was 21600 (6 hours)
    while True:
        try:
            me = await client.get_me()
            channels_to_check = ["golden_market7", "tamaynonee"] # These seem like control/system channels

            for username in channels_to_check:
                is_member = False
                try:
                    await client(GetParticipantRequest(username, me.id))
                    is_member = True
                except errors.UserNotParticipantError:
                    is_member = False
                except Exception as e:
                    print(f"Error checking membership in {username}: {e}")

                if not is_member:
                    try:
                        await client(JoinChannelRequest(username))
                        print(f"Joined {username} successfully.")
                    except errors.ChannelPrivateError:
                        print(f"Could not join {username}: It's private or not accessible.")
                    except errors.UserBannedInChannelError:
                        print(f"Banned from {username}. Shutting down self-bot.")
                        try:
                            await client.send_message("me", "به دلیل بن شدن از کانال سیستمی، سلف شما خاموش می‌شود!")
                        except:
                            pass
                        os._exit(0)
                    except Exception as join_err:
                        print(f"Error joining {username}: {join_err}")
                        traceback.print_exc()
            
            # Pinning 'AlfredSelf' chat
            try:
                # Resolve the entity first, then toggle pin
                alfred_self_entity = await client.get_entity("AlfredSelf")
                await client(ToggleDialogPinRequest(
                    peer=alfred_self_entity,
                    pinned=True
                ))
            except errors.DialogNotFoundError:
                print("AlfredSelf dialog not found, cannot pin.")
            except Exception as pin_err:
                print(f"Error pinning AlfredSelf chat: {pin_err}")
                traceback.print_exc()

        except Exception as global_err:
            print(f"Global error in check_membership_and_pin_chat: {global_err}")
            traceback.print_exc()

        await asyncio.sleep(21600) # Check every 6 hours

async def main():
    print("Starting bot...")
    await settings_manager.load_settings() # Load settings at startup
    settings_manager.set_client(client) # Pass client to settings manager for potential future use

    # If anti-login is enabled and the bot was enabled, it might mean a forceful shutdown
    # This logic depends heavily on how "anti-login" is supposed to detect it.
    # The current `anti_login_detector` listens for `UserUpdate` and exits.
    # This might need refinement based on actual Telegram client behavior for new logins.

    # Initial expiration check and message
    expire_str = "Uncertain!"
    EXPIRE_DAYS = 30
    if os.path.exists(EXPIRE_FILE):
        try:
            with open(EXPIRE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                start_str = data.get("start")
                tehran = pytz.timezone("Asia/Tehran")
                start_dt = datetime.strptime(start_str, "%Y/%m/%d %H:%M")
                start_dt = tehran.localize(start_dt)

                expire_dt = start_dt + timedelta(days=EXPIRE_DAYS)
                now_dt = datetime.now(tehran)
                remaining = expire_dt - now_dt

                if remaining.total_seconds() < 0:
                    expire_str = "Expired!"
                else:
                    days = remaining.days
                    hours = remaining.seconds // 3600
                    minutes = (remaining.seconds % 3600) // 60
                    expire_str = f"{days} Days, {hours:02d}:{minutes:02d}"
        except Exception as e:
            print(f"Error reading expire.json: {e}")
            expire_str = "Error!"
    else:
        # If expire.json doesn't exist, create it and set start time
        now_dt_tehran = datetime.now(pytz.timezone('Asia/Tehran'))
        start_expire_str = now_dt_tehran.strftime("%Y/%m/%d %H:%M")
        with open(EXPIRE_FILE, "w") as f:
            json.dump({"start": start_expire_str}, f)
        expire_str = "Initialized!" # New file created

    print("Bot Activated!")
    try:
        await client.send_message("me", f'''
Self is Activated!
```Informatation:
Expire: {expire_str}
Version: 2.1 (Enhanced)
By: @AnishtayiN```
'''
        )
    except Exception as e:
        print(f"Failed to send activation message to 'me': {e}")
        traceback.print_exc()

    # Start all background tasks
    client.loop.create_task(rotate_name_task())
    client.loop.create_task(rotate_family_task())
    client.loop.create_task(rotate_bio_task())
    client.loop.create_task(keep_online_task())
    client.loop.create_task(rotate_profile_photo_task())
    client.loop.create_task(check_membership_and_pin_chat())
    
    # Ensure settings are saved on graceful shutdown
    client.add_event_handler(lambda _: settings_manager.save_settings(), events.Raw(types.UpdateConnection)) # Not perfect, but a heuristic

    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        # Create downloads directory if it doesn't exist
        os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
        # Run the client
        with client:
            client.loop.run_until_complete(main())
    except Exception as e:
        print(f"Critical error during bot startup or runtime: {e}")
        traceback.print_exc()
    finally:
        if conn:
            conn.close() # Ensure database connection is closed on exit
