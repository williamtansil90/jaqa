# JAQA Format & Automation Guide (for AI Agents)

This document teaches another AI how to **create**, **structure**, and **validate** JAQA test cases without using the JAQA desktop UI. Use it when you need to generate test suites in JAQA-compatible **JSON** or **Excel** format.

---

## 1. What is JAQA?

**JAQA (Jalin Automate QA)** is a Windows desktop SIT (System Integration Test) tool that:

1. Stores **Test Cases (TC)** with metadata (URL, credentials, description).
2. Replays **Record Steps** in a real browser (Playwright + Chrome/Edge).
3. Verifies **Expected Results** (automated assertions on DOM elements).
4. Marks each TC **OK** (pass) or **NOK** (fail) after a run.
5. Exports results to **Excel** or **PDF**.

An AI agent typically:

- Reads requirements / UI specs → produces a TC list.
- Outputs `suite.json` or `suite.xlsx` → user imports into JAQA.
- Optionally documents manual **Expectation** text vs automated **Expected Result** checks.

---

## 2. Source of truth in code

| Concept | Python module |
|---------|---------------|
| Data models | `app/core/models.py` |
| JSON I/O | `app/core/storage.py` |
| Excel I/O | `app/core/reporter.py` |
| Run / record engine | `app/core/engine.py` |
| UI column labels | `TC_LIST_COLUMNS`, `STEP_LIST_COLUMNS`, `EXPECT_LIST_COLUMNS` in `models.py` |

When in doubt, prefer field names from `models.py` over this document.

---

## 3. Object hierarchy

```
TestSuite
└── test_cases[]: TestCase
    ├── steps[]: Step          (Record Step — browser actions)
    ├── expectations[]: Expectation   (Expected Result — assertions)
    ├── browser_cookies[]      (optional, Playwright cookie format)
    ├── browser_storage_state  (optional, Playwright storage state)
    └── expectation_results[]  (filled after run, usually omit when authoring)
```

---

## 4. UI column labels (display names)

These are the **exact headers** shown in JAQA and used in Excel export/import.

### 4.1 Test Case list

| Internal key | UI / Excel header | Notes |
|--------------|-------------------|-------|
| `enabled` | **Active** | `ENABLE` or `DISABLE` in Excel; `true`/`false` in JSON |
| `no_tc` | **NO. TC** | Unique human-readable ID, e.g. `TC-001` |
| `deskripsi` | **Description** | What is being tested |
| `aplikasi` | **Application** | Application name |
| `url` | **URL** | Start URL (https recommended) |
| `username` | **Username** | Reference / can be used in steps manually |
| `password` | **Password** | Reference / can be used in steps manually |
| `expected_result` | **Expectation** | Manual text expectation (documentation) |
| *(computed)* | **Expected Result** | Summary of `expectations[]`; not stored as single field |
| `status` | **Status** | `OK`, `NOK`, empty, or `RUNNING` |
| `notes` | **Notes** | Run notes / failure reasons |

### 4.2 Record Step tab

| Internal key | UI / Excel header |
|--------------|-------------------|
| `enabled` | **Active** |
| *(order)* | **#** |
| `type` | **Type** |
| `label` | **Step** |
| `delay_ms` | **Delay** |
| `selector` | **Selector** |
| `value` | **Value** |

### 4.3 Expected Result tab

| Internal key | UI / Excel header |
|--------------|-------------------|
| `enabled` | **Active** |
| *(order)* | **#** |
| `label` | **Label** |
| `kind` | **Type** |
| `match` | **Comparison** |
| `expected_value` | **Expected Value** |
| `after_step` | **Check After** |

---

## 5. JSON format (recommended for AI generation)

### 5.1 Root: TestSuite

