import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
import sqlite3
from datetime import datetime, timedelta
import json

# ===== CONFIGURATION =====
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # @BotFather-dan alacaqsan
ADMIN_ID = 8034872992
LOG_CHANNEL = -1003895644077
START_BALANCE = 0

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== DATABASE =====
def init_db():
    conn = sqlite3.connect('eren_smm.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        balance INTEGER DEFAULT 0,
        vip_status BOOLEAN DEFAULT 0,
        referrals INTEGER DEFAULT 0,
        daily_bonus_used BOOLEAN DEFAULT 0,
        last_bonus_date TEXT,
        daily_transfer_count INTEGER DEFAULT 0,
        last_transfer_date TEXT,
        language TEXT DEFAULT 'TR',
        registration_date TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS products (
        product_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        category TEXT,
        price INTEGER,
        stock INTEGER,
        vip_only BOOLEAN DEFAULT 0,
        description TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        order_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        product_id INTEGER,
        quantity INTEGER,
        status TEXT DEFAULT 'Alındı',
        order_date TEXT,
        profile_link TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS transfers (
        transfer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id INTEGER,
        receiver_id INTEGER,
        amount INTEGER,
        transfer_date TEXT,
        status TEXT DEFAULT 'Başarılı'
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS referrals (
        referral_id INTEGER PRIMARY KEY AUTOINCREMENT,
        referrer_id INTEGER,
        referred_user_id INTEGER,
        referral_date TEXT
    )''')
    
    conn.commit()
    conn.close()

init_db()

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
        'vip_text': '👑 VIP Satın Al\n\nVIP olmak için 20 referans şart!\n\n✅ Mevcut referansınız: {current}/20\n❌ Eksik referans: {missing} kişi daha davet edin!\n\n👑 VIP Avantajları:\n✅ VIP Mağazaya erişim\n✅ Günde 2 kez günlük bonus\n✅ Her davette +2 Puan',
        'daily_bonus_success': '🎁 Günlük Bonus Alındı!\n\n➕ +1 Puan hesabınıza eklendi!\n💎 Yeni Bakiye: {balance} Puan\n\n👍 Bugünkü tüm bonus haklarını kullandın!',
        'daily_bonus_used': '⏳ Yarın tekrar gel!\n\nSonraki bonus: {time}',
        'get_daily_bonus': '🎁 Günlük Puanı Al',
        'insufficient_balance': '❌ Yetersiz Bakiye!\nGerekli: {needed} Puan\nBakiyeniz: {balance} Puan',
        'transfer_info': '💰 Puan Transfer Sistemi\n\n💎 Bakiyeniz: {balance} Puan\n⏳ Günlük Hak: {daily_left}/2 kaldı\n\n1️⃣ Her transferde bot 1 Puan komisyon keser.\n👤 Alıcı ID ve miktarı girerek transfer yapın.\n\nFormat: AlıcıID|Miktar\nÖrn: 1234567|10',
        'transfer_format_error': '❌ Hatalı format!\nDoğru format: AlıcıID|Miktar\nÖrn: 1234567|10',
        'transfer_success': '✅ Transfer Başarılı!\n\n📤 {amount} Puan gönderdiniz\n👤 Alıcı: {receiver_id}\n💸 Komisyon: 1 Puan\n💎 Yeni Bakiye: {new_balance} Puan',
        'shop_welcome': '👋 Normal Mağazaya Hoşgeldiniz!\n\nBir kategori seçin:',
        'tiktok_smm': '🎵 TikTok Smm',
        'telegram_smm': '📱 Telegram Smm',
        'vip_required_alert': '⚠️ Lütfen önce VIP olun!\n\nVIP mağazaya erişmek için VIP üyeliğiniz gerekiyor.',
        'no_orders': '📦 Sipariş Geçmişiniz\n\nHenüz hiç siparişiniz bulunmuyor.',
        'referral_link': '🤝 Davet Et, Kazan!\n\n👇 Aşağıdaki kişisel linkinizle arkadaşlarınızı sisteme davet edin, her yeni katılımda anında +1 Puan kazanın.\n\n📋 Sizin Linkiniz:\nhttps://t.me/ErenSMMBot?start={user_id}',
        'support_text': '💬 Destek Merkezi\n\n⚠️ Lütfen admini boş yere rahatsız etmeyiniz.\nMesajınız yalnızca gerçek bir sorun, hatalı sipariş veya acil durum söz konusuysa iletilmelidir.\nSık sorulan sorular için önce Yardım menüsünü inceleyin.\n\n💎 Bakiyeniz: {balance} Puan\n\n━━━━━━━━━━━━━━━━━\nSorununuzu veya talebinizi aşağıya yazın.\nİptal etmek için /iptal yazın.',
        'no_active_raffle': '🎲 Çekiliş\n\n⚠️ Şu anda aktif bir çekiliş bulunmuyor.\n\nYeni çekilişler için takipte kalın!',
        'donate_text': '⭐️ Bağış Yap\n\nDextroo SMM TR olarak sizlere her zaman daha iyi, daha hızlı, daha uzun süre ve daha uygun fiyata hizmet verebilmek için büyük emek harcıyoruz.\n\nEğer hizmetlerimizden memnun kaldıysanız, bize bir yıldız bağışı yaparak destek olabilirsiniz. Her katkı bizim için çok değerlidir. Sağ olun, var olun! 🙏\n\nKaç yıldız bağış yapmak istersiniz?',
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
• Promosyon kodu kullanarak

━━━━━━━━━━━━━━━━━
📦 Sipariş Takibi Nasıl Çalışır ⁉️
Satın aldığınız her ürün için otomatik bir Sipariş ID oluşturulur.

Sipariş durumları:
🟡 Alındı — Sisteme kaydedildi
🔵 İşlemde — Hazırlanıyor
🟢 Teslim Edildi — Size iletildi
🟥 İptal — Puan iade edildi

━━━━━━━━━━━━━━━━━
⁉️ Destek İçin: Destek butonu üzerinden ulaşabilirsiniz ⁉️''',
        'coupon_maintenance': '🔧 Kupon Sistemi Tamirde',
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
        'profile_text': '👤 Profile Summary\n\n🆔 User ID: {user_id}\n💎 Wallet Balance: {balance} Points\n🤝 Invited: {referrals} People\n💼 Total Orders: {orders}\n📆 Registration Date: {reg_date}',
    }
}

# ===== HELPER FUNCTIONS =====
def get_user(user_id):
    conn = sqlite3.connect('eren_smm.db')
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = c.fetchone()
    conn.close()
    return user

def create_user(user_id, username):
    conn = sqlite3.connect('eren_smm.db')
    c = conn.cursor()
    c.execute('''INSERT INTO users (user_id, username, balance, registration_date)
                 VALUES (?, ?, ?, ?)''',
              (user_id, username, START_BALANCE, datetime.now().strftime('%Y-%m-%d %H:%M')))
    conn.commit()
    conn.close()

def update_balance(user_id, amount):
    conn = sqlite3.connect('eren_smm.db')
    c = conn.cursor()
    c.execute('UPDATE users SET balance = balance + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()
    conn.close()

def get_user_language(user_id):
    conn = sqlite3.connect('eren_smm.db')
    c = conn.cursor()
    c.execute('SELECT language FROM users WHERE user_id = ?', (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 'TR'

def get_text(key, user_id, **kwargs):
    lang = get_user_language(user_id)
    text = LANG.get(lang, LANG['TR']).get(key, LANG['TR'].get(key, ''))
    return text.format(**kwargs) if kwargs else text

# ===== MAIN HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    
    existing_user = get_user(user_id)
    if not existing_user:
        create_user(user_id, user.username or f"User{user_id}")
    
    # Referral check
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id:
                conn = sqlite3.connect('eren_smm.db')
                c = conn.cursor()
                c.execute('SELECT * FROM referrals WHERE referrer_id = ? AND referred_user_id = ?',
                         (referrer_id, user_id))
                if not c.fetchone():
                    vip_status = get_user(referrer_id)[3]
                    bonus = 2 if vip_status else 1
                    c.execute('''INSERT INTO referrals (referrer_id, referred_user_id, referral_date)
                               VALUES (?, ?, ?)''',
                             (referrer_id, user_id, datetime.now().strftime('%Y-%m-%d %H:%M')))
                    c.execute('UPDATE users SET referrals = referrals + 1 WHERE user_id = ?',
                             (referrer_id,))
                    update_balance(referrer_id, bonus)
                    conn.commit()
                conn.close()
        except:
            pass
    
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
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(get_text('welcome', user_id), reply_markup=reply_markup)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    
    if query.data == 'balance':
        conn = sqlite3.connect('eren_smm.db')
        c = conn.cursor()
        c.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        balance = c.fetchone()[0]
        conn.close()
        text = f"💎 Bakiye: {balance} Puan"
        keyboard = [[InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'profile':
        conn = sqlite3.connect('eren_smm.db')
        c = conn.cursor()
        c.execute('SELECT user_id, balance, referrals, registration_date FROM users WHERE user_id = ?',
                 (user_id,))
        data = c.fetchone()
        c.execute('SELECT COUNT(*) FROM orders WHERE user_id = ?', (user_id,))
        order_count = c.fetchone()[0]
        conn.close()
        
        text = get_text('profile_text', user_id,
                       user_id=data[0],
                       balance=data[1],
                       referrals=data[2],
                       orders=order_count,
                       reg_date=data[3])
        keyboard = [[InlineKeyboardButton(get_text('daily_bonus', user_id), callback_data='daily_bonus'),
                     InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'daily_bonus':
        conn = sqlite3.connect('eren_smm.db')
        c = conn.cursor()
        c.execute('SELECT last_bonus_date, balance FROM users WHERE user_id = ?', (user_id,))
        last_bonus, balance = c.fetchone()
        
        can_use = True
        if last_bonus:
            last_date = datetime.strptime(last_bonus, '%Y-%m-%d')
            if (datetime.now() - last_date).days == 0:
                can_use = False
        
        if not can_use:
            text = get_text('daily_bonus_used', user_id, time='24:00')
            await query.answer(text, show_alert=True)
            return
        
        update_balance(user_id, 1)
        c.execute('UPDATE users SET last_bonus_date = ? WHERE user_id = ?',
                 (datetime.now().strftime('%Y-%m-%d'), user_id))
        conn.commit()
        conn.close()
        
        text = get_text('daily_bonus_success', user_id, balance=balance + 1)
        keyboard = [[InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'referral':
        text = get_text('referral_link', user_id, user_id=user_id)
        keyboard = [[InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'language':
        keyboard = [
            [InlineKeyboardButton('🇹🇷 Türkçe', callback_data='lang_tr'),
             InlineKeyboardButton('🇬🇧 English', callback_data='lang_en')],
            [InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]
        ]
        await query.edit_message_text('🌍 Lütfen dil tercihinizi yapın:', reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'lang_tr':
        conn = sqlite3.connect('eren_smm.db')
        c = conn.cursor()
        c.execute('UPDATE users SET language = ? WHERE user_id = ?', ('TR', user_id))
        conn.commit()
        conn.close()
        await start(update, context)
    
    elif query.data == 'lang_en':
        conn = sqlite3.connect('eren_smm.db')
        c = conn.cursor()
        c.execute('UPDATE users SET language = ? WHERE user_id = ?', ('EN', user_id))
        conn.commit()
        conn.close()
        await start(update, context)
    
    elif query.data == 'shop':
        keyboard = [
            [InlineKeyboardButton(get_text('tiktok_smm', user_id), callback_data='shop_tiktok'),
             InlineKeyboardButton(get_text('telegram_smm', user_id), callback_data='shop_telegram')],
            [InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]
        ]
        await query.edit_message_text(get_text('shop_welcome', user_id), reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'vip_shop':
        conn = sqlite3.connect('eren_smm.db')
        c = conn.cursor()
        c.execute('SELECT vip_status FROM users WHERE user_id = ?', (user_id,))
        vip = c.fetchone()[0]
        conn.close()
        
        if not vip:
            await query.answer(get_text('vip_required_alert', user_id), show_alert=True)
            return
    
    elif query.data == 'orders':
        conn = sqlite3.connect('eren_smm.db')
        c = conn.cursor()
        c.execute('SELECT * FROM orders WHERE user_id = ?', (user_id,))
        orders = c.fetchall()
        conn.close()
        
        if not orders:
            text = get_text('no_orders', user_id)
        else:
            text = f"📦 Siparişleriniz ({len(orders)} adet):\n\n"
            for order in orders:
                text += f"ID: {order[0]} | Status: {order[4]}\n"
        
        keyboard = [[InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'transfer':
        conn = sqlite3.connect('eren_smm.db')
        c = conn.cursor()
        c.execute('SELECT balance, last_transfer_date, daily_transfer_count FROM users WHERE user_id = ?',
                 (user_id,))
        balance, last_transfer, daily_count = c.fetchone()
        
        daily_left = 0
        if last_transfer:
            last_date = datetime.strptime(last_transfer, '%Y-%m-%d')
            if (datetime.now() - last_date).days == 0:
                daily_left = 2 - daily_count
            else:
                daily_left = 2
        else:
            daily_left = 2
        
        conn.close()
        
        text = get_text('transfer_info', user_id, balance=balance, daily_left=daily_left)
        keyboard = [[InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        
        context.user_data['awaiting_transfer'] = True
    
    elif query.data == 'raffle':
        text = get_text('no_active_raffle', user_id)
        keyboard = [[InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
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
            [InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]
        ]
        await query.edit_message_text(get_text('donate_text', user_id), reply_markup=InlineKeyboardMarkup(buttons))
    
    elif query.data.startswith('donate_'):
        stars = int(query.data.split('_')[1])
        await context.bot.send_invoice(
            chat_id=user_id,
            title=f'Eren SMM - {stars} Yıldız Bağış',
            description=f'{stars} yıldız bağışı yapın',
            payload=f'donate_{stars}_{user_id}',
            provider_token='',
            currency='XTR',
            prices=[{'label': f'{stars} Yıldız', 'amount': stars}]
        )
    
    elif query.data == 'coupon':
        text = get_text('coupon_maintenance', user_id)
        keyboard = [[InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'support':
        text = get_text('support_text', user_id, balance=get_user(user_id)[2])
        keyboard = [[InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        context.user_data['awaiting_support'] = True
    
    elif query.data == 'help':
        keyboard = [[InlineKeyboardButton(get_text('back_to_menu', user_id), callback_data='main_menu')]]
        await query.edit_message_text(get_text('help_text', user_id), reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data == 'main_menu':
        await start(update, context)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            
            conn = sqlite3.connect('eren_smm.db')
            c = conn.cursor()
            
            c.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
            sender_balance = c.fetchone()[0]
            
            if sender_balance < amount + 1:
                needed = amount + 1
                await update.message.reply_text(
                    get_text('insufficient_balance', user_id,
                            needed=needed,
                            balance=sender_balance))
                return
            
            c.execute('SELECT balance FROM users WHERE user_id = ?', (receiver_id,))
            receiver = c.fetchone()
            if not receiver:
                await update.message.reply_text('❌ Alıcı kullanıcı bulunamadı!')
                return
            
            update_balance(user_id, -(amount + 1))
            update_balance(receiver_id, amount)
            
            c.execute('''INSERT INTO transfers (sender_id, receiver_id, amount, transfer_date)
                        VALUES (?, ?, ?, ?)''',
                     (user_id, receiver_id, amount, datetime.now().strftime('%Y-%m-%d %H:%M')))
            
            c.execute('UPDATE users SET daily_transfer_count = daily_transfer_count + 1, last_transfer_date = ? WHERE user_id = ?',
                     (datetime.now().strftime('%Y-%m-%d'), user_id))
            
            conn.commit()
            conn.close()
            
            new_balance = sender_balance - (amount + 1)
            context.user_data['awaiting_transfer'] = False
            
            success_msg = get_text('transfer_success', user_id,
                                  amount=amount,
                                  receiver_id=receiver_id,
                                  new_balance=new_balance)
            await update.message.reply_text(success_msg)
            
            # Log to channel
            log_msg = f"💸 YENİ TRANSFER\n\n👤 Gönderen: {user_id}\n👤 Alan: {receiver_id}\n💎 Miktar: {amount}\n💰 Komisyon: 1\n📅 Zaman: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            await context.bot.send_message(LOG_CHANNEL, log_msg)
            
            # Notify receiver
            receiver_msg = f"✅ {user_id} sizinə {amount} Puan göndərdi!\n💎 Yeni Bakiye: {receiver[0] + amount}"
            await context.bot.send_message(receiver_id, receiver_msg)
        
        except ValueError:
            await update.message.reply_text(get_text('transfer_format_error', user_id))
    
    elif context.user_data.get('awaiting_support'):
        if text == '/iptal':
            context.user_data['awaiting_support'] = False
            await update.message.reply_text('❌ İptal edildi.')
            return
        
        context.user_data['awaiting_support'] = False
        
        # Send to admin
        support_log = f"💬 YENİ DESTEK MESAJI\n\n👤 Kullanıcı: {user_id}\n💬 Mesaj:\n{text}\n\n📅 Zaman: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        await context.bot.send_message(LOG_CHANNEL, support_log)
        await context.bot.send_message(ADMIN_ID, f"Yeni destek mesajı:\n\nKullanıcı: {user_id}\nMesaj: {text}")
        
        await update.message.reply_text('✅ Mesajınız iletildi. Yakında sizinle iletişime geçeceğiz.')

# ===== ADMIN COMMANDS =====
async def admin_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    
    if len(context.args) < 4:
        await update.message.reply_text(
            '📝 Kullanım:\n'
            '/admin_add_product "ad" kategori fiyat stok [vip]\n'
            'Örn: /admin_add_product "TikTok Followers" tiktok 10 100\n'
            'VIP: /admin_add_product "VIP Paket" tiktok 50 50 vip'
        )
        return
    
    try:
        name = ' '.join(context.args[:-3]).strip('"')
        category = context.args[-3]
        price = int(context.args[-2])
        stock = int(context.args[-1])
        vip_only = 0
        
        if len(context.args) > 4 and context.args[-1] == 'vip':
            vip_only = 1
            stock = int(context.args[-2])
        
        conn = sqlite3.connect('eren_smm.db')
        c = conn.cursor()
        c.execute('''INSERT INTO products (name, category, price, stock, vip_only)
                    VALUES (?, ?, ?, ?, ?)''',
                 (name, category, price, stock, vip_only))
        product_id = c.lastrowid
        conn.commit()
        conn.close()
        
        vip_tag = '👑 VIP' if vip_only else ''
        await update.message.reply_text(f'✅ Ürün eklendi!\n\nID: {product_id}\n📝 Ad: {name}\n📂 Kategori: {category}\n💰 Fiyat: {price}\n📦 Stok: {stock} {vip_tag}')
    
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
        
        conn = sqlite3.connect('eren_smm.db')
        c = conn.cursor()
        c.execute('UPDATE products SET stock = ? WHERE product_id = ?', (new_stock, product_id))
        c.execute('SELECT name, stock FROM products WHERE product_id = ?', (product_id,))
        product = c.fetchone()
        conn.commit()
        conn.close()
        
        if product:
            await update.message.reply_text(f'✅ Stok güncellendi!\n\n📝 Ürün: {product[0]}\n📦 Yeni Stok: {new_stock}')
        else:
            await update.message.reply_text('❌ Ürün bulunamadı!')
    except Exception as e:
        await update.message.reply_text(f'❌ Hata: {str(e)}')

async def admin_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    
    conn = sqlite3.connect('eren_smm.db')
    c = conn.cursor()
    c.execute('SELECT product_id, name, category, price, stock, vip_only FROM products')
    products = c.fetchall()
    conn.close()
    
    if not products:
        await update.message.reply_text('📦 Ürün bulunamadı!')
        return
    
    text = '📦 TÜM ÜRÜNLER\n\n'
    for p in products:
        vip_tag = '👑' if p[5] else ''
        text += f"ID: {p[0]} | {p[1]} ({p[2]}) | 💰{p[3]} | 📦{p[4]} {vip_tag}\n"
    
    await update.message.reply_text(text)

async def admin_give_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    
    if len(context.args) < 2:
        await update.message.reply_text('📝 Kullanım: /admin_give <user_id> <puan>')
        return
    
    try:
        user_id = int(context.args[0])
        points = int(context.args[1])
        
        update_balance(user_id, points)
        
        conn = sqlite3.connect('eren_smm.db')
        c = conn.cursor()
        c.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        new_balance = c.fetchone()
        conn.close()
        
        if new_balance:
            await update.message.reply_text(f'✅ {points} puan verildi!\n\n👤 ID: {user_id}\n💎 Yeni Bakiye: {new_balance[0]}')
        else:
            await update.message.reply_text('❌ Kullanıcı bulunamadı!')
    except Exception as e:
        await update.message.reply_text(f'❌ Hata: {str(e)}')

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text('❌ Yetkiniz yok!')
        return
    
    conn = sqlite3.connect('eren_smm.db')
    c = conn.cursor()
    
    c.execute('SELECT COUNT(*) FROM users')
    total_users = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM users WHERE vip_status = 1')
    vip_users = c.fetchone()[0]
    
    c.execute('SELECT COUNT(*) FROM orders')
    total_orders = c.fetchone()[0]
    
    c.execute('SELECT SUM(balance) FROM users')
    total_balance = c.fetchone()[0] or 0
    
    c.execute('SELECT COUNT(*) FROM products')
    total_products = c.fetchone()[0]
    
    conn.close()
    
    text = f'''📊 BOT STATİSTİKLERİ
    
👥 Toplam Kullanıcı: {total_users}
👑 VIP Kullanıcı: {vip_users}
📦 Toplam Sipariş: {total_orders}
💎 Toplam Bakiye: {total_balance}
🛍️ Toplam Ürün: {total_products}
📅 Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}'''
    
    await update.message.reply_text(text)

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
    
    app.run_polling()

if __name__ == '__main__':
    main()

