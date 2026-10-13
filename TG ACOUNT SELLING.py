import os
import sqlite3
import re
import asyncio
import time
import logging
import csv
import zipfile
import shutil
import html
import imaplib
import email
import urllib.request
import json
import ssl
import hashlib
from datetime import datetime
from urllib.parse import quote, urlencode

from telethon import TelegramClient, events, Button

# ================= GLOBAL BUTTON FONT =================
# Keep callback data/URLs untouched while rendering every Telegram button
# label in Mathematical Sans-Serif Bold (𝗧𝗚 𝗔𝗖𝗖 style). Only ASCII
# letters are converted, so numbers, symbols, existing Unicode/fancy text,
# callback payloads and URLs remain unchanged.
_ORIGINAL_BUTTON = Button

de _button_font(text):
    text = str(text)
    out = []
    for ch in text:
        o = ord(ch)
        if 65 <= o <= 90:          # A-Z
            out.append(chr(0x1D5D4 + (o - 65)))
        elif 97 <= o <= 122:      # a-z
            out.append(chr(0x1D5EE + (o - 97)))
        else:
            out.append(ch)
    return ''.join(out)

class _StyledButtonProxy:
    @staticmethod
    def inline(text, data=None, **kwargs):
        return _ORIGINAL_BUTTON.inline(_button_font(text), data=data, **kwargs)

    @staticmethod
    def url(text, url, **kwargs):
        return _ORIGINAL_BUTTON.url(_button_font(text), url, **kwargs)

Button = _StyledButtonProxy
from telethon.errors import (
  SessionPasswordNeededError, 
  MessageNotModifiedError,
  UserNotParticipantError,
  ChatAdminRequiredError
)
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.functions.messages import ExportChatInviteRequest
from telethon.tl.types import ChannelParticipantAdmin, ChannelParticipantCreator
from telethon.tl.functions.account import GetPasswordRequest

# ================= CONFIGURATION =================
API_ID = 39776296 
API_HASH = "39750d30671418c6fd01a96b6296ee82"
BOT_TOKEN = "8997315834:AAFFBJqj2dkj6ODf6EVBblh4vIaNYmicH24" 
ADMIN_ID = 8781077406 

# ================= TELEGRAM CUSTOM EMOJI CONSTANTS (UPDATED) =================
P_YES = ''
P_NO = ''
P_PKG = ''
P_MONEY = ''
P_USDT = ''
P_INR = '₹'
P_TG = ''
P_GIFT = ''
P_STATS = ''
P_CARD = ''
P_USERS = ''
P_CAL = ''
P_PC = ''
P_EYE = ''
P_CW = ''
P_ON = ''
P_OFF = ''
P_ID = ''
P_KEY = ''
P_GLOBE = ''
P_CART = ''
P_STORE = ''
P_OTP = ''
P_2FA = ''
P_FLAG = ''
P_PHONE = ''
P_WAIT = ''
P_TIME = ''
P_WARN = ''
P_DOC = ''
P_ASST = ''
P_ACC = ''
P_FIRE = ''
P_STAR = ''
P_DIAMOND = ''
P_BELL = ''
P_CROWN = ''
P_LIGHTNING = ''
P_ROCKET = ''
P_PARTY = ''
P_FOLDER = ''
P_GEAR = ''
P_PIN = ''
P_SEARCH = ''
P_LINK = ''
P_TITLE = ''
P_DESC = ''
P_RATE = ''
P_MIN = ''
P_MAX = ''
P_QTY = ''


def custom_emoji_text(text):
  """Return message text with all emoji/custom-emoji markup removed."""
  if text is None:
    return text
  text = str(text)
  text = re.sub(r'<emoji\s+id=["\'][^"\']+["\']>(.*?)</emoji>', r'\1', text, flags=re.DOTALL | re.IGNORECASE)
  # Remove emoji/pictograph/symbol ranges while retaining ordinary text and currency symbols.
  text = re.sub(r'[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]', '', text)
  return text


logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

os.makedirs("sessions", exist_ok=True)

session_name = f"bot_session_{BOT_TOKEN.split(':')[0]}"
bot = TelegramClient(session_name, API_ID, API_HASH)
bot.parse_mode = 'html'

db = sqlite3.connect("otp_bot_final.db", check_same_thread=False, timeout=20)
db.execute("PRAGMA journal_mode=WAL;")
cur = db.cursor()

active_orders = {}   
waiting_proof = {}   
deposit_input = {} 
admin_dep_state = {}  
user_spam_cooldown = {} 
session_buy_state = {}   
smm_order_state = {}
refill_state = {}
redeem_state = {}
digital_shop_state = {}

# Telegram callback_data is limited to 64 UTF-8 bytes. Country/account names
# can contain fancy Unicode characters which make callback_data exceed that
# limit. Always use a short stable token in buttons and resolve it back to the
# real database value when clicked. This keeps display names fully Unicode-safe.
def _country_token(country):
  return hashlib.sha256(str(country).encode("utf-8")).hexdigest()[:10]

def _resolve_country_ref(ref):
  ref = str(ref or "")
  # New compact token format.
  if re.fullmatch(r"[0-9a-f]{10}", ref):
    rows = cur.execute("SELECT DISTINCT country_name FROM stock").fetchall()
    for (name,) in rows:
      if _country_token(name) == ref:
        return name
  # Backward compatibility for old buttons which stored the literal name.
  return ref

user_locks = {}

def get_user_lock(uid):
  if uid not in user_locks:
    user_locks[uid] = asyncio.Lock()
  return user_locks[uid]

def setup_db():
  cur.executescript("""
  CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    total_deposited INTEGER DEFAULT 0,
    joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    banned INTEGER DEFAULT 0,
    discount INTEGER DEFAULT 0,
    terms_accepted INTEGER DEFAULT 1
  );
  CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
  CREATE TABLE IF NOT EXISTS stock (
    phone TEXT PRIMARY KEY,
    session_file TEXT,
    country_name TEXT,
    country_icon TEXT DEFAULT '',
    account_year INTEGER,
    category TEXT DEFAULT 'Good',
    price INTEGER,
    available INTEGER DEFAULT 1,
    twofa TEXT DEFAULT 'None',
    added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );
  CREATE TABLE IF NOT EXISTS auto_prices (
    country TEXT,
    year TEXT,
    price INTEGER,
    PRIMARY KEY (country, year)
  );
  CREATE TABLE IF NOT EXISTS deposits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    method_name TEXT,
    status TEXT, 
    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );
  CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    country TEXT,
    year INTEGER,
    price INTEGER,
    phone TEXT,
    otp TEXT,
    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );
  CREATE TABLE IF NOT EXISTS smm_orders (
    bot_order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    service_id INTEGER,
    link TEXT,
    quantity INTEGER,
    total_price REAL,
    smm_order_id TEXT,
    status TEXT DEFAULT 'Completed',
    date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
  );
  CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY,
    p_add_stock INTEGER DEFAULT 1,
    p_manage_stock INTEGER DEFAULT 1,
    p_stats INTEGER DEFAULT 1,
    p_bal INTEGER DEFAULT 1,
    p_settings INTEGER DEFAULT 1
  );
  CREATE TABLE IF NOT EXISTS custom_countries (
    code TEXT PRIMARY KEY,
    name TEXT,
    flag TEXT DEFAULT ''
  );
  CREATE TABLE IF NOT EXISTS force_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT,
    invite_url TEXT,
    title TEXT
  );
  CREATE TABLE IF NOT EXISTS smm_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT
  );
  CREATE TABLE IF NOT EXISTS smm_services (
    service_id INTEGER PRIMARY KEY,
    category_id INTEGER,
    name TEXT,
    rate REAL,
    min INTEGER,
    max INTEGER,
    description TEXT
  );
  CREATE TABLE IF NOT EXISTS redeem_codes (
    code TEXT PRIMARY KEY,
    amount INTEGER NOT NULL,
    max_users INTEGER NOT NULL DEFAULT 1,
    used_count INTEGER NOT NULL DEFAULT 0,
    created_by INTEGER,
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active INTEGER DEFAULT 1
  );
  CREATE TABLE IF NOT EXISTS redeem_claims (
    code TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    claimed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (code, user_id)
  );
  CREATE TABLE IF NOT EXISTS digital_products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    price INTEGER NOT NULL,
    photo_file_id TEXT DEFAULT '',
    photo_path TEXT DEFAULT '',
    file_path TEXT DEFAULT '',
    created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    active INTEGER DEFAULT 1
  );
  """)
  
  # Digital Shop migration: optional preview image + separate required delivery file.
  try:
    cur.execute("ALTER TABLE digital_products ADD COLUMN file_path TEXT DEFAULT ''")
  except sqlite3.OperationalError:
    pass

  # Migration for payment UTR tracking / duplicate protection.
  try:
    cur.execute("ALTER TABLE deposits ADD COLUMN utr TEXT DEFAULT ''")
  except sqlite3.OperationalError:
    pass
  try:
    cur.execute("CREATE INDEX IF NOT EXISTS idx_deposits_utr ON deposits(utr)")
  except Exception:
    pass

  cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('imap_server', 'imap.gmail.com')")
  cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('imap_email', 'aroy327154@gmail.com')")
  cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('imap_password', 'foor ircl isyr jcva')")
  cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('fampay_upi', 'fampay@upi')")
  cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('fampay_name', 'AccStore')")
  cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('manual_upi', 'manual@upi')")
  cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('manual_name', 'AccStore Manual')")
  cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('fampay_enabled', 'on')")
  cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('manual_enabled', 'on')")
  cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('log_channel_id', '-1003940330621')")
  cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('support_url', 'https://t.me/XLARYAN_0100')")
  cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('support_channel_url', 'https://t.me/FREEARUAN')")
  cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('smm_api_url', '')")
  cur.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('smm_api_key', '')")
  db.commit()

setup_db()

# Requested default Support/Updates destinations. Only migrate the old
# built-in defaults; a custom URL previously configured by the admin is kept.
def ensure_requested_default_links():
  defaults = {
    'support_url': 'https://t.me/XLARYAN_0100',
    'support_channel_url': 'https://t.me/FREEARUAN',
  }
  old_defaults = {
    'support_url': {'', 'https://t.me/m/XLARYAN_0100'},
    'support_channel_url': {'', 'https://t.me/', 'https://t.me/FREEARUAN'},
  }
  for key, default in defaults.items():
    row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    current = (row[0] or '').strip() if row else ''
    valid = current.startswith(('http://', 'https://', 'tg://')) and len(current) > len('https://t.me/')
    if current in old_defaults[key] or not valid:
      cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, default))
  db.commit()

ensure_requested_default_links()

# Migrate the previously embedded Gmail App Password to the credentials supplied
# for this bot. Existing custom IMAP credentials are preserved.try:

  _imap_user = cur.execute("SELECT value FROM settings WHERE key='imap_email'").fetchone()
  _imap_pwd = cur.execute("SELECT value FROM settings WHERE key='imap_password'").fetchone()
  if ((_imap_user and (_imap_user[0] or '').strip() == 'aroy327154@gmail.com') and
      (_imap_pwd and re.sub(r"\s+", "", (_imap_pwd[0] or '').strip()) == 'yascqrsoaunp dnbc'.replace(' ', ''))):
    cur.execute("UPDATE settings SET value=? WHERE key='imap_password'", ('foor ircl isyr jcva',))
    db.commit()
except Exception:
  pass

def is_bot_online():
  res = cur.execute("SELECT value FROM settings WHERE key='bot_status'").fetchone()
  return res[0] == 'on' if res else True

def is_admin(uid):
  if uid == ADMIN_ID: return True
  row = cur.execute("SELECT user_id FROM admins WHERE user_id=?", (uid,)).fetchone()
  return bool(row)

def has_perm(uid, perm):
  if uid == ADMIN_ID: return True
  row = cur.execute(f"SELECT {perm} FROM admins WHERE user_id=?", (uid,)).fetchone()
  return bool(row and row[0] == 1)

def get_all_admin_ids():
  """Return the owner plus every admin configured in the admins table, without duplicates."""
  ids = [ADMIN_ID]
  try:
    rows = cur.execute("SELECT user_id FROM admins").fetchall()
    ids.extend(int(row[0]) for row in rows if row and row[0])
  except Exception as ex:
    logger.error(f"Failed to load admin IDs: {ex}")
  return list(dict.fromkeys(ids))

async def send_admins_file(photo, caption, buttons=None):
  """Forward a photo to the owner and all configured admins."""
  sent = 0
  for admin_id in get_all_admin_ids():
    try:
      await bot.send_file(admin_id, photo, caption=custom_emoji_text(caption), buttons=buttons)
      sent += 1
    except Exception as ex:
      logger.error(f"Failed to send admin review to {admin_id}: {ex}")
  return sent

def ensure_user(uid):
  cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (uid,))
  db.commit()

def get_usdt_rate():
  res = cur.execute("SELECT value FROM settings WHERE key='usdt_rate'").fetchone()
  try: return float(res[0]) if res else 94.0
  except: return 94.0

def _normalize_tg_url(raw_url, fallback=""):
  """Normalize a Telegram username/link without ever returning an invalid t.me root URL."""
  url = str(raw_url or "").strip()
  if not url:
    return fallback
  if url.startswith("@"): 
    url = "https://t.me/" + url[1:]
  elif not url.startswith(("http://", "https://")):
    url = "https://t.me/" + url.lstrip("/")
  # Telegram rejects bare https://t.me/ as a Button.url destination.
  if re.fullmatch(r"https?://t\.me/?", url, flags=re.IGNORECASE):
    return fallback
  # Basic URL sanity check; keep normal t.me invite links and usernames.
  if not re.match(r"^https?://(?:t\.me|telegram\.me)/[^\s<>]+$", url, flags=re.IGNORECASE):
    return fallback
  return url

def _safe_url_button(label, raw_url, style="primary"):
  """Build a Telegram URL button only when the URL is valid. Never let a bad admin/config URL crash a whole message."""
  url = _normalize_tg_url(raw_url, "")
  if not url:
    return None
  try:
    return Button.url(str(label)[:64], url, style=style)
  except Exception as ex:
    logger.error(f"Invalid URL button skipped: {ex}")
    return None

def get_support_url():
  # Admin Panel -> Support URL is the single source of truth for Support.
  res = cur.execute("SELECT value FROM settings WHERE key='support_url'").fetchone()
  return _normalize_tg_url(res[0] if res and res[0] else "", "")

def get_support_channel_url():
  # Admin Panel -> Support/Updates Channel is used for the Updates button.
  res = cur.execute("SELECT value FROM settings WHERE key='support_channel_url'").fetchone()
  return _normalize_tg_url(res[0] if res and res[0] else "", "")

def _has_valid_button_url(url):
  return bool(_normalize_tg_url(url, ""))

def get_fampay_upi():
  res = cur.execute("SELECT value FROM settings WHERE key='fampay_upi'").fetchone()
  return res[0] if res and res[0] else "fampay@upi"

def get_fampay_name():
  res = cur.execute("SELECT value FROM settings WHERE key='fampay_name'").fetchone()
  return res[0] if res and res[0] else "AccStore"


def get_setting(key, default=''):
  row = cur.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
  return row[0] if row and row[0] is not None else default

def set_setting(key, value):
  cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
  db.commit()

def get_manual_upi(): return get_setting('manual_upi', 'manual@upi')
def get_manual_name(): return get_setting('manual_name', 'AccStore Manual')
def payment_enabled(key): return get_setting(key, 'on').lower() == 'on'

def get_log_channel_id():
  res = cur.execute("SELECT value FROM settings WHERE key='log_channel_id'").fetchone()
  try: return int(res[0]) if res and res[0] else -1003940330621
  except: return -1003940330621

def clean_html_url(raw_url):
  if not raw_url: return ""
  clean = re.sub(r'<.*?>', '', raw_url)
  match = re.search(r'https?://[^\s<>"]+', clean)
  if match:
    return match.group(0).strip()
  return clean.strip()

def get_smm_api_config():
  url = cur.execute("SELECT value FROM settings WHERE key='smm_api_url'").fetchone()
  key = cur.execute("SELECT value FROM settings WHERE key='smm_api_key'").fetchone()
  raw_url = url[0].strip() if url and url[0] else ""
  return (clean_html_url(raw_url), key[0].strip() if key and key[0] else "")

def get_ssl_context():
  ctx = ssl.create_default_context()
  ctx.check_hostname = False
  ctx.verify_mode = ssl.CERT_NONE
  return ctx

def fetch_smm_services_from_api(api_url, api_key):
  api_url = clean_html_url(api_url)
  headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.5',
    'Connection': 'keep-alive'
  }
  try:
    data = urllib.parse.urlencode({'key': api_key, 'action': 'services'}).encode('utf-8')
    req = urllib.request.Request(api_url, data=data, method='POST', headers=headers)
    ctx = get_ssl_context()
    with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
      res_text = response.read().decode('utf-8', errors='ignore')
      return json.loads(res_text)
  except Exception as e:
    logger.error(f"SMM API POST Fetch Error: {e}")
    try:
      get_url = f"{api_url.rstrip('/')}?key={api_key}&action=services"
      req = urllib.request.Request(get_url, headers=headers)
      ctx = get_ssl_context()
      with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
        res_text = response.read().decode('utf-8', errors='ignore')
        return json.loads(res_text)
    except Exception as e2:
      logger.error(f"SMM API GET Fetch Error: {e2}")
      return None

def place_smm_order_api(api_url, api_key, service_id, link, quantity):
  api_url = clean_html_url(api_url)
  headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Accept-Language': 'en-US,en;q=0.9',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    'Origin': api_url.split('/api')[0] if '/api' in api_url else api_url,
    'Referer': api_url,
    'X-Requested-With': 'XMLHttpRequest'
  }
  try:
    data = urllib.parse.urlencode({
      'key': api_key,
      'action': 'add',
      'service': service_id,
      'link': link,
      'quantity': quantity
    }).encode('utf-8')
    
    req = urllib.request.Request(api_url, data=data, headers=headers, method='POST')
    ctx = get_ssl_context()
    with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
      res_text = response.read().decode('utf-8', errors='ignore')
      
      if "<html" in res_text.lower() or "cloudflare" in res_text.lower():
        logger.error("Cloudflare blocked the SMM API order request.")
        return {"error": "Cloudflare security block! Please whitelist server IP in panel admin."}
        
      return json.loads(res_text)
  except Exception as e:
    logger.error(f"SMM Order API Error: {e}")
    return {"error": f"API Connection Error: {str(e)}"}

def refill_smm_order_api(api_url, api_key, smm_order_id):
  api_url = clean_html_url(api_url)
  headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'application/json, text/javascript, */*; q=0.01',
    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
  }
  try:
    data = urllib.parse.urlencode({
      'key': api_key,
      'action': 'refill',
      'order': smm_order_id
    }).encode('utf-8')
    req = urllib.request.Request(api_url, data=data, headers=headers, method='POST')
    ctx = get_ssl_context()
    with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
      res_text = response.read().decode('utf-8', errors='ignore')
      return json.loads(res_text)
  except Exception as e:
    logger.error(f"SMM Refill API Error: {e}")
    return {"error": str(e)}

async def safe_callback_answer(event, message=None, alert=False):
  """Safely acknowledge callback queries without swallowing later error messages."""
  try:
    already_answered = getattr(event, "_accstore_callback_answered", False)
    if already_answered:
      if message:
        try:
          await event.respond(str(message))
        except Exception:
          pass
      return
    setattr(event, "_accstore_callback_answered", True)
    await event.answer(message, alert=alert)
  except Exception:
    if message:
      try:
        await event.respond(str(message))
      except Exception:
        pass

