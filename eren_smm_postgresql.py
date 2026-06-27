import logging
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest
from telegram.constants import ParseMode
from datetime import datetime, timedelta
import json

# ===== CONFIGURATION =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8034872992"))
LOG_CHANNEL = int(os.getenv("LOG_CHANNEL", "-1003895644077"))
START_BALANCE = int(os.getenv("START_BALANCE", "0"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/eren_smm")

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== DATABASE CONNECTION =====
def get_db():
    """PostgreSQL bağlantısı aç"""
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Database cədvəllərini yaratmaq"""
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        balance INTEGER DEFAULT 0,
        vip_status BOOLEAN DEFAULT FALSE,
        referrals INTEGER DEFAULT 0,
        daily_bonus_used BOOLEAN DEFAULT FALSE,
        last_bonus_date TEXT,
        daily_transfer_count INTEGER DEFAULT 0,
        last_transfer_date TEXT,
        language TEXT DEFAULT 'TR',
        registration_date TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS products (
        product_id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        price INTEGER NOT NULL,
        stock INTEGER NOT NULL,
        vip_only BOOLEAN DEFAULT FALSE,
        description TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        order_id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL REFERENCES users(user_id),
        product_id INTEGER NOT NULL REFERENCES products(product_id),
        quantity INTEGER NOT NULL,
        status TEXT DEFAULT 'Alındı',
        order_date TEXT,
        profile_link TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS transfers (
        transfer_id SERIAL PRIMARY KEY,
        sender_id BIGINT NOT NULL REFERENCES users(user_id),
        receiver_id BIGINT NOT NULL REFERENCES users(user_id),
        amount INTEGER NOT NULL,
        transfer_date TEXT,
        status TEXT DEFAULT 'Başarılı'
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS referrals (
        referral_id SERIAL PRIMARY KEY,
        referrer_id BIGINT NOT NULL REFERENCES users(user_id),
        referred_user_id BIGINT NOT NULL REFERENCES users(user_id),
        referral_date TEXT
    )''')

    # Index'ler qurulmaq (sürətlik üçün)
    c.execute('CREATE INDEX IF NOT EXISTS idx_users_id ON users(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_transfers_sender ON transfers(sender_id)')

    conn.commit()
    c.close()
    conn.close()
    logger.info("Database başlatıldı")

# Başlat
try:
    init_db()
except Exception as e:
    logger.error(f"Database başlatma hatası: {e}")

# ===== LANGUAGE =====
LANG = {
    'TR': {
        'welcome': '☀️ Merhaba\n\n👾 Eren SMM TR\nTürkiye\'nin güvenilir dijital ürün marketi.\n\nİşlem seçin:',
        'balance': '💎 Bakiye',
        'profile': '👤 Profilim',
        'shop': '🛍️ Mağaza',
        'vip_shop': '👑 VIP Mağaza',
        'daily_bonus': '🎁 Günlük Bonus',
        'orders': '📦 Siparişlerim',
        'transfer': '💰 Puan Transferi',
        'coupon': '🎫 Kupon Kodu',
        'referral': '🤝 Referans',
        'support': '💬 Destek',
        'help': '❓ Yardım',
        'language': '🌍 Dil',
        'raffle': '🎲 Çekiliş',
        'donate': '⭐️ Bağış Yap',
        'back_to_menu': '← Ana Merkeze Dön',
        'profile_text': '👤 Profil Özeti\n\n🆔 Kullanıcı ID: {user_id}\n💎 Cüzdan Bakiyesi: {balance} Puan\n🤝 Davet Edilen: {referrals} Kişi\n💼 Toplam Sipariş: {orders}\n📆 Kayıt Tarihi: {reg_date}\n\n💡 VIP olarak: 2x Günlük Bonus, +2 Davet Puanı, VIP Mağazaya erişim!',
        'daily_bonus_success': '🎁 Günlük Bonus Alındı!\n\n➕ +1 Puan hesabınıza eklendi!\n💎 Yeni Bakiye: {balance} Puan\n\n👍 Bugünkü tüm bonus haklarını kullandın!',
        'daily_bonus_used': '⏳ Yarın tekrar gel!\n\nSonraki bonus: {time}',
        'insufficient_balance': '❌ Yetersiz Bakiye!\nGerekli: {needed} Puan\nBakiyeniz: {balance} Puan',
        'transfer_info': '💰 Puan Transfer Sistemi\n\n💎 Bakiyeniz: {balance} Puan\n⏳ Günlük Hak: {daily_left}/2 kaldı\n\n1️⃣ Her transferde bot 1 Puan komisyon keser.\n👤 Alıcı ID ve miktarı girerek transfer yapın.\n\nFormat: AlıcıID|Miktar\nÖrn: 1234567|10',
        'transfer_format_error': '❌ Hatalı format!\nDoğru format: AlıcıID|Miktar\nÖrn: 1234567|10',
        'transfer_success': '✅ Transfer Başarılı!\n\n📤 {amount} Puan gönderdiniz\n👤 Alıcı: {receiver_id}\n💸 Komisyon: 1 Puan\n💎 Yeni Bakiye: {new_balance} Puan',
        'transfer_limit_reached': '⏳ Günlük transfer hakkınız bitti!\n\nGünde en fazla 2 transfer yapabilirsiniz. Yarın tekrar deneyin.',
        'shop_welcome': '👋 Normal Mağazaya Hoşgeldiniz!\n\nBir kategori seçin:',
        'tiktok_smm': '🎵 TikTok Smm',
        'telegram_smm': '📱 Telegram Smm',
        'category_empty': '📦 {category}\n\nBu kategoride henüz ürün bulunmuyor.\nYakında eklenecek!',
        'vip_shop_welcome': '👑 VIP Mağazaya Hoşgeldiniz!\n\nÖzel VIP ürünleri:',
        'vip_required_alert': '⚠️ Lütfen önce VIP olun!\n\nVIP mağazaya erişmek için VIP üyeliğiniz gerekiyor.',
        'no_orders': '📦 Sipariş Geçmişiniz\n\nHenüz hiç siparişiniz bulunmuyor.',
        'referral_link': '🤝 Davet Et, Kazan!\n\n👇 Aşağıdaki kişisel linkinizle arkadaşlarınızı sisteme davet edin, her yeni katılımda anında +1 Puan kazanın.\n\n📋 Sizin Linkiniz:\nhttps://t.me/ErenSMMBot?start={user_id}',
        'support_text': '💬 Destek Merkezi\n\n⚠️ Lütfen admini boş yere rahatsız etmeyiniz.\nMesajınız yalnızca gerçek bir sorun, hatalı sipariş veya acil durum söz konusuysa iletilmelidir.\nSık sorulan sorular için önce Yardım menüsünü inceleyin.\n\n💎 Bakiyeniz: {balance} Puan\n\n━━━━━━━━━━━━━━━━━\nSorununuzu veya talebinizi aşağıya yazın.\nİptal etmek için /iptal yazın.',
        'no_active_raffle': '🎲 Çekiliş\n\n⚠️ Şu anda aktif bir çekiliş bulunmuyor.\n\nYeni çekilişler için takipte kalın!',
        'donate_text': '⭐️ Bağış Yap\n\nDextroo SMM TR olarak sizlere her zaman daha iyi, daha hızlı, daha uzun süre ve daha uygun fiyata hizmet verebilmek için büyük emek harcıyoruz.\n\nEğer hizmetlerimizden memnun kaldıysanız, bize bir yıldız bağışı yaparak destek olabilirsiniz. Her katkı bizim için çok değerlidir. Sağ olun, var olun! 🙏\n\nKaç yıldız bağış yapmak istersiniz?',
        'donate_invoice_sent': '⭐️ {stars} yıldızlık bağış faturası size özelden gönderildi. Lütfen ödemeyi tamamlayın.',
        'help_text': '''📖 YARDIM MERKEZİ 📖

━━━━━━━━━━━━━━━━━
🛍 Mağaza Nedir ⁉️
Botun ana satış alanıdır. Kategoriler halinde düzenlenmiş ürünleri buradan satın alabilirsiniz.

━━━━━━━━━━━━━━━━━
👑 VIP Mağaza ve Üyelik ⁉️
VIP mağaza yalnızca VIP üyelere özel ürünler içerir. 20 referans getirerek VIP olabilirsiniz.

━━━━━━━━━━━━━━━━━
💎 Puan Nasıl Kazanılır ⁉️
• Davet linkinizle arkadaş getirince +1 Puan (VIP: +2 Puan)
• Her gün günlük bonus: +1 Puan (VIP: günde 2 kez)
• Admin tarafından manuel puan yüklenmesiyle

━━━━━━━━━━━━━━━━━
📦 Sipariş Takibi Nasıl Çalışır ⁉️
Satın aldığınız her ürün için otomatik bir Sipariş ID oluşturulur.

Sipariş durumları:
🟡 Alındı — Sisteme kaydedildi
🔵 İşlemde — Hazırlanıyor
🟢 Teslim Edildi — Size iletildi

━━━━━━━━━━━━━━━━━
⁉️ Destek İçin: Destek butonu üzerinden ulaşabilirsiniz ⁉️''',
        'coupon_maintenance': '🔧 Kupon Sistemi Tamirde',
        'generic_error': '⚠️ Bir şeyler ters gitti, lütfen tekrar deneyin.',
    },
    'EN': {
        'welcome': '☀️ Hello\n\n👾 Eren SMM TR\nTurkey\'s trusted digital product marketplace.\n\nSelect an operation:',
        'balance': '💎 Balance',
        'profile': '👤 Profile',
        'shop': '🛍️ Shop',
        'vip_shop': '👑 VIP Shop',
        'daily_bonus': '🎁 Daily Bonus',
        'orders': '📦 My Orders',
        'transfer': '💰 Points Transfer',
        'coupon': '🎫 Coupon Code',
        'referral': '🤝 Referral',
        'support': '💬 Support',
        'help': '❓ Help',
        'language': '🌍 Language',
        'raffle': '🎲 Raffle',
        'donate': '⭐️ Donate',
        'back_to_menu': '← Back to Menu',
        'profile_text': '👤 Profile Summary\n\n🆔 User ID: {user_id}\n💎 Wallet Balance: {balance} Points\n🤝 Referred: {referrals} People\n💼 Total Orders: {orders}\n📆 Registration Date: {reg_date}\n\n💡 As VIP: 2x Daily Bonus, +2 Referral Points, access to VIP Shop!',
        'daily_bonus_success': '🎁 Daily Bonus Claimed!\n\n➕ +1 Point added to your account!\n💎 New Balance: {balance} Points\n\n👍 You\'ve used all your bonus rights for today!',
        'daily_bonus_used': '⏳ Come back tomorrow!\n\nNext bonus: {time}',
        'insufficient_balance': '❌ Insufficient Balance!\nRequired: {needed} Points\nYour Balance: {balance} Points',
        'transfer_info': '💰 Points Transfer System\n\n💎 Your Balance: {balance} Points\n⏳ Daily Limit: {daily_left}/2 left\n\n1️⃣ The bot deducts 1 Point commission per transfer.\n👤 Enter recipient ID and amount to transfer.\n\nFormat: RecipientID|Amount\nE.g.: 1234567|10',
        'transfer_format_error': '❌ Invalid format!\nCorrect format: RecipientID|Amount\nE.g.: 1234567|10',
        'transfer_success': '✅ Transfer Successful!\n\n📤 You sent {amount} Points\n👤 Recipient: {receiver_id}\n💸 Commission: 1 Point\n💎 New Balance: {new_balance} Points',
        'transfer_limit_reached': '⏳ Your daily transfer limit is reached!\n\nYou can make at most 2 transfers per day. Try again tomorrow.',
        'shop_welcome': '👋 Welcome to the Shop!\n\nSelect a category:',
        'tiktok_smm': '🎵 TikTok SMM',
        'telegram_smm': '📱 Telegram SMM',
        'category_empty': '📦 {category}\n\nNo products in this category yet.\nComing soon!',
        'vip_shop_welcome': '👑 Welcome to the VIP Shop!\n\nExclusive VIP products:',
        'vip_required_alert': '⚠️ Please become VIP first!\n\nVIP membership is required to access the VIP shop.',
        'no_orders': '📦 Your Order History\n\nYou have no orders yet.',
        'referral_link': '🤝 Invite, Earn!\n\n👇 Invite your friends with your personal link below, earn +1 Point instantly for every new signup.\n\n📋 Your Link:\nhttps://t.me/ErenSMMBot?start={user_id}',
        'support_text': '💬 Support Center\n\n⚠️ Please don\'t disturb the admin unnecessarily.\nOnly send a message for a real issue, faulty order, or emergency.\nCheck the Help menu first for FAQs.\n\n💎 Your Balance: {balance} Points\n\n━━━━━━━━━━━━━━━━━\nWrite your issue or request below.\nType /iptal to cancel.',
        'no_active_raffle': '🎲 Raffle\n\n⚠️ There is no active raffle right now.\n\nStay tuned for new raffles!',
        'donate_text': '⭐️ Donate\n\nAs Dextroo SMM TR, we work hard to always provide you better, faster, longer-lasting and more affordable service.\n\nIf you are happy with our services, you can support us with a star donation. Every contribution means a lot to us. Thank you! 🙏\n\nHow many stars would you like to donate?',
        'donate_invoice_sent': '⭐️ A {stars}-star donation invoice has been sent to you in private. Please complete the payment.',
        'help_text': '''📖 HELP CENTER 📖

━━━━━━━━━━━━━━━━━
🛍 What is the Shop ⁉️
The bot's main sales area. You can buy products organized into categories here.

━━━━━━━━━━━━━━━━━
👑 VIP Shop & Membership ⁉️
The VIP shop contains products exclusive to VIP members. You can become VIP by bringing 20 referrals.

━━━━━━━━━━━━━━━━━
💎 How to Earn Points ⁉️
• +1 Point when a friend joins via your link (VIP: +2 Points)
• Daily bonus every day: +1 Point (VIP: 2 times a day)
• Manual point top-up by the admin

━━━━━━━━━━━━━━━━━
📦 How Order Tracking Works ⁉️
An automatic Order ID is created for every product you purchase.

Order statuses:
🟡 Received — Recorded in the system
🔵 Processing — Being prepared
🟢 Delivered — Sent to you

━━━━━━━━━━━━━━━━━
⁉️ For Support: Use the Support button ⁉️''',
        'coupon_maintenance': '🔧 Coupon System Under Maintenance',
        'generic_error': '⚠️ Something went wrong, please try again.',
    }
}

# ===== HELPER FUNCTIONS =====
def get_user(user_id):
    """Kullanıcı bilgisini al"""
    try:
        conn = get_db()
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
        user = c.fetchone()
        c.close()
        conn.close()
        return user
    except Exception as e:
        logger.error(f"get_user error: {e}")
        return None

def create_user(user_id, username):
    """Yeni kullanıcı yaratmaq"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''INSERT INTO users (user_id, username, balance, registration_date)
                     VALUES (%s, %s, %s, %s)
                     ON CONFLICT (user_id) DO NOTHING''',
                  (user_id, username, START_BALANCE, datetime.now().strftime('%Y-%m-%d %H:%M')))
        conn.commit()
        c.close()
        conn.close()
    except Exception as e:
        logger.error(f"create_user error: {e}")

def update_balance(user_id, amount):
    """Bakiyəni dəyiştirmək"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('UPDATE users SET balance = balance + %s WHERE user_id = %s',
                  (amount, user_id))
        conn.commit()
        c.close()
        conn.close()
    except Exception as e:
        logger.error(f"update_balance error: {e}")

def get_user_language(user_id):
    """İstifadəçinin dilini al"""
    try:
        user = get_user(user_id)
        return user['language'] if user and user['language'] else 'TR'
    except:
        return 'TR'

def get_text(key, user_id, **kwargs):
    """Dil text'ini al"""
    lang = get_user_language(user_id)
    text = LANG.get(lang, LANG['TR']).get(key, LANG['TR'].get(key, ''))
    return text.format(**kwargs) if kwargs else text

async def safe_edit(query, text, reply_markup=None):
    """edit_message_text-i xəta tutaraq çağır (eyni mətn/qarışıq markup botu çökərtməsin)"""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            # İçerik eyni idi, problem deyil
            try:
                await query.answer()
            except Exception:
                pass
        else:
            logger.error(f"safe_edit error: {e}")
    except Exception as e:
        logger.error(f"safe_edit unexpected error: {e}")

def get_products_by_category(category, vip_only=None):
    """Kateqoriyaya uyğun məhsulları gətir"""
    try:
        conn = get_db()
        c = conn.cursor(cursor_factory=RealDictCursor)
        if vip_only is None:
            c.execute('SELECT * FROM products WHERE category = %s', (category,))
        else:
            c.execute('SELECT * FROM products WHERE category = %s AND vip_only = %s', (category, vip_only))
        products = c.fetchall()
        c.close()
        conn.close()
        return products
    except Exception as e:
        logger.error(f"get_products_by_category error: {e}")
        return []

def get_all_vip_products():
    try:
        conn = get_db()
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT * FROM products WHERE vip_only = TRUE')
        products = c.fetchall()
        c.close()
        conn.close()
        return products
    except Exception as e:
        logger.error(f"get_all_vip_products error: {e}")
        return []

def main_menu_keyboard(user_id):
    keyboard = [
        [InlineKeyboardButton(get_text('balance', user_id), callback_data='balance'),
         InlineKeyboardButton(get_text('profile', user_id), callback_data='profile')],
        [InlineKeyboardButton(get_text('shop', user_id), callback_data='shop'),
         InlineKeyboardButton(get_text('vip_shop', user_id), callback_data='vip_shop')],
        [InlineKeyboardButton(get_text('daily_bonus', user_id), callback_data='daily_bonus'),
         InlineKeyboardButton(get_text('orders', user_id), callback_data='orders')],
        [InlineKeyboardButton(get_text('transfer', user_id), callback_data='transfer'),
         InlineKeyboardButton(get_text('coupon', user_id), callback_data='coupon')],
        [InlineKeyboardButton(get_text('referral', user_id), callback_data='referral'),
         InlineKeyboardButton(get_text('support', user_id), callback_data='support')],
        [InlineKeyboardButton(get_text('help', user_id), callback_data='help'),
         InlineKeyboardButton(get_text('language', user_id), callback_data='language')],
        [InlineKeyboardButton(get_text('raffle', user_id), callback_data='raffle'),
         InlineKeyboardButton(get_text('donate', user_id), callback_data='donate')]
    ]
    return InlineKeyboardMarkup(keyboard)

# ===== MAIN HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Başlanğıc komandası"""
    # Bu fonksiyon hem mesajdan hem de callback'ten (geri dön) çağırılabilir
    if update.message:
        user = update.message.from_user
        user_id = user.id
    else:
        user = update.callback_query.from_user
        user_id = user.id

    existing_user = get_user(user_id)
    if not existing_user:
        create_user(user_id, user.username or f"User{user_id}")

    # Referral sistem (yalnız /start mesajla gəldikdə işləsin)
    if update.message and context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id:
                conn = get_db()
                c = conn.cursor(cursor_factory=RealDictCursor)

                # Referral mövcud mu kontrol et
                c.execute('SELECT * FROM referrals WHERE referrer_id = %s AND referred_user_id = %s',
                         (referrer_id, user_id))
                if not c.fetchone():
                    referrer = get_user(referrer_id)
                    if referrer:
                        bonus = 2 if referrer['vip_status'] else 1
                        c.execute('''INSERT INTO referrals (referrer_id, referred_user_id, referral_date)
                                   VALUES (%s, %s, %s)''',
                                 (referrer_id, user_id, datetime.now().strftime('%Y-%m-%d %H:%M')))
                        c.execute('UPDATE users SET referrals = referrals + 1 WHERE user_id = %s',
                                 (referrer_id,))
                        update_balance(referrer_id, bonus)
                        conn.commit()

                c.close()
                conn.close()
        except Exception as e:
            logger.error(f"referral error: {e}")

    reply_markup = main_menu_keyboard(user_id)
    welcome_text = get_text('welcome', user_id)

    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    else:
        await safe_edit(update.callback_query, welcome_text, reply_markup)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Düymə klikləri"""
    query = update.callback_query
    user_id = query.from_user.id

    try:
        await query.answer()
    except Exception as e:
        logger.error(f"query.answer error: {e}")

    back_btn = [[InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]]

    try:
        if query.data == 'balance':
            user = get_user(user_id)
            balance = user['balance'] if user else 0
            text = f"💎 {get_text('balance', user_id)}: {balance} Puan"
            await safe_edit(query, text, InlineKeyboardMarkup(back_btn))

        elif query.data == 'profile':
            user = get_user(user_id)
            if user:
                try:
                    conn = get_db()
                    c = conn.cursor()
                    c.execute('SELECT COUNT(*) FROM orders WHERE user_id = %s', (user_id,))
                    order_count = c.fetchone()[0]
                    c.close()
                    conn.close()
                except Exception as e:
                    logger.error(f"profile order count error: {e}")
                    order_count = 0

                text = get_text('profile_text', user_id,
                               user_id=user['user_id'],
                               balance=user['balance'],
                               referrals=user['referrals'],
                               orders=order_count,
                               reg_date=user['registration_date'])
                keyboard = [[InlineKeyboardButton(get_text('daily_bonus', user_id), callback_data='daily_bonus'),
                             InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]]
                await safe_edit(query, text, InlineKeyboardMarkup(keyboard))
            else:
                await safe_edit(query, get_text('generic_error', user_id), InlineKeyboardMarkup(back_btn))

        elif query.data == 'daily_bonus':
            user = get_user(user_id)
            if user:
                can_use = True
                if user['last_bonus_date']:
                    last_date = datetime.strptime(user['last_bonus_date'], '%Y-%m-%d')
                    if (datetime.now() - last_date).days == 0:
                        can_use = False

                if not can_use:
                    text = get_text('daily_bonus_used', user_id, time='24:00')
                    await query.answer(text, show_alert=True)
                    return

                update_balance(user_id, 1)
                try:
                    conn = get_db()
                    c = conn.cursor()
                    c.execute('UPDATE users SET last_bonus_date = %s WHERE user_id = %s',
                             (datetime.now().strftime('%Y-%m-%d'), user_id))
                    conn.commit()
                    c.close()
                    conn.close()
                except Exception as e:
                    logger.error(f"daily_bonus error: {e}")

                new_balance = user['balance'] + 1
                text = get_text('daily_bonus_success', user_id, balance=new_balance)
                await safe_edit(query, text, InlineKeyboardMarkup(back_btn))
            else:
                await safe_edit(query, get_text('generic_error', user_id), InlineKeyboardMarkup(back_btn))

        elif query.data == 'referral':
            text = get_text('referral_link', user_id, user_id=user_id)
            await safe_edit(query, text, InlineKeyboardMarkup(back_btn))

        elif query.data == 'language':
            keyboard = [
                [InlineKeyboardButton('🇹🇷 Türkçe', callback_data='lang_tr'),
                 InlineKeyboardButton('🇬🇧 English', callback_data='lang_en')],
                back_btn[0]
            ]
            await safe_edit(query, '🌍 Lütfen dil tercihinizi yapın / Please select your language:', InlineKeyboardMarkup(keyboard))

        elif query.data == 'lang_tr':
            try:
                conn = get_db()
                c = conn.cursor()
                c.execute('UPDATE users SET language = %s WHERE user_id = %s', ('TR', user_id))
                conn.commit()
                c.close()
                conn.close()
            except Exception as e:
                logger.error(f"lang_tr error: {e}")
            await start(update, context)

        elif query.data == 'lang_en':
            try:
                conn = get_db()
                c = conn.cursor()
                c.execute('UPDATE users SET language = %s WHERE user_id = %s', ('EN', user_id))
                conn.commit()
                c.close()
                conn.close()
            except Exception as e:
                logger.error(f"lang_en error: {e}")
            await start(update, context)

        elif query.data == 'shop':
            keyboard = [
                [InlineKeyboardButton(get_text('tiktok_smm', user_id), callback_data='shop_tiktok'),
                 InlineKeyboardButton(get_text('telegram_smm', user_id), callback_data='shop_telegram')],
                back_btn[0]
            ]
            await safe_edit(query, get_text('shop_welcome', user_id), InlineKeyboardMarkup(keyboard))

        elif query.data == 'shop_tiktok' or query.data == 'shop_telegram':
            category = 'TikTok' if query.data == 'shop_tiktok' else 'Telegram'
            products = get_products_by_category(category, vip_only=False)

            if not products:
                cat_label = get_text('tiktok_smm', user_id) if category == 'TikTok' else get_text('telegram_smm', user_id)
                text = get_text('category_empty', user_id, category=cat_label)
                back_to_shop = [[InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='shop')]]
                await safe_edit(query, text, InlineKeyboardMarkup(back_to_shop))
            else:
                text = f"📦 {category} SMM\n\n"
                keyboard = []
                for p in products:
                    text += f"• {p['name']} — 💰{p['price']} Puan (📦{p['stock']} stok)\n"
                    keyboard.append([InlineKeyboardButton(f"{p['name']} ({p['price']}P)", callback_data=f"buy_{p['product_id']}")])
                keyboard.append([InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='shop')])
                await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

        elif query.data == 'vip_shop':
            user = get_user(user_id)
            if not user or not user['vip_status']:
                await query.answer(get_text('vip_required_alert', user_id), show_alert=True)
                return

            products = get_all_vip_products()
            if not products:
                text = get_text('category_empty', user_id, category=get_text('vip_shop', user_id))
                await safe_edit(query, text, InlineKeyboardMarkup(back_btn))
            else:
                text = get_text('vip_shop_welcome', user_id) + "\n\n"
                keyboard = []
                for p in products:
                    text += f"• {p['name']} — 💰{p['price']} Puan (📦{p['stock']} stok)\n"
                    keyboard.append([InlineKeyboardButton(f"{p['name']} ({p['price']}P)", callback_data=f"buy_{p['product_id']}")])
                keyboard.append(back_btn[0])
                await safe_edit(query, text, InlineKeyboardMarkup(keyboard))

        elif query.data == 'orders':
            try:
                conn = get_db()
                c = conn.cursor(cursor_factory=RealDictCursor)
                c.execute('SELECT * FROM orders WHERE user_id = %s ORDER BY order_id DESC', (user_id,))
                orders = c.fetchall()
                c.close()
                conn.close()
            except Exception as e:
                logger.error(f"orders fetch error: {e}")
                orders = []

            if not orders:
                text = get_text('no_orders', user_id)
            else:
                text = f"📦 Siparişleriniz ({len(orders)} adet):\n\n"
                for order in orders:
                    text += f"ID: {order['order_id']} | Status: {order['status']}\n"

            await safe_edit(query, text, InlineKeyboardMarkup(back_btn))

        elif query.data == 'transfer':
            user = get_user(user_id)
            if user:
                daily_left = 2
                if user['last_transfer_date']:
                    last_date = datetime.strptime(user['last_transfer_date'], '%Y-%m-%d')
                    if (datetime.now() - last_date).days == 0:
                        daily_left = max(0, 2 - user['daily_transfer_count'])
                    else:
                        daily_left = 2

                if daily_left <= 0:
                    await safe_edit(query, get_text('transfer_limit_reached', user_id), InlineKeyboardMarkup(back_btn))
                    return

                text = get_text('transfer_info', user_id, balance=user['balance'], daily_left=daily_left)
                await safe_edit(query, text, InlineKeyboardMarkup(back_btn))

                context.user_data['awaiting_transfer'] = True
            else:
                await safe_edit(query, get_text('generic_error', user_id), InlineKeyboardMarkup(back_btn))

        elif query.data == 'raffle':
            text = get_text('no_active_raffle', user_id)
            await safe_edit(query, text, InlineKeyboardMarkup(back_btn))

        elif query.data == 'donate':
            buttons = [
                [InlineKeyboardButton('⭐️ 5', callback_data='donate_5'),
                 InlineKeyboardButton('⭐️ 10', callback_data='donate_10')],
                [InlineKeyboardButton('⭐️ 15', callback_data='donate_15'),
                 InlineKeyboardButton('⭐️ 20', callback_data='donate_20')],
                [InlineKeyboardButton('⭐️ 25', callback_data='donate_25'),
                 InlineKeyboardButton('⭐️ 30', callback_data='donate_30')],
                [InlineKeyboardButton('⭐️ 35', callback_data='donate_35'),
                 InlineKeyboardButton('⭐️ 40', callback_data='donate_40')],
                [InlineKeyboardButton('⭐️ 45', callback_data='donate_45'),
                 InlineKeyboardButton('⭐️ 50', callback_data='donate_50')],
                [InlineKeyboardButton('⭐️ 75', callback_data='donate_75'),
                 InlineKeyboardButton('⭐️ 100', callback_data='donate_100')],
                back_btn[0]
            ]
            await safe_edit(query, get_text('donate_text', user_id), InlineKeyboardMarkup(buttons))

        elif query.data.startswith('donate_'):
            stars = int(query.data.split('_')[1])
            try:
                await context.bot.send_invoice(
                    chat_id=user_id,
                    title=f'Eren SMM - {stars} Yıldız Bağış',
                    description=f'{stars} yıldız bağışı yapın',
                    payload=f'donate_{stars}_{user_id}',
                    provider_token='',
                    currency='XTR',
                    prices=[{'label': f'{stars} Yıldız', 'amount': stars}]
                )
                text = get_text('donate_invoice_sent', user_id, stars=stars)
                await safe_edit(query, text, InlineKeyboardMarkup(back_btn))
            except Exception as e:
                logger.error(f"send_invoice error: {e}")
                await safe_edit(query, get_text('generic_error', user_id), InlineKeyboardMarkup(back_btn))

        elif query.data == 'coupon':
            text = get_text('coupon_maintenance', user_id)
            await safe_edit(query, text, InlineKeyboardMarkup(back_btn))

        elif query.data == 'support':
            user = get_user(user_id)
            text = get_text('support_text', user_id, balance=user['balance'] if user else 0)
            await safe_edit(query, text, InlineKeyboardMarkup(back_btn))
            context.user_data['awaiting_support'] = True

        elif query.data == 'help':
            await safe_edit(query, get_text('help_text', user_id), InlineKeyboardMarkup(back_btn))

        elif query.data == 'main_menu':
            context.user_data['awaiting_transfer'] = False
            context.user_data['awaiting_support'] = False
            await start(update, context)

        elif query.data.startswith('buy_'):
            # Sadə alış axını - mövcud strukturu pozmadan minimal işlək hala gətirildi
            product_id = int(query.data.split('_')[1])
            try:
                conn = get_db()
                c = conn.cursor(cursor_factory=RealDictCursor)
                c.execute('SELECT * FROM products WHERE product_id = %s', (product_id,))
                product = c.fetchone()
                c.close()
                conn.close()
            except Exception as e:
                logger.error(f"buy fetch product error: {e}")
                product = None

            if not product or product['stock'] <= 0:
                await query.answer('❌ Ürün bulunamadı veya stok yok!', show_alert=True)
                return

            user = get_user(user_id)
            if not user or user['balance'] < product['price']:
                await query.answer(get_text('insufficient_balance', user_id,
                                             needed=product['price'],
                                             balance=user['balance'] if user else 0), show_alert=True)
                return

            await query.answer('🛒 Sipariş için kullanıcıya özel mesajla profil linki istenecek (bu adım projenize göre genişletilebilir).', show_alert=True)

        else:
            # Tanınmayan callback - en azından menüye dönsün
            logger.warning(f"Bilinmeyen callback_data: {query.data}")
            await start(update, context)

    except Exception as e:
        logger.error(f"button_click genel hata: {e}")
        try:
            await safe_edit(query, get_text('generic_error', user_id), InlineKeyboardMarkup(back_btn))
        except Exception:
            pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mesaj handler'ı"""
    user_id = update.message.from_user.id
    text = update.message.text

    if context.user_data.get('awaiting_transfer'):
        if text == '/iptal':
            context.user_data['awaiting_transfer'] = False
            await update.message.reply_text('❌ İptal edildi.')
            return

        try:
            parts = text.split('|')
            if len(parts) != 2:
                await update.message.reply_text(get_text('transfer_format_error', user_id))
                return

            receiver_id = int(parts[0].strip())
            amount = int(parts[1].strip())

            if amount <= 0:
                await update.message.reply_text(get_text('transfer_format_error', user_id))
                return

            if receiver_id == user_id:
                await update.message.reply_text('❌ Kendinize transfer yapamazsınız!')
                return

            user = get_user(user_id)
            if not user or user['balance'] < amount + 1:
                needed = amount + 1
                balance = user['balance'] if user else 0
                await update.message.reply_text(
                    get_text('insufficient_balance', user_id,
                            needed=needed,
                            balance=balance))
                return

            # Günlük transfer limiti kontrolü
            daily_left = 2
            if user['last_transfer_date']:
                last_date = datetime.strptime(user['last_transfer_date'], '%Y-%m-%d')
                if (datetime.now() - last_date).days == 0:
                    daily_left = max(0, 2 - user['daily_transfer_count'])
            if daily_left <= 0:
                context.user_data['awaiting_transfer'] = False
                await update.message.reply_text(get_text('transfer_limit_reached', user_id))
                return

            receiver = get_user(receiver_id)
            if not receiver:
                await update.message.reply_text('❌ Alıcı kullanıcı bulunamadı!')
                return

            try:
                conn = get_db()
                c = conn.cursor()

                today = datetime.now().strftime('%Y-%m-%d')
                # Yeni gün ise transfer sayacını sıfırla, değilse +1
                if user['last_transfer_date'] == today:
                    c.execute('UPDATE users SET daily_transfer_count = daily_transfer_count + 1 WHERE user_id = %s',
                             (user_id,))
                else:
                    c.execute('UPDATE users SET daily_transfer_count = 1, last_transfer_date = %s WHERE user_id = %s',
                             (today, user_id))

                c.execute('UPDATE users SET balance = balance - %s WHERE user_id = %s', (amount + 1, user_id))
                c.execute('UPDATE users SET balance = balance + %s WHERE user_id = %s', (amount, receiver_id))

                c.execute('''INSERT INTO transfers (sender_id, receiver_id, amount, transfer_date)
                            VALUES (%s, %s, %s, %s)''',
                         (user_id, receiver_id, amount, datetime.now().strftime('%Y-%m-%d %H:%M')))

                conn.commit()
                c.close()
                conn.close()
            except Exception as e:
                logger.error(f"transfer error: {e}")
                await update.message.reply_text('❌ Transfer yapılamadı!')
                return

            context.user_data['awaiting_transfer'] = False
            new_balance = user['balance'] - (amount + 1)

            success_msg = get_text('transfer_success', user_id,
                                  amount=amount,
                                  receiver_id=receiver_id,
                                  new_balance=new_balance)
            await update.message.reply_text(success_msg)

            # Log kanal'a göndir
            log_msg = f"💸 YENİ TRANSFER\n\n👤 Gönderen: {user_id}\n👤 Alan: {receiver_id}\n💎 Miktar: {amount}\n💰 Komisyon: 1\n📅 Zaman: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            try:
                await context.bot.send_message(LOG_CHANNEL, log_msg)
            except Exception as e:
                logger.error(f"log channel error: {e}")

            # Alıcıya xəbər ver
            receiver_msg = f"✅ {user_id} sizə {amount} Puan gönderdi!\n💎 Yeni Bakiye: {receiver['balance'] + amount}"
            try:
                await context.bot.send_message(receiver_id, receiver_msg)
            except Exception as e:
                logger.error(f"receiver notify error: {e}")

        except ValueError:
            await update.message.reply_text(get_text('transfer_format_error', user_id))

    elif context.user_data.get('awaiting_support'):
        if text == '/iptal':
            context.user_data['awaiting_support'] = False
            await update.message.reply_text('❌ İptal edildi.')
            return

        context.user_data['awaiting_support'] = False

        # Admin'ə göndər
        support_log = f"💬 YENİ DESTEK MESAJI\n\n👤 Kullanıcı: {user_id}\n💬 Mesaj:\n{text}\n\n📅 Zaman: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        try:
            await context.bot.send_message(LOG_CHANNEL, support_log)
        except Exception as e:
            logger.error(f"support log channel error: {e}")
        try:
            await context.bot.send_message(ADMIN_ID, f"Yeni destek mesajı:\n\nKullanıcı: {user_id}\nMesaj: {text}")
        except Exception as e:
            logger.error(f"support admin notify error: {e}")

        await update.message.reply_text('✅ Mesajınız iletildi. Yakında sizinle iletişime geçeceğiz.')

# ===== ADMIN COMMANDS =====
async def admin_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ürün əlavə et"""
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return

    if len(context.args) < 4:
        await update.message.reply_text('📝 Kullanım: /admin_add_product "ad" kategori fiyat stok [vip]')
        return

    try:
        vip_only = False
        args = context.args
        if args[-1].lower() in ('vip', 'true', '1'):
            vip_only = True
            args = args[:-1]

        name = ' '.join(args[:-3]).strip('"')
        category = args[-3]
        price = int(args[-2])
        stock = int(args[-1])

        try:
            conn = get_db()
            c = conn.cursor()
            c.execute('''INSERT INTO products (name, category, price, stock, vip_only)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING product_id''',
                     (name, category, price, stock, vip_only))
            product_id = c.fetchone()[0]
            conn.commit()
            c.close()
            conn.close()

            vip_tag = '👑 VIP' if vip_only else ''
            await update.message.reply_text(f'✅ Ürün eklendi!\n\nID: {product_id}\n📝 Ad: {name}\n📂 Kategori: {category}\n💰 Fiyat: {price}\n📦 Stok: {stock} {vip_tag}')
        except Exception as e:
            logger.error(f"add_product error: {e}")
            await update.message.reply_text(f'❌ Hata: {str(e)}')
    except Exception as e:
        await update.message.reply_text(f'❌ Hata: {str(e)}')

async def admin_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stok dəyiştir"""
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return

    if len(context.args) < 2:
        await update.message.reply_text('📝 Kullanım: /admin_stock <ürün_id> <yeni_stok>')
        return

    try:
        product_id = int(context.args[0])
        new_stock = int(context.args[1])

        try:
            conn = get_db()
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute('UPDATE products SET stock = %s WHERE product_id = %s',
                     (new_stock, product_id))
            c.execute('SELECT name, stock FROM products WHERE product_id = %s', (product_id,))
            product = c.fetchone()
            conn.commit()
            c.close()
            conn.close()

            if product:
                await update.message.reply_text(f'✅ Stok güncellendi!\n\n📝 Ürün: {product["name"]}\n📦 Yeni Stok: {new_stock}')
            else:
                await update.message.reply_text('❌ Ürün bulunamadı!')
        except Exception as e:
            logger.error(f"stock error: {e}")
            await update.message.reply_text(f'❌ Hata: {str(e)}')
    except Exception as e:
        await update.message.reply_text(f'❌ Hata: {str(e)}')

async def admin_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bütün məhsulları göstər"""
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return

    try:
        conn = get_db()
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT product_id, name, category, price, stock, vip_only FROM products')
        products = c.fetchall()
        c.close()
        conn.close()
    except Exception as e:
        logger.error(f"products error: {e}")
        products = []

    if not products:
        await update.message.reply_text('📦 Ürün bulunamadı!')
        return

    text = '📦 TÜM ÜRÜNLER\n\n'
    for p in products:
        vip_tag = '👑' if p['vip_only'] else ''
        text += f"ID: {p['product_id']} | {p['name']} ({p['category']}) | 💰{p['price']} | 📦{p['stock']} {vip_tag}\n"

    await update.message.reply_text(text)

async def admin_give_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Puan ver"""
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return

    if len(context.args) < 2:
        await update.message.reply_text('📝 Kullanım: /admin_give <user_id> <puan>')
        return

    try:
        user_id = int(context.args[0])
        points = int(context.args[1])

        user_before = get_user(user_id)
        if not user_before:
            await update.message.reply_text('❌ Kullanıcı bulunamadı!')
            return

        update_balance(user_id, points)

        user_after = get_user(user_id)
        await update.message.reply_text(f'✅ {points} puan verildi!\n\n👤 ID: {user_id}\n💎 Yeni Bakiye: {user_after["balance"]}')
    except Exception as e:
        await update.message.reply_text(f'❌ Hata: {str(e)}')

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """İstatistika"""
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return

    try:
        conn = get_db()
        c = conn.cursor()

        c.execute('SELECT COUNT(*) FROM users')
        total_users = c.fetchone()[0]

        c.execute('SELECT COUNT(*) FROM users WHERE vip_status = true')
        vip_users = c.fetchone()[0]

        c.execute('SELECT COUNT(*) FROM orders')
        total_orders = c.fetchone()[0]

        c.execute('SELECT SUM(balance) FROM users')
        total_balance = c.fetchone()[0] or 0

        c.execute('SELECT COUNT(*) FROM products')
        total_products = c.fetchone()[0]

        c.close()
        conn.close()

        text = f'''📊 BOT STATİSTİKLERİ

👥 Toplam Kullanıcı: {total_users}
👑 VIP Kullanıcı: {vip_users}
📦 Toplam Sipariş: {total_orders}
💎 Toplam Bakiye: {total_balance}
🛍️ Toplam Ürün: {total_products}
📅 Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}'''

        await update.message.reply_text(text)
    except Exception as e:
        logger.error(f"stats error: {e}")
        await update.message.reply_text(f'❌ Hata: {str(e)}')

# ===== MAIN =====
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Admin commands
    app.add_handler(CommandHandler('admin_add_product', admin_add_product))
    app.add_handler(CommandHandler('admin_stock', admin_stock))
    app.add_handler(CommandHandler('admin_products', admin_products))
    app.add_handler(CommandHandler('admin_give', admin_give_points))
    app.add_handler(CommandHandler('admin_stats', admin_stats))

    logger.info("Bot başlatılıyor...")
    app.run_polling()

if __name__ == '__main__':
    main()
