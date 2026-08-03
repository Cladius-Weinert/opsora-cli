"""Tests for opsora_session module."""
import pytest
from pathlib import Path
import opsora_session


@pytest.fixture
def sess_db(tmp_path, monkeypatch):
    """Isolate session DB to a temporary path."""
    db_path = tmp_path / "sessions.db"
    monkeypatch.setattr(opsora_session, "DB_PATH", db_path)
    return db_path


def _sample_messages():
    return [
        {"role": "user", "content": "Hello world"},
        {"role": "assistant", "content": "Hi there!"},
    ]


def test_generate_id_rapid_no_duplicates():
    """10,000 ids generated back-to-back must not collide."""
    ids = [opsora_session._generate_id() for _ in range(10_000)]
    assert len(set(ids)) == 10_000


def test_generate_id_format_is_12_char_lowercase_hex():
    """Consumers (sessions.db rows, opsora_v2 display) expect 12-char hex."""
    import re
    for _ in range(100):
        assert re.fullmatch(r"[0-9a-f]{12}", opsora_session._generate_id())


def test_save_session_new(sess_db):
    sid = opsora_session._generate_id()
    result = opsora_session.save_session(
        session_id=sid,
        title="Test Session",
        provider="alibaba",
        model="qwen-plus",
        approval_mode="full-auto",
        messages=_sample_messages(),
    )
    assert result == sid


def test_save_session_update_existing(sess_db):
    sid = opsora_session._generate_id()
    msgs1 = [{"role": "user", "content": "First message"}]
    opsora_session.save_session(sid, "Original", "alibaba", "qwen-plus", "full-auto", msgs1)
    
    msgs2 = msgs1 + [{"role": "assistant", "content": "Reply"}]
    result = opsora_session.save_session(sid, "Updated", "alibaba", "qwen-plus", "full-auto", msgs2)
    assert result == sid
    
    loaded = opsora_session.load_session(sid)
    assert loaded.title == "Updated"
    assert len(loaded.messages) == 2


def test_save_session_empty_id_raises(sess_db):
    with pytest.raises(ValueError):
        opsora_session.save_session("", "Title", "alibaba", "qwen-plus", "full-auto", [])


def test_save_session_invalid_messages_type(sess_db):
    with pytest.raises(TypeError):
        opsora_session.save_session("sid123", "Title", "alibaba", "qwen-plus", "full-auto", "not a list")


def test_load_session_existing(sess_db):
    sid = opsora_session._generate_id()
    msgs = _sample_messages()
    opsora_session.save_session(sid, "Test", "alibaba", "qwen-plus", "full-auto", msgs)
    
    loaded = opsora_session.load_session(sid)
    assert loaded is not None
    assert loaded.id == sid
    assert loaded.title == "Test"
    assert loaded.provider == "alibaba"
    assert loaded.model == "qwen-plus"
    assert loaded.approval_mode == "full-auto"
    assert len(loaded.messages) == 2


def test_load_session_non_existing(sess_db):
    loaded = opsora_session.load_session("nonexistent-id")
    assert loaded is None


def test_load_session_with_tool_calls(sess_db):
    sid = opsora_session._generate_id()
    msgs = [
        {"role": "user", "content": "Read file"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "content": "file content", "tool_call_id": "call_1", "name": "read_file"},
    ]
    opsora_session.save_session(sid, "Tool Test", "alibaba", "qwen-plus", "full-auto", msgs)
    
    loaded = opsora_session.load_session(sid)
    assert len(loaded.messages) == 3
    assert loaded.messages[1]["tool_calls"][0]["function"]["name"] == "read_file"
    assert loaded.messages[2]["tool_call_id"] == "call_1"


def test_list_sessions_empty(sess_db):
    sessions = opsora_session.list_sessions()
    assert sessions == []