async def check_payment_in_gmail_async(utr_to_find, gmail_user, gmail_pass, expected_amount=None):
  """Verify a payment notification from Gmail IMAP.

  Matching rules:
  1. Normalize the submitted UTR and search Gmail INBOX and All Mail.
  2. Decode plain text and HTML MIME parts.
  3. Require the normalized UTR to be present in the actual message content.
  4. Extract monetary values from the local UTR context first; only then use
    transaction/payment-labelled values from the full message.
  5. Return an amount only when it meets the requested deposit amount.
  """
  def clean_text(value):
    if value is None:
      return ""
    if isinstance(value, (bytes, bytearray)):
      value = value.decode('utf-8', errors='ignore')
    value = html.unescape(str(value))
    value = re.sub(r'<br\s*/?>', '\n', value, flags=re.I)
    value = re.sub(r'</(?:p|div|li|tr|h[1-6])>', '\n', value, flags=re.I)
    value = re.sub(r'<[^>]+>', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()

  def norm_ref(value):
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())

  def extract_amounts(text):
    text = clean_text(text).upper()
    patterns = [
      r'(?:₹|RS\.?|INR)\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)',
      r'(?:AMOUNT\s*(?:PAID|RECEIVED|SENT|CREDITED)?|PAID|RECEIVED|CREDITED|TRANSACTION\s+AMOUNT|TRANSFERRED)\s*[:=-]?\s*(?:₹|RS\.?|INR)?\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)',
    ]
    vals=[]
    for pat in patterns:
      for m in re.findall(pat, text, flags=re.I):
        try:
          v=float(str(m).replace(',',''))
          if v > 0 and v < 100000000:
            vals.append(v)
        except Exception:
          pass
    return list(dict.fromkeys(vals))

  def decode_part(part):
    try:
      payload=part.get_payload(decode=True)
      if payload is None:
        payload=part.get_payload()
      charset=part.get_content_charset() or 'utf-8'
      return payload.decode(charset, errors='ignore') if isinstance(payload,(bytes,bytearray)) else str(payload or '')
    except Exception:
      return str(part.get_payload() or '')

  def message_text(msg):
    pieces=[str(msg.get('Subject') or ''), str(msg.get('From') or ''), str(msg.get('To') or '')]
    if msg.is_multipart():
      for part in msg.walk():
        if part.get_content_maintype() == 'multipart':
          continue
        if (part.get_content_type() or '').lower() in ('text/plain','text/html'):
          pieces.append(decode_part(part))
    else:
      pieces.append(decode_part(msg))
    return clean_text('\n'.join(pieces))

  def fetch_sync():
    mail=None
    try:
      user=(gmail_user or '').strip()
      password=re.sub(r'\s+', '', (gmail_pass or '').strip())
      if not user or not password:
        logger.error('Payment verification: Gmail credentials are missing.')
        return None
      server_row=cur.execute("SELECT value FROM settings WHERE key='imap_server'").fetchone()
      server=(server_row[0].strip() if server_row and server_row[0] else 'imap.gmail.com')
      if not re.fullmatch(r'[A-Za-z0-9._-]+', server):
        server='imap.gmail.com'
      utr_norm=norm_ref(utr_to_find)
      if len(utr_norm) < 6:
        return None
      expected=float(expected_amount) if expected_amount is not None else None

      mail=imaplib.IMAP4_SSL(server,993)
      mail.login(user,password)
      folders=['INBOX','[Gmail]/All Mail']
      candidates=[]
      seen=set()

      # First pass: server-side UTR searches, both raw and compact forms.
      for folder in folders:
        try:
          st,_=mail.select(folder,readonly=True)
          if st!='OK': continue
          raw=str(utr_to_find).replace('"','').strip()
          terms=[raw, re.sub(r'[\s-]+','',raw)]
          for term in dict.fromkeys(x for x in terms if x):
            st,data=mail.search(None,'TEXT',f'"{term}"')
            if st=='OK' and data and data[0]:
              for mid in data[0].split()[-100:]:
                key=(folder,mid)
                if key not in seen:
                  seen.add(key); candidates.append(key)
        except Exception as ex:
          logger.warning('IMAP search failed for %s: %s',folder,ex)

      # Second pass: newest messages, because some Gmail payment mails do not
      # expose the UTR to the IMAP SEARCH index immediately.
      if not candidates:
        for folder in folders:
          try:
            st,_=mail.select(folder,readonly=True)
            if st!='OK': continue
            st,data=mail.search(None,'ALL')
            if st=='OK' and data and data[0]:
              for mid in data[0].split()[-750:]:
                key=(folder,mid)
                if key not in seen:
                  seen.add(key); candidates.append(key)
          except Exception:
            pass

      # Newest first.
      candidates=list(reversed(candidates))[:1000]
      logger.info('Payment verification: checking %d Gmail candidates for UTR %s',len(candidates),utr_to_find)

      for folder,mid in candidates:
        try:
          st,_=mail.select(folder,readonly=True)
          if st!='OK': continue
          st,data=mail.fetch(mid,'(RFC822)')
          if st!='OK': continue
          rawparts=[x[1] for x in data if isinstance(x,tuple) and len(x)>1]
          if not rawparts: continue
          msg=email.message_from_bytes(b''.join(rawparts))
          body=message_text(msg)
          if utr_norm not in norm_ref(body):
            continue

          # Work around formatting differences by using a normalized copy,
          # but retain a generous local context around the UTR.
          nb=norm_ref(body)
          pos=nb.find(utr_norm)
          local=body
          if pos>=0:
            local=nb[max(0,pos-500):pos+len(utr_norm)+500]

          local_amounts=extract_amounts(local)
          all_amounts=extract_amounts(body)
          amounts=local_amounts or all_amounts
          if not amounts:
            continue

          if expected is not None:
            # Prefer an amount that exactly matches the requested deposit.
            exact=[a for a in amounts if abs(a-expected)<0.01]
            if exact:
              logger.info('Payment verification: exact amount match %.2f found for UTR %s',exact[0],utr_to_find)
              return exact[0]
            sufficient=[a for a in amounts if a+0.01>=expected]
            if sufficient:
              # Prefer the smallest sufficient amount to avoid selecting a
              # larger unrelated balance/total from the email.
              chosen=min(sufficient)
              logger.info('Payment verification: sufficient amount %.2f found for UTR %s',chosen,utr_to_find)
              return chosen
            continue
          return max(amounts)
        except Exception as ex:
          logger.warning('IMAP message parse failed: %s',ex)

      logger.info('Payment verification: no matching Gmail payment found for UTR %s',utr_to_find)
      return None
    except Exception as ex:
      logger.error('Payment verification IMAP error: %s: %s',type(ex).__name__,ex)
      return None
    finally:
      if mail is not None:
        try: mail.logout()
        except Exception: pass

  return await asyncio.to_thread(fetch_sync)

def to_usd(inr):
  return round(inr / get_usdt_rate(), 2)

def is_user_banned(uid):
  res = cur.execute("SELECT banned FROM users WHERE user_id=?", (uid,)).fetchone()
  return res and res[0] == 1

def update_balance(uid, amount):
  cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, uid))
  db.commit()

def delete_session_files(session_path):
  base = session_path if not session_path.endswith('.session') else session_path[:-8]
  for ext in ['.session', '.session-wal', '.session-shm', '.session-journal']:
    try:
      if os.path.exists(base + ext): os.remove(base + ext)
    except: pass

async def _get_channel_entity(channel_id):
  """Resolve a configured channel ID safely for both public/private channels."""
  raw = str(channel_id or '').strip()
  if not raw:
    raise ValueError("Channel ID is empty")
  try:
    target = int(raw)
  except ValueError:
    target = raw
  return await bot.get_input_entity(target)

async def _is_bot_channel_admin(channel_id):
  """Return (ok, reason) after checking that THIS bot is admin/creator in the channel."""
  try:
    channel = await _get_channel_entity(channel_id)
    me = await bot.get_me()
    result = await bot(GetParticipantRequest(channel=channel, participant=me.id))
    participant = getattr(result, 'participant', result)
    if isinstance(participant, ChannelParticipantCreator):
      return True, ""
    if isinstance(participant, ChannelParticipantAdmin):
      rights = getattr(participant, 'admin_rights', None)
      # Telegram exposes invite_users for the permission needed to create an invite link.
      if rights is not None and getattr(rights, 'invite_users', None) is False:
        return False, 'The bot is an admin, but "Invite Users via Link" permission is disabled.'
      return True, ""
    return False, "The bot is in the channel, but it is not an admin."
  except UserNotParticipantError:
    return False, "The bot is not a member/admin of this channel."
  except ChatAdminRequiredError:
    return False, "Telegram did not allow the bot to inspect this channel. Make the bot an admin first."
  except Exception as ex:
    logger.error(f"Force channel admin check failed for {channel_id}: {ex}")
    return False, f"Could not verify this channel: {ex}"

async def _validate_force_invite_url(raw_url):
  """Accept only a real Telegram URL suitable for a Join button."""
  normalized = _normalize_tg_url(raw_url, "")
  if not normalized:
    return ""
  # Force-join links may be public channel URLs or private +invite links.
  if not re.match(r"^https?://(?:t\.me|telegram\.me)/(?:\+[^\s<>]+|[A-Za-z0-9_][^\s<>]*)$", normalized, re.IGNORECASE):
    return ""
  return normalized

async def _create_force_channel_invite(channel_id):
  """Create a Telegram invite link automatically for a verified channel."""
  try:
    channel = await _get_channel_entity(channel_id)
    result = await bot(ExportChatInviteRequest(peer=channel))
    link = getattr(result, 'link', '') or ''
    link = await _validate_force_invite_url(link)
    if not link:
      return False, '', 'Telegram returned an invalid invite link.'
    return True, link, ''
  except ChatAdminRequiredError:
    return False, '', 'Bot is admin, but Telegram has not granted it permission to create invite links. Enable the channel permission "Invite Users via Link".'
  except Exception as ex:
    logger.error(f"Force channel invite creation failed for {channel_id}: {ex}", exc_info=True)
    return False, '', f'Could not create invite link: {ex}'

async def check_channel_joined(uid):
  if is_admin(uid): return True
  rows = cur.execute("SELECT channel_id FROM force_channels").fetchall()
  if not rows: return True

  for (ch,) in rows:
    try:
      channel = await _get_channel_entity(ch)
      try: user = await bot.get_input_entity(uid)
      except Exception: user = await bot.get_entity(uid)
      await bot(GetParticipantRequest(channel=channel, participant=user))
    except (UserNotParticipantError, ValueError):
      return False
    except Exception as e:
      logger.error(f"Channel Check Error: {e}")
      return False
  return True

COUNTRY_CODES = {
  '1': 'USA/Canada', '7': 'Russia', '20': 'Egypt', '27': 'South Africa',
  '31': 'Netherlands', '32': 'Belgium', '33': 'France', '34': 'Spain',
  '39': 'Italy', '44': 'UK', '46': 'Sweden', '48': 'Poland',
  '49': 'Germany', '51': 'Peru', '52': 'Mexico', '54': 'Argentina',
  '55': 'Brazil', '56': 'Chile', '57': 'Colombia', '58': 'Venezuela',
  '60': 'Malaysia', '61': 'Australia', '62': 'Indonesia', '63': 'Philippines', 
  '66': 'Thailand', '84': 'Vietnam', '86': 'China', '90': 'Turkey',
  '91': 'India', '92': 'Pakistan', '93': 'Afghanistan', '94': 'Sri Lanka',
  '95': 'Myanmar', '98': 'Iran', '212': 'Morocco', '213': 'Algeria',
  '234': 'Nigeria', '254': 'Kenya', '255': 'Tanzania', '380': 'Ukraine',
  '880': 'Bangladesh', '964': 'Iraq', '966': 'Saudi Arabia', '971': 'UAE',
  '998': 'Uzbekistan'
}

def get_country_info(phone):
  phone = str(phone).replace(' ', '').replace('+', '')
  if not phone: return "Unknown"
  
  try:
    customs = cur.execute("SELECT code, name FROM custom_countries").fetchall()
    customs.sort(key=lambda x: len(x[0]), reverse=True)
    for code, name in customs:
      if phone.startswith(code): return name
  except: pass

  for length in (3, 2, 1):
    prefix = phone[:length]
    if prefix in COUNTRY_CODES: return COUNTRY_CODES[prefix]
  return "Unknown"

async def detect_account_year(client):
  year = 2024
  try:
    try: await client.delete_dialog('TGDNAbot')
    except: pass
    await client.send_message(custom_emoji_text('TGDNAbot'), '/start')
    me = await client.get_me()
    await asyncio.sleep(1)
    await client.send_message(custom_emoji_text('TGDNAbot'), str(me.id)) 
    for _ in range(8):
      await asyncio.sleep(1.5)
      msgs = await client.get_messages('TGDNAbot', limit=3)
      for m in msgs:
        if m.text and ('Created:' in m.text or 'Age:' in m.text or 'Registration' in m.text):
          match = re.search(r'(?:Created|Age|Registration)[^\d]*(\d{4})', m.text, re.IGNORECASE)
          if match: return int(match.group(1))
  except Exception: pass
  return year

def _spoiler(value):
  """Hide sensitive values in Telegram logs using Telegram spoiler formatting."""
  return f"<tg-spoiler>{html.escape(str(value))}</tg-spoiler>"

async def _get_bot_buy_button():
  try:
    bot_info = await bot.get_me()
    username = getattr(bot_info, 'username', None)
    if username:
      return [[Button.url(" Buy Now", f"https://t.me/{username}", style="success")]]
  except Exception as ex:
    logger.error(f"Failed to build Buy Now button: {ex}")
  return None

async def _send_selling_log(msg):
  try:
    buttons = await _get_bot_buy_button()
    await bot.send_message(
      custom_emoji_text(get_log_channel_id()),
      custom_emoji_text(msg),
      buttons=buttons,
      parse_mode='html'
    )
    return True
  except Exception as ex:
    logger.error(f"Selling log send failed: {ex}")
    return False

async def log_primary_deposit(uid, amt, method):
  """Successful deposit log only. Verification/pending screenshots never go to the log channel."""
  try:
    try:
      user = await bot.get_entity(int(uid))
      username = user.username if user and user.username else "NoUsername"
    except Exception:
      username = "NoUsername"
    t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    msg = (
      f"{P_YES} {P_FIRE} <b>NEW DEPOSIT SUCCESSFUL</b> {P_PARTY}\n\n"
      f"{P_ACC} User ID: {_spoiler(uid)}\n"
      f"{P_ACC} Username: {_spoiler('@' + username if username != 'NoUsername' else username)}\n"
      f"{P_MONEY} Amount: {P_INR}{amt}\n"
      f"{P_CARD} Method: <b>{html.escape(str(method))}</b>\n"
      f"{P_TIME} Time: {t}\n\n"
      f"<i>{P_STAR} Deposit confirmed successfully. {P_STAR}</i>"
    )
    await _send_selling_log(msg)
  except Exception as ex:
    logger.error(f"Global Dep Log Err: {ex}", exc_info=True)

async def log_primary_deposit_success(uid, amt, method, utr=None):
  # UTR is intentionally not displayed in the channel; only successful deposit metadata is logged.
  await log_primary_deposit(uid, amt, method)

async def log_primary_purchase(uid, country, price, amount, year, qty):
  try:
    t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    msg = (
      f"{P_CART} {P_ROCKET} <b>NEW TELEGRAM ACCOUNT SALE</b> {P_PARTY}\n\n"
      f"{P_ID} User ID: {_spoiler(uid)}\n"
      f"{P_GLOBE} Country: {html.escape(str(country))}\n"
      f"{P_MONEY} Price: {P_INR}{price}\n"
      f"{P_CARD} Total Paid: {P_INR}{amount}\n"
      f"{P_CAL} Year: {year}\n"
      f"{P_PKG} Quantity: {qty}\n"
      f"{P_PHONE} Account Details: {_spoiler('Hidden / Delivered Privately')}\n"
      f"{P_TIME} Time: {t}"
    )
    await _send_selling_log(msg)
  except Exception as ex:
    logger.error(f"Purchase Log Err: {ex}", exc_info=True)

async def log_smm_sale(uid, service_name, bot_order_id, panel_order_id, link, quantity, total_price):
  try:
    t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    msg = (
      f"{P_CART} {P_ROCKET} <b>NEW SMM ORDER SALE</b> {P_PARTY}\n\n"
      f"{P_ID} User ID: {_spoiler(uid)}\n"
      f"{P_GEAR} Service: {html.escape(str(service_name))}\n"
      f"{P_ID} Bot Order ID: {_spoiler(bot_order_id)}\n"
      f"{P_GEAR} Panel Order ID: {_spoiler(panel_order_id)}\n"
      f"{P_LINK} Link: {_spoiler(link)}\n"
      f"{P_PKG} Quantity: {quantity}\n"
      f"{P_MONEY} Total Paid: ₹{float(total_price):.4f}\n"
      f"{P_TIME} Time: {t}"
    )
    await _send_selling_log(msg)
  except Exception as ex:
    logger.error(f"SMM Sale Log Err: {ex}", exc_info=True)

async def log_digital_sale(uid, product_name, price):
  try:
    t = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    msg = (
      f"{P_STORE} {P_ROCKET} <b>NEW DIGITAL PRODUCT SALE</b> {P_PARTY}\n\n"
      f"{P_ID} User ID: {_spoiler(uid)}\n"
      f"{P_DOC} Product: {html.escape(str(product_name))}\n"
      f"{P_MONEY} Total Paid: ₹{price}\n"
      f"{P_TIME} Time: {t}"
    )
    await _send_selling_log(msg)
  except Exception as ex:
    logger.error(f"Digital Sale Log Err: {ex}", exc_info=True)

async def notify_new_user(uid, event):
  """Notify the owner in DM once when a genuinely new user is created."""
  try:
    sender = await event.get_sender()
    name = getattr(sender, 'first_name', None) or 'Unknown'
    username = getattr(sender, 'username', None)
    msg = (
      f"{P_BELL} <b>NEW USER JOINED</b>\n\n"
      f"{P_ACC} User ID: <code>{uid}</code>\n"
      f"{P_ACC} Name: {html.escape(name)}\n"
      f"{P_ACC} Username: @{html.escape(username) if username else 'NoUsername'}\n"
      f"{P_TIME} Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    await bot.send_message(custom_emoji_text(ADMIN_ID), custom_emoji_text(msg), parse_mode='html')
  except Exception as ex:
    logger.error(f"New user admin notification failed: {ex}")

# ================= PERSISTENT MENU =================
def get_persistent_menu(uid):
  # Support/Updates are direct URL buttons so they never depend on a callback
  # handler. Their destinations are controlled from the Admin Panel settings.
  support_url = get_support_url()
  updates_url = "https://t.me/BOTS_UPDATE_07"
  # Support/Updates remain direct redirects when Admin has configured a valid
  # Telegram URL. If a URL has not been configured yet, use the callback
  # fallback instead of constructing an invalid Button.url (which crashes
  # the entire /start media send with ButtonUrlInvalidError).
  support_btn = (
    Button.url("Support", support_url, style="primary")
    if _has_valid_button_url(support_url)
    else Button.inline("Support", data="cb_support", style="primary")
  )
  updates_btn = (
    Button.url("Updates", updates_url, style="primary")
    if _has_valid_button_url(updates_url)
    else Button.inline("Updates", data="cb_updates", style="primary")
  )
  rows = [
    [
      Button.inline("Store", data="cb_store", style="primary"),
      Button.inline("Add Funds", data="cb_addfunds", style="success")
    ],
    [
      Button.inline("Profile", data="cb_profile", style="primary"),
      Button.inline("Orders History", data="cb_orders", style="primary")
    ],
    [
      Button.inline("Refill", data="cb_refill", style="primary"),
      Button.inline("Redeem Code", data="redeem_start", style="success")
    ],
    [Button.url(" Selling Logs", "https://t.me/+_ZKmRFObdYA1YjU1", style="primary")],
    [support_btn],
    [updates_btn]
  ]
  return rows

async def send_main_menu(event, uid):
  ensure_user(uid)
  row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
  bal = row[0] if row else 0

  try:
    sender = await event.get_sender()
    user_name = html.escape(sender.first_name) if sender and sender.first_name else "User"
  except Exception:
    user_name = "User"

  # Keep the account summary together inside a Telegram quote block, matching
  # the requested UI. Custom-emoji constants remain inside the quoted lines.
  # Premium/custom-emoji styled welcome text. Every visual marker is a
  # Telegram custom emoji ID, including the quoted account summary.
  msg = (
    f"{P_DIAMOND} <b>AccStore Marketplace</b> {P_STAR}\n"
    f"{P_TG} <b>Welcome back,</b> {P_ACC} <b>{user_name}</b> {P_LIGHTNING} {P_STAR}\n\n"
    f"<blockquote>"
    f"{P_MONEY} <b>Wallet Balance:</b> {P_INR}{bal:.2f} {P_USDT} (${to_usd(bal):.2f})\n"
    f"{P_ID} <b>Account UID:</b> <code>{uid}</code> {P_YES}\n"
    f"{P_CROWN} <b>Membership:</b> <b>Verified VIP</b> {P_YES}"
    f"</blockquote>\n"
    f"{P_STAR} <i>Your premium destination for fast, reliable, and automated account purchases.</i> {P_FIRE} {P_DIAMOND}"
  )

  img_path = "23593.jpg"
  buttons = get_persistent_menu(uid)

  if isinstance(event, events.CallbackQuery.Event):
    try:
      await event.delete()
    except Exception:
      pass
    if os.path.exists(img_path):
      await bot.send_file(uid, img_path, caption=custom_emoji_text(msg), buttons=buttons, parse_mode='html')
    else:
      await bot.send_message(custom_emoji_text(uid), custom_emoji_text(msg), buttons=buttons, parse_mode='html')
  else:
    if os.path.exists(img_path):
      await event.respond(file=img_path, message=custom_emoji_text(msg), buttons=buttons, parse_mode='html')
    else:
      await event.respond(custom_emoji_text(msg), buttons=buttons, parse_mode='html')

async def store_servers_menu(event):
  """Open the Store menu reliably from both text and callback messages.

  The main menu is usually a photo message. Telegram cannot turn that media
  message into a normal text message with buttons reliably on every client,
  so callback navigation explicitly replaces the media message and falls
  back to a fresh message if the first send path fails.
  """
  msg = (
    f"{P_STORE} {P_ROCKET} <b>AccStore Store</b> {P_STAR}\n"
    f"────────────────\n\n"
    f"<b>Welcome to our digital marketplace!</b> {P_PARTY}\n"
    f"Please select below to browse our available stock:"
  )
  btns = [
    [Button.inline("𝗧𝗚 𝗔𝗖𝗖", "srv|manual", style="primary")],
    [Button.inline("Digital Shop", "digital_shop", style="success")],
    [Button.inline("Social Media Services", "cb_smm_services", style="success")],
    [Button.inline("Back to Main", "back_main", style="primary")]
  ]
  rendered = custom_emoji_text(msg)

  if not isinstance(event, events.CallbackQuery.Event):
    return await event.respond(rendered, buttons=btns, parse_mode='html')

  try:
    if getattr(getattr(event, '_message', None), 'media', None):
      try:
        await event.delete()
      except Exception as ex:
        logger.warning(f"Store media delete failed: {ex}")
      try:
        return await event.respond(rendered, buttons=btns, parse_mode='html')
      except Exception as ex:
        logger.warning(f"Store event.respond failed: {ex}")
        return await bot.send_message(event.chat_id, rendered, buttons=btns, parse_mode='html')

    try:
      return await event.edit(rendered, buttons=btns, parse_mode='html')
    except MessageNotModifiedError:
      return
    except Exception as ex:
      logger.warning(f"Store event.edit failed: {ex}")
      return await event.respond(rendered, buttons=btns, parse_mode='html')
  except Exception as ex:
    logger.error(f"Store menu error: {ex}", exc_info=True)
    try:
      return await bot.send_message(event.chat_id, rendered, buttons=btns, parse_mode='html')
    except Exception as send_ex:
      logger.error(f"Store fallback send failed: {send_ex}", exc_info=True)
      await safe_callback_answer(event, "Store could not be opened. Please try /start again.", alert=True)

# ================= DIGITAL SHOP =================
async def digital_shop_menu(event):
  """Open Digital Shop reliably from any callback message type."""
  try:
    rows = cur.execute(
      "SELECT id, name, description, price, photo_path, file_path FROM digital_products WHERE active=1 ORDER BY id DESC"
    ).fetchall()
  except Exception as ex:
    logger.error(f"Digital Shop DB Error: {ex}", exc_info=True)
    msg = custom_emoji_text(f"{P_NO} <b>Digital Shop</b>\n\nUnable to load products right now.")
    btns = [[Button.inline("Back to Store", "store_servers", style="primary")]]
    try:
      return await e_edit_or_send(event, msg, btns)
    except Exception:
      return await bot.send_message(event.chat_id, msg, buttons=btns, parse_mode='html')

  if not rows:
    msg = custom_emoji_text(f"{P_STORE} <b>Digital Shop</b>\n\nNo digital products are available right now.")
    btns = [[Button.inline("Back to Store", "store_servers", style="primary")]]
    return await e_edit_or_send(event, msg, btns)

  btns = []
  for pid, name, desc, price, preview_path, file_path in rows:
    # Telegram callback data is limited; keep the ID as the only payload.
    label = str(name or f"Product #{pid}")
    if len(label) > 42:
      label = label[:39] + "..."
    btns.append([Button.inline(f"{label} - ₹{price}", f"digital_product|{pid}", style="primary")])
  btns.append([Button.inline("Back to Store", "store_servers", style="primary")])
  msg = custom_emoji_text(f"{P_STORE} <b>Digital Shop</b>\n\nSelect a product:")
  return await e_edit_or_send(event, msg, btns)


async def e_edit_or_send(event, msg, buttons):
  """Edit a callback message when possible; otherwise send a fresh message."""
  if not isinstance(event, events.CallbackQuery.Event):
    return await event.respond(msg, buttons=buttons, parse_mode='html')
  try:
    if getattr(getattr(event, '_message', None), 'media', None):
      try:
        await event.delete()
      except Exception as ex:
        logger.warning(f"Callback media delete failed: {ex}")
      return await bot.send_message(event.chat_id, msg, buttons=buttons, parse_mode='html')
    try:
      return await event.edit(msg, buttons=buttons, parse_mode='html')
    except MessageNotModifiedError:
      return
    except Exception as ex:
      logger.warning(f"Callback edit failed, using send fallback: {ex}")
      return await bot.send_message(event.chat_id, msg, buttons=buttons, parse_mode='html')
  except Exception as ex:
    logger.error(f"Callback edit/send fallback failed: {ex}", exc_info=True)
    return await bot.send_message(event.chat_id, msg, buttons=buttons, parse_mode='html')

async def digital_product_view(event, pid):
  try:
    pid = int(pid)
    row = cur.execute(
      "SELECT id,name,description,price,photo_path,file_path FROM digital_products WHERE id=? AND active=1",
      (pid,)
    ).fetchone()
    if not row:
      return await safe_callback_answer(event, "Product not found.", alert=True)

    _, name, desc, price, preview_path, file_path = row
    path = str(preview_path or '').strip()
    name = str(name or f"Product #{pid}")
    desc = str(desc or "No description provided.")
    path = str(path or "").strip()
    price = int(price)
    msg = (
      f"<b>{html.escape(name)}</b>\n\n"
      f"<b>Description:</b>\n{html.escape(desc)}\n\n"
      f"<b>Price:</b> ₹{price}"
    )
    btns = [
      [Button.inline(f"Buy Now - ₹{price}", str(f"digital_buy|{pid}"), style="success")],
      [Button.inline("Back to Digital Shop", "digital_shop", style="primary")]
    ]
    if path and os.path.isfile(path):
      try:
        await event.delete()
        return await bot.send_file(
          event.chat_id, path, caption=custom_emoji_text(msg),
          buttons=btns, parse_mode='html'
        )
      except Exception as ex:
        logger.warning(f"Digital product media send failed: {ex}", exc_info=True)
    return await e_edit_or_send(event, custom_emoji_text(msg), btns)
  except Exception as ex:
    logger.error(f"Digital Product View Error: {ex}", exc_info=True)
    try:
      await bot.send_message(
        event.chat_id,
        "Product could not be opened right now. Please try again.",
        buttons=[[Button.inline("Back to Digital Shop", "digital_shop", style="primary")]],
        parse_mode='html'
      )
    except Exception:
      pass


async def digital_buy(event, pid):
  uid = int(event.sender_id)
  charged = False
  price = 0
  try:
    pid = int(pid)
    row = cur.execute(
      "SELECT id,name,description,price,photo_path,file_path FROM digital_products WHERE id=? AND active=1",
      (pid,)
    ).fetchone()
    if not row:
      return await safe_callback_answer(event, "Product unavailable.", alert=True)

    _, name, desc, db_price, preview_path, db_file_path = row
    name = str(name or f"Product #{pid}")
    desc = str(desc or "")
    price = int(db_price)
    # Existing products used photo_path as the delivered file; keep backward compatibility.
    path = str(db_file_path or preview_path or '').strip()

    if price <= 0:
      return await safe_callback_answer(event, "Invalid product price. Please contact admin.", alert=True)
    if not path or not os.path.isfile(path):
      logger.error(f"Digital product file missing: pid={pid}, path={path!r}")
      return await safe_callback_answer(event, "Product file is unavailable. Please contact admin.", alert=True)

    async with get_user_lock(uid):
      balrow = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
      bal = int(balrow[0]) if balrow and balrow[0] is not None else 0
      if bal < price:
        return await safe_callback_answer(event, f"Insufficient balance. Need ₹{price}.", alert=True)
      cur.execute(
        "UPDATE users SET balance=balance-? WHERE user_id=? AND balance>=?",
        (price, uid, price)
      )
      if cur.rowcount != 1:
        db.rollback()
        return await safe_callback_answer(event, "Balance changed. Please try again.", alert=True)
      db.commit()
      charged = True

    msg = (
      f"<b>Digital Product Purchased</b>\n\n"
      f"<b>{html.escape(name)}</b>\n"
      f"Paid: ₹{price}\n\n"
      f"{html.escape(desc)}"
    )
    buttons = [[Button.inline("Back to Digital Shop", "digital_shop", style="primary")]]

    try:
      try:
        await event.delete()
      except Exception:
        pass
      await bot.send_file(
        uid, path, caption=custom_emoji_text(msg),
        parse_mode='html', buttons=buttons
      )
    except Exception as delivery_ex:
      logger.error(f"Digital delivery failed for pid={pid}, uid={uid}: {delivery_ex}", exc_info=True)
      if charged:
        try:
          async with get_user_lock(uid):
            cur.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (price, uid))
            db.commit()
          charged = False
        except Exception as refund_ex:
          logger.error(f"Digital purchase refund failed for uid={uid}: {refund_ex}", exc_info=True)
      return await bot.send_message(
        uid,
        "Purchase could not be delivered. Your balance has been refunded. Please try again later.",
        buttons=buttons, parse_mode='html'
      )

    try:
      await log_digital_sale(uid, name, price)
    except Exception as log_ex:
      logger.error(f"Digital sale log error: {log_ex}", exc_info=True)
  except Exception as ex:
    logger.error(f"Digital Buy Error: {ex}", exc_info=True)
    try:
      await bot.send_message(
        uid,
        "Digital purchase could not be completed. No balance was charged if delivery did not start.",
        buttons=[[Button.inline("Back to Digital Shop", "digital_shop", style="primary")]],
        parse_mode='html'
      )
    except Exception:
      pass

