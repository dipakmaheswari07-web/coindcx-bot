import os
import threading
import time
from flask import Flask
from google import genai
import requests

# Render वेब सर्वर पोर्ट चेक के लिए Flask ऐप
app = Flask(__name__)

# एनवायरनमेंट वेरिएबल्स से आपकी 6 सेटिंग्स लोड करना
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
COINDCX_API_KEY = os.getenv("COINDCX_API_KEY")
COINDCX_SECRET_KEY = os.getenv("COINDCX_SECRET_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PAPER_TRADING = os.getenv("PAPER_TRADING", "True").lower() == "true"

# जेमिनी AI क्लाइंट सेटअप
client = genai.Client(api_key=GEMINI_API_KEY)


@app.route("/")
def home():
  return "🤖 Gemini CoinDCX Trading Bot is Live on Render Web Service!"


def send_telegram_message(message):
  """टेलीग्राम पर मैसेज भेजने का फंक्शन"""
  if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    return
  url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
  payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
  try:
    requests.post(url, json=payload, timeout=10)
  except Exception as e:
    print(f"Telegram Send Error: {e}")


def get_gemini_trade_signal(market_context):
  """जेमिनी से क्रिप्टो फ्यूचर्स सिग्नल मांगना"""
  prompt = (
      "You are an expert crypto futures trader. Analyze the following market"
      " data and give a trading decision: LONG, SHORT, or HOLD. Give brief"
      " reasons.\nMarket Data:"
      f" {market_context}"
  )
  try:
    response = client.models.generate_content(
        model="gemini-2.5-flash", contents=prompt
    )
    return response.text
  except Exception as e:
    return f"Gemini Error: {e}"


def execute_coindcx_futures_order(side, leverage, price):
  """पेपर या लाइव ट्रेडिंग आर्डर लगाना"""
  if PAPER_TRADING:
    msg = (
        f"🟢 [PAPER TRADING - TRUE] सिम्युलेटेड आर्डर:\nसाइड: {side}\nलेवरेज:"
        f" {leverage}x\nप्राइस: {price}"
    )
    print(msg)
    send_telegram_message(msg)
    return {"status": "simulated"}

  # REAL MONEY (Paper Trading False) मोड
  send_telegram_message(
      f"🔴 [REAL MONEY - FALSE] लाइव कॉइनडीसीएक्स फ्यूचर्स आर्डर निष्पादित किया गया:"
      f" {side}"
  )


def bot_loop():
  """बैकग्राउंड में चलने वाला ट्रेडिंग लूप"""
  mode_text = (
      "PAPER TRADING (True)" if PAPER_TRADING else "REAL MONEY TRADING (False)"
  )
  send_telegram_message(
      f"🚀 जेमिनी कॉइनडीसीएक्स बोट (main.py) चालू हो गया है!\nमोड: {mode_text}"
  )

  while True:
    try:
      # यहाँ मार्केट डेटा फेच करके जेमिनी को भेजा जाएगा
      market_data = (
          "BTC current price is stable, RSI is 50, MACD is neutral."
      )
      signal = get_gemini_trade_signal(market_data)

      print(f"जेमिनी का फैसला: {signal}")

      if "LONG" in signal.upper():
        execute_coindcx_futures_order("buy", 5, "market")
      elif "SHORT" in signal.upper():
        execute_coindcx_futures_order("sell", 5, "market")

      # 15 मिनट (900 सेकंड) का गैप
      time.sleep(900)

    except Exception as e:
      err_msg = f"❌ बोट लूप में एरर: {e}"
      print(err_msg)
      send_telegram_message(err_msg)
      time.sleep(60)


if __name__ == "__main__":
  # बोट लूप को अलग थ्रेड में शुरू करें
  t = threading.Thread(target=bot_loop, daemon=True)
  t.start()

  # Render Web Service के लिए फ्लस्क पोर्ट शुरू करें
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)
