# CI Feature Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `qav-collector import-features` CI command keeps test cases in sync with the
repository's `.feature` files. It authenticates with the project's API key, which ingestion trades
for a short-lived service token. A server-side guard stops mass archives.

**Architecture:**
- ingestion gains `POST /api/v1/collect/token`. It signs a 5-minute JWT with the shared
  `SECRET_KEY`, whose `sub` is not numeric and whose scope is `cases:import`.
- test-management's import route accepts that token through a new dependency, without asking
  project-service. Every other route still requires a numeric `sub`, so the token is 401 there.
- The planner's summary gains `mass_archive`. A real full import that would archive more than half
  of the live imported cases is 409 unless `allow_mass_archive` is set.
- The collector gets a new `features.py` module, reusing `upload._send` / `make_context` /
  `ci.detect` / `config_file`.

**Tech Stack:**
- Python 3.11, FastAPI, PyJWT 2.8, SQLAlchemy, pytest + respx.
- Collector: stdlib only (urllib); tests use the `platform` fake HTTP server.
- Dashboard: React + TS, vitest + msw.
- Gateway: bash smoke.

**Spec:** `docs/superpowers/specs/2026-10-06-ci-feature-import-design.md` (also read ADR-023,
`docs/architecture/adr/ADR-023-gherkin-import.md`).

## Global Constraints

- Token endpoint: `POST /api/v1/collect/token`, authenticated with `Authorization: Bearer qav_…` via the existing `get_api_key`.
- Token response: `{"token": "<jwt>", "expires_in": 300, "project_id": <id>}`.
- JWT claims, exactly: `sub = "apikey:<api key id>"`, `project_id`, `organization_id`, `scope = "cases:import"`, `token_type = "service"`, `iat`, `exp = iat + 300 s`. Signed with `settings.SECRET_KEY`, `settings.ALGORITHM`.
- Token use: the service token is accepted ONLY by `POST /api/v1/projects/{id}/cases/import`, and only when `token_type == "service"`, `scope == "cases:import"` and `project_id == {id}`.
  - Wrong project: 404 `"Project not found"`.
  - Wrong or missing scope, or a non-numeric `sub` on any other route: 401.
- Changes made with a service token have `created_by` / `updated_by` = `0` (CI).
- Mass archive: `full=true` and `archived * 2 > live`, where `live = archived + unchanged + updated + moved`, and `live > 0`.
  - A dry-run summary carries `"mass_archive": true|false`.
  - A real import is 409 `{"code": "mass_archive", "message", "archived", "live"}` unless the body has `allow_mass_archive: true`.
- CLI: `qav-collector import-features [PATTERN ...] [--branch NAME] [--no-full] [--allow-mass-archive] [--strict] [--dry-run] [--url URL] [--ca-file FILE]`.
  - Patterns default to `.qav.yml` `features:`, then `**/*.feature`.
  - The sync branch defaults to `$QAV_IMPORT_BRANCH`, then `master`. On another detected branch it prints `skipped: on <branch>; cases sync from <name>` and exits 0.
  - The API key comes from `$QAV_API_KEY` only.
- CLI exit codes:
  - 0: imported, skipped, or parse errors without `--strict`.
  - 1: network/TLS failure, 401/403/404, 409, 413, or parse errors with `--strict`.
  - 2: configuration error (no URL, no key, no files matched, unreadable file).
- Collector version `0.3.0`; the dashboard pins `COLLECTOR_REF = "collector-v0.3.0"`.
- Commits end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Work on master, never push.
- Never run two pytest processes in `platforms/test-management-service` at once (they share `./test.db`).
- Before any dashboard UI edit, invoke the `ui-ux-pro-max` skill (project rule).
- Before reporting done, run every CI step for what you touched. For the dashboard that is `npm run lint`, `npm run typecheck`, `npx vitest run` and `npm run build`; for Python, the service's pytest.

## Review Focus

1. **The service token on ingestion's own user routes.** It must be 401, not a crash and not
   access. Pinned in Task 1 (`test_the_import_token_opens_no_ingestion_route`).
2. **A token for project 7 used on project 8.** It must be 404 with no project-service call.
   Pinned in Task 2 (`test_a_token_for_another_project_is_404`).
3. **Exactly half archived** (2 of 4) **is allowed**, because the rule is "more than half". Pinned
   in Task 2 (`test_archiving_exactly_half_is_not_a_mass_archive`).
4. **A GitHub pull-request build.** `GITHUB_HEAD_REF` is the feature branch, so the command skips
   and exits 0. Pinned in Task 3 (`test_a_pull_request_build_skips`).
5. **A `.feature` file that is not valid UTF-8.** The CLI exits 2 and names the file, without a
   traceback. Pinned in Task 3 (`test_an_unreadable_file_is_a_configuration_error`).

---

## File Structure

| File | Change |
|---|---|
| `platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py` | Modify: `POST /token` |
| `platforms/ingestion-service/tests/integration/test_collect_token.py` | Create |
| `platforms/test-management-service/src/casebook/api/deps.py` | Modify: `require_import_access`, `CI_USER_ID`, `IMPORT_SCOPE` |
| `platforms/test-management-service/src/casebook/gherkin_import/plan.py` | Modify: `is_mass_archive()` |
| `platforms/test-management-service/src/casebook/schemas/case_import.py` | Modify: `allow_mass_archive` |
| `platforms/test-management-service/src/casebook/api/v1/endpoints/case_import.py` | Modify: new dependency, mass guard, `mass_archive` in the summary |
| `platforms/test-management-service/tests/integration/test_import_ci.py` | Create |
| `collector/src/qav_collector/features.py` | Create |
| `collector/src/qav_collector/cli.py` | Modify: `import-features` parser and dispatch |
| `collector/src/qav_collector/config_file.py` | Modify: `features` list key |
| `collector/src/qav_collector/__init__.py` | Modify: `__version__ = "0.3.0"` |
| `collector/tests/test_features.py` | Create |
| `collector/README.md` | Modify |
| `dashboard/src/api/cases.ts` | Modify: `allowMassArchive`, `summary.mass_archive` |
| `dashboard/src/pages/CaseImportPage.tsx` | Modify: server flag, send `allow_mass_archive` |
| `dashboard/src/pages/CaseImport.test.tsx` | Modify |
| `dashboard/src/pages/ProjectSettingsPage.tsx` + its test | Modify: snippets, `collector-v0.3.0` |
| `scripts/smoke_gateway.sh` | Modify |
| `docs/architecture/adr/ADR-024-service-tokens-for-ci-imports.md`, `INDEX.md`, `ADR-023-gherkin-import.md` | Create / modify |
| Service READMEs, spec, `TODO.md` | Modify |