def test_list_sessions_multiple(sess_db):
    for i in range(5):
        sid = f"sess_{i}"
        opsora_session.save_session(sid, f"Session {i}", "alibaba", "qwen-plus", "full-auto", [])
    
    sessions = opsora_session.list_sessions()
    assert len(sessions) == 5


def test_list_sessions_ordering(sess_db):
    import time
    for i in range(3):
        sid = f"sess_{i}"
        opsora_session.save_session(sid, f"Session {i}", "alibaba", "qwen-plus", "full-auto", [])
        time.sleep(0.05)  # Ensure different updated_at
    
    sessions = opsora_session.list_sessions()
    # Most recently updated first
    assert sessions[0]["id"] == "sess_2"
    assert sessions[-1]["id"] == "sess_0"


def test_list_sessions_respects_limit(sess_db):
    for i in range(10):
        opsora_session.save_session(f"s{i}", f"S{i}", "alibaba", "qwen-plus", "full-auto", [])
    
    sessions = opsora_session.list_sessions(limit=5)
    assert len(sessions) == 5


def test_delete_session_existing(sess_db):
    sid = opsora_session._generate_id()
    opsora_session.save_session(sid, "Test", "alibaba", "qwen-plus", "full-auto", _sample_messages())
    
    result = opsora_session.delete_session(sid)
    assert result is True
    assert opsora_session.load_session(sid) is None


def test_delete_session_non_existing(sess_db):
    result = opsora_session.delete_session("does-not-exist")
    assert result is False


def test_delete_session_removes_messages(sess_db):
    sid = opsora_session._generate_id()
    opsora_session.save_session(sid, "Test", "alibaba", "qwen-plus", "full-auto", _sample_messages())
    opsora_session.delete_session(sid)
    
    # Verify messages are gone too
    loaded = opsora_session.load_session(sid)
    assert loaded is None


def test_search_sessions_by_title(sess_db):
    # search_sessions joins messages, so sessions need at least one message
    msgs = [{"role": "user", "content": "hello"}]
    opsora_session.save_session("s1", "Python tutorial", "alibaba", "qwen-plus", "full-auto", msgs)
    opsora_session.save_session("s2", "Java basics", "alibaba", "qwen-plus", "full-auto", msgs)
    
    results = opsora_session.search_sessions("python")
    assert len(results) == 1
    assert results[0]["title"] == "Python tutorial"


def test_search_sessions_by_message_content(sess_db):
    msgs1 = [{"role": "user", "content": "How to use decorators in Python?"}]
    msgs2 = [{"role": "user", "content": "Java generics question"}]
    
    opsora_session.save_session("s1", "Session 1", "alibaba", "qwen-plus", "full-auto", msgs1)
    opsora_session.save_session("s2", "Session 2", "alibaba", "qwen-plus", "full-auto", msgs2)
    
    results = opsora_session.search_sessions("decorators")
    assert len(results) == 1
    assert results[0]["id"] == "s1"


def test_search_sessions_case_insensitive(sess_db):
    msgs = [{"role": "user", "content": "HELLO WORLD"}]
    opsora_session.save_session("s1", "Test", "alibaba", "qwen-plus", "full-auto", msgs)
    
    results = opsora_session.search_sessions("hello")
    assert len(results) == 1


def test_search_sessions_no_results(sess_db):
    opsora_session.save_session("s1", "Python", "alibaba", "qwen-plus", "full-auto", [])
    results = opsora_session.search_sessions("golang")
    assert results == []


def test_estimate_tokens():
    msgs = [
        {"role": "user", "content": "one two three"},
        {"role": "assistant", "content": "four five"},
    ]
    tokens = opsora_session._estimate_tokens(msgs)
    assert tokens == 5  # 3 + 2 words


def test_estimate_tokens_empty_content():
    msgs = [{"role": "user", "content": ""}, {"role": "assistant"}]
    tokens = opsora_session._estimate_tokens(msgs)
    assert tokens == 0
