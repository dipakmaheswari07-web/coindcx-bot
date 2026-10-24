import os
import time
import threading
import requests
import telebot
from google import genai
from flask import Flask

app = Flask(__name__)

COINDCX_API_KEY = os.getenv("COINDCX_API_KEY", "")
COINDCX_SECRET_KEY = os.getenv("COINDCX_SECRET_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
PAPER_TRADING = os.getenv("PAPER_TRADING", "True").lower() == "true"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = genai.Client(api_key=GEMINI_API_KEY)

initial_day_balance = None
STOP_LOSS_PERCENTAGE = 20.0
trading_halted = False

def send_alert(message):
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
    except Exception as e:
        print(f"Telegram Error: {e}")

def get_coindcx_balance():
    if PAPER_TRADING:
        return 50000.0
    else:
        return 10000.0

def check_daily_stop_loss():
    global initial_day_balance, trading_halted
    current_balance = get_coindcx_balance()
    if initial_day_balance is None:
        initial_day_balance = current_balance
        mode = "📝 [PAPER TRADING]" if PAPER_TRADING else "🚨 [REAL MONEY LIVE TRADING]"
        send_alert(f"🚀 वेब बोट शुरू! मोड: {mode}\nशुरुआती बैलेंस: ₹{initial_day_balance}")
        return False

    loss_amount = initial_day_balance - current_balance
    loss_percentage = (loss_amount / initial_day_balance) * 100

    if loss_percentage >= STOP_LOSS_PERCENTAGE:
        trading_halted = True
        send_alert(f"🚨 **स्टॉप लॉस हिट!** नुकसान {loss_percentage:.2f}% (≥20%)। ट्रेडिंग बंद।")
        return True
    return False

def get_gemini_insight(prompt):
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text
    except Exception as e:
        return f"Gemini Error: {e}"

def bot_worker():
    global trading_halted
    send_alert("🤖 वेब ट्रेडिंग बोट लाइव हो गया है।")
    while True:
        if trading_halted:
            time.sleep(3600)
            continue
        if check_daily_stop_loss():
            continue

        insight = get_gemini_insight("Analyze crypto market sentiment briefly.")
        print(f"Gemini: {insight}")

        if PAPER_TRADING:
            print("--- [Paper Trading Mode Active] ---")
        else:
            print("--- [Real Money Live Trading Active] ---")

        time.sleep(1800)

@app.route("/")
def home():
    return "Trading Bot Web Server is running live!"

if __name__ == "__main__":
    # बोट लूप को बैकग्राउंड धागे (Thread) में शुरू करें
    t = threading.Thread(target=bot_worker)
    t.daemon = True
    t.start()

    # रेंडर के दिए गए पोर्ट पर वेब सर्वर चलाएं
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