---

### Task 1: ingestion trades an API key for an import token

**Files:**
- Modify: `platforms/ingestion-service/src/ingestion/api/v1/endpoints/collect.py`
- Test: `platforms/ingestion-service/tests/integration/test_collect_token.py`

**Interfaces:**
- Produces: `POST /api/v1/collect/token`, which returns `{"token": str, "expires_in": 300, "project_id": int}`. The claims are listed in Global Constraints.

- [ ] **Step 1: Write the failing tests** in `tests/integration/test_collect_token.py`

```python
"""POST /collect/token: a project's API key traded for a 5-minute import token (ADR-024)."""
import jwt
import pytest

from src.ingestion.core.config import settings

URL = "/api/v1/collect/token"


def bearer(key):
    return {"Authorization": f"Bearer {key}"}


def test_a_key_is_traded_for_a_short_import_token(client, make_key, db):
    row, key = make_key(project_id=7, organization_id=3)
    response = client.post(URL, headers=bearer(key))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expires_in"] == 300 and body["project_id"] == 7
    claims = jwt.decode(body["token"], settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    assert claims["sub"] == f"apikey:{row.id}"
    assert (claims["project_id"], claims["organization_id"]) == (7, 3)
    assert (claims["scope"], claims["token_type"]) == ("cases:import", "service")
    assert claims["exp"] - claims["iat"] == 300
    db.refresh(row)
    assert row.last_used_at is not None


@pytest.mark.parametrize("headers", [{}, bearer("not-a-key"), bearer("qav_unknown_key_000000")])
def test_no_valid_key_is_401(client, headers):
    assert client.post(URL, headers=headers).status_code == 401


def test_a_revoked_key_gets_no_token(client, make_key):
    _, key = make_key(revoked=True)
    assert client.post(URL, headers=bearer(key)).status_code == 401


def test_the_import_token_opens_no_ingestion_route(client, make_key):
    _, key = make_key(project_id=7)
    token = client.post(URL, headers=bearer(key)).json()["token"]
    assert client.get("/api/v1/projects/7/runs", headers=bearer(token)).status_code == 401
```

- [ ] **Step 2: Run the tests and check they fail**

Run, from `platforms/ingestion-service`: `SECRET_KEY=test .venv/Scripts/python -m pytest -q tests/integration/test_collect_token.py`
Expected: the first and revoked tests FAIL with 404 or 405 (no route). The last test may fail
differently.

- [ ] **Step 3: Implement.** In `collect.py`, add these imports if they are missing:
`from datetime import datetime, timedelta, timezone`, `import jwt`,
`from src.ingestion.core.config import settings`. Then add:

```python
SERVICE_TOKEN_SECONDS = 300
IMPORT_SCOPE = "cases:import"


@router.post("/token")
def import_token(db: Session = Depends(get_db), key: ApiKey = Depends(get_api_key)):
    """Trades the project's API key for a 5-minute token that test-management accepts on its
    import route only (ADR-024). `sub` is not a number, so every user route rejects it."""
    now = datetime.now(timezone.utc)
    claims = {
        "sub": f"apikey:{key.id}", "project_id": key.project_id, "organization_id": key.organization_id,
        "scope": IMPORT_SCOPE, "token_type": "service",
        "iat": now, "exp": now + timedelta(seconds=SERVICE_TOKEN_SECONDS),
    }
    key.last_used_at = now
    db.commit()
    return {
        "token": jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM),
        "expires_in": SERVICE_TOKEN_SECONDS, "project_id": key.project_id,
    }
```

`get_db` and `Session` are already imported in `collect.py`, because `collect_run` uses them.
Check that, and import them from where `collect_run` gets them if they are not.

If `test_the_import_token_opens_no_ingestion_route` fails with a 500, ingestion's user-token
dependency crashes on a non-numeric `sub`. Find it (search `int(` near `decode_token` under
`src/ingestion/api`) and make it answer 401 for `ValueError`/`KeyError`/`TypeError`, exactly as
test-management's `get_caller` does.

- [ ] **Step 4: Run the tests and check they pass**

Run: the same file, then the whole suite with `SECRET_KEY=test .venv/Scripts/python -m pytest -q`.
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add platforms/ingestion-service
git commit -m "feat(ingestion): trade a project API key for a 5-minute import token

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: test-management accepts the token on imports, and refuses mass archives

**Files:**
- Modify: `platforms/test-management-service/src/casebook/api/deps.py`
- Modify: `platforms/test-management-service/src/casebook/gherkin_import/plan.py`
- Modify: `platforms/test-management-service/src/casebook/schemas/case_import.py`
- Modify: `platforms/test-management-service/src/casebook/api/v1/endpoints/case_import.py`
- Test: `platforms/test-management-service/tests/integration/test_import_ci.py`

