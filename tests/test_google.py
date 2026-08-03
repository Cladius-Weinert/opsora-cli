"""Comprehensive tests for opsora_google.py Google OAuth tools."""
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import json
import time

# Add cmd directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "opsora_cmd"))

import opsora_google


class TestConstants:
    """Tests for module constants."""

    def test_config_dir(self):
        assert opsora_google.CONFIG_DIR == Path("/root/.google_auth")

    def test_tokens_dir(self):
        assert opsora_google.TOKENS_DIR == Path("/root/.google_auth/tokens")

    def test_client_creds(self):
        assert opsora_google.CLIENT_CREDS == Path("/root/.google_auth/client_creds.json")

    def test_accounts_list(self):
        assert len(opsora_google.ACCOUNTS) == 4
        assert "jalankecil351@gmail.com" in opsora_google.ACCOUNTS
        assert "cladiusweinert05@gmail.com" in opsora_google.ACCOUNTS
        assert "nurma67066@gmail.com" in opsora_google.ACCOUNTS
        assert "cloudbitget@gmail.com" in opsora_google.ACCOUNTS


class TestLoadClientCreds:
    """Tests for _load_client_creds function."""

    def test_load_creds_success(self):
        """Test loading client credentials successfully."""
        creds = {"client_id": "test-id", "client_secret": "test-secret"}
        with patch('pathlib.Path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=json.dumps(creds))):
                client_id, client_secret = opsora_google._load_client_creds()
                assert client_id == "test-id"
                assert client_secret == "test-secret"

    def test_load_creds_file_not_found(self):
        """Test loading when file doesn't exist."""
        with patch('pathlib.Path.exists', return_value=False):
            client_id, client_secret = opsora_google._load_client_creds()
            assert client_id == ""
            assert client_secret == ""

    def test_load_creds_invalid_json(self):
        """Test loading invalid JSON."""
        with patch('pathlib.Path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data="not json")):
                client_id, client_secret = opsora_google._load_client_creds()
                assert client_id == ""
                assert client_secret == ""


class TestLoadTokens:
    """Tests for _load_tokens function."""

    def test_load_tokens_success(self):
        """Test loading tokens successfully."""
        tokens = {"access_token": "token123", "refresh_token": "refresh123", "expires_at": 9999999999}
        with patch('pathlib.Path.exists', return_value=True):
            with patch('builtins.open', mock_open(read_data=json.dumps(tokens))):
                result = opsora_google._load_tokens("test@gmail.com")
                assert result == tokens

    def test_load_tokens_not_found(self):
        """Test loading when token file doesn't exist."""
        with patch('pathlib.Path.exists', return_value=False):
            result = opsora_google._load_tokens("test@gmail.com")
            assert result is None


class TestRefreshAccessToken:
    """Tests for _refresh_access_token function."""

    @patch('urllib.request.urlopen')
    def test_refresh_success(self, mock_urlopen):
        """Test successful token refresh."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "access_token": "new-access-token",
            "expires_in": 3600
        }).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        new_token = opsora_google._refresh_access_token("client-id", "client-secret", "refresh-token")

        assert new_token == "new-access-token"
        mock_urlopen.assert_called_once()

    @patch('urllib.request.urlopen')
    def test_refresh_failure(self, mock_urlopen):
        """Test token refresh failure."""
        mock_urlopen.side_effect = Exception("Network error")

        new_token = opsora_google._refresh_access_token("client-id", "client-secret", "refresh-token")

        assert new_token is None


class TestGetValidToken:
    """Tests for _get_valid_token function."""

    def test_valid_token_not_expired(self):
        """Test getting valid token that hasn't expired."""
        tokens = {
            "access_token": "valid-token",
            "refresh_token": "refresh-token",
            "expires_at": time.time() + 3600  # 1 hour from now
        }
        with patch('opsora_google._load_tokens', return_value=tokens):
            with patch('opsora_google._load_client_creds', return_value=("id", "secret")):
                token = opsora_google._get_valid_token("test@gmail.com")
                assert token == "valid-token"

    def test_expired_token_refreshes(self):
        """Test expired token gets refreshed."""
        tokens = {
            "access_token": "old-token",
            "refresh_token": "refresh-token",
            "expires_at": time.time() - 100  # Expired
        }
        with patch('opsora_google._load_tokens', return_value=tokens):
            with patch('opsora_google._load_client_creds', return_value=("id", "secret")):
                with patch('opsora_google._refresh_access_token', return_value="new-token"):
                    with patch('pathlib.Path.write_text') as mock_write:
                        token = opsora_google._get_valid_token("test@gmail.com")
                        assert token == "new-token"
                        # Should save updated tokens
                        mock_write.assert_called_once()

    def test_expired_no_refresh_token(self):
        """Test expired token with no refresh token."""
        tokens = {
            "access_token": "old-token",
            "refresh_token": None,
            "expires_at": time.time() - 100
        }
        with patch('opsora_google._load_tokens', return_value=tokens):
            with patch('opsora_google._load_client_creds', return_value=("id", "secret")):
                token = opsora_google._get_valid_token("test@gmail.com")
                assert token is None

    def test_no_client_creds(self):
        """Test when client credentials not available."""
        with patch('opsora_google._load_tokens', return_value={"access_token": "token"}):
            with patch('opsora_google._load_client_creds', return_value=("", "")):
                token = opsora_google._get_valid_token("test@gmail.com")
                assert token is None

    def test_no_tokens_file(self):
        """Test when tokens file doesn't exist."""
        with patch('opsora_google._load_tokens', return_value=None):
            token = opsora_google._get_valid_token("test@gmail.com")
            assert token is None


class TestGoogleGetPost:
    """Tests for _google_get and _google_post functions."""

    @patch('urllib.request.urlopen')
    def test_google_get_success(self, mock_urlopen):
        """Test successful GET request."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"data": "test"}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = opsora_google._google_get("valid-token", "https://api.example.com/test")

        assert result == {"data": "test"}

    @patch('urllib.request.urlopen')
    def test_google_post_success(self, mock_urlopen):
        """Test successful POST request."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"result": "ok"}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_response

        result = opsora_google._google_post("valid-token", "https://api.example.com/test", {"key": "value"})

        assert result == {"result": "ok"}

    @patch('urllib.request.urlopen')
    def test_google_get_failure(self, mock_urlopen):
        """Test GET request failure."""
        mock_urlopen.side_effect = Exception("Network error")

        with pytest.raises(Exception):
            opsora_google._google_get("valid-token", "https://api.example.com/test")


class TestGmailList:
    """Tests for gmail_list function."""

    @patch('opsora_google._get_valid_token', return_value="valid-token")
    @patch('opsora_google._google_get')
    def test_gmail_list_success(self, mock_get, mock_token):
        """Test successful Gmail listing."""
        # First call: message list
        # Second call: message details for each message
        mock_get.side_effect = [
            {"messages": [{"id": "msg1"}, {"id": "msg2"}]},
            {"payload": {"headers": [{"name": "Subject", "value": "Test 1"}, {"name": "From", "value": "a@b.com"}, {"name": "Date", "value": "today"}]}, "snippet": "Snippet 1"},
            {"payload": {"headers": [{"name": "Subject", "value": "Test 2"}, {"name": "From", "value": "c@d.com"}, {"name": "Date", "value": "yesterday"}]}, "snippet": "Snippet 2"},
        ]

        result = opsora_google.gmail_list("test@gmail.com", max_results=2)

        assert "test@gmail.com" in result
        assert "Test 1" in result
        assert "Test 2" in result
        assert "a@b.com" in result

    @patch('opsora_google._get_valid_token', return_value=None)
    def test_gmail_list_invalid_token(self, mock_token):
        """Test Gmail list with invalid token."""
        result = opsora_google.gmail_list("test@gmail.com")
        assert "Token OAuth" in result or "tidak valid" in result

    def test_gmail_list_unknown_account(self):
        """Test Gmail list with unknown account."""
        result = opsora_google.gmail_list("unknown@gmail.com")
        assert "tidak dikenal" in result

    @patch('opsora_google._get_valid_token', return_value="valid-token")
    @patch('opsora_google._google_get')
    def test_gmail_list_empty(self, mock_get, mock_token):
        """Test Gmail list with empty inbox."""
        mock_get.return_value = {"messages": []}

        result = opsora_google.gmail_list("test@gmail.com")
        assert "Tidak ada email" in result


class TestGmailUnread:
    """Tests for gmail_unread function."""

    @patch('opsora_google._get_valid_token', return_value="valid-token")
    @patch('opsora_google._google_get')
    def test_gmail_unread_single_account(self, mock_get, mock_token):
        """Test unread count for single account."""
        mock_get.return_value = {"resultSizeEstimate": 5}

        result = opsora_google.gmail_unread("test@gmail.com")

        assert "test@gmail.com" in result
        assert "5" in result

    @patch('opsora_google._get_valid_token', return_value="valid-token")
    @patch('opsora_google._google_get')
    def test_gmail_unread_all_accounts(self, mock_get, mock_token):
        """Test unread count for all accounts."""
        mock_get.return_value = {"resultSizeEstimate": 3}

        result = opsora_google.gmail_unread("")

        # Should check all 4 accounts
        assert mock_get.call_count == 4

    def test_gmail_unread_unknown_account(self):
        """Test unread with unknown account."""
        result = opsora_google.gmail_unread("unknown@gmail.com")
        assert "tidak dikenal" in result


class TestGmailSearch:
    """Tests for gmail_search function."""

    @patch('opsora_google._get_valid_token', return_value="valid-token")
    @patch('opsora_google._google_get')
    def test_gmail_search_success(self, mock_get, mock_token):
        """Test successful Gmail search."""
        mock_get.side_effect = [
            {"messages": [{"id": "msg1"}]},
            {"payload": {"headers": [{"name": "Subject", "value": "Search Result"}, {"name": "From", "value": "sender@test.com"}]}, "snippet": "Found it"}
        ]

        result = opsora_google.gmail_search("test query", "test@gmail.com")

        assert "test@gmail.com" in result
        assert "test query" in result
        assert "Search Result" in result

    @patch('opsora_google._get_valid_token', return_value=None)
    def test_gmail_search_invalid_token(self, mock_token):
        """Test search with invalid token."""
        result = opsora_google.gmail_search("query", "test@gmail.com")
        assert "Token OAuth" in result


class TestDriveList:
    """Tests for drive_list function."""

    @patch('opsora_google._get_valid_token', return_value="valid-token")
    @patch('opsora_google._google_get')
    def test_drive_list_success(self, mock_get, mock_token):
        """Test successful Drive listing."""
        mock_get.return_value = {
            "files": [
                {"name": "Doc1", "mimeType": "application/vnd.google-apps.document", "modifiedTime": "2024-01-15T10:00:00Z", "size": "1024"},
                {"name": "Sheet1", "mimeType": "application/vnd.google-apps.spreadsheet", "modifiedTime": "2024-01-14T10:00:00Z"},
                {"name": "Folder1", "mimeType": "application/vnd.google-apps.folder", "modifiedTime": "2024-01-13T10:00:00Z"}
            ]
        }

        result = opsora_google.drive_list("test@gmail.com")

        assert "test@gmail.com" in result
        assert "Doc1" in result
        assert "Sheet1" in result
        assert "Folder1" in result
        assert "📄" in result  # Document icon
        assert "📊" in result  # Spreadsheet icon
        assert "📁" in result  # Folder icon


class TestDriveSearch:
    """Tests for drive_search function."""

    @patch('opsora_google._get_valid_token', return_value="valid-token")
    @patch('opsora_google._google_get')
    def test_drive_search_success(self, mock_get, mock_token):
        """Test successful Drive search."""
        mock_get.return_value = {
            "files": [
                {"name": "Report.pdf", "modifiedTime": "2024-01-15T10:00:00Z"},
                {"name": "Report-final.docx", "modifiedTime": "2024-01-14T10:00:00Z"}
            ]
        }

        result = opsora_google.drive_search("Report", "test@gmail.com")

        assert "Report" in result
        assert "Report.pdf" in result
        assert "Report-final.docx" in result


class TestCalendarEvents:
    """Tests for calendar_events function."""

    @patch('opsora_google._get_valid_token', return_value="valid-token")
    @patch('opsora_google._google_get')
    @patch('time.strftime', return_value="2024-01-15T10:00:00Z")
    def test_calendar_events_success(self, mock_strftime, mock_get, mock_token):
        """Test successful Calendar events listing."""
        mock_get.return_value = {
            "items": [
                {"summary": "Meeting", "start": {"dateTime": "2024-01-15T14:00:00Z"}},
                {"summary": "Lunch", "start": {"dateTime": "2024-01-15T12:00:00Z"}}
            ]
        }

        result = opsora_google.calendar_events("test@gmail.com")

        assert "test@gmail.com" in result
        assert "Meeting" in result
        assert "Lunch" in result


class TestGoogleStatus:
    """Tests for google_status function."""

    @patch('opsora_google._get_valid_token', return_value="valid-token")
    @patch('opsora_google._google_get')
    def test_google_status_all_accounts(self, mock_get, mock_token):
        """Test status check for all accounts."""
        # Userinfo response
        mock_get.side_effect = [
            {"name": "Test User"},  # userinfo for account 1
            {},  # calendar check
            {},  # drive check
            {"name": "Test User 2"},  # userinfo for account 2
            {},  # calendar check
            {},  # drive check
            # ... repeats for all 4 accounts
        ]

        result = opsora_google.google_status("")

        assert "Google Account Status" in result
        assert "Test User" in result

    @patch('opsora_google._get_valid_token', return_value=None)
    def test_google_status_invalid_token(self, mock_token):
        """Test status with invalid token."""
        result = opsora_google.google_status("test@gmail.com")
        assert "Token tidak valid" in result


class TestAccountValidation:
    """Tests for account validation across functions."""

    @pytest.mark.parametrize("func", [
        "gmail_list", "gmail_unread", "gmail_search",
        "drive_list", "drive_search", "calendar_events", "google_status"
    ])
    def test_unknown_account_rejected(self, func):
        """Test that unknown accounts are rejected."""
        func_obj = getattr(opsora_google, func)
        if func in ("gmail_search", "drive_search"):
            result = func_obj("query", "unknown@gmail.com")
        elif func == "gmail_unread":
            result = func_obj("unknown@gmail.com")
        elif func == "google_status":
            result = func_obj("unknown@gmail.com")
        else:
            result = func_obj("unknown@gmail.com")
        assert "tidak dikenal" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])