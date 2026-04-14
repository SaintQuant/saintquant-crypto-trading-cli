# Contributing to crypto-trading-cli

Thank you for your interest in contributing! This guide covers how to set up a development environment, run the test suite, and follow the project's code style.

---

## Development Setup

### Prerequisites

- Python 3.10 or later
- [Freqtrade](https://www.freqtrade.io/en/stable/installation/) installed locally (required to run integration tests)
- Git

### Install in editable mode with dev dependencies

```bash
git clone https://github.com/your-org/crypto-trading-cli.git
cd crypto-trading-cli
pip install -e ".[dev]"
```

This installs the package in editable mode along with `pytest`, `pytest-cov`, and `hypothesis`.

---

## Running Tests

```bash
# Run all tests
pytest tests/

# Run with coverage report
pytest tests/ --cov=crypto_trading_cli --cov-report=term-missing

# Run a specific test file
pytest tests/test_crypto.py -v

# Run property-based tests with more examples
pytest tests/ --hypothesis-seed=0
```

---

## Project Structure

```
crypto-trading-cli/
├── crypto_trading_cli/       # Main package
│   ├── main.py               # CLI entry point (click)
│   ├── bot_manager.py        # Bot lifecycle orchestrator
│   ├── ft_process.py         # Freqtrade subprocess manager
│   ├── ft_api_client.py      # Freqtrade REST API client
│   ├── db.py                 # SQLite persistence layer
│   ├── crypto.py             # Fernet encryption utilities
│   ├── config.py             # AppConfig dataclass + load/save
│   ├── strategy.py           # Freqtrade config builder
│   ├── exchange.py           # Exchange ccxt config
│   ├── validators.py         # Strategy parameter validation
│   ├── ui/
│   │   ├── menus.py          # Interactive menu flows
│   │   ├── prompts.py        # Input helpers (masked, typed, selection)
│   │   └── tables.py         # Rich table/panel renderers
│   └── strategies/           # Bundled Freqtrade strategy files
│       ├── GridStrategy.py
│       ├── RSIStrategy.py
│       └── EMAStrategy.py
└── tests/                    # Test suite
```

---

## Code Style Guidelines

- **Language**: All code, comments, docstrings, and documentation must be in **English**.
- **Formatting**: Follow [PEP 8](https://peps.python.org/pep-0008/). Use 4-space indentation.
- **Type hints**: All public functions and methods must have type annotations.
- **Docstrings**: Use Google-style docstrings for all public classes and functions.
- **No raw tracebacks**: Never let a raw Python traceback reach the user. Catch exceptions and display friendly messages.
- **No credential logging**: Never log or print API keys, secrets, or encryption keys at any log level.
- **Tests**: All new features must include tests. Property-based tests (Hypothesis) are preferred for pure functions with large input spaces.

---

## Submitting a Pull Request

1. Fork the repository and create a feature branch: `git checkout -b feature/my-feature`
2. Make your changes and add tests.
3. Run the full test suite: `pytest tests/`
4. Commit with a clear message: `git commit -m "feat: add support for XYZ exchange"`
5. Push and open a pull request against `main`.

---

## Reporting Issues

Please open a GitHub issue with:
- Your operating system and Python version
- The exact command you ran
- The full error output (redact any API keys before posting)
