import os
import time
import requests
import google.generativeai as genai
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# Environment Variables
COINDCX_API_KEY = os.environ.get("COINDCX_API_KEY")
COINDCX_API_SECRET = os.environ.get("COINDCX_API_SECRET")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Setup Gemini AI with Gemini 3.8 Flash
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-3.8-flash")

# Simple HTTP Server for Render Health Check
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"Gemini Dynamic Trading Bot with 20% Stop-Loss is Running!")

    def do_HEAD(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server_address = ('', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"Web server running on port {port}")
    httpd.serve_forever()

# Trading Logic Rules
DAILY_STOP_LOSS_PCT = 20.0

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
    3. Use high leverage (up to 100x) ONLY as a fallback when an exceptional high-conviction trade cannot meet minimum order requirements with low leverage due to limited margin.
    4. You have full authority to BUY, SELL, or HOLD on any crypto futures coin.
    """
    print("AI scanning all crypto futures with dynamic leverage & 20% stop-loss rules...")

if __name__ == "__main__":
    # Web server in background thread
    web_thread = threading.Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()

    # Main Trading Loop
    while True:
        try:
            analyze_and_trade()
        except Exception as e:
            print(f"Execution Error: {e}")
        time.sleep(300)
