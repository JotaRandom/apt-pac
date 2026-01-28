# Contributing to apt-pac

First off, thanks for taking the time to contribute! 🎉

## How do I contribute?

Since this project is a fun experiment (and partially AI-generated), we don't have super strict rules, but here are some guidelines to keep things smooth:

### 1. Reporting Bugs

- Check if the issue has already been reported.
- Open a new issue with a clear title and description.
- Include your Arch version (e.g., standard Arch, Manjaro, EndeavourOS).
- Run `apt-pac --version` and include the output.

### 2. Suggesting Enhancements

- Have an idea? Open an issue to discuss it first!
- We generally want to avoid scope creep—this tool is meant to be a *simple* wrapper.

### 3. Pull Requests

- Fork the repo and create your branch from `main`.
- **Code Style**: We use `black` and `isort`. Please run `pre-commit run --all-files` before submitting.
- **Tests**: If you add functionality, try to add a test case in `tests/`.
- **AI Usage**: If you use AI to write code, that's totally fine! Just make sure you verify it works. 😉

## Development Setup

1. Clone the repo:

    ```bash
    git clone https://github.com/JotaRandom/apt-pac.git
    cd apt-pac
    ```

2. Install dependencies:

    ```bash
    pacman -S python-rich pyalpm
    pip install pre-commit
    ```

3. Install git hooks:

    ```bash
    pre-commit install
    ```

4. Run tests:

    ```bash
    python3 tests/run_tests.py
    ```

Thanks! 🚀