async def digital_shop_admin_menu(event):
  rows=cur.execute("SELECT id,name,price,active FROM digital_products ORDER BY id DESC").fetchall()
  msg=f"{P_STORE} <b>Manage Digital Shop</b>\n\n"
  if not rows: msg += "No products added yet."
  else:
    for pid,name,price,active in rows:
      msg += f"<code>{pid}</code> - <b>{html.escape(name)}</b> - ₹{price} - {'ON' if active else 'OFF'}\n"
  btns=[[Button.inline("Add Product","adm_digital_add",style="success")],
     [Button.inline("Remove Product","adm_digital_remove",style="danger")],
     [Button.inline("Back to Admin","adm_adminmain",style="primary")]]
  await event.edit(custom_emoji_text(msg),buttons=btns)

# ================= REDEEM CODES =================
async def redeem_code_for_user(event, code):
  uid=event.sender_id; code=str(code).strip().upper()
  row=cur.execute("SELECT amount,max_users,used_count,active FROM redeem_codes WHERE code=?",(code,)).fetchone()
  if not row: return await safe_callback_answer(event,"Invalid redeem code.",alert=True)
  amount,max_users,used_count,active=row
  if not active or used_count>=max_users: return await safe_callback_answer(event,"This code is no longer available.",alert=True)
  claimed=cur.execute("SELECT 1 FROM redeem_claims WHERE code=? AND user_id=?",(code,uid)).fetchone()
  if claimed: return await safe_callback_answer(event,"You have already redeemed this code.",alert=True)
  async with get_user_lock(uid):
    cur.execute("INSERT INTO redeem_claims(code,user_id) VALUES(?,?)",(code,uid))
    if cur.rowcount != 1: return await safe_callback_answer(event,"You have already redeemed this code.",alert=True)
    cur.execute("UPDATE redeem_codes SET used_count=used_count+1 WHERE code=? AND active=1 AND used_count<?",(code,max_users))
    if cur.rowcount != 1:
      cur.execute("DELETE FROM redeem_claims WHERE code=? AND user_id=?",(code,uid)); db.commit()
      return await safe_callback_answer(event,"This code just reached its limit.",alert=True)
    update_balance(uid,amount); db.commit()
  await event.edit(custom_emoji_text(f"{P_YES} <b>Redeem Successful!</b>\n\nCode: <code>{html.escape(code)}</code>\nAmount Added: <b>₹{amount}</b>"),buttons=[[Button.inline("Back to Main","back_main",style="primary")]])

# ================= SOCIAL MEDIA SERVICES (USER FLOW) =================
async def show_smm_categories(event):
  rows = cur.execute("SELECT id, name FROM smm_categories").fetchall()
  if not rows:
    msg = f"{P_WARN} <b>No social media service categories available right now.</b>"
    btns = [[Button.inline("Back", "back_main", style="primary")]]
    if isinstance(event, events.CallbackQuery.Event): return await event.edit(custom_emoji_text(msg), buttons=btns)
    else: return await event.respond(custom_emoji_text(msg), buttons=btns)

  msg = f"{P_FOLDER} <b>Select Category (Page 1/1):</b>"
  btns = []
  for cid, cname in rows:
    btns.append([Button.inline(f"{cname}", f"smm_cat|{cid}", style="primary")])
  btns.append([Button.inline("Back", "back_main", style="primary")])

  if isinstance(event, events.CallbackQuery.Event): await event.edit(custom_emoji_text(msg), buttons=btns)
  else: await event.respond(custom_emoji_text(msg), buttons=btns)

async def show_smm_services_in_category(event, category_id):
  rows = cur.execute("SELECT service_id, name, rate, min, max FROM smm_services WHERE category_id=?", (category_id,)).fetchall()
  
  if not rows:
    msg = f"{P_WARN} <b>No services found in this category.</b>"
    btns = [[Button.inline("Back to Categories", "cb_smm_services", style="primary")]]
    return await event.edit(custom_emoji_text(msg), buttons=btns)

  msg = f"{P_ASST} <b>Select Service (Page 1/1):</b>"
  btns = []
  for sid, sname, rate, smin, smax in rows:
    btns.append([Button.inline(f"{custom_emoji_text(str(sname))}", f"smm_srv|{sid}", style="primary")])
  btns.append([Button.inline("Back to Categories", "cb_smm_services", style="primary")])
  await event.edit(custom_emoji_text(msg), buttons=btns)

async def smm_service_detail_view(event, service_id):
  row = cur.execute("SELECT service_id, name, rate, min, max, description FROM smm_services WHERE service_id=?", (service_id,)).fetchone()
  if not row: return await safe_callback_answer(event, "Service not found.", alert=True)
  sid, name, rate, smin, smax, desc = row
  
  msg = (f"{P_ID} <b>Service ID: {sid}</b>\n"
      f"{P_TITLE} <b>Title:</b> {html.escape(name)}\n\n"
      f"{P_DESC} <b>Description:</b>\n{html.escape(desc if desc else 'No description available')}\n\n"
      f"{P_RATE} <b>Rate: ₹{rate} Per 1000</b>\n"
      f"{P_MIN} <b>Min: {smin}</b>\n"
      f"{P_MAX} <b>Max :{smax}</b>\n\n"
      f"{P_ASST} <b>Send Link:</b>")
  
  btns = [
    [Button.inline(f"{custom_emoji_text(str(name))} Buy Service", f"smm_buy|{sid}", style="success")],
    [Button.inline("Back to Categories", "cb_smm_services", style="primary")]
  ]
  await event.edit(custom_emoji_text(msg), buttons=btns)

async def show_server_countries(event, server_type, page=1):
  limit = 10
  offset = (page - 1) * limit
  
  total_row = cur.execute("SELECT COUNT(DISTINCT country_name) FROM stock WHERE available=1").fetchone()
  total = total_row[0] if total_row else 0
  rows = cur.execute("SELECT country_name, COUNT(*), MIN(price) FROM stock WHERE available=1 GROUP BY country_name ORDER BY country_name ASC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    
  if not rows and page == 1: 
    err_msg = f"{P_NO} <b>Stock is Empty right now. Check back later!</b>"
    btns = [[Button.inline("Back to Store", "store_servers", style="primary")]]
    if isinstance(event, events.CallbackQuery.Event): return await event.edit(custom_emoji_text(err_msg), buttons=btns)
    else: return await event.respond(custom_emoji_text(err_msg), buttons=btns)
  
  rate = get_usdt_rate()
  msg = (
    f"{P_CART} {P_FIRE} <b>SELECT PRODUCT (ACCOUNTS)</b> {P_STAR}\n"
    f"────────────────\n\n"
    f"{P_USDT} <b>Rate: 1 USDT = ₹{rate}</b>\n"
  )
  
  for (c_name, count, min_p) in rows:
    usd_p = to_usd(min_p)
    flag = ""
    msg += f"- {flag} {c_name}: ${usd_p} (₹{min_p}) - Stock: {count} {P_YES}\n"
    
  msg += f"\n<i>Select an item to view details:</i> {P_ASST}"
  
  btns = []
  for (c_name, count, min_p) in rows:
    usd_p = to_usd(min_p)
    btns.append([Button.inline(f"{c_name} - ₹{min_p} (${usd_p})", f"s_country|{server_type}|{_country_token(c_name)}", style="primary")])

  nav = []
  if page > 1: nav.append(Button.inline("Prev", f"srv_pg|{server_type}|{page-1}", style="primary"))
  if offset + limit < total: nav.append(Button.inline("Next", f"srv_pg|{server_type}|{page+1}", style="primary"))
  if nav: btns.append(nav)
  btns.append([Button.inline("Back to Store", "store_servers", style="primary")])
  
  if isinstance(event, events.CallbackQuery.Event): await event.edit(custom_emoji_text(msg), buttons=btns)
  else: await event.respond(custom_emoji_text(msg), buttons=btns)

async def show_country_details(event, server_type, country):
  rows = cur.execute("SELECT account_year, price, COUNT(*) FROM stock WHERE available=1 AND country_name LIKE ? GROUP BY account_year, price ORDER BY account_year DESC", (f"{country}%",)).fetchall()
  total_stock = sum([r[2] for r in rows]) if rows else 0
  
  msg = (
    f"{P_STAR} {P_FIRE} <b>Quality Account - {html.escape(country)}</b> {P_STAR}\n\n"
    f"- <b>Country:</b> {html.escape(country)}\n"
    f"- <b>Available:</b> {total_stock} {P_YES}\n\n"
    f"<b>Stock by year:</b> {P_CAL}\n"
  )
  for (y, p, c) in rows:
    msg += f"- {country} {y} – {c} × ₹{p} each {P_MONEY}\n"
    
  msg += (
    f"\n<i>Each account is charged at its year price (admin-configured).</i>\n"
    f"{P_WARN} <b>Use Telegraph for login.</b>\n"
    f"{P_NO} <b>Account freeze/ban risk is user responsibility.</b>"
  )
  
  btns = [
    [Button.inline(f"Buy Single", f"p_buy|single|{_country_token(country)}", style="success")],
    [Button.inline(f"Buy Bulk", f"p_buy|bulk|{_country_token(country)}", style="success")],
    [Button.inline(f"Choose Year", f"p_year|{_country_token(country)}", style="primary")],
    [Button.inline("Back to Countries", f"srv|{server_type}", style="primary")]
  ]
  await event.edit(custom_emoji_text(msg), buttons=btns)

async def show_years_for_country(event, country):
  rows = cur.execute("SELECT account_year, price, COUNT(*) FROM stock WHERE available=1 AND country_name LIKE ? GROUP BY account_year, price ORDER BY account_year DESC", (f"{country}%",)).fetchall()
  if not rows: return await safe_callback_answer(event, "Out of stock for this country.", alert=True)

  uid = event.sender_id
  disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
  discount = disc_row[0] if disc_row else 0

  msg = f"{P_CAL} {P_STAR} <b>Select Account Year</b>\n{P_GLOBE} Country: <b>{html.escape(country)}</b>\n\n"
  btns = []
  
  for (y, p, c) in rows:
    disp_p = p if discount == 0 else int(p * (100 - discount) / 100)
    disc_text = f" (-{discount}%)" if discount > 0 else ""
    btns.append([Button.inline(f"{y} | ₹{disp_p}{disc_text} | Stock: {c}", f"by_yr|{_country_token(country)}|{y}|{p}", style="primary")])

  btns.append([Button.inline("Back to Details", f"s_country|manual|{_country_token(country)}", style="primary")])
  await event.edit(custom_emoji_text(msg), buttons=btns)

async def profile_handler(event, is_callback=False):
  uid = event.sender_id
  row = cur.execute("SELECT balance, total_deposited, joined_date FROM users WHERE user_id=?", (uid,)).fetchone()
  if not row: return
  
  bal, dep, joined = row
  o_row = cur.execute("SELECT COUNT(*), SUM(price) FROM orders WHERE user_id=?", (uid,)).fetchone()
  total_orders = o_row[0] if o_row else 0
  spent = o_row[1] if o_row and o_row[1] else 0
  
  try:
    sender = await event.get_sender()
    user_name = html.escape(sender.first_name) if sender and sender.first_name else "User"
  except:
    user_name = "User"
    
  date_str = joined[:10] if joined else "2026-05-25"

  msg = (
    f"{P_STAR} {P_CROWN} <b>VIP ACCOUNT PROFILE</b> {P_STAR}\n\n"
    f"{P_ACC} <b>Account Holder:</b> <b>{user_name}</b> {P_FIRE}!!\n"
    f"{P_ID} <b>User ID:</b> <code>{uid}</code>\n"
    f"{P_CAL} <b>Member Since:</b> {date_str}\n"
    f"────────────────────────\n\n"
    f"{P_MONEY} <b>WALLET OVERVIEW</b>\n"
    f"├ <b>Available Balance:</b> ₹{bal:.2f} (${to_usd(bal):.2f})\n"
    f"├ <b>Total Deposited:</b> ₹{dep:.2f}\n"
    f"└ <b>Total Spent:</b> ₹{spent:.2f}\n\n"
    f"{P_STATS} <b>ACCOUNT ACTIVITY</b>\n"
    f"├ <b>Orders Completed:</b> {total_orders} {P_ROCKET}\n"
    f"├ <b>Verification:</b> Verified {P_YES}\n"
    f"└ <b>Terms of Service:</b> Accepted {P_YES}"
  )

  btns = [
    [Button.inline("Deposit Funds", "dep_menu_cb", style="success")],
    [Button.inline("My Orders", "my_orders_list", style="primary"), Button.inline("Payments History", "payments_history", style="primary")],
    [Button.inline("Back to Main Menu", "back_main", style="primary")]
  ]

  if is_callback:
    try: await event.edit(custom_emoji_text(msg), buttons=btns)
    except MessageNotModifiedError: pass
  else:
    await bot.send_message(custom_emoji_text(event.chat_id), msg, buttons=btns)

async def orders_history_handler(event, is_callback=False):
  uid = event.sender_id
  rows = cur.execute("SELECT country, year, price, phone, date FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid,)).fetchall()
  
  if not rows:
    msg = f"{P_DOC} <b>You don't have any orders yet.</b> {P_WARN}"
  else:
    msg = f"{P_DOC} {P_ROCKET} <b>Your Recent Orders:</b>\n\n"
    for country, yr, price, phone, d in rows:
      msg += f"- <b>{country} ({yr})</b>\n {P_PHONE} <code>{phone}</code> | ₹{price} {P_MONEY}\n {P_CAL} {d}\n────────────────\n"

  btns = [
    [Button.inline("Back", "back_main", style="primary")]
  ]

  if is_callback:
    try: await event.edit(custom_emoji_text(msg), buttons=btns)
    except MessageNotModifiedError: pass
  else:
    await bot.send_message(custom_emoji_text(event.chat_id), msg, buttons=btns)

async def payments_history_handler(event):
  uid = event.sender_id
  rows = cur.execute("SELECT amount, method_name, status, date FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid,)).fetchall()
  
  if not rows:
    msg = f"{P_CARD} <b>You don't have any payment history yet.</b>"
  else:
    msg = f"{P_CARD} {P_MONEY} <b>Recent Payments:</b>\n\n"
    for amt, method, status, d in rows:
      msg += f"- ₹{amt} via {method} – <b>{status.upper()}</b> {P_YES}\n {P_CAL} {d}\n────────────────\n"

  btns = [[Button.inline("Back to Profile", "profile_callback", style="primary")]]
  await event.edit(custom_emoji_text(msg), buttons=btns)

async def deposit_menu(event):
  rows=[]
  if payment_enabled('fampay_enabled'):
    rows.append([Button.inline("FamPay Automatic", "depm_auto", style="success")])
  if payment_enabled('manual_enabled'):
    rows.append([Button.inline("UPI Manual", "depm_manual", style="primary")])
  rows.append([Button.inline("Back", "back_main", style="primary")])
  msg=f"{P_CARD} {P_MONEY} <b>Select Payment Method</b>\n\nChoose an enabled method below."
  if isinstance(event, events.CallbackQuery.Event): await event.edit(custom_emoji_text(msg),buttons=rows)
  else: await bot.send_message(event.chat_id,custom_emoji_text(msg),buttons=rows)

async def manual_deposit_init(event, method):
  """Open a button-based amount keypad for both payment methods."""
  uid = event.sender_id
  method_key = 'auto' if method == 'FamPay Automatic' else 'manual'
  deposit_input[uid] = {'step': 'amount_keypad', 'method': method, 'method_key': method_key, 'amount': ''}
  await show_deposit_amount_keypad(event, uid)

async def show_deposit_amount_keypad(event, uid):
  state = deposit_input.get(uid, {})
  method = state.get('method', 'UPI Manual')
  amount = state.get('amount', '') or '0'
  msg = (
    f"{P_CARD} <b>Custom Amount</b>\n\n"
    f"{P_MONEY} <b>Method:</b> {html.escape(method)}\n"
    f"{P_ASST} <b>Amount: ₹{html.escape(amount)}</b>\n\n"
    f"{P_ASST} <i>Amount type karo - buttons se:</i>"
  )
  btns = [
    [Button.inline(" 1", "dep_key|1", style="success"), Button.inline(" 2", "dep_key|2", style="success"), Button.inline(" 3", "dep_key|3", style="success")],
    [Button.inline(" 4", "dep_key|4", style="success"), Button.inline(" 5", "dep_key|5", style="success"), Button.inline(" 6", "dep_key|6", style="success")],
    [Button.inline(" 7", "dep_key|7", style="success"), Button.inline(" 8", "dep_key|8", style="success"), Button.inline(" 9", "dep_key|9", style="success")],
    [Button.inline(" Delete", "dep_key_del", style="danger"), Button.inline(" 0", "dep_key|0", style="success"), Button.inline(" Confirm", "dep_key_confirm", style="success")],
    [Button.inline(" Back", "dep_menu_cb", style="primary")]
  ]
  await event.edit(custom_emoji_text(msg), buttons=btns)

async def generate_deposit_qr(event, uid):
  state = deposit_input.get(uid)
  if not state or state.get('step') != 'amount_keypad':
    return await safe_callback_answer(event, "Amount session expired. Please start again.", alert=True)
  raw_amount = state.get('amount', '')
  try:
    amt = int(raw_amount)
  except Exception:
    amt = 0
  if amt < 10:
    return await safe_callback_answer(event, "Minimum deposit is ₹10.", alert=True)

  method = state.get('method', 'UPI Manual')
  is_auto = method == 'FamPay Automatic'
  upi_id = get_fampay_upi() if is_auto else get_manual_upi()
  payee = get_fampay_name() if is_auto else get_manual_name()

  # Keep the UPI URI internal only for QR generation. Never show a payment link to the user.
  upi_link = 'upi://pay?' + urlencode({'pa': upi_id, 'pn': payee, 'am': amt, 'cu': 'INR'})
  qr_url = 'https://api.qrserver.com/v1/create-qr-code/?size=350x350&data=' + quote(upi_link)
  qr_file = f"qr_{uid}_{int(time.time())}.png"

  await safe_callback_answer(event, "Generating payment QR...", alert=False)
  try:
    await event.edit(custom_emoji_text(f"{P_WAIT} <b>Generating payment QR...</b>\n\nAmount: <b>₹{amt}</b>"), buttons=[[Button.inline("Cancel", "cancel_action", style="danger")]])
  except Exception:
    pass

  try:
    urllib.request.urlretrieve(qr_url, qr_file)
  except Exception as ex:
    logger.error(f"Deposit QR generation failed: {ex}")
    deposit_input[uid] = {'step': 'amount_keypad', 'method': method, 'method_key': state.get('method_key'), 'amount': raw_amount}
    return await event.edit(custom_emoji_text(f"{P_NO} <b>QR generation failed.</b>\n\nPlease try again."), buttons=[[Button.inline("Generate QR Again", "dep_key_confirm", style="success")], [Button.inline("Cancel", "cancel_action", style="danger")]])

  deposit_input[uid] = {'step': 'wait_payment_verify', 'amount': amt, 'method': method, 'upi_id': upi_id, 'payee': payee}
  caption = (
    f"{P_CARD} <b>{html.escape(method)} Payment</b>\n\n"
    f"{P_MONEY} <b>Amount: ₹{amt}</b>\n"
    f"{P_ACC} <b>Payee: {html.escape(payee)}</b>\n\n"
    f"Scan the QR and complete the payment.\n"
    f"After payment, tap <b>Verify Payment</b> and send your payment screenshot."
  )
  btns = [[Button.inline(" Verify Payment", "dep_payment_verify", style="success")], [Button.inline(" Cancel", "cancel_action", style="danger")]]
  try:
    await bot.send_file(uid, qr_file, caption=custom_emoji_text(caption), buttons=btns, force_document=False)
    try: os.remove(qr_file)
    except Exception: pass
    try: await event.delete()
    except Exception: pass
  except Exception as ex:
    logger.error(f"Failed to send deposit QR: {ex}")
    try: os.remove(qr_file)
    except Exception: pass
    deposit_input.pop(uid, None)
    await event.edit(custom_emoji_text(f"{P_NO} <b>Could not send the payment QR.</b> Please try again."), buttons=[[Button.inline("Back", "dep_menu_cb", style="primary")]])

async def confirm_purchase(event, country, year, price_str):
  uid = event.sender_id
  base_price = int(price_str)
  
  bal_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
  bal = bal_row[0] if bal_row else 0
  disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
  discount = disc_row[0] if disc_row else 0
  final_price = base_price if discount == 0 else int(base_price * (100 - discount) / 100)

  msg = (f"{P_CART} {P_FIRE} <b>Confirm Your Purchase</b> {P_STAR}\n\n"
      f"{P_FLAG} <b>Country:</b> {html.escape(country)}\n"
      f"{P_CAL} <b>Year:</b> {year}\n"
      f"{P_MONEY} <b>Final Price:</b> {P_INR}{final_price}\n\n"
      f"{P_CARD} <b>Your Balance:</b> {P_INR}{bal}\n\n"
      f"Do you want to proceed with this purchase? {P_ASST}")
  
  btns = [
    [Button.inline("Yes, Buy Now", f"buy_cf|{_country_token(country)}|{year}|{base_price}", style="success")],
    [Button.inline("No, Cancel", "cancel_action", style="danger")]
  ]
  await event.edit(custom_emoji_text(msg), buttons=btns)

async def process_purchase(event, country, year_str, price_str):
  uid, base_price = event.sender_id, int(price_str)

  disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
  discount = disc_row[0] if disc_row else 0
  final_price = base_price if discount == 0 else int(base_price * (100 - discount) / 100)

  async with get_user_lock(uid):
    row = cur.execute("SELECT phone, session_file, account_year, twofa FROM stock WHERE country_name LIKE ? AND account_year=? AND price=? AND available=1 LIMIT 1", (f"{country}%", int(year_str), base_price)).fetchone()

    if not row:
      return await safe_callback_answer(event, "Sold out! Another user just bought this account.", alert=True)
    
    phone, sess, actual_year, twofa_pass = row

    cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (final_price, uid, final_price))
    if cur.rowcount == 0:
      return await safe_callback_answer(event, f"Insufficient Balance! Need ₹{final_price}", alert=True)

    cur.execute("UPDATE stock SET available=0 WHERE phone=?", (phone,))
    db.commit()

  await event.edit(custom_emoji_text(f"{P_WAIT} <b>Fetching Number (+{phone})...</b>"))
  clean_sess = sess if not sess.endswith(".session") else sess[:-8]
  client = TelegramClient(clean_sess, API_ID, API_HASH)
  
  try:
    await client.connect()
    if not await client.is_user_authorized(): raise Exception("Session dead")
  except Exception:
    async with get_user_lock(uid):
      cur.execute("DELETE FROM stock WHERE phone=?", (phone,))
      cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (final_price, uid))
      db.commit()
    await client.disconnect()
    delete_session_files(sess)
    return await event.edit(custom_emoji_text(f"{P_NO} <b>Account Invalid.</b> Money refunded. Try buying another."))

  msg = (f"{P_YES} {P_ROCKET} <b>Order Active!</b>\n\n"
      f"{P_PHONE} <b>Phone:</b> <code>{phone}</code>\n"
      f"{P_FLAG} <b>Country:</b> {html.escape(country)}\n\n"
      f"{P_STAR} <b>INSTRUCTIONS:</b>\n"
      f"1. Open Telegram & Add Account\n"
      f"2. Enter the number above.\n"
      f"3. {P_WAIT} <b>Please wait!</b> The bot is actively listening for your OTP and will send it automatically.\n\n"
      f"<i>{P_WARN} Note: If no OTP is received within 10 minutes, the bot will auto-cancel and refund your balance automatically.</i>")
  
  sent_msg = await event.edit(custom_emoji_text(msg))
  
  active_orders[phone] = {
    'uid': uid,
    'client': client, 'sess': sess, 'start_time': time.time(), 
    'paid': False, 'price': final_price, 'country': country, 'year': actual_year, 
    'twofa': twofa_pass, 'msg_id': sent_msg.id
  }
  asyncio.create_task(auto_otp_task(phone))

async def auto_otp_task(phone):
  if phone not in active_orders: return
  
  order = active_orders[phone]
  client = order['client']
  start_time = order['start_time']
  uid = order['uid']
  msg_id = order['msg_id']
  
  while time.time() - start_time < 600:
    if phone not in active_orders: return 
    try:
      msgs = await client.get_messages(777000, limit=5)
      code = None
      for m in msgs:
        if m.date.timestamp() > start_time - 10: 
          if m.message and re.search(r'\b\d{5}\b', m.message) and "Login detected" not in m.message:
            code = re.search(r'\b\d{5}\b', m.message).group()
            break
      
      if code:
        if not order['paid']:
          order['paid'] = True
          async with get_user_lock(uid):
            cur.execute("INSERT INTO orders (user_id, country, year, price, phone, otp) VALUES (?,?,?,?,?,?)", (uid, order['country'], order['year'], order['price'], phone, code))
            cur.execute("DELETE FROM stock WHERE phone=?", (phone,))
            db.commit()
          
          await log_primary_purchase(uid, order['country'], order['price'], order['price'], order['year'], 1)
        
        twofa_text = f"{P_2FA} <b>2FA:</b> <code>{html.escape(order['twofa'])}</code>" if order['twofa'] != "None" else f"{P_2FA} <b>2FA:</b> <code>Disabled (No Password)</code>"
        msg_text = (f"{P_YES} {P_FIRE} <b>Latest OTP Fetched!</b> {P_PARTY}\n\n"
              f"{P_PHONE} <b>Phone:</b> <code>{phone}</code>\n"
              f"{P_FLAG} <b>Country:</b> {html.escape(order['country'])}\n"
              f"{P_OTP} <b>OTP:</b> <code>{code}</code>\n"
              f"{twofa_text}")
        
        btns = [
          [Button.inline("Get OTP Again", f"get_otp_again|{phone}", style="primary")],
          [Button.inline("Finish & Logout", f"logout_bot|{phone}", style="danger")]
        ]
        try: await bot.edit_message(uid, msg_id, msg_text, buttons=btns)
        except: await bot.send_message(custom_emoji_text(uid), msg_text, buttons=btns)
        return 
    except Exception: pass
    await asyncio.sleep(6) 
    
  if phone in active_orders and not active_orders[phone]['paid']:
    order = active_orders.pop(phone)
    try: await order['client'].disconnect()
    except: pass
    
    async with get_user_lock(uid):
      cur.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (order['price'], uid))
      cur.execute("UPDATE stock SET available=1 WHERE phone=?", (phone,))
      db.commit()
      
    try: 
      await bot.edit_message(uid, msg_id, f"{P_TIME} <b>Order Expired!</b>\nThe 10-minute limit for <code>{phone}</code> ran out. Your money ({P_INR}{order['price']}) has been automatically refunded.")
    except: pass

