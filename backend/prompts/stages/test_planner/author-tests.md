## Testing plan content

The testing_plan must be detailed enough for both Code Tester and UI Tester to execute after implementation.

Use layered strictness that matches the PRD/discovery complexity:

- `trivial`: write a compact plan with one direct verification path and any obvious negative/edge check. Include a short `Acceptance Coverage` list that maps the PRD's acceptance point(s) to evidence.
- `simple`: cover the primary path plus the most likely error/empty/loading case. Keep manual scenarios concise and executable.
- `moderate`: include an `Acceptance Coverage` matrix mapping each `AC-*` or acceptance bullet from the PRD to at least one automated, UI, or manual check.
- `complex` or high-risk: require coverage for every acceptance point and every high-risk boundary from the PRD, including persistence, migration, authorization, async/background jobs, idempotency/concurrency, external integrations, and rollback/fallback evidence where relevant.

Do not make simple tasks heavy just to fill a template. Mark irrelevant categories as `N/A — reason` rather than inventing tests. However, every task must still have a clear verification path that proves the PRD's `Done When` conditions.

The testing_plan must include:

- `## Acceptance Coverage`: a compact mapping from PRD acceptance IDs (`AC-*`) or acceptance bullets to planned evidence. Use columns or bullets for `Acceptance`, `Test/Evidence`, `Owner` (`code_tester`, `ui_tester`, or `human`), and `Priority`. For trivial/simple tasks this may be a short bullet list.
- `## 1. Automated Tests (for Code Tester)`
- `## 2. Manual Tests (for UI Tester / Human Verification)`

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

Prefer tests that directly prove PRD acceptance evidence. For each automated test, mention the `AC-*` or acceptance bullet it covers when the PRD provides stable IDs. If the PRD has no stable IDs, use short acceptance labels rather than inventing a new product requirement.

### Manual Tests Section (for UI Tester)

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

Manual/UI scenarios should validate user-visible outcomes, not implementation internals. For simple UI changes, one scenario may be enough if it names the screen, visible state, and failure signal. For complex UI flows, include setup/reset data and note any screenshots, raw logs, generated docs, or telemetry that should be captured as evidence.

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

Do NOT write actual test code or `tests/ui/*.json` specs. Write the plan in Markdown format within the testing_plan field.
