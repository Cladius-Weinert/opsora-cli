"""Tests for opsora_memory module."""
import pytest
from pathlib import Path
import opsora_memory


@pytest.fixture
def mem_db(tmp_path, monkeypatch):
    """Isolate memory DB to a temporary path."""
    db_path = tmp_path / "memory.db"
    monkeypatch.setattr(opsora_memory, "DB_PATH", db_path)
    return db_path


def test_add_memory_normal(mem_db):
    result = opsora_memory.add_memory("Python is great", source="test")
    assert "Saved to memory" in result
    assert "Python is great" in result


def test_add_memory_empty(mem_db):
    result = opsora_memory.add_memory("", source="test")
    assert "empty" in result.lower() or "cannot be empty" in result


def test_add_memory_whitespace_only(mem_db):
    result = opsora_memory.add_memory("   \n\t  ", source="test")
    assert "empty" in result.lower() or "cannot be empty" in result


def test_add_memory_max_length(mem_db):
    long_text = "x" * 4097
    result = opsora_memory.add_memory(long_text, source="test")
    assert "too long" in result.lower() or "max" in result.lower()


def test_add_memory_exact_max_length(mem_db):
    text = "a" * 4096
    result = opsora_memory.add_memory(text, source="test")
    assert "Saved to memory" in result


def test_add_memory_strips_whitespace(mem_db):
    result = opsora_memory.add_memory("  hello world  ", source="test")
    assert "hello world" in result


def test_search_memory_single_keyword(mem_db):
    opsora_memory.add_memory("Python is a programming language")
    opsora_memory.add_memory("Java is another language")
    opsora_memory.add_memory("Rust is fast")
    
    results = opsora_memory.search_memory("python")
    assert len(results) == 1
    assert "Python" in results[0]["text"]


def test_search_memory_multi_keyword(mem_db):
    opsora_memory.add_memory("Python is great for data science")
    opsora_memory.add_memory("Java is used for enterprise")
    opsora_memory.add_memory("Python data analysis is popular")
    
    results = opsora_memory.search_memory("python data")
    # Should find entries matching either keyword, deduplicated
    assert len(results) >= 1
    texts = [r["text"] for r in results]
    assert any("Python" in t and "data" in t.lower() for t in texts)


def test_search_memory_no_results(mem_db):
    opsora_memory.add_memory("Python is great")
    results = opsora_memory.search_memory("golang")
    assert results == []


def test_search_memory_empty_query(mem_db):
    opsora_memory.add_memory("Python is great")
    results = opsora_memory.search_memory("")
    assert results == []


def test_search_memory_case_insensitive(mem_db):
    opsora_memory.add_memory("PyThOn is GREAT")
    results = opsora_memory.search_memory("python")
    assert len(results) == 1


def test_search_memory_deduplicates(mem_db):
    opsora_memory.add_memory("Python Python Python")
    results = opsora_memory.search_memory("python")
    assert len(results) == 1


def test_search_memory_respects_limit(mem_db):
    for i in range(10):
        opsora_memory.add_memory(f"Python fact number {i}")
    results = opsora_memory.search_memory("python", limit=3)
    assert len(results) <= 3


def test_memory_stats_empty(mem_db):
    stats = opsora_memory.memory_stats()
    assert stats["total_memories"] == 0
    assert stats["last_saved"] is None
    assert str(mem_db) in stats["db_path"]


def test_memory_stats_populated(mem_db):
    opsora_memory.add_memory("Memory 1")
    opsora_memory.add_memory("Memory 2")
    opsora_memory.add_memory("Memory 3")
    
    stats = opsora_memory.memory_stats()
    assert stats["total_memories"] == 3
    assert stats["last_saved"] is not None


def test_memory_stats_returns_db_path(mem_db):
    stats = opsora_memory.memory_stats()
    assert "db_path" in stats
    assert stats["db_path"].endswith("memory.db")
