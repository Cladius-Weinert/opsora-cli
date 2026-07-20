# Contributing to Opsora CLI

Thank you for your interest in contributing! Opsora is open source and we welcome contributions of all kinds.

## Getting Started

1. **Fork** the repository on GitHub.
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/opsora-cli.git
   cd opsora-cli
   ```
3. **Install** in development mode:
   ```bash
   pip install -e ".[dev]"
   ```
4. Create a **feature branch**:
   ```bash
   git checkout -b feature/my-feature
   ```

## Development Guidelines

### Code Style

- Follow [PEP 8](https://peps.python.org/pep-0008/) conventions.
- Use type hints for function signatures.
- Keep functions small and focused (single responsibility).
- Write docstrings for public functions.

We use [Ruff](https://github.com/astral-sh/ruff) for linting and formatting:

```bash
ruff check cmd/
ruff format cmd/
```

### Testing

- Write tests for new features and bug fixes.
- Run the test suite before submitting:
  ```bash
  pytest tests/
  ```
- Aim for meaningful coverage, not 100% line coverage.

### Commit Messages

Use clear, descriptive commit messages:

```
feat: add streaming response support for NVIDIA provider
fix: handle timeout when Ollama is unreachable
docs: update provider configuration examples
refactor: extract fallback chain into separate function
test: add tests for auto-routing engine
```

### Pull Requests

1. **Keep PRs focused** — one feature or fix per PR.
2. **Update documentation** if you change behavior.
3. **Add tests** for new functionality.
4. **Ensure CI passes** — linting, tests, and type checks.
5. Write a clear PR description explaining **what** and **why**.

## Adding a New Provider

To add support for a new AI provider:

1. Add the provider client initialization in `cmd/opsora_v2.py`.
2. Add the provider to `PROVIDER_MODELS`.
3. Implement `invoke_<provider>()` following the existing pattern.
4. Add availability check to `is_provider_available()`.
5. Update `show_models_table()` to display the new provider.
6. Update this README and the main README.

## Adding a New Tool

To add a new tool:

1. Define the tool schema in `SAFE_TOOLS` following the OpenAI function-calling format.
2. Implement the execution logic in `execute_tool()`.
3. Add the tool to `show_tools_status()`.
4. Write tests for the tool.

## Security

- **Never commit API keys, secrets, or credentials.**
- If you discover a security vulnerability, email security@opsora.dev instead of opening a public issue.
- The `.opsora_env` file and any `*.env` files are gitignored.

## Reporting Issues

- Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md) for bugs.
- Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.md) for ideas.
- Search existing issues before opening a new one.

## Code of Conduct

- Be respectful and constructive.
- Focus on the technical merits of contributions.
- Help newcomers learn and contribute.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
