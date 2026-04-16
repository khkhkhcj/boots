import asyncio
import sqlite3
import datetime
import re
import threading

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)

# ================= CONFIG =================
API_TOKEN = "8732957894:AAEaxVVWuOoKtg_ckYTJQrzT9WS2E7QFy7w"
ADMIN_ID = 864829848

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# ================= DB =================
conn = sqlite3.connect("exams.db", check_same_thread=False)
cur = conn.cursor()
db_lock = threading.Lock()

def init_db():
    with db_lock:
        cur.execute("""CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            date TEXT,
            status INTEGER DEFAULT 0,
            reason TEXT,
            reminded_tomorrow INTEGER DEFAULT 0,
            reminded_today INTEGER DEFAULT 0
        )""")
        cur.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            is_blocked INTEGER DEFAULT 0
        )""")
        conn.commit()

init_db()

# ================= FSM =================
class AddExam(StatesGroup):
    subject = State()
    date_choice = State()
    custom_date = State()

class FailReason(StatesGroup):
    reason = State()

class EditExam(StatesGroup):
    eid = State()
    new_subject = State()
    new_date = State()

# ================= KEYBOARDS =================
admin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📚 Все пересдачи"), KeyboardButton(text="⏳ Только ждуны")],
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="➕ Добавить")]
    ],
    resize_keyboard=True
)

user_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📚 Расписание")],
        [KeyboardButton(text="📊 Статистика")]
    ],
    resize_keyboard=True
)

date_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Сегодня", callback_data="date_today"),
     InlineKeyboardButton(text="Завтра", callback_data="date_tomorrow")],
    [InlineKeyboardButton(text="Через 3 дня", callback_data="date_3"),
     InlineKeyboardButton(text="Через неделю", callback_data="date_7")],
    [InlineKeyboardButton(text="📝 Ввести вручную", callback_data="date_manual"),
     InlineKeyboardButton(text="⏳ Без даты", callback_data="date_skip")]
])

# ================= HELPERS =================
def validate_date(text: str):
    """Проверяет дату формата ДД.ММ.ГГГГ. Возвращает строку или None."""
    if not re.match(r"^\d{2}\.\d{2}\.\d{4}$", text):
        return None
    try:
        datetime.datetime.strptime(text, "%d.%m.%Y")
        return text
    except ValueError:
        return None

def get_date_from_callback(cb_data):
    today = datetime.date.today()
    if cb_data == "date_today":    return today
    if cb_data == "date_tomorrow": return today + datetime.timedelta(days=1)
    if cb_data == "date_3":        return today + datetime.timedelta(days=3)
    if cb_data == "date_7":        return today + datetime.timedelta(days=7)
    return None

def get_all_users():
    with db_lock:
        cur.execute("SELECT user_id FROM users WHERE is_blocked=0")
        return [row[0] for row in cur.fetchall()]

def days_until(date_str: str) -> str:
    """Возвращает строку типа 'через 3 дня' или 'сегодня'."""
    if date_str == "Без даты":
        return ""
    try:
        exam_date = datetime.datetime.strptime(date_str, "%d.%m.%Y").date()
        today = datetime.date.today()
        diff = (exam_date - today).days
        if diff == 0:   return " — 🔥 сегодня!"
        if diff == 1:   return " — ⚡️ завтра!"
        if diff < 0:    return f" — {abs(diff)} дн. назад"
        return f" — через {diff} дн."
    except:
        return ""

# ================= BROADCAST =================
async def broadcast(text: str, exclude_id: int = None):
    """Рассылает сообщение всем пользователям."""
    users = get_all_users()
    for user_id in users:
        if exclude_id and user_id == exclude_id:
            continue
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
        except Exception:
            pass

# ================= КРАСИВОЕ РАСПИСАНИЕ =================
def build_schedule_text(rows, title="📚 РАСПИСАНИЕ ПЕРЕСДАЧ") -> str:
    """Строит красивый текст расписания из строк БД."""
    today = datetime.date.today()

    # Разбиваем на группы
    overdue = []
    upcoming = []
    no_date = []
    done_list = []

    for eid, subject, date, status, reason in rows:
        if status == 1:
            done_list.append((subject, date))
            continue
        if status == 2:
            done_list.append((subject, date, reason))
            continue
        if date == "Без даты":
            no_date.append(subject)
            continue
        try:
            exam_date = datetime.datetime.strptime(date, "%d.%m.%Y").date()
            if exam_date < today:
                overdue.append((subject, date))
            else:
                upcoming.append((subject, date, exam_date))
        except:
            no_date.append(subject)

    upcoming.sort(key=lambda x: x[2])

    lines = [f"╔══════════════════════╗"]
    lines.append(f"║  {title}  ║")
    lines.append(f"╚══════════════════════╝\n")

    if upcoming:
        lines.append("📅 <b>ПРЕДСТОЯЩИЕ:</b>")
        for subject, date, exam_date in upcoming:
            diff = (exam_date - today).days
            if diff == 0:
                badge = "🔥 СЕГОДНЯ"
            elif diff == 1:
                badge = "⚡️ ЗАВТРА"
            elif diff <= 3:
                badge = f"⏰ через {diff} дн."
            else:
                badge = f"📌 {date}"
            lines.append(f"  └ {subject}  <i>{badge}</i>")
        lines.append("")

    if overdue:
        lines.append("⚠️ <b>ПРОСРОЧЕННЫЕ:</b>")
        for subject, date in overdue:
            lines.append(f"  └ {subject}  <i>({date})</i>")
        lines.append("")

    if no_date:
        lines.append("🗓 <b>ДАТА НЕ НАЗНАЧЕНА:</b>")
        for subject in no_date:
            lines.append(f"  └ {subject}")
        lines.append("")

    if done_list:
        lines.append("✅ <b>ЗАВЕРШЁННЫЕ:</b>")
        for item in done_list:
            if len(item) == 2:
                subject, date = item
                lines.append(f"  └ ✔️ {subject}  <i>({date})</i>")
            else:
                subject, date, reason = item
                lines.append(f"  └ ❌ {subject}  <i>— {reason}</i>")
        lines.append("")

    if not upcoming and not overdue and not no_date and not done_list:
        lines.append("📭 Список пуст")

    lines.append(f"🕐 Обновлено: {today.strftime('%d.%m.%Y')}")
    return "\n".join(lines)

# ================= УВЕДОМЛЕНИЕ ОБ ИЗМЕНЕНИИ =================
async def notify_status_change(subject: str, date: str, new_status: int, reason: str = None):
    """Красивое уведомление всем при изменении статуса экзамена."""
    today_str = datetime.date.today().strftime("%d.%m.%Y")

    if new_status == 1:
        text = (
            f"🎉 <b>ОБНОВЛЕНИЕ СТАТУСА</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📖 Предмет: <b>{subject}</b>\n"
            f"📅 Дата экзамена: {date}\n"
            f"✅ Статус: <b>СДАН</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 {today_str}"
        )
    elif new_status == 2:
        text = (
            f"📋 <b>ОБНОВЛЕНИЕ СТАТУСА</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📖 Предмет: <b>{subject}</b>\n"
            f"📅 Дата экзамена: {date}\n"
            f"❌ Статус: <b>НЕ СДАН</b>\n"
            f"💬 Причина: {reason}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 {today_str}"
        )
    elif new_status == 0:
        text = (
            f"📌 <b>ДОБАВЛЕН НОВЫЙ ЭКЗАМЕН</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📖 Предмет: <b>{subject}</b>\n"
            f"📅 Дата: {date if date != 'Без даты' else 'будет назначена'}\n"
            f"⏳ Статус: <b>ОЖИДАЕТ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 {today_str}"
        )
    else:
        return

    await broadcast(text)

# ================= NOTIFICATION SCHEDULER =================
async def check_notifications():
    print("🔔 Система уведомлений запущена")
    while True:
        try:
            today = datetime.date.today()
            tomorrow = today + datetime.timedelta(days=1)
            today_str = today.strftime("%d.%m.%Y")
            tomorrow_str = tomorrow.strftime("%d.%m.%Y")

            # Уведомления ЗА ДЕНЬ ДО
            with db_lock:
                cur.execute("SELECT id, subject FROM exams WHERE status=0 AND date=? AND reminded_tomorrow=0", (tomorrow_str,))
                tomorrow_exams = cur.fetchall()

            if tomorrow_exams:
                names = "\n".join([f"  └ ⚡️ {subj}" for _, subj in tomorrow_exams])
                msg_text = (
                    f"🔔 <b>НАПОМИНАНИЕ</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"Завтра <b>{tomorrow_str}</b> экзамены:\n"
                    f"{names}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📚 Готовьтесь!"
                )
                users = get_all_users()
                for user_id in users:
                    try:
                        await bot.send_message(user_id, msg_text, parse_mode="HTML")
                    except Exception:
                        pass
                with db_lock:
                    for eid, _ in tomorrow_exams:
                        cur.execute("UPDATE exams SET reminded_tomorrow=1 WHERE id=?", (eid,))
                    conn.commit()

            # Уведомления В ДЕНЬ ЭКЗАМЕНА
            with db_lock:
                cur.execute("SELECT id, subject FROM exams WHERE status=0 AND date=? AND reminded_today=0", (today_str,))
                today_exams = cur.fetchall()

            if today_exams:
                names = "\n".join([f"  └ 🔥 {subj}" for _, subj in today_exams])
                msg_text = (
                    f"🚨 <b>СЕГОДНЯ ЭКЗАМЕНЫ!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📅 <b>{today_str}</b>\n"
                    f"{names}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🍀 Удачи всем!"
                )
                users = get_all_users()
                for user_id in users:
                    try:
                        await bot.send_message(user_id, msg_text, parse_mode="HTML")
                    except Exception:
                        pass
                with db_lock:
                    for eid, _ in today_exams:
                        cur.execute("UPDATE exams SET reminded_today=1 WHERE id=?", (eid,))
                    conn.commit()

        except Exception as e:
            print(f"Ошибка шедулера: {e}")

        await asyncio.sleep(3600)  # Проверяем раз в час

@dp.startup()
async def on_startup(bot: Bot):
    asyncio.create_task(check_notifications())

# ================= HANDLERS =================

@dp.message(Command("start"))
async def start(msg: types.Message):
    with db_lock:
        cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (msg.from_user.id,))
        conn.commit()
    kb = admin_kb if msg.from_user.id == ADMIN_ID else user_kb
    await msg.answer(
        "👋 <b>Привет!</b>\nЯ бот для учёта пересдач.\n"
        "Здесь ты всегда в курсе статусов и расписания 📚",
        reply_markup=kb,
        parse_mode="HTML"
    )

# --- TEST NOTIFICATIONS ---
@dp.message(Command("test_notify"))
async def test_notify(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    test_msg = (
        "🧪 <b>ТЕСТОВОЕ УВЕДОМЛЕНИЕ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Система уведомлений работает корректно ✅"
    )
    users = get_all_users()
    sent = 0
    for user_id in users:
        try:
            await bot.send_message(user_id, test_msg, parse_mode="HTML")
            sent += 1
        except Exception:
            pass
    await msg.answer(f"✅ Отправлено {sent} пользователям")

# --- ADD ---
@dp.message(F.text == "➕ Добавить")
async def add_start(msg: types.Message, state: FSMContext):
    if msg.from_user.id != ADMIN_ID:
        await msg.answer("🔒 Только администратор может добавлять экзамены.")
        return
    await msg.answer("📌 Введите название предмета:")
    await state.set_state(AddExam.subject)

@dp.message(AddExam.subject)
async def add_subject(msg: types.Message, state: FSMContext):
    await state.update_data(subject=msg.text.strip())
    await msg.answer("📅 Выберите дату или пропустите:", reply_markup=date_kb)
    await state.set_state(AddExam.date_choice)

@dp.callback_query(F.data.startswith("date_"), AddExam.date_choice)
async def add_date_handler(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    subject = data["subject"]

    if call.data == "date_manual":
        await call.message.answer("✏️ Введите дату (ДД.ММ.ГГГГ):")
        await state.set_state(AddExam.custom_date)
        await call.answer()
        return

    if call.data == "date_skip":
        date_str = "Без даты"
    else:
        date_obj = get_date_from_callback(call.data)
        date_str = date_obj.strftime("%d.%m.%Y")

    with db_lock:
        cur.execute("INSERT INTO exams (subject, date) VALUES (?, ?)", (subject, date_str))
        conn.commit()

    date_display = date_str if date_str != "Без даты" else "будет назначена"
    await call.message.answer(f"✅ <b>{subject}</b> добавлен\n📅 Дата: {date_display}", parse_mode="HTML")
    await notify_status_change(subject, date_str, 0)
    await state.clear()
    await call.answer()

@dp.message(AddExam.custom_date)
async def add_custom_date(msg: types.Message, state: FSMContext):
    text = msg.text.strip()
    if not validate_date(text):
        await msg.answer("❌ Неверный формат. Введите дату как ДД.ММ.ГГГГ")
        return
    data = await state.get_data()
    subject = data["subject"]
    with db_lock:
        cur.execute("INSERT INTO exams (subject, date) VALUES (?, ?)", (subject, text))
        conn.commit()
    await msg.answer(f"✅ <b>{subject}</b> добавлен\n📅 Дата: {text}", parse_mode="HTML")
    await notify_status_change(subject, text, 0)
    await state.clear()

# --- SHOW EXAMS ---
async def show_exams(msg: types.Message, status_filter=None):
    query = "SELECT id, subject, date, status, reason FROM exams ORDER BY date"
    params = []

    if status_filter is not None:
        query = "SELECT id, subject, date, status, reason FROM exams WHERE status=? ORDER BY date"
        params.append(status_filter)

    with db_lock:
        cur.execute(query, params)
        rows = cur.fetchall()

    if not rows:
        await msg.answer("📭 Список пуст")
        return

    # Админ — каждый экзамен отдельно с кнопками
    if msg.from_user.id == ADMIN_ID:
        today = datetime.date.today()
        for eid, subject, date, status, reason in rows:
            if status == 0:
                st = f"⏳ Ожидает{days_until(date)}"
            elif status == 1:
                st = "✅ Сдан"
            else:
                st = f"❌ Не сдан — {reason}"

            date_display = f"📅 {date}" if date != "Без даты" else "📅 Дата не назначена"

            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Сдан", callback_data=f"done_{eid}"),
                    InlineKeyboardButton(text="❌ Не сдан", callback_data=f"fail_{eid}"),
                    InlineKeyboardButton(text="✏️", callback_data=f"edit_{eid}"),
                    InlineKeyboardButton(text="🗑", callback_data=f"del_{eid}")
                ]
            ])
            await msg.answer(
                f"📖 <b>{subject}</b>\n{date_display}\n{st}",
                reply_markup=kb,
                parse_mode="HTML"
            )

    # Юзер — красивое расписание одним сообщением
    else:
        text = build_schedule_text(rows)
        await msg.answer(text, parse_mode="HTML")

@dp.message(F.text.in_(["📚 Все пересдачи", "📚 Расписание"]))
async def show_all(msg: types.Message):
    await show_exams(msg)

@dp.message(F.text == "⏳ Только ждуны")
async def show_pending(msg: types.Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await show_exams(msg, status_filter=0)

# --- STATS ---
@dp.message(F.text == "📊 Статистика")
async def stats(msg: types.Message):
    with db_lock:
        cur.execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN status=1 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN status=2 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN status=0 THEN 1 ELSE 0 END)
            FROM exams
        """)
        total, passed, failed, pending = cur.fetchone()

    passed = passed or 0
    failed = failed or 0
    pending = pending or 0

    if not total or total == 0:
        await msg.answer("📊 Нет данных")
        return

    success_rate = (passed / total) * 100
    bar_filled = int(success_rate / 10)
    bar = "█" * bar_filled + "░" * (10 - bar_filled)

    text = (
        f"📊 <b>СТАТИСТИКА</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📚 Всего экзаменов: <b>{total}</b>\n"
        f"✅ Сдано:           <b>{passed}</b>\n"
        f"❌ Не сдано:        <b>{failed}</b>\n"
        f"⏳ Ожидают:         <b>{pending}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 Успешность:\n"
        f"[{bar}] {success_rate:.1f}%"
    )
    await msg.answer(text, parse_mode="HTML")

