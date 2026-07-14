```markdown
# dmz-backend-supletivo Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches the core development patterns and conventions used in the `dmz-backend-supletivo` Python codebase. You will learn about file naming, import/export styles, commit message habits, and how to structure and run tests. This guide is designed to help contributors maintain consistency and efficiency when working on this repository.

## Coding Conventions

### File Naming
- **Style:** camelCase
- **Example:**  
  ```python
  userManager.py
  studentRecords.py
  ```

### Import Style
- **Style:** Relative imports are preferred.
- **Example:**  
  ```python
  from .models import Student
  from .utils import calculateAverage
  ```

### Export Style
- **Style:** Named exports (explicitly listing what is exported).
- **Example:**  
  ```python
  __all__ = ['Student', 'Teacher', 'Course']
  ```

### Commit Messages
- **Type:** Freeform, no enforced structure.
- **Prefix:** No specific prefixes required.
- **Average Length:** ~59 characters.
- **Example:**  
  ```
  Add endpoint for updating student grades
  ```

## Workflows

### Adding a New Feature
**Trigger:** When implementing a new functionality.
**Command:** `/add-feature`

1. Create a new camelCase Python file if needed.
2. Use relative imports for any internal modules.
3. Implement the feature, ensuring named exports where applicable.
4. Write or update corresponding test files (`*.test.*`).
5. Commit changes with a clear, concise message.

### Fixing a Bug
**Trigger:** When resolving a reported issue or bug.
**Command:** `/fix-bug`

1. Locate the relevant camelCase file(s).
2. Apply the fix, maintaining code style conventions.
3. Update or add tests in `*.test.*` files to cover the fix.
4. Commit with a descriptive message about the bug fix.

### Writing and Running Tests
**Trigger:** When verifying new or existing code.
**Command:** `/run-tests`

1. Create or update test files using the `*.test.*` pattern.
2. Use the project's preferred (currently unknown) testing framework.
3. Run all tests to ensure correctness.
4. Address any failing tests before committing.

## Testing Patterns

- **File Pattern:** Test files follow the `*.test.*` naming convention.
- **Framework:** The specific testing framework is not detected—check existing test files for clues.
- **Example:**  
  ```
  userManager.test.py
  studentRecords.test.py
  ```
- **Note:** Place tests alongside or near the modules they test, and ensure all new features and bug fixes are covered by tests.

## Commands
| Command      | Purpose                                  |
|--------------|------------------------------------------|
| /add-feature | Start the workflow for adding a feature  |
| /fix-bug     | Start the workflow for fixing a bug      |
| /run-tests   | Run all test files in the repository     |
```