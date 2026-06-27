import logging
import os
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import BadRequest
from telegram.constants import ParseMode
from datetime import datetime, timedelta

# ===== CONFIGURATION =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "8034872992"))
LOG_CHANNEL = int(os.getenv("LOG_CHANNEL", "-1003895644077"))
START_BALANCE = int(os.getenv("START_BALANCE", "0"))
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/eren_smm")
BOT_USERNAME = os.getenv("BOT_USERNAME", "DrxtrooMarketBot")
VIP_REFERRAL_REQUIREMENT = int(os.getenv("VIP_REFERRAL_REQUIREMENT", "20"))

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== DATABASE CONNECTION POOL =====
# Hər kliklə yeni TCP bağlantısı açmaq gecikməyə səbəb olur.
# Pool ilə bağlantılar yenidən istifadə olunur -> butonlar daha tez cavab verir.
db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, DATABASE_URL)

def get_conn():
    return db_pool.getconn()

def put_conn(conn):
    db_pool.putconn(conn)

def init_db():
    """Database cədvəllərini yaratmaq"""
    conn = get_conn()
    try:
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

        c.execute('CREATE INDEX IF NOT EXISTS idx_users_id ON users(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_transfers_sender ON transfers(sender_id)')

        conn.commit()
        c.close()
        logger.info("Database başlatıldı")
    finally:
        put_conn(conn)

try:
    init_db()
except Exception as e:
    logger.error(f"Database başlatma hatası: {e}")