# --- DONE ---
@dp.callback_query(F.data.startswith("done_"))
async def done(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("🔒 Только администратор", show_alert=True)
    eid = int(call.data.split("_")[1])

    with db_lock:
        cur.execute("SELECT subject, date FROM exams WHERE id=?", (eid,))
        row = cur.fetchone()
        cur.execute("UPDATE exams SET status=1 WHERE id=?", (eid,))
        conn.commit()

    await call.answer("✅ Отмечено как сдано!")
    await call.message.delete()

    if row:
        await notify_status_change(row[0], row[1], 1)

# --- FAIL ---
@dp.callback_query(F.data.startswith("fail_"))
async def fail(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("🔒 Только администратор", show_alert=True)
    eid = int(call.data.split("_")[1])
    await state.update_data(eid=eid)
    await call.message.answer("❌ Укажите причину несдачи:")
    await state.set_state(FailReason.reason)
    await call.answer()

@dp.message(FailReason.reason)
async def save_fail(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    reason = msg.text.strip()

    with db_lock:
        cur.execute("SELECT subject, date FROM exams WHERE id=?", (data["eid"],))
        row = cur.fetchone()
        cur.execute("UPDATE exams SET status=2, reason=? WHERE id=?", (reason, data["eid"]))
        conn.commit()

    await msg.answer("❌ Записано")
    await state.clear()

    if row:
        await notify_status_change(row[0], row[1], 2, reason)

# --- DELETE ---
@dp.callback_query(F.data.startswith("del_"))
async def delete(call: types.CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("🔒 Только администратор", show_alert=True)
    eid = int(call.data.split("_")[1])

    with db_lock:
        cur.execute("SELECT subject FROM exams WHERE id=?", (eid,))
        row = cur.fetchone()
        cur.execute("DELETE FROM exams WHERE id=?", (eid,))
        conn.commit()

    await call.answer("🗑 Удалено")
    await call.message.delete()

    if row:
        today_str = datetime.date.today().strftime("%d.%m.%Y")
        await broadcast(
            f"🗑 <b>ЭКЗАМЕН УДАЛЁН</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📖 Предмет: <b>{row[0]}</b>\n"
            f"🕐 {today_str}"
        )

# --- EDIT ---
@dp.callback_query(F.data.startswith("edit_"))
async def edit_start(call: types.CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        return await call.answer("🔒 Только администратор", show_alert=True)

    eid = int(call.data.split("_")[1])
    await state.update_data(eid=eid)

    with db_lock:
        cur.execute("SELECT subject, date FROM exams WHERE id=?", (eid,))
        row = cur.fetchone()

    await call.message.answer(
        f"✏️ Редактируем: <b>{row[0]}</b> ({row[1]})\nВведите новое название предмета:",
        parse_mode="HTML"
    )
    await state.set_state(EditExam.new_subject)
    await call.answer()

@dp.message(EditExam.new_subject)
async def edit_subject(msg: types.Message, state: FSMContext):
    new_subject = msg.text.strip()
    await state.update_data(new_subject=new_subject)

    # Сохраняем новое название сразу
    data = await state.get_data()
    with db_lock:
        cur.execute("UPDATE exams SET subject=? WHERE id=?", (new_subject, data["eid"]))
        conn.commit()

    await msg.answer("📅 Выберите новую дату или пропустите:", reply_markup=date_kb)
    await state.set_state(EditExam.new_date)

@dp.callback_query(F.data.startswith("date_"), EditExam.new_date)
async def edit_date_handler(call: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()

    if call.data == "date_manual":
        await call.message.answer("✏️ Введите дату (ДД.ММ.ГГГГ):")
        await call.answer()
        return

    if call.data == "date_skip":
        date_str = "Без даты"
    else:
        date_obj = get_date_from_callback(call.data)
        date_str = date_obj.strftime("%d.%m.%Y")

    with db_lock:
        cur.execute("UPDATE exams SET date=? WHERE id=?", (date_str, data["eid"]))
        conn.commit()

    subject = data.get("new_subject", "")
    await call.message.answer(f"✅ Изменения сохранены\n📖 <b>{subject}</b>\n📅 {date_str}", parse_mode="HTML")
    await state.clear()
    await call.answer()

@dp.message(EditExam.new_date)
async def edit_custom_date(msg: types.Message, state: FSMContext):
    text = msg.text.strip()
    if not validate_date(text):
        await msg.answer("❌ Неверный формат. Введите дату как ДД.ММ.ГГГГ")
        return
    data = await state.get_data()
    with db_lock:
        cur.execute("UPDATE exams SET date=? WHERE id=?", (text, data["eid"]))
        conn.commit()
    subject = data.get("new_subject", "")
    await msg.answer(f"✅ Изменения сохранены\n📖 <b>{subject}</b>\n📅 {text}", parse_mode="HTML")
    await state.clear()

# ================= MAIN =================
async def main():
    print("🤖 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())