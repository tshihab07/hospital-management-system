# Contributing to IHMS

Thanks for contributing. This project follows a strict, phase-ordered workflow
described in [`docs/RULES.md`](docs/RULES.md). Please read it before opening a
change.

## Ground rules

- **Respect the phase order.** Build only what the current phase allows; queue
  later-phase work. The dependency graph is in `docs/RULES.md` §1.
- **Layer discipline.** Each app separates `models.py`, `services.py`
  (transactional, audited business logic), `selectors.py` (read queries),
  `forms.py`, `views/`, `urls.py`, and `templates/`.
- **Audit everything.** Every CREATE/UPDATE/DELETE of a business record must
  call `core.audit.log_action` (RULES §4.4.1).
- **No secrets in git.** Only `.env.example` is committed; never commit `.env`.

## Branching & commits

- Branch from `main`: `feature/<phase>-<short-desc>`, `fix/<desc>`.
- Write [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(pharmacy): add FIFO dispensing service`.
- Keep commits focused; one logical change per commit.

## Before you push

```bash
black .          # format
isort .          # import order
ruff check .     # lint
pytest           # tests must pass
bandit -r apps core
```

Install the git hooks so these run automatically on commit:

```bash
pip install pre-commit
pre-commit install
```

## Definition of done

A change is complete when it has: models + migrations, services (with audit),
forms, views/urls, templates, tests (happy path + one audit assertion + one
permission/security test), and documentation updated (app notes in
`docs/MEMORY.md`, corrected deviations in `docs/MISTAKES.md`).
