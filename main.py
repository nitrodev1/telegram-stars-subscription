import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Optional
import secrets
import string

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    LabeledPrice,
    PreCheckoutQuery
)

#config

BOT_TOKEN = ""
ADMIN_ID = 

class AdminStates(StatesGroup):
    waiting_description = State()
    waiting_price = State()
    waiting_channel_id = State()
    waiting_user_id = State()

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

def init_db():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            subscription_end TIMESTAMP,
            invite_link TEXT,
            notified BOOLEAN DEFAULT FALSE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', 
                   ('description', 'Описание проекта по умолчанию'))
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', 
                   ('price', '10'))
    cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', 
                   ('channel_id', ''))
    
    conn.commit()
    conn.close()

def get_setting(key: str) -> str:
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else ''

def set_setting(key: str, value: str):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result

def add_user(user_id: int, username: str, subscription_end: datetime, invite_link: str):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO users (user_id, username, subscription_end, invite_link, notified) 
        VALUES (?, ?, ?, ?, FALSE)
    ''', (user_id, username, subscription_end, invite_link))
    conn.commit()
    conn.close()

def update_subscription(user_id: int, new_end_date: datetime):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET subscription_end = ?, notified = FALSE WHERE user_id = ?', 
                   (new_end_date, user_id))
    conn.commit()
    conn.close()

def remove_user(user_id: int):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def get_expiring_users():
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    expiry_date = datetime.now() + timedelta(days=2)
    cursor.execute('''
        SELECT * FROM users 
        WHERE subscription_end <= ? AND subscription_end > ? AND notified = FALSE
    ''', (expiry_date, datetime.now()))
    result = cursor.fetchall()
    conn.close()
    return result

def mark_user_notified(user_id: int):
    conn = sqlite3.connect('bot.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET notified = TRUE WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

def generate_invite_link():
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))

async def create_channel_invite(channel_id: str):
    try:
        invite_link = await bot.create_chat_invite_link(
            chat_id=channel_id,
            member_limit=1,
            expire_date=datetime.now() + timedelta(days=32)
        )
        return invite_link.invite_link
    except Exception as e:
        logging.error(f"Ошибка создания ссылки: {e}")
        return None

def main_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Описание проекта", callback_data="description")],
        [InlineKeyboardButton(text="💳 Оплатить подписку", callback_data="payment")]
    ])
    return keyboard

def admin_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Изменить описание", callback_data="admin_description")],
        [InlineKeyboardButton(text="💰 Изменить цену", callback_data="admin_price")],
        [InlineKeyboardButton(text="📺 Изменить канал", callback_data="admin_channel")],
        [InlineKeyboardButton(text="🎁 Выдать подписку", callback_data="admin_give_sub")]
    ])
    return keyboard

def renewal_keyboard(discounted_price: int):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔄 Продлить за {discounted_price} звезд", 
                             callback_data=f"renew_{discounted_price}")],
        [InlineKeyboardButton(text="❌ Не продлевать", callback_data="cancel_sub")]
    ])
    return keyboard

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    if message.from_user.id == ADMIN_ID:
        await message.answer("👋 Добро пожаловать в админ-панель!", reply_markup=admin_keyboard())
    else:
        user = get_user(message.from_user.id)
        if user and datetime.fromisoformat(user[2]) > datetime.now():
            await message.answer(f"✅ У вас активна подписка до {user[2]}")
        else:
            await message.answer(
                "👋 Добро пожаловать! Выберите действие:", 
                reply_markup=main_keyboard()
            )


@dp.callback_query(F.data == "description")
async def description_handler(callback: types.CallbackQuery):
    description = get_setting('description')
    await callback.message.edit_text(description, reply_markup=main_keyboard())

@dp.callback_query(F.data == "payment")
async def payment_handler(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    if user and datetime.fromisoformat(user[2]) > datetime.now():
        await callback.answer("У вас уже есть активная подписка!", show_alert=True)
        return
    
    price = int(get_setting('price'))
    channel_id = get_setting('channel_id')
    
    if not channel_id:
        await callback.answer("Канал не настроен. Обратитесь к администратору.", show_alert=True)
        return
    
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Подписка на канал",
        description="Подписка на 1 месяц",
        payload="subscription_payment",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Подписка", amount=price)]
    )

@dp.pre_checkout_query()
async def pre_checkout_handler(query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment_handler(message: types.Message):

    if message.successful_payment.invoice_payload == "renewal_payment":
        user_id = message.from_user.id
        user = get_user(user_id)
        
        if user:
            current_end = datetime.fromisoformat(user[2])
            new_end = current_end + timedelta(days=30)
            update_subscription(user_id, new_end)
            
            await message.answer(
                f"✅ Подписка продлена!\n\n"
                f"📅 Новая дата окончания: {new_end.strftime('%d.%m.%Y %H:%M')}"
            )
    else:
        user_id = message.from_user.id
        username = message.from_user.username or f"user_{user_id}"
        channel_id = get_setting('channel_id')
        
        invite_link = await create_channel_invite(channel_id)
        
        if invite_link:
            subscription_end = datetime.now() + timedelta(days=30)
            add_user(user_id, username, subscription_end, invite_link)
            
            await message.answer(
                f"✅ Оплата прошла успешно!\n\n"
                f"🔗 Ваша ссылка для входа в канал: {invite_link}\n\n"
                f"📅 Подписка действует до: {subscription_end.strftime('%d.%m.%Y %H:%M')}"
            )
        else:
            await message.answer("❌ Ошибка при создании ссылки. Обратитесь к администратору.")

@dp.callback_query(F.data.startswith("renew_"))
async def renew_subscription_handler(callback: types.CallbackQuery):
    discounted_price = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    await bot.send_invoice(
        chat_id=user_id,
        title="Продление подписки",
        description="Продление подписки на 1 месяц со скидкой 10%",
        payload="renewal_payment",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Продление", amount=discounted_price)]
    )

@dp.callback_query(F.data == "cancel_sub")
async def cancel_subscription_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if user:
        channel_id = get_setting('channel_id')
        try:
            await bot.ban_chat_member(channel_id, user_id)
            await bot.unban_chat_member(channel_id, user_id)
        except Exception as e:
            logging.error(f"Ошибка при удалении пользователя из канала: {e}")
        
        remove_user(user_id)
        await callback.message.edit_text("❌ Подписка отменена. Доступ к каналу закрыт.")

@dp.callback_query(F.data == "admin_description")
async def admin_description_handler(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    await callback.message.edit_text("📝 Введите новое описание проекта:")
    await state.set_state(AdminStates.waiting_description)

@dp.message(StateFilter(AdminStates.waiting_description))
async def process_description(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    set_setting('description', message.text)
    await message.answer("✅ Описание обновлено!", reply_markup=admin_keyboard())
    await state.clear()

@dp.callback_query(F.data == "admin_price")
async def admin_price_handler(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    current_price = get_setting('price')
    await callback.message.edit_text(f"💰 Текущая цена: {current_price} звезд\nВведите новую цену:")
    await state.set_state(AdminStates.waiting_price)

@dp.message(StateFilter(AdminStates.waiting_price))
async def process_price(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        price = int(message.text)
        if price <= 0:
            await message.answer("❌ Цена должна быть положительным числом!")
            return
        
        set_setting('price', str(price))
        await message.answer(f"✅ Цена обновлена на {price} звезд!", reply_markup=admin_keyboard())
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число!")

@dp.callback_query(F.data == "admin_channel")
async def admin_channel_handler(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    current_channel = get_setting('channel_id')
    await callback.message.edit_text(f"📺 Текущий канал: {current_channel}\nВведите ID нового канала:")
    await state.set_state(AdminStates.waiting_channel_id)

@dp.message(StateFilter(AdminStates.waiting_channel_id))
async def process_channel_id(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    channel_id = message.text.strip()
    try:
        chat = await bot.get_chat(channel_id)
        set_setting('channel_id', channel_id)
        await message.answer(f"✅ Канал обновлен: {chat.title}", reply_markup=admin_keyboard())
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}\nПроверьте ID канала и права бота!")

@dp.callback_query(F.data == "admin_give_sub")
async def admin_give_sub_handler(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Доступ запрещен!", show_alert=True)
        return
    
    await callback.message.edit_text("🎁 Введите ID пользователя для выдачи подписки:")
    await state.set_state(AdminStates.waiting_user_id)

@dp.message(StateFilter(AdminStates.waiting_user_id))
async def process_give_subscription(message: types.Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        user_id = int(message.text)
        channel_id = get_setting('channel_id')
        
        if not channel_id:
            await message.answer("❌ Канал не настроен!")
            return
        
        invite_link = await create_channel_invite(channel_id)
        
        if invite_link:
            subscription_end = datetime.now() + timedelta(days=30)
            add_user(user_id, f"admin_given_{user_id}", subscription_end, invite_link)
            
            await bot.send_message(
                user_id,
                f"🎁 Вам выдана подписка!\n\n"
                f"🔗 Ссылка для входа: {invite_link}\n\n"
                f"📅 Действует до: {subscription_end.strftime('%d.%m.%Y %H:%M')}"
            )
            
            await message.answer("✅ Подписка выдана!", reply_markup=admin_keyboard())
        else:
            await message.answer("❌ Ошибка при создании ссылки!")
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректный ID пользователя!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

async def check_expiring_subscriptions():
    while True:
        try:
            expiring_users = get_expiring_users()
            regular_price = int(get_setting('price'))
            discounted_price = int(regular_price * 0.9)
            
            for user in expiring_users:
                user_id, username, subscription_end, invite_link, notified = user
                
                await bot.send_message(
                    user_id,
                    f"⏰ Ваша подписка истекает {subscription_end}!\n\n"
                    f"🎯 Продлите сейчас со скидкой 10%!",
                    reply_markup=renewal_keyboard(discounted_price)
                )
                
                mark_user_notified(user_id)
                
        except Exception as e:
            logging.error(f"Ошибка при проверке подписок: {e}")
        
        await asyncio.sleep(3600)

async def main():
    init_db()
    
    asyncio.create_task(check_expiring_subscriptions())
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