async def init_session_purchase(event, country, year, price_str):
  uid, price = event.sender_id, int(price_str)
  stock_row = cur.execute("SELECT COUNT(*) FROM stock WHERE country_name LIKE ? AND account_year=? AND price=? AND available=1", (f"{country}%", int(year), price)).fetchone()
  stock = stock_row[0] if stock_row else 0
  if stock == 0: return await safe_callback_answer(event, "Out of stock!", alert=True)
  
  session_buy_state[uid] = {'country': country, 'year': year, 'price': price, 'stock': stock}
  disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
  discount = disc_row[0] if disc_row else 0
  p_disp = price if discount == 0 else int(price * (100 - discount) / 100)
  
  msg = (f"{P_STORE} {P_ROCKET} <b>Buy {html.escape(country)} ({year}) Sessions</b>\n\n"
      f"{P_MONEY} <b>Price per session:</b> {P_INR}{p_disp}\n"
      f"{P_PKG} <b>Available Stock:</b> {stock}\n\n"
      f"Reply to this message with the <b>Number of Sessions</b> you want to buy.")
  await event.edit(custom_emoji_text(msg), buttons=[[Button.inline("Cancel", "cancel_action", style="danger")]])

async def process_bulk_sessions(event, uid, qty, state, final_cost):
  country, year, price = state['country'], int(state['year']), int(state['price'])
  await event.respond(custom_emoji_text(f"{P_WAIT} <b>Processing your sessions...</b>"))

  async with get_user_lock(uid):
    rows = cur.execute("SELECT phone, session_file, twofa, account_year FROM stock WHERE country_name LIKE ? AND account_year=? AND price=? AND available=1 LIMIT ?", (f"{country}%", year, price, qty)).fetchall()
    if len(rows) < qty:
      return await event.respond(custom_emoji_text(f"{P_NO} Stock changed during processing. Purchase Cancelled."))
    
    cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (final_cost, uid, final_cost))
    if cur.rowcount == 0:
      return await event.respond(custom_emoji_text(f"{P_NO} Insufficient Balance! Purchase Cancelled."))

    phones = [r[0] for r in rows]
    placeholders = ",".join("?" for _ in phones)
    cur.execute(f"UPDATE stock SET available=0 WHERE phone IN ({placeholders})", phones)
    
    price_per_acc = final_cost // qty
    for p in phones:
      cur.execute("INSERT INTO orders (user_id, country, price, phone, otp) VALUES (?,?,?,?,?)", (uid, country, price_per_acc, p, "SESSION_FILES"))
    db.commit()

  zip_name = f"sessions_{uid}_{int(time.time())}.zip"
  numbers_txt = ""

  try:
    with zipfile.ZipFile(zip_name, 'w') as zf:
      for phone, sess_file, twofa_pass, y in rows:
        base_s = sess_file if not sess_file.endswith(".session") else sess_file[:-8]
        for ext in ['.session', '.session-wal', '.session-shm', '.session-journal']:
          src = base_s + ext
          if os.path.exists(src): zf.write(src, os.path.basename(src))
        
        pass_text = twofa_pass if twofa_pass != "None" else "No_Password"
        numbers_txt += f"+{phone} | pass:{pass_text}\n"
      
      numbers_txt += "\n\nPurchased from @Freshtgsales\n"
      zf.writestr("numbers.txt", numbers_txt)
      
    caption = f"{P_YES} {P_PARTY} <b>Bulk Purchase Successful!</b>\n\n{P_FLAG} Country: {html.escape(country)}\n{P_PKG} Quantity: {qty}\n{P_CARD} Total Paid: {P_INR}{final_cost}\n\n<i>(Note: Sessions are safely provided, the bot does not keep them active)</i>"
    await bot.send_file(uid, zip_name, caption=custom_emoji_text(caption))
    await log_primary_purchase(uid, country, price, final_cost, year, qty)
  except Exception as e: await event.respond(custom_emoji_text(f"{P_WARN} Error creating zip: {e}"))
  finally:
    if os.path.exists(zip_name): os.remove(zip_name)

# ================= ADMIN PANEL =================
async def admin_panel_handler(event):
  uid = event.sender_id
  if not is_admin(uid): return
  
  status_text = "Bot is ON" if is_bot_online() else "Bot is OFF"
  btns = []
  
  if uid == ADMIN_ID or has_perm(uid, 'p_settings'):
    btns.append([Button.inline(f"Status: {status_text}", "adm_togglebot", style="primary")])
    
  r1 = []
  if uid == ADMIN_ID or has_perm(uid, 'p_add_stock'):
    r1.extend([
      Button.inline("Add Single Acc", "adm_addstock", style="success"), 
      Button.inline("Add ZIP", "adm_addzip", style="success")
    ])
  if r1: btns.append(r1)

  r2 = []
  if uid == ADMIN_ID or has_perm(uid, 'p_manage_stock'):
    r2.extend([
      Button.inline("Manage Stock", "adm_managestock", style="primary"), 
      Button.inline("Auto Price", "adm_autoprice", style="primary")
    ])
  if r2: btns.append(r2)

  btns.append([
    Button.inline(" SMM API", "adm_smm_api", style="primary"),
    Button.inline(" Categories", "adm_smm_cats", style="primary")
  ])
  btns.append([
    Button.inline(" Add Service", "adm_smm_addsrv", style="success"),
    Button.inline(" Bulk Add", "adm_smm_bulksrv", style="success"),
    Button.inline(" Manage", "adm_smm_managesrv", style="primary"),
    Button.inline(" Delete", "adm_smm_delsrv", style="danger")
  ])

  r3 = []
  if uid == ADMIN_ID or has_perm(uid, 'p_stats'):
    r3.extend([
      Button.inline("Statistics", "adm_stats", style="primary"), 
      Button.inline("Broadcast", "adm_bcast", style="primary")
    ])
    r3.append(Button.inline("User Info", "adm_userinfo", style="primary"))
  if r3: btns.append(r3)

  r4 = []
  if uid == ADMIN_ID or has_perm(uid, 'p_bal'):
    r4.extend([
      Button.inline("Change Balance", "adm_bal", style="primary"), 
      Button.inline("Ban User", "adm_ban", style="danger")
    ])
  if r4: btns.append(r4)

  r5 = []
  if uid == ADMIN_ID or has_perm(uid, 'p_settings'):
    r5.extend([
      Button.inline("Discount", "adm_discount", style="primary"), 
      Button.inline("USDT Rate", "adm_usdtrate", style="primary")
    ])
    btns.append(r5)
    btns.append([
      Button.inline("Support User", "adm_supporturl", style="primary"), 
      Button.inline("Support Channel", "adm_supportchan", style="primary")
    ])
    btns.append([
      Button.inline("Update Welcome Photo", "adm_update_welcome_photo", style="primary"),
      Button.inline("Change Logs Channel", "adm_changelogs", style="primary")
    ])
    btns.append([
      Button.inline("Backup Users", "adm_backupusr", style="primary"), 
      Button.inline("Restore Users", "adm_restoreusr", style="primary")
    ])
    btns.append([
      Button.inline("Channels", "adm_forcechannels", style="primary"),
      Button.inline("Payment Methods", "adm_paymentmethods", style="primary")
    ])
    btns.append([
      Button.inline("Redeem Codes", "adm_redeemcodes", style="primary"),
      Button.inline("Digital Shop", "adm_digitalshop", style="success")
    ])
    btns.append([Button.inline("FamPay / IMAP", "adm_fampayset", style="primary")])

  if uid == ADMIN_ID:
    btns.append([Button.inline("Manage Admins", "adm_manageadmins", style="danger")])

  await bot.send_message(event.chat_id, custom_emoji_text(f"{P_PC} <b>ADVANCED ADMIN DASHBOARD</b>"), buttons=btns)

async def manage_admins_menu(event):
  rows = cur.execute("SELECT user_id FROM admins").fetchall()
  msg = f"{P_USERS} <b>Manage Sub-Admins</b>\n\n"
  for r in rows: msg += f"{P_ACC} <code>{r[0]}</code>\n"
  btns = [
    [Button.inline("Add Admin", "adm_addadmin", style="success"), Button.inline("Edit Admin", "adm_editadminreq", style="primary")],
    [Button.inline("Back", "adm_adminmain", style="primary")]
  ]
  await event.edit(custom_emoji_text(msg), buttons=btns)

async def edit_admin_menu(event, target_id):
  row = cur.execute("SELECT p_add_stock, p_manage_stock, p_stats, p_bal, p_settings FROM admins WHERE user_id=?", (target_id,)).fetchone()
  if not row: return await safe_callback_answer(event, "Admin not found", alert=True)
  p = ["Yes" if x==1 else "No" for x in row]
  
  btns = [
    [Button.inline(f"Add Stock: {p[0]}", f"adm_tglperm|{target_id}|p_add_stock", style="primary")],
    [Button.inline(f"Manage Stock: {p[1]}", f"adm_tglperm|{target_id}|p_manage_stock", style="primary")],
    [Button.inline(f"Stats & Bcast: {p[2]}", f"adm_tglperm|{target_id}|p_stats", style="primary")],
    [Button.inline(f"Bal & Users: {p[3]}", f"adm_tglperm|{target_id}|p_bal", style="primary")],
    [Button.inline(f"Settings: {p[4]}", f"adm_tglperm|{target_id}|p_settings", style="primary")],
    [Button.inline("Remove Admin", f"adm_deladmin|{target_id}", style="danger")],
    [Button.inline("Back", "adm_manageadmins", style="primary")]
  ]
  await event.edit(custom_emoji_text(f"{P_DOC} <b>Editing Admin:</b> <code>{target_id}</code>"), buttons=btns)

async def send_manage_stock_page(event, page):
  limit = 10
  offset = (page - 1) * limit
  rows = cur.execute("SELECT DISTINCT country_name FROM stock ORDER BY country_name").fetchall()
  total = len(rows)
  countries = rows[offset:offset+limit]
  
  btns = []
  for (c,) in countries: 
    btns.append([Button.inline(f"{html.escape(c)}", f"adm_msc|{c}", style="primary")])
  
  nav = []
  if page > 1: nav.append(Button.inline("Prev", f"adm_mspg|{page-1}", style="primary"))
  if offset + limit < total: nav.append(Button.inline("Next", f"adm_mspg|{page+1}", style="primary"))
  if nav: btns.append(nav)
  btns.append([Button.inline("Back", "adm_adminmain", style="primary")])
  await event.edit(custom_emoji_text(f"{P_DOC} <b>Manage Stock</b> (Page {page})\nSelect a country to edit its properties:"), buttons=btns)

async def send_manage_stock_country(event, c_name):
  years = cur.execute("SELECT DISTINCT account_year FROM stock WHERE country_name=? ORDER BY account_year DESC", (c_name,)).fetchall()
  btns = [
    [Button.inline("Edit Country Name", f"adm_msedit|name|{c_name}", style="primary")],
    [Button.inline("Edit Common Price (All Years)", f"adm_msedit|cprice|{c_name}", style="primary")]
  ]
  y_btns = []
  for (y,) in years: 
    y_btns.append(Button.inline(f"{y}", f"adm_msedit|yprice|{c_name}|{y}", style="primary"))
  
  for i in range(0, len(y_btns), 3): btns.append(y_btns[i:i+3])
  btns.append([Button.inline("Back", "adm_mspg|1", style="primary")])
  await event.edit(custom_emoji_text(f"{P_GLOBE} <b>Managing: {html.escape(c_name)}</b>\nSelect an option to edit:"), buttons=btns)

async def send_autoprice_page(event, page):
  limit = 10
  offset = (page - 1) * limit
  c_list = set([c for c in COUNTRY_CODES.values()])
  db_countries = cur.execute("SELECT DISTINCT country_name FROM stock").fetchall()
  for (c,) in db_countries: c_list.add(c)
  
  custom_countries = cur.execute("SELECT DISTINCT name FROM custom_countries").fetchall()
  for (c,) in custom_countries: c_list.add(c)

  c_list = sorted(list(c_list))
  total = len(c_list)
  countries = c_list[offset:offset+limit]
  
  btns = []
  for c in countries: 
    btns.append([Button.inline(f"{html.escape(c)}", f"adm_apc|{c}", style="primary")])
    
  nav = []
  if page > 1: nav.append(Button.inline("Prev", f"adm_appg|{page-1}", style="primary"))
  if offset + limit < total: nav.append(Button.inline("Next", f"adm_appg|{page+1}", style="primary"))
  if nav: btns.append(nav)
  btns.append([Button.inline("Add Custom Country", "adm_ap_add_country", style="success")])
  btns.append([Button.inline("Back", "adm_adminmain", style="primary")])
  await event.edit(custom_emoji_text(f"{P_ASST} <b>Auto Price Setup</b> (Page {page})\nSelect a country to set fixed prices:"), buttons=btns)

