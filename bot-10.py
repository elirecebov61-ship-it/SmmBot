import logging
import os
import re
import random
import asyncio
import httpx
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity
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
BOT_USERNAME = os.getenv("BOT_USERNAME", "WextyroMarketBot")
VIP_REFERRAL_REQUIREMENT = int(os.getenv("VIP_REFERRAL_REQUIREMENT", "20"))

# ===== PANELBAKU SMM API =====
PANELBAKU_API_URL = os.getenv("PANELBAKU_API_URL", "https://panelbaku.com/api/v2")
PANELBAKU_API_KEY = os.getenv("PANELBAKU_API_KEY", "af5111d02469901041d92f3463ad21ed")

# ===== AZETAKIP SMM API =====
AZETAKIP_API_URL = os.getenv("AZETAKIP_API_URL", "https://azetakip.com/api/v2")
AZETAKIP_API_KEY = os.getenv("AZETAKIP_API_KEY", "7890e7fa6a1ba91f9b12668069644167")

# Bu istifadəçi ID-lərinin sifarişləri API-yə GÖNDƏRİLMİR - admin manual idarə edir.
# Yenə də normal şəkildə log kanalına düşür, sadəcə avtomatik API çağırışı edilmir.
API_EXCLUDED_USER_IDS = {8034872992, 8793739928}

# Otomatik sipariş statusu kontrolü - bu saniye aralığında PanelBaku/AzeTakip'teki "Onaylandı"
# durumundaki siparişler kontrol edilir, "Completed" gelirse otomatik "Tamamlandı" yapılır.
ORDER_STATUS_CHECK_INTERVAL = 300  # 5 dakika

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== PREMIUM EMOJI MAP =====
# Hər unicode emoji -> sənin premium custom emoji ID-n.
# Mesaj göndərilərkən mətndəki bu emoji-lər avtomatik custom_emoji entity-yə çevrilir.
# (Bu yalnız botun bağlı olduğu hesabda Telegram Premium varsa düzgün animasiyalı görünür;
#  premium olmayan istifadəçilər bunları normal placeholder emoji kimi görür, bu normaldır.)
PREMIUM_EMOJI_MAP = {
    '✅': '5377574606808835666',
    '➕': '5397916757333654639',
    '❌': '6224185666704511761',
    '💎': '5251562950698759162',
    '👤': '4967667085606912536',
    '🛍': '5143290574673019778',
    '👑': '6266995104687330978',
    '👍': '6224185666704511761',  # Günlük bonusdaki "alınmaz" emoji - ❌ ilə eyni custom emoji
    '📦': '5909003528956812070',
    '💰': '5375338737028841420',
    '🤝': '6071278787947925866',
    '💬': '5352759161945867747',
    '❓': '5197269100878907942',
    '🌍': '5397575638146110953',
    '🌎': '5397575638146110953',
    '🌏': '5397575638146110953',
    '🎲': '6071123877067494706',
    '⭐': '6221736233970700254',
    '🌞': '5402477260982731644',
    '👾': '5305444432118589379',
    '☀': '5402477260982731644',
    '💡': '5422439311196834318',
    '💼': '5348227245599105972',
    '📆': '5028418466000930064',
    '🆔': '5974526806995242353',
    '🛒': '5312361253610475399',
    '💵': '5197434882321567830',
    '🟢': '6073110518485227661',
    '🟡': '5208447513475954676',
    '🔴': '5411225014148014586',
    '🔗': '5271604874419647061',
    '⚠': '5447644880824181073',
    '👇': '5231102735817918643',
    '📋': '5197269100878907942',
    '⁉': '5314504236132747481',
    '📖': '5226512880362332956',
}
# Telegram ürünleri ve TikTok ürünleri üçün xüsusi emoji-lər (mətndə manuel yazılacaq, map-da deyil,
# çünki bunlar mövcud unicode emoji-ni əvəzləmir, yeni bir simvol kimi əlavə olunur)
TELEGRAM_PRODUCT_EMOJI_ID = '5345965137863928359'
TIKTOK_PRODUCT_EMOJI_ID = '5359640777590841912'
WHATSAPP_PRODUCT_EMOJI_ID = '5935973359480213803'
YOUTUBE_PRODUCT_EMOJI_ID = '5427158904729513162'
INSTAGRAM_PRODUCT_EMOJI_ID = '5348533850429470257'

# Tanınan kateqoriyaların standart (canonical) adı + premium icon-u.
# Açar həmişə kiçik hərflə saxlanır ki, axtarış case-insensitive olsun.
KNOWN_CATEGORIES = {
    'tiktok': ('TikTok', TIKTOK_PRODUCT_EMOJI_ID),
    'telegram': ('Telegram', TELEGRAM_PRODUCT_EMOJI_ID),
    'instagram': ('Instagram', INSTAGRAM_PRODUCT_EMOJI_ID),
    'whatsapp': ('WhatsApp', WHATSAPP_PRODUCT_EMOJI_ID),
    'youtube': ('YouTube', YOUTUBE_PRODUCT_EMOJI_ID),
}

def normalize_category(category):
    """İstifadəçinin yazdığı kateqoriya adını (hər hansı böyük/kiçik hərf yazılışı) standart formaya çevirir.
    Tanınmayan kateqoriyalar olduğu kimi qalır (yalnız baş hərfi böyüdülür).
    Türk dilindəki nöqtəli İ hərfi .lower()-da 'i̇' (i + birləşmiş nöqtə işarəsi) verdiyi üçün
    bunu adi 'i'-yə çevirib axtarış aparırıq, əks halda 'İnstagram' tanınmaz."""
    key = category.strip().lower().replace('i̇', 'i')
    if key in KNOWN_CATEGORIES:
        return KNOWN_CATEGORIES[key][0]
    return category.strip()

def get_category_icon(category):
    """Kateqoriyaya uyğun premium emoji ID-sini qaytarır (case-insensitive).
    Tanınan kateqoriyalar (TikTok, Telegram, Instagram, WhatsApp, YouTube) öz xüsusi
    icon-larını alır, digər (yeni, naməlum) kateqoriyalar ümumi mağaza (🛍) icon-u istifadə edir."""
    key = category.strip().lower().replace('i̇', 'i')
    if key in KNOWN_CATEGORIES:
        return KNOWN_CATEGORIES[key][1]
    return PREMIUM_EMOJI_MAP.get('🛍', TIKTOK_PRODUCT_EMOJI_ID)
# Tək kod nöqtəli emoji-ləri uzunluğa görə sıralayırıq (uzun olanlar əvvəl yoxlanmalı,
# məsələn variation selector daxil olan emoji-lər səhv bölünməsin)
_EMOJI_KEYS_SORTED = sorted(PREMIUM_EMOJI_MAP.keys(), key=len, reverse=True)

# ===== DATABASE CONNECTION POOL =====
db_pool = psycopg2.pool.SimpleConnectionPool(1, 10, DATABASE_URL)

def get_conn():
    return db_pool.getconn()

def put_conn(conn):
    db_pool.putconn(conn)

def init_db():
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
            registration_date TEXT,
            is_verified BOOLEAN DEFAULT TRUE,
            captcha_answer INTEGER,
            pending_referrer BIGINT
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
            status TEXT DEFAULT 'Beklemede',
            order_date TEXT,
            profile_link TEXT,
            log_message_id BIGINT
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

        try:
            c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS log_message_id BIGINT")
        except Exception:
            pass

        try:
            c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT TRUE")
            c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS captcha_answer INTEGER")
            c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS pending_referrer BIGINT")
            c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS bonus_balance INTEGER DEFAULT 0")
        except Exception:
            pass

        # PanelBaku SMM API inteqrasiyası üçün yeni sütunlar
        try:
            c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS api_service_id INTEGER")
            c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS api_quantity INTEGER")
            c.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS api_provider TEXT DEFAULT 'panelbaku'")
            c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS panel_order_id TEXT")
            c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS api_status TEXT")
            c.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS paid_price INTEGER")
        except Exception:
            pass

        c.execute('''CREATE TABLE IF NOT EXISTS admins (
            admin_id BIGINT PRIMARY KEY,
            added_by BIGINT,
            added_date TEXT
        )''')

        c.execute('CREATE INDEX IF NOT EXISTS idx_users_id ON users(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_transfers_sender ON transfers(sender_id)')

        conn.commit()
        c.close()

        _seed_products(conn)
        _strip_quantity_labels_from_names(conn)

        logger.info("Database başlatıldı")
    finally:
        put_conn(conn)

def _seed_products(conn):
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("SELECT COUNT(*) as cnt FROM products")
        count = c.fetchone()['cnt']
        if count == 0:
            c.execute(
                "INSERT INTO products (name, category, price, stock, vip_only) VALUES (%s, %s, %s, %s, %s)",
                ('TikTok İzlenme', 'TikTok', 10, 999999, False)
            )
            c.execute(
                "INSERT INTO products (name, category, price, stock, vip_only) VALUES (%s, %s, %s, %s, %s)",
                ('Telegram Abone (Garantili)', 'Telegram', 10, 999999, False)
            )
            conn.commit()
            logger.info("Default məhsullar əlavə edildi")
    except Exception as e:
        logger.error(f"_seed_products error: {e}")

def _strip_quantity_labels_from_names(conn):
    """
    Mövcud məhsul adlarından '1k', '10k', '100k' kimi miqdar göstəricilərini silir
    (məs. 'TikTok 10k İzlenme' -> 'TikTok İzlenme'). Bu, miqdar sistemi tətbiq olunduqdan
    sonra ad daxilindəki köhnə sabit rəqəmlərin istifadəçini çaşdırmaması üçündür.
    İdempotentdir - dəfələrlə işləsə də əlavə zərər vermir.
    """
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute("SELECT product_id, name FROM products")
        products = c.fetchall()
        pattern = re.compile(r'\b\d+k\b', re.IGNORECASE)
        for p in products:
            new_name = pattern.sub('', p['name'])
            new_name = re.sub(r'\s{2,}', ' ', new_name).strip()
            if new_name != p['name'] and new_name:
                c.execute('UPDATE products SET name = %s WHERE product_id = %s', (new_name, p['product_id']))
        conn.commit()
    except Exception as e:
        logger.error(f"_strip_quantity_labels_from_names error: {e}")
        conn.rollback()

try:
    init_db()
except Exception as e:
    logger.error(f"Database başlatma hatası: {e}")

# ===== LANGUAGE =====
LANG = {
    'TR': {
        'welcome': '☀️ Merhaba\n\n👾 <b>Wextyro SMM TR</b>\n<i>Türkiye\'nin güvenilir dijital ürün marketi.</i>\n\nİşlem seçin:',
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
            'Wextyro SMM TR olarak sizlere her zaman daha iyi, daha hızlı, daha uzun süre ve daha uygun fiyata hizmet verebilmek için büyük emek harcıyoruz.\n\n'
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
            '🟡 Beklemede — Onay bekleniyor\n'
            '🟢 Tamamlandı — Teslim edildi\n'
            '🔴 Reddedildi — İptal edildi\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '🎫 Promosyon Kodu Nedir? ⁉️\n'
            'Yönetici tarafından oluşturulan özel kodlardır.\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '🤝 Davet Et Kazan Nedir ⁉️\n'
            'Size özel davet linkinizi paylaşın. Her katılan kişi için otomatik +1 Puan kazanırsınız.\n'
            '20 kişiyi davet ederek VIP üye olabilirsiniz.\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '💰 Puan Transfer ⁉️\n'
            'Günde 2 transfer hakkınız vardır. Her transferde 1 Puan komisyon kesilir.\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '⁉️ Destek İçin: <b>Destek</b> butonu üzerinden ulaşabilirsiniz ⁉️'
        ),

        'coupon_maintenance': '🔧 Kupon Sistemi Tamirde',
        'generic_error': '⚠️ Bir şeyler ters gitti, lütfen tekrar deneyin.',
        'lang_select': 'Lütfen dil tercihinizi yapın / Please select your language:',
    },
    'EN': {
        'welcome': '☀️ Hello\n\n👾 <b>Wextyro SMM TR</b>\n<i>Turkey\'s trusted digital product marketplace.</i>\n\nSelect an operation:',
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
            'As Wextyro SMM TR, we work hard to always provide you better, faster, longer-lasting and more affordable service.\n\n'
            'If you are happy with our services, you can support us with a star <b>donation</b>. Every contribution means a lot to us. Thank you! 🙏\n\n'
            'How many stars would you like to <b>donate</b>?'
        ),
        'donate_invoice_sent': '⭐️ A {stars}-star donation invoice has been sent to you in private. Please complete the payment.',

        'help_text': (
            '📖 <b>HELP CENTER</b> 📖\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '🛍 What is the Shop ⁉️\n'
            'The bot\'s main sales area. You can buy products organized into categories here.\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '👑 VIP Shop & Membership ⁉️\n'
            'VIP benefits: 👑 VIP Shop access • 🎁 2x daily bonus • 🤝 +2 Points per referral\n\n'
            '━━━━━━━━━━━━━━━━━\n'
            '⁉️ For Support: Use the <b>Support</b> button ⁉️'
        ),

        'coupon_maintenance': '🔧 Coupon System Under Maintenance',
        'generic_error': '⚠️ Something went wrong, please try again.',
        'lang_select': 'Lütfen dil tercihinizi yapın / Please select your language:',
    }
}