**Interfaces:**
- Consumes: the token claims from Task 1.
- Produces:
  - `deps.require_import_access(project_id, token) -> ProjectAccess`, where `user_id = 0` for service tokens;
  - `deps.CI_USER_ID = 0`;
  - `plan.is_mass_archive(summary: dict, full: bool) -> bool`;
  - `ImportRequest.allow_mass_archive: bool = False`;
  - the response `summary["mass_archive"]: bool`;
  - 409 `detail = {"code": "mass_archive", "message": str, "archived": int, "live": int}`.

- [ ] **Step 1: Write the failing tests** in `tests/integration/test_import_ci.py`

```python
"""The import route with a CI service token (ADR-024), and the mass-archive guard (ADR-023)."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from src.casebook.core.config import settings
from src.casebook.models import Case

URL = "/api/v1/projects/1/cases/import"
ONE = "Feature: A\n  Scenario: one\n    Given x\n"


def service(project_id=1, scope="cases:import", token_type="service"):
    claims = {"sub": "apikey:9", "project_id": project_id, "organization_id": 10, "scope": scope,
              "token_type": token_type, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    return {"Authorization": f"Bearer {jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)}"}


def body(*files, **extra):
    return {"files": [{"path": p, "content": c} for p, c in files], **extra}


def feature(*names):
    return "Feature: F\n" + "".join(f"  Scenario: {n}\n    Given {n}\n" for n in names)


@pytest.fixture
def member(project_role):
    project_role("member")


# --- service token ---------------------------------------------------------------------------

def test_a_service_token_imports_without_asking_project_service(client, http, db):
    r = client.post(URL, json=body(("a.feature", ONE)), headers=service())
    assert r.status_code == 200, r.text
    assert db.query(Case).one().created_by == 0
    assert not http.calls  # the respx router saw no request to project-service


def test_a_token_for_another_project_is_404(client, http):
    assert client.post(URL, json=body(("a.feature", ONE)), headers=service(project_id=2)).status_code == 404
    assert not http.calls


@pytest.mark.parametrize("headers", [service(scope="cases:read"), service(scope=None), service(token_type="access")])
def test_a_token_without_the_import_scope_is_401(client, headers):
    assert client.post(URL, json=body(("a.feature", ONE)), headers=headers).status_code == 401


@pytest.mark.parametrize("method, path", [("get", "/api/v1/projects/1/cases"),
                                          ("patch", "/api/v1/projects/1/cases/1"),
                                          ("get", "/api/v1/projects/1/suites")])
def test_the_service_token_opens_no_other_route(client, method, path):
    kwargs = {"json": {"priority": "high"}} if method == "patch" else {}
    assert getattr(client, method)(path, headers=service(), **kwargs).status_code == 401


def test_a_user_token_still_imports(client, auth, member):
    assert client.post(URL, json=body(("a.feature", ONE)), headers=auth()).status_code == 200


def test_ci_updates_are_recorded_as_user_0(client, auth, member, db):
    client.post(URL, json=body(("a.feature", ONE)), headers=auth())
    client.post(URL, json=body(("a.feature", ONE.replace("Given x", "Given y"))), headers=service())
    assert db.query(Case).one().updated_by == 0


# --- mass-archive guard ----------------------------------------------------------------------

def test_a_full_import_archiving_most_cases_is_refused_unless_allowed(client, auth, member, db):
    client.post(URL, json=body(("a.feature", feature("a1", "a2")), ("b.feature", feature("b1"))), headers=auth())
    dry = client.post(f"{URL}?dry_run=true", json=body(("b.feature", feature("b1")), full=True), headers=auth())
    assert dry.json()["summary"]["mass_archive"] is True
    refused = client.post(URL, json=body(("b.feature", feature("b1")), full=True), headers=auth())
    assert refused.status_code == 409
    assert refused.json()["detail"] | {"message": ""} == {"code": "mass_archive", "message": "", "archived": 2, "live": 3}
    assert db.query(Case).filter(Case.status == "archived").count() == 0
    allowed = client.post(URL, json=body(("b.feature", feature("b1")), full=True, allow_mass_archive=True), headers=auth())
    assert allowed.status_code == 200 and allowed.json()["summary"]["archived"] == 2


def test_archiving_exactly_half_is_not_a_mass_archive(client, auth, member):
    client.post(URL, json=body(("a.feature", feature("a1", "a2")), ("b.feature", feature("b1", "b2"))), headers=auth())
    r = client.post(URL, json=body(("b.feature", feature("b1", "b2")), full=True), headers=auth())
    assert r.status_code == 200 and r.json()["summary"]["archived"] == 2
    assert r.json()["summary"]["mass_archive"] is False


def test_without_full_there_is_no_mass_archive(client, auth, member):
    client.post(URL, json=body(("a.feature", feature("a1", "a2", "a3"))), headers=auth())
    r = client.post(URL, json=body(("a.feature", feature("a1"))), headers=auth())
    assert r.status_code == 200 and r.json()["summary"]["archived"] == 2
    assert r.json()["summary"]["mass_archive"] is False


def test_a_first_full_import_is_never_a_mass_archive(client, auth, member):
    r = client.post(URL, json=body(("a.feature", ONE), full=True), headers=auth())
    assert r.status_code == 200 and r.json()["summary"]["mass_archive"] is False
```

Before relying on `http.calls`, check the `http` fixture in `tests/conftest.py`. It yields a
`respx` router, and `router.calls` lists every request it intercepted. `assert_all_called=False`
lets unrouted requests raise, which would also fail the test. Either way a project-service call is
caught.

- [ ] **Step 2: Run the tests and check they fail**

Run, from `platforms/test-management-service`: `SECRET_KEY=test .venv/Scripts/python -m pytest -q tests/integration/test_import_ci.py`
Expected: FAIL. The service-token tests get 401, because `get_caller` does `int("apikey:9")`. The
mass-archive tests fail on the missing `mass_archive` key.

- [ ] **Step 3: Implement**