async def send_autoprice_country(event, c_name):
  btns = [[Button.inline("Set Common Price", f"adm_apset|{c_name}|Common", style="primary")]]
  y_btns = []
  for y in range(2024, 1999, -1): 
    y_btns.append(Button.inline(f"{y}", f"adm_apset|{c_name}|{y}", style="primary"))
  for i in range(0, len(y_btns), 4): btns.append(y_btns[i:i+4])
  btns.append([Button.inline("Back", "adm_appg|1", style="primary")])
  await event.edit(custom_emoji_text(f"{P_GLOBE} <b>Auto Price: {html.escape(c_name)}</b>\nSelect 'Common' for default price, or specific years:"), buttons=btns)

async def admin_actions(event):
  data_full = event.data.decode()
  if not data_full.startswith("adm_"): return
  uid = event.sender_id
  action_data = data_full[4:]
  chat = event.chat_id
  
  if action_data == "adminmain":
    await event.delete()
    class FakeEvent: chat_id = chat; sender_id = uid
    return await admin_panel_handler(FakeEvent())

  if action_data == "togglebot" and has_perm(uid, 'p_settings'):
    new_status = 'off' if is_bot_online() else 'on'
    cur.execute("UPDATE settings SET value=? WHERE key='bot_status'", (new_status,))
    db.commit()
    await safe_callback_answer(event, f"Bot turned {new_status.upper()}", alert=True)
    class FakeEvent: chat_id = chat; sender_id = uid
    await admin_panel_handler(FakeEvent())
    await event.delete()
    return

  elif action_data == "forcechannels":
    rows = cur.execute("SELECT id, channel_id, title FROM force_channels").fetchall()
    msg = f"{P_USERS} <b>Manage Force Channels (Unlimited)</b>\n\n"
    if not rows: msg += "No force channels added yet."
    else:
      for r in rows: msg += f"ID: {r[0]} | Title: {html.escape(str(r[2]))} | <code>{r[1]}</code>\n"
      
    btns = [
      [Button.inline("Add Channel", "adm_add_fchan", style="success")],
      [Button.inline("Remove Channel", "adm_del_fchan", style="danger")],
      [Button.inline("Back to Admin", "adm_adminmain", style="primary")]
    ]
    return await event.edit(custom_emoji_text(msg), buttons=btns)

  elif action_data == "paymentmethods" and has_perm(uid, 'p_settings'):
    ae = payment_enabled('fampay_enabled'); me = payment_enabled('manual_enabled')
    msg=(f"{P_CARD} <b>Payment Methods</b>\n\n"
       f"FamPay Automatic: <b>{'ON' if ae else 'OFF'}</b>\n"
       f"UPI Manual: <b>{'ON' if me else 'OFF'}</b>\n\n"
       f"Automatic UPI: <code>{html.escape(get_fampay_upi())}</code>\n"
       f"Manual UPI: <code>{html.escape(get_manual_upi())}</code>")
    btns=[[Button.inline(f"FamPay Automatic: {'ON' if ae else 'OFF'}","adm_toggle_fampay",style="success" if not ae else "danger")],
       [Button.inline(f"UPI Manual: {'ON' if me else 'OFF'}","adm_toggle_manual",style="success" if not me else "danger")],
       [Button.inline("Set FamPay UPI & Name","adm_set_auto_upi",style="primary")],
       [Button.inline("Set Manual UPI & Name","adm_set_manual_upi",style="primary")],
       [Button.inline("Back to Admin","adm_adminmain",style="primary")]]
    return await event.edit(custom_emoji_text(msg),buttons=btns)

  elif action_data == "toggle_fampay" and has_perm(uid, 'p_settings'):
    set_setting('fampay_enabled','off' if payment_enabled('fampay_enabled') else 'on')
    return await event.edit(custom_emoji_text("FamPay Automatic setting updated."),buttons=[[Button.inline("Back to Payment Methods","adm_paymentmethods",style="primary")]])

  elif action_data == "toggle_manual" and has_perm(uid, 'p_settings'):
    set_setting('manual_enabled','off' if payment_enabled('manual_enabled') else 'on')
    return await event.edit(custom_emoji_text("UPI Manual setting updated."),buttons=[[Button.inline("Back to Payment Methods","adm_paymentmethods",style="primary")]])

  elif action_data in ("set_auto_upi","set_manual_upi") and has_perm(uid, 'p_settings'):
    is_auto = action_data == "set_auto_upi"
    await event.delete()
    async with bot.conversation(chat, timeout=300) as conv:
      async def get_reply(txt):
        await conv.send_message(custom_emoji_text(txt+"\n\n<i>(Type /cancel to abort)</i>")); r=await conv.get_response()
        if (r.text or '').strip().lower()=='/cancel': raise ValueError
        return r
      try:
        upi=(await get_reply("Enter UPI ID:")).text.strip(); name=(await get_reply("Enter Payee Name:")).text.strip()
        if not re.match(r"^[A-Za-z0-9._-]+@[A-Za-z0-9._-]+$",upi): return await conv.send_message("Invalid UPI ID.")
        prefix='fampay' if is_auto else 'manual'
        set_setting(prefix+'_upi',upi); set_setting(prefix+'_name',name)
        await conv.send_message(custom_emoji_text("Payment UPI settings saved successfully."))
      except ValueError: await conv.send_message("Cancelled.")
    return

  elif action_data == "fampayset":
    upi = get_fampay_upi()
    name = get_fampay_name()
    msg = (f"{P_CARD} <b>FamPay / UPI & IMAP Settings</b>\n\n"
        f"Current UPI ID: <code>{upi}</code>\n"
        f"Payee Name: <code>{name}</code>\n\n"
        f"Click below to update UPI ID, Payee Name, or IMAP configuration for automatic verification.")
    btns = [
      [Button.inline("Change FamPay UPI & Name", "adm_set_auto_upi", style="primary")],
      [Button.inline("Change Manual UPI & Name", "adm_set_manual_upi", style="primary")],
      [Button.inline("Configure IMAP (Gmail)", "adm_set_imap", style="primary")],
      [Button.inline("Payment Methods", "adm_paymentmethods", style="primary")],
      [Button.inline("Back to Admin", "adm_adminmain", style="primary")]
    ]
    return await event.edit(custom_emoji_text(msg), buttons=btns)

  elif action_data == "smm_cats":
    rows = cur.execute("SELECT id, name FROM smm_categories").fetchall()
    msg = f"{P_FOLDER} <b>Manage SMM Categories</b>\n\n"
    if not rows: msg += "No categories created yet."
    else:
      for r in rows: msg += f"ID: {r[0]} | Name: {html.escape(r[1])}\n"
    btns = [
      [Button.inline(" Create Category", "adm_smm_addcat", style="success")],
      [Button.inline(" Remove Category", "adm_smm_delcat", style="danger")],
      [Button.inline(" Back to Admin", "adm_adminmain", style="primary")]
    ]
    return await event.edit(custom_emoji_text(msg), buttons=btns)

  elif action_data == "smm_managesrv":
    rows = cur.execute("SELECT service_id, name FROM smm_services LIMIT 15").fetchall()
    if not rows: return await safe_callback_answer(event, "No services added yet.", alert=True)
    msg = f"{P_GEAR} <b>Manage SMM Service</b>\nSelect a service to edit:"
    btns = []
    for sid, sname in rows:
      btns.append([Button.inline(f"Edit: {sname} ({sid})", f"adm_smm_editsrv|{sid}", style="primary")])
    btns.append([Button.inline(" Back", "adm_adminmain", style="primary")])
    return await event.edit(custom_emoji_text(msg), buttons=btns)

  elif action_data.startswith("smm_editsrv|"):
    sid = int(action_data.split("|")[1])
    await event.delete()
    class FakeEvent: chat_id = chat; sender_id = uid
    async with bot.conversation(chat, timeout=600) as conv:
      async def get_reply(txt):
        await conv.send_message(custom_emoji_text(txt + "\n\n<i>(Type /cancel to abort)</i>"))
        resp = await conv.get_response()
        if resp.text == "/cancel": raise ValueError("Cancelled")
        return resp
      try:
        edit_msg = (f"{P_GEAR} <b>Editing Service ID: {sid}</b>\n"
              f"1. Edit Name\n2. Edit Description\n3. Edit Price (Rate)\n4. Edit Category\n\n"
              f"Reply with option number (1, 2, 3, or 4):")
        opt = (await get_reply(edit_msg)).text.strip()
        if opt == '1':
          new_name = (await get_reply("Enter new Service Name:")).text.strip()
          cur.execute("UPDATE smm_services SET name=? WHERE service_id=?", (new_name, sid))
          db.commit()
          await conv.send_message(custom_emoji_text(f"{P_YES} Service Name updated successfully!"))
        elif opt == '2':
          new_desc = (await get_reply("Enter new Description:")).text.strip()
          cur.execute("UPDATE smm_services SET description=? WHERE service_id=?", (new_desc, sid))
          db.commit()
          await conv.send_message(custom_emoji_text(f"{P_YES} Service Description updated successfully!"))
        elif opt == '3':
          new_rate = float((await get_reply("Enter new Price (Rate per 1k):")).text.strip())
          cur.execute("UPDATE smm_services SET rate=? WHERE service_id=?", (new_rate, sid))
          db.commit()
          await conv.send_message(custom_emoji_text(f"{P_YES} Service Price updated successfully!"))
        elif opt == '4':
          cats = cur.execute("SELECT id, name FROM smm_categories").fetchall()
          c_txt = "Select new Category ID:\n"
          for c in cats: c_txt += f"ID: {c[0]} - {c[1]}\n"
          new_cid = int((await get_reply(c_txt)).text.strip())
          cur.execute("UPDATE smm_services SET category_id=? WHERE service_id=?", (new_cid, sid))
          db.commit()
          await conv.send_message(custom_emoji_text(f"{P_YES} Service Category updated successfully!"))
        else:
          await conv.send_message(custom_emoji_text("Invalid option selected."))
      except ValueError: await conv.send_message(custom_emoji_text(f"{P_NO} Cancelled."))
      except Exception as ex: await conv.send_message(custom_emoji_text(f"{P_NO} Error: {ex}"))
    return

  elif action_data == "smm_delsrv":
    rows = cur.execute("SELECT service_id, name FROM smm_services LIMIT 15").fetchall()
    if not rows: return await safe_callback_answer(event, "No services added yet.", alert=True)
    msg = f"{P_NO} <b>Remove Service</b>\nSelect service ID to delete:"
    btns = []
    for sid, sname in rows:
      btns.append([Button.inline(f"Del: {sname} ({sid})", f"adm_smm_dsrv|{sid}", style="danger")])
    btns.append([Button.inline(" Back", "adm_adminmain", style="primary")])
    return await event.edit(custom_emoji_text(msg), buttons=btns)

  elif action_data.startswith("smm_dsrv|"):
    sid = int(action_data.split("|")[1])
    cur.execute("DELETE FROM smm_services WHERE service_id=?", (sid,))
    db.commit()
    await safe_callback_answer(event, "Service Removed Successfully!", alert=True)
    class FakeEvent: chat_id = chat; sender_id = uid
    return await admin_panel_handler(FakeEvent())

  elif action_data == "redeemcodes" and has_perm(uid, 'p_settings'):
    rows=cur.execute("SELECT code,amount,max_users,used_count,active FROM redeem_codes ORDER BY created_date DESC LIMIT 20").fetchall()
    msg=f"{P_GIFT} <b>Redeem Codes</b>\n\n"
    for code,amount,mx,used,active in rows: msg += f"<code>{html.escape(code)}</code> - ₹{amount} - {used}/{mx} - {'ON' if active else 'OFF'}\n"
    if not rows: msg += "No redeem codes created yet.\n"
    btns=[[Button.inline("Create Code","adm_redeem_add",style="success")],[Button.inline("Remove Code","adm_redeem_remove",style="danger")],[Button.inline("Back to Admin","adm_adminmain",style="primary")]]
    return await event.edit(custom_emoji_text(msg),buttons=btns)

  elif action_data in ("redeem_add","redeem_remove") and has_perm(uid, 'p_settings'):
    await event.delete()
    async with bot.conversation(chat, timeout=300) as conv:
      async def get_reply(txt):
        await conv.send_message(custom_emoji_text(txt+"\n\n<i>(Type /cancel to abort)</i>")); r=await conv.get_response()
        if (r.text or '').strip().lower()=='/cancel': raise ValueError
        return r
      try:
        if action_data == 'redeem_add':
          code=(await get_reply("Enter code (e.g. AKOP):")).text.strip().upper()
          amount=int((await get_reply("Enter amount in INR (e.g. 5):")).text.strip())
          max_users=int((await get_reply("Enter max users (e.g. 10):")).text.strip())
          if not re.fullmatch(r"[A-Z0-9_-]{3,40}",code) or amount<=0 or max_users<=0: raise ValueError
          cur.execute("INSERT OR REPLACE INTO redeem_codes(code,amount,max_users,used_count,created_by,active) VALUES(?,?,?,?,?,1)",(code,amount,max_users,0,uid)); db.commit()
          await conv.send_message(custom_emoji_text(f"{P_YES} <b>Redeem Code Created</b>\n\n<code>{code}</code> {amount} {max_users}"))
        else:
          code=(await get_reply("Enter code to remove:")).text.strip().upper()
          cur.execute("UPDATE redeem_codes SET active=0 WHERE code=?",(code,)); db.commit()
          await conv.send_message(custom_emoji_text(f"{P_YES} Code <code>{html.escape(code)}</code> removed."))
      except ValueError: await conv.send_message("Invalid input or cancelled.")
    return

  elif action_data == "digitalshop" and has_perm(uid, 'p_settings'):
    return await digital_shop_admin_menu(event)

  elif action_data in ("digital_add","digital_remove") and has_perm(uid, 'p_settings'):
    await event.delete()
    async with bot.conversation(chat, timeout=600) as conv:
      async def get_reply(txt):
        await conv.send_message(custom_emoji_text(txt+"\n\n<i>(Type /cancel to abort)</i>")); r=await conv.get_response()
        if (r.text or '').strip().lower()=='/cancel': raise ValueError
        return r
      try:
        if action_data == 'digital_add':
          name=(await get_reply("Enter Product Name:")).text.strip()
          desc=(await get_reply("Enter Product Description:")).text.strip()
          price=int((await get_reply("Enter Product Price (₹):")).text.strip())
          if price<=0: raise ValueError

          # Preview image is optional. Admin can simply reply with `skip`.
          preview = await get_reply("Send product preview photo/screenshot now, or type <b>skip</b> to continue without a preview:")
          preview_path = ''
          preview_file_id = ''
          preview_text = (preview.text or '').strip().lower()
          if preview_text not in ('skip', 'none', 'no'):
            if not preview.photo:
              return await conv.send_message(custom_emoji_text(f"{P_NO} Please send a photo/screenshot or type <b>skip</b>."))
            os.makedirs('digital_shop/previews',exist_ok=True)
            preview_path = await bot.download_media(preview, file='digital_shop/previews/') or ''
            preview_file_id = str(preview.photo.id)

          # The actual product file remains required so Buy Now can always deliver something.
          product_file = await get_reply("Now send the <b>product file</b> to deliver after purchase (document/file/photo).")
          if not getattr(product_file, 'media', None):
            return await conv.send_message(custom_emoji_text(f"{P_NO} Product file is required. Please send the file."))
          os.makedirs('digital_shop/files',exist_ok=True)
          file_path = await bot.download_media(product_file, file='digital_shop/files/') or ''
          if not file_path or not os.path.isfile(file_path):
            return await conv.send_message(custom_emoji_text(f"{P_NO} Product file could not be saved. Please try again."))

          cur.execute("INSERT INTO digital_products(name,description,price,photo_file_id,photo_path,file_path) VALUES(?,?,?,?,?,?)",(name,desc,price,preview_file_id,preview_path,file_path))
          db.commit()
          preview_status = 'No preview' if not preview_path else 'Preview added'
          await conv.send_message(custom_emoji_text(f"{P_YES} Product <b>{html.escape(name)}</b> added successfully.\n\n{preview_status}\nDelivery file saved successfully."))
        else:
          pid=int((await get_reply("Enter Product ID to remove:")).text.strip())
          cur.execute("UPDATE digital_products SET active=0 WHERE id=?",(pid,)); db.commit()
          await conv.send_message(custom_emoji_text(f"{P_YES} Product #{pid} removed from the shop."))
      except ValueError: await conv.send_message("Invalid input or cancelled.")
      except Exception as ex: await conv.send_message(custom_emoji_text(f"{P_NO} Error: {html.escape(str(ex))}"))
    return

  elif action_data == "stats" and has_perm(uid, 'p_stats'):
    u_row = cur.execute("SELECT COUNT(*) FROM users").fetchone()
    u = u_row[0] if u_row else 0
    s_row = cur.execute("SELECT COUNT(*) FROM stock WHERE available=1").fetchone()
    s = s_row[0] if s_row else 0
    bal_row = cur.execute("SELECT SUM(balance) FROM users").fetchone()
    total_bal = bal_row[0] if bal_row and bal_row[0] else 0
    o_row = cur.execute("SELECT COUNT(*), SUM(price) FROM orders").fetchone()
    total_orders = o_row[0] if o_row else 0
    total_spent = o_row[1] if o_row and o_row[1] else 0
    
    msg = (f"{P_STATS} <b>ADVANCED STATS</b>\n\n{P_USERS} <b>Total Users:</b> {u}\n{P_PKG} <b>Accounts in Stock:</b> {s}\n\n"
        f"{P_CARD} <b>Overall Users Balance:</b> {P_INR}{total_bal}\n"
        f"{P_CART} <b>Total Accounts Sold:</b> {total_orders}\n{P_USDT} <b>Overall Sales Amount:</b> {P_INR}{total_spent}")
    return await event.edit(custom_emoji_text(msg), buttons=[[Button.inline("Back", "adm_adminmain", style="primary")]])

  elif action_data == "manageadmins" and uid == ADMIN_ID:
    return await manage_admins_menu(event)

  elif action_data.startswith("tglperm|") and uid == ADMIN_ID:
    _, t_id, p_name = action_data.split("|")
    cur.execute(f"UPDATE admins SET {p_name} = CASE WHEN {p_name}=1 THEN 0 ELSE 1 END WHERE user_id=?", (t_id,))
    db.commit()
    return await edit_admin_menu(event, t_id)
    
  elif action_data.startswith("deladmin|") and uid == ADMIN_ID:
    t_id = action_data.split("|")[1]
    cur.execute("DELETE FROM admins WHERE user_id=?", (t_id,))
    db.commit()
    await safe_callback_answer(event, "Admin Removed", alert=True)
    return await manage_admins_menu(event)

  elif action_data == "managestock" and has_perm(uid, 'p_manage_stock'): return await send_manage_stock_page(event, 1)
  elif action_data.startswith("mspg|") and has_perm(uid, 'p_manage_stock'): return await send_manage_stock_page(event, int(action_data.split("|")[1]))
  elif action_data.startswith("msc|") and has_perm(uid, 'p_manage_stock'): return await send_manage_stock_country(event, action_data.split("|")[1])
  elif action_data == "autoprice" and has_perm(uid, 'p_manage_stock'): return await send_autoprice_page(event, 1)
  elif action_data.startswith("appg|") and has_perm(uid, 'p_manage_stock'): return await send_autoprice_page(event, int(action_data.split("|")[1]))
  elif action_data.startswith("apc|") and has_perm(uid, 'p_manage_stock'): return await send_autoprice_country(event, action_data.split("|")[1])
    
  elif action_data == "backupusr" and has_perm(uid, 'p_settings'):
    cur.execute("SELECT * FROM users")
    with open("users_backup.csv", "w", newline="", encoding="utf-8") as f:
      w = csv.writer(f); w.writerow([i[0] for i in cur.description]); w.writerows(cur.fetchall())
    await bot.send_file(chat, "users_backup.csv", caption=custom_emoji_text(f"{P_USERS} <b>Users Backup CSV</b>"))
    os.remove("users_backup.csv")
    return await safe_callback_answer(event, "Backup Generated!", alert=True)

  async with bot.conversation(chat, timeout=600) as conv:
    async def get_reply(txt):
      await conv.send_message(custom_emoji_text(txt + "\n\n<i>(Type /cancel to abort)</i>"))
      resp = await conv.get_response()
      if resp.text == "/cancel": raise ValueError("Cancelled")
      return resp

    try:
      if action_data == "smm_api" and has_perm(uid, 'p_settings'):
        url_resp = (await get_reply(f"{P_GEAR} <b>Enter SMM API URL</b> (e.g., https://growtak.com/api/v2):")).text.strip()
        key_resp = (await get_reply(f"{P_KEY} <b>Enter SMM API Key:</b>")).text.strip()
        clean_u = clean_html_url(url_resp)
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('smm_api_url', ?)", (clean_u,))
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('smm_api_key', ?)", (key_resp,))
        db.commit()
        await conv.send_message(custom_emoji_text(f"{P_YES} <b>SMM API credentials updated successfully!</b>\nClean URL: <code>{clean_u}</code>"))

      elif action_data == "smm_addcat" and has_perm(uid, 'p_manage_stock'):
        cname = (await get_reply(f"{P_FOLDER} <b>Enter Category Name</b> (e.g., Telegram):")).text.strip()
        cur.execute("INSERT INTO smm_categories (name) VALUES (?)", (cname,))
        db.commit()
        await conv.send_message(custom_emoji_text(f"{P_YES} Category <b>{html.escape(cname)}</b> created successfully!"))

      elif action_data == "smm_delcat" and has_perm(uid, 'p_manage_stock'):
        rows = cur.execute("SELECT id, name FROM smm_categories").fetchall()
        if not rows: return await conv.send_message(custom_emoji_text("No categories found."))
        txt = "Reply with Category ID to delete:\n"
        for r in rows: txt += f"ID: {r[0]} - {r[1]}\n"
        cid = int((await get_reply(txt)).text.strip())
        cur.execute("DELETE FROM smm_categories WHERE id=?", (cid,))
        cur.execute("DELETE FROM smm_services WHERE category_id=?", (cid,))
        db.commit()
        await conv.send_message(custom_emoji_text(f"{P_YES} Category and its services removed!"))

      elif action_data == "smm_bulksrv" and has_perm(uid, 'p_manage_stock'):
        cats = cur.execute("SELECT id, name FROM smm_categories").fetchall()
        if not cats: return await conv.send_message(custom_emoji_text("Please create a category first using 'Categories' menu."))
        
        cat_text = "Select Category ID for bulk services:\n"
        for c in cats: cat_text += f"ID: {c[0]} - {c[1]}\n"
        cid = int((await get_reply(cat_text)).text.strip())
        
        ids_resp = (await get_reply(f"{P_ID} <b>Enter Service IDs (separated by space, comma or newline):</b>\n<i>Example: 2222 6478 22461</i>")).text.strip()
        service_ids = re.findall(r'\d+', ids_resp)
        
        if not service_ids:
          return await conv.send_message(custom_emoji_text(f"{P_NO} No valid Service IDs found."))

        api_url, api_key = get_smm_api_config()
        if not api_url or not api_key:
          return await conv.send_message(custom_emoji_text(f"{P_NO} SMM API URL or Key not configured."))

        await conv.send_message(custom_emoji_text(f"{P_WAIT} <b>Fetching services from SMM API...</b>"))
        services_data = fetch_smm_services_from_api(api_url, api_key)
        
        api_services_dict = {}
        if services_data:
          if isinstance(services_data, dict):
            for k, v in services_data.items():
              if isinstance(v, dict):
                s_id = str(v.get('service', v.get('service_id', v.get('id', k))))
                api_services_dict[s_id] = v
              else:
                api_services_dict[str(k)] = {'name': str(v), 'rate': 0.0, 'min': 10, 'max': 10000}
          elif isinstance(services_data, list):
            for s in services_data:
              if isinstance(s, dict):
                s_id = str(s.get('service', s.get('service_id', s.get('id', ''))))
                if s_id: api_services_dict[s_id] = s

        markup_pct = float((await get_reply(f"{P_RATE} <b>Enter Profit Margin / Markup %</b> (e.g., enter <code>10</code> for 10% profit markup):")).text.strip() or 0)

        success_count = 0
        report_msg = f"{P_PKG} <b>Bulk Add Report ({markup_pct}% Markup):</b>\n\n"

        for sid_str in service_ids:
          sid_int = int(sid_str)
          target_srv = api_services_dict.get(str(sid_int))
          
          if target_srv and isinstance(target_srv, dict):
            sname = target_srv.get('name', f'Service {sid_int}')
            api_rate = float(target_srv.get('rate', 0.0))
            smin = int(target_srv.get('min', 10))
            smax = int(target_srv.get('max', 10000))
            sdesc = target_srv.get('description', '')
            
            srate = round(api_rate * (1 + markup_pct / 100.0), 2)
            
            cur.execute("INSERT OR REPLACE INTO smm_services (service_id, category_id, name, rate, min, max, description) VALUES (?,?,?,?,?,?,?)",
                  (sid_int, cid, sname, srate, smin, smax, sdesc))
            success_count += 1
            report_msg += f" ID {sid_int}: {html.escape(sname)} (₹{srate})\n"
          else:
            sname = f"Service {sid_int}"
            srate = 100.0
            smin, smax = 10, 10000
            sdesc = "Added via bulk"
            cur.execute("INSERT OR REPLACE INTO smm_services (service_id, category_id, name, rate, min, max, description) VALUES (?,?,?,?,?,?,?)",
                  (sid_int, cid, sname, srate, smin, smax, sdesc))
            success_count += 1
            report_msg += f" ID {sid_int}: Added with default values.\n"

        db.commit()
        report_msg += f"\n <b>Total Added:</b> {success_count} services successfully!"
        await conv.send_message(custom_emoji_text(report_msg))

      elif action_data == "smm_addsrv" and has_perm(uid, 'p_manage_stock'):
        cats = cur.execute("SELECT id, name FROM smm_categories").fetchall()
        if not cats: return await conv.send_message(custom_emoji_text("Please create a category first."))
        
        cat_text = "Select Category ID for the service:\n"
        for c in cats: cat_text += f"ID: {c[0]} - {c[1]}\n"
        cid = int((await get_reply(cat_text)).text.strip())
        
        sid_input = int((await get_reply(f"{P_ID} <b>Enter SMM Service ID:</b>")).text.strip())
        
        api_url, api_key = get_smm_api_config()
        target_srv = None
        
        if api_url and api_key:
          await conv.send_message(custom_emoji_text(f"{P_WAIT} <b>Fetching service details from SMM API...</b>"))
          services_data = fetch_smm_services_from_api(api_url, api_key)
          
          if services_data:
            if isinstance(services_data, dict):
              for k, v in services_data.items():
                if str(k) == str(sid_input) or (isinstance(v, dict) and str(v.get('service', v.get('service_id', v.get('id', '')))) == str(sid_input)):
                  target_srv = v if isinstance(v, dict) else {'name': str(v)}
                  target_srv['service'] = sid_input
                  break
            elif isinstance(services_data, list):
              for s in services_data:
                if isinstance(s, dict) and str(s.get('service', s.get('service_id', s.get('id', '')))) == str(sid_input):
                  target_srv = s
                  break

        if target_srv and isinstance(target_srv, dict):
          sname = target_srv.get('name', f'Service {sid_input}')
          api_rate = float(target_srv.get('rate', 0.0))
          smin = int(target_srv.get('min', 10))
          smax = int(target_srv.get('max', 10000))
          sdesc = target_srv.get('description', '')
          await conv.send_message(custom_emoji_text(f"{P_YES} <b>API details fetched successfully!</b>\n- Name: {html.escape(sname)}\n- Rate: ₹{api_rate}\n- Min: {smin} | Max: {smax}"))
        else:
          await conv.send_message(custom_emoji_text(f"{P_WARN} Auto-fetch failed due to API/Cloudflare. Please enter details manually:"))
          sname = (await get_reply("Enter Service Name:")).text.strip()
          api_rate = float((await get_reply("Enter API Rate per 1000 (₹):")).text.strip())
          smin = int((await get_reply("Enter Min Quantity:")).text.strip())
          smax = int((await get_reply("Enter Max Quantity:")).text.strip())
          sdesc = (await get_reply("Enter Description (or type 'none'):")).text.strip()

        markup_pct = float((await get_reply(f"{P_RATE} <b>API Rate:</b> ₹{api_rate}\n\n<b>Enter Profit Margin / Markup % (e.g., 10 for 10%):</b>")).text.strip() or 0)
        srate = round(api_rate * (1 + markup_pct / 100.0), 2)

        cur.execute("INSERT OR REPLACE INTO smm_services (service_id, category_id, name, rate, min, max, description) VALUES (?,?,?,?,?,?,?)",
              (sid_input, cid, sname, srate, smin, smax, sdesc))
        db.commit()
        await conv.send_message(custom_emoji_text(f"{P_YES} <b>Service Added Successfully!</b>\n\n- ID: <code>{sid_input}</code>\n- Name: {html.escape(sname)}\n- Rate/1k: ₹{srate} ({markup_pct}% markup)\n- Min: {smin} | Max: {smax}"))

      elif action_data == "update_welcome_photo" and has_perm(uid, 'p_settings'):
        resp = await get_reply(f"{P_EYE} <b>Send new welcome photo (image):</b>")
        if resp.photo:
          await bot.download_media(resp, "23593.jpg")
          await conv.send_message(custom_emoji_text(f"{P_YES} <b>Welcome photo updated successfully!</b>"))
        else:
          await conv.send_message(custom_emoji_text(f"{P_NO} This is not a valid photo. Try again."))

      elif action_data == "changelogs" and has_perm(uid, 'p_settings'):
        new_ch = (await get_reply(f"{P_GLOBE} <b>Enter new Logs Channel ID (e.g., -100xxxxxxxxxx):</b>")).text.strip()
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('log_channel_id', ?)", (new_ch,))
        db.commit()
        await conv.send_message(custom_emoji_text(f"{P_YES} <b>Logs Channel ID updated successfully:</b> <code>{new_ch}</code>"))

      elif action_data == "add_fchan":
        title = (await get_reply("Enter Channel Title/Name (e.g., Updates Channel):")).text.strip()
        ch_id = (await get_reply("Enter Channel Chat ID (e.g., -100xxxxxxxxxx):")).text.strip()

        # Never save a force channel until the bot itself is confirmed as admin/creator.
        bot_admin_ok, admin_reason = await _is_bot_channel_admin(ch_id)
        if not bot_admin_ok:
          await conv.send_message(custom_emoji_text(
            f"{P_NO} <b>Channel verification failed.</b>\n\n"
            f"<b>Reason:</b> {html.escape(admin_reason)}\n\n"
            "Add the bot to that channel as an <b>Administrator</b>, then try again."
          ))
          return

        # No manual invite URL is required. Telegram creates the invite link for
        # this channel and that generated link is stored for the Join button.
        await conv.send_message(custom_emoji_text(
          "Bot admin verified successfully.\n\n"
          "Creating the channel invite link automatically..."
        ))
        invite_ok, inv, invite_reason = await _create_force_channel_invite(ch_id)
        if not invite_ok:
          await conv.send_message(custom_emoji_text(
            f"{P_NO} <b>Invite link creation failed.</b>\n\n"
            f"<b>Reason:</b> {html.escape(invite_reason)}\n\n"
            "Make sure the bot has permission to <b>Invite Users via Link</b> in this channel and try again."
          ))
          return

        # Replace an existing entry for the same channel instead of creating duplicates.
        cur.execute("DELETE FROM force_channels WHERE channel_id=?", (ch_id,))
        cur.execute(
          "INSERT INTO force_channels (channel_id, invite_url, title) VALUES (?,?,?)",
          (ch_id, inv, title)
        )
        db.commit()
        await conv.send_message(custom_emoji_text(
          f"{P_YES} <b>Force channel added successfully!</b>\n\n"
          f"Title: {html.escape(title)}\n"
          f"Chat ID: <code>{html.escape(ch_id)}</code>\n"
          f"Join link created automatically."
        ))

      elif action_data == "del_fchan":
        rows = cur.execute("SELECT id, title, channel_id FROM force_channels").fetchall()
        if not rows: return await conv.send_message(custom_emoji_text("No channels to delete."))
        txt = "Reply with ID to delete:\n"
        for r in rows: txt += f"ID: {r[0]} - {r[1]} ({r[2]})\n"
        del_id = int((await get_reply(txt)).text.strip())
        cur.execute("DELETE FROM force_channels WHERE id=?", (del_id,))
        db.commit()
        await conv.send_message(custom_emoji_text(f"{P_YES} Force channel removed!"))

      elif action_data == "set_upi":
        new_upi = (await get_reply("Enter new UPI ID (e.g., yourname@fampay):")).text.strip()
        new_name = (await get_reply("Enter Payee Name (e.g., AccStore):")).text.strip()
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('fampay_upi', ?)", (new_upi,))
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('fampay_name', ?)", (new_name,))
        db.commit()
        await conv.send_message(custom_emoji_text(f"{P_YES} FamPay UPI settings updated!"))

      elif action_data == "set_imap":
        srv = (await get_reply("Enter IMAP Server (e.g., imap.gmail.com):")).text.strip()
        mail_id = (await get_reply("Enter Gmail Email Address (e.g., aroy327154@gmail.com):")).text.strip()
        pwd = (await get_reply("Enter Gmail App Password (e.g., yasc qrso aunp dnbc):")).text.strip()
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('imap_server', ?)", (srv,))
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('imap_email', ?)", (mail_id,))
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('imap_password', ?)", (pwd,))
        db.commit()
        await conv.send_message(custom_emoji_text(f"{P_YES} IMAP credentials saved successfully for automatic UTR verification!"))

      elif action_data == "ap_add_country" and has_perm(uid, 'p_manage_stock'):
        code = (await get_reply(f"{P_PHONE} <b>Enter Country Calling Code (without +):</b>\n<i>Example: 91</i>")).text.replace("+", "").strip()
        name = html.escape((await get_reply(f"{P_GLOBE} <b>Enter Country Name:</b>\n<i>Example: India</i>")).text.strip())
        
        cur.execute("INSERT OR REPLACE INTO custom_countries (code, name) VALUES (?,?)", (code, name))
        db.commit()
        await conv.send_message(custom_emoji_text(f"{P_YES} <b>Custom Country Added Successfully!</b>\n{name} (+{code})\n\n<i>It will now automatically be recognized when adding stock!</i>"))

      elif action_data == "userinfo" and has_perm(uid, 'p_stats'):
        t_uid = int((await get_reply(f"{P_ACC} <b>Enter User ID:</b>")).text)
        u_row = cur.execute("SELECT balance, total_deposited, joined_date, banned, discount FROM users WHERE user_id=?", (t_uid,)).fetchone()
        if not u_row: return await conv.send_message(custom_emoji_text(f"{P_NO} User not found."))
        
        o_row = cur.execute("SELECT COUNT(*), SUM(price) FROM orders WHERE user_id=?", (t_uid,)).fetchone()
        
        bal, dep, joined, is_banned, disc = u_row
        o_count = o_row[0] if o_row else 0
        o_spent = o_row[1] if o_row and o_row[1] else 0
        
        msg = (f"{P_ACC} <b>USER INFO:</b> <code>{t_uid}</code>\n\n"
            f"{P_MONEY} Balance: {P_INR}{bal}\n"
            f"{P_CARD} Total Deposited: {P_INR}{dep}\n"
            f"{P_CART} Total Orders: {o_count}\n"
            f"{P_USDT} Total Spent: {P_INR}{o_spent}\n"
            f"{P_GIFT} Discount: {disc}%\n"
            f"{P_CAL} Joined: {joined}\n"
            f"{P_OFF} Banned: {'Yes' if is_banned else 'No'}")
        await conv.send_message(custom_emoji_text(msg))

      elif action_data == "addadmin" and uid == ADMIN_ID:
        new_ad = int((await get_reply(f"{P_ACC} <b>Enter User ID for new Admin:</b>")).text)
        cur.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (new_ad,))
        db.commit()
        await conv.send_message(custom_emoji_text(f"{P_YES} Admin added!"))
        class FakeEvent: 
          async def edit(self, text, buttons): await bot.send_message(custom_emoji_text(chat), text, buttons=buttons)
          async def answer(self, txt, alert): pass
        await edit_admin_menu(FakeEvent(), new_ad)
        
      elif action_data == "editadminreq" and uid == ADMIN_ID:
        t_id = int((await get_reply(f"{P_ACC} <b>Enter User ID to edit:</b>")).text)
        class FakeEvent: 
          async def edit(self, text, buttons): await bot.send_message(custom_emoji_text(chat), text, buttons=buttons)
          async def answer(self, txt, alert): pass
        await edit_admin_menu(FakeEvent(), t_id)

      elif action_data.startswith("msedit|") and has_perm(uid, 'p_manage_stock'):
        parts = action_data.split("|")
        action, c_name = parts[1], parts[2]
        
        if action == "name":
          new_name = html.escape((await get_reply(f"{P_DOC} <b>Enter NEW Name for {html.escape(c_name)}:</b>")).text)
          cur.execute("UPDATE stock SET country_name=? WHERE country_name=?", (new_name, c_name))
          cur.execute("UPDATE auto_prices SET country=? WHERE country=?", (new_name, c_name))
          db.commit()
          await conv.send_message(custom_emoji_text(f"{P_YES} Country '{html.escape(c_name)}' successfully renamed to '{new_name}'!"))
          
        elif action == "cprice":
          new_p = int((await get_reply(f"{P_MONEY} <b>Enter NEW Common Price for all {html.escape(c_name)} accounts:</b>")).text)
          cur.execute("UPDATE stock SET price=? WHERE country_name=?", (new_p, c_name))
          db.commit()
          await conv.send_message(custom_emoji_text(f"{P_YES} All existing '{html.escape(c_name)}' accounts updated to {P_INR}{new_p}!"))
          
        elif action == "yprice":
          year = parts[3]
          new_p = int((await get_reply(f"{P_MONEY} <b>Enter NEW Price for {html.escape(c_name)} ({year}):</b>")).text)
          cur.execute("UPDATE stock SET price=? WHERE country_name=? AND account_year=?", (new_p, c_name, year))
          db.commit()
          await conv.send_message(custom_emoji_text(f"{P_YES} All existing '{html.escape(c_name)}' ({year}) accounts updated to {P_INR}{new_p}!"))
          
      elif action_data.startswith("apset|") and has_perm(uid, 'p_manage_stock'):
        parts = action_data.split("|")
        c_name, year = parts[1], parts[2]
        new_p = int((await get_reply(f"{P_ASST} <b>Enter Auto-Price for {html.escape(c_name)} ({year}):</b>\n<i>(Enter 0 to remove this auto-price)</i>")).text)
        if new_p == 0:
          cur.execute("DELETE FROM auto_prices WHERE country=? AND year=?", (c_name, year))
          await conv.send_message(custom_emoji_text(f"{P_YES} Auto-Price for {html.escape(c_name)} ({year}) removed!"))
        else:
          cur.execute("INSERT OR REPLACE INTO auto_prices (country, year, price) VALUES (?,?,?)", (c_name, year, new_p))
          await conv.send_message(custom_emoji_text(f"{P_YES} Auto-Price for {html.escape(c_name)} ({year}) set to {P_INR}{new_p}! Incoming accounts will use this price automatically."))
        db.commit()

      elif action_data == "addzip" and has_perm(uid, 'p_add_stock'):
        resp = await get_reply(f"{P_PKG} <b>Send the ZIP file containing <code>.session</code> files:</b>")
        if not resp.file or not resp.file.name.endswith('.zip'): return await conv.send_message(custom_emoji_text(f"{P_NO} Invalid file."))
        
        await conv.send_message(custom_emoji_text(f"{P_WAIT} <b>Extracting & Scanning Accounts...</b>"))
        zip_path = await bot.download_media(resp, "temp_sessions.zip")
        extracted_dir = f"temp_extracted_{int(time.time())}"
        os.makedirs(extracted_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref: zip_ref.extractall(extracted_dir)

        groups = {}
        for file in os.listdir(extracted_dir):
          if not file.endswith(".session"): continue
          sess_path = os.path.join(extracted_dir, file)
          clean_path = sess_path[:-8]
          try:
            client = TelegramClient(clean_path, API_ID, API_HASH)
            await client.connect()
            if not await client.is_user_authorized(): await client.disconnect(); continue
            me = await client.get_me()
            phone = getattr(me, 'phone', None)
            if not phone: await client.disconnect(); continue
            
            c_name = get_country_info(phone)
            pwd = await client(GetPasswordRequest())
            has_2fa = pwd.has_password
            year = await detect_account_year(client)
            await client.disconnect()

            key = (c_name, year, has_2fa)
            if key not in groups: groups[key] = []
            groups[key].append({"phone": phone, "path": clean_path})
          except Exception as e: logger.error(f"Scan error: {e}")

        for key in list(groups.keys()):
          if key[0] == "Unknown":
            sample_phone = groups[key][0]["phone"]
            await conv.send_message(custom_emoji_text(f"{P_WARN} <b>Country not recognized for +{sample_phone}!</b>"))
            new_name = html.escape((await get_reply(f"{P_GLOBE} <b>Enter Country Name:</b>\n<i>Example: India</i>")).text)
            new_key = (new_name, key[1], key[2])
            groups[new_key] = groups.pop(key)

        success = 0
        for (c_name, year, has_2fa), accs in groups.items():
          twofa_pass = "None"
          if has_2fa: twofa_pass = html.escape((await get_reply(f"{P_2FA} <b>Enter 2FA Password for {len(accs)}x {html.escape(c_name)} accounts:</b>")).text)

          auto_row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year=?", (c_name, str(year))).fetchone()
          if not auto_row: auto_row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year='Common'", (c_name,)).fetchone()

          if auto_row:
            price = auto_row[0]
            await conv.send_message(custom_emoji_text(f"{P_FIRE} <b>Auto-Price Applied:</b> {len(accs)}x {html.escape(c_name)} ({year}) at {P_INR}{price}."))
          else:
            existing_price = cur.execute("SELECT price FROM stock WHERE country_name=? LIMIT 1", (c_name,)).fetchone()
            if existing_price:
              price = existing_price[0]
              await conv.send_message(custom_emoji_text(f"{P_FIRE} <b>Auto-Added:</b> {len(accs)}x {html.escape(c_name)} at {P_INR}{price} (Copied from DB)."))
            else:
              price = int((await get_reply(f"{P_DOC} Found {len(accs)}x {html.escape(c_name)} ({year}).\n{P_MONEY} Enter Price (₹):")).text)

          for acc in accs:
            perm_base = f"sessions/{acc['phone']}"
            for ext in ['.session', '.session-wal', '.session-shm', '.session-journal']:
              if os.path.exists(acc['path'] + ext): shutil.move(acc['path'] + ext, perm_base + ext)
            cur.execute("INSERT OR REPLACE INTO stock (phone, session_file, country_name, account_year, category, price, available, twofa) VALUES (?,?,?,?,?,?,?,?)", 
                  (acc['phone'], perm_base + ".session", c_name, year, 'Good', price, 1, twofa_pass))
            success += 1
        db.commit()
        os.remove(zip_path); shutil.rmtree(extracted_dir)
        await conv.send_message(custom_emoji_text(f"{P_YES} {P_PARTY} <b>Bulk Interactive Upload Complete!</b>\n{P_ON} Added: {success}"))

      elif action_data == "addstock" and has_perm(uid, 'p_add_stock'):
        phone = (await get_reply(f"{P_PHONE} Enter Phone (+919999...):")).text.replace(" ", "").replace("+", "")
        sp = f"sessions/{phone}"
        client = TelegramClient(sp, API_ID, API_HASH)
        await client.connect()
        sreq = await client.send_code_request(phone)
        
        twofa_pass = "None"
        try: 
          await client.sign_in(phone, (await get_reply(f"{P_OTP} OTP:")).text, phone_code_hash=sreq.phone_code_hash)
        except SessionPasswordNeededError: 
          twofa_pass = html.escape((await get_reply(f"{P_2FA} 2FA Pass required. Enter it now:")).text)
          await client.sign_in(password=twofa_pass)
        
        c_name = get_country_info(phone)
        
        if c_name == "Unknown":
          await conv.send_message(custom_emoji_text(f"{P_WARN} <b>Country not recognized for +{phone}!</b>"))
          c_name = html.escape((await get_reply(f"{P_GLOBE} <b>Enter Country Name:</b>\n<i>Example: India</i>")).text)
        
        auto_year = await detect_account_year(client)
        await client.disconnect()
        
        year = int((await get_reply(f"{P_CAL} Detected Year: <b>{auto_year}</b>\nReply with Year to confirm or change:")).text)
        auto_row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year=?", (c_name, str(year))).fetchone()
        if not auto_row: auto_row = cur.execute("SELECT price FROM auto_prices WHERE country=? AND year='Common'", (c_name,)).fetchone()

        if auto_row:
          price = auto_row[0]
          await conv.send_message(custom_emoji_text(f"{P_FIRE} <b>Auto-Price Applied:</b> {P_INR}{price} for {html.escape(c_name)} ({year})"))
        else:
          existing_price = cur.execute("SELECT price FROM stock WHERE country_name=? LIMIT 1", (c_name,)).fetchone()
          if existing_price:
            price = existing_price[0]
            await conv.send_message(custom_emoji_text(f"{P_FIRE} <b>Auto-detected Price:</b> {P_INR}{price} for {html.escape(c_name)}"))
          else: price = int((await get_reply(f"{P_MONEY} Price (₹):")).text)
        
        cur.execute("INSERT OR REPLACE INTO stock (phone, session_file, country_name, account_year, category, price, available, twofa) VALUES (?,?,?,?,?,?,?,?)", 
              (phone, sp + ".session", c_name, year, 'Good', price, 1, twofa_pass))
        db.commit()
        await conv.send_message(custom_emoji_text(f"{P_YES} <b>Added!</b> {html.escape(c_name)}"))

      elif action_data == "supporturl" and has_perm(uid, 'p_settings'):
        url_inp = (await get_reply(f"{P_DOC} <b>Enter new Support Username or URL:</b>\n<i>(Examples: <code>https://t.me/m/XLARYAN_0100</code>)</i>")).text.strip()
        normalized = _normalize_tg_url(url_inp, "")
        if not normalized:
          await conv.send_message(custom_emoji_text(f"{P_NO} <b>Invalid Telegram support link.</b>\nPlease enter a valid <code>https://t.me/username</code>, <code>https://t.me/+invite</code>, or <code>@username</code>."))
        else:
          cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('support_url', ?)", (normalized,))
          db.commit()
          await conv.send_message(custom_emoji_text(f"{P_YES} <b>Support Link updated successfully!</b>\nTarget: <code>{html.escape(normalized)}</code>"))

      elif action_data == "supportchan" and has_perm(uid, 'p_settings'):
        chan_inp = (await get_reply(f"{P_GLOBE} <b>Enter new Support/Updates Channel Link or Username:</b>\n<i>(Examples: <code>https://t.me/...</code> or <code>@MyChannel</code>)</i>")).text.strip()
        normalized = _normalize_tg_url(chan_inp, "")
        if not normalized:
          await conv.send_message(custom_emoji_text(f"{P_NO} <b>Invalid Telegram channel link.</b>\nPlease enter a valid <code>https://t.me/channel</code>, <code>https://t.me/+invite</code>, or <code>@channel</code>."))
        else:
          cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('support_channel_url', ?)", (normalized,))
          db.commit()
          await conv.send_message(custom_emoji_text(f"{P_YES} <b>Support/Updates Channel Link updated successfully!</b>\nTarget: <code>{html.escape(normalized)}</code>"))

      elif action_data == "bcast" and has_perm(uid, 'p_stats'):
        txt = (await get_reply(f"{P_DOC} <b>Message (Supports HTML & tg-emoji tags):</b>")).text
        btn_name = (await get_reply("Button Name (or 'skip'):")).text
        url = (await get_reply("URL:")).text if btn_name.lower() != 'skip' else None
        btn = _safe_url_button(btn_name, url, style="primary") if url else None
        btns = [[btn]] if btn is not None else None
        users = cur.execute("SELECT user_id FROM users").fetchall()
        s, f = 0, 0
        await conv.send_message(custom_emoji_text(f"{P_TG} Broadcasting..."))
        for (u_id,) in users:
          try: 
            await bot.send_message(custom_emoji_text(int(u_id)), txt, buttons=btns, parse_mode='html')
            s += 1
          except: f += 1
          await asyncio.sleep(0.1) 
        await conv.send_message(custom_emoji_text(f"{P_YES} Done! Sent: {s} | Failed: {f}"))

      elif action_data == "bal" and has_perm(uid, 'p_bal'):
        t_uid = int((await get_reply(f"{P_ACC} <b>User ID:</b>")).text)
        amt = int((await get_reply(f"{P_MONEY} <b>Amount (Negative to deduct):</b>")).text)
        update_balance(t_uid, amt)
        await conv.send_message(custom_emoji_text(f"{P_YES} Added {P_INR}{amt} to {t_uid}."))
        
      elif action_data == "discount" and has_perm(uid, 'p_settings'):
        t_uid = int((await get_reply(f"{P_ACC} <b>User ID:</b>")).text)
        pct = int((await get_reply(f"{P_GIFT} <b>Discount % (0 to remove):</b>")).text)
        cur.execute("UPDATE users SET discount=? WHERE user_id=?", (pct, t_uid))
        db.commit()
        await conv.send_message(custom_emoji_text(f"{P_YES} User {t_uid} has {pct}% discount."))

      elif action_data == "usdtrate" and has_perm(uid, 'p_settings'):
        r = float((await get_reply(f"{P_USDT} <b>New USDT Rate (INR):</b>")).text)
        cur.execute("UPDATE settings SET value=? WHERE key='usdt_rate'", (str(r),))
        db.commit()
        await conv.send_message(custom_emoji_text(f"{P_YES} Rate set to {r}."))

      elif action_data == "restoreusr" and has_perm(uid, 'p_settings'):
        resp = await get_reply(f"{P_DOC} <b>Send the <code>users_backup.csv</code> file:</b>")
        if not resp.file or not resp.file.name.endswith('.csv'): return await conv.send_message(custom_emoji_text(f"{P_NO} Invalid file."))
        await bot.download_media(resp, "temp_restore.csv")
        with open("temp_restore.csv", "r", encoding="utf-8") as f:
          reader = csv.reader(f); next(reader); count = 0
          for row in reader:
            try:
              cur.execute("INSERT OR REPLACE INTO users (user_id, balance, total_deposited, joined_date, banned, discount, terms_accepted) VALUES (?,?,?,?,?,?,?)", 
                    (int(row[0]), int(row[1]), int(row[2]), row[3], int(row[4]), int(row[5]), int(row[6])))
              count += 1
            except: pass
        db.commit()
        os.remove("temp_restore.csv")
        await conv.send_message(custom_emoji_text(f"{P_YES} Restored {count} users."))

      elif action_data == "ban" and has_perm(uid, 'p_bal'):
        t_uid = int((await get_reply(f"{P_ACC} <b>User ID:</b>")).text)
        is_ban = cur.execute("SELECT banned FROM users WHERE user_id=?", (t_uid,)).fetchone()
        if not is_ban: return await conv.send_message(custom_emoji_text(f"{P_NO} User not found."))
        ns = 0 if is_ban[0] == 1 else 1
        cur.execute("UPDATE users SET banned=? WHERE user_id=?", (ns, t_uid))
        db.commit()
        await conv.send_message(custom_emoji_text(f"User {t_uid} status updated: {'Banned' if ns == 1 else 'Unbanned'}."))

    except ValueError: await conv.send_message(custom_emoji_text(f"{P_NO} Cancelled."))
    except Exception as e: await conv.send_message(custom_emoji_text(f"{P_NO} Error: {e}"))

@bot.on(events.NewMessage(pattern=r"(?i)^/refill(?:\s+(\d+))?"))
async def handle_refill_command(e):
  try:
    uid = e.sender_id
    if not uid: return
    ensure_user(uid)
    if is_user_banned(uid): return

    match = e.pattern_match.group(1)
    if not match:
      refill_state[uid] = {'step': 'wait_order_id'}
      await e.respond(custom_emoji_text(f"{P_ASST} <b>Please enter your Bot Order ID for refill:</b>\n<i>(Type /cancel to abort)</i>"))
    else:
      bot_order_id = int(match)
      order_row = cur.execute("SELECT user_id, smm_order_id FROM smm_orders WHERE bot_order_id=?", (bot_order_id,)).fetchone()
      if not order_row:
        return await e.respond(custom_emoji_text(f"{P_NO} Order ID <code>{bot_order_id}</code> not found in database."))
      owner_uid, smm_order_id = order_row
      if owner_uid != uid and not is_admin(uid):
        return await e.respond(custom_emoji_text(f"{P_NO} This order does not belong to you."))
      if not smm_order_id or smm_order_id == 'SUCCESS':
        return await e.respond(custom_emoji_text(f"{P_NO} Valid SMM Panel Order ID not available for this order."))
      
      refill_state[uid] = {'step': 'wait_screenshot', 'bot_order_id': bot_order_id, 'smm_order_id': smm_order_id}
      await e.respond(
        custom_emoji_text(f"{P_DOC} <b>Order ID Verified: #{bot_order_id}</b>\n\n"
        f"Please send a <b>screenshot</b> showing the invite link joined statistics (showing member list and joined count, exactly like the reference example).\n\n"
        f"<i>Send the screenshot now:</i>")
      )
  except Exception as ex:
    logger.error(f"Refill error: {ex}")

@bot.on(events.NewMessage(pattern=r"(?i)^/admin(?:@\w+)?\s*$"))
async def handle_admin_command(e):
  """Open the admin panel only through /admin."""
  uid = e.sender_id
  if not uid:
    return
  if not is_admin(uid):
    await e.respond("You are not authorized to use the admin panel.")
    return
  for state in (session_buy_state, deposit_input, smm_order_state, refill_state, waiting_proof, admin_dep_state):
    state.pop(uid, None)
  try:
    await admin_panel_handler(e)
  except Exception:
    logger.exception("Admin panel error for %s", uid)
    await e.respond("Admin panel could not be opened. Please check the bot logs.")

@bot.on(events.NewMessage(pattern=r"(?i)^/start"))
async def handle_start(e):
  try:
    uid = e.sender_id
    if not uid: return
    
    existing_user = cur.execute("SELECT 1 FROM users WHERE user_id=?", (uid,)).fetchone()
    is_new_user = existing_user is None
    ensure_user(uid)
    if is_new_user:
      await notify_new_user(uid, e)
    if is_user_banned(uid): return

    if not is_bot_online() and not is_admin(uid):
      return await e.respond(custom_emoji_text(f"{P_OFF} <b>Bot is currently under maintenance.</b> Please try again later."))
    
    session_buy_state.pop(uid, None)
    deposit_input.pop(uid, None)
    smm_order_state.pop(uid, None)
    refill_state.pop(uid, None)
    redeem_state.pop(uid, None)

    is_joined = await check_channel_joined(uid)
    if not is_joined:
      rows = cur.execute("SELECT title, invite_url FROM force_channels").fetchall()
      btns = []
      for title, invite_url in rows:
        b = _safe_url_button(title or "Join Channel", invite_url, style="primary")
        if b is not None:
          btns.append([b])
      btns.append([Button.inline("Verify Joined", "verify_join", style="success")])
      msg = f"{P_WARN} <b>You must join our channels first!</b>"
      return await e.respond(custom_emoji_text(msg), buttons=btns)

    await send_main_menu(e, uid)
  except Exception as ex: 
    logger.error(f"Start Error: {ex}", exc_info=True)

@bot.on(events.NewMessage())
async def handle_all_messages(e):
  try:
    uid = e.sender_id
    if not uid: return
    if getattr(e, 'text', None) and e.text and e.text.startswith('/'): return
    if not is_bot_online() and not is_admin(uid):
      return await e.respond(custom_emoji_text(f"{P_OFF} <b>Bot is currently under maintenance.</b> Please try again later."))
    
    ensure_user(uid)
    if is_user_banned(uid): return

    if uid in redeem_state:
      state=redeem_state.get(uid,{})
      text=(e.text or '').strip()
      if text.lower() == '/cancel':
        redeem_state.pop(uid,None); return await e.respond("Redeem cancelled.")
      if state.get('step') == 'wait_code' and text:
        redeem_state.pop(uid,None)
        code=text.upper()
        row=cur.execute("SELECT amount,max_users,used_count,active FROM redeem_codes WHERE code=?",(code,)).fetchone()
        if not row: return await e.respond("Invalid redeem code.")
        amount,mx,used,active=row
        if not active or used>=mx: return await e.respond("This code is no longer available.")
        if cur.execute("SELECT 1 FROM redeem_claims WHERE code=? AND user_id=?",(code,uid)).fetchone(): return await e.respond("You have already redeemed this code.")
        async with get_user_lock(uid):
          cur.execute("INSERT INTO redeem_claims(code,user_id) VALUES(?,?)",(code,uid))
          cur.execute("UPDATE redeem_codes SET used_count=used_count+1 WHERE code=? AND active=1 AND used_count<?",(code,mx))
          if cur.rowcount != 1:
            cur.execute("DELETE FROM redeem_claims WHERE code=? AND user_id=?",(code,uid)); db.commit(); return await e.respond("This code just reached its limit.")
          update_balance(uid,amount); db.commit()
        return await e.respond(custom_emoji_text(f"{P_YES} <b>Redeem Successful!</b>\nAmount Added: ₹{amount}"))

    if uid in refill_state:
      state = refill_state[uid]
      step = state['step']
      text = e.text.strip() if e.text else ""

      if text.lower() == '/cancel':
        refill_state.pop(uid, None)
        return await e.respond(custom_emoji_text(f"{P_NO} Refill process cancelled."))

      if step == 'wait_order_id':
        if not text.isdigit():
          return await e.respond(custom_emoji_text(f"{P_NO} Please enter a valid numeric Bot Order ID."))
        bot_order_id = int(text)
        order_row = cur.execute("SELECT user_id, smm_order_id FROM smm_orders WHERE bot_order_id=?", (bot_order_id,)).fetchone()
        if not order_row:
          return await e.respond(custom_emoji_text(f"{P_NO} Order ID <code>{bot_order_id}</code> not found in database."))
        owner_uid, smm_order_id = order_row
        if owner_uid != uid and not is_admin(uid):
          return await e.respond(custom_emoji_text(f"{P_NO} This order does not belong to you."))
        if not smm_order_id or smm_order_id == 'SUCCESS':
          return await e.respond(custom_emoji_text(f"{P_NO} Valid SMM Panel Order ID not available for this order."))
        
        state['bot_order_id'] = bot_order_id
        state['smm_order_id'] = smm_order_id
        state['step'] = 'wait_screenshot'
        refill_state[uid] = state
        
        await e.respond(
          custom_emoji_text(f"{P_DOC} <b>Order ID Verified: #{bot_order_id}</b>\n\n"
          f"Please send a <b>screenshot</b> showing the invite link joined statistics (showing member list and joined count, exactly like the reference example).\n\n"
          f"<i>Send the screenshot now:</i>")
        )
        return
      elif step == 'wait_screenshot':
        if not e.photo:
          return await e.respond(custom_emoji_text(f"{P_NO} Please send a valid image screenshot."))
        
        bot_order_id = state['bot_order_id']
        smm_order_id = state['smm_order_id']
        refill_state.pop(uid, None)
        
        await e.respond(custom_emoji_text(f"{P_WAIT} <b>Processing refill request and sending to SMM panel... Please wait.</b>"))
        
        api_url, api_key = get_smm_api_config()
        refill_res = None
        if api_url and api_key:
          refill_res = refill_smm_order_api(api_url, api_key, smm_order_id)
        
        # Forward refill request screenshot directly to ADMIN_ID (Admin DM)
        try:
          log_msg = (
            f"{P_BELL} <b>NEW REFILL REQUEST WITH SCREENSHOT</b>\n\n"
            f"{P_ACC} User ID: <code>{uid}</code>\n"
            f"{P_ID} Bot Order ID: <code>{bot_order_id}</code>\n"
            f"{P_GEAR} Panel Order ID: <code>{smm_order_id}</code>\n"
            f"{P_TIME} Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
          )
          await bot.send_file(ADMIN_ID, e.photo, caption=custom_emoji_text(log_msg))
        except Exception as ex:
          logger.error(f"Failed to forward refill screenshot to admin DM: {ex}")
        
        if refill_res and isinstance(refill_res, dict) and ('refill' in refill_res or refill_res.get('status') == 'success' or 'refill_id' in refill_res):
          refill_id = refill_res.get('refill', refill_res.get('refill_id', 'SUCCESS'))
          await e.respond(custom_emoji_text(f"{P_YES} <b>Refill Request Submitted Successfully!</b> {P_PARTY}\n\n- Bot Order ID: <code>{bot_order_id}</code>\n- Panel Refill ID: <code>{refill_id}</code>\n\n<i>Your screenshot has been verified and submitted.</i>"))
        else:
          err = refill_res.get('error', 'Unknown refill error') if isinstance(refill_res, dict) else 'Refill API connection failed'
          await e.respond(custom_emoji_text(f"{P_YES} <b>Refill Screenshot Received & Forwarded to Admin!</b>\n\nNote: Panel response: {html.escape(str(err))}. Your request has been logged for review."))
        
        await send_main_menu(e, uid)
        return

    if uid in smm_order_state:
      state = smm_order_state[uid]
      step = state['step']
      text = e.text.strip()

      if step == 'wait_link':
        state['link'] = text
        state['step'] = 'wait_qty'
        smm_order_state[uid] = state
        await e.respond(custom_emoji_text(f"{P_QTY} <b>Enter Quantity:</b>\n(Min: {state['min']} | Max: {state['max']}):"))
        return
      elif step == 'wait_qty':
        try:
          qty = int(re.sub(r'[^\d]', '', text))
          if qty < state['min'] or qty > state['max']:
            return await e.respond(custom_emoji_text(f"{P_NO} Quantity must be between {state['min']} and {state['max']}."))
          
          total_price = (qty / 1000.0) * state['rate']
          state['qty'] = qty
          state['total_price'] = total_price
          
          bal_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
          bal = bal_row[0] if bal_row else 0
          if bal < total_price:
            smm_order_state.pop(uid, None)
            err_msg = (
              f"{P_NO} <b>Insufficient Funds!</b>\n\n"
              f"<b>Order Cost:</b> ₹{total_price:.4f}\n"
              f"<b>Your Balance:</b> ₹{bal:.4f}\n\n"
              f"Please use /addfunds to top up your account."
            )
            return await e.respond(custom_emoji_text(err_msg))

          api_url, api_key = get_smm_api_config()
          if not api_url or not api_key:
            smm_order_state.pop(uid, None)
            return await e.respond(custom_emoji_text(f"{P_NO} SMM API is not configured by admin."))

          await e.respond(custom_emoji_text(f"{P_WAIT} <b>Placing order to SMM Panel... Please wait.</b>"))
          api_res = place_smm_order_api(api_url, api_key, state['service_id'], state['link'], qty)
          
          if api_res and isinstance(api_res, dict) and ('order' in api_res or api_res.get('status') == 'success'):
            smm_order_id = str(api_res.get('order', api_res.get('order_id', 'SUCCESS')))
            async with get_user_lock(uid):
              cur.execute("UPDATE users SET balance = balance - ? WHERE user_id=? AND balance >= ?", (total_price, uid, total_price))
              cur.execute("INSERT INTO smm_orders (user_id, service_id, link, quantity, total_price, smm_order_id, status) VALUES (?,?,?,?,?,?,?)",
                    (uid, state['service_id'], state['link'], qty, total_price, smm_order_id, 'Completed'))
              db.commit()
              bot_order_id = cur.lastrowid

            await log_smm_sale(
              uid, state['name'], bot_order_id, smm_order_id,
              state['link'], qty, total_price
            )
            smm_order_state.pop(uid, None)
            await e.respond(custom_emoji_text(f"{P_YES} <b>SMM Order Placed Successfully!</b> {P_PARTY}\n\n"
                    f"- Service: {html.escape(state['name'])}\n"
                    f"- Bot Order ID: <code>{bot_order_id}</code>\n"
                    f"- Panel Order ID: <code>{smm_order_id}</code>\n"
                    f"- Link: {html.escape(state['link'])}\n"
                    f"- Quantity: {qty}\n"
                    f"- Total Cost: ₹{total_price:.4f}\n\n"
                    f"<i>(Note: For refill use /refill {bot_order_id} or click Refill button)</i>"))
            await send_main_menu(e, uid)
          else:
            err_msg = api_res.get('error', 'Unknown error from SMM API') if isinstance(api_res, dict) else 'API connection failed'
            smm_order_state.pop(uid, None)
            await e.respond(custom_emoji_text(f"{P_NO} <b>SMM Order Failed:</b> {html.escape(str(err_msg))}"))
          return
        except ValueError:
          return await e.respond(custom_emoji_text(f"{P_NO} Please enter a valid number for quantity."))

    if uid in waiting_proof and waiting_proof[uid].get('step') == 'wait_utr':
      info = waiting_proof.pop(uid)
      amt = info['amount']
      utr = e.text.strip()
      
      if len(utr) < 6:
        waiting_proof[uid] = info
        return await e.reply(custom_emoji_text(f"{P_NO} Please enter a valid UTR / Transaction Reference number."))
        
      await e.respond(custom_emoji_text(f"{P_WAIT} <b>Verifying transaction via automated Gmail IMAP... Please wait.</b>"))
      
      settings_row_user = cur.execute("SELECT value FROM settings WHERE key='imap_email'").fetchone()
      settings_row_pass = cur.execute("SELECT value FROM settings WHERE key='imap_password'").fetchone()
      g_user = settings_row_user[0].strip() if settings_row_user and settings_row_user[0] else ""
      g_pass = settings_row_pass[0].strip() if settings_row_pass and settings_row_pass[0] else ""
      
      # Never credit the same UTR twice.
      existing_utr = cur.execute("SELECT id FROM deposits WHERE UPPER(COALESCE(utr,''))=? AND status='approved' LIMIT 1", (utr.upper(),)).fetchone()
      if existing_utr:
        waiting_proof[uid] = {'step': 'wait_utr', 'amount': amt}
        return await e.respond(custom_emoji_text(f"{P_NO} <b>This UTR has already been used.</b> Please enter a different transaction UTR."))

      # Email delivery can take a few seconds. Retry automatically instead of
      # forcing the user to submit the same payment again.
      paid_amount = None
      for attempt in range(8):
        paid_amount = await check_payment_in_gmail_async(utr, g_user, g_pass, expected_amount=amt)
        if paid_amount is not None and paid_amount + 0.01 >= amt:
          break
        if attempt < 7:
          await asyncio.sleep(5)
      
      if paid_amount is not None and paid_amount + 0.01 >= amt:
        async with get_user_lock(uid):
          prev_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
          prev_bal = prev_row[0] if prev_row else 0
          update_balance(uid, amt)
          cur.execute("INSERT INTO deposits (user_id, amount, method_name, status, utr) VALUES (?,?,?,?,?)", (uid, amt, "FamPay UPI", "approved", utr))
          cur.execute("UPDATE users SET total_deposited = total_deposited + ? WHERE user_id=?", (amt, uid))
          db.commit()
          
        await log_primary_deposit_success(uid, amt, "FamPay UPI", utr)
        
        user_msg = (f"{P_YES} {P_PARTY} <b>Payment Verified Automatically via Gmail IMAP!</b>\n\n"
              f"{P_MONEY} <b>Amount Credited:</b> ₹{amt}\n"
              f"Previous Balance: ₹{prev_bal} | New Balance: ₹{prev_bal+amt}\n"
              f"UTR: <code>{utr}</code>")
        await e.respond(custom_emoji_text(user_msg))
        await send_main_menu(e, uid)
      else:
        # Fallback: If automated check fails, ask user to upload payment screenshot for manual review sent to ADMIN_ID DM
        waiting_proof[uid] = {'step': 'wait_screenshot', 'amount': amt, 'utr': utr}
        await e.respond(
          custom_emoji_text(f"{P_WARN} <b>Automated verification note:</b> No matching payment email/UTR was found, or the email amount was lower than the requested deposit.\n\n"
          f"Please send a <b>screenshot</b> of your payment receipt so the admin can verify and approve it manually.")
        )
      return

    if uid in waiting_proof and waiting_proof[uid].get('step') == 'wait_screenshot':
      if not e.photo:
        return await e.reply(custom_emoji_text(f"{P_NO} Please send a valid image screenshot."))
      
      info = waiting_proof.pop(uid)
      amt = info['amount']
      utr = info['utr']
      
      cur.execute("INSERT INTO deposits (user_id, amount, method_name, status, utr) VALUES (?,?,?,?,?)", (uid, amt, "FamPay UPI (Pending Screenshot)", "pending", utr))
      db.commit()
      dep_id = cur.lastrowid
      
      cap = (f"{P_BELL} <b>NEW FAMPA/UPI MANUAL DEPOSIT REVIEW</b>\n\n"
          f"{P_ACC} User ID: <code>{uid}</code>\n"
          f"{P_MONEY} Amount: <b>₹{amt}</b>\n"
          f"{P_CARD} UTR: <code>{utr}</code>\n"
          f"{P_ID} Ref ID: <code>{dep_id}</code>")
      btns = [
        [Button.inline(f"Accept (₹{amt})", f"dep_acc|{dep_id}|{uid}|FamPay UPI|exact|{amt}", style="success"),
         Button.inline("Reject", f"dep_rej|{dep_id}|{uid}", style="danger")]
      ]
      
      # Send manual deposit review with screenshot to the owner and all configured admins.
      await send_admins_file(e.photo, cap, buttons=btns)
        
      await e.respond(custom_emoji_text(f"{P_YES} <b>Payment screenshot forwarded to Admin successfully!</b>\nAdmin will review it and add the balance shortly."))
      await send_main_menu(e, uid)
      return

    text = e.text or ""
    if not text: return

    if text in ["Store", "Add Funds", "Profile", "Orders History", "Support", "Updates", "__ADMIN_PANEL_REMOVED__"]:
      session_buy_state.pop(uid, None)
      deposit_input.pop(uid, None)
      admin_dep_state.pop(uid, None)
      smm_order_state.pop(uid, None)
      refill_state.pop(uid, None)

    if uid in session_buy_state:
      state = session_buy_state[uid]
      try:
        qty = int(re.sub(r'[^\d]', '', text))
        if qty < 1: raise ValueError
        if qty > state['stock']: return await e.respond(custom_emoji_text(f"{P_WARN} <b>Not enough stock!</b> Max is {state['stock']}."))
        
        disc_row = cur.execute("SELECT discount FROM users WHERE user_id=?", (uid,)).fetchone()
        discount = disc_row[0] if disc_row else 0
        total_cost = qty * state['price']
        if discount > 0: total_cost = int(total_cost * (100 - discount) / 100)
          
        bal_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        user_bal = bal_row[0] if bal_row else 0
        if user_bal < total_cost: return await e.respond(custom_emoji_text(f"{P_NO} <b>Insufficient Balance!</b>\nYou need {P_INR}{total_cost} to buy {qty} sessions."))

        session_buy_state.pop(uid)
        await process_bulk_sessions(e, uid, qty, state, total_cost)
        return
      except ValueError: return await e.respond(custom_emoji_text(f"{P_NO} Please enter a valid number."))

    if uid in deposit_input and deposit_input[uid].get('step') == 'wait_payment_screenshot':
      if not e.photo:
        return await e.respond(custom_emoji_text(f"{P_NO} Please send the payment screenshot."))
      info = deposit_input.pop(uid)
      amt = info['amount']
      method = info.get('method', 'UPI Manual')
      cur.execute("INSERT INTO deposits (user_id,amount,method_name,status,utr) VALUES (?,?,?,?,?)", (uid, amt, method, 'pending', ''))
      db.commit()
      dep_id = cur.lastrowid
      cap = (f"{P_BELL} <b>NEW {html.escape(method.upper())} DEPOSIT REVIEW</b>\n\n"
          f"{P_ACC} User ID: <code>{uid}</code>\n"
          f"{P_MONEY} Amount: <b>₹{amt}</b>\n"
          f"{P_CARD} Method: <b>{html.escape(method)}</b>\n"
          f"{P_ID} Ref ID: <code>{dep_id}</code>")
      btns = [[Button.inline(f"Accept ₹{amt}", f"dep_acc|{dep_id}|{uid}|{method}|exact|{amt}", style="success"), Button.inline("Reject", f"dep_rej|{dep_id}|{uid}", style="danger")]]
      sent_admins = await send_admins_file(e.photo, cap, buttons=btns)
      if sent_admins:
        await e.respond(custom_emoji_text(f"{P_YES} <b>Screenshot sent to all admins.</b>\nYour payment is pending verification."))
      else:
        await e.respond(custom_emoji_text(f"{P_WARN} Screenshot received, but no admin could be reached right now."))
      return

  except Exception as ex: logger.error(f"Message Error: {ex}", exc_info=True)

@bot.on(events.CallbackQuery)
async def handle_callback_query(e):
  try:
    # Do not pre-answer the callback here. Individual branches answer alerts
    # when needed; pre-answering makes later alert/error responses invisible
    # and was causing many buttons to look dead. Successful edit/respond calls
    # also clear the Telegram button spinner.
    uid = e.sender_id
    if not is_bot_online() and not is_admin(uid):
      return await safe_callback_answer(e, "Bot is under maintenance.", alert=True)
      
    ensure_user(uid)
    if is_user_banned(uid): return await safe_callback_answer(e, "BANNED", alert=True)
    raw_data = getattr(e, "data", b"")
    if isinstance(raw_data, bytes):
      data = raw_data.decode("utf-8", errors="replace")
    else:
      data = str(raw_data or "")

    if data == "cb_store":
      try:
        await store_servers_menu(e)
      except Exception as ex:
        logger.error(f"Store callback error: {ex}", exc_info=True)
        await safe_callback_answer(e, "Store could not be opened. Please try /start again.", alert=True)
    elif data == "digital_shop":
      try:
        await digital_shop_menu(e)
      except Exception as ex:
        logger.error(f"Digital Shop callback error: {ex}", exc_info=True)
        try:
          await bot.send_message(e.chat_id, custom_emoji_text(f"{P_NO} <b>Digital Shop</b>\n\nPlease try again."), buttons=[[Button.inline("Back to Store", "store_servers", style="primary")]], parse_mode='html')
        except Exception:
          pass
    elif data.startswith("digital_product|"):
      await digital_product_view(e, int(data.split("|")[1]))
    elif data.startswith("digital_buy|"):
      await digital_buy(e, int(data.split("|")[1]))
    elif data == "redeem_start":
      redeem_state[uid] = {'step':'wait_code'}
      await e.edit(custom_emoji_text("Enter your redeem code (for example: AKOP):"), buttons=[[Button.inline("Cancel","cancel_action",style="danger")]])
    elif data == "cb_smm_services":
      await show_smm_categories(e)
    elif data.startswith("smm_cat|"):
      cid = int(data.split("|")[1])
      await show_smm_services_in_category(e, cid)
    elif data.startswith("smm_srv|"):
      sid = int(data.split("|")[1])
      await smm_service_detail_view(e, sid)
    elif data.startswith("smm_buy|"):
      sid = int(data.split("|")[1])
      row = cur.execute("SELECT service_id, name, rate, min, max FROM smm_services WHERE service_id=?", (sid,)).fetchone()
      if not row: return await safe_callback_answer(e, "Service not found.", alert=True)
      s_id, s_name, s_rate, s_min, s_max = row
      smm_order_state[uid] = {'service_id': s_id, 'name': s_name, 'rate': s_rate, 'min': s_min, 'max': s_max, 'step': 'wait_link'}
      await e.edit(custom_emoji_text(f"{P_ID} <b>Service ID: {s_id}</b>\n{P_TITLE} <b>Title: {html.escape(s_name)}</b>\n\n{P_ASST} <b>Send Link:</b>"), buttons=[[Button.inline(" Cancel", "cancel_action", style="danger")]])
    elif data == "cb_addfunds":
      await deposit_menu(e)
    elif data == "cb_profile":
      await profile_handler(e, is_callback=True)
    elif data == "cb_orders":
      await orders_history_handler(e, is_callback=True)
    elif data == "cb_refill":
      refill_state[uid] = {'step': 'wait_order_id'}
      msg = f"{P_ID} <b>SMM Service Refill</b>\n\nPlease reply with your <b>Bot Order ID</b> that you want to refill:"
      btns = [[Button.inline("Cancel", "cancel_action", style="danger")]]
      await e.edit(custom_emoji_text(msg), buttons=btns)
    elif data == "cb_support":
      # Backward-compatible handler for older menus.
      support_url = get_support_url()
      if not _has_valid_button_url(support_url):
        return await safe_callback_answer(e, custom_emoji_text(" Support link is not configured by Admin yet."), alert=True)
      await safe_callback_answer(e, custom_emoji_text(" Opening Support..."), alert=False)
      await e.respond(
        custom_emoji_text(f"{P_ON} <b>Support</b>\n\n{P_ASST} Tap below to contact support."),
        buttons=[[_safe_url_button("Support", support_url, style="primary")],
             [Button.inline("Back to Main", "back_main", style="primary")]]
      )
    elif data == "cb_updates":
      # Backward-compatible handler for older menus.
      updates_url = get_support_channel_url()
      if not _has_valid_button_url(updates_url):
        return await safe_callback_answer(e, custom_emoji_text(" Updates channel link is not configured by Admin yet."), alert=True)
      await safe_callback_answer(e, custom_emoji_text(" Opening Updates..."), alert=False)
      await e.respond(
        custom_emoji_text(f"{P_STAR} <b>Channel Updates & News</b> {P_ROCKET}\n\n{P_ASST} Tap below to open the official updates channel."),
        buttons=[[_safe_url_button("Updates", updates_url, style="primary")],
             [Button.inline("Back to Main", "back_main", style="primary")]]
      )
    elif data == "verify_join":
      if not await check_channel_joined(uid): return await safe_callback_answer(e, "You must join the channels first!", alert=True)
      await send_main_menu(e, uid)

    elif data == "cancel_action":
      deposit_input.pop(uid, None); waiting_proof.pop(uid, None); session_buy_state.pop(uid, None); smm_order_state.pop(uid, None); refill_state.pop(uid, None); redeem_state.pop(uid, None)
      try: await e.edit(custom_emoji_text(f"{P_NO} <b>Cancelled.</b>"))
      except MessageNotModifiedError: pass

    elif data == "store_servers":
      await store_servers_menu(e)

    elif data == "back_main":
      await send_main_menu(e, uid)

    elif data == "profile_callback":
      await profile_handler(e, is_callback=True)

    elif data == "my_orders_list":
      await orders_history_handler(e, is_callback=True)

    elif data == "payments_history":
      await payments_history_handler(e)

    elif data == "dep_menu_cb":
      await deposit_menu(e)

    elif data.startswith("dep_key|"):
      state = deposit_input.get(uid)
      if not state or state.get('step') != 'amount_keypad':
        return await safe_callback_answer(e, "Amount session expired. Please start again.", alert=True)
      digit = data.split("|", 1)[1]
      if digit not in '0123456789':
        return await safe_callback_answer(e, "Invalid amount button.", alert=True)
      current = state.get('amount', '')
      if len(current) >= 8:
        return await safe_callback_answer(e, "Amount is too large.", alert=True)
      if not current and digit == '0':
        return await safe_callback_answer(e, "Amount cannot start with 0.", alert=True)
      state['amount'] = current + digit
      await show_deposit_amount_keypad(e, uid)

    elif data == "dep_key_del":
      state = deposit_input.get(uid)
      if not state or state.get('step') != 'amount_keypad':
        return await safe_callback_answer(e, "Amount session expired. Please start again.", alert=True)
      state['amount'] = state.get('amount', '')[:-1]
      await show_deposit_amount_keypad(e, uid)

    elif data == "dep_key_confirm":
      await generate_deposit_qr(e, uid)

    elif data == "dep_payment_verify":
      state = deposit_input.get(uid)
      if not state or state.get('step') != 'wait_payment_verify':
        return await safe_callback_answer(e, "Payment session expired. Please start again.", alert=True)
      state['step'] = 'wait_payment_screenshot'
      await e.edit(custom_emoji_text(
        f"{P_CARD} <b>Verify Payment</b>\n\n"
        f"Amount: <b>₹{state['amount']}</b>\n"
        f"Method: <b>{html.escape(state.get('method',''))}</b>\n\n"
        f"{P_ASST} <b>Now send your payment screenshot here.</b>\n"
        f"The screenshot will be sent to all admins for verification."
      ), buttons=[[Button.inline(" Cancel", "cancel_action", style="danger")]])

    elif data.startswith("dep_verify_start|"):
      # Backward compatibility for old payment messages: use screenshot verification.
      amt = int(data.split("|")[1])
      deposit_input[uid] = {'step': 'wait_payment_screenshot', 'amount': amt, 'method': 'FamPay Automatic'}
      await e.edit(custom_emoji_text(f"{P_CARD} <b>Verify Payment</b>\n\nAmount: <b>₹{amt}</b>\n\n{P_ASST} <b>Send your payment screenshot here.</b>\nIt will be forwarded to all admins for manual verification."), buttons=[[Button.inline(" Cancel", "cancel_action", style="danger")]])

    elif data == "srv|manual":
      await show_server_countries(e, 'manual', 1)

    elif data.startswith("srv_pg|"):
      p = data.split("|")
      await show_server_countries(e, p[1], int(p[2]))

    elif data.startswith("s_country|"):
      p = data.split("|", 2)
      country = _resolve_country_ref(p[2]) if len(p) > 2 else ""
      await show_country_details(e, p[1], country)

    elif data.startswith("p_buy|"):
      p = data.split("|", 2)
      flow = p[1]
      country = _resolve_country_ref(p[2]) if len(p) > 2 else ""
      if flow == 'single':
        rows = cur.execute("SELECT account_year, price FROM stock WHERE available=1 AND country_name LIKE ? ORDER BY price ASC LIMIT 1", (f"{country}%",)).fetchone()
        if not rows: return await safe_callback_answer(e, "Out of stock!", alert=True)
        await confirm_purchase(e, country, rows[0], rows[1])
      else:
        rows = cur.execute("SELECT account_year, price FROM stock WHERE available=1 AND country_name LIKE ? ORDER BY price ASC LIMIT 1", (f"{country}%",)).fetchone()
        if not rows: return await safe_callback_answer(e, "Out of stock!", alert=True)
        await init_session_purchase(e, country, rows[0], rows[1])

    elif data.startswith("p_year|"):
      country_ref = data.split("|", 1)[1]
      country = _resolve_country_ref(country_ref)
      await show_years_for_country(e, country)

    elif data.startswith("by_yr|"):
      p = data.split("|")
      country = _resolve_country_ref(p[1])
      await confirm_purchase(e, country, p[2], p[3])

    elif data.startswith("buy_cf|"):
      p = data.split("|")
      country = _resolve_country_ref(p[1])
      await process_purchase(e, country, p[2], p[3])

    elif data.startswith("get_otp_again|"):
      phone = data.split("|")[1]
      if phone not in active_orders:
        return await safe_callback_answer(e, "Session already logged out or expired.", alert=True)
      
      order = active_orders[phone]
      client = order['client']
      start_time = order['start_time']
      
      await safe_callback_answer(e, "Fetching latest OTP...", alert=False)
      try:
        msgs = await client.get_messages(777000, limit=5)
        latest_code = None
        for m in msgs:
          if m.date.timestamp() > start_time - 10:
            if m.message and re.search(r'\b\d{5}\b', m.message) and "Login detected" not in m.message:
              latest_code = re.search(r'\b\d{5}\b', m.message).group()
              break
        
        if latest_code:
          twofa_text = f"{P_2FA} <b>2FA:</b> <code>{html.escape(order['twofa'])}</code>" if order['twofa'] != "None" else f"{P_2FA} <b>2FA:</b> <code>Disabled (No Password)</code>"
          msg = (f"{P_YES} {P_FIRE} <b>Latest OTP Fetched!</b>\n\n"
              f"{P_PHONE} <b>Phone:</b> <code>{phone}</code>\n"
              f"{P_FLAG} <b>Country:</b> {html.escape(order['country'])}\n"
              f"{P_OTP} <b>OTP:</b> <code>{latest_code}</code>\n"
              f"{twofa_text}")
          btns = [
            [Button.inline("Get OTP Again", f"get_otp_again|{phone}", style="primary")],
            [Button.inline("Finish & Logout", f"logout_bot|{phone}", style="danger")]
          ]
          try: await e.edit(custom_emoji_text(msg), buttons=btns)
          except MessageNotModifiedError: pass
        else:
          await safe_callback_answer(e, "No new OTP found yet. Try again in a few seconds.", alert=True)
      except Exception:
        await safe_callback_answer(e, "Error fetching OTP.", alert=True)

    elif data.startswith("logout_bot|"):
      phone = data.split("|")[1]
      if phone in active_orders:
        order = active_orders.pop(phone)
        try: await order['client'].log_out()
        except: pass
        try: await order['client'].disconnect()
        except: pass
        delete_session_files(order['sess'])
        await e.edit(custom_emoji_text(f"{P_YES} <b>Session Finished & Logged out successfully.</b>"))
      else:
        await safe_callback_answer(e, "No active order found or already logged out.", alert=True)
    
    elif data == "depm_auto": await manual_deposit_init(e, "FamPay Automatic")
    elif data == "depm_manual": await manual_deposit_init(e, "UPI Manual")
    
    elif data.startswith("adm_") and is_admin(uid): await admin_actions(e)
    
    elif data.startswith("dep_acc|") and has_perm(uid, 'p_bal'):
      p = data.split("|")
      dep_id, t_uid, method, a_type = p[1], int(p[2]), p[3], p[4]
      row = cur.execute("SELECT status FROM deposits WHERE id=?", (dep_id,)).fetchone()
      if not row or row[0] != 'pending': return await e.edit(custom_emoji_text(f"{P_WARN} Already processed."))
      
      if a_type == "exact":
        amt = int(p[5]) 
        async with get_user_lock(t_uid):
          prev_row = cur.execute("SELECT balance FROM users WHERE user_id=?", (t_uid,)).fetchone()
          prev_bal = prev_row[0] if prev_row else 0
          update_balance(t_uid, amt)
          
          cur.execute("UPDATE deposits SET status='approved', amount=? WHERE id=?", (amt, dep_id))
          cur.execute("UPDATE users SET total_deposited = total_deposited + ? WHERE user_id=?", (amt, t_uid))
          db.commit()
        await log_primary_deposit(t_uid, amt, method)
        
        user_msg = (f"{P_YES} {P_PARTY} <b>Deposit Approved!</b>\n\n{P_MONEY} <b>Amount Added:</b> ₹{amt}\n"
              f"Previous Balance: ₹{prev_bal} | New Balance: ₹{prev_bal+amt}")
        await bot.send_message(custom_emoji_text(int(t_uid)), custom_emoji_text(user_msg))
        try: await e.edit(custom_emoji_text(f"{P_YES} <b>MANUALLY CREDITED ₹{amt} TO {t_uid}</b>"))
        except MessageNotModifiedError: pass
        
    elif data.startswith("dep_rej|") and has_perm(uid, 'p_bal'):
      p = data.split("|")
      dep_id, t_uid = p[1], int(p[2])
      row = cur.execute("SELECT status FROM deposits WHERE id=?", (dep_id,)).fetchone()
      if not row or row[0] != 'pending': return await e.edit(custom_emoji_text(f"{P_WARN} Already processed."))
      admin_dep_state[uid] = {'target_uid': t_uid, 'dep_id': dep_id, 'step': 'wait_reason', 'msg_id': getattr(getattr(e, '_message', None), 'id', None)}
      await bot.send_message(custom_emoji_text(uid), custom_emoji_text(f"{P_WARN} Reply to this message with the REASON for rejecting user <code>{t_uid}</code>:"))
      try: await safe_callback_answer(e, "Check your bot PMs to enter the reason.", alert=True)
      except: pass
    else:
      await safe_callback_answer(e, "This button is no longer active. Please open the menu again.", alert=True)

  except Exception as ex:
    logger.error(f"Callback Error: {ex}", exc_info=True)
    # Always leave the user with a visible response. If the callback was not
    # answered yet, the alert is useful; otherwise the chat message is the
    # fallback. Never let the error itself crash the callback handler.
    try:
      await safe_callback_answer(e, "This action failed. Please try again.", alert=True)
    except Exception:
      try:
        await bot.send_message(e.chat_id, f"Button error: {html.escape(str(ex))}")
      except Exception:
        pass

async def main():
  print("BOT STARTED SUCCESSFULLY")
  await bot.run_until_disconnected()

if __name__ == '__main__':
  bot.start(bot_token=BOT_TOKEN)
  loop = asyncio.get_event_loop()
  loop.run_until_complete(main())