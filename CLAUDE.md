# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## README.md

The most important source of truth is the [`/README.md`](README.md) file, which contains the latest information about the project. You MUST read and understand the `README.md` file in order to provide accurate and relevant responses and coding assistance.
The `README.md` file includes:
- **Introduction**: Project overview, objectives, and Apache Airflow integration for end-to-end data analytics workflows.
- **Directories**: Comprehensive documentation of each component:
  - `dags/lib/`: Utility modules for DAG development (dag_utils, etl_config, sql_utils, filesystem_utils, etc.).
  - `dags/pipelines/`: Individual DAG implementations with DDL files and documentation.
  - `dags/database.ddl`: Creates the lens database for all pipeline outputs.
  - `dags/schemas.ddl`: TimescaleDB schema initialization with pgvectorscale extension.
  - `dags/iam.sql`: Identity and Access Management configuration for secure pipeline operations.
  - `tests/`: Pytest-based testing framework with fixtures and coverage.
  - `iac/`: Infrastructure as Code for deployment (Airflow, Astro CLI, TimescaleDB).
  - `CLAUDE.md`: Project-specific instructions for Claude Code.
- **Standard DAG**: Framework for creating ETL pipelines using ETLConfig and standard task patterns.
  - Four-step pipeline: ingest → batch → process → store.
  - Example implementation with custom processors and file type definitions.
- **Formatting**: Comprehensive code quality standards and automation.
  - Python formatting with Black, Autoflake, and Docformatter.
  - SQL formatting with SQLFluff.
  - Pre-commit hooks and make targets for consistency.
  - Detailed style rules, import organization, and quality checklists.

## Code Execution Environment

When running code in this repo, you can use the `airflow` conda environment, which is setup based on the [`requirements_dev.txt`](requirements_dev.txt). This environment includes all necessary dependencies for running the Airflow DAGs and tests.

### Command Reference

- **Conda activation**: `source ~/.zshrc && conda activate airflow`

## MANDATORY Formatting Protocol

When ANY formatting request is made (explicit or implicit), you MUST:

### Step 1: Manual Quality Review (BEFORE make format)
Execute EVERY item from README.md Quality Checklist (lines 334-347):

- [ ] Module docstring present  
- [ ] Imports properly organized and sorted, no unused imports
- [ ] All functions have type hints
- [ ] All docstrings use `:param` and `:return` format
- [ ] **MANUALLY CHECK: Proper spacing and blank lines throughout file**
- [ ] Black-compliant format
- [ ] **MANUALLY CHECK: No trailing whitespace** 
- [ ] Consistent indentation (4 spaces)
- [ ] **MANUALLY CHECK: Periods at the end of ALL sentences** (comments, docstrings, bullet lists, log messages)
- [ ] **MANUALLY CHECK: No line longer than 88 characters**

### Step 2: Apply Automated Tools
- [ ] Run `make format`
- [ ] Run `make check-format` to validate

### Step 3: Final Manual Verification  
- [ ] Verify final newline at end of file
- [ ] Double-check line lengths and periods were properly applied

### CRITICAL: Manual Checks Required
The following items are NOT caught by automated tools and MUST be manually verified:
1. **Line length**: Check every line ≤88 characters
2. **Periods**: Every comment, docstring sentence, log message ends with period
3. **Spacing**: Proper blank lines between logical sections
4. **File ending**: Final newline present

## Formatting Trigger Words

When you encounter ANY of these words/phrases, immediately execute the complete formatting protocol:
- "formatting"
- "format"
- "quality check" 
- "style"
- "apply formatting guidelines"
- "according to guidelines in README.md"
- "quality checklist"
- When completing ANY code file creation/modification

NEVER use `make format` alone - always execute the complete manual + automated protocol.

## Quality Checklist Command Reference

Before ANY file completion, run this mental checklist:
1. **Read current file** - identify all issues manually
2. **Line length check** - scan for any line exceeding 88 characters
3. **Period check** - ensure all comments, docstrings, and log messages end with periods
4. **Spacing check** - verify proper spacing between sections and imports
5. **Apply automated tools** - run `make format` and `make check-format`
6. **Final verification** - confirm all quality standards are met

## Code Completion Protocol Enforcement

**MANDATORY**: Before marking any code task as complete:
1. Execute complete manual quality review (Steps 1-3 above)
2. Run `make format` followed by `make check-format`
3. Verify zero formatting violations
4. Only then proceed with task completion

**VIOLATION HANDLING**: If you discover you missed manual checks:
1. Immediately acknowledge the oversight
2. Execute the complete formatting protocol
3. Document what was missed to prevent recurrence