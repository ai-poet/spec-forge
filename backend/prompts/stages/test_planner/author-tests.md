## Testing plan content

The testing_plan must be detailed enough for Code Tester to write tests after implementation. Include:

1. **Unit tests**: List specific functions/methods to test, with:
   - Input examples and expected outputs
   - Boundary conditions (empty, null, max values, etc.)
   - Error cases and expected exceptions

2. **Integration tests**: Describe component interactions:
   - API endpoints with request/response examples
   - Database operations and expected state changes
   - External service interactions (mocked)

3. **UI tests** (if applicable): Describe user scenarios:
   - User flows and steps
   - Expected page states after each action
   - Assertions for visible text, elements, navigation

Do NOT write actual test code. Write the plan in Markdown format within the testing_plan field.
