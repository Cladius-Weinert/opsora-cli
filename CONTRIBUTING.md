# Contributing to Opsora CLI

> **Bahasa Indonesia + English**  
> Terima kasih atas minat Anda berkontribusi! Opsora adalah open source dan kami menyambut kontribusi segala jenis.

---

## 🚀 Getting Started | Memulai

### 1. Fork Repository

Fork repository di GitHub: https://github.com/opsora/opsora-cli/fork

### 2. Clone Fork Anda

```bash
git clone https://github.com/YOUR_USERNAME/opsora-cli.git
cd opsora-cli
```

### 3. Install Development Mode

```bash
pip install -e ".[dev]"
```

Ini menginstall dependencies + development tools (pytest, ruff, mypy).

### 4. Buat Feature Branch

```bash
git checkout -b feature/nama-fitur-anda
# atau
git checkout -b fix/nama-bug-yang-diperbaiki
```

---

## 📝 Development Guidelines | Pedoman Pengembangan

### Code Style

- Ikuti [PEP 8](https://peps.python.org/pep-0008/) conventions
- Gunakan **type hints** untuk function signatures
- Jaga functions kecil dan focused (single responsibility)
- Tulis **docstrings** untuk public functions (Google/NumPy style)

**Contoh:**

```python
def execute_tool(name: str, args: dict[str, Any]) -> str:
    """Execute a tool by name with given arguments.
    
    Args:
        name: Tool name (e.g., 'read_file', 'run_command')
        args: Tool arguments matching the tool's schema
        
    Returns:
        Tool output as string, or error message
        
    Raises:
        ValueError: If tool name is not recognized
    """
    ...
```

### Linting & Formatting

Kami menggunakan [Ruff](https://github.com/astral-sh/ruff) untuk linting dan formatting:

```bash
# Check linting
ruff check opsora_cmd/

# Auto-fix issues
ruff check opsora_cmd/ --fix

# Format code
ruff format opsora_cmd/

# Run both
ruff check opsora_cmd/ && ruff format opsora_cmd/
```

**Pre-commit hook** (opsional tapi direkomendasikan):

```bash
pip install pre-commit
pre-commit install
```

### Type Checking

```bash
mypy opsora_cmd/
```

### Testing

- Tulis tests untuk fitur baru dan bug fixes
- Jalankan test suite sebelum submit PR:

```bash
# All tests
pytest tests/

# Verbose
pytest tests/ -v

# With coverage
pytest tests/ --cov=opsora_cmd --cov-report=term-missing

# Specific test file
pytest tests/test_routing.py -v
```

**Test Structure:**
```
tests/
├── conftest.py              # Shared fixtures
├── test_compression.py      # Context compression tests
├── test_memory.py           # Memory persistence tests
├── test_routing.py          # Intent router tests
├── test_session.py          # Session save/load tests
├── test_tokenhub.py         # TokenHub provider tests
└── test_tools.py            # Tool execution tests
```

**Target Coverage:** Meaningful coverage > 100% line coverage.

---

## 📋 Commit Messages

Gunakan clear, descriptive commit messages mengikuti [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types:**
| Type | Description |
|---|---|
| `feat` | Fitur baru |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `refactor` | Code restructuring tanpa behavior change |
| `test` | Adding/updating tests |
| `chore` | Maintenance (deps, config, etc.) |
| `perf` | Performance improvement |
| `security` | Security fix |

**Examples:**

```bash
feat(routing): add vision intent classification for image prompts
fix(memory): handle sqlite locking on concurrent access
docs(readme): update provider table with TokenHub models
refactor(agent): extract verification logic to separate method
test(tools): add test for edit_file with non-existent file
chore(deps): update ruff to 0.5.0
```

---

## 🔀 Pull Requests

### PR Checklist

- [ ] **Focused scope** — satu fitur atau fix per PR
- [ ] **Tests pass** — `pytest tests/` green
- [ ] **Linting clean** — `ruff check opsora_cmd/` clean
- [ ] **Types clean** — `mypy opsora_cmd/` clean
- [ ] **Documentation updated** — README, ARCHITECTURE, atau file docs relevan
- [ ] **Clear description** — jelaskan *what* dan *why*

### PR Template

```markdown
## Description
Brief description of changes.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Unit tests added/updated
- [ ] Manual testing performed
- [ ] All existing tests pass

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex logic
- [ ] Documentation updated
- [ ] No breaking changes (or documented)
```

### Review Process

1. **Automated checks** — CI runs linting, tests, type checks
2. **Maintainer review** — Code review untuk correctness, style, architecture
3. **Feedback incorporation** — Address review comments
4. **Approval & merge** — Squash merge ke `main`

---

## 🔌 Adding a New Provider

Untuk menambah support provider AI baru:

### 1. Add Client Initialization (`opsora_v2.py`)

```python
def get_newprovider_client() -> Optional[OpenAI]:
    global _newprovider_client
    if _newprovider_client is None:
        key = os.environ.get("NEWPROVIDER_API_KEY")
        if key:
            _newprovider_client = OpenAI(
                api_key=key,
                base_url="https://api.newprovider.com/v1",
                timeout=DEFAULT_TIMEOUT
            )
    return _newprovider_client
```

### 2. Add to Provider Models

```python
PROVIDER_MODELS = {
    # ... existing
    "newprovider": "model-1,model-2,model-3",
}
```

### 3. Implement Invoke Function

```python
async def invoke_newprovider(
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    **kwargs
) -> Any:
    client = get_newprovider_client()
    if not client:
        raise RuntimeError("NewProvider not configured")
    return client.chat.completions.create(
        model=model,
        messages=messages,
        tools=tools,
        **kwargs
    )
```

### 4. Add Availability Check

```python
def is_provider_available(provider: str) -> bool:
    return {
        # ... existing
        "newprovider": get_newprovider_client() is not None,
    }.get(provider, False)
```

### 5. Update Model Tiers (if applicable)

```python
# Add to appropriate tier based on capabilities
POWER_MODELS.append(("newprovider", "model-1"))
CODING_MODELS.append(("newprovider", "model-2"))
```

### 6. Update Documentation

- `README.md` — Provider table
- `PROVIDERS.md` — Detailed config
- `ARCHITECTURE.md` — Provider layer diagram

---

## 🛠️ Adding a New Tool

### 1. Define Tool Schema

Tambahkan ke `SAFE_TOOLS` di `opsora_v2.py`:

```python
{"type": "function", "function": {
    "name": "my_new_tool",
    "description": "Clear description of what this tool does. USE WHEN...",
    "parameters": {
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "Description"},
            "param2": {"type": "integer", "description": "Description"}
        },
        "required": ["param1"]
    }
}},
```

### 2. Implement Execution Logic

Di `execute_tool()` function:

```python
if name == "my_new_tool":
    param1 = args.get("param1")
    param2 = args.get("param2", 10)
    
    # Validation
    if not param1:
        return "Error: param1 is required"
    
    # Execution
    try:
        result = do_something(param1, param2)
        return str(result)
    except Exception as e:
        return f"Error: {e}"
```

### 3. Add to Status Display

```python
def show_tools_status():
    # ... existing
    tools_list.append(("my_new_tool", "🔧 My New Tool", "Available"))
```

### 4. Write Tests

```python
# tests/test_tools.py
def test_my_new_tool():
    result = execute_tool("my_new_tool", {"param1": "test"})
    assert "expected output" in result
```

### 5. Security Review

- Path traversal protection?
- Sensitive file blocking?
- Input validation?
- Timeout handling?

---

## 🧪 Testing Guidelines

### Unit Tests

- Test satu function/class per test
- Mock external dependencies (API calls, file system, time)
- Use descriptive test names: `test_<function>_<scenario>_<expected>`

```python
def test_auto_select_model_code_intent_returns_coding_model():
    prompt = "write a python function to parse json"
    selection = auto_select_model(prompt)
    assert selection.provider in ("alibaba", "nvidia")
    assert "coder" in selection.model or "code" in selection.model
```

### Integration Tests

- Test full flows (prompt → routing → provider → response)
- Use test providers or mock clients
- Mark with `@pytest.mark.integration`

### Test Fixtures (conftest.py)

```python
@pytest.fixture
def mock_nvidia_client(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("opsora_v2.get_nvidia_client", lambda: mock)
    return mock
```

---

## 🔒 Security

### Reporting Vulnerabilities

**JANGAN buka public issue** untuk security vulnerabilities.

Email: **security@opsora.dev**

Include:
- Description of vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

### Security Practices

- **Never commit API keys, secrets, atau credentials**
- `.opsora_env` dan `*.env` files sudah di-gitignore
- Gunakan `os.environ.get()` untuk secrets
- Validate all file paths (path traversal protection)
- Read-only AWS operations by default

---

## 📖 Documentation

### When to Update Docs

| Change | Docs to Update |
|---|---|
| New provider | README.md, PROVIDERS.md, ARCHITECTURE.md |
| New tool | README.md, ARCHITECTURE.md, TOOLS.md (future) |
| New slash command | README.md, opsora_tui.py help |
| Architecture change | ARCHITECTURE.md |
| Config change | PROVIDERS.md, DEPLOYMENT.md |
| Breaking change | CHANGELOG.md, README.md migration guide |

### Documentation Style

- **Bilingual** (Indonesia + English) — parallel sections
- **Code examples** — practical, copy-pasteable
- **Mermaid diagrams** — untuk architecture/flows
- **Tables** — untuk comparison/configuration
- **Links** — cross-reference related docs

---

## 🐛 Reporting Issues

### Bug Reports

Gunakan [Bug Report Template](.github/ISSUE_TEMPLATE/bug_report.md):

```markdown
**Describe the bug**
Clear description of what went wrong.

**To Reproduce**
Steps to reproduce:
1. Run command '...'
2. Input '...'
3. See error

**Expected behavior**
What should happen.

**Environment**
- OS: Ubuntu 24.04 / macOS / Windows WSL
- Python: 3.12.3
- Opsora version: 3.1.0
- Providers configured: nvidia, alibaba

**Logs/Output**
```
Paste relevant output here
```
```

### Feature Requests

Gunakan [Feature Request Template](.github/ISSUE_TEMPLATE/feature_request.md):

```markdown
**Is your feature request related to a problem?**
Clear description of the problem.

**Describe the solution you'd like**
What you want to happen.

**Describe alternatives you've considered**
Other approaches.

**Additional context**
Screenshots, mockups, references.
```

---

## 🤝 Code of Conduct

### Our Standards

- **Be respectful** — constructive feedback, no personal attacks
- **Be inclusive** — welcome newcomers, help them learn
- **Be collaborative** — focus on technical merits
- **Be patient** — reviews take time, discussions are valuable

### Unacceptable Behavior

- Harassment, discrimination, or hate speech
- Trolling, insulting, or derogatory comments
- Public or private harassment
- Publishing private information without consent

### Enforcement

Violations dapat dilaporkan ke **conduct@opsora.org**. Semua laporan ditinjau dan ditindaklanjuti.

---

## 📄 License

Dengan berkontribusi, Anda setuju kontribusi Anda akan dilisensikan di bawah [MIT License](LICENSE).

---

## 🙏 Recognition

Kontributor akan ditambahkan ke:
- `CONTRIBUTORS.md` (akan dibuat)
- Release notes
- GitHub contributors graph

---

## 📞 Getting Help

- **Discord:** https://discord.gg/opsora
- **GitHub Discussions:** https://github.com/opsora/opsora-cli/discussions
- **Email:** hello@opsora.dev

---

*Terima kasih untuk berkontribusi ke Opsora! 🎉*