In `api/deps.py`, add after `check_project_role`:

```python
IMPORT_SCOPE = "cases:import"
CI_USER_ID = 0  # created_by / updated_by for changes made by a CI service token (ADR-024)


def require_import_access(project_id: int, token: str = Depends(oauth2_scheme)) -> ProjectAccess:
    """The import route's callers: an editor's JWT, or the 5-minute service token ingestion trades
    for the project's API key (ADR-024). Only this route accepts the service token."""
    if token is None:
        raise _unauthorized()
    try:
        claims = decode_token(token)
    except ValueError:
        raise _unauthorized()
    if claims.get("token_type") == "service":
        if claims.get("scope") != IMPORT_SCOPE:
            raise _unauthorized()
        if claims.get("project_id") != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        return ProjectAccess(project_id=project_id, organization_id=int(claims.get("organization_id") or 0),
                             user_id=CI_USER_ID, role="ci")
    try:
        caller = Caller(user_id=int(claims["sub"]), token=token)
    except (KeyError, TypeError, ValueError):
        raise _unauthorized()
    return check_project_role(project_id, caller, EDIT_ROLES, "Project not found")
```

Add `"require_import_access", "CI_USER_ID", "IMPORT_SCOPE"` to `__all__`.

A token with `token_type == "access"` and `sub == "apikey:9"` falls through to the user path, and
`int()` makes it 401. That is the parametrized case.

In `gherkin_import/plan.py`, add after `plan_hash`:

```python
def is_mass_archive(summary: dict, full: bool) -> bool:
    """A full import that would archive more than half of the imported cases that are live today
    (each of them is in a full plan as unchanged, updated, moved or archived). ADR-023."""
    live = summary["archived"] + summary["unchanged"] + summary["updated"] + summary["moved"]
    return full and live > 0 and summary["archived"] * 2 > live
```

In `schemas/case_import.py` `ImportRequest`, add `allow_mass_archive: bool = False` after `full`.

In `api/v1/endpoints/case_import.py`:
- import `require_import_access` (and drop `EDIT_ROLES` / `require_project_role` if they are now unused);
- import `from src.casebook.gherkin_import.plan import is_mass_archive`;
- change `_out` to take `full` and add the flag:

```python
def _out(plan, full: bool) -> dict:
    issue = lambda i: {"path": i.path, "line": i.line, "message": i.message}  # noqa: E731
    summary = plan.summary()
    summary["mass_archive"] = is_mass_archive(summary, full)
    return {
        "plan_hash": plan.plan_hash, "summary": summary,
        "items": [{"action": i.action, "path": i.path, "scenario": i.scenario, "case_number": i.case_number}
                  for i in plan.items],
        "errors": [issue(e) for e in plan.errors], "warnings": [issue(w) for w in plan.warnings],
    }
```

- change the dependency to `access: ProjectAccess = Depends(require_import_access),`;
- pass `payload.full` to both `_out(...)` calls;
- after the `plan_changed` check and before `apply_plan`, add:

```python
    summary = plan.summary()
    if is_mass_archive(summary, payload.full) and not payload.allow_mass_archive:
        live = summary["archived"] + summary["unchanged"] + summary["updated"] + summary["moved"]
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
            "code": "mass_archive", "archived": summary["archived"], "live": live,
            "message": f"This would archive {summary['archived']} of {live} imported cases. "
                       "Check the folder and path prefix, or allow the mass archive to go ahead.",
        })
```

`ImportResult.summary` is typed `dict`, so a boolean value validates. If it is
`Dict[str, int]`, widen it to `dict`.

- [ ] **Step 4: Run the tests and check they pass**

Run: the new file, then the whole service suite. The existing `test_import.py` must still pass:
it uses user tokens, and its summaries now carry one extra key.
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add platforms/test-management-service
git commit -m "feat(test-management): CI service tokens may import; full imports that archive most cases need allow_mass_archive

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: `qav-collector import-features`

**Files:**
- Create: `collector/src/qav_collector/features.py`
- Modify: `collector/src/qav_collector/cli.py` (parser and dispatch), `config_file.py` (`LIST_KEYS`), `__init__.py` (`0.3.0`)
- Test: `collector/tests/test_features.py`
- Modify: `collector/README.md`

**Interfaces:**
- Consumes:
  - `POST /api/v1/collect/token` (Task 1);
  - `POST /api/v1/projects/{id}/cases/import?dry_run=` with `full`, `allow_mass_archive` (Task 2);
  - `upload._send(endpoint, body, headers, context) -> (status, bytes, headers)`, which raises only `OSError` / `http.client.HTTPException`;
  - `upload.make_context(ca_file, client_cert=None, client_key=None)`;
  - `upload.endpoint_for(url)`, which returns `url.rstrip("/") + COLLECT_PATH` or raises `ConfigError`;
  - `ci.detect(env).branch`;
  - `config_file.load_config(directory)`.
- Produces: `features.run(args, env, api_key, say, cwd) -> int`.

- [ ] **Step 1: Read** `collector/tests/conftest.py` (the `platform` fixture: `.url`, `.reply(status, body)`, `.requests` with `path`/`headers`/`body`), `ci.py` (which env vars make GitHub detection kick in) and `cli.py` `main()`. Match their conventions.

- [ ] **Step 2: Write the failing tests** in `collector/tests/test_features.py`