# ===== LANGUAGE (HTML format ilə) =====
# <b>bold</b>, <i>italic</i> taglarından istifadə edilir.
# Bütün mesajlar parse_mode=HTML ilə göndərilir.
LANG = {
    'TR': {
        'welcome': '☀️ Merhaba\n\n👾 <b>Eren SMM TR</b>\nTürkiye\'nin güvenilir dijital ürün marketi.\n\nİşlem seçin:',
        'balance': '💎 Bakiye',
        'profile': '👤 Profilim',
        'shop': '🛍️ Mağaza',
        'vip_button': '👑 VIP Ol • 20 Referans',
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

        'profile_text': (
            '👤 <b>Profil Özeti</b>\n\n'
            '🆔 <b>Kullanıcı ID:</b> {user_id}\n'
            '💎 <b>Cüzdan Bakiyesi:</b> {balance} Puan\n'
            '🤝 <b>Davet Edilen:</b> {referrals} Kişi\n'
            '💼 <b>Toplam Sipariş:</b> {orders}\n'
            '📆 <b>Kayıt Tarihi:</b> {reg_date}\n\n'
            '💡 VIP olarak: 2x Günlük Bonus, +2 Davet Puanı, VIP Mağazaya erişim!'
        ),

        'daily_bonus_success': (
            '🎁 <b>Günlük Bonus Alındı!</b>\n\n'
            '➕ +1 Puan hesabınıza eklendi!\n'
            '💎 Yeni Bakiye: {balance} Puan\n\n'
            '👍 Bugünkü tüm bonus haklarını kullandın!'
        ),
        'daily_bonus_success_vip': (
            '🎁 <b>Günlük Bonus Alındı!</b>\n\n'
            '➕ +1 Puan hesabınıza eklendi!\n'
            '💎 Yeni Bakiye: {balance} Puan\n\n'
            '👑 VIP olarak bugün {used}/2 bonus hakkını kullandın!'
        ),
        'daily_bonus_used': '⏳ Bugünkü bonus hakkını kullandın!\nYarın tekrar gel!',

        'insufficient_balance': '❌ Yetersiz Bakiye!\nGerekli: {needed} Puan\nBakiyeniz: {balance} Puan',

        'transfer_info': (
            '💰 <b>Puan Transfer Sistemi</b>\n\n'
            '💎 <b>Bakiyeniz:</b> {balance} Puan\n'
            '⏳ <b>Günlük Hak:</b> {daily_left}/2 kaldı\n\n'
            '1️⃣ Her transferde bot <b>1 Puan</b> komisyon keser.\n'
            '👤 Alıcı ID ve miktarı girerek transfer yapın.\n\n'
            'Format: AlıcıID|Miktar\n'
            'Örn: 1234567|10'
        ),
        'transfer_prompt': (
            '💰 <b>Transfer Bilgisi Girin</b>\n\n'
            'Format: AlıcıID|Miktar\n'
            'Örn: 1234567|10\n\n'
            '⚠️ Bot <b>1 Puan</b> komisyon keser.\n'
            '💎 <b>Bakiyeniz:</b> {balance} Puan\n\n'
            'İptal: /iptal'
        ),
        'transfer_cancelled': '⚠️ Transfer iptal edildi.',
        'transfer_format_error': '❌ Hatalı format!\nDoğru format: AlıcıID|Miktar\nÖrn: 1234567|10',
        'transfer_success': '✅ Transfer Başarılı!\n\n📤 {amount} Puan gönderdiniz\n👤 Alıcı: {receiver_id}\n💸 Komisyon: 1 Puan\n💎 Yeni Bakiye: {new_balance} Puan',
        'transfer_limit_reached': '⏳ Günlük transfer hakkınız bitti!\n\nGünde en fazla 2 transfer yapabilirsiniz. Yarın tekrar deneyin.',

        'shop_welcome': '👋 <b>Normal Mağazaya Hoşgeldiniz!</b>\n\nBir kategori seçin:',
        'tiktok_smm': '🎵 TikTok Smm',
        'telegram_smm': '📱 Telegram Smm',
        'category_empty': '📦 {category}\n\nBu kategoride henüz ürün bulunmuyor.\nYakında eklenecek!',

        'vip_shop_welcome': '👑 <b>VIP Mağazaya Hoşgeldiniz!</b>\n\nÖzel VIP ürünleri:',
        'vip_required_alert': '👑 Lütfen önce VIP olun!\nVIP mağazaya erişmek için VIP üyeliğiniz gerekiyor.',

        'vip_purchase_text': (
            '👍 <b>VIP Satın Al</b>\n\n'
            'VIP olmak için <b>{required} referans</b> şart!\n\n'
            '👍 Mevcut referansınız: <b>{current}/{required}</b>\n'
            '👍 Eksik referans: <b>{missing} kişi</b> daha davet edin!\n\n'
            '• 👍 <b>VIP Avantajları:</b>\n'
            '• 👍 VIP Mağazaya erişim\n'
            '• 👍 Günde 2 kez günlük bonus\n'
            '• 👍 Her davette <b>+2 Puan</b>'
        ),
        'vip_already': (
            '👑 <b>Zaten VIP üyesiniz!</b>\n\n'
            '✅ VIP Mağazaya erişiminiz var\n'
            '✅ Günde 2 kez günlük bonus hakkınız var\n'
            '✅ Her davette +2 Puan kazanıyorsunuz'
        ),
        'vip_granted': (
            '🎉 <b>Tebrikler! VIP üye oldunuz!</b>\n\n'
            '👑 Artık VIP Mağazaya erişiminiz var\n'
            '🎁 Günde 2 kez günlük bonus alabilirsiniz\n'
            '🤝 Her davette +2 Puan kazanacaksınız'
        ),

        'no_orders': '📦 <b>Sipariş Geçmişiniz</b>\n\nHenüz hiç siparişiniz bulunmuyor.',

        'referral_link': (
            '🤝 <b>Davet Et, Kazan!</b>\n\n'
            '👇 Aşağıdaki kişisel linkinizle arkadaşlarınızı sisteme davet edin, her yeni katılımda anında <b>+1 Puan</b> kazanın.\n\n'
            '📋 <b>Sizin Linkiniz:</b>\n'
            'https://t.me/{bot_username}?start={user_id}'
        ),

        'support_text': (
            '💬 <b>Destek Merkezi</b>\n\n'
            '⚠️ <b>Lütfen admini boş yere rahatsız etmeyiniz.</b>\n'
            'Mesajınız yalnızca gerçek bir sorun, hatalı sipariş veya acil durum söz konusuysa iletilmelidir.\n'
            'Sık sorulan sorular için önce Yardım menüsünü inceleyin.\n\n'
            '💎 <b>Bakiyeniz:</b> {balance} Puan\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            'Sorununuzu veya talebinizi aşağıya yazın.\n'
            'İptal etmek için /iptal yazın.'
        ),
        'support_cancelled': '❌ İptal edildi.',
        'support_sent': '✅ Mesajınız iletildi. Yakında sizinle iletişime geçeceğiz.',

        'no_active_raffle': '🎲 <b>Çekiliş</b>\n\n⚠️ Şu anda aktif bir çekiliş bulunmuyor.\n\n<i>Yeni çekilişler için takipte kalın!</i>',

        'donate_text': (
            '⭐️ <b>Bağış Yap</b>\n\n'
            'Eren SMM TR olarak sizlere her zaman daha iyi, daha hızlı, daha uzun süre ve daha uygun fiyata hizmet verebilmek için büyük emek harcıyoruz.\n\n'
            'Eğer hizmetlerimizden memnun kaldıysanız, bize bir yıldız <b>bağışı</b> yaparak destek olabilirsiniz. Her katkı bizim için çok değerlidir. Sağ olun, var olun! 🙏\n\n'
            'Kaç yıldız <b>bağış</b> yapmak istersiniz?'
        ),
        'donate_invoice_sent': '⭐️ {stars} yıldızlık bağış faturası size özelden gönderildi. Lütfen ödemeyi tamamlayın.',

        'help_text': (
            '📖 <b>YARDIM MERKEZİ</b> 📖\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '🛍 Mağaza Nedir ⁉️\n'
            'Botun ana satış alanıdır. Kategoriler halinde düzenlenmiş ürünleri buradan satın alabilirsiniz. Bir ürüne tıklayınca fiyat ve stok bilgisi çıkar, satın al butonuna basınca puan düşülür ve siparişiniz oluşur.\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '👑 VIP Mağaza ve Üyelik ⁉️\n'
            'VIP mağaza yalnızca VIP üyelere özel ürünler içerir. 20 referans getirerek VIP olabilirsiniz.\n'
            'VIP avantajları: 👑 VIP Mağaza erişimi • 🎁 Günde 2x bonus • 🤝 Davette +2 Puan\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '💎 Puan Nasıl Kazanılır ⁉️\n'
            '• Davet linkinizle arkadaş getirince +1 Puan (VIP: +2 Puan)\n'
            '• Her gün günlük bonus: +1 Puan (VIP: günde 2 kez)\n'
            '• Admin tarafından manuel puan yüklenmesiyle\n'
            '• Promosyon kodu kullanarak\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '📦 Sipariş Takibi Nasıl Çalışır ⁉️\n'
            'Satın aldığınız her ürün için otomatik bir Sipariş ID oluşturulur.\n'
            'Sipariş verdikten sonra bot sizden profil linkinizi isteyecektir.\n\n'
            'Sipariş durumları:\n'
            '🟡 Alındı — Sisteme kaydedildi\n'
            '🔵 İşlemde — Hazırlanıyor\n'
            '🟢 Teslim Edildi — Size iletildi\n'
            '🟥 İptal — Puan iade edildi\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '📦 Sipariş İptali ⁉️\n'
            'Siparişlerim menüsünden ilgili siparişe tıklayın. Teslim edilmemiş siparişlerde İptal Et butonu görünür. İptal ücreti 1 Puan\'dır, kalan iade edilir.\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '🎫 Promosyon Kodu Nedir? ⁉️\n'
            'Yönetici tarafından oluşturulan özel kodlardır. Ana menüden Kupon Kodu butonuna basarak kodunuzu girin ve puan kazanın. Her kod sadece belirtilen kişi sayısınca kullanılabilir.\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '🤝 Davet Et Kazan Nedir ⁉️\n'
            'Size özel davet linkinizi paylaşın. Her katılan kişi için otomatik +1 Puan kazanırsınız.\n'
            '20 kişiyi davet ederek VIP üye olabilirsiniz.\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '💰 Puan Transfer ⁉️\n'
            'Günde 2 transfer hakkınız vardır. Her transferde 1 Puan komisyon kesilir.\n'
            'Grupta kullanım: Birine yanıt vererek /transfer 10 yazın.\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '🎲 Çekiliş ve Haftalık Ödül ⁉️\n'
            'Zaman zaman çekilişler düzenlenir, Çekiliş butonuyla katılabilirsiniz.\n'
            'Her hafta en çok referans getiren 3 kişi özel ödül kazanır.\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '💸 Bakiye İadesi ve Destek ⁉️\n'
            'Hatalı sipariş veya sorun yaşarsanız ana menüden Destek butonuna basarak yöneticiye talebinizi iletebilirsiniz.\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '⁉️ Destek İçin: <b>Admin</b> butonu üzerinden ulaşabilirsiniz ⁉️'
        ),

        'coupon_maintenance': '🔧 Kupon Sistemi Tamirde',
        'generic_error': '⚠️ Bir şeyler ters gitti, lütfen tekrar deneyin.',
        'lang_select': 'Lütfen dil tercihinizi yapın / Please select your language:',
    },
    'EN': {
        'welcome': '☀️ Hello\n\n👾 <b>Eren SMM TR</b>\nTurkey\'s trusted digital product marketplace.\n\nSelect an operation:',
        'balance': '💎 Balance',
        'profile': '👤 Profile',
        'shop': '🛍️ Shop',
        'vip_button': '👑 Get VIP • 20 Referrals',
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

        'profile_text': (
            '👤 <b>Profile Summary</b>\n\n'
            '🆔 <b>User ID:</b> {user_id}\n'
            '💎 <b>Wallet Balance:</b> {balance} Points\n'
            '🤝 <b>Referred:</b> {referrals} People\n'
            '💼 <b>Total Orders:</b> {orders}\n'
            '📆 <b>Registration Date:</b> {reg_date}\n\n'
            '💡 As VIP: 2x Daily Bonus, +2 Referral Points, access to VIP Shop!'
        ),

        'daily_bonus_success': (
            '🎁 <b>Daily Bonus Claimed!</b>\n\n'
            '➕ +1 Point added to your account!\n'
            '💎 New Balance: {balance} Points\n\n'
            '👍 You\'ve used all your bonus rights for today!'
        ),
        'daily_bonus_success_vip': (
            '🎁 <b>Daily Bonus Claimed!</b>\n\n'
            '➕ +1 Point added to your account!\n'
            '💎 New Balance: {balance} Points\n\n'
            '👑 As VIP you\'ve used {used}/2 bonuses today!'
        ),
        'daily_bonus_used': '⏳ You\'ve used today\'s bonus!\nCome back tomorrow!',

        'insufficient_balance': '❌ Insufficient Balance!\nRequired: {needed} Points\nYour Balance: {balance} Points',

        'transfer_info': (
            '💰 <b>Points Transfer System</b>\n\n'
            '💎 <b>Your Balance:</b> {balance} Points\n'
            '⏳ <b>Daily Limit:</b> {daily_left}/2 left\n\n'
            '1️⃣ The bot deducts <b>1 Point</b> commission per transfer.\n'
            '👤 Enter recipient ID and amount to transfer.\n\n'
            'Format: RecipientID|Amount\n'
            'E.g.: 1234567|10'
        ),
        'transfer_prompt': (
            '💰 <b>Enter Transfer Info</b>\n\n'
            'Format: RecipientID|Amount\n'
            'E.g.: 1234567|10\n\n'
            '⚠️ The bot deducts <b>1 Point</b> commission.\n'
            '💎 <b>Your Balance:</b> {balance} Points\n\n'
            'Cancel: /iptal'
        ),
        'transfer_cancelled': '⚠️ Transfer cancelled.',
        'transfer_format_error': '❌ Invalid format!\nCorrect format: RecipientID|Amount\nE.g.: 1234567|10',
        'transfer_success': '✅ Transfer Successful!\n\n📤 You sent {amount} Points\n👤 Recipient: {receiver_id}\n💸 Commission: 1 Point\n💎 New Balance: {new_balance} Points',
        'transfer_limit_reached': '⏳ Your daily transfer limit is reached!\n\nYou can make at most 2 transfers per day. Try again tomorrow.',

        'shop_welcome': '👋 <b>Welcome to the Shop!</b>\n\nSelect a category:',
        'tiktok_smm': '🎵 TikTok SMM',
        'telegram_smm': '📱 Telegram SMM',
        'category_empty': '📦 {category}\n\nNo products in this category yet.\nComing soon!',

        'vip_shop_welcome': '👑 <b>Welcome to the VIP Shop!</b>\n\nExclusive VIP products:',
        'vip_required_alert': '👑 Please become VIP first!\nVIP membership is required to access the VIP shop.',

        'vip_purchase_text': (
            '👍 <b>Get VIP</b>\n\n'
            '{required} referrals are required for VIP!\n\n'
            '👍 Your current referrals: <b>{current}/{required}</b>\n'
            '👍 Missing: <b>{missing} more people</b> to invite!\n\n'
            '• 👍 <b>VIP Benefits:</b>\n'
            '• 👍 VIP Shop access\n'
            '• 👍 Daily bonus twice a day\n'
            '• 👍 <b>+2 Points</b> per referral'
        ),
        'vip_already': (
            '👑 <b>You are already a VIP member!</b>\n\n'
            '✅ You have VIP Shop access\n'
            '✅ You can claim the daily bonus twice a day\n'
            '✅ You earn +2 Points per referral'
        ),
        'vip_granted': (
            '🎉 <b>Congrats! You are now VIP!</b>\n\n'
            '👑 You now have VIP Shop access\n'
            '🎁 You can claim the daily bonus twice a day\n'
            '🤝 You\'ll earn +2 Points per referral'
        ),

        'no_orders': '📦 <b>Your Order History</b>\n\nYou have no orders yet.',

        'referral_link': (
            '🤝 <b>Invite, Earn!</b>\n\n'
            '👇 Invite your friends with your personal link below, earn <b>+1 Point</b> instantly for every new signup.\n\n'
            '📋 <b>Your Link:</b>\n'
            'https://t.me/{bot_username}?start={user_id}'
        ),

        'support_text': (
            '💬 <b>Support Center</b>\n\n'
            '⚠️ <b>Please don\'t disturb the admin unnecessarily.</b>\n'
            'Only send a message for a real issue, faulty order, or emergency.\n'
            'Check the Help menu first for FAQs.\n\n'
            '💎 <b>Your Balance:</b> {balance} Points\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            'Write your issue or request below.\n'
            'Type /iptal to cancel.'
        ),
        'support_cancelled': '❌ Cancelled.',
        'support_sent': '✅ Your message has been sent. We\'ll contact you soon.',

        'no_active_raffle': '🎲 <b>Raffle</b>\n\n⚠️ There is no active raffle right now.\n\n<i>Stay tuned for new raffles!</i>',

        'donate_text': (
            '⭐️ <b>Donate</b>\n\n'
            'As Eren SMM TR, we work hard to always provide you better, faster, longer-lasting and more affordable service.\n\n'
            'If you are happy with our services, you can support us with a star <b>donation</b>. Every contribution means a lot to us. Thank you! 🙏\n\n'
            'How many stars would you like to <b>donate</b>?'
        ),
        'donate_invoice_sent': '⭐️ A {stars}-star donation invoice has been sent to you in private. Please complete the payment.',

        'help_text': (
            '📖 <b>HELP CENTER</b> 📖\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '🛍 What is the Shop ⁉️\n'
            'The bot\'s main sales area. You can buy products organized into categories here. Click a product to see price and stock, then tap buy to deduct points and create your order.\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '👑 VIP Shop & Membership ⁉️\n'
            'The VIP shop contains products exclusive to VIP members. You can become VIP by bringing 20 referrals.\n'
            'VIP benefits: 👑 VIP Shop access • 🎁 2x daily bonus • 🤝 +2 Points per referral\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '💎 How to Earn Points ⁉️\n'
            '• +1 Point when a friend joins via your link (VIP: +2 Points)\n'
            '• Daily bonus every day: +1 Point (VIP: 2 times a day)\n'
            '• Manual point top-up by the admin\n'
            '• Using a promo code\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '📦 How Order Tracking Works ⁉️\n'
            'An automatic Order ID is created for every product you purchase.\n\n'
            'Order statuses:\n'
            '🟡 Received — Recorded in the system\n'
            '🔵 Processing — Being prepared\n'
            '🟢 Delivered — Sent to you\n'
            '🟥 Cancelled — Points refunded\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '⁉️ For Support: Use the <b>Admin</b> button ⁉️'
        ),

        'coupon_maintenance': '🔧 Coupon System Under Maintenance',
        'generic_error': '⚠️ Something went wrong, please try again.',
        'lang_select': 'Lütfen dil tercihinizi yapın / Please select your language:',
    }
}

