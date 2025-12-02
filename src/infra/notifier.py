# src/infra/notifier.py
import requests
from src.core.interfaces import INotifier

class TelegramNotifier(INotifier):
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}/sendMessage"

    def send_message(self, message: str) -> None:
        self._send(f"🤖 [SolidQuant]\n{message}")

    def send_alert(self, message: str) -> None:
        self._send(f"🚨 [WARNING]\n{message}")

    def _send(self, text: str):
        if not self.token or not self.chat_id:
            print(f"[Telegram Mock] {text}") # 설정 없으면 콘솔 출력
            return

        try:
            payload = {"chat_id": self.chat_id, "text": text}
            requests.post(self.base_url, json=payload, timeout=5)
        except Exception as e:
            print(f"[Telegram Error] Failed to send: {e}")