```python
"""qav-collector import-features (ADR-024)."""
import json

import pytest

from qav_collector.cli import main

KEY = "qav_test_key_123"
GRANT = {"token": "t0k", "expires_in": 300, "project_id": 7}
SUMMARY = {"created": 1, "updated": 0, "moved": 0, "reactivated": 0, "archived": 0, "unchanged": 0,
           "skipped": 0, "mass_archive": False}
RESULT = {"plan_hash": "a" * 64, "summary": SUMMARY,
          "items": [{"action": "create", "path": "features/a.feature", "scenario": "S", "case_number": 1}],
          "errors": [], "warnings": []}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / "features" / "sub").mkdir(parents=True)
    (tmp_path / "features" / "a.feature").write_text("Feature: A\n  Scenario: S\n    Given x\n", encoding="utf-8")
    (tmp_path / "features" / "sub" / "b.feature").write_text("Feature: B\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def env(platform, **extra):
    return {"QAV_URL": platform.url, "QAV_API_KEY": KEY, **extra}


def sent(platform, i):
    return json.loads(platform.requests[i]["body"])


def test_it_trades_the_key_then_runs_a_full_import(platform, repo):
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    assert main(["import-features"], env(platform)) == 0
    token, imp = platform.requests
    assert token["path"] == "/api/v1/collect/token"
    assert token["headers"]["Authorization"] == f"Bearer {KEY}"
    assert imp["path"] == "/api/v1/projects/7/cases/import?dry_run=false"
    assert imp["headers"]["Authorization"] == "Bearer t0k"
    body = sent(platform, 1)
    assert [f["path"] for f in body["files"]] == ["features/a.feature", "features/sub/b.feature"]
    assert body["full"] is True and "allow_mass_archive" not in body


def test_flags_reach_the_request(platform, repo):
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    assert main(["import-features", "features/*.feature", "--no-full", "--allow-mass-archive"], env(platform)) == 0
    body = sent(platform, 1)
    assert [f["path"] for f in body["files"]] == ["features/a.feature"]
    assert body["full"] is False and body["allow_mass_archive"] is True


def test_qav_yml_features_are_the_default_patterns(platform, repo):
    (repo / ".qav.yml").write_text("features:\n  - features/sub/*.feature\n", encoding="utf-8")
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    assert main(["import-features"], env(platform)) == 0
    assert [f["path"] for f in sent(platform, 1)["files"]] == ["features/sub/b.feature"]


def test_a_pull_request_build_skips(platform, repo, capsys):
    ci = {"GITHUB_ACTIONS": "true", "GITHUB_REF_NAME": "12/merge", "GITHUB_HEAD_REF": "feature-x"}
    assert main(["import-features"], env(platform, **ci)) == 0
    assert platform.requests == []
    assert "skipped: on feature-x; cases sync from master" in capsys.readouterr().out


def test_the_sync_branch_can_be_named(platform, repo):
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    ci = {"GITHUB_ACTIONS": "true", "GITHUB_REF_NAME": "main"}
    assert main(["import-features", "--branch", "main"], env(platform, **ci)) == 0
    assert len(platform.requests) == 2


def test_dry_run_asks_for_a_plan_and_prints_it(platform, repo, capsys):
    platform.reply(200, GRANT)
    platform.reply(200, RESULT)
    assert main(["import-features", "--dry-run"], env(platform)) == 0
    assert platform.requests[1]["path"].endswith("dry_run=true")
    out = capsys.readouterr().out
    assert "would import: 1 created" in out and "features/a.feature" in out


def test_a_refused_mass_archive_fails_the_build(platform, repo, capsys):
    platform.reply(200, GRANT)
    platform.reply(409, {"detail": {"code": "mass_archive", "message": "This would archive 9 of 10 imported cases.",
                                    "archived": 9, "live": 10}})
    assert main(["import-features"], env(platform)) == 1
    assert "This would archive 9 of 10" in capsys.readouterr().out


def test_a_bad_key_fails_the_build(platform, repo):
    platform.reply(401, {"detail": "Invalid API key"})
    assert main(["import-features"], env(platform)) == 1


def test_parse_errors_fail_only_with_strict(platform, repo):
    broken = {**RESULT, "errors": [{"path": "features/sub/b.feature", "line": 2, "message": "(2:1): expected"}]}
    for argv, code in ((["import-features"], 0), (["import-features", "--strict"], 1)):
        platform.reply(200, GRANT)
        platform.reply(200, broken)
        assert main(argv, env(platform)) == code


@pytest.mark.parametrize("environment", [{"QAV_API_KEY": KEY}, {"QAV_URL": "https://qav.example"}])
def test_missing_url_or_key_is_a_configuration_error(repo, environment):
    assert main(["import-features"], environment) == 2


def test_no_matching_files_is_a_configuration_error(platform, repo):
    assert main(["import-features", "nothing/**/*.feature"], env(platform)) == 2


def test_an_unreadable_file_is_a_configuration_error(platform, repo, capsys):
    (repo / "features" / "latin.feature").write_bytes(b"Feature: caf\xe9\n")
    assert main(["import-features"], env(platform)) == 2
    assert "latin.feature" in capsys.readouterr().out
```

If `ci.detect` needs different environment variables to recognise GitHub, adjust the `ci` dicts
in the tests to what `ci.py` reads. If `_Output` writes to stderr rather than stdout, read `.err`.
Do not change the behaviour being asserted.

- [ ] **Step 3: Run the tests and check they fail**

Run, from `collector/`: `.venv/Scripts/python -m pytest -q tests/test_features.py`
Expected: FAIL with argparse "invalid choice: 'import-features'" (exit 2 on every test).

- [ ] **Step 4: Implement** `collector/src/qav_collector/features.py`

