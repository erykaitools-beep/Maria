# Contributing to M.A.R.I.A.

Thank you for your interest in contributing to M.A.R.I.A.!

## Getting Started

1. Fork the repository
2. Run `bash install.sh` to set up the development environment
3. Create a feature branch: `git checkout -b feature/your-feature`
4. Make your changes
5. Run tests: `python -m pytest agent_core/tests/ -q`
6. Commit and push to your fork
7. Open a Pull Request

## Development Setup

```bash
git clone https://github.com/YOUR_USERNAME/Maria.git
cd Maria
bash install.sh
source venv/bin/activate
python -m pytest agent_core/tests/ -q  # verify everything works
```

## Code Style

- Python 3.10+
- Type hints preferred
- Docstrings in English
- Comments can be in Polish or English
- **No emoji in code** (terminal compatibility - ADR-005)
- Max line length: 120 characters

## Architecture Rules

M.A.R.I.A. follows strict architectural contracts (K1-K13). Before contributing:

1. Read `docs/ARCHITECTURE.md` for system overview
2. Read `docs/CONTRACTS.md` for formal module contracts
3. Read `DEVELOPER_GUIDE.md` for coding conventions

### Key Principles

- **JSONL as source of truth** (ADR-001) - no databases, all state in append-only JSONL files
- **Threading, not asyncio** (ADR-002)
- **READ-ONLY introspection** (ADR-006) - Maria never modifies her own code
- **Rule-based before LLM** (ADR-013) - prefer deterministic logic over LLM calls
- **Graceful fallbacks** - every feature must work without optional dependencies (NIM, Telegram, camera)

### Module Boundaries

Each module in `agent_core/` owns a clear domain. Don't create cross-module dependencies without checking existing contracts. Key boundaries:

- `homeostasis/` owns the 1Hz tick loop and system health
- `planner/` owns the ReAct decision cycle
- `goals/` owns goal lifecycle (PROPOSED -> ACTIVE -> ACHIEVED)
- `consciousness/` owns identity, personality, and operator memory
- `llm/` owns all LLM routing and model management

## Testing

- All tests in `agent_core/tests/`
- Use `pytest` with fixtures and mocks
- **No external dependencies in tests** - all HTTP, LLM, and file I/O must be mocked
- Name test files: `test_<module>.py`
- Target: every new module should have >90% coverage

```bash
# Run all tests
python -m pytest agent_core/tests/ -q

# Run specific module
python -m pytest agent_core/tests/test_planner.py -v

# Run with coverage
python -m pytest agent_core/tests/ --cov=agent_core --cov-report=term-missing
```

## Pull Request Guidelines

- Keep PRs focused (one feature/fix per PR)
- Include tests for new functionality
- Update relevant docs if behavior changes
- Don't modify `.env.example` without discussion
- Don't add new Python dependencies without discussion

## Reporting Issues

- Use GitHub Issues
- Include: what you expected, what happened, steps to reproduce
- For bugs: include Python version, OS, and relevant logs

## License

By contributing, you agree that your contributions will be licensed under the AGPL-3.0 license.
