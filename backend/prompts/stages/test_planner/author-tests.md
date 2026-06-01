## Testing plan content

The testing_plan must be detailed enough for both Code Tester and CUA to execute after implementation.

### Automated Tests Section (for Code Tester)

Include:

1. **Unit tests**: List specific functions/methods to test, with:
   - Input examples and expected outputs
   - Boundary conditions (empty, null, max values, etc.)
   - Error cases and expected exceptions

2. **Integration tests**: Describe component interactions:
   - API endpoints with request/response examples
   - Database operations and expected state changes
   - External service interactions (mocked)

### Manual Tests Section (for CUA)

For each manual test scenario, include:

1. **Scenario ID and Title**: e.g., "MT-01: User Login Flow"

2. **Goal**: What user goal or acceptance criterion this validates

3. **Prerequisites**: Required setup before starting (e.g., "User account exists", "App is on home screen")

4. **Steps**: Detailed user actions in sequence:
   - Action: what the user does (click, type, tap, swipe, etc.)
   - Target: which element/area (button name, input field label, etc.)
   - Value: what to input (if applicable)

5. **Expected Result**: What should be visible/observable after each step or at completion:
   - Visible text or UI elements
   - Page/screen changes
   - Success/error messages

6. **Success Criteria**: Clear pass/fail conditions:
   - Must see: X
   - Must not see: Y
   - State should be: Z

Example manual test format:

```markdown
### MT-01: User Login

**Goal**: Verify registered user can log in with valid credentials

**Prerequisites**: Test user "alice@example.com" with password "secret123" exists

**Steps**:
1. Open login page
2. Click email input field
3. Type "alice@example.com"
4. Click password input field
5. Type "secret123"
6. Click "Sign In" button

**Expected Result**:
- After step 6: User is redirected to dashboard
- Dashboard shows welcome message with user name
- Navigation menu shows logged-in options

**Success Criteria**:
- Pass: Dashboard loads within 3 seconds, user name visible
- Fail: Error message shown, stays on login page, or redirects elsewhere
```

Do NOT write actual test code. Write the plan in Markdown format within the testing_plan field.