# ===== PREMIUM EMOJİ + HTML -> (text, entities) CONVERTER =====
# Telegram API parse_mode və entities-i eyni anda qəbul etmir, ona görə
# mövcud <b>/<i> HTML taglarını əl ilə entity-yə çeviririk, eyni zamanda
# mətndəki unicode emoji-ləri premium custom_emoji entity-lərinə çeviririk.

def render_with_premium_emoji(html_text):
    """
    HTML-bənzər mətni (yalnız <b> və <i> dəstəklənir) plain mətnə çevirir,
    bold/italic/custom_emoji üçün MessageEntity siyahısı qaytarır.
    Qaytarır: (plain_text, [MessageEntity, ...])
    """
    entities = []
    plain_parts = []
    plain_len = 0  # UTF-16 kod vahidi sayğacı (Telegram entity offset-ləri belə hesablanır)

    def utf16_len(s):
        return len(s.encode('utf-16-le')) // 2

    # Tag yığını: (tag_adı, başlanğıc_offset)
    stack = []
    pos = 0
    tag_pattern = re.compile(r'</?(b|i)>')

    for m in tag_pattern.finditer(html_text):
        # Tag-dan əvvəlki düz mətni emoji-ləri çevirərək əlavə et
        chunk = html_text[pos:m.start()]
        if chunk:
            plain_len = _append_chunk_with_emoji(chunk, plain_parts, entities, plain_len, utf16_len)
        pos = m.end()

        tag_text = m.group(0)
        tag_name = m.group(1)
        if tag_text.startswith('</'):
            # bağlanış tagı -> yığından uyğun açılışı tap
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == tag_name:
                    _, start_offset = stack.pop(i)
                    length = plain_len - start_offset
                    if length > 0:
                        ent_type = MessageEntity.BOLD if tag_name == 'b' else MessageEntity.ITALIC
                        entities.append(MessageEntity(type=ent_type, offset=start_offset, length=length))
                    break
        else:
            stack.append((tag_name, plain_len))

    # Qalan mətn
    chunk = html_text[pos:]
    if chunk:
        plain_len = _append_chunk_with_emoji(chunk, plain_parts, entities, plain_len, utf16_len)

    plain_text = ''.join(plain_parts)
    # Entity-ləri offset-ə görə sırala (Telegram bunu tələb edir)
    entities.sort(key=lambda e: e.offset)
    return plain_text, entities

def _append_chunk_with_emoji(chunk, plain_parts, entities, plain_len, utf16_len):
    """Düz mətn parçasını emoji-lərə görə bölüb premium custom_emoji entity-ləri yaradır."""
    i = 0
    n = len(chunk)
    VARIATION_SELECTOR_16 = '\ufe0f'
    while i < n:
        matched = False
        for emoji_char in _EMOJI_KEYS_SORTED:
            elen = len(emoji_char)
            if chunk[i:i + elen] == emoji_char:
                custom_id = PREMIUM_EMOJI_MAP[emoji_char]
                # Telegram custom_emoji entity-si üçün placeholder mətn olaraq
                # orijinal emoji-nin özünü saxlamaq tövsiyə olunur (placeholder kimi göstərir)
                plain_parts.append(emoji_char)
                elen_utf16 = utf16_len(emoji_char)
                entities.append(MessageEntity(
                    type=MessageEntity.CUSTOM_EMOJI,
                    offset=plain_len,
                    length=elen_utf16,
                    custom_emoji_id=custom_id
                ))
                plain_len += elen_utf16
                i += elen
                # Əgər bu emoji-dən dərhal sonra variation selector (️) gəlirsə, onu sil -
                # əks halda custom_emoji görüntüsünün yanında görünməz/qoşa simvol effekti yaranır.
                if i < n and chunk[i] == VARIATION_SELECTOR_16:
                    i += 1
                matched = True
                break
        if not matched:
            ch = chunk[i]
            plain_parts.append(ch)
            plain_len += utf16_len(ch)
            i += 1
    return plain_len

async def send_rich(bot, chat_id, html_text, reply_markup=None):
    """parse_mode əvəzinə entities ilə premium-emoji-uyğun mesaj göndərir."""
    plain_text, entities = render_with_premium_emoji(html_text)
    return await bot.send_message(chat_id, plain_text, entities=entities, reply_markup=reply_markup)

async def reply_rich(message, html_text, reply_markup=None):
    plain_text, entities = render_with_premium_emoji(html_text)
    return await message.reply_text(plain_text, entities=entities, reply_markup=reply_markup)

async def edit_rich(query, html_text, reply_markup=None):
    plain_text, entities = render_with_premium_emoji(html_text)
    try:
        await query.edit_message_text(plain_text, entities=entities, reply_markup=reply_markup)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            try:
                await query.answer()
            except Exception:
                pass
        else:
            logger.error(f"edit_rich error: {e}")
    except Exception as e:
        logger.error(f"edit_rich unexpected error: {e}")