```python
"""qav-collector import-features: keep test cases in sync with the repository's .feature files.

The API key is traded for a 5-minute import token (ADR-024); the import is full by default, so
cases of deleted files are archived, and the server refuses a mass archive unless allowed."""
from __future__ import annotations

import glob
import http.client
import json
import os
from typing import Callable, Dict, List, Mapping, Optional

from qav_collector.ci import detect
from qav_collector.config_file import load_config
from qav_collector.upload import COLLECT_PATH, ConfigError, _send, endpoint_for, make_context

TOKEN_PATH = "/api/v1/collect/token"
DEFAULT_BRANCH = "master"
DEFAULT_PATTERNS = ["**/*.feature"]
SHOWN_ERRORS = 5


class ImportFailed(Exception):
    pass


def base_url(url: str) -> str:
    return endpoint_for(url)[: -len(COLLECT_PATH)]


def collect_files(patterns: List[str], cwd: str) -> List[Dict[str, str]]:
    paths = sorted({os.path.normpath(p) for pattern in patterns
                    for p in glob.glob(os.path.join(cwd, pattern), recursive=True) if os.path.isfile(p)})
    files = []
    for path in paths:
        relative = os.path.relpath(path, cwd).replace(os.sep, "/")
        try:
            with open(path, encoding="utf-8") as fh:
                files.append({"path": relative, "content": fh.read()})
        except (OSError, UnicodeDecodeError) as exc:
            raise ConfigError(f"cannot read {relative} as UTF-8 text: {exc}") from exc
    return files


def _detail(raw: bytes) -> str:
    try:
        detail = json.loads(raw or b"{}").get("detail")
    except (ValueError, AttributeError):
        return raw[:200].decode("utf-8", "replace")
    if isinstance(detail, dict):
        return str(detail.get("message") or detail)
    return str(detail)


def _post(url: str, body: bytes, token: str, context) -> tuple:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        return _send(url, body, headers, context)
    except (OSError, http.client.HTTPException) as exc:
        raise ImportFailed(f"cannot reach {url.split('/api/')[0]}: {exc}") from exc


def trade_key(base: str, api_key: str, context) -> dict:
    status, raw, _ = _post(base + TOKEN_PATH, b"{}", api_key, context)
    if status == 200:
        return json.loads(raw)
    if status == 401:
        raise ImportFailed("the API key is invalid or revoked (401)")
    raise ImportFailed(f"the token request answered {status}: {_detail(raw)}")


def run_import(base: str, grant: dict, files: list, *, full: bool, allow_mass_archive: bool,
               dry_run: bool, context) -> dict:
    payload = {"files": files, "full": full}
    if allow_mass_archive:
        payload["allow_mass_archive"] = True
    url = f"{base}/api/v1/projects/{grant['project_id']}/cases/import?dry_run={'true' if dry_run else 'false'}"
    status, raw, _ = _post(url, json.dumps(payload).encode("utf-8"), grant["token"], context)
    if status == 200:
        return json.loads(raw)
    raise ImportFailed(f"the import answered {status}: {_detail(raw)}")


def report(result: dict, say: Callable[[str], None], dry_run: bool) -> None:
    s = result["summary"]
    verb = "would import" if dry_run else "imported"
    say(f"{verb}: {s['created']} created, {s['updated']} updated, {s['moved']} moved, "
        f"{s['reactivated']} reactivated, {s['archived']} archived, {s['unchanged']} unchanged, "
        f"{s['skipped']} skipped")
    if dry_run:
        for item in result["items"]:
            if item["action"] != "unchanged":
                say(f"  {item['action']:<10} {item['path']}  {item['scenario'] or ''}".rstrip())
    for error in result["errors"][:SHOWN_ERRORS]:
        line = f":{error['line']}" if error.get("line") else ""
        say(f"  error {error['path']}{line} {error['message']}")
    if len(result["errors"]) > SHOWN_ERRORS:
        say(f"  ... and {len(result['errors']) - SHOWN_ERRORS} more errors")
    if result["warnings"]:
        say(f"  {len(result['warnings'])} warnings (skipped scenarios or tags)")


def run(args, env: Mapping[str, str], api_key: str, say: Callable[[str], None], cwd: str) -> int:
    config = load_config(cwd)
    url: Optional[str] = args.url or env.get("QAV_URL") or config.get("url")
    if not url:
        raise ConfigError("no platform URL: pass --url, set QAV_URL, or add url to .qav.yml")
    if not api_key:
        raise ConfigError("QAV_API_KEY is not set")
    sync_branch = args.branch or env.get("QAV_IMPORT_BRANCH") or DEFAULT_BRANCH
    current = detect(env).branch
    if current and current != sync_branch:
        say(f"skipped: on {current}; cases sync from {sync_branch}")
        return 0
    patterns = args.patterns or config.get("features") or DEFAULT_PATTERNS
    files = collect_files(list(patterns), cwd)
    if not files:
        raise ConfigError(f"no .feature files match {', '.join(patterns)}")
    context = make_context(args.ca_file or env.get("QAV_CA_FILE") or config.get("ca-file"))
    base = base_url(url)
    try:
        grant = trade_key(base, api_key, context)
        result = run_import(base, grant, files, full=not args.no_full,
                            allow_mass_archive=args.allow_mass_archive, dry_run=args.dry_run, context=context)
    except ImportFailed as exc:
        say(str(exc))
        return 1
    report(result, say, args.dry_run)
    return 1 if result["errors"] and args.strict else 0
```

In `cli.py` `build_parser()`, after the `check` parser:

```python
    features = commands.add_parser(
        "import-features",
        help="sync the repository's Gherkin .feature files into QA Vision test cases",
        description="Read the .feature files matching PATTERN (default: features in .qav.yml, else "
        "**/*.feature) and import them as test cases. Runs only on the sync branch (default: "
        "$QAV_IMPORT_BRANCH, else master). The API key is read from QAV_API_KEY only.",
    )
    features.add_argument("patterns", nargs="*", metavar="PATTERN")
    features.add_argument("--branch", help="the branch cases sync from (default: $QAV_IMPORT_BRANCH, else master)")
    features.add_argument("--no-full", action="store_true",
                          help="compare only the given files; never archive cases of other files")
    features.add_argument("--allow-mass-archive", action="store_true",
                          help="let a full import archive more than half of the imported cases")
    features.add_argument("--strict", action="store_true", help="exit 1 when a .feature file fails to parse")
    features.add_argument("--dry-run", action="store_true", help="print the plan; change nothing")
    features.add_argument("--url", help="platform URL (default: $QAV_URL)")
    features.add_argument("--ca-file", help="trust exactly this CA certificate (default: $QAV_CA_FILE)")
```