```json
{
  "app": "JAQA",
  "version": "1.0",
  "name": "My SIT Suite",
  "exported_at": "2026-08-24T10:00:00",
  "test_cases": []
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `app` | string | yes | Must be `"JAQA"` |
| `version` | string | no | Suite schema version, default `"1.0"` |
| `name` | string | no | Suite display name |
| `exported_at` | string | no | ISO datetime |
| `test_cases` | array | yes | List of TestCase objects |

Import also accepts a **bare array** of test cases (wrapped automatically).

### 5.2 TestCase

```json
{
  "id": "a1b2c3d4e5f6",
  "no_tc": "TC-001",
  "deskripsi": "Login with valid credentials",
  "aplikasi": "Portal",
  "url": "https://example.com/login",
  "username": "sit.user",
  "password": "secret",
  "expected_result": "User lands on dashboard",
  "enabled": true,
  "steps": [],
  "expectations": [],
  "status": "",
  "notes": "",
  "last_run_at": "",
  "expectation_results": [],
  "browser_cookies": [],
  "browser_storage_state": {}
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | auto 12-char hex | Stable internal ID; omit to auto-generate |
| `no_tc` | string | `""` | **Required for Excel linking**; primary key across sheets |
| `deskripsi` | string | | Description |
| `aplikasi` | string | | Application name |
| `url` | string | | Initial URL when recording; first `goto` often duplicates this |
| `username` | string | | Metadata (not auto-filled unless steps do it) |
| `password` | string | | Metadata |
| `expected_result` | string | | Manual **Expectation** column text |
| `enabled` | bool | `true` | If `false`, TC skipped on Run All |
| `steps` | Step[] | `[]` | Automation steps |
| `expectations` | Expectation[] | `[]` | Automated checks |
| `status` | string | `""` | Set by runner: `OK` / `NOK` |
| `notes` | string | | Failure summary after run |
| `browser_cookies` | array | `[]` | Playwright cookies (optional) |
| `browser_storage_state` | object | `{}` | Playwright storage (optional) |

### 5.3 Step (Record Step)

```json
{
  "id": "step001abc",
  "type": "fill",
  "selector": "#username",
  "value": "sit.user",
  "url": "",
  "key": "",
  "checked": null,
  "tag": "input",
  "label": "Username field",
  "delay_ms": 500,
  "timestamp": "2026-08-24T10:00:00",
  "enabled": true
}
```

#### Step `type` values

| type | Playwright action | Required fields |
|------|-------------------|-----------------|
| `goto` | `page.goto()` | `url` or `value` (URL string) |
| `click` | `locator.click()` | `selector` |
| `fill` | `locator.fill()` | `selector`, `value` |
| `select` | `locator.select_option()` | `selector`, `value` |
| `check` | `locator.set_checked()` | `selector`, `checked` (bool) |
| `press` | fill optional + `locator.press()` | `selector`, `key` (e.g. `Enter`) |
| `wait` | `page.wait_for_timeout()` | `value` or `delay_ms` (milliseconds) |

**Execution notes:**

- Selectors are **Playwright** selectors (CSS, `#id`, `[name=...]`, `text=...`, etc.).
- After each step (except `goto` / `wait`), engine waits `delay_ms` ms (default 250 ms if 0).
- Steps with `enabled: false` are **skipped** during run but still count for `after_step` numbering.

### 5.4 Expectation (Expected Result)

```json
{
  "id": "exp001abc",
  "selector": "h1.page-title",
  "kind": "text",
  "attribute": "",
  "match": "contains",
  "expected_value": "Dashboard",
  "label": "Page title",
  "after_step": 3,
  "tag": "h1",
  "sample_text": "Dashboard",
  "enabled": true
}
```

#### `kind` (Type)

| kind | Reads from element |
|------|-------------------|
| `text` | `inner_text()` |
| `value` | `input_value()` |
| `visible` | visibility; `expected_value` `true`/`false` |
| `attribute` | `get_attribute(attribute)` |
| `checked` | checkbox state; `expected_value` `true`/`false` |

#### `match` (Comparison)

| match | Rule |
|-------|------|
| `equals` | Trimmed exact match |
| `contains` | Case-insensitive substring |
| `regex` | Python `re.search` on actual text |

#### `after_step` (Check After)

| Value | Meaning |
|-------|---------|
| `0` | After all steps complete |
| `N` (1-based) | After step number **N** in the TC's `steps` array |

Expectations with `enabled: false` are not evaluated.

---

## 6. Excel format (TC File import/export)

File: **Import → TC File (Excel)** / **Export → TC File as Excel**

Three sheets:

### Sheet 1: `Test Cases`

Headers (row 1):

```
Active | NO. TC | Description | Application | URL | Username | Password | Expectation | Notes | ID
```

- **Active**: `ENABLE` or `DISABLE`
- **ID**: internal id (optional on import; auto-generated if empty)

### Sheet 2: `Steps`

Headers:

```
NO. TC | # | Active | Type | Step | Selector | Value | URL | Key | Checked | Delay | Tag | ID
```

- **NO. TC**: links row to Test Cases sheet
- **#**: step order (1, 2, 3…)
- **Type**: `goto`, `click`, `fill`, `select`, `check`, `press`, `wait`
- **Step**: maps to `label` field
- **Checked**: `TRUE`, `FALSE`, or empty
- **Delay**: milliseconds (`delay_ms`)

### Sheet 3: `Expectations`

Headers:

```
NO. TC | # | Active | Label | Selector | Type | Comparison | Expected Value | Attribute | Check After | Tag | Sample | ID
```

- **Type**: `text`, `value`, `visible`, `attribute`, `checked`
- **Comparison**: `equals`, `contains`, `regex`
- **Check After**: integer step index (0 = end)

### Excel import aliases (legacy headers still accepted)

| Header variants | Maps to |
|-----------------|---------|
| Active, Enabled, Aktif | `enabled` |
| Description, Deskripsi | `deskripsi` |
| Application, Aplikasi | `aplikasi` |
| Expectation, Ekspetasi, Expected Result | `expected_result` |
| #, Urutan, Order | `urutan` |
| Step, Keterangan | `label` (steps) |
| Comparison, Banding, Match | `match` |
| Check After, After Step | `after_step` |

---

## 7. Run result export (Excel / PDF)

**Export → TC Result as Excel / Pdf**

Headers match the TC list:

```
Active | NO. TC | Description | Application | URL | Username | Password | Expectation | Expected Result | Status | Notes
```

- **Expected Result** column = bullet list of automated expectation summaries.
- **Status**: `OK`, `NOK`, or `BELUM DIUJI` (not yet run).

---

## 8. Execution & pass/fail rules

1. Only **enabled** test cases run (Run All / Run Until skip disabled TCs).
2. Runner executes **enabled** steps in order.
3. After step `N`, all expectations with `after_step <= N` and `after_step > 0` are checked.
4. Remaining expectations (`after_step == 0` or not yet triggered) run at the end.
5. TC **OK** if all evaluated expectations pass; otherwise **NOK** with reasons in `notes`.
6. On failure, screenshot saved under `%APPDATA%\JAQA\screenshots\`.

**Minimum to run a TC:** at least one step in `steps[]` (recording usually creates these).

---

## 9. Complete JSON example (login flow)

```json
{
  "app": "JAQA",
  "version": "1.0",
  "name": "Portal Login SIT",
  "test_cases": [
    {
      "no_tc": "TC-LOGIN-001",
      "deskripsi": "Valid login redirects to dashboard",
      "aplikasi": "Portal",
      "url": "https://10.132.130.195/mandiri/jetsnetterminal/",
      "username": "sit.user",
      "password": "P@ssw0rd",
      "expected_result": "User sees dashboard after login",
      "enabled": true,
      "steps": [
        {
          "type": "goto",
          "url": "https://10.132.130.195/mandiri/jetsnetterminal/",
          "label": "Open login page",
          "enabled": true
        },
        {
          "type": "fill",
          "selector": "#username",
          "value": "sit.user",
          "label": "Username",
          "delay_ms": 300,
          "enabled": true
        },
        {
          "type": "fill",
          "selector": "#password",
          "value": "P@ssw0rd",
          "label": "Password",
          "delay_ms": 300,
          "enabled": true
        },
        {
          "type": "click",
          "selector": "button[type=submit]",
          "label": "Login button",
          "delay_ms": 1000,
          "enabled": true
        }
      ],
      "expectations": [
        {
          "label": "Dashboard heading",
          "selector": "h1.dashboard-title",
          "kind": "text",
          "match": "contains",
          "expected_value": "Dashboard",
          "after_step": 4,
          "enabled": true
        },
        {
          "label": "Welcome message visible",
          "selector": ".welcome-banner",
          "kind": "visible",
          "match": "contains",
          "expected_value": "true",
          "after_step": 0,
          "enabled": true
        }
      ]
    }
  ]
}
```

---

## 10. AI workflow: how to build a TC list

### Step A — Gather inputs

- Application name, base URL, credentials (if any).
- User journey per TC (happy path + key negatives).
- DOM selectors (from dev tools, accessibility tree, or prior recording export).

### Step B — Design test cases

For each scenario:

1. Assign **`no_tc`** (unique, stable), e.g. `TC-MODULE-001`.
2. Fill metadata: **Description**, **Application**, **URL**, **Expectation** (manual).
3. Set **`enabled: true`** unless the TC is draft.

### Step C — Define Record Steps

Order matters. Typical pattern:

```
goto → fill credentials → click login → wait (optional) → further actions
```

Rules:

- Use stable selectors (`#id`, `[data-testid=...]`, `role=button[name=...]`).
- Put waits in `delay_ms` on prior step or explicit `wait` step.
- Mark exploratory steps `enabled: false` to keep them documented but skipped.

### Step D — Define Expected Results

- One assertion per UI outcome.
- Use `after_step` to tie checks to the correct point in the flow.
- Prefer `contains` over `equals` for dynamic text.

### Step E — Output file

**Option 1 — JSON (easiest for AI):**

```python
import json
from app.core.models import TestSuite, TestCase, Step, Expectation

suite = TestSuite(name="Generated Suite", test_cases=[...])
path.write_text(json.dumps(suite.to_dict(), ensure_ascii=False, indent=2))
```

**Option 2 — Excel:** use headers from section 6 exactly, or export a template from JAQA and fill rows.

### Step F — Validate before delivery

- [ ] Every `no_tc` unique.
- [ ] Steps sheet / array: every row references existing `no_tc`.
- [ ] Each runnable TC has ≥ 1 enabled step.
- [ ] Selectors non-empty for non-`goto` steps.
- [ ] Expectations have `selector` + `expected_value` (except some `visible` cases).
- [ ] URLs include `https://` for internal/VPN hosts (JAQA ignores invalid SSL certs by default).

---

## 11. Selector guidelines for AI

JAQA uses **Playwright** locators (`.first` on all selectors).

**Prefer (stable → fragile):**

1. `#elementId`
2. `[data-testid="login-submit"]`
3. `[name="username"]`
4. `role=button[name="Sign in"]`
5. `text=Submit` (breaks on i18n)

**Avoid:**

- Long absolute XPath unless no alternative.
- Class names that look generated (`css-1a2b3c`).

**Internal / VPN HTTPS:** JAQA launches Chrome with `--ignore-certificate-errors` and `ignore_https_errors=True` for self-signed certificates.

---

## 12. Enable / Disable semantics

| Level | Field | Effect |
|-------|-------|--------|
| Test Case | `enabled` | Entire TC skipped in batch run |
| Record Step | `enabled` | Step not executed; step index unchanged |
| Expected Result | `enabled` | Assertion not evaluated |

Excel **Active** column: `ENABLE` / `DISABLE`.

JSON: boolean `true` / `false`.

---

## 13. Browser session (optional)

TC may store imported session data:

- `browser_cookies`: Playwright cookie dict list.
- `browser_storage_state`: Playwright `storage_state` object.

Used to skip login when cookies/session copied via **Toolbox → Copy Cookies / Copy Session**. AI-authored files usually leave these empty.

---

## 14. Clipboard formats (UI copy/paste)

When users copy steps/expectations inside JAQA GUI:

| List | Clipboard JSON key |
|------|-------------------|
| Steps | `jaqa_steps` |
| Expectations | `jaqa_expectations` |

AI-generated bulk data should use full suite JSON/Excel instead.

---

## 15. File locations (runtime)

| Path | Content |
|------|---------|
| `%APPDATA%\JAQA\session.json` | Auto-saved last session |
| `%APPDATA%\JAQA\last_config.txt` | Path to last opened JSON file |
| `%APPDATA%\JAQA\reports\` | Exported Excel/PDF |
| `%APPDATA%\JAQA\screenshots\` | Failure screenshots |

---

## 16. Minimal TC (metadata only, needs recording in UI)

```json
{
  "no_tc": "TC-DRAFT-001",
  "deskripsi": "To be recorded",
  "aplikasi": "MyApp",
  "url": "https://example.com",
  "expected_result": "TBD",
  "steps": [],
  "expectations": []
}
```

User selects TC in JAQA → **RECORD** → performs actions → **EXPECTED RESULT** → stop record.

---

## 17. Checklist for AI-generated suites

```markdown
## Suite QA checklist
- [ ] Suite has `app: "JAQA"` and meaningful `name`
- [ ] All TC have unique `no_tc`
- [ ] URLs valid; VPN/internal hosts use https://
- [ ] Steps ordered; types valid
- [ ] Disabled items intentional
- [ ] Expectations linked via `after_step`
- [ ] No secrets in repo unless intended (password fields are plain text in JSON)
- [ ] File imports cleanly: File → Open (JSON) or Import → TC File (Excel)
```

---

## 18. Programmatic import (Python)

```python
from pathlib import Path
from app.core.storage import import_json, export_json
from app.core.reporter import import_tc_excel, export_tc_excel

# JSON
suite = import_json(Path("generated_suite.json"))

# Excel
suite = import_tc_excel(Path("generated_suite.xlsx"))

# Re-export to verify round-trip
export_json(suite, Path("roundtrip.json"))
export_tc_excel(suite, Path("roundtrip.xlsx"))
```

Run from project root with venv:

```bat
.venv\Scripts\python.exe -c "from app.core.storage import import_json; print(import_json('suite.json').name)"
```

---

## 19. Glossary

| Term | Meaning |
|------|---------|
| **TC** | Test Case — one scenario |
| **Record Step** | Automated browser action |
| **Expectation** | Manual text field on TC (`expected_result`) |
| **Expected Result** | Automated assertion (`expectations[]`) |
| **Active** | Enabled flag (green = on, gray = off in UI) |
| **SIT** | System Integration Test |

---

## 20. Version

Document aligned with JAQA codebase as of **2026-08-24**.

When the application changes, re-read:

- `app/core/models.py` — schema & column labels
- `app/core/reporter.py` — Excel headers & import aliases
- `app/core/engine.py` — runtime behavior

---

*End of JAQA AI Guide*
