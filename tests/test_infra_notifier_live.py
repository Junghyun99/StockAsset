import os
import pytest
from unittest.mock import MagicMock 
from dotenv import load_dotenv
from src.infra.notifier import SlackNotifier


@pytest.fixture
def mock_logger():
    """가짜 로거 생성"""
    return MagicMock()

# .env 로드
load_dotenv()
REAL_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

# 실제 URL이 없으면(GitHub Actions 등) 이 테스트는 건너뜀(Skip)
@pytest.mark.skipif(not REAL_WEBHOOK_URL, reason="No real Slack URL found")
def test_slack_live_integration(mock_logger):
    """
    [통합] 실제로 슬랙 서버에 요청을 보내고 200 OK를 받는지 확인
    주의: 실제 슬랙 채널에 메시지가 전송됩니다.
    """
    notifier = SlackNotifier(REAL_WEBHOOK_URL,mock_logger)

    # send_message 내부는 리턴값이 없으므로, 
    # _send 메서드를 직접 호출하거나 예외가 발생하지 않음을 검증
    try:
        notifier.send_message("🧪 Pytest Live Integration Test!!")
    except Exception as e:
        pytest.fail(f"Live Slack notification failed: {e}")

# tests/test_infra_notifier_live.py (기존 내용 아래에 추가)

@pytest.mark.skipif(not REAL_WEBHOOK_URL, reason="No real Slack URL found")
def test_slack_live_alert_mention(mock_logger):
    """
    [Live] send_alert가 실제로 채널 전체(channel)를 멘션하는지 확인
    주의: 이 테스트는 채널에 있는 모든 사람에게 알림이 갑니다.
    """
    notifier = SlackNotifier(REAL_WEBHOOK_URL,mock_logger)
    try:
        notifier.send_alert("🚨 [LiveTest] 긴급 알림 테스트입니다. (채널 멘션 확인용)")
    except Exception as e:
        pytest.fail(f"Live Alert failed: {e}")

@pytest.mark.skipif(not REAL_WEBHOOK_URL, reason="No real Slack URL found")
def test_slack_live_rich_format(mock_logger):
    """
    [Live] 마크다운, 이모지, 줄바꿈이 슬랙에서 예쁘게 나오는지 확인
    """
    notifier = SlackNotifier(REAL_WEBHOOK_URL,mock_logger)
    
    # 실제 리포트와 유사한 복잡한 메시지 구성
    rich_message = (
        "📊 *Daily Rebalancing Report*\n"
        "--------------------------------\n"
        "• *Date*: 2024-05-25\n"
        "• *Regime*: `Bull Market` 🐂\n"
        "• *Profit*: +1.5% 📈\n"
        "• *Action*: Rebalanced (Buy `SPY`, Sell `SHV`)"
    )
    
    try:
        notifier.send_message(rich_message)
    except Exception as e:
        pytest.fail(f"Live Rich Text failed: {e}")