import os
import pytest
from dotenv import load_dotenv
from src.infra.notifier import SlackNotifier

# .env 로드
load_dotenv()
REAL_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

# 실제 URL이 없으면(GitHub Actions 등) 이 테스트는 건너뜀(Skip)
@pytest.mark.skipif(not REAL_WEBHOOK_URL, reason="No real Slack URL found")
def test_slack_live_integration():
    """
    [통합] 실제로 슬랙 서버에 요청을 보내고 200 OK를 받는지 확인
    주의: 실제 슬랙 채널에 메시지가 전송됩니다.
    """
    notifier = SlackNotifier(REAL_WEBHOOK_URL)

    # send_message 내부는 리턴값이 없으므로, 
    # _send 메서드를 직접 호출하거나 예외가 발생하지 않음을 검증
    try:
        notifier.send_message("🧪 Pytest Live Integration Test")
    except Exception as e:
        pytest.fail(f"Live Slack notification failed: {e}")