from unittest.mock import MagicMock, patch

from app.services import oauth


@patch("app.services.oauth.Flow")
def test_build_auth_url_sets_scope_and_prompt(mock_flow_cls):
    mock_flow = MagicMock()
    mock_flow.authorization_url.return_value = ("https://accounts.google.com/fake?state=xyz", "xyz")
    mock_flow_cls.from_client_config.return_value = mock_flow

    url = oauth.build_auth_url(state="xyz")

    mock_flow.authorization_url.assert_called_once_with(
        access_type="offline",
        prompt="consent",
        state="xyz",
    )
    config_arg = mock_flow_cls.from_client_config.call_args
    assert "gmail.readonly" in config_arg.kwargs["scopes"][0]
    assert url == "https://accounts.google.com/fake?state=xyz"


@patch("app.services.oauth.httpx")
@patch("app.services.oauth.Flow")
def test_exchange_code_for_tokens_returns_parsed_fields(mock_flow_cls, mock_httpx):
    mock_flow = MagicMock()
    mock_creds = MagicMock()
    mock_creds.token = "at-new"
    mock_creds.refresh_token = "rt-new"
    mock_creds.expiry = None
    mock_flow.credentials = mock_creds
    mock_flow_cls.from_client_config.return_value = mock_flow

    mock_response = MagicMock()
    mock_response.json.return_value = {"email": "user@gmail.com"}
    mock_httpx.get.return_value = mock_response

    result = oauth.exchange_code_for_tokens("fake-code")

    mock_flow.fetch_token.assert_called_once_with(code="fake-code")
    assert result == {
        "email": "user@gmail.com",
        "access_token": "at-new",
        "refresh_token": "rt-new",
        "expires_at": None,
    }


@patch("app.services.oauth.Credentials")
def test_refresh_access_token_returns_unchanged_refresh_token(mock_creds_cls):
    mock_creds = MagicMock()
    mock_creds.token = "at-refreshed"
    mock_creds.refresh_token = "rt-old"  # Google did not rotate
    mock_creds.expiry = None
    mock_creds_cls.return_value = mock_creds

    result = oauth.refresh_access_token("rt-old")

    mock_creds.refresh.assert_called_once()
    assert result == {
        "access_token": "at-refreshed",
        "refresh_token": "rt-old",
        "expires_at": None,
    }


@patch("app.services.oauth.Credentials")
def test_refresh_access_token_returns_rotated_refresh_token(mock_creds_cls):
    mock_creds = MagicMock()
    mock_creds.token = "at-refreshed"
    mock_creds.refresh_token = "rt-rotated"  # Google rotated it
    mock_creds.expiry = None
    mock_creds_cls.return_value = mock_creds

    result = oauth.refresh_access_token("rt-old")

    assert result["refresh_token"] == "rt-rotated"