In `main()`, right after the `check` branch:

```python
    if args.command == "import-features":
        try:
            return features.run(args, env, api_key, say, os.getcwd())
        except ConfigError as exc:
            say(str(exc))
            return 2
```

Add `from qav_collector import features` with the other imports. Don't shadow it with the local
`features = commands.add_parser(...)` variable in `build_parser`: name that variable
`import_features` instead.

- In `config_file.py`: `LIST_KEYS = ("patterns", "components", "features")`.
- In `__init__.py`: `__version__ = "0.3.0"`. If a test or changelog pins the version, update it too.
- In `collector/README.md`, add an "import-features" section: what it does, the branch rule, full by default, `--allow-mass-archive`, `.qav.yml` `features:`, the exit codes table, and a GitHub Actions example. The exit codes are the ones in Global Constraints.

- [ ] **Step 5: Run the tests and check they pass**

Run: `.venv/Scripts/python -m pip install -q .` then `.venv/Scripts/python -m pytest -q`
(the whole collector suite).
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add collector
git commit -m "feat(collector): import-features keeps test cases in sync from the main branch (0.3.0)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Dashboard — server mass-archive flag, and the CI snippets

**Files:**
- Modify: `dashboard/src/api/cases.ts`, `dashboard/src/pages/CaseImportPage.tsx`, `dashboard/src/pages/CaseImport.test.tsx`
- Modify: `dashboard/src/pages/ProjectSettingsPage.tsx`, `dashboard/src/pages/ProjectSettingsPage.test.tsx`

**Interfaces:**
- Consumes: `summary.mass_archive` and 409 `mass_archive` (Task 2); the CLI command (Task 3).

- [ ] **Step 1: Invoke the `ui-ux-pro-max` skill** (project rule). The only visible changes are the snippet text and the error message.

- [ ] **Step 2: Write the failing tests.**

In `CaseImport.test.tsx`:
- add `mass_archive: false` to the shared `preview.summary`;
- in "archiving more than half of the imported cases shows a warning", set `mass_archive: true` in its `mass` summary;
- append:

```tsx
test("a confirm with the mass-archive alert showing allows the mass archive", async () => {
  asRole("member");
  const mass = { ...preview, summary: { created: 0, updated: 0, moved: 0, reactivated: 0, archived: 3, unchanged: 1, skipped: 0, mass_archive: true } };
  const bodies: Record<string, unknown>[] = [];
  server.use(http.post(`${P}/cases/import`, async ({ request }) => {
    bodies.push((await request.json()) as Record<string, unknown>);
    return HttpResponse.json(mass);
  }));
  renderAt("/projects/42/cases/import");
  const user = userEvent.setup();
  await user.upload(await screen.findByLabelText(/choose folder/i), [featureFile("a.feature", "Feature: A", "f/a.feature")]);
  await user.click(screen.getByRole("checkbox", { name: /complete features folder/i }));
  await user.click(screen.getByRole("button", { name: /preview/i }));
  await user.click(await screen.findByRole("button", { name: /archives 3/i }));
  await screen.findByText(/imported:/i);
  expect(bodies[0].allow_mass_archive).toBeUndefined();
  expect(bodies[1].allow_mass_archive).toBe(true);
});

test("a refused mass archive shows the server's message", async () => {
  asRole("member");
  server.use(http.post(`${P}/cases/import`, ({ request }) => new URL(request.url).searchParams.get("dry_run") === "true"
    ? HttpResponse.json(preview)
    : HttpResponse.json({ detail: { code: "mass_archive", message: "This would archive 9 of 10 imported cases.", archived: 9, live: 10 } }, { status: 409 })));
  renderAt("/projects/42/cases/import");
  const user = userEvent.setup();
  await user.upload(await screen.findByLabelText(/choose folder/i), [featureFile("a.feature", "Feature: A", "f/a.feature")]);
  await user.click(screen.getByRole("button", { name: /preview/i }));
  await user.click(await screen.findByRole("button", { name: /import 2 changes/i }));
  expect(await screen.findByText(/this would archive 9 of 10/i)).toBeInTheDocument();
});
```

In `ProjectSettingsPage.test.tsx`, add a test that renders the page the way its existing snippet
tests do. It asserts that the GitHub and CLI snippets contain `import-features` and
`collector-v0.3.0`. Follow the file's existing pattern for switching providers.

- [ ] **Step 3: Run the tests and check they fail**

Run, from `dashboard/`: `npx vitest run src/pages/CaseImport.test.tsx src/pages/ProjectSettingsPage.test.tsx`
Expected: the new tests FAIL.

- [ ] **Step 4: Implement**

In `api/cases.ts`:
- `ImportResult.summary` becomes `Record<"created" | "updated" | "moved" | "reactivated" | "archived" | "unchanged" | "skipped", number> & { mass_archive?: boolean }`;
- `importCases` options gain `allowMassArchive?: boolean`, and the body adds `...(opts.allowMassArchive ? { allow_mass_archive: true } : {})`.

In `CaseImportPage.tsx`:
- `const massArchive = preview?.summary.mass_archive ?? false;` replaces the client-side calculation. Keep `archived` and `live` for the alert text.
- The apply mutation passes `allowMassArchive: massArchive`. Capture it at click time: `apply.mutate({ hash: preview.plan_hash, allow: massArchive })` and destructure it in `mutationFn`.
- A 409 `mass_archive` needs no special branch: `errorFrom` already turns `detail.message` into the error text that `ErrorBanner` shows.

