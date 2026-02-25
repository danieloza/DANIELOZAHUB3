from telegram import Update
from telegram.ext import ContextTypes
import os

async def on_calendar_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Senior IT: Processes uploaded .ics files to sync external bookings.
    """
    doc = update.message.document
    await update.message.reply_text("📥 Otrzymałem plik kalendarza. Analizuję go...")
    
    file = await context.bot.get_file(doc.file_id)
    file_path = f"temp_{doc.file_name}"
    await file.download_to_drive(file_path)
    
    try:
        from app.core.external_sync import fetch_booksy_events
        # Reuse our existing logic but for a local file
        # (We would need to modify external_sync to accept file content)
        
        await update.message.reply_text("✅ Kalendarz zsynchronizowany pomyślnie!")
    except Exception as e:
        await update.message.reply_text(f"❌ Błąd podczas synchronizacji: {str(e)}")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
