import pytest
from unittest.mock import patch, MagicMock 
from src.infra.notifier import TelegramNotifier, SlackNotifier

@pytest.fixture
def mock_requests_post():
    with patch('src.infra.notifier.requests.post') as mock:
        yield mock


@pytest.fixture
def mock_logger():
    """가짜 로거 생성"""
    return MagicMock()
def test_telegram_send_success(mock_requests_post):
    # 1. 정상 전송 테스트
    notifier = TelegramNotifier(token="1234:ABC", chat_id="999")
    notifier.send_message("Hello Test")
    
    # requests.post가 호출되었는지 확인
    mock_requests_post.assert_called_once()
    
    # 호출된 인자 검사 (URL, JSON 데이터)
    args, kwargs = mock_requests_post.call_args
    assert "1234:ABC" in notifier.base_url
    assert kwargs['json']['chat_id'] == "999"
    assert "Hello Test" in kwargs['json']['text']

def test_telegram_send_without_token(mock_requests_post):
    # 2. 토큰이 없는 경우 (설정 미비)
    notifier = TelegramNotifier(token="", chat_id="")
    notifier.send_message("Should not send")
    
    # 전송 시도조차 하지 않아야 함
    mock_requests_post.assert_not_called()

def test_telegram_network_error(mock_requests_post, capsys):
    # 3. 네트워크 에러 발생 시 프로그램이 죽지 않고 예외 처리하는지
    mock_requests_post.side_effect = Exception("Connection Refused")
    
    notifier = TelegramNotifier(token="123:ABC", chat_id="111")
    
    # 에러가 발생하더라도 catch 되어야 함 (여기서 raise되면 테스트 실패)
    notifier.send_message("Error Test")
    
    # 콘솔에 에러 로그가 찍혔는지 확인
    captured = capsys.readouterr()
    assert "[Telegram Error]" in captured.out


def test_slack_send_success(mock_requests_post,mock_logger):
    # 1. Mock 설정 (성공 응답 200)
    mock_requests_post.return_value.status_code = 200
    
    notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test",logger= mock_logger)
    notifier.send_message("Hello Slack")
    
    # 호출 검증
    mock_requests_post.assert_called_once()
    
    # 인자 검증 (json 파라미터 확인)
    args, kwargs = mock_requests_post.call_args
    assert args[0] == "https://hooks.slack.com/test"
    assert "Hello Slack" in kwargs['json']['text']

def test_slack_alert_channel_mention(mock_requests_post,mock_logger):
    # 2. Alert 전송 시 <!channel> 멘션 포함 확인
    mock_requests_post.return_value.status_code = 200
    
    notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test",logger=mock_logger)
    notifier.send_alert("Emergency!")
    
    _, kwargs = mock_requests_post.call_args
    assert "<!channel>" in kwargs['json']['text']

def test_slack_send_failure(mock_requests_post, mock_logger):
    # 3. 슬랙 서버 에러 (500) 처리 확인
    mock_requests_post.return_value.status_code = 500
    mock_requests_post.return_value.text = "Internal Server Error"
    
    notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test",logger=mock_logger)
    notifier.send_message("Test")
    
    mock_logger.error.assert_called() # error 메서드가 호출되었나?
    
    # 호출된 메시지 내용 확인
    args, _ = mock_logger.error.call_args
    assert "[Slack Error]" in args[0] # 메시지 내용에 에러 태그가 있는가?