# ===== HELPER FUNCTIONS =====
def get_user(user_id):
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
        return c.fetchone()
    except Exception as e:
        logger.error(f"get_user error: {e}")
        return None
    finally:
        put_conn(conn)

def create_user(user_id, username):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute('''INSERT INTO users (user_id, username, balance, registration_date)
                     VALUES (%s, %s, %s, %s)
                     ON CONFLICT (user_id) DO NOTHING''',
                  (user_id, username, START_BALANCE, datetime.now().strftime('%Y-%m-%d %H:%M')))
        conn.commit()
    except Exception as e:
        logger.error(f"create_user error: {e}")
    finally:
        put_conn(conn)

def update_balance(user_id, amount):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute('UPDATE users SET balance = balance + %s WHERE user_id = %s', (amount, user_id))
        conn.commit()
    except Exception as e:
        logger.error(f"update_balance error: {e}")
    finally:
        put_conn(conn)

def get_user_language(user_id_or_user):
    """user_id və ya artıq alınmış user dict qəbul edə bilər (əlavə DB sorğusundan qaçmaq üçün)"""
    try:
        if isinstance(user_id_or_user, dict):
            user = user_id_or_user
        else:
            user = get_user(user_id_or_user)
        return user['language'] if user and user.get('language') else 'TR'
    except Exception:
        return 'TR'

