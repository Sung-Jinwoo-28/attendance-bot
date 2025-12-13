import httpx
import json
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from apscheduler.schedulers.background import BackgroundScheduler

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

BOT_TOKEN = "8329574176:AAHVRhNgGjT5Z1ckbivE5r8e2H02e5TO6NA"
SHEETS_API_URL = "https://script.google.com/macros/s/AKfycbzLNfd_hoiFaEeEsQr2q5UBc1XXJ-iAAAu6PJA3JiwRwShjkxWDQ8Hda0SilDaUuYIN/exec"
ALERT_FILE = "alerts.json"


# ---------- HELPERS ----------

async def fetch_data():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        r = await client.get(SHEETS_API_URL, timeout=20.0)
        r.raise_for_status()
        return r.json()

def pct(p):
    return f"{p*100:.1f}%"


def load_alerts():
    if not os.path.exists(ALERT_FILE):
        return {}
    with open(ALERT_FILE, "r") as f:
        return json.load(f)



def save_alerts(data):
    with open(ALERT_FILE, "w") as f:
        json.dump(data, f)


def get_initials(name):
    # "Business Economics" -> "BE"
    parts = name.split()
    return "".join(p[0].upper() for p in parts if p)


def match_subject(query, rows):
    """
    Matches query against rows (subject names) using:
    1. Case-insensitive substring match
    2. Case-insensitive abbreviation match (initials)
    Returns list of matching rows.
    """
    query = query.strip().upper()
    matches = []
    
    for r in rows:
        subject = r[0]
        subject_upper = subject.upper()
        initials = get_initials(subject)
        
        # 1. Substring match (using original query logic)
        # We use 'in' for substring
        if query in subject_upper:
            matches.append(r)
            continue
            
        # 2. Initials match
        # Exact match of initials "BE" == "BE"
        if query == initials:
            matches.append(r)
            
    return matches


# ---------- DAILY SUMMARY ENGINE ----------

