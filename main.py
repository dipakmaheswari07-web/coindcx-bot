import os
import time
import requests
import google.generativeai as genai
from flask import Flask

# Environment Variables
COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY")
COINDCX_API_SECRET = os.environ.get("COINDCX_API_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Setup Gemini AI
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# Flask Web Server (Render ke liye)
app = Flask(__name__)

@app.route('/')
def home():
    return "Gemini Dynamic Trading Bot is Running!"

# Global Risk Parameters
DAILY_STOP_LOSS_PCT = 20.0 # 20% Daily Stop Loss

def send_telegram(msg):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})
        except Exception as e:
            print(f"Telegram error: {e}")

def analyze_and_trade():
    system_prompt = """
    You are an autonomous top-tier Crypto Futures Trader with access to all crypto futures pairs.
    Rules:
    1. Maximum daily stop loss is 20%. Protect capital at all costs.
    2. ALWAYS prioritize the lowest possible leverage (1x to 3x) for all setups.
    3. Use high leverage (up to 100x) ONLY as a fallback when an exceptional high-conviction trade (e.g., SOL) cannot meet minimum order requirements with low leverage due to limited margin.
    4. You have full authority to BUY, SELL, or HOLD on any crypto futures coin.
    """
    print("AI scanning all crypto futures with dynamic leverage & 20% stop-loss rules...")
    # Trading analysis logic executes here

if __name__ == "__main__":
    import threading
    def loop():
        while True:
            try:
                analyze_and_trade()
            except Exception as e:
                print(f"Execution Error: {e}")
            time.sleep(300)

    t = threading.Thread(target=loop)
    t.daemon = True
    t.start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
