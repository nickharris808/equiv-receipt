# Contributing to equiv-receipt

This package is part of [certified-oss][p]. **The portfolio-wide guide is
[CONTRIBUTING.md][c] and it is the one to read** — it covers the rules that are not negotiable,
how to install packages that depend on each other, and what kind of contribution is most wanted
(a forgery this project fails to catch).

What is specific to this package:

- **`bcp()` is the specification, not dead code.** The watched-literal engine is checked against it
  by 25 randomised differential tests on every run. If you change either, they must still agree.
- **Standard library only.** Checked against `sys.stdlib_module_names`.
- **`UNDECIDED-AT-K` is a verdict.** Any change that makes it render as a pass or a plain failure —
  in an exit code, an emitter, anywhere — will be rejected.

## Working on it

```bash
pip install -e ".[test]"
pytest -q
ruff check .
```

## Licence

Apache-2.0. By contributing you agree your contribution is licensed the same way.

[p]: https://github.com/nickharris808/certified-oss
[c]: https://github.com/nickharris808/certified-oss/blob/main/CONTRIBUTING.md