# ===== HELPER FUNCTIONS =====
def is_admin(user_id):
    if user_id == ADMIN_ID:
        return True
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute('SELECT 1 FROM admins WHERE admin_id = %s', (user_id,))
        return c.fetchone() is not None
    except Exception:
        return False
    finally:
        put_conn(conn)

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
        c.execute('''INSERT INTO users (user_id, username, balance, registration_date, is_verified)
                     VALUES (%s, %s, %s, %s, FALSE)
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

def set_pending_referrer(user_id, referrer_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute('UPDATE users SET pending_referrer = %s WHERE user_id = %s', (referrer_id, user_id))
        conn.commit()
    except Exception as e:
        logger.error(f"set_pending_referrer error: {e}")
    finally:
        put_conn(conn)

def set_captcha_answer(user_id, answer):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute('UPDATE users SET captcha_answer = %s WHERE user_id = %s', (answer, user_id))
        conn.commit()
    except Exception as e:
        logger.error(f"set_captcha_answer error: {e}")
    finally:
        put_conn(conn)

def set_verified(user_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute('UPDATE users SET is_verified = TRUE, captcha_answer = NULL WHERE user_id = %s', (user_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"set_verified error: {e}")
    finally:
        put_conn(conn)

def clear_pending_referrer(user_id):
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute('UPDATE users SET pending_referrer = NULL WHERE user_id = %s', (user_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"clear_pending_referrer error: {e}")
    finally:
        put_conn(conn)

async def credit_referral(context, referrer_id, referred_user_id, referred_name):
    conn = get_conn()
    referrer = None
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT 1 FROM referrals WHERE referrer_id = %s AND referred_user_id = %s',
                 (referrer_id, referred_user_id))
        if c.fetchone():
            return
        c.execute('SELECT * FROM users WHERE user_id = %s', (referrer_id,))
        referrer = c.fetchone()
        if not referrer:
            return
        bonus = 2 if referrer['vip_status'] else 1
        c.execute('''INSERT INTO referrals (referrer_id, referred_user_id, referral_date)
                   VALUES (%s, %s, %s)''',
                 (referrer_id, referred_user_id, datetime.now().strftime('%Y-%m-%d %H:%M')))
        c.execute('UPDATE users SET referrals = referrals + 1, balance = balance + %s WHERE user_id = %s',
                 (bonus, referrer_id))
        conn.commit()
    except Exception as e:
        logger.error(f"credit_referral db error: {e}")
        conn.rollback()
        return
    finally:
        put_conn(conn)

    try:
        ref_lang = get_user_language(referrer)
        notify = ('🤝 Yeni bir kişi linkinizle katıldı!\n➕ +{} Puan kazandınız!' if ref_lang == 'TR'
                  else '🤝 Someone joined using your link!\n➕ You earned +{} Points!').format(bonus)
        await send_rich(context.bot, referrer_id, notify)
    except Exception as e:
        logger.error(f"referrer notify error: {e}")

    referrer_name = referrer.get('username') or str(referrer_id)
    log_text = (
        f"🤝 <b>Yeni Referans</b>\n\n"
        f"👤 <b>Referans Veren:</b> {referrer_name} ({referrer_id})\n"
        f"👤 <b>Yeni Üye:</b> {referred_name} ({referred_user_id})\n"
        f"📅 <b>Tarih:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    try:
        await send_rich(context.bot, LOG_CHANNEL, log_text)
    except Exception as e:
        logger.error(f"referral log channel error: {e}")

def get_user_language(user_id_or_user):
    try:
        if isinstance(user_id_or_user, dict):
            user = user_id_or_user
        else:
            user = get_user(user_id_or_user)
        return user['language'] if user and user.get('language') else 'TR'
    except Exception:
        return 'TR'

def get_text(key, lang_or_user_id, **kwargs):
    if lang_or_user_id in ('TR', 'EN'):
        lang = lang_or_user_id
    else:
        lang = get_user_language(lang_or_user_id)
    text = LANG.get(lang, LANG['TR']).get(key, LANG['TR'].get(key, ''))
    return text.format(**kwargs) if kwargs else text

async def safe_edit(query, text, reply_markup=None):
    """Geriyə uyğunluq üçün saxlanılan ad - artıq premium emoji render edir."""
    await edit_rich(query, text, reply_markup)

def get_products_by_category(category, vip_only=None):
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        if vip_only is None:
            c.execute('SELECT * FROM products WHERE category ILIKE %s', (category,))
        else:
            c.execute('SELECT * FROM products WHERE category ILIKE %s AND vip_only = %s', (category, vip_only))
        return c.fetchall()
    except Exception as e:
        logger.error(f"get_products_by_category error: {e}")
        return []
    finally:
        put_conn(conn)

def get_all_categories():
    """Qeyri-VIP məhsulların mövcud olduğu bütün unikal kateqoriyaları gətirir (mağaza menyusu üçün).
    Case-insensitive deduplication edilir ki, köhnə fərqli yazılışlı qeydlər (Instagram/instagram)
    mağazada iki ayrı düymə kimi görünməsin."""
    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute('SELECT DISTINCT category FROM products WHERE vip_only = FALSE ORDER BY category')
        raw_categories = [row[0] for row in c.fetchall()]
        seen = {}
        for cat in raw_categories:
            display_name = normalize_category(cat)
            key = display_name.lower()
            if key not in seen:
                seen[key] = display_name
        return sorted(seen.values())
    except Exception as e:
        logger.error(f"get_all_categories error: {e}")
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

def order_status_emoji(status):
    if status == 'Beklemede':
        return '🟡'
    elif status == 'Tamamlandı':
        return '🟢'
    elif status == 'Reddedildi':
        return '🔴'
    return '⚪'

def main_menu_keyboard(user):
    lang = get_user_language(user)
    is_vip = bool(user and user.get('vip_status'))

    if is_vip:
        vip_row = [InlineKeyboardButton(
            'VIP Üye' if lang == 'TR' else 'VIP Member',
            callback_data='vip_already_info',
            style='primary',
            icon_custom_emoji_id=PREMIUM_EMOJI_MAP['👑']
        )]
    else:
        vip_row = [InlineKeyboardButton(
            get_text('vip_button', lang).replace('👑 ', ''),
            callback_data='vip_purchase',
            style='primary',
            icon_custom_emoji_id=PREMIUM_EMOJI_MAP['👑']
        )]

    keyboard = [
        [InlineKeyboardButton(get_text('balance', lang).replace('💎 ', ''), callback_data='balance',
                               style='success', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['💎']),
         InlineKeyboardButton(get_text('profile', lang).replace('👤 ', ''), callback_data='profile',
                               style='success', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['👤'])],
        [InlineKeyboardButton(get_text('shop', lang).replace('🛍️ ', ''), callback_data='shop',
                               style='danger', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['🛍']),
         InlineKeyboardButton('VIP Mağaza' if lang == 'TR' else 'VIP Shop', callback_data='vip_shop',
                               style='danger', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['👑'])],
        vip_row,
        [InlineKeyboardButton(get_text('daily_bonus', lang).replace('🎁 ', ''), callback_data='daily_bonus',
                               style='success', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['💎']),
         InlineKeyboardButton(get_text('orders', lang).replace('📦 ', ''), callback_data='orders',
                               style='success', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['📦'])],
        [InlineKeyboardButton(get_text('transfer', lang).replace('💰 ', ''), callback_data='transfer',
                               style='danger', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['💰']),
         InlineKeyboardButton(get_text('coupon', lang).replace('🎫 ', ''), callback_data='coupon',
                               style='danger')],
        [InlineKeyboardButton(get_text('referral', lang).replace('🤝 ', ''), callback_data='referral',
                               style='primary', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['🤝']),
         InlineKeyboardButton(get_text('support', lang).replace('💬 ', ''), callback_data='support',
                               style='primary', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['💬'])],
        [InlineKeyboardButton(get_text('help', lang).replace('❓ ', ''), callback_data='help',
                               style='success', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['❓']),
         InlineKeyboardButton(get_text('language', lang).replace('🌍 ', ''), callback_data='language',
                               style='success', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['🌍'])],
        [InlineKeyboardButton(get_text('raffle', lang).replace('🎲 ', ''), callback_data='raffle',
                               style='primary', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['🎲']),
         InlineKeyboardButton(get_text('donate', lang).replace('⭐️ ', ''), callback_data='donate',
                               style='primary', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['⭐'])]
    ]
    return InlineKeyboardMarkup(keyboard)

def back_to_menu_markup(lang):
    return InlineKeyboardMarkup([[InlineKeyboardButton(
        get_text('back_to_menu', lang), callback_data='main_menu', style='danger'
    )]])

def is_valid_url(url):
    pattern = re.compile(
        r'^https?://'
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'
        r'localhost|'
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        r'(?::\d+)?'
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return bool(pattern.match(url))

# ===== LINK FORMAT DOĞRULAMASI =====
# Bir ürünün "profil/kanal" linki mi yoksa "post/video" linki mi istediğini ürün adındaki
# anahtar kelimelere göre belirleriz. Takipçi/Abone -> profil linki, diğerleri (Beğeni,
# İzlenme, Yorum, Görüntülenme vb.) -> post/video linki.
PROFILE_LINK_KEYWORDS = ['takipçi', 'takipci', 'abone', 'üye', 'uye', 'kanal']

def product_needs_profile_link(product_name):
    """Məhsul adına görə profil/kanal linki tələb olunub-olunmadığını müəyyən edir."""
    lowered = product_name.lower()
    return any(k in lowered for k in PROFILE_LINK_KEYWORDS)

# Hər platforma üçün profil linki və post linki nümunələri + doğrulama pattern-ləri.
LINK_RULES = {
    'TikTok': {
        'profile_pattern': re.compile(r'^https?://(www\.)?tiktok\.com/@[\w.\-]+/?$', re.IGNORECASE),
        'post_pattern': re.compile(r'^https?://(www\.)?tiktok\.com/@[\w.\-]+/video/\d+', re.IGNORECASE),
        'profile_example': 'https://tiktok.com/@kullaniciadi',
        'post_example': 'https://tiktok.com/@kullaniciadi/video/1234567890',
    },
    'Instagram': {
        'profile_pattern': re.compile(r'^https?://(www\.)?instagram\.com/[\w.\-]+/?$', re.IGNORECASE),
        'post_pattern': re.compile(r'^https?://(www\.)?instagram\.com/(p|reel|tv)/[\w\-]+', re.IGNORECASE),
        'profile_example': 'https://instagram.com/kullaniciadi',
        'post_example': 'https://instagram.com/p/AbCdEfGhIjK',
    },
    'Telegram': {
        'profile_pattern': re.compile(r'^https?://t\.me/[\w]+/?$', re.IGNORECASE),
        'post_pattern': re.compile(r'^https?://t\.me/[\w]+/\d+', re.IGNORECASE),
        'profile_example': 't.me/kanaladi',
        'post_example': 't.me/kanaladi/123',
    },
    'YouTube': {
        'profile_pattern': re.compile(r'^https?://(www\.)?youtube\.com/(@[\w\-]+|channel/[\w\-]+|c/[\w\-]+)/?$', re.IGNORECASE),
        'post_pattern': re.compile(r'^https?://(www\.)?(youtube\.com/watch\?v=[\w\-]+|youtu\.be/[\w\-]+)', re.IGNORECASE),
        'profile_example': 'https://youtube.com/@kanaladi',
        'post_example': 'https://youtube.com/watch?v=AbCdEfGhIjK',
    },
    'WhatsApp': None,  # WhatsApp linkleri admin tarafından manuel kontrol edilir, format zorlaması yok.
}

def get_link_rules_for_category(category):
    """LINK_RULES-dan kateqoriyaya uyğun qaydaları case-insensitive şəkildə tapır."""
    category_key = (category or '').strip().lower()
    for known_cat, cat_rules in LINK_RULES.items():
        if known_cat.lower() == category_key:
            return cat_rules
    return None

def validate_order_link(category, product_name, link):
    """
    Sipariş linkinin, ürünün kategorisine ve tipine (profil/post) uygun olup olmadığını kontrol eder.
    Qaytarır: (is_valid: bool, example_or_None: str)
    Kategori tanınmazsa veya WhatsApp ise, sadece genel URL formatı kontrol edilir (her zaman geçerli kabul edilir).
    Kategori adı eşleşmesi case-insensitive yapılır (TikTok/Tiktok/tiktok hepsi aynı kabul edilir).
    """
    rules = get_link_rules_for_category(category)
    if not rules:
        return is_valid_url(link), None

    needs_profile = product_needs_profile_link(product_name)
    pattern = rules['profile_pattern'] if needs_profile else rules['post_pattern']
    example = rules['profile_example'] if needs_profile else rules['post_example']

    link_check = link.strip()
    if not link_check.startswith('http'):
        link_check = 'https://' + link_check

    if pattern.match(link_check):
        return True, None
    return False, example

# ===== SMM API (PanelBaku + AzeTakip) =====
SMM_PROVIDERS = {
    'panelbaku': {'url': PANELBAKU_API_URL, 'key': PANELBAKU_API_KEY, 'label': 'PanelBaku'},
    'azetakip': {'url': AZETAKIP_API_URL, 'key': AZETAKIP_API_KEY, 'label': 'AzeTakip'},
}

def get_provider_config(provider):
    return SMM_PROVIDERS.get(provider, SMM_PROVIDERS['panelbaku'])

async def smm_get_balance(provider):
    """Verilən provider-in (panelbaku/azetakip) cari balansını çəkir.
    Qaytarır: (balance: float, currency: str) və ya (None, None) xəta halında."""
    cfg = get_provider_config(provider)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(cfg['url'], data={
                'key': cfg['key'],
                'action': 'balance'
            })
            data = resp.json()
            if isinstance(data, dict) and 'balance' in data:
                return float(data['balance']), data.get('currency', '')
            return None, None
    except Exception as e:
        logger.error(f"smm_get_balance[{provider}] error: {e}")
        return None, None

async def smm_add_order(provider, service_id, link, quantity):
    """
    Verilən provider-ə sifariş göndərir.
    Qaytarır: (success: bool, order_id_or_None, error_message_or_None)
    """
    cfg = get_provider_config(provider)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(cfg['url'], data={
                'key': cfg['key'],
                'action': 'add',
                'service': service_id,
                'link': link,
                'quantity': quantity
            })
            data = resp.json()

            if isinstance(data, dict) and 'order' in data:
                return True, str(data['order']), None

            error_msg = str(data.get('error', data)) if isinstance(data, dict) else str(data)
            return False, None, error_msg
    except Exception as e:
        logger.error(f"smm_add_order[{provider}] error: {e}")
        return False, None, str(e)

async def smm_get_status(provider, order_id):
    """Verilən provider-dəki sifarişin statusunu sorğulayır.
    Qaytarır: dict (məs. {'status': 'Completed', ...}) və ya None xəta halında."""
    cfg = get_provider_config(provider)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(cfg['url'], data={
                'key': cfg['key'],
                'action': 'status',
                'order': order_id
            })
            data = resp.json()
            if isinstance(data, dict) and 'status' in data:
                return data
            return None
    except Exception as e:
        logger.error(f"smm_get_status[{provider}] error: {e}")
        return None

def is_insufficient_balance_error(error_message):
    """SMM panel-in balans yetersizliği xətasını tanıyır (panel müxtəlif dillərdə mətn qaytara bilər)."""
    if not error_message:
        return False
    lowered = error_message.lower()
    keywords = ['balance', 'bakiye', 'bakiyə', 'insufficient', 'yetersiz', 'funds']
    return any(k in lowered for k in keywords)

async def try_send_order_to_panel(order_id, user_id, provider, service_id, link, quantity, context):
    """
    Bir sifarişi uyğun SMM provider-ə göndərməyə cəhd edir və DB-ni uyğun şəkildə yeniləyir.
    Bu fonksiya admin-istisna istifadəçilər üçün çağırılmamalıdır (əvvəlcədən yoxlanmalıdır).
    Qaytarır: 'sent' | 'insufficient_balance' | 'error'
    """
    success, ext_order_id, error_msg = await smm_add_order(provider, service_id, link, quantity)

    conn = get_conn()
    try:
        c = conn.cursor()
        if success:
            c.execute(
                "UPDATE orders SET status = 'Onaylandı', panel_order_id = %s, api_status = 'Gönderildi' WHERE order_id = %s",
                (ext_order_id, order_id)
            )
            conn.commit()
        else:
            api_status = 'Bakiye Yetersiz' if is_insufficient_balance_error(error_msg) else 'Gönderim Hatası'
            c.execute(
                "UPDATE orders SET api_status = %s WHERE order_id = %s",
                (api_status, order_id)
            )
            conn.commit()
    except Exception as e:
        logger.error(f"try_send_order_to_panel db error: {e}")
        conn.rollback()
    finally:
        put_conn(conn)

    if success:
        return 'sent'
    elif is_insufficient_balance_error(error_msg):
        return 'insufficient_balance'
    else:
        return 'error'

# ===== MAIN HANDLERS =====
async def send_captcha(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    a = random.randint(2, 15)
    b = random.randint(1, 10)
    correct = a + b
    set_captcha_answer(user_id, correct)

    options = {correct}
    deltas = [-7, -5, -3, -2, -1, 1, 2, 3, 5, 7]
    random.shuffle(deltas)
    for d in deltas:
        if len(options) >= 4:
            break
        fake = correct + d
        if fake > 0:
            options.add(fake)
    options = list(options)
    random.shuffle(options)

    text = (
        "📆 <b>Güvenlik Doğrulaması</b> 📆\n\n"
        "⁉️ Soruyu çözün ⁉️\n\n"
        f"<b>{a}</b> + <b>{b}</b> = ?\n\n"
        "➕ Doğru cevabı seçin: ➕"
    )
    btns = [InlineKeyboardButton(str(opt), callback_data=f'captcha_{opt}', style='primary') for opt in options]
    rows = [[b] for b in btns]  # hər düymə öz sırasında - 1 1 1 1 düzümü, 2 2 yox
    keyboard = InlineKeyboardMarkup(rows)

    # Bu mesajdaki "📆" (Güvenlik Doğrulaması başlığında) ümumi map-dakı 📆 ID-sindən fərqli,
    # xüsusi bir ID istəyir. Render etdikdən sonra hər iki 📆 instansını yeni ID-yə dəyişirik.
    plain_text, entities = render_with_premium_emoji(text)
    default_calendar_id = PREMIUM_EMOJI_MAP['📆']
    for idx, ent in enumerate(entities):
        if ent.type == MessageEntity.CUSTOM_EMOJI and ent.custom_emoji_id == default_calendar_id:
            entities[idx] = MessageEntity(
                type=MessageEntity.CUSTOM_EMOJI,
                offset=ent.offset,
                length=ent.length,
                custom_emoji_id='5030732809128379408'
            )

    if update.message:
        try:
            await update.message.reply_text(plain_text, entities=entities, reply_markup=keyboard)
        except Exception as e:
            logger.error(f"send_captcha reply error: {e}")
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(plain_text, entities=entities, reply_markup=keyboard)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.error(f"send_captcha edit error: {e}")
        except Exception as e:
            logger.error(f"send_captcha edit unexpected error: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        tg_user = update.message.from_user
        user_id = tg_user.id
    else:
        tg_user = update.callback_query.from_user
        user_id = tg_user.id

    existing_user = get_user(user_id)
    is_new_user = existing_user is None

    if is_new_user:
        create_user(user_id, tg_user.username or f"User{user_id}")
        existing_user = get_user(user_id)

        if update.message and context.args:
            try:
                referrer_id = int(context.args[0])
                if referrer_id != user_id and get_user(referrer_id):
                    set_pending_referrer(user_id, referrer_id)
            except (ValueError, IndexError):
                pass

    if not existing_user.get('is_verified', True):
        await send_captcha(update, context, user_id)
        return

    reply_markup = main_menu_keyboard(existing_user)
    lang = get_user_language(existing_user)
    welcome_text = get_text('welcome', lang)

    if update.message:
        await reply_rich(update.message, welcome_text, reply_markup)
    elif update.callback_query:
        await edit_rich(update.callback_query, welcome_text, reply_markup)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    answered = False

    async def answer_once(alert_text=None, show_alert=False):
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

    data_preview = query.data or ''
    will_show_alert = (data_preview in ('daily_bonus', 'vip_shop')) or data_preview.startswith('buy_confirm_') or data_preview.startswith('captcha_')
    if not will_show_alert:
        await answer_once()

    try:
        data = query.data

        # ===== GÜVENLİK DOĞRULAMASI =====
        if data.startswith('captcha_'):
            try:
                guessed = int(data.split('_', 1)[1])
            except ValueError:
                await answer_once()
                return

            stored_answer = user.get('captcha_answer')
            if stored_answer is None:
                await answer_once()
                return

            if guessed == stored_answer:
                set_verified(user_id)
                await answer_once()
                success_text = (
                    "✅ <b>Doğrulama Başarılı</b>\n\n"
                    "Botu Kullanmak için /start kullan"
                )
                try:
                    plain_text, entities = render_with_premium_emoji(success_text)
                    await query.edit_message_text(plain_text, entities=entities)
                except Exception as e:
                    logger.error(f"captcha success edit error: {e}")

                pending_referrer = user.get('pending_referrer')
                if pending_referrer:
                    referred_name = query.from_user.username or query.from_user.first_name or str(user_id)
                    await credit_referral(context, pending_referrer, user_id, referred_name)
                    clear_pending_referrer(user_id)
            else:
                await answer_once('❌ Yanlış cevap! Tekrar deneyin.', show_alert=True)
            return

        # ===== BALANCE / PROFILE =====
        elif data in ('balance', 'profile'):
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
                [InlineKeyboardButton(get_text('daily_bonus', lang).replace('🎁 ', ''), callback_data='daily_bonus',
                                       style='success', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['💎'])],
                [InlineKeyboardButton(get_text('back_to_menu', lang), callback_data='main_menu', style='danger')]
            ])
            await safe_edit(query, text, keyboard)

        # ===== DAILY BONUS =====
        elif data == 'daily_bonus':
            is_vip = bool(user['vip_status'])
            today = datetime.now().strftime('%Y-%m-%d')
            max_per_day = 2 if is_vip else 1

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

        # ===== REFERRAL =====
        elif data == 'referral':
            text = get_text('referral_link', lang, user_id=user_id, bot_username=BOT_USERNAME)
            await safe_edit(query, text, back_markup)

        # ===== LANGUAGE =====
        elif data == 'language':
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton('Türkçe', callback_data='lang_tr', style='success',
                                       icon_custom_emoji_id='5891175480488367676'),
                 InlineKeyboardButton('English', callback_data='lang_en', style='success',
                                       icon_custom_emoji_id='5202196682497859879')],
                [InlineKeyboardButton(get_text('back_to_menu', lang), callback_data='main_menu', style='danger')]
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

        # ===== SHOP =====
        elif data == 'shop':
            categories = get_all_categories()
            if not categories:
                text = get_text('category_empty', lang, category=('Mağaza' if lang == 'TR' else 'Shop'))
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
                    get_text('back_to_menu', lang), callback_data='main_menu', style='danger'
                )]])
                await safe_edit(query, text, keyboard)
            else:
                rows = []
                for i in range(0, len(categories), 2):
                    row = []
                    for cat in categories[i:i + 2]:
                        row.append(InlineKeyboardButton(
                            cat, callback_data=f"shop_cat_{cat}",
                            style='success', icon_custom_emoji_id=get_category_icon(cat)
                        ))
                    rows.append(row)
                rows.append([InlineKeyboardButton(get_text('back_to_menu', lang), callback_data='main_menu', style='danger')])
                await safe_edit(query, get_text('shop_welcome', lang), InlineKeyboardMarkup(rows))

        elif data.startswith('shop_cat_'):
            category = data[len('shop_cat_'):]
            products = get_products_by_category(category, vip_only=False)
            cat_icon = get_category_icon(category)

            if not products:
                text = get_text('category_empty', lang, category=category)
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
                    get_text('back_to_menu', lang), callback_data='shop', style='danger'
                )]])
                await safe_edit(query, text, keyboard)
            else:
                listing_title = 'Ürünler Listeleniyor' if lang == 'TR' else 'Products Listed'
                listing_prompt = ('Satın almak istediğiniz ürünü seçin:' if lang == 'TR'
                                   else 'Select the product you want to buy:')
                text = f"👍 <b>{listing_title}</b>\n\n{listing_prompt}"
                rows = []
                for p in products:
                    rows.append([InlineKeyboardButton(
                        p['name'], callback_data=f"buy_{p['product_id']}",
                        style='success', icon_custom_emoji_id=cat_icon
                    )])
                rows.append([InlineKeyboardButton(get_text('back_to_menu', lang), callback_data='shop', style='danger')])
                # "👍" emojisi bu mesajda fərqli premium ID istəyir. Mətndə yalnız bir dəfə keçdiyi üçün,
                # render olunmuş entity siyahısında onun custom_emoji_id-sini (ümumi map-dakı dəyər) tapıb dəyişirik.
                plain_text, entities = render_with_premium_emoji(text)
                default_thumbsup_id = PREMIUM_EMOJI_MAP['👍']
                for idx, ent in enumerate(entities):
                    if ent.type == MessageEntity.CUSTOM_EMOJI and ent.custom_emoji_id == default_thumbsup_id:
                        entities[idx] = MessageEntity(
                            type=MessageEntity.CUSTOM_EMOJI,
                            offset=ent.offset,
                            length=ent.length,
                            custom_emoji_id='6266995104687330978'
                        )
                        break
                try:
                    await query.edit_message_text(plain_text, entities=entities, reply_markup=InlineKeyboardMarkup(rows))
                except BadRequest as e:
                    if "Message is not modified" not in str(e):
                        logger.error(f"shop listing edit error: {e}")
                except Exception as e:
                    logger.error(f"shop listing edit unexpected error: {e}")

        # ===== VIP SHOP =====
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
                    stock_text = 'Sınırsız' if p['stock'] >= 999999 else str(p['stock'])
                    text += f"<b>{p['name']}</b>\n💵 Fiyat: {p['price']} Puan | 📦 Stok: {stock_text}\n\n"
                    rows.append([InlineKeyboardButton(
                        p['name'], callback_data=f"buy_{p['product_id']}",
                        style='success', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['👑']
                    )])
                rows.append([InlineKeyboardButton(get_text('back_to_menu', lang), callback_data='main_menu', style='danger')])
                await safe_edit(query, text, InlineKeyboardMarkup(rows))

        # ===== VIP PURCHASE =====
        elif data == 'vip_purchase':
            if user['vip_status']:
                await safe_edit(query, get_text('vip_already', lang), back_markup)
                return

            current = user['referrals']
            required = VIP_REFERRAL_REQUIREMENT
            missing = max(0, required - current)

            if missing == 0:
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

        # ===== ORDERS =====
        elif data == 'orders':
            conn = get_conn()
            try:
                c = conn.cursor(cursor_factory=RealDictCursor)
                c.execute('''
                    SELECT o.*, p.name as product_name, p.price as product_price
                    FROM orders o
                    JOIN products p ON o.product_id = p.product_id
                    WHERE o.user_id = %s
                    ORDER BY o.order_id DESC
                ''', (user_id,))
                orders = c.fetchall()
            except Exception as e:
                logger.error(f"orders fetch error: {e}")
                orders = []
            finally:
                put_conn(conn)

            if not orders:
                await safe_edit(query, get_text('no_orders', lang), back_markup)
            else:
                title = '📦 <b>Siparişleriniz</b>' if lang == 'TR' else '📦 <b>Your Orders</b>'
                text = f"{title} ({len(orders)}):\n\n"
                for order in orders:
                    emoji = order_status_emoji(order['status'])
                    text += (
                        f"{emoji} <b>#{order['order_id']}</b> — {order['status']}\n"
                        f"🛍️ <b>{order['product_name']}</b>\n"
                        f"💵 {order['product_price']} Puan\n"
                        f"🔗 {order.get('profile_link', '-')}\n"
                        f"📅 {order.get('order_date', '-')}\n\n"
                    )
                await safe_edit(query, text, back_markup)

        # ===== TRANSFER =====
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

        # ===== RAFFLE =====
        elif data == 'raffle':
            await safe_edit(query, get_text('no_active_raffle', lang), back_markup)

        # ===== DONATE =====
        elif data == 'donate':
            star_icon = '6221736233970700254'
            buttons = [
                [InlineKeyboardButton('5 Yıldız Bağış', callback_data='donate_5', style='success', icon_custom_emoji_id=star_icon),
                 InlineKeyboardButton('10 Yıldız Bağış', callback_data='donate_10', style='success', icon_custom_emoji_id=star_icon)],
                [InlineKeyboardButton('15 Yıldız Bağış', callback_data='donate_15', style='success', icon_custom_emoji_id=star_icon),
                 InlineKeyboardButton('20 Yıldız Bağış', callback_data='donate_20', style='success', icon_custom_emoji_id=star_icon)],
                [InlineKeyboardButton('25 Yıldız Bağış', callback_data='donate_25', style='success', icon_custom_emoji_id=star_icon),
                 InlineKeyboardButton('30 Yıldız Bağış', callback_data='donate_30', style='success', icon_custom_emoji_id=star_icon)],
                [InlineKeyboardButton('35 Yıldız Bağış', callback_data='donate_35', style='success', icon_custom_emoji_id=star_icon),
                 InlineKeyboardButton('40 Yıldız Bağış', callback_data='donate_40', style='success', icon_custom_emoji_id=star_icon)],
                [InlineKeyboardButton('45 Yıldız Bağış', callback_data='donate_45', style='success', icon_custom_emoji_id=star_icon),
                 InlineKeyboardButton('50 Yıldız Bağış', callback_data='donate_50', style='success', icon_custom_emoji_id=star_icon)],
                [InlineKeyboardButton('75 Yıldız Bağış', callback_data='donate_75', style='success', icon_custom_emoji_id=star_icon),
                 InlineKeyboardButton('100 Yıldız Bağış', callback_data='donate_100', style='success', icon_custom_emoji_id=star_icon)],
                [InlineKeyboardButton(get_text('back_to_menu', lang), callback_data='main_menu', style='danger')]
            ]
            await safe_edit(query, get_text('donate_text', lang), InlineKeyboardMarkup(buttons))

        elif data.startswith('donate_') and not data.startswith('donate_invoice'):
            stars = int(data.split('_')[1])
            try:
                await context.bot.send_invoice(
                    chat_id=user_id,
                    title=f'Wextyro SMM - {stars} Yıldız Bağış',
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

        # ===== COUPON =====
        elif data == 'coupon':
            await safe_edit(query, get_text('coupon_maintenance', lang), back_markup)

        # ===== SUPPORT =====
        elif data == 'support':
            text = get_text('support_text', lang, balance=user['balance'])
            await safe_edit(query, text, back_markup)
            context.user_data['awaiting_support'] = True

        # ===== HELP =====
        elif data == 'help':
            await safe_edit(query, get_text('help_text', lang), back_markup)

        # ===== MAIN MENU =====
        elif data == 'main_menu':
            context.user_data['awaiting_transfer'] = False
            context.user_data['awaiting_support'] = False
            context.user_data['awaiting_profile_link'] = False
            context.user_data['pending_product_id'] = None
            await start(update, context)

        # ===== BUY — Məhsul Detay Səhifəsi =====
        elif data.startswith('buy_') and not data.startswith('buy_confirm_') and not data.startswith('buy_cancel_'):
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

            if not product:
                await answer_once('❌ Ürün bulunamadı!', show_alert=True)
                return

            stock_text = 'Sınırsız' if product['stock'] >= 999999 else str(product['stock'])

            back_cb = f"shop_cat_{product['category']}"

            text = (
                f"<b>{product['name']}</b>\n\n"
                f"💵 <b>Fiyat:</b> {product['price']} Puan\n"
                f"📦 <b>Stok:</b> {stock_text}\n\n"
                f"⁉️ Satın almak istiyorsunuz ⁉️"
            )
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton('Evet', callback_data=f'buy_confirm_{product_id}', style='success'),
                    InlineKeyboardButton('Hayır', callback_data=back_cb, style='danger')
                ]
            ])
            await safe_edit(query, text, keyboard)

        # ===== BUY CONFIRM — Miktar/Bakiye Yoxla, Link İstə =====
        elif data.startswith('buy_confirm_'):
            product_id = int(data.split('_')[2])
            conn = get_conn()
            try:
                c = conn.cursor(cursor_factory=RealDictCursor)
                c.execute('SELECT * FROM products WHERE product_id = %s', (product_id,))
                product = c.fetchone()
            except Exception as e:
                logger.error(f"buy_confirm fetch error: {e}")
                product = None
            finally:
                put_conn(conn)

            if not product:
                await answer_once('❌ Ürün bulunamadı!', show_alert=True)
                return

            await answer_once()

            # Miktar sistemi: eğer ürün bir API servisine bağlıysa (api_quantity dolu),
            # önce miktar soruyoruz, fiyat (price / api_quantity) * girilen_miktar olarak hesaplanır.
            # API'ye bağlı olmayan ürünlerde miktar sabit (1) kalır (eski davranış).
            if product.get('api_quantity'):
                context.user_data['awaiting_quantity'] = True
                context.user_data['pending_product_id'] = product_id

                min_qty = product['api_quantity']
                text = (
                    f"<b>{product['name']}</b>\n\n"
                    f"🔢 Sipariş etmek istediğiniz miktarı yazın.\n"
                    f"Minimum: <b>{min_qty}</b>\n\n"
                    f"İptal için /iptal yazın."
                )
                await safe_edit(query, text, InlineKeyboardMarkup([
                    [InlineKeyboardButton('İptal', callback_data='main_menu', style='danger')]
                ]))
                return

            # Eski davranış: miktar sabit (1), doğrudan bakiye kontrolü + link isteme
            if user['balance'] < product['price']:
                needed = product['price']
                text = (
                    f"👎 <b>Yetersiz Bakiye!</b>\n\n"
                    f"💵 <b>{needed} Puana</b> ihtiyacınız var.\n"
                    f"💎 Mevcut Bakiyeniz: <b>{user['balance']} Puan</b>"
                )
                await safe_edit(query, text, back_markup)
                return

            context.user_data['awaiting_profile_link'] = True
            context.user_data['pending_product_id'] = product_id
            context.user_data['pending_quantity'] = 1
            context.user_data['pending_price'] = product['price']

            rules = get_link_rules_for_category(product['category'])
            if rules:
                needs_profile = product_needs_profile_link(product['name'])
                example = rules['profile_example'] if needs_profile else rules['post_example']
                example_line = f"\n\n📋 Örnek: {example}"
            else:
                example_line = ""

            text = (
                f"🔗 <b>Sipariş Etmek İstediğiniz Bağlantıyı Girin</b>\n\n"
                f"🛍️ Ürün: <b>{product['name']}</b>\n"
                f"💵 Fiyat: <b>{product['price']} Puan</b>\n\n"
                f"Lütfen geçerli bir URL girin (https:// ile başlamalı).{example_line}\n\n"
                f"İptal için /iptal yazın."
            )
            await safe_edit(query, text, InlineKeyboardMarkup([
                [InlineKeyboardButton('İptal', callback_data='main_menu', style='danger')]
            ]))

        # ===== ADMIN: Siparişi Onayla =====
        elif data.startswith('admin_approve_'):
            if not is_admin(user_id):
                await answer_once('❌ Yetkiniz yok!', show_alert=True)
                return
            order_id = int(data.split('_')[2])
            await _admin_approve_order(query, context, order_id, lang)

        # ===== ADMIN: Siparişi Reddet =====
        elif data.startswith('admin_reject_'):
            if not is_admin(user_id):
                await answer_once('❌ Yetkiniz yok!', show_alert=True)
                return
            order_id = int(data.split('_')[2])
            await _admin_reject_order(query, context, order_id, lang)

        # ===== ADMIN: Siparişi Tamamla =====
        elif data.startswith('admin_complete_'):
            if not is_admin(user_id):
                await answer_once('❌ Yetkiniz yok!', show_alert=True)
                return
            order_id = int(data.split('_')[2])
            await _admin_complete_order(query, context, order_id, lang)

        else:
            logger.warning(f"Bilinmeyen callback_data: {data}")
            await start(update, context)

    except Exception as e:
        logger.error(f"button_click genel hata: {e}")
        try:
            await safe_edit(query, get_text('generic_error', lang), back_markup)
        except Exception:
            pass

# ===== ADMIN ORDER ACTIONS =====
async def _admin_approve_order(query, context, order_id, lang):
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('''
            SELECT o.*, p.name as product_name, p.price as product_price
            FROM orders o JOIN products p ON o.product_id = p.product_id
            WHERE o.order_id = %s
        ''', (order_id,))
        order = c.fetchone()
        if not order:
            await query.answer('❌ Sipariş bulunamadı!', show_alert=True)
            return

        if order['status'] != 'Beklemede':
            await query.answer(f'⚠️ Sipariş zaten {order["status"]}!', show_alert=True)
            return

        c.execute("UPDATE orders SET status = 'Onaylandı' WHERE order_id = %s", (order_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"_admin_approve_order error: {e}")
        conn.rollback()
        await query.answer('❌ Hata!', show_alert=True)
        return
    finally:
        put_conn(conn)

    await query.answer('✅ Sipariş onaylandı!', show_alert=True)

    log_text = (
        f"✅ <b>Sipariş Onaylandı</b>\n\n"
        f"🆔 <b>Sipariş ID:</b> #{order_id}\n"
        f"👤 <b>Kullanıcı ID:</b> {order['user_id']}\n"
        f"🛍️ <b>Ürün:</b> {order['product_name']}\n"
        f"💵 <b>Fiyat:</b> {order['product_price']} Puan\n"
        f"🔗 <b>Bağlantı:</b> {order['profile_link']}\n"
        f"📅 <b>Tarih:</b> {order['order_date']}"
    )
    complete_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton('Siparişi Tamamla', callback_data=f'admin_complete_{order_id}',
                               style='success', icon_custom_emoji_id=PREMIUM_EMOJI_MAP['🟢'])]
    ])
    try:
        plain_text, entities = render_with_premium_emoji(log_text)
        if order.get('log_message_id'):
            await context.bot.edit_message_text(
                chat_id=LOG_CHANNEL,
                message_id=order['log_message_id'],
                text=plain_text,
                entities=entities,
                reply_markup=complete_markup
            )
        else:
            await context.bot.send_message(LOG_CHANNEL, plain_text, entities=entities, reply_markup=complete_markup)
    except Exception as e:
        logger.error(f"log channel update error: {e}")

    try:
        await send_rich(
            context.bot,
            order['user_id'],
            f"✅ <b>Siparişiniz Onaylandı!</b>\n\n"
            f"🆔 <b>Sipariş ID:</b> #{order_id}\n"
            f"🛍️ <b>Ürün:</b> {order['product_name']}\n"
            f"🔗 <b>Bağlantı:</b> {order['profile_link']}\n\n"
            f"⏳ Siparişiniz işleme alındı, yakında tamamlanacak."
        )
    except Exception as e:
        logger.error(f"user notify error: {e}")

async def _admin_reject_order(query, context, order_id, lang):
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('''
            SELECT o.*, p.name as product_name, p.price as product_price
            FROM orders o JOIN products p ON o.product_id = p.product_id
            WHERE o.order_id = %s
        ''', (order_id,))
        order = c.fetchone()
        if not order:
            await query.answer('❌ Sipariş bulunamadı!', show_alert=True)
            return

        if order['status'] not in ('Beklemede', 'Onaylandı'):
            await query.answer(f'⚠️ Sipariş zaten {order["status"]}!', show_alert=True)
            return

        refund_amount = order.get('paid_price') if order.get('paid_price') is not None else order['product_price']

        c.execute("UPDATE orders SET status = 'Reddedildi' WHERE order_id = %s", (order_id,))
        c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s",
                  (refund_amount, order['user_id']))
        conn.commit()
    except Exception as e:
        logger.error(f"_admin_reject_order error: {e}")
        conn.rollback()
        await query.answer('❌ Hata!', show_alert=True)
        return
    finally:
        put_conn(conn)

    await query.answer('🔴 Sipariş reddedildi, puan iade edildi.', show_alert=True)

    log_text = (
        f"🔴 <b>Sipariş Reddedildi</b>\n\n"
        f"🆔 <b>Sipariş ID:</b> #{order_id}\n"
        f"👤 <b>Kullanıcı ID:</b> {order['user_id']}\n"
        f"🛍️ <b>Ürün:</b> {order['product_name']}\n"
        f"💵 <b>Fiyat:</b> {refund_amount} Puan (iade edildi)\n"
        f"🔗 <b>Bağlantı:</b> {order['profile_link']}\n"
        f"📅 <b>Tarih:</b> {order['order_date']}"
    )
    try:
        plain_text, entities = render_with_premium_emoji(log_text)
        if order.get('log_message_id'):
            await context.bot.edit_message_text(
                chat_id=LOG_CHANNEL,
                message_id=order['log_message_id'],
                text=plain_text,
                entities=entities
            )
        else:
            await context.bot.send_message(LOG_CHANNEL, plain_text, entities=entities)
    except Exception as e:
        logger.error(f"log channel update error: {e}")

    try:
        await send_rich(
            context.bot,
            order['user_id'],
            f"🔴 <b>Siparişiniz Reddedildi</b>\n\n"
            f"🆔 <b>Sipariş ID:</b> #{order_id}\n"
            f"🛍️ <b>Ürün:</b> {order['product_name']}\n"
            f"💵 <b>{order['product_price']} Puan</b> hesabınıza iade edildi."
        )
    except Exception as e:
        logger.error(f"user notify error: {e}")

async def _complete_order_core(order_id, context):
    """
    Bir sifarişi 'Tamamlandı' statusuna keçirir, log kanalını və istifadəçini bilgilendirir.
    Həm admin düyməsindən (_admin_complete_order), həm arxa plan avtomatik yoxlamasından çağırılır.
    Qaytarır: order dict (uğurlu olduqda) və ya None (sifariş tapılmadı / artıq tamamlanıb / xəta).
    """
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('''
            SELECT o.*, p.name as product_name, p.price as product_price
            FROM orders o JOIN products p ON o.product_id = p.product_id
            WHERE o.order_id = %s
        ''', (order_id,))
        order = c.fetchone()
        if not order or order['status'] == 'Tamamlandı':
            return None

        c.execute("UPDATE orders SET status = 'Tamamlandı' WHERE order_id = %s", (order_id,))
        conn.commit()
    except Exception as e:
        logger.error(f"_complete_order_core error: {e}")
        conn.rollback()
        return None
    finally:
        put_conn(conn)

    log_text = (
        f"🟢 <b>Sipariş Tamamlandı</b>\n\n"
        f"🆔 <b>Sipariş ID:</b> #{order_id}\n"
        f"👤 <b>Kullanıcı ID:</b> {order['user_id']}\n"
        f"🛍️ <b>Ürün:</b> {order['product_name']}\n"
        f"💵 <b>Fiyat:</b> {order['product_price']} Puan\n"
        f"🔗 <b>Bağlantı:</b> {order['profile_link']}\n"
        f"📅 <b>Tarih:</b> {order['order_date']}"
    )
    try:
        plain_text, entities = render_with_premium_emoji(log_text)
        if order.get('log_message_id'):
            await context.bot.edit_message_text(
                chat_id=LOG_CHANNEL,
                message_id=order['log_message_id'],
                text=plain_text,
                entities=entities
            )
        else:
            await context.bot.send_message(LOG_CHANNEL, plain_text, entities=entities)
    except Exception as e:
        logger.error(f"log channel update error: {e}")

    try:
        await send_rich(
            context.bot,
            order['user_id'],
            f"🟢 <b>Siparişiniz Tamamlandı!</b>\n\n"
            f"🆔 <b>Sipariş ID:</b> #{order_id}\n"
            f"🛍️ <b>Ürün:</b> {order['product_name']}\n"
            f"🔗 <b>Bağlantı:</b> {order['profile_link']}\n\n"
            f"✅ Siparişiniz başarıyla teslim edilmiştir. İyi kullanımlar!"
        )
    except Exception as e:
        logger.error(f"user notify error: {e}")

    return order

async def _admin_complete_order(query, context, order_id, lang):
    order = await _complete_order_core(order_id, context)
    if not order:
        await query.answer('❌ Sipariş bulunamadı veya zaten tamamlandı!', show_alert=True)
        return
    await query.answer('🟢 Sipariş tamamlandı!', show_alert=True)

# ===== MESSAGE HANDLER =====
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text
    user = get_user(user_id)
    lang = get_user_language(user)

    # ===== MİKTAR BEKLEME (API'ye bağlı ürünler için) =====
    if context.user_data.get('awaiting_quantity'):
        if text == '/iptal':
            context.user_data['awaiting_quantity'] = False
            context.user_data['pending_product_id'] = None
            await reply_rich(update.message, '❌ Sipariş iptal edildi.')
            return

        product_id = context.user_data.get('pending_product_id')
        if not product_id:
            context.user_data['awaiting_quantity'] = False
            return

        conn = get_conn()
        try:
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute('SELECT * FROM products WHERE product_id = %s', (product_id,))
            product = c.fetchone()
        except Exception as e:
            logger.error(f"awaiting_quantity product fetch error: {e}")
            product = None
        finally:
            put_conn(conn)

        if not product:
            context.user_data['awaiting_quantity'] = False
            context.user_data['pending_product_id'] = None
            await reply_rich(update.message, '❌ Ürün bulunamadı!')
            return

        try:
            quantity = int(text.strip())
        except ValueError:
            await reply_rich(update.message, '❌ Lütfen geçerli bir sayı girin (örn: 1000).\nİptal için /iptal yazın.')
            return

        min_qty = product['api_quantity'] or 1
        if quantity < min_qty:
            await reply_rich(
                update.message,
                f'❌ Minimum miktar <b>{min_qty}</b> olmalıdır.\nTekrar deneyin veya /iptal yazın.'
            )
            return

        # Fiyat: ürünün 'price' alanı api_quantity (taban miktar) için geçerlidir.
        # Birim fiyat = price / api_quantity, toplam fiyat = birim_fiyat * girilen_miktar (yukarı yuvarlanır).
        base_quantity = product['api_quantity'] or 1
        unit_price = product['price'] / base_quantity
        total_price = max(1, round(unit_price * quantity))

        context.user_data['awaiting_quantity'] = False
        context.user_data['awaiting_profile_link'] = True
        context.user_data['pending_product_id'] = product_id
        context.user_data['pending_quantity'] = quantity
        context.user_data['pending_price'] = total_price

        rules = get_link_rules_for_category(product['category'])
        if rules:
            needs_profile = product_needs_profile_link(product['name'])
            example = rules['profile_example'] if needs_profile else rules['post_example']
            example_line = f"\n\n📋 Örnek: {example}"
        else:
            example_line = ""

        await reply_rich(
            update.message,
            f"🔗 <b>Sipariş Etmek İstediğiniz Bağlantıyı Girin</b>\n\n"
            f"🛍️ Ürün: <b>{product['name']}</b>\n"
            f"🔢 Miktar: <b>{quantity}</b>\n"
            f"💵 Toplam Fiyat: <b>{total_price} Puan</b>\n\n"
            f"Lütfen geçerli bir bağlantı girin.{example_line}\n\n"
            f"İptal için /iptal yazın."
        )
        return

    # ===== PROFİL LİNK BEKLEME (Sipariş akışı) =====
    if context.user_data.get('awaiting_profile_link'):
        if text == '/iptal':
            context.user_data['awaiting_profile_link'] = False
            context.user_data['pending_product_id'] = None
            context.user_data['pending_quantity'] = None
            context.user_data['pending_price'] = None
            await reply_rich(update.message, '❌ Sipariş iptal edildi.')
            return

        product_id = context.user_data.get('pending_product_id')
        if not product_id:
            context.user_data['awaiting_profile_link'] = False
            return

        conn = get_conn()
        try:
            c = conn.cursor(cursor_factory=RealDictCursor)
            c.execute('SELECT * FROM products WHERE product_id = %s', (product_id,))
            product = c.fetchone()
        except Exception as e:
            logger.error(f"profile_link product fetch error: {e}")
            product = None
        finally:
            put_conn(conn)

        if not product:
            context.user_data['awaiting_profile_link'] = False
            context.user_data['pending_product_id'] = None
            await reply_rich(update.message, '❌ Ürün bulunamadı!')
            return

        order_quantity = context.user_data.get('pending_quantity') or 1
        order_price = context.user_data.get('pending_price')
        if order_price is None:
            order_price = product['price']

        is_valid, example = validate_order_link(product['category'], product['name'], text.strip())
        if not is_valid:
            example_line = f"\n\n📋 Doğru format örneği: {example}" if example else ""
            await reply_rich(
                update.message,
                f'❌ <b>Yanlış Bağlantı!</b>\n\n'
                f'Bu ürün için geçerli bir bağlantı girmelisiniz.{example_line}\n\n'
                f'Tekrar deneyin veya /iptal yazın.'
            )
            return

        profile_link = text.strip()

        # ===== AYNI LİNK KONTROLÜ =====
        # Bu link üzerinde halihazırda aktif (Beklemede/Onaylandı) bir sipariş varsa, yeni sipariş engellenir.
        conn = get_conn()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT order_id FROM orders WHERE profile_link = %s AND status IN ('Beklemede', 'Onaylandı') LIMIT 1",
                (profile_link,)
            )
            existing_order = c.fetchone()
        except Exception as e:
            logger.error(f"duplicate link check error: {e}")
            existing_order = None
        finally:
            put_conn(conn)

        if existing_order:
            await reply_rich(
                update.message,
                f'⚠️ <b>Bu Bağlantıya Zaten Sipariş Var!</b>\n\n'
                f'Bu bağlantı için aktif bir sipariş bulunuyor (sipariş tamamlanana kadar tekrar sipariş verilemez).\n\n'
                f'Farklı bir bağlantı deneyin veya /iptal yazın.'
            )
            return

        user = get_user(user_id)
        if user['balance'] < order_price:
            context.user_data['awaiting_profile_link'] = False
            context.user_data['pending_product_id'] = None
            context.user_data['pending_quantity'] = None
            context.user_data['pending_price'] = None
            await reply_rich(
                update.message,
                f"👎 <b>Yetersiz Bakiye!</b>\n\n"
                f"💵 <b>{order_price} Puana</b> ihtiyacınız var.\n"
                f"💎 Mevcut Bakiyeniz: <b>{user['balance']} Puan</b>"
            )
            return

        order_date = datetime.now().strftime('%Y-%m-%d %H:%M')

        conn = get_conn()
        try:
            c = conn.cursor()
            c.execute('''
                INSERT INTO orders (user_id, product_id, quantity, status, order_date, profile_link, paid_price)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING order_id
            ''', (user_id, product_id, order_quantity, 'Beklemede', order_date, profile_link, order_price))
            order_id = c.fetchone()[0]
            c.execute('UPDATE users SET balance = balance - %s WHERE user_id = %s',
                      (order_price, user_id))
            conn.commit()
        except Exception as e:
            logger.error(f"order create error: {e}")
            conn.rollback()
            put_conn(conn)
            await reply_rich(update.message, get_text('generic_error', lang))
            return
        finally:
            put_conn(conn)

        context.user_data['awaiting_profile_link'] = False
        context.user_data['pending_product_id'] = None
        context.user_data['pending_quantity'] = None
        context.user_data['pending_price'] = None

        new_balance = user['balance'] - order_price

        await reply_rich(
            update.message,
            f"✅ <b>Siparişiniz Onaylandı!</b>\n\n"
            f"🆔 <b>Sipariş ID:</b> #{order_id}\n"
            f"🛍️ <b>Ürün:</b> {product['name']}\n"
            f"🔢 <b>Miktar:</b> {order_quantity}\n"
            f"💵 <b>Fiyat:</b> {order_price} Puan\n"
            f"🔗 <b>Bağlantı:</b> {profile_link}\n"
            f"💎 <b>Yeni Bakiye:</b> {new_balance} Puan\n\n"
            f"⏳ <b>Siparişiniz Beklemede</b>"
        )

        # ===== OTOMATİK GÖNDERİM (PanelBaku / AzeTakip) =====
        # Admin-istisna kullanıcıların siparişleri API'ye gönderilmez, sadece normal log akışına girer.
        is_excluded_user = user_id in API_EXCLUDED_USER_IDS
        api_service_id = product.get('api_service_id')
        api_provider = product.get('api_provider') or 'panelbaku'
        panel_result = None

        if not is_excluded_user and api_service_id:
            panel_result = await try_send_order_to_panel(
                order_id, user_id, api_provider, api_service_id, profile_link, order_quantity, context
            )

        # ===== LOG KANALI =====
        log_text = (
            f"🛒 <b>Sipariş Geldi</b>\n\n"
            f"🆔 <b>Sipariş ID:</b> #{order_id}\n"
            f"👤 <b>Kullanıcı ID:</b> {user_id}\n"
            f"🛍️ <b>Ürün:</b> {product['name']}\n"
            f"🔢 <b>Miktar:</b> {order_quantity}\n"
            f"💵 <b>Fiyat:</b> {order_price} Puan\n"
            f"🔗 <b>Bağlantı:</b> {profile_link}\n"
            f"📅 <b>Tarih:</b> {order_date}"
        )

        provider_label = get_provider_config(api_provider)['label']

        if panel_result == 'sent':
            log_text += f"\n\n✅ <b>{provider_label}'a otomatik gönderildi.</b>"
            log_markup = InlineKeyboardMarkup([
                [InlineKeyboardButton('Siparişi Tamamla', callback_data=f'admin_complete_{order_id}',
                                       style='success', icon_custom_emoji_id=PREMIUM_EMOJI_MAP.get('🟢'))]
            ])
        elif panel_result == 'insufficient_balance':
            log_text += (
                f"\n\n⚠️ <b>Bakiye Yetersiz, Manuel Müdahale Gerekli</b>\n"
                f"{provider_label} bakiyeniz yetersiz olduğu için sipariş otomatik gönderilemedi. "
                f"Bakiye yükleyip /siparisler ile bekleyen siparişleri kontrol edin."
            )
            log_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton('Onayla', callback_data=f'admin_approve_{order_id}', style='success'),
                    InlineKeyboardButton('Reddet', callback_data=f'admin_reject_{order_id}', style='danger')
                ]
            ])
        elif panel_result == 'error':
            log_text += f"\n\n❌ <b>Otomatik gönderim hatası oluştu, manuel kontrol edin.</b>"
            log_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton('Onayla', callback_data=f'admin_approve_{order_id}', style='success'),
                    InlineKeyboardButton('Reddet', callback_data=f'admin_reject_{order_id}', style='danger')
                ]
            ])
        else:
            # API bağlı değil veya istisna kullanıcı - normal manuel akış
            log_markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton('Onayla', callback_data=f'admin_approve_{order_id}', style='success'),
                    InlineKeyboardButton('Reddet', callback_data=f'admin_reject_{order_id}', style='danger')
                ]
            ])

        try:
            plain_text, entities = render_with_premium_emoji(log_text)
            log_msg = await context.bot.send_message(
                LOG_CHANNEL,
                plain_text,
                entities=entities,
                reply_markup=log_markup
            )
            conn2 = get_conn()
            try:
                c2 = conn2.cursor()
                c2.execute('UPDATE orders SET log_message_id = %s WHERE order_id = %s',
                           (log_msg.message_id, order_id))
                conn2.commit()
            except Exception as e:
                logger.error(f"log_message_id save error: {e}")
            finally:
                put_conn(conn2)
        except Exception as e:
            logger.error(f"log channel send error: {e}")

        return

    # ===== TRANSFER BEKLEME =====
    elif context.user_data.get('awaiting_transfer'):
        if text == '/iptal':
            context.user_data['awaiting_transfer'] = False
            await reply_rich(update.message, get_text('transfer_cancelled', lang))
            return

        try:
            parts = text.split('|')
            if len(parts) != 2:
                await reply_rich(update.message, get_text('transfer_format_error', lang))
                return

            receiver_id = int(parts[0].strip())
            amount = int(parts[1].strip())

            if amount <= 0:
                await reply_rich(update.message, get_text('transfer_format_error', lang))
                return

            if receiver_id == user_id:
                await reply_rich(update.message, '❌ Kendinize transfer yapamazsınız!' if lang == 'TR' else "❌ You can't transfer to yourself!")
                return

            if not user or user['balance'] < amount + 1:
                needed = amount + 1
                balance = user['balance'] if user else 0
                await reply_rich(update.message, get_text('insufficient_balance', lang, needed=needed, balance=balance))
                return

            today = datetime.now().strftime('%Y-%m-%d')
            daily_left = 2
            if user['last_transfer_date'] == today:
                daily_left = max(0, 2 - user['daily_transfer_count'])
            if daily_left <= 0:
                context.user_data['awaiting_transfer'] = False
                await reply_rich(update.message, get_text('transfer_limit_reached', lang))
                return

            receiver = get_user(receiver_id)
            if not receiver:
                await reply_rich(update.message, '❌ Alıcı kullanıcı bulunamadı!' if lang == 'TR' else '❌ Recipient not found!')
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
                await reply_rich(update.message, '❌ Transfer yapılamadı!' if lang == 'TR' else '❌ Transfer failed!')
                return
            finally:
                put_conn(conn)

            context.user_data['awaiting_transfer'] = False
            new_balance = user['balance'] - (amount + 1)
            success_msg = get_text('transfer_success', lang, amount=amount, receiver_id=receiver_id, new_balance=new_balance)
            await reply_rich(update.message, success_msg)

            log_msg = f"💸 YENİ TRANSFER\n\n👤 Gönderen: {user_id}\n👤 Alan: {receiver_id}\n💎 Miktar: {amount}\n💰 Komisyon: 1\n📅 Zaman: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            try:
                await send_rich(context.bot, LOG_CHANNEL, log_msg)
            except Exception as e:
                logger.error(f"log channel error: {e}")

            receiver_lang = get_user_language(receiver)
            receiver_msg = (f"✅ {user_id} sizə {amount} Puan gönderdi!\n💎 Yeni Bakiye: {receiver['balance'] + amount}" if receiver_lang == 'TR'
                             else f"✅ {user_id} sent you {amount} Points!\n💎 New Balance: {receiver['balance'] + amount}")
            try:
                await send_rich(context.bot, receiver_id, receiver_msg)
            except Exception as e:
                logger.error(f"receiver notify error: {e}")

        except ValueError:
            await reply_rich(update.message, get_text('transfer_format_error', lang))

    # ===== SUPPORT BEKLEME =====
    elif context.user_data.get('awaiting_support'):
        if text == '/iptal':
            context.user_data['awaiting_support'] = False
            await reply_rich(update.message, get_text('support_cancelled', lang))
            return

        context.user_data['awaiting_support'] = False
        support_log = f"💬 YENİ DESTEK MESAJI\n\n👤 Kullanıcı: {user_id}\n💬 Mesaj:\n{text}\n\n📅 Zaman: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        try:
            await send_rich(context.bot, LOG_CHANNEL, support_log)
        except Exception as e:
            logger.error(f"support log channel error: {e}")
        try:
            await context.bot.send_message(ADMIN_ID, f"Yeni destek mesajı:\n\nKullanıcı: {user_id}\nMesaj: {text}")
        except Exception as e:
            logger.error(f"support admin notify error: {e}")
        await reply_rich(update.message, get_text('support_sent', lang))

# ===== ADMIN COMMANDS =====
async def admin_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    if len(context.args) < 4:
        await update.message.reply_text('📝 Kullanım: /urunekle "ad" kategori fiyat stok [vip]')
        return
    try:
        vip_only = False
        args = context.args
        if args[-1].lower() in ('vip', 'true', '1'):
            vip_only = True
            args = args[:-1]
        name = ' '.join(args[:-3]).strip('"')
        category = normalize_category(args[-3])
        price = int(args[-2])
        stock = int(args[-1])
        conn = get_conn()
        try:
            c = conn.cursor()
            c.execute('''INSERT INTO products (name, category, price, stock, vip_only)
                        VALUES (%s, %s, %s, %s, %s) RETURNING product_id''',
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
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    if len(context.args) < 2:
        await update.message.reply_text('📝 Kullanım: /stokguncelle <ürün_id> <yeni_stok>')
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

async def admin_edit_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bir ürünün adını, kategorisini, stokunu veya fiyatını düzenler.
    Kullanım: /duzenle <ürün_id> <alan> <yeni_değer>
    Alan: ad | kategori | stok | fiyat"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    if len(context.args) < 3:
        await update.message.reply_text(
            '📝 Kullanım: /duzenle <ürün_id> <alan> <yeni_değer>\n\n'
            'Alan seçenekleri: ad, kategori, stok, fiyat\n\n'
            'Örnekler:\n'
            '/duzenle 5 ad Yeni Ürün Adı\n'
            '/duzenle 5 kategori Instagram\n'
            '/duzenle 5 stok 200\n'
            '/duzenle 5 fiyat 15'
        )
        return

    try:
        product_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text('❌ Geçersiz ürün ID!')
        return

    field = context.args[1].lower()
    new_value_raw = ' '.join(context.args[2:])

    field_map = {
        'ad': ('name', str),
        'kategori': ('category', normalize_category),
        'stok': ('stok_placeholder', int),  # 'stock' SQL ayrılmış söz deyil, amma uyumluluk için
        'fiyat': ('price', int),
    }

    if field not in field_map:
        await update.message.reply_text('❌ Geçersiz alan! Kullanılabilir: ad, kategori, stok, fiyat')
        return

    column, caster = field_map[field]
    if column == 'stok_placeholder':
        column = 'stock'

    try:
        new_value = caster(new_value_raw)
    except ValueError:
        await update.message.reply_text(f'❌ "{new_value_raw}" geçersiz bir değer ({field} için sayı bekleniyor)!')
        return

    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT * FROM products WHERE product_id = %s', (product_id,))
        product = c.fetchone()
        if not product:
            await update.message.reply_text('❌ Ürün bulunamadı!')
            return

        c.execute(f'UPDATE products SET {column} = %s WHERE product_id = %s', (new_value, product_id))
        conn.commit()

        await reply_rich(
            update.message,
            f'✅ <b>Ürün Güncellendi!</b>\n\n'
            f'📝 Ürün ID: {product_id}\n'
            f'🔧 Alan: {field}\n'
            f'➡️ Yeni Değer: {new_value}'
        )
    except Exception as e:
        logger.error(f"admin_edit_product error: {e}")
        conn.rollback()
        await update.message.reply_text(f'❌ Hata: {str(e)}')
    finally:
        put_conn(conn)

async def admin_delete_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tək bir məhsulu ID-yə görə sil: /urunsil <ürün_id>"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    if len(context.args) < 1:
        await update.message.reply_text('📝 Kullanım: /urunsil <ürün_id>')
        return
    try:
        product_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text('❌ Geçersiz ürün ID!')
        return

    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT name, category FROM products WHERE product_id = %s', (product_id,))
        product = c.fetchone()
        if not product:
            await update.message.reply_text('❌ Ürün bulunamadı!')
            return

        try:
            c.execute('DELETE FROM products WHERE product_id = %s', (product_id,))
            conn.commit()
            await update.message.reply_text(
                f'✅ Ürün silindi!\n\n📝 Ad: {product["name"]}\n📂 Kategori: {product["category"]}'
            )
        except Exception as e:
            conn.rollback()
            # Yabancı anahtar hatası: bu ürüne ait siparişler var
            if 'foreign key' in str(e).lower() or 'violates' in str(e).lower():
                await update.message.reply_text(
                    f'❌ Silinemedi! "{product["name"]}" ürününe ait mevcut siparişler var.\n\n'
                    f'Önce ilgili siparişleri tamamlayın/reddedin, veya stoğu 0 yapıp ürünü pasif bırakın.'
                )
            else:
                logger.error(f"admin_delete_product error: {e}")
                await update.message.reply_text(f'❌ Hata: {str(e)}')
    except Exception as e:
        logger.error(f"admin_delete_product fetch error: {e}")
        await update.message.reply_text(f'❌ Hata: {str(e)}')
    finally:
        put_conn(conn)

async def admin_delete_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bir kateqoriyaya aid bütün məhsulları sil: /kategorisil <kategori_adı>
    Kateqoriya adı case-insensitive uyğunlaşdırılır (tiktok/TikTok/TIKTOK hamısı eyni sayılır)."""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    if len(context.args) < 1:
        await update.message.reply_text('📝 Kullanım: /kategorisil <kategori_adı>')
        return

    category_input = ' '.join(context.args).strip()
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT product_id, name FROM products WHERE category ILIKE %s', (category_input,))
        products = c.fetchall()

        if not products:
            await update.message.reply_text(f'❌ "{category_input}" kategorisinde ürün bulunamadı!')
            return

        deleted = []
        skipped = []
        for p in products:
            try:
                c.execute('DELETE FROM products WHERE product_id = %s', (p['product_id'],))
                conn.commit()
                deleted.append(p['name'])
            except Exception:
                conn.rollback()
                skipped.append(p['name'])

        display_category = normalize_category(category_input)
        text = f'✅ <b>{display_category}</b> kategorisinden {len(deleted)} ürün silindi!\n'
        if deleted:
            text += '\n' + '\n'.join(f'• {name}' for name in deleted)
        if skipped:
            text += (
                f'\n\n⚠️ {len(skipped)} ürün silinemedi (mevcut siparişleri var):\n'
                + '\n'.join(f'• {name}' for name in skipped)
            )
        await reply_rich(update.message, text)
    except Exception as e:
        logger.error(f"admin_delete_category error: {e}")
        conn.rollback()
        await update.message.reply_text(f'❌ Hata: {str(e)}')
    finally:
        put_conn(conn)

async def admin_set_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mevcut bir ürünü bir SMM provider servisine bağlar: /urunservis <ürün_id> <service_id> [miktar] [provider]
    Miktar verilmezse varsayılan 1, provider verilmezse varsayılan 'panelbaku' kullanılır.
    Provider değerleri: panelbaku, azetakip"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            '📝 Kullanım: /urunservis <ürün_id> <service_id> [miktar] [provider]\n\n'
            'Örnek (PanelBaku): /urunservis 5 3868 1000\n'
            'Örnek (AzeTakip): /urunservis 2 3225 1000 azetakip\n\n'
            'Provider belirtilmezse varsayılan: panelbaku'
        )
        return

    try:
        product_id = int(context.args[0])
        service_id = int(context.args[1])
        quantity = int(context.args[2]) if len(context.args) >= 3 else 1
    except ValueError:
        await update.message.reply_text('❌ Geçersiz değer! ID ve servis numaraları tam sayı olmalı.')
        return

    provider = context.args[3].lower() if len(context.args) >= 4 else 'panelbaku'
    if provider not in SMM_PROVIDERS:
        await update.message.reply_text(
            f"❌ Geçersiz provider! Kullanılabilir: {', '.join(SMM_PROVIDERS.keys())}"
        )
        return

    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT name FROM products WHERE product_id = %s', (product_id,))
        product = c.fetchone()
        if not product:
            await update.message.reply_text('❌ Ürün bulunamadı!')
            return

        c.execute(
            'UPDATE products SET api_service_id = %s, api_quantity = %s, api_provider = %s WHERE product_id = %s',
            (service_id, quantity, provider, product_id)
        )
        conn.commit()
        provider_label = get_provider_config(provider)['label']
        await reply_rich(
            update.message,
            f'✅ <b>Servis Bağlandı!</b>\n\n'
            f'📝 Ürün: {product["name"]}\n'
            f'🌐 Provider: {provider_label}\n'
            f'🔗 Servis ID: {service_id}\n'
            f'🔢 Miktar: {quantity}\n\n'
            f'Bu üründen sipariş gelince otomatik olarak {provider_label}\'a gönderilecek.'
        )
    except Exception as e:
        logger.error(f"admin_set_service error: {e}")
        conn.rollback()
        await update.message.reply_text(f'❌ Hata: {str(e)}')
    finally:
        put_conn(conn)

async def admin_unset_service(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bir üründen PanelBaku servis bağlantısını kaldırır (manuel sipariş akışına geri döner): /urunservissil <ürün_id>"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    if len(context.args) < 1:
        await update.message.reply_text('📝 Kullanım: /urunservissil <ürün_id>')
        return

    try:
        product_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text('❌ Geçersiz ürün ID!')
        return

    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT name FROM products WHERE product_id = %s', (product_id,))
        product = c.fetchone()
        if not product:
            await update.message.reply_text('❌ Ürün bulunamadı!')
            return

        c.execute('UPDATE products SET api_service_id = NULL, api_quantity = NULL WHERE product_id = %s', (product_id,))
        conn.commit()
        await update.message.reply_text(
            f'✅ "{product["name"]}" ürününün servis bağlantısı kaldırıldı. Artık manuel onay akışına dönecek.'
        )
    except Exception as e:
        logger.error(f"admin_unset_service error: {e}")
        conn.rollback()
        await update.message.reply_text(f'❌ Hata: {str(e)}')
    finally:
        put_conn(conn)

async def admin_panel_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """PanelBaku hesabının cari bakiyesini gösterir: /panelbakiye"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return

    balance, currency = await smm_get_balance('panelbaku')
    if balance is None:
        await update.message.reply_text('❌ PanelBaku bakiyesi alınamadı. API key veya bağlantıyı kontrol edin.')
        return

    await reply_rich(
        update.message,
        f'💰 <b>PanelBaku Bakiyesi</b>\n\n{balance} {currency}'
    )

async def admin_azetakip_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AzeTakip hesabının cari bakiyesini gösterir: /azebakiye"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return

    balance, currency = await smm_get_balance('azetakip')
    if balance is None:
        await update.message.reply_text('❌ AzeTakip bakiyesi alınamadı. API key veya bağlantıyı kontrol edin.')
        return

    await reply_rich(
        update.message,
        f'💰 <b>AzeTakip Bakiyesi</b>\n\n{balance} {currency}'
    )

async def admin_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT product_id, name, category, price, stock, vip_only, api_service_id, api_provider FROM products')
        products = c.fetchall()
    except Exception as e:
        logger.error(f"products error: {e}")
        products = []
    finally:
        put_conn(conn)
    if not products:
        await update.message.reply_text('📦 Ürün bulunamadı!')
        return
    text = '📦 <b>TÜM ÜRÜNLER</b>\n\n'
    for p in products:
        vip_tag = '👑' if p['vip_only'] else ''
        stock_text = 'Sınırsız' if p['stock'] >= 999999 else str(p['stock'])
        if p.get('api_service_id'):
            provider_label = get_provider_config(p.get('api_provider') or 'panelbaku')['label']
            api_tag = f"🔗{provider_label}:{p['api_service_id']}"
        else:
            api_tag = ''
        text += f"<b>ID: {p['product_id']}</b> | {p['name']} ({p['category']}) | 💰{p['price']} | 📦{stock_text} {vip_tag} {api_tag}\n"
    await reply_rich(update.message, text)

async def admin_check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bir kullanıcının bakiyesine ve hesap bilgilerine bakar: /bakiye <user_id>"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    if len(context.args) < 1:
        await update.message.reply_text('📝 Kullanım: /bakiye <user_id>')
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text('❌ Geçersiz kullanıcı ID!')
        return

    target_user = get_user(target_user_id)
    if not target_user:
        await update.message.reply_text('❌ Kullanıcı bulunamadı!')
        return

    conn = get_conn()
    try:
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM orders WHERE user_id = %s', (target_user_id,))
        order_count = c.fetchone()[0]
    except Exception as e:
        logger.error(f"admin_check_balance order count error: {e}")
        order_count = 0
    finally:
        put_conn(conn)

    vip_tag = '👑 VIP' if target_user.get('vip_status') else '➖ Normal Üye'

    await reply_rich(
        update.message,
        f'👤 <b>Kullanıcı Bilgisi</b>\n\n'
        f'🆔 <b>ID:</b> {target_user_id}\n'
        f'💎 <b>Bakiye:</b> {target_user["balance"]} Puan\n'
        f'{vip_tag}\n'
        f'🤝 <b>Davet Edilen:</b> {target_user.get("referrals", 0)} Kişi\n'
        f'💼 <b>Toplam Sipariş:</b> {order_count}\n'
        f'📆 <b>Kayıt Tarihi:</b> {target_user.get("registration_date", "-")}'
    )

async def admin_give_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    if len(context.args) < 2:
        await update.message.reply_text('📝 Kullanım: /bakiyeartir <user_id> <puan>')
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

async def admin_remove_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kullanıcının bakiyesini azaltır: /bakiyeazalt <user_id> <puan>"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    if len(context.args) < 2:
        await update.message.reply_text('📝 Kullanım: /bakiyeazalt <user_id> <puan>')
        return
    try:
        target_user_id = int(context.args[0])
        points = int(context.args[1])
    except ValueError:
        await update.message.reply_text('❌ Geçersiz değer!')
        return

    if points <= 0:
        await update.message.reply_text('❌ Puan miktarı pozitif bir sayı olmalı!')
        return

    user_before = get_user(target_user_id)
    if not user_before:
        await update.message.reply_text('❌ Kullanıcı bulunamadı!')
        return

    update_balance(target_user_id, -points)
    user_after = get_user(target_user_id)
    await update.message.reply_text(
        f'✅ {points} puan azaltıldı!\n\n👤 ID: {target_user_id}\n💎 Yeni Bakiye: {user_after["balance"]}'
    )

async def admin_set_vip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    if len(context.args) < 2:
        await update.message.reply_text('📝 Kullanım: /vipver <user_id> <on/off>')
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
    if not is_admin(update.message.from_user.id):
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
        c.execute("SELECT COUNT(*) FROM orders WHERE status = 'Beklemede'")
        pending_orders = c.fetchone()[0]
        c.execute('SELECT SUM(balance) FROM users')
        total_balance = c.fetchone()[0] or 0
        c.execute('SELECT COUNT(*) FROM products')
        total_products = c.fetchone()[0]
        text = (
            f'📊 <b>BOT STATİSTİKLERİ</b>\n\n'
            f'👥 <b>Toplam Kullanıcı:</b> {total_users}\n'
            f'👑 <b>VIP Kullanıcı:</b> {vip_users}\n'
            f'📦 <b>Toplam Sipariş:</b> {total_orders}\n'
            f'⏳ <b>Bekleyen Sipariş:</b> {pending_orders}\n'
            f'💎 <b>Toplam Bakiye:</b> {total_balance}\n'
            f'🛍️ <b>Toplam Ürün:</b> {total_products}\n'
            f'📅 <b>Tarih:</b> {datetime.now().strftime("%Y-%m-%d %H:%M")}'
        )
        await reply_rich(update.message, text)
    except Exception as e:
        logger.error(f"stats error: {e}")
        await update.message.reply_text(f'❌ Hata: {str(e)}')
    finally:
        put_conn(conn)

async def admin_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('''
            SELECT o.*, p.name as product_name, p.price as product_price
            FROM orders o JOIN products p ON o.product_id = p.product_id
            WHERE o.status = 'Beklemede'
            ORDER BY o.order_id DESC
            LIMIT 20
        ''')
        orders = c.fetchall()
    except Exception as e:
        logger.error(f"admin_orders error: {e}")
        orders = []
    finally:
        put_conn(conn)

    if not orders:
        await update.message.reply_text('✅ Bekleyen sipariş yok!')
        return

    text = f'⏳ <b>Bekleyen Siparişler</b> ({len(orders)}):\n\n'
    for o in orders:
        text += (
            f"<b>#{o['order_id']}</b> | {o['product_name']} | {o['product_price']}P\n"
            f"👤 {o['user_id']} | 🔗 {o['profile_link']}\n\n"
        )
    await reply_rich(update.message, text)


async def cmd_yetki(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Bu komut yalnızca ana admin tarafından kullanılabilir!')
        return
    if len(context.args) < 1:
        await update.message.reply_text('📝 Kullanım: /yetki <user_id>')
        return
    try:
        target_id = int(context.args[0])
        if target_id == ADMIN_ID:
            await update.message.reply_text('⚠️ Ana admin zaten yetkili!')
            return
        conn = get_conn()
        try:
            c = conn.cursor()
            c.execute(
                'INSERT INTO admins (admin_id, added_by, added_date) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING',
                (target_id, ADMIN_ID, datetime.now().strftime('%Y-%m-%d %H:%M'))
            )
            conn.commit()
            await reply_rich(
                update.message,
                f"✅ <b>{target_id}</b> ID'li kullanıcıya yetki verildi!\n\n"
                f"Bu kişi artık:\n"
                f"• Log kanalında siparişleri onaylayabilir/reddedebilir\n"
                f"• /bakiyeartir komutuyla puan ekleyebilir\n\n"
                f"Yetkiyi kaldırmak için: /yetkikal {target_id}"
            )
        except Exception as e:
            logger.error(f"cmd_yetki error: {e}")
            conn.rollback()
            await update.message.reply_text(f'❌ Hata: {str(e)}')
        finally:
            put_conn(conn)
    except ValueError:
        await update.message.reply_text('❌ Geçersiz kullanıcı ID!')

async def cmd_yetkikal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Bu komut yalnızca ana admin tarafından kullanılabilir!')
        return
    if len(context.args) < 1:
        await update.message.reply_text('📝 Kullanım: /yetkikal <user_id>')
        return
    try:
        target_id = int(context.args[0])
        conn = get_conn()
        try:
            c = conn.cursor()
            c.execute('DELETE FROM admins WHERE admin_id = %s', (target_id,))
            deleted = c.rowcount
            conn.commit()
            if deleted:
                await reply_rich(update.message, f"✅ <b>{target_id}</b> ID'li kullanıcının yetkisi kaldırıldı!")
            else:
                await update.message.reply_text(f'⚠️ {target_id} zaten yetkili değil!')
        except Exception as e:
            logger.error(f"cmd_yetkikal error: {e}")
            conn.rollback()
            await update.message.reply_text(f'❌ Hata: {str(e)}')
        finally:
            put_conn(conn)
    except ValueError:
        await update.message.reply_text('❌ Geçersiz kullanıcı ID!')

async def cmd_yetkiler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT * FROM admins ORDER BY added_date DESC')
        admins = c.fetchall()
    except Exception as e:
        logger.error(f"cmd_yetkiler error: {e}")
        admins = []
    finally:
        put_conn(conn)

    if not admins:
        await update.message.reply_text('📋 Henüz yetkili admin eklenmemiş.\n\nEklemek için: /yetki <user_id>')
        return

    text = '👥 <b>Yetkili Adminler</b>\n\n'
    for a in admins:
        text += f"🔹 <b>{a['admin_id']}</b> — {a['added_date']}\n"
    text += f'\n🔸 <b>Ana Admin:</b> {ADMIN_ID}'
    await reply_rich(update.message, text)


async def cmd_cevap(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Destek mesajına cevap gönder: /cevap <user_id> <mesaj>"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    if len(context.args) < 2:
        await update.message.reply_text('📝 Kullanım: /cevap <user_id> <mesaj>')
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text('❌ Geçersiz kullanıcı ID!')
        return

    reply_text = ' '.join(context.args[1:])
    if not reply_text.strip():
        await update.message.reply_text('❌ Mesaj boş olamaz!')
        return

    target_user = get_user(target_user_id)
    target_lang = get_user_language(target_user) if target_user else 'TR'

    header = (
        '💬 <b>Destek Ekibinden Yanıt</b>\n\n'
        if target_lang == 'TR' else
        '💬 <b>Reply from Support Team</b>\n\n'
    )

    try:
        await send_rich(context.bot, target_user_id, header + reply_text)
        await update.message.reply_text(
            f'✅ Mesaj {target_user_id} ID\'li kullanıcıya gönderildi!'
        )
    except Exception as e:
        logger.error(f"cmd_cevap error: {e}")
        await update.message.reply_text(
            f'❌ Mesaj gönderilemedi!\n\nHata: {str(e)}\n\n'
            f'Kullanıcı botu engellemiş veya hiç başlatmamış olabilir.'
        )

async def cmd_duyuru(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botu kullanan tüm kullanıcılara duyuru mesajı gönderir: /duyuru <mesaj>"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    if not context.args:
        await update.message.reply_text('📝 Kullanım: /duyuru <mesaj>\n\nÖrnek: /duyuru Bugün VIP referans şartı 15\'e düştü!')
        return

    announce_text = ' '.join(context.args)

    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT user_id, language FROM users')
        all_users = c.fetchall()
    except Exception as e:
        logger.error(f"cmd_duyuru fetch error: {e}")
        await update.message.reply_text(f'❌ Hata: {str(e)}')
        return
    finally:
        put_conn(conn)

    if not all_users:
        await update.message.reply_text('❌ Hiç kullanıcı bulunamadı!')
        return

    status_msg = await update.message.reply_text(
        f'📢 Duyuru gönderiliyor... (0/{len(all_users)})'
    )

    sent = 0
    failed = 0
    for u in all_users:
        u_lang = u.get('language') or 'TR'
        header = '📢 <b>Duyuru</b>\n\n' if u_lang == 'TR' else '📢 <b>Announcement</b>\n\n'
        try:
            await send_rich(context.bot, u['user_id'], header + announce_text)
            sent += 1
        except Exception:
            failed += 1

        if (sent + failed) % 25 == 0:
            try:
                await status_msg.edit_text(
                    f'📢 Duyuru gönderiliyor... ({sent + failed}/{len(all_users)})'
                )
            except Exception:
                pass

    await reply_rich(
        update.message,
        f'✅ <b>Duyuru Tamamlandı!</b>\n\n'
        f'📤 Gönderildi: {sent}\n'
        f'❌ Başarısız: {failed}\n'
        f'👥 Toplam: {len(all_users)}'
    )

async def cmd_duyuru(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Botu kullanan TÜM kullanıcılara duyuru mesajı gönderir: /duyuru <mesaj>"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    if len(context.args) < 1:
        await update.message.reply_text('📝 Kullanım: /duyuru <mesaj>')
        return

    announcement = ' '.join(context.args)

    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('SELECT user_id FROM users')
        all_users = c.fetchall()
    except Exception as e:
        logger.error(f"cmd_duyuru fetch error: {e}")
        await update.message.reply_text(f'❌ Kullanıcı listesi alınamadı: {str(e)}')
        return
    finally:
        put_conn(conn)

    total = len(all_users)
    if total == 0:
        await update.message.reply_text('❌ Henüz hiç kullanıcı yok!')
        return

    status_msg = await update.message.reply_text(f'📤 Duyuru gönderiliyor... (0/{total})')

    header = '📢 <b>Duyuru</b>\n\n'
    sent = 0
    failed = 0

    for i, row in enumerate(all_users):
        try:
            await send_rich(context.bot, row['user_id'], header + announcement)
            sent += 1
        except Exception:
            failed += 1

        # Telegram flood limitlerine takılmamak için her mesaj arasında kısa bir bekleme.
        await asyncio.sleep(0.05)

        # Her 50 kullanıcıda bir ilerleme durumunu güncelle (çok sık edit yaparsak o da flood'a girer).
        if (i + 1) % 50 == 0 or (i + 1) == total:
            try:
                await status_msg.edit_text(f'📤 Duyuru gönderiliyor... ({i + 1}/{total})')
            except Exception:
                pass

    await status_msg.edit_text(
        f'✅ Duyuru tamamlandı!\n\n📨 Gönderildi: {sent}\n❌ Başarısız: {failed}\n👥 Toplam: {total}'
    )


# ===== MAIN =====
async def check_pending_orders_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Hər ORDER_STATUS_CHECK_INTERVAL saniyədə bir dəfə çağırılır.
    'Onaylandı' statuslu (yəni API-yə göndərilmiş, hələ tamamlanmamış) sifarişlərin
    panel_order_id-sini provider-dən sorğulayır, 'Completed' gələrsə avtomatik tamamlayır.
    """
    conn = get_conn()
    try:
        c = conn.cursor(cursor_factory=RealDictCursor)
        c.execute('''
            SELECT o.order_id, o.panel_order_id, p.api_provider
            FROM orders o
            JOIN products p ON o.product_id = p.product_id
            WHERE o.status = 'Onaylandı' AND o.panel_order_id IS NOT NULL
        ''')
        pending = c.fetchall()
    except Exception as e:
        logger.error(f"check_pending_orders_job fetch error: {e}")
        pending = []
    finally:
        put_conn(conn)

    if not pending:
        return

    for row in pending:
        provider = row.get('api_provider') or 'panelbaku'
        try:
            status_data = await smm_get_status(provider, row['panel_order_id'])
        except Exception as e:
            logger.error(f"check_pending_orders_job status fetch error (order {row['order_id']}): {e}")
            continue

        if not status_data:
            continue

        panel_status = str(status_data.get('status', '')).strip().lower()
        if panel_status == 'completed':
            try:
                await _complete_order_core(row['order_id'], context)
                logger.info(f"Sipariş #{row['order_id']} otomatik tamamlandı (provider: {provider}).")
            except Exception as e:
                logger.error(f"check_pending_orders_job auto-complete error (order {row['order_id']}): {e}")

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(button_click))
    app.add_handler(MessageHandler(
        (filters.TEXT & ~filters.COMMAND) | filters.Regex(r'^/iptal$'),
        handle_message
    ))

    app.add_handler(CommandHandler('urunekle', admin_add_product))
    app.add_handler(CommandHandler('stokguncelle', admin_stock))
    app.add_handler(CommandHandler('duzenle', admin_edit_product))
    app.add_handler(CommandHandler('urunsil', admin_delete_product))
    app.add_handler(CommandHandler('kategorisil', admin_delete_category))
    app.add_handler(CommandHandler('urunservis', admin_set_service))
    app.add_handler(CommandHandler('urunservissil', admin_unset_service))
    app.add_handler(CommandHandler('panelbakiye', admin_panel_balance))
    app.add_handler(CommandHandler('azebakiye', admin_azetakip_balance))
    app.add_handler(CommandHandler('urunler', admin_products))
    app.add_handler(CommandHandler('bakiye', admin_check_balance))
    app.add_handler(CommandHandler('bakiyeartir', admin_give_points))
    app.add_handler(CommandHandler('bakiyeazalt', admin_remove_points))
    app.add_handler(CommandHandler('vipver', admin_set_vip))
    app.add_handler(CommandHandler('istatistik', admin_stats))
    app.add_handler(CommandHandler('siparisler', admin_orders))
    app.add_handler(CommandHandler('yetki', cmd_yetki))
    app.add_handler(CommandHandler('yetkikal', cmd_yetkikal))
    app.add_handler(CommandHandler('yetkiler', cmd_yetkiler))
    app.add_handler(CommandHandler('cevap', cmd_cevap))
    app.add_handler(CommandHandler('duyuru', cmd_duyuru))

    if app.job_queue:
        app.job_queue.run_repeating(
            check_pending_orders_job,
            interval=ORDER_STATUS_CHECK_INTERVAL,
            first=30
        )
    else:
        logger.warning(
            "JobQueue mevcut değil - otomatik sipariş tamamlama çalışmayacak. "
            "requirements.txt'de 'python-telegram-bot[job-queue]' olduğundan emin olun."
        )

    logger.info("Bot başlatılıyor...")
    app.run_polling(drop_pending_updates=True)

if __name__ == '__main__':
    main()