async def send_daily_summary(app, target_chat_id=None):
    """
    Sends summary.
    If target_chat_id is provided, sends ONLY to that chat (for testing).
    Otherwise, sends to all subscribed chats (scheduled job).
    """
    try:
        rows = await fetch_data()
    except Exception as e:
        logging.error(f"Failed to fetch data: {e}")
        if target_chat_id:
            await app.bot.send_message(target_chat_id, f"⚠️ Failed to fetch data: {e}")
        return

    alerts = load_alerts()
    # If this is a scheduled run, and no alerts are set, just return
    if target_chat_id is None and not alerts:
        return

    below85 = [r for r in rows if r[4] < 0.85]
    safe = [r for r in rows if r[4] >= 0.90]

    msg = "📅 *Daily Attendance Summary*\n\n"

    if below85:
        msg += "⚠️ *Below 85%*\n"
        for r in below85:
            msg += f"• {r[0]} ({pct(r[4])})\n"
    else:
        msg += "✅ All subjects above 85%\n"

    msg += "\n🟢 *Safe (≥90%)*\n"
    if safe:
        for r in safe:
            msg += f"• {r[0]} ({pct(r[4])})\n"
    else:
        msg += "• None\n"

    msg += "\n🎯 *Priority Today*\n"
    for r in sorted(rows, key=lambda x: x[4])[:3]:
        msg += f"• {r[0]} ({pct(r[4])})\n"

    # If manual test, send to requester
    if target_chat_id:
        await app.bot.send_message(
            chat_id=target_chat_id,
            text=msg,
            parse_mode="Markdown"
        )
    # Else, send to all subscribers
    else:
        for chat_id, enabled in alerts.items():
            if enabled:
                try:
                    await app.bot.send_message(
                        chat_id=int(chat_id),
                        text=msg,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logging.error(f"Failed to send to {chat_id}: {e}")


# ---------- LOGIC HELPERS ----------

async def get_summary_text():
    try:
        rows = await fetch_data()
    except Exception as e:
        return f"⚠️ Error fetching data: {e}"

    msg = "📊 *Attendance Summary*\n\n"
    for r in rows:
        msg += f"{r[0]} ({r[1]}): {r[4]*100:.1f}%\n"
    return msg

async def get_below85_text():
    try:
        rows = await fetch_data()
    except Exception as e:
        return f"⚠️ Error fetching data: {e}"

    bad = [r for r in rows if r[4] < 0.85]
    if not bad:
        return "✅ All subjects above 85%"

    msg = "⚠️ *Below 85%*\n\n"
    for r in bad:
        msg += f"{r[0]} ({r[1]}): {r[4]*100:.1f}%\n"
    return msg

# ---------- HANDLERS ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Menu", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🤖 *Attendance Bot Ready!*\nClick below to see options:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "main_menu":
        keyboard = [
            [InlineKeyboardButton("📊 Summary", callback_data="cmd_summary")],
            [InlineKeyboardButton("⚠️ Below 85%", callback_data="cmd_below85")],
            [InlineKeyboardButton("📝 Attendance Help", callback_data="help_attendance")],
            [InlineKeyboardButton("🛌 Bunk Help", callback_data="help_bunk")],
            [InlineKeyboardButton("🔔 Alerts Status", callback_data="cmd_alerts_status")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "📋 *Main Menu*\nSelect an option below:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

    elif query.data == "cmd_summary":
        text = await get_summary_text()
        await query.edit_message_text(text, parse_mode="Markdown")

    elif query.data == "cmd_below85":
        text = await get_below85_text()
        await query.edit_message_text(text, parse_mode="Markdown")

    elif query.data == "help_attendance":
        await query.edit_message_text("Usage:\n/attendance <subject>\n\nExample:\n/attendance python", parse_mode="Markdown")

    elif query.data == "help_bunk":
        await query.edit_message_text("Usage:\n/bunk <subject>\n\nExample:\n/bunk math", parse_mode="Markdown")

    elif query.data == "cmd_alerts_status":
        alerts = load_alerts()
        chat_id = str(update.effective_chat.id)
        status = alerts.get(chat_id, False)
        await query.edit_message_text(
            f"🔔 Daily alerts are *{'ON' if status else 'OFF'}*\nUse /alerts on|off to change.",
            parse_mode="Markdown"
        )

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await get_summary_text()
    await update.message.reply_text(text, parse_mode="Markdown")

async def below85(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = await get_below85_text()
    await update.message.reply_text(text, parse_mode="Markdown")

async def attendance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /attendance <subject>")
        return

    try:
        rows = await fetch_data()
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error fetching data: {e}")
        return

    query = " ".join(context.args)
    matches = match_subject(query, rows)

    if not matches:
        await update.message.reply_text("❌ Subject not found")
        return

    msg = ""
    for r in matches:
        msg += (
            f"{r[0]} ({r[1]})\n"
            f"Conducted: {r[2]}\n"
            f"Present: {r[3]}\n"
            f"Attendance: {r[4]*100:.1f}%\n"
            f"Status: {r[5]}\n\n"
        )
    await update.message.reply_text(msg)

async def bunk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /bunk <subject>")
        return

    try:
        rows = await fetch_data()
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error fetching data: {e}")
        return

    query = " ".join(context.args)
    matches = match_subject(query, rows)

    if not matches:
        await update.message.reply_text("❌ Subject not found")
        return

    msg = ""
    for r in matches:
        msg += f"{r[0]} ({r[1]})\n{r[6]}\n\n"

    await update.message.reply_text(msg)


# ---------- ALERT COMMAND ----------

async def alerts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    alerts = load_alerts()
    chat_id = str(update.effective_chat.id)

    if not context.args:
        status = alerts.get(chat_id, False)
        await update.message.reply_text(
            f"🔔 Daily alerts are *{'ON' if status else 'OFF'}*",
            parse_mode="Markdown"
        )
        return

    arg = context.args[0].lower()
    if arg == "on":
        alerts[chat_id] = True
        save_alerts(alerts)
        await update.message.reply_text("✅ Daily alerts ENABLED (9:00 AM)")
    elif arg == "off":
        alerts.pop(chat_id, None)
        save_alerts(alerts)
        await update.message.reply_text("❌ Daily alerts DISABLED")
    elif arg == "status":
        status = alerts.get(chat_id, False)
        await update.message.reply_text(
            f"🔔 Daily alerts are *{'ON' if status else 'OFF'}*",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("Usage: /alerts on | off | status")

async def test_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Generating preview...")
    # Pass the current app and the requester's chat ID
    await send_daily_summary(context.application, target_chat_id=update.effective_chat.id)


# ---------- MAIN ----------

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("below85", below85))
    app.add_handler(CommandHandler("attendance", attendance))
    app.add_handler(CommandHandler("bunk", bunk))
    app.add_handler(CommandHandler("alerts", alerts_cmd))
    app.add_handler(CommandHandler("testdaily", test_daily))

    # DAILY scheduler (9:00 AM)
    scheduler = BackgroundScheduler()
    # Note: send_daily_summary now requires 'app' as arg, and no target_chat_id for broadcast
    scheduler.add_job(
        lambda: app.create_task(send_daily_summary(app)),
        trigger="cron",
        hour=9,
        minute=0
    )
    scheduler.start()

    print("🤖 Attendance Bot V2 (Async + Daily) running...")
    app.run_polling()


if __name__ == "__main__":
    main()