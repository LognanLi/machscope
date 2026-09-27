# Repository Guidelines

## Project Structure & Module Organization

This directory is a multi-project workspace, with no root Git repository or shared build system.

- `CS61A/`: Python coursework organized into `hw/`, `lab/`, and `proj/hog/`. Assignment folders contain source files, `tests/`, pytest configuration, and bundled `.grader/` tooling. Hog browser assets live in `gui-files/`.
- `Learning Python/`: standalone Python exercises and a `portfolio/` static website.
- `projects/logan_website/`: static portfolio with `index.html`, `css/`, and `js/`.
- `ux_at_berkeley/`: static website with `index.html`, `styles.css`, and reference images in `screenshots/`.
- `projects/machscope/`: initialized Git repository with no source files or commits yet.

Keep changes scoped to the requested project. Do not assume the two portfolio directories should be synchronized.

## Build, Test, and Development Commands

Run these from the workspace root unless stated otherwise:

- `python3 -m http.server 8000 --bind 127.0.0.1 --directory projects/logan_website`: preview the portfolio at `http://localhost:8000`; substitute `ux_at_berkeley` for that site. No build step is required.
- `python3 "Learning Python/learn.py"`: run a standalone Python exercise. Quote paths containing spaces.
- From an assignment directory, such as `CS61A/proj/hog`, run `PYTHONPATH=.grader python3 -m pytest --score` for the bundled grader.
- In Hog, use `PYTHONPATH=.grader python3 -m pytest -k q01` to check one question.

## Coding Style & Naming Conventions

Use four-space indentation and `snake_case` for Python functions and variables. Preserve coursework function signatures and docstrings. Follow the portfolio JavaScript's two-space indentation, `camelCase` identifiers, and semicolons. Use descriptive, hyphenated CSS classes and preserve each stylesheet's existing formatting. No shared formatter or linter configuration is present.

## Testing Guidelines

Coursework uses pytest, doctests, and `pytest_grader`. Preserve supplied test filenames, including `tests/q01.py`, and assignment-specific restrictions. Do not alter grader internals or expected answers to make checks pass. No workspace-wide coverage threshold is configured.

For website changes, check desktop and mobile layouts, navigation, affected interactions, and browser console errors. Include screenshots for visual changes.

## Commit & Pull Request Guidelines

No commit history is available to establish conventions. Use concise imperative messages, such as `Fix portfolio mobile navigation`, and keep commits focused. PR descriptions should identify the project, explain the change, list validation performed, link relevant issues, and include screenshots when applicable. Exclude secrets, `.env` contents, caches, and local session logs from commits.


# MachScope

MachScope is a learning project for exploring operating systems and
macOS process observability.

## Rules

- Keep implementations simple.
- Use Python initially.
- Do not implement features I didn't request.
- Explain OS concepts that appear in the code.
- Prefer standard library tools when reasonable.
- Before making large architectural changes, explain them first.
- Run tests after changes.

## Learning mode

I am early in my CS education.

For important logic, guide me through the reasoning instead of
immediately writing everything for me.

Boilerplate can be implemented directly.