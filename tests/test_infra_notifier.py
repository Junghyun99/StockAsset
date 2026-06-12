import pytest
from unittest.mock import patch, MagicMock 
from src.infra.notifier import SlackNotifier

@pytest.fixture
def mock_requests_post():
    with patch('src.infra.notifier.requests.post') as mock:
        yield mock


@pytest.fixture
def mock_logger():
    """가짜 로거 생성"""
    return MagicMock()


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


def test_slack_bot_token_threaded_reply(mock_requests_post, mock_logger):
    """[핵심] Bot Token + detail이면 부모 메시지 + 스레드 댓글로 2회 전송한다."""
    mock_requests_post.return_value.json.return_value = {"ok": True, "ts": "111.222"}

    notifier = SlackNotifier(
        webhook_url="https://hooks.slack.com/test",
        logger=mock_logger,
        bot_token="xoxb-token",
        channel_id="C123",
    )
    notifier.send_message("Summary", detail="captured log body")

    # chat.postMessage가 2회 호출 (부모 + 댓글)
    assert mock_requests_post.call_count == 2
    first_args, first_kwargs = mock_requests_post.call_args_list[0]
    second_args, second_kwargs = mock_requests_post.call_args_list[1]

    # 둘 다 Web API 엔드포인트로 전송, Bearer 인증 헤더 포함
    assert first_args[0] == "https://slack.com/api/chat.postMessage"
    assert "Bearer xoxb-token" in first_kwargs['headers']['Authorization']

    # 부모에는 thread_ts 없음, 댓글에는 thread_ts=부모 ts
    assert "thread_ts" not in first_kwargs['json']
    assert second_kwargs['json']['thread_ts'] == "111.222"
    assert "captured log body" in second_kwargs['json']['text']


def test_slack_bot_token_no_detail_single_call(mock_requests_post, mock_logger):
    """Bot Token이 있어도 detail이 없으면 부모 메시지 1회만 전송한다."""
    mock_requests_post.return_value.json.return_value = {"ok": True, "ts": "111.222"}

    notifier = SlackNotifier(
        webhook_url="https://hooks.slack.com/test",
        logger=mock_logger,
        bot_token="xoxb-token",
        channel_id="C123",
    )
    notifier.send_message("Summary")

    assert mock_requests_post.call_count == 1


def test_slack_api_failure_falls_back_to_webhook(mock_requests_post, mock_logger):
    """API가 ok=False를 반환하면 웹후크로 폴백하여 요약만(detail 없이) 전송한다."""
    # 1번째 호출(API): ok=False, 2번째 호출(webhook): status 200
    api_resp = MagicMock()
    api_resp.json.return_value = {"ok": False, "error": "channel_not_found"}
    webhook_resp = MagicMock()
    webhook_resp.status_code = 200
    mock_requests_post.side_effect = [api_resp, webhook_resp]

    notifier = SlackNotifier(
        webhook_url="https://hooks.slack.com/test",
        logger=mock_logger,
        bot_token="xoxb-token",
        channel_id="C123",
    )
    notifier.send_message("Summary", detail="should be dropped on fallback")

    # API 1회 + webhook 1회
    assert mock_requests_post.call_count == 2
    webhook_args, webhook_kwargs = mock_requests_post.call_args_list[1]
    assert webhook_args[0] == "https://hooks.slack.com/test"
    # 폴백은 요약만 전송 (text 키, detail은 미포함)
    assert webhook_kwargs['json'] == {"text": "🤖 *[SolidQuant]*\nSummary"}
    mock_logger.error.assert_called()


def test_slack_thread_failure_does_not_fallback(mock_requests_post, mock_logger):
    """[버그방지] 부모 메시지 성공 후 스레드 댓글 실패 시 웹후크로 폴백하지 않는다.

    폴백하면 동일 요약이 채널에 중복 전송되므로, 스레드 실패는 에러 로깅만 한다.
    """
    parent_resp = MagicMock()
    parent_resp.json.return_value = {"ok": True, "ts": "111.222"}  # 부모 성공
    thread_resp = MagicMock()
    thread_resp.json.return_value = {"ok": False, "error": "thread_broken"}  # 댓글 실패
    mock_requests_post.side_effect = [parent_resp, thread_resp]

    notifier = SlackNotifier(
        webhook_url="https://hooks.slack.com/test",
        logger=mock_logger,
        bot_token="xoxb-token",
        channel_id="C123",
    )
    notifier.send_message("Summary", detail="detail body")

    # 부모(API) + 스레드(API) = 2회. 웹후크(3번째 호출)는 발생하지 않아야 한다.
    assert mock_requests_post.call_count == 2
    for call in mock_requests_post.call_args_list:
        assert call.args[0] == "https://slack.com/api/chat.postMessage"
    # 스레드 실패는 에러 로깅으로만 남는다
    assert any(
        "Thread" in str(c.args[0]) for c in mock_logger.error.call_args_list
    )


def test_slack_webhook_fallback_summary_only(mock_requests_post, mock_logger):
    """Bot Token이 없으면 detail이 있어도 웹후크로 요약만 전송한다 (detail 생략)."""
    mock_requests_post.return_value.status_code = 200

    notifier = SlackNotifier(webhook_url="https://hooks.slack.com/test", logger=mock_logger)
    notifier.send_message("Summary", detail="this detail is dropped")

    mock_requests_post.assert_called_once()
    _, kwargs = mock_requests_post.call_args
    assert kwargs['json'] == {"text": "🤖 *[SolidQuant]*\nSummary"}
    assert "this detail is dropped" not in str(kwargs['json'])