def get_text(key, lang_or_user_id, **kwargs):
    """İkinci parametr ya birbaşa dil kodu ('TR'/'EN'), ya da user_id ola bilər (geriyə uyğunluq üçün)"""
    if lang_or_user_id in ('TR', 'EN'):
        lang = lang_or_user_id
    else:
        lang = get_user_language(lang_or_user_id)
    text = LANG.get(lang, LANG['TR']).get(key, LANG['TR'].get(key, ''))
    return text.format(**kwargs) if kwargs else text

async def safe_edit(query, text, reply_markup=None):
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            try:
                await query.answer()
            except Exception:
                pass
        else:
            logger.error(f"safe_edit error: {e}")
    except Exception as e:
        logger.error(f"safe_edit unexpected error: {e}")

def get_products_by_category(category, vip_only=None):
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        if vip_only is None:
            c.execute('SELECT * FROM products WHERE category = %s', (category,))
        else:
            c.execute('SELECT * FROM products WHERE category = %s AND vip_only = %s', (category, vip_only))
        return c.fetchall()
    except Exception as e:
        logger.error(f"get_products_by_category error: {e}")
        return []
    finally:
        put_conn(conn)

def get_all_vip_products():
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT * FROM products WHERE vip_only = TRUE')
        return c.fetchall()
    except Exception as e:
        logger.error(f"get_all_vip_products error: {e}")
        return []
    finally:
        put_conn(conn)

