# Contributing to OpenETL

Thank you for your interest in contributing to OpenETL! This document provides guidelines and instructions for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How to Contribute](#how-to-contribute)
  - [External Contributors Workflow](#external-contributors-workflow)
  - [Reporting Bugs](#reporting-bugs)
  - [Suggesting Features](#suggesting-features)
  - [Submitting Pull Requests](#submitting-pull-requests)
- [Development Guidelines](#development-guidelines)
  - [Formatting](#formatting)
  - [Testing](#testing)
  - [Documentation](#documentation)
- [Code Review Process](#code-review-process)

## Code of Conduct

This project adheres to a [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## How to Contribute

Before contributing code, complete the setup steps in the [README Getting Started](README.md#getting-started) section, including:
- Database Installation and Initialization
- Airflow Installation and Initialization
- Development Environment Setup

Once your environment is ready, follow the workflow below.

### External Contributors Workflow

We use a **fork-based workflow** for external contributions. Here's the process:

1. **Fork the repository** via the GitHub UI.

2. **Clone your fork**:
   ```bash
   git clone git@github.com:YOUR_USERNAME/openetl.git
   cd openetl
   ```

3. **Add the upstream repository** as a remote:
   ```bash
   git remote add upstream git@github.com:diegoscarabelli/openetl.git
   ```

4. **Create a feature branch** in your fork:
   ```bash
   git checkout -b feature/your-feature-name
   ```

   **Branch naming conventions**:
   - `feature/` - New features or enhancements
   - `fix/` - Bug fixes
   - `docs/` - Documentation updates
   - `refactor/` - Code refactoring
   - `test/` - Test additions or updates

5. **Make your changes** and commit them:
   ```bash
   git add .
   git commit -m "Add feature: description of your changes"
   ```

   **Commit message guidelines**:
   - Use present tense ("Add feature" not "Added feature")
   - Be concise but descriptive
   - Reference issues when applicable (e.g., "Fix #123")

6. **Push your branch to your fork**:
   ```bash
   git push origin feature/your-feature-name
   ```

7. **Create a Pull Request** via GitHub UI:
   - Go to your fork on GitHub
   - Click "Compare & pull request"
   - Ensure the PR is from `YOUR_USERNAME/openetl:feature/your-feature-name` → `diegoscarabelli/openetl:main`
   - Fill out the PR template with detailed information
   - Link any related issues

8. **Keep your fork synchronized** with upstream:
   ```bash
   git fetch upstream
   git checkout main
   git merge upstream/main
   git push origin main
   ```

### Reporting Bugs

Use the [Bug Report template](.github/ISSUE_TEMPLATE/bug_report.md) when creating a new issue. Please include:

- Clear description of the bug
- Steps to reproduce
- Expected vs actual behavior
- Environment details (OS, Python version, PostgreSQL version, etc.)
- Relevant logs or error messages

### Suggesting Features

Use the [Feature Request template](.github/ISSUE_TEMPLATE/feature_request.md) when suggesting new features. Please include:

- Problem description
- Proposed solution
- Use case and benefits
- Any alternatives you've considered

### Submitting Pull Requests

Before submitting a PR, ensure:

1. **Your code follows the formatting standards** (see [Formatting](#formatting) below)
2. **All tests pass**: `make test`
3. **Code is properly formatted**: `make format` and `make check-format`
4. **New code has tests** with adequate coverage
5. **Documentation is updated** (README, docstrings, etc.)
6. **The PR template is filled out** completely

## Development Guidelines

### Formatting

Python code formatting is handled using the following tools:

- **[Black](https://github.com/psf/black)**: Formats Python code with a focus on readability and consistency. The default settings are used, and it can be [integrated](https://black.readthedocs.io/en/stable/integrations/editors.html) with most editors and IDEs.
- **[Autoflake](https://github.com/myint/autoflake)**: Removes unused imports and variables to keep the code clean.
- **[Docformatter](https://github.com/PyCQA/docformatter)**: Formats docstrings to ensure compliance with `black` and maintain a consistent style.

For SQL files, **[SQLFluff](https://docs.sqlfluff.com/en/stable/)** is used to enforce consistent formatting. Some files are ignored by SQLFluff as specified in the [`.sqlfluffignore`](.sqlfluffignore) file.

The configuration for all these formatting tools is defined in the [`pyproject.toml`](pyproject.toml) file, ensuring a centralized and consistent setup across the repository. This file is automatically read by the formatting tools, eliminating the need for additional configuration steps.

#### Running Formatters

The `make` command is configured using a [`Makefile`](Makefile) located in the root of the repository. This file defines the `format` and `check-format` targets, which encapsulate the commands for running the formatting tools. The `format` target applies the formatting tools to all Python and SQL files, while the `check-format` target verifies compliance without making changes. These targets ensure a consistent and automated approach to code formatting across the repository.

To format all Python and SQL files in this repository, execute the following command:
```bash
make format
```

To verify that the files adhere to the formatting standards, run:
```bash
make check-format
```

If any files are not properly formatted, the `make check-format` command will return a non-zero exit code, allowing you to identify and address formatting issues.

#### Automating Formatting

To ensure consistent code quality throughout the development process, you can install **[pre-commit](https://pre-commit.com/)** hooks. These hooks automatically run the formatters before each commit, preventing improperly formatted code from being committed to the repository.

The hooks are configured in the [`.pre-commit-config.yaml`](.pre-commit-config.yaml) file located in the root of the repository. This file specifies the tools and rules that will be executed by `pre-commit`. The hooks are set up to use the `make` commands defined in the [`Makefile`](Makefile), ensuring that the same formatting rules are applied consistently across the repository.

##### Installing Pre-commit Hooks

1. Install the `pre-commit` package using `pip`:
  ```bash
  pip install pre-commit
  ```

2. Install the pre-commit hooks:
  ```bash
  pre-commit install
  ```

3. (Optional) Run the hooks on all files to ensure the repository is compliant:
  ```bash
  pre-commit run --all-files
  ```

#### Formatting Standards

##### Code Style Rules

- **Use Black formatting** with a maximum of 88 characters per line.
- **Apply docformatter style** per [pyproject.toml](pyproject.toml) configuration:
  - Add a blank line after each docstring.
  - Ensure Black-compatible formatting.
  - Use multi-line summary format.
  - Add a pre-summary newline for improved readability.
- **Include type hints** for all function parameters and return values.
- **Use `:param` and `:return`** tags in docstrings (not Google or NumPy style).
- **Automatically remove unused imports** using autoflake.
- **Use f-strings for string interpolation** instead of other formatting methods.
- **Print full tracebacks for exceptions** rather than only the exception message.

##### Import Organization

1. **Standard library imports** (alphabetically sorted)
   - `import` statements first.
   - `from` imports second.
2. **Blank line**
3. **Third-party imports** (alphabetically sorted)
   - `import` statements first.
   - `from` imports second.
4. **Blank line**
5. **Local application imports** (alphabetically sorted)
   - `import` statements first.
   - `from` imports second.
6. **Two blank lines** before first class/function.

##### Spacing Rules

- **Module docstring**: Immediately at the top.
- **Two blank lines**: After module docstring, before imports.
- **Two blank lines**: After imports, before first class/function.
- **Two blank lines**: Between classes and top-level functions.
- **One blank line**: Between methods within a class.
- **One blank line**: After docstrings, before code.

##### File Structure Example

```python
"""
Module description goes here.
Explain the purpose and main functionality of this module.
"""


import os
import sys
from pprint import pformat
from typing import Union

import pendulum
import sqlalchemy
from requests import Session
from sqlalchemy import create_engine

from .local_module import LocalClass
from .utils import helper_function


class ExampleClass:
    """
    Class description that demonstrates the multi-line format with pre-summary
    newline as configured in pyproject.toml.

    :param param1: Description of param1
    :return: Description of return value if applicable
    """

    def __init__(self, param1: int) -> None:
        """
        Initialize the class with the provided parameter following docformatter
        configuration.

        :param param1: Description of param1
        """

        self.param1 = param1


def example_function(arg1: int, arg2: str) -> bool:
    """
    Function description that follows the project's docformatter settings for
    multi-line summaries.

    :param arg1: Description of arg1
    :param arg2: Description of arg2
    :return: True if successful, False otherwise
    """

    return True
```

##### Quality Checklist

Before pushing any changes to Github, verify:

**Manual Checks (REQUIRED before automated tools):**
- [ ] Module docstring present (see [File Structure Example](#file-structure-example)).
- [ ] Proper spacing and blank lines throughout file (see [Spacing Rules](#spacing-rules)).
- [ ] No trailing whitespace.
- [ ] Periods at the end of sentences such as comments, docstrings, bullet lists, log messages (not the header of the file).
- [ ] No line in python and SQL files longer than 88 characters. (see [Code Style Rules](#code-style-rules)).

**Automated Checks:**
- [ ] Imports properly organized and sorted, no unused imports (see [Import Organization](#import-organization)).
- [ ] All functions have type hints (see [Code Style Rules](#code-style-rules)).
- [ ] All docstrings use `:param` and `:return` format (see [Code Style Rules](#code-style-rules)).
- [ ] Black-compliant format (see [Code Style Rules](#code-style-rules)).
- [ ] Consistent indentation (4 spaces).

### Testing

All code changes must include appropriate tests. We use [pytest](https://docs.pytest.org/) for testing.

#### Running Tests

```bash
# Run all tests with coverage
make test

# Run specific test file
pytest tests/path/to/test_file.py

# Run specific test function
pytest tests/path/to/test_file.py::test_function_name

# Run with verbose output
pytest -v
```

#### Test Requirements

- **New features** must include tests demonstrating the functionality
- **Bug fixes** must include tests that would have caught the bug
- **Aim for high coverage** on new code (ideally 100%)
- **Use fixtures** from `conftest.py` when appropriate
- **Follow existing test patterns** in the repository

#### Test Environment

Tests require a PostgreSQL database. For configuration instructions, see the [Configure Test Environment](README.md#configure-test-environment) section in the README.

### Documentation

Update documentation when making changes:

- **README.md**: Update if adding new features, changing setup steps, or modifying core functionality
- **Docstrings**: Add/update for all new/modified functions and classes
- **Pipeline READMEs**: Update pipeline-specific documentation in `dags/pipelines/*/README.md`
- **CLAUDE.md**: Update if changing development workflows or standards

## Code Review Process

1. **Automated checks** run via GitHub Actions on all PRs
   - Code formatting verification
   - Test suite execution
   - Must pass before merge

2. **Manual review** by project maintainers
   - Code quality and style
   - Test coverage and quality
   - Documentation completeness
   - Architectural fit

3. **Feedback and iteration**
   - Address reviewer comments
   - Make requested changes
   - Push updates to your PR branch

4. **Approval and merge**
   - PRs require approval from a maintainer
   - Maintainer will merge once approved
   - Your contribution becomes part of the project!

---

Thank you for contributing to OpenETL! Your efforts help make this project better for everyone.
