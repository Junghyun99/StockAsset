# src/infra/notifier.py
import requests
from typing import Optional
from src.core.interfaces import INotifier

class SlackNotifier(INotifier):
    """슬랙 알림. 요약(부모 메시지) + 상세 로그(스레드 댓글) 2단 구조.

    Bot Token이 설정되어 있으면 Web API(chat.postMessage)로 요약을 보내고,
    응답의 ts를 thread_ts로 사용해 상세 로그를 진짜 스레드 댓글로 첨부한다.
    Token이 없거나 API 호출이 실패하면 기존 Webhook 방식으로 요약만 전송한다
    (폴백 시 상세 로그는 생략).
    """

    def __init__(self, webhook_url: str, logger, bot_token: str = "", channel_id: str = ""):
        self.webhook_url = webhook_url
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.logger = logger

    def send_message(self, message: str, detail: Optional[str] = None) -> None:
        # 일반 메시지
        self._send_formatted(f"🤖 *[SolidQuant]*\n{message}", detail)

    def send_alert(self, message: str, detail: Optional[str] = None) -> None:
        # 긴급 알림 (channel 전체 호출)
        self._send_formatted(f"🚨 *[WARNING]* <!channel>\n{message}", detail)

    def _send_formatted(self, summary: str, detail: Optional[str] = None):
        # 1. Bot Token 방식 (스레드 댓글 지원) 우선 시도
        if self.bot_token and self.channel_id:
            try:
                parent_ts = self._send_via_api(self.channel_id, summary)
            except Exception as e:
                self.logger.error(f"[Slack API Error] Failed: {e}")
                # 부모 메시지 전송 자체가 실패한 경우에만 웹후크로 폴백 (요약만 전송)
            else:
                # 부모 메시지는 이미 전송 완료. 스레드 댓글 실패는 폴백하지 않는다
                # (폴백 시 동일 요약이 채널에 중복 전송되는 것을 방지).
                if parent_ts and detail:
                    try:
                        self._send_via_api(
                            self.channel_id, f"```\n{detail}\n```", thread_ts=parent_ts
                        )
                    except Exception as thread_err:
                        self.logger.error(
                            f"[Slack API Thread Error] Failed to send thread: {thread_err}"
                        )
                return

        # 2. 웹후크 폴백 — 요약만 전송 (상세 로그 생략)
        self._send_via_webhook({"text": summary})

    def _send_via_api(self, channel: str, text: str, thread_ts: Optional[str] = None) -> Optional[str]:
        """Slack Web API (chat.postMessage)로 메시지를 전송하고 ts를 반환한다."""
        url = "https://slack.com/api/chat.postMessage"
        headers = {
            "Authorization": f"Bearer {self.bot_token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {"channel": channel, "text": text}
        if thread_ts:
            payload["thread_ts"] = thread_ts

        response = requests.post(url, json=payload, headers=headers, timeout=5)
        res_json = response.json()
        if not res_json.get("ok"):
            error_msg = res_json.get("error", "unknown error")
            raise Exception(f"Slack API error: {error_msg}")
        return res_json.get("ts")

    def _send_via_webhook(self, payload: dict):
        if not self.webhook_url:
            # URL이 없으면(테스트 환경 등) 콘솔에만 출력
            self.logger.info(f"[Slack Mock] {payload}")
            return

        try:
            # 슬랙 Webhook은 JSON Payload를 사용
            response = requests.post(
                self.webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=5,
            )

            if response.status_code != 200:
                # [핵심] 파일에 기록 남기기
                self.logger.error(
                    f"[Slack Error] Status: {response.status_code}, Body: {response.text}"
                )
        except Exception as e:
            # [핵심] 파일에 기록 남기기
            self.logger.error(f"[Slack Error] Connection failed: {e}")