def main_menu_keyboard(user):
    """user: dict (artıq DB-dən alınmış). 4 buton 2x2, sonra uzun VIP/Zaten-VIP, sonra qalanı 2x2."""
    lang = get_user_language(user)
    is_vip = bool(user and user.get('vip_status'))

    if is_vip:
        vip_row = [InlineKeyboardButton(
            '👑 VIP Üye' if lang == 'TR' else '👑 VIP Member',
            callback_data='vip_already_info'
        )]
    else:
        vip_row = [InlineKeyboardButton(get_text('vip_button', lang), callback_data='vip_purchase')]

    keyboard = [
        [InlineKeyboardButton(get_text('balance', lang), callback_data='balance'),
         InlineKeyboardButton(get_text('profile', lang), callback_data='profile')],
        [InlineKeyboardButton(get_text('shop', lang), callback_data='shop'),
         InlineKeyboardButton('👑 VIP Mağaza' if lang == 'TR' else '👑 VIP Shop', callback_data='vip_shop')],
        vip_row,
        [InlineKeyboardButton(get_text('daily_bonus', lang), callback_data='daily_bonus'),
         InlineKeyboardButton(get_text('orders', lang), callback_data='orders')],
        [InlineKeyboardButton(get_text('transfer', lang), callback_data='transfer'),
         InlineKeyboardButton(get_text('coupon', lang), callback_data='coupon')],
        [InlineKeyboardButton(get_text('referral', lang), callback_data='referral'),
         InlineKeyboardButton(get_text('support', lang), callback_data='support')],
        [InlineKeyboardButton(get_text('help', lang), callback_data='help'),
         InlineKeyboardButton(get_text('language', lang), callback_data='language')],
        [InlineKeyboardButton(get_text('raffle', lang), callback_data='raffle'),
         InlineKeyboardButton(get_text('donate', lang), callback_data='donate')]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_to_menu_markup(lang):
    return InlineKeyboardMarkup([[InlineKeyboardButton(get_text('back_to_menu', lang), callback_data='main_menu')]])

# ===== MAIN HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        tg_user = update.message.from_user
        user_id = tg_user.id
    else:
        tg_user = update.callback_query.from_user
        user_id = tg_user.id

    existing_user = get_user(user_id)
    if not existing_user:
        create_user(user_id, tg_user.username or f"User{user_id}")
        existing_user = get_user(user_id)

    # Referral sistem (yalnız /start mesajla gəldikdə işləsin)
    if update.message and context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id:
                conn = get_conn()
                try:
                    c = conn.cursor(cursor_factory=RealDictCursor)
                    c.execute('SELECT 1 FROM referrals WHERE referrer_id = %s AND referred_user_id = %s',
                             (referrer_id, user_id))
                    if not c.fetchone():
                        c.execute('SELECT * FROM users WHERE user_id = %s', (referrer_id,))
                        referrer = c.fetchone()
                        if referrer:
                            bonus = 2 if referrer['vip_status'] else 1
                            c.execute('''INSERT INTO referrals (referrer_id, referred_user_id, referral_date)
                                       VALUES (%s, %s, %s)''',
                                     (referrer_id, user_id, datetime.now().strftime('%Y-%m-%d %H:%M')))
                            c.execute('UPDATE users SET referrals = referrals + 1, balance = balance + %s WHERE user_id = %s',
                                     (bonus, referrer_id))
                            conn.commit()

                            # Referans verən şəxsə xəbər ver
                            try:
                                ref_lang = get_user_language(referrer)
                                notify = ('🤝 Yeni bir kişi linkinizle katıldı!\n➕ +{} Puan kazandınız!' if ref_lang == 'TR'
                                          else '🤝 Someone joined using your link!\n➕ You earned +{} Points!').format(bonus)
                                await context.bot.send_message(referrer_id, notify)
                            except Exception as e:
                                logger.error(f"referrer notify error: {e}")
                except Exception as e:
                    logger.error(f"referral db error: {e}")
                    conn.rollback()
                finally:
                    put_conn(conn)
        except (ValueError, IndexError):
            pass

    reply_markup = main_menu_keyboard(existing_user)
    lang = get_user_language(existing_user)
    welcome_text = get_text('welcome', lang)

    if update.message:
        await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    else:
        await safe_edit(update.callback_query, welcome_text, reply_markup)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    answered = False

    async def answer_once(alert_text=None, show_alert=False):
        """Telegram bir callback query-ye yalnizca BIR defe cevap vermeye izin verir.
        Ikinci cagiri sessizce yutulup hicbir sey gostermez. Bu fonksiyon bunu onler."""
        nonlocal answered
        if answered:
            return
        answered = True
        try:
            if alert_text:
                await query.answer(alert_text, show_alert=show_alert)
            else:
                await query.answer()
        except Exception as e:
            logger.error(f"query.answer error: {e}")

    user = get_user(user_id)
    if not user:
        create_user(user_id, query.from_user.username or f"User{user_id}")
        user = get_user(user_id)

    lang = get_user_language(user)
    back_markup = back_to_menu_markup(lang)

    # Alert gosterecek callback'ler disinda hemen spinner'i durdur (hiz icin).
    # Alert gosterilecek callback'lerde answer_once alert ile cagrilacak,
    # bu yuzden burada bos cevap GONDERMIYORUZ - tek cevap hakkimizi alert icin saklıyoruz.
    data_preview = query.data or ''
    will_show_alert = (data_preview in ('daily_bonus', 'vip_shop')) or data_preview.startswith('buy_')
    if not will_show_alert:
        await answer_once()

    try:
        data = query.data

        if data in ('balance', 'profile'):
            conn = get_conn()
            try:
                c = conn.cursor()
                c.execute('SELECT COUNT(*) FROM orders WHERE user_id = %s', (user_id,))
                order_count = c.fetchone()[0]
            except Exception as e:
                logger.error(f"profile order count error: {e}")
                order_count = 0
            finally:
                put_conn(conn)

            text = get_text('profile_text', lang,
                           user_id=user['user_id'],
                           balance=user['balance'],
                           referrals=user['referrals'],
                           orders=order_count,
                           reg_date=user['registration_date'])
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(get_text('daily_bonus', lang), callback_data='daily_bonus')],
                [InlineKeyboardButton(get_text('back_to_menu', lang), callback_data='main_menu')]
            ])
            await safe_edit(query, text, keyboard)

        elif data == 'daily_bonus':
            is_vip = bool(user['vip_status'])
            today = datetime.now().strftime('%Y-%m-%d')
            max_per_day = 2 if is_vip else 1

            # daily_transfer_count'u transfer için kullandığımızdan,
            # bonus sayacı için last_bonus_date + ayrı bir sayaç gerekiyor.
            # Burada last_bonus_date alanını "YYYY-MM-DD" veya "YYYY-MM-DD:count" formatında saklıyoruz.
            raw = user['last_bonus_date'] or ''
            if ':' in raw:
                last_day, used_str = raw.split(':', 1)
                used_today = int(used_str) if used_str.isdigit() else 0
            else:
                last_day = raw
                used_today = 1 if raw == today else 0

            if last_day != today:
                used_today = 0

            if used_today >= max_per_day:
                await answer_once(get_text('daily_bonus_used', lang), show_alert=True)
                return

            used_today += 1
            update_balance(user_id, 1)
            conn = get_conn()
            try:
                c = conn.cursor()
                c.execute('UPDATE users SET last_bonus_date = %s WHERE user_id = %s',
                         (f"{today}:{used_today}", user_id))
                conn.commit()
            except Exception as e:
                logger.error(f"daily_bonus error: {e}")
            finally:
                put_conn(conn)

            await answer_once()

            new_balance = user['balance'] + 1
            if is_vip and max_per_day == 2:
                text = get_text('daily_bonus_success_vip', lang, balance=new_balance, used=used_today)
            else:
                text = get_text('daily_bonus_success', lang, balance=new_balance)
            await safe_edit(query, text, back_markup)

        elif data == 'referral':
            text = get_text('referral_link', lang, user_id=user_id, bot_username=BOT_USERNAME)
            await safe_edit(query, text, back_markup)

        elif data == 'language':
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton('🇹🇷 Türkçe', callback_data='lang_tr'),
                 InlineKeyboardButton('🇬🇧 English', callback_data='lang_en')],
                [InlineKeyboardButton(get_text('back_to_menu', lang), callback_data='main_menu')]
            ])
            await safe_edit(query, get_text('lang_select', lang), keyboard)

        elif data in ('lang_tr', 'lang_en'):
            new_lang = 'TR' if data == 'lang_tr' else 'EN'
            conn = get_conn()
            try:
                c = conn.cursor()
                c.execute('UPDATE users SET language = %s WHERE user_id = %s', (new_lang, user_id))
                conn.commit()
            except Exception as e:
                logger.error(f"{data} error: {e}")
            finally:
                put_conn(conn)
            await start(update, context)

        elif data == 'shop':
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(get_text('tiktok_smm', lang), callback_data='shop_tiktok'),
                 InlineKeyboardButton(get_text('telegram_smm', lang), callback_data='shop_telegram')],
                [InlineKeyboardButton(get_text('back_to_menu', lang), callback_data='main_menu')]
            ])
            await safe_edit(query, get_text('shop_welcome', lang), keyboard)

        elif data in ('shop_tiktok', 'shop_telegram'):
            category = 'TikTok' if data == 'shop_tiktok' else 'Telegram'
            products = get_products_by_category(category, vip_only=False)

            if not products:
                cat_label = get_text('tiktok_smm', lang) if category == 'TikTok' else get_text('telegram_smm', lang)
                text = get_text('category_empty', lang, category=cat_label)
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(get_text('back_to_menu', lang), callback_data='shop')]])
                await safe_edit(query, text, keyboard)
            else:
                text = f"📦 <b>{category} SMM</b>\n\n"
                rows = []
                for p in products:
                    text += f"• {p['name']} — 💰{p['price']} Puan (📦{p['stock']} stok)\n"
                    rows.append([InlineKeyboardButton(f"{p['name']} ({p['price']}P)", callback_data=f"buy_{p['product_id']}")])
                rows.append([InlineKeyboardButton(get_text('back_to_menu', lang), callback_data='shop')])
                await safe_edit(query, text, InlineKeyboardMarkup(rows))

        elif data == 'vip_shop':
            if not user['vip_status']:
                await answer_once(get_text('vip_required_alert', lang), show_alert=True)
                return

            await answer_once()
            products = get_all_vip_products()
            if not products:
                text = get_text('category_empty', lang, category=('VIP Mağaza' if lang == 'TR' else 'VIP Shop'))
                await safe_edit(query, text, back_markup)
            else:
                text = get_text('vip_shop_welcome', lang) + "\n\n"
                rows = []
                for p in products:
                    text += f"• {p['name']} — 💰{p['price']} Puan (📦{p['stock']} stok)\n"
                    rows.append([InlineKeyboardButton(f"{p['name']} ({p['price']}P)", callback_data=f"buy_{p['product_id']}")])
                rows.append([InlineKeyboardButton(get_text('back_to_menu', lang), callback_data='main_menu')])
                await safe_edit(query, text, InlineKeyboardMarkup(rows))

        elif data == 'vip_purchase':
            if user['vip_status']:
                await safe_edit(query, get_text('vip_already', lang), back_markup)
                return

            current = user['referrals']
            required = VIP_REFERRAL_REQUIREMENT
            missing = max(0, required - current)

            if missing == 0:
                # Referans yetərlidir -> VIP-i avtomatik təyin et
                conn = get_conn()
                try:
                    c = conn.cursor()
                    c.execute('UPDATE users SET vip_status = TRUE WHERE user_id = %s', (user_id,))
                    conn.commit()
                except Exception as e:
                    logger.error(f"vip grant error: {e}")
                finally:
                    put_conn(conn)
                await safe_edit(query, get_text('vip_granted', lang), back_markup)
            else:
                text = get_text('vip_purchase_text', lang, required=required, current=current, missing=missing)
                await safe_edit(query, text, back_markup)

        elif data == 'vip_already_info':
            await safe_edit(query, get_text('vip_already', lang), back_markup)

        elif data == 'orders':
            conn = get_conn()
            try:
                c = conn.cursor(cursor_factory=RealDictCursor)
                c.execute('SELECT * FROM orders WHERE user_id = %s ORDER BY order_id DESC', (user_id,))
                orders = c.fetchall()
            except Exception as e:
                logger.error(f"orders fetch error: {e}")
                orders = []
            finally:
                put_conn(conn)

            if not orders:
                text = get_text('no_orders', lang)
            else:
                title = 'Siparişleriniz' if lang == 'TR' else 'Your Orders'
                text = f"📦 <b>{title}</b> ({len(orders)}):\n\n"
                for order in orders:
                    text += f"ID: {order['order_id']} | Status: {order['status']}\n"

            await safe_edit(query, text, back_markup)

        elif data == 'transfer':
            daily_left = 2
            today = datetime.now().strftime('%Y-%m-%d')
            if user['last_transfer_date'] == today:
                daily_left = max(0, 2 - user['daily_transfer_count'])

            if daily_left <= 0:
                await safe_edit(query, get_text('transfer_limit_reached', lang), back_markup)
                return

            text = get_text('transfer_prompt', lang, balance=user['balance'])
            await safe_edit(query, text, back_markup)
            context.user_data['awaiting_transfer'] = True

        elif data == 'raffle':
            await safe_edit(query, get_text('no_active_raffle', lang), back_markup)

        elif data == 'donate':
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
                [InlineKeyboardButton(get_text('back_to_menu', lang), callback_data='main_menu')]
            ]
            await safe_edit(query, get_text('donate_text', lang), InlineKeyboardMarkup(buttons))

        elif data.startswith('donate_'):
            stars = int(data.split('_')[1])
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
                text = get_text('donate_invoice_sent', lang, stars=stars)
                await safe_edit(query, text, back_markup)
            except Exception as e:
                logger.error(f"send_invoice error: {e}")
                await safe_edit(query, get_text('generic_error', lang), back_markup)

        elif data == 'coupon':
            await safe_edit(query, get_text('coupon_maintenance', lang), back_markup)

        elif data == 'support':
            text = get_text('support_text', lang, balance=user['balance'])
            await safe_edit(query, text, back_markup)
            context.user_data['awaiting_support'] = True

        elif data == 'help':
            await safe_edit(query, get_text('help_text', lang), back_markup)

        elif data == 'main_menu':
            context.user_data['awaiting_transfer'] = False
            context.user_data['awaiting_support'] = False
            await start(update, context)

        elif data.startswith('buy_'):
            product_id = int(data.split('_')[1])
            conn = get_conn()
            try:
                c = conn.cursor(cursor_factory=RealDictCursor)
                c.execute('SELECT * FROM products WHERE product_id = %s', (product_id,))
                product = c.fetchone()
            except Exception as e:
                logger.error(f"buy fetch product error: {e}")
                product = None
            finally:
                put_conn(conn)

            if not product or product['stock'] <= 0:
                await answer_once('❌ Ürün bulunamadı veya stok yok!', show_alert=True)
                return

            if user['balance'] < product['price']:
                await answer_once(get_text('insufficient_balance', lang,
                                             needed=product['price'],
                                             balance=user['balance']), show_alert=True)
                return

            await answer_once('🛒 Sipariş akışı için bu adımı kendi iş mantığınıza göre genişletin (profil linki isteme vb).', show_alert=True)

        else:
            logger.warning(f"Bilinmeyen callback_data: {data}")
            await start(update, context)

    except Exception as e:
        logger.error(f"button_click genel hata: {e}")
        try:
            await safe_edit(query, get_text('generic_error', lang), back_markup)
        except Exception:
            pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text
    user = get_user(user_id)
    lang = get_user_language(user)

    if context.user_data.get('awaiting_transfer'):
        if text == '/iptal':
            context.user_data['awaiting_transfer'] = False
            await update.message.reply_text(get_text('transfer_cancelled', lang))
            return

        try:
            parts = text.split('|')
            if len(parts) != 2:
                await update.message.reply_text(get_text('transfer_format_error', lang))
                return

            receiver_id = int(parts[0].strip())
            amount = int(parts[1].strip())

            if amount <= 0:
                await update.message.reply_text(get_text('transfer_format_error', lang))
                return

            if receiver_id == user_id:
                await update.message.reply_text('❌ Kendinize transfer yapamazsınız!' if lang == 'TR' else "❌ You can't transfer to yourself!")
                return

            if not user or user['balance'] < amount + 1:
                needed = amount + 1
                balance = user['balance'] if user else 0
                await update.message.reply_text(get_text('insufficient_balance', lang, needed=needed, balance=balance))
                return

            today = datetime.now().strftime('%Y-%m-%d')
            daily_left = 2
            if user['last_transfer_date'] == today:
                daily_left = max(0, 2 - user['daily_transfer_count'])
            if daily_left <= 0:
                context.user_data['awaiting_transfer'] = False
                await update.message.reply_text(get_text('transfer_limit_reached', lang))
                return

            receiver = get_user(receiver_id)
            if not receiver:
                await update.message.reply_text('❌ Alıcı kullanıcı bulunamadı!' if lang == 'TR' else '❌ Recipient not found!')
                return

            conn = get_conn()
            try:
                c = conn.cursor()

                if user['last_transfer_date'] == today:
                    c.execute('UPDATE users SET daily_transfer_count = daily_transfer_count + 1 WHERE user_id = %s', (user_id,))
                else:
                    c.execute('UPDATE users SET daily_transfer_count = 1, last_transfer_date = %s WHERE user_id = %s', (today, user_id))

                c.execute('UPDATE users SET balance = balance - %s WHERE user_id = %s', (amount + 1, user_id))
                c.execute('UPDATE users SET balance = balance + %s WHERE user_id = %s', (amount, receiver_id))

                c.execute('''INSERT INTO transfers (sender_id, receiver_id, amount, transfer_date)
                            VALUES (%s, %s, %s, %s)''',
                         (user_id, receiver_id, amount, datetime.now().strftime('%Y-%m-%d %H:%M')))

                conn.commit()
            except Exception as e:
                logger.error(f"transfer error: {e}")
                conn.rollback()
                await update.message.reply_text('❌ Transfer yapılamadı!' if lang == 'TR' else '❌ Transfer failed!')
                return
            finally:
                put_conn(conn)

            context.user_data['awaiting_transfer'] = False
            new_balance = user['balance'] - (amount + 1)

            success_msg = get_text('transfer_success', lang, amount=amount, receiver_id=receiver_id, new_balance=new_balance)
            await update.message.reply_text(success_msg)

            log_msg = f"💸 YENİ TRANSFER\n\n👤 Gönderen: {user_id}\n👤 Alan: {receiver_id}\n💎 Miktar: {amount}\n💰 Komisyon: 1\n📅 Zaman: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            try:
                await context.bot.send_message(LOG_CHANNEL, log_msg)
            except Exception as e:
                logger.error(f"log channel error: {e}")

            receiver_lang = get_user_language(receiver)
            receiver_msg = (f"✅ {user_id} sizə {amount} Puan gönderdi!\n💎 Yeni Bakiye: {receiver['balance'] + amount}" if receiver_lang == 'TR'
                             else f"✅ {user_id} sent you {amount} Points!\n💎 New Balance: {receiver['balance'] + amount}")
            try:
                await context.bot.send_message(receiver_id, receiver_msg)
            except Exception as e:
                logger.error(f"receiver notify error: {e}")

        except ValueError:
            await update.message.reply_text(get_text('transfer_format_error', lang))

    elif context.user_data.get('awaiting_support'):
        if text == '/iptal':
            context.user_data['awaiting_support'] = False
            await update.message.reply_text(get_text('support_cancelled', lang))
            return

        context.user_data['awaiting_support'] = False

        support_log = f"💬 YENİ DESTEK MESAJI\n\n👤 Kullanıcı: {user_id}\n💬 Mesaj:\n{text}\n\n📅 Zaman: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        try:
            await context.bot.send_message(LOG_CHANNEL, support_log)
        except Exception as e:
            logger.error(f"support log channel error: {e}")
        try:
            await context.bot.send_message(ADMIN_ID, f"Yeni destek mesajı:\n\nKullanıcı: {user_id}\nMesaj: {text}")
        except Exception as e:
            logger.error(f"support admin notify error: {e}")

        await update.message.reply_text(get_text('support_sent', lang))

