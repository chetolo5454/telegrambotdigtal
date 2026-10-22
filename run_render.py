"""
Render Deployment Entrypoint for Digital Egypt Case Tracker Telegram Bot.
Starts a lightweight HTTP server on $PORT to satisfy Render's Web Service health check,
while running the Telegram bot 24/7.
"""

import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

# Ensure project root is in sys.path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from telegram_bot.bot import run_bot

PORT = int(os.environ.get("PORT", 10000))


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        response = {
            "status": "online",
            "service": "Digital Egypt Case Tracker Telegram Bot",
            "message": "البوت يعمل بنجاح على تليجرام ويمكنك التفاعل معه الآن."
        }
        self.wfile.write(json.dumps(response, ensure_ascii=False, indent=2).encode("utf-8"))

    def log_message(self, format, *args):
        # Suppress noisy health-check access logs
        return


def start_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
    print(f"[Render]: Health check server is listening on port {PORT}...")
    server.serve_forever()


if __name__ == "__main__":
    # Start HTTP server in a daemon thread so Render sees an active web service
    t = threading.Thread(target=start_health_server, daemon=True)
    t.start()

    # Run Telegram bot in the main thread
    run_bot()