In `ProjectSettingsPage.tsx`:
- set `COLLECTOR_REF = "collector-v0.3.0"`;
- give every provider's snippet a second step that runs `qav-collector import-features "tests/features/**/*.feature"`, with the same `QAV_URL` / `QAV_API_KEY` wiring as its upload step;
- add the comment `# syncs test cases from .feature files; runs on master only (set QAV_IMPORT_BRANCH to change)`.

For GitHub, append to the template:

```
- name: Sync test cases from .feature files   # runs on master only (QAV_IMPORT_BRANCH to change)
  run: |
    pip install "qav-collector @ git+https://github.com/atriis/Atriis.QEOS@${COLLECTOR_REF}#subdirectory=collector"
    qav-collector import-features "tests/features/**/*.feature"
  env:
    QAV_URL: ${origin}
    QAV_API_KEY: \${{ secrets.QAV_API_KEY }}
```

Do the same for gitlab, azure, jenkins and cli, in each one's syntax. The cli `local` variant also
passes `--ca-file qav-ca.crt`.

- [ ] **Step 5: Run every CI step for the dashboard**

Run, from `dashboard/`: `npm run lint`, `npm run typecheck`, `npx vitest run`, `npm run build`.
Expected: all succeed.

- [ ] **Step 6: Commit**

```bash
git add dashboard/src
git commit -m "feat(dashboard): CI snippets sync test cases; the import page uses the server's mass-archive flag

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Gateway smoke, ADR-024 and docs

**Files:**
- Modify: `scripts/smoke_gateway.sh`
- Create: `docs/architecture/adr/ADR-024-service-tokens-for-ci-imports.md`
- Modify: `docs/architecture/adr/INDEX.md`, `docs/architecture/adr/ADR-023-gherkin-import.md`
- Modify: `platforms/ingestion-service/README.md`, `platforms/test-management-service/README.md`, `TODO.md`
- Modify: `docs/superpowers/specs/2026-10-06-ci-feature-import-design.md`

- [ ] **Step 1: Add the smoke checks.** In `scripts/smoke_gateway.sh`, after the Gherkin import
  checks (around line 115, after `API_KEY` exists and before the key is revoked):

```bash
check "trade the API key for an import token -> ingestion-service" 200 POST "$BASE/api/v1/collect/token" \
  -H "Authorization: Bearer $API_KEY"
SERVICE_TOKEN="$(sed -n 's/.*"token":"\([^"]*\)".*/\1/p' "$TMP/body")"
CI_BODY='{"files":[{"path":"tests/features/ci.feature","content":"Feature: CI\n  Scenario: from ci\n    Given a token\n"}]}'
check "import a .feature with the CI token -> test-management-service" 200 POST \
  "$BASE/api/v1/projects/$PROJECT_ID/cases/import" -H "Authorization: Bearer $SERVICE_TOKEN" \
  -H "Content-Type: application/json" -d "$CI_BODY"
body_has "... one case created by CI" '"created":1'
check "the CI token opens no other route" 401 GET "$BASE/api/v1/projects/$PROJECT_ID/cases" \
  -H "Authorization: Bearer $SERVICE_TOKEN"
```

- [ ] **Step 2: Run the smoke and check it passes.** From the repo root:

```bash
set -a; . ./.env; set +a
docker compose up -d --build ingestion-service test-management-service gateway
bash scripts/smoke_gateway.sh
```

Expected: `all gateway checks passed`. Never run `docker compose down -v`.

- [ ] **Step 3: Write ADR-024**, following `TEMPLATE.md` and ADR-022/023's style.
  - **Context:** CI holds only a project API key, which only ingestion can check. test-management
    takes user JWTs and asks project-service for the role. ADR-022 says services do not call each
    other.
  - **Decision:**
    - the token trade at `POST /api/v1/collect/token`;
    - the claims table;
    - the non-numeric `sub` as the reason no other route accepts the token;
    - the scope and project check on the import route only;
    - `created_by` / `updated_by = 0`;
    - a 5-minute life instead of revocation.
  - **Alternatives rejected:** the gateway `auth_request` with a trusted header (anyone who reaches
    the service directly can forge the header); reading ingestion's database (couples two services
    through a database).
  - **Consequences:**
    - one more endpoint on ingestion;
    - revoking a key stops new tokens, and an issued token lasts at most 5 minutes;
    - every future service-token route must check `scope` itself;
    - the dashboard shows no user names, so CI's user 0 is invisible today.

  Add the INDEX row in ADR-023's format.

- [ ] **Step 4: Update the docs.**
  - **ADR-023:** replace the Consequence "A server-side mass-archive guard … is due with the CLI command" with what shipped: 409 `mass_archive` unless `allow_mass_archive`; `summary.mass_archive` in dry runs; the dashboard allows it when its alert is showing; the CLI passes `--allow-mass-archive`.
  - **ingestion README:** add the `POST /api/v1/collect/token` row.
  - **test-management README:** the import route accepts an editor's JWT or the CI service token (ADR-024); add `allow_mass_archive` to the body and `mass_archive` to the summary.
  - **TODO.md** (CRLF line endings — keep them): mark the `qav-collector import-features` line `[x]` with "(2026-10-06, ADR-024)".
  - **Spec:** in the test-management section, replace "The dashboard shows 'CI' for user id 0." with "The dashboard shows no user ids today, so nothing displays it yet." Drop the dashboard bullet "The case editor and list show 'CI'…" and the matching test bullet.

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke_gateway.sh docs TODO.md platforms/ingestion-service/README.md platforms/test-management-service/README.md
git commit -m "docs: ADR-024 service tokens for CI imports; smoke covers the token and the CI import

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Release handoff (the user does it)**

Tell the user to push master, then create and push the collector tag that the dashboard snippet
now pins:

```bash
git push origin master
git tag collector-v0.3.0
git push origin collector-v0.3.0
```