# ===== ADMIN COMMANDS =====
async def admin_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

        conn = get_conn()
        try:
            c = conn.cursor()
            c.execute('''INSERT INTO products (name, category, price, stock, vip_only)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING product_id''',
                     (name, category, price, stock, vip_only))
            product_id = c.fetchone()[0]
            conn.commit()

            vip_tag = '👑 VIP' if vip_only else ''
            await update.message.reply_text(f'✅ Ürün eklendi!\n\nID: {product_id}\n📝 Ad: {name}\n📂 Kategori: {category}\n💰 Fiyat: {price}\n📦 Stok: {stock} {vip_tag}')
        except Exception as e:
            logger.error(f"add_product error: {e}")
            conn.rollback()
            await update.message.reply_text(f'❌ Hata: {str(e)}')
        finally:
            put_conn(conn)
    except Exception as e:
        await update.message.reply_text(f'❌ Hata: {str(e)}')

async def admin_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return

    if len(context.args) < 2:
        await update.message.reply_text('📝 Kullanım: /admin_stock <ürün_id> <yeni_stok>')
        return

    try:
        product_id = int(context.args[0])
        new_stock = int(context.args[1])

        conn = get_conn()
        try:
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute('UPDATE products SET stock = %s WHERE product_id = %s', (new_stock, product_id))
            c.execute('SELECT name, stock FROM products WHERE product_id = %s', (product_id,))
            product = c.fetchone()
            conn.commit()

            if product:
                await update.message.reply_text(f'✅ Stok güncellendi!\n\n📝 Ürün: {product["name"]}\n📦 Yeni Stok: {new_stock}')
            else:
                await update.message.reply_text('❌ Ürün bulunamadı!')
        except Exception as e:
            logger.error(f"stock error: {e}")
            conn.rollback()
            await update.message.reply_text(f'❌ Hata: {str(e)}')
        finally:
            put_conn(conn)
    except Exception as e:
        await update.message.reply_text(f'❌ Hata: {str(e)}')

async def admin_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return

    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT product_id, name, category, price, stock, vip_only FROM products')
        products = c.fetchall()
    except Exception as e:
        logger.error(f"products error: {e}")
        products = []
    finally:
        put_conn(conn)

    if not products:
        await update.message.reply_text('📦 Ürün bulunamadı!')
        return

    text = '📦 TÜM ÜRÜNLER\n\n'
    for p in products:
        vip_tag = '👑' if p['vip_only'] else ''
        text += f"ID: {p['product_id']} | {p['name']} ({p['category']}) | 💰{p['price']} | 📦{p['stock']} {vip_tag}\n"

    await update.message.reply_text(text)

async def admin_give_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return

    if len(context.args) < 2:
        await update.message.reply_text('📝 Kullanım: /admin_give <user_id> <puan>')
        return

    try:
        target_user_id = int(context.args[0])
        points = int(context.args[1])

        user_before = get_user(target_user_id)
        if not user_before:
            await update.message.reply_text('❌ Kullanıcı bulunamadı!')
            return

        update_balance(target_user_id, points)

        user_after = get_user(target_user_id)
        await update.message.reply_text(f'✅ {points} puan verildi!\n\n👤 ID: {target_user_id}\n💎 Yeni Bakiye: {user_after["balance"]}')
    except Exception as e:
        await update.message.reply_text(f'❌ Hata: {str(e)}')

async def admin_set_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin manuel olarak VIP verebilir/kaldırabilir: /admin_vip <user_id> <on/off>"""
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return

    if len(context.args) < 2:
        await update.message.reply_text('📝 Kullanım: /admin_vip <user_id> <on/off>')
        return

    try:
        target_user_id = int(context.args[0])
        status = context.args[1].lower() in ('on', 'true', '1', 'evet')

        conn = get_conn()
        try:
            c = conn.cursor()
            c.execute('UPDATE users SET vip_status = %s WHERE user_id = %s', (status, target_user_id))
            conn.commit()
            await update.message.reply_text(f'✅ Kullanıcı {target_user_id} VIP durumu: {"AÇIK" if status else "KAPALI"}')
        except Exception as e:
            logger.error(f"admin_set_vip error: {e}")
            conn.rollback()
            await update.message.reply_text(f'❌ Hata: {str(e)}')
        finally:
            put_conn(conn)
    except Exception as e:
        await update.message.reply_text(f'❌ Hata: {str(e)}')

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return

    conn = get_conn()
    try:
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
    finally:
        put_conn(conn)

# ===== MAIN =====
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(
        (filters.TEXT & ~filters.COMMAND) | filters.Regex(r'^/iptal$'),
        handle_message
    ))

    app.add_handler(CommandHandler('admin_add_product', admin_add_product))
    app.add_handler(CommandHandler('admin_stock', admin_stock))
    app.add_handler(CommandHandler('admin_products', admin_products))
    app.add_handler(CommandHandler('admin_give', admin_give_points))
    app.add_handler(CommandHandler('admin_vip', admin_set_vip))
    app.add_handler(CommandHandler('admin_stats', admin_stats))

    logger.info("Bot başlatılıyor...")
    app.run_polling()

if __name__ == '__main__':
    main()
