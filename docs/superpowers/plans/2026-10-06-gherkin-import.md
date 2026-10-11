# Gherkin Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import test cases from Gherkin `.feature` files into test-management-service. There is
one endpoint with a dry run and a plan hash, a dashboard page to upload and preview, and imported
cases are read-only where the repository owns the content.

**Architecture:**
- The service parses with Cucumber's `gherkin-official`.
- A pure planner compares the parsed scenarios with the project's imported cases.
- One endpoint returns the plan (`dry_run=true`) or applies it in a single transaction.
- `test_key()` moves to `qav_shared`, so ingestion and the import share one formula.
- The dashboard reads a folder in the browser and posts `{path, content}` JSON.

**Tech Stack:**
- Python 3.11, FastAPI 0.104, SQLAlchemy 2.0, Alembic, `gherkin-official==42.0.1`, pytest.
- React + TypeScript, TanStack Query, vitest + msw.
- NGINX gateway.

**Spec:** `docs/superpowers/specs/2026-10-06-gherkin-import-design.md`

## Global Constraints

- Imported case = `source_key IS NOT NULL`. Manual cases are never part of an import plan.
- `source_key = sha256(f"{source_path}\0{scenario name}")`, as lowercase hex, unique per project.
- `PATCH` on an imported case rejects `title`, `steps`, `labels` and `gherkin` with 422. `priority`, `status`, `description` and `automated_test_key`/`automated_name` stay editable.
- Tags:
  - `@priority:<low|medium|high|critical>` sets priority and is not a label.
  - Every other tag drops the `@`, is lower-cased, and has `:` replaced by `-`. It must then match `^[a-z0-9._-]{1,40}$`.
  - At most 20 labels. A skipped tag is a warning.
- `automated_test_key = qav_shared.keys.test_key(feature name, source_path, scenario name)`.
  - For an outline whose name has `<placeholders>`, the name is filled from the first Examples row.
  - It is set only while the case has no link.
- Limits are settings, with these defaults: `IMPORT_MAX_FILES=2000`, `IMPORT_MAX_FILE_BYTES=262144`, `IMPORT_MAX_TOTAL_BYTES=10485760`. Over a limit is 413, and the message names the setting.
- Path rules:
  - `\` becomes `/` and a leading `./` is dropped.
  - Absolute, drive-letter, empty, `..` or over 500 characters is 422.
  - The same path twice in one request is 422.
- The gateway import location reads `client_max_body_size` from `GATEWAY_IMPORT_MAX_BODY` (default `25m`). Every other route keeps `10m`.
- Response errors:
  - 409 `plan_changed` when `expected_plan_hash` differs from the rebuilt plan's hash;
  - 409 `import_conflict` when two imports race;
  - viewer 403, a project the caller cannot see 404.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run the service tests with `SECRET_KEY=test .venv/Scripts/python -m pytest -q` from `platforms/test-management-service`.
- Before any dashboard UI edit, invoke the `ui-ux-pro-max` skill (project rule).

## Review Focus

1. **A file that fails to parse inside a batch.** Its existing cases must not be archived, and the rest of the batch still imports. Pinned in Task 4 (`test_a_broken_file_never_archives_its_cases`).
2. **The editor saving an imported case.** Today it always sends `title`, `steps` and `labels`, which would now get 422 on every save. It must send only the editable fields. Pinned in Task 8 (`saving an imported case sends only the fields QA Vision owns`).
3. **Windows paths and folder picks.** `tests\features\a.feature` and `./tests/features/a.feature` must produce the same `source_key` as `tests/features/a.feature`. Pinned in Task 4 (`test_paths_are_normalised_before_keys_are_computed`).
4. **Re-importing after a manual unlink, or with a different file order.** File order must not change `plan_hash`. Pinned in Task 4 (`test_same_batch_twice_is_all_unchanged_and_hash_is_order_free`).
5. **An outline with `<placeholders>` in its name.** The key must match the collector's first-row name. Pinned in Task 6 (contract test).

---

## File Structure

Service, `platforms/test-management-service/`:

| File | Change |
|---|---|
| `requirements.txt` | Modify: add `gherkin-official==42.0.1` |
| `src/casebook/core/config.py` | Modify: add the three `IMPORT_MAX_*` settings |
| `src/casebook/models/case.py` | Modify: add `source_path`, `source_key`, `gherkin` and a unique index |
| `alembic/versions/002_case_source.py` | Create: migration |
| `src/casebook/gherkin_import/__init__.py` | Create: empty |
| `src/casebook/gherkin_import/parse.py` | Create: `.feature` text to `ParsedScenario`s, with no DB |
| `src/casebook/gherkin_import/plan.py` | Create: parsed scenarios plus existing cases to `Plan`, with no DB writes |
| `src/casebook/service/import_service.py` | Create: load existing cases, build the plan, apply it in one transaction |
| `src/casebook/schemas/case_import.py` | Create: request and response models, and path validation |
| `src/casebook/api/v1/endpoints/case_import.py` | Create: `POST /cases/import` |
| `src/casebook/api/v1/api.py` | Modify: mount the import router before `cases.router` |
| `src/casebook/schemas/case.py` | Modify: `CaseOut` gains `source_path` and `gherkin`; `CaseUpdate` gains `gherkin` |
| `src/casebook/service/case_service.py` | Modify: `out()`, the `origin` filter, search in Gherkin, read-only guard |
| `src/casebook/api/v1/endpoints/cases.py` | Modify: `origin` query and the 422 guard |
| `tests/fixtures/*.feature`, `tests/fixtures/cucumber_report.json` | Create |
| `tests/unit/test_gherkin_parse.py`, `tests/unit/test_import_plan.py`, `tests/integration/test_import.py`, `tests/unit/test_key_contract.py` | Create |
| `tests/unit/test_migration.py`, `tests/integration/test_cases.py` | Modify |
| `README.md` | Modify: endpoint, limits and settings |

Shared and ingestion:

| File | Change |
|---|---|
| `shared/qav_shared/keys.py` | Create: `test_key()` |
| `shared/tests/test_keys.py` | Create |
| `platforms/ingestion-service/src/ingestion/service/ingest_service.py` | Modify: import `test_key` from `qav_shared.keys` |

Dashboard, `dashboard/src/`:

| File | Change |
|---|---|
| `api/cases.ts` | Modify: `Case.source_path` and `Case.gherkin`, `origin` in `CaseQuery`, `importCases()` and its types |
| `lib/gherkinTokens.ts` | Create: line tokenizer for highlighting |
| `lib/gherkinTokens.test.ts` | Create |
| `components/GherkinBlock.tsx` | Create: read-only highlighted Gherkin |
| `pages/CaseImportPage.tsx` | Create: choose, preview, import, result |
| `pages/CaseImport.test.tsx` | Create |
| `pages/CasesPage.tsx` | Modify: import button, origin filter, imported icon |
| `pages/CaseEditorPage.tsx` | Modify: imported mode |
| `pages/TestManagement.test.tsx` | Modify: imported editor and origin filter tests |
| `App.tsx` | Modify: route `cases/import`, before `cases/:caseNumber` |

Gateway, ops and docs:

| File | Change |
|---|---|
| `gateway/nginx.conf.template` | Modify: import `location` with `${GATEWAY_IMPORT_MAX_BODY}` |
| `gateway/entrypoint.sh` | Modify: default and substitute `GATEWAY_IMPORT_MAX_BODY` |
| `docker-compose.yml` | Modify: pass `GATEWAY_IMPORT_MAX_BODY` and the `IMPORT_MAX_*` settings |
| `.env.example` | Modify: document the four variables |
| `scripts/smoke_gateway.sh` | Modify: import one feature; a body over 10 MB reaches the service |
| `docs/architecture/adr/ADR-023-gherkin-import.md`, `docs/architecture/adr/INDEX.md` | Create / modify |
| `docs/superpowers/specs/2026-10-06-test-management-design.md`, `IMPLEMENTATION_PLAN.md`, `TODO.md` | Modify |

---

### Task 1: `test_key()` moves to `qav_shared`

**Files:**
- Create: `shared/qav_shared/keys.py`
- Create: `shared/tests/test_keys.py`
- Modify: `platforms/ingestion-service/src/ingestion/service/ingest_service.py:47-52`

**Interfaces:**
- Produces: `qav_shared.keys.test_key(suite: str, class_name: str, name: str) -> str`, 64 lowercase hex.

- [ ] **Step 1: Write the failing test** in `shared/tests/test_keys.py`

```python
import hashlib

from qav_shared.keys import test_key as make_test_key


def test_key_is_sha256_of_the_three_parts_joined_by_nul():
    expected = hashlib.sha256("checkout\0CartTest\0adds item".encode("utf-8")).hexdigest()
    assert make_test_key("checkout", "CartTest", "adds item") == expected


def test_nul_separator_keeps_shifted_parts_apart():
    assert make_test_key("a", "bc", "d") != make_test_key("ab", "c", "d")
```

- [ ] **Step 2: Run the test and check it fails**

Run from `platforms/organization-service` (whose CI job runs `../../shared/tests`): `SECRET_KEY=test .venv/Scripts/python -m pytest -q ../../shared/tests/test_keys.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'qav_shared.keys'`

- [ ] **Step 3: Implement** `shared/qav_shared/keys.py`

```python
"""Identities shared by more than one service. Changing a formula here breaks every stored key."""
import hashlib


def test_key(suite: str, class_name: str, name: str) -> str:
    """Stable identity of a test across runs; the NUL separator keeps ("a","bc") and ("ab","c") apart.

    ingestion stores it on every result; test-management computes it for imported Gherkin
    scenarios so a case links to its automated results without a lookup (ADR-023)."""
    return hashlib.sha256(f"{suite}\0{class_name}\0{name}".encode("utf-8")).hexdigest()


test_key.__test__ = False  # not a pytest test, despite the name
```

In `ingest_service.py`, delete the local `test_key` function and its `__test__` line. Add
`from qav_shared.keys import test_key` with the other imports. The call at line 134 and
`tests/unit/test_ingest_service.py`, which imports `test_key` from `ingest_service`, keep working
unchanged.

- [ ] **Step 4: Run the tests and check they pass**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest -q ../../shared/tests` (organization-service venv).
Then from `platforms/ingestion-service`: `SECRET_KEY=test .venv/Scripts/python -m pytest -q`.
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add shared/qav_shared/keys.py shared/tests/test_keys.py platforms/ingestion-service/src/ingestion/service/ingest_service.py
git commit -m "refactor(shared): test_key lives in qav_shared so test-management can compute it too

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Migration 002, model columns and settings

**Files:**
- Modify: `platforms/test-management-service/src/casebook/models/case.py`
- Create: `platforms/test-management-service/alembic/versions/002_case_source.py`
- Modify: `platforms/test-management-service/src/casebook/core/config.py`
- Modify: `platforms/test-management-service/requirements.txt`
- Test: `platforms/test-management-service/tests/unit/test_migration.py`

**Interfaces:**
- Produces: `Case.source_path: str|None`, `Case.source_key: str|None`, `Case.gherkin: str|None`. Unique index `uq_cases_project_source_key` on `(project_id, source_key)`. `settings.IMPORT_MAX_FILES`, `settings.IMPORT_MAX_FILE_BYTES`, `settings.IMPORT_MAX_TOTAL_BYTES`.

- [ ] **Step 1: Write the failing tests.** Append to `tests/unit/test_migration.py`:

```python
SOURCED = ("INSERT INTO cases (project_id, number, title, steps, created_by, source_key)"
           " VALUES (:project, :number, 't', '[]', 1, :key)")


def test_source_keys_are_unique_per_project_and_manual_cases_are_free(migrated_engine):
    with migrated_engine.begin() as conn:
        conn.execute(text(SOURCED), {"project": 1, "number": 1, "key": "k" * 64})
        conn.execute(text(SOURCED), {"project": 2, "number": 1, "key": "k" * 64})
        conn.execute(text(SOURCED), {"project": 1, "number": 2, "key": None})
        conn.execute(text(SOURCED), {"project": 1, "number": 3, "key": None})
    with pytest.raises(IntegrityError), migrated_engine.begin() as conn:
        conn.execute(text(SOURCED), {"project": 1, "number": 4, "key": "k" * 64})


def test_downgrade_to_001_drops_the_source_columns(tmp_path):
    url = f"sqlite:///{(tmp_path / 'down.db').as_posix()}"
    cfg = Config()
    cfg.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "001")
    engine = create_engine(url)
    try:
        columns = {c["name"] for c in inspect(engine).get_columns("cases")}
    finally:
        engine.dispose()
    assert not columns & {"source_path", "source_key", "gherkin"}
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest -q tests/unit/test_migration.py`
Expected: FAIL. The INSERT names `source_key`, which does not exist.

- [ ] **Step 3: Implement**

In `models/case.py`, add to `__table_args__`:
`Index("uq_cases_project_source_key", "project_id", "source_key", unique=True),`. Add these
columns after `automated_name`:

```python
    # Imported from a .feature file (ADR-023): the repository owns title, gherkin and labels.
    # NULL source_key = a manual case. source_key = sha256(source_path \0 scenario name)
    source_path = Column(String(500), nullable=True)
    source_key = Column(String(64), nullable=True)
    gherkin = Column(Text, nullable=True)
```

Create `alembic/versions/002_case_source.py`:

```python
"""cases: source_path, source_key, gherkin (Gherkin import, ADR-023)

Revision ID: 002
Revises: 001
Create Date: 2026-10-06
"""
import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cases") as batch:
        batch.add_column(sa.Column("source_path", sa.String(500), nullable=True))
        batch.add_column(sa.Column("source_key", sa.String(64), nullable=True))
        batch.add_column(sa.Column("gherkin", sa.Text(), nullable=True))
    # NULLs never collide, in PostgreSQL and SQLite alike, so manual cases are unaffected
    op.create_index("uq_cases_project_source_key", "cases", ["project_id", "source_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_cases_project_source_key", table_name="cases")
    with op.batch_alter_table("cases") as batch:
        batch.drop_column("gherkin")
        batch.drop_column("source_key")
        batch.drop_column("source_path")
```

In `core/config.py`, add to `Settings`:

```python
    # Gherkin import (ADR-023): one request is one transaction; these keep it bounded.
    # Raise them in .env; the gateway's GATEWAY_IMPORT_MAX_BODY must stay above the total
    IMPORT_MAX_FILES: int = 2000
    IMPORT_MAX_FILE_BYTES: int = 262144
    IMPORT_MAX_TOTAL_BYTES: int = 10485760
```

In `requirements.txt`, add `gherkin-official==42.0.1` after `respx==0.21.1`. Then run
`.venv/Scripts/python -m pip install -r requirements.txt`.

- [ ] **Step 4: Run the tests and check they pass**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: all PASS. `test_migration_columns_match_models` now checks the new columns too.

- [ ] **Step 5: Commit**

```bash
git add platforms/test-management-service
git commit -m "feat(test-management): cases record where an imported case came from (migration 002)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Parse a `.feature` file into scenarios

**Files:**
- Create: `platforms/test-management-service/src/casebook/gherkin_import/__init__.py` (empty)
- Create: `platforms/test-management-service/src/casebook/gherkin_import/parse.py`
- Create fixtures: `tests/fixtures/checkout.feature`, `tests/fixtures/portugues.feature`, `tests/fixtures/broken.feature`
- Test: `platforms/test-management-service/tests/unit/test_gherkin_parse.py`

**Interfaces:**
- Consumes: `qav_shared.keys.test_key`.
- Produces:

```python
@dataclass(frozen=True)
class Issue:
    path: str
    line: Optional[int]
    message: str

@dataclass(frozen=True)
class ParsedScenario:
    path: str
    feature_name: str
    name: str             # full scenario name, stripped
    title: str            # name[:200]
    gherkin: str
    description: Optional[str]
    labels: tuple         # sorted, unique, valid labels
    priority: Optional[str]
    source_key: str
    test_key: str
    test_name: str        # the result name the key was computed from
    line: int

@dataclass
class ParsedFile:
    path: str
    scenarios: list       # [ParsedScenario]
    errors: list          # [Issue]: the file failed to parse; scenarios is then empty
    warnings: list        # [Issue]

def source_key(path: str, name: str) -> str
def parse_feature(path: str, content: str) -> ParsedFile
```

- [ ] **Step 1: Write the fixtures**

`tests/fixtures/checkout.feature`:

```gherkin
@checkout @priority:low
Feature: Checkout
  Paying for the cart.

  Background:
    Given a signed-in shopper

  @smoke @ado:81284 @priority:high
  Scenario: Pay by card
    The happy path.
    When I pay with a stored card
      | brand | last4 |
      | visa  | 4242  |
    Then the order is confirmed
      """json
      {"status": "confirmed"}
      """

  Scenario: Pay by card
    When I pay again

  @Has:Colon @bad!tag
  Scenario: Tag edge cases
    Given nothing

  Rule: Coupons
    Background:
      Given a coupon "SAVE10"

    Scenario Outline: Apply <code>
      When I apply "<code>"
      Then the total drops by <off>

      Examples:
        | code   | off |
        | SAVE10 | 10  |
        | SAVE20 | 20  |
```

In Gherkin, every scenario after a `Rule:` belongs to that rule. That is why the rule comes last
here.

`tests/fixtures/portugues.feature`:

```gherkin
# language: pt
Funcionalidade: Pagamento
  Cenário: Pagar com cartão
    Dado um carrinho
    Quando pago
    Então a encomenda é confirmada
```

`tests/fixtures/broken.feature`:

```gherkin
Feature: Broken
  Scenario: a
    Given b
  oops here
```

- [ ] **Step 2: Write the failing tests** in `tests/unit/test_gherkin_parse.py`

```python
"""Gherkin text -> scenarios (ADR-023): keys, rendering, tags, outlines, languages, errors."""
import hashlib
from pathlib import Path

from qav_shared.keys import test_key as make_test_key
from src.casebook.gherkin_import.parse import parse_feature, source_key

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PATH = "tests/features/checkout.feature"


def parsed(name="checkout.feature", path=PATH):
    return parse_feature(path, (FIXTURES / name).read_text(encoding="utf-8"))


def by_name(result):
    return {s.name: s for s in result.scenarios}


def test_source_key_is_sha256_of_path_and_name():
    assert source_key("a.feature", "x") == hashlib.sha256("a.feature\0x".encode()).hexdigest()


def test_every_scenario_and_outline_becomes_one_case_and_duplicate_names_are_skipped():
    result = parsed()
    assert [s.name for s in result.scenarios] == ["Pay by card", "Tag edge cases", "Apply <code>"]
    assert result.errors == []
    duplicate = [w for w in result.warnings if "Pay by card" in w.message]
    assert len(duplicate) == 1 and duplicate[0].line == 19


def test_gherkin_keeps_backgrounds_tables_and_doc_strings():
    assert by_name(parsed())["Pay by card"].gherkin == (
        "Background:\n"
        "  Given a signed-in shopper\n"
        "Scenario: Pay by card\n"
        "  When I pay with a stored card\n"
        "    | brand | last4 |\n"
        "    | visa | 4242 |\n"
        "  Then the order is confirmed\n"
        '    """json\n'
        '    {"status": "confirmed"}\n'
        '    """'
    )


def test_an_outline_keeps_rule_background_and_examples_in_its_gherkin():
    outline = by_name(parsed())["Apply <code>"]
    assert outline.gherkin == (
        "Background:\n"
        "  Given a signed-in shopper\n"
        '  Given a coupon "SAVE10"\n'
        "Scenario Outline: Apply <code>\n"
        '  When I apply "<code>"\n'
        "  Then the total drops by <off>\n"
        "  Examples:\n"
        "    | code | off |\n"
        "    | SAVE10 | 10 |\n"
        "    | SAVE20 | 20 |"
    )


def test_tags_become_labels_and_priority():
    scenarios = by_name(parsed())
    card = scenarios["Pay by card"]
    assert card.labels == ("ado-81284", "checkout", "smoke")
    assert card.priority == "high"                         # the scenario's tag beats the feature's
    assert scenarios["Apply <code>"].priority == "low"     # inherited from the feature


def test_tags_that_are_still_invalid_are_skipped_with_a_warning():
    result = parsed()
    edge = by_name(result)["Tag edge cases"]
    assert edge.labels == ("checkout", "has-colon")
    assert any("@bad!tag" in w.message for w in result.warnings)


def test_more_than_20_tags_keeps_20_and_warns():
    tags = " ".join(f"@t{i}" for i in range(25))
    result = parse_feature("a.feature", f"Feature: F\n  {tags}\n  Scenario: S\n    Given x\n")
    assert len(result.scenarios[0].labels) == 20
    assert any("20" in w.message for w in result.warnings)


def test_description_title_and_keys():
    card = by_name(parsed())["Pay by card"]
    assert card.description == "The happy path."
    assert card.title == "Pay by card" and card.feature_name == "Checkout"
    assert card.source_key == source_key(PATH, "Pay by card")
    assert card.test_key == make_test_key("Checkout", PATH, "Pay by card")


def test_an_outline_with_placeholders_links_to_its_first_example_row():
    outline = by_name(parsed())["Apply <code>"]
    assert outline.test_name == "Apply SAVE10"
    assert outline.test_key == make_test_key("Checkout", PATH, "Apply SAVE10")


def test_a_long_name_is_cut_for_the_title_but_not_for_the_keys():
    name = "n" * 250
    s = parse_feature("a.feature", f"Feature: F\n  Scenario: {name}\n    Given x\n").scenarios[0]
    assert len(s.title) == 200 and s.name == name
    assert s.source_key == source_key("a.feature", name)


def test_another_language_parses_with_its_own_keywords():
    s = parsed("portugues.feature", "f/pt.feature").scenarios[0]
    assert s.name == "Pagar com cartão" and s.feature_name == "Pagamento"
    assert s.gherkin.splitlines() == ["Cenário: Pagar com cartão", "  Dado um carrinho", "  Quando pago",
                                      "  Então a encomenda é confirmada"]


def test_a_syntax_error_skips_the_file_and_reports_the_line():
    result = parsed("broken.feature", "b.feature")
    assert result.scenarios == []
    assert len(result.errors) == 1 and result.errors[0].line == 4


def test_an_empty_file_or_one_without_a_feature_has_no_scenarios_and_no_error():
    assert parse_feature("e.feature", "").scenarios == []
    assert parse_feature("e.feature", "# only a comment\n").errors == []
```

- [ ] **Step 3: Run the tests and check they fail**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest -q tests/unit/test_gherkin_parse.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.casebook.gherkin_import'`

- [ ] **Step 4: Implement** `src/casebook/gherkin_import/parse.py`

```python
"""A .feature file -> the cases it holds (docs/superpowers/specs/2026-10-06-gherkin-import-design.md).

Pure: no database. Uses Cucumber's own parser, so scenarios are seen exactly as runners see them."""
import hashlib
import re
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from gherkin.errors import CompositeParserException, ParserError
from gherkin.parser import Parser

from qav_shared.keys import test_key

PRIORITIES = ("low", "medium", "high", "critical")
LABEL = re.compile(r"^[a-z0-9._-]{1,40}$")
MAX_LABELS = 20
TITLE_LENGTH = 200
DESCRIPTION_LENGTH = 10000
PLACEHOLDER = re.compile(r"<([^<>]+)>")
INDENT = "  "


@dataclass(frozen=True)
class Issue:
    path: str
    line: Optional[int]
    message: str


@dataclass(frozen=True)
class ParsedScenario:
    path: str
    feature_name: str
    name: str
    title: str
    gherkin: str
    description: Optional[str]
    labels: tuple
    priority: Optional[str]
    source_key: str
    test_key: str
    test_name: str
    line: int


@dataclass
class ParsedFile:
    path: str
    scenarios: List[ParsedScenario] = field(default_factory=list)
    errors: List[Issue] = field(default_factory=list)
    warnings: List[Issue] = field(default_factory=list)


def source_key(path: str, name: str) -> str:
    return hashlib.sha256(f"{path}\0{name}".encode("utf-8")).hexdigest()


def parse_feature(path: str, content: str) -> ParsedFile:
    result = ParsedFile(path=path)
    try:
        document = Parser().parse(content)
    except CompositeParserException as exc:
        for error in exc.errors:
            result.errors.append(Issue(path, _line(error), str(error)))
        return result
    except ParserError as exc:
        result.errors.append(Issue(path, _line(exc), str(exc)))
        return result
    feature = document.get("feature")
    if not feature:
        return result
    feature_name = (feature.get("name") or "").strip()
    seen: set = set()
    for child in feature.get("children", []):
        if "background" in child:
            continue
        if "rule" in child:
            rule = child["rule"]
            for rule_child in rule.get("children", []):
                if "scenario" in rule_child:
                    _add(result, seen, feature, feature_name, rule, rule_child["scenario"])
        elif "scenario" in child:
            _add(result, seen, feature, feature_name, None, child["scenario"])
    return result


def _line(error) -> Optional[int]:
    location = getattr(error, "location", None) or {}
    return location.get("line")


def _background_steps(children: Iterable[dict]) -> list:
    return [step for child in children if "background" in child for step in child["background"]["steps"]]


def _add(result: ParsedFile, seen: set, feature: dict, feature_name: str, rule: Optional[dict],
         scenario: dict) -> None:
    name = (scenario.get("name") or "").strip()
    line = scenario["location"]["line"]
    if not name:
        result.warnings.append(Issue(result.path, line, "skipped a scenario without a name"))
        return
    if name in seen:
        result.warnings.append(Issue(result.path, line, f'skipped "{name}": another scenario in this file has the same name'))
        return
    seen.add(name)

    tags = list(feature.get("tags", [])) + list((rule or {}).get("tags", [])) + list(scenario.get("tags", []))
    labels, priority = _labels_and_priority(result, line, [t["name"] for t in tags])
    background = _background_steps(feature.get("children", []))
    if rule is not None:
        background += _background_steps(rule.get("children", []))
    test_name = _first_example_name(name, scenario)
    description = (scenario.get("description") or "").strip() or None
    result.scenarios.append(ParsedScenario(
        path=result.path, feature_name=feature_name, name=name, title=name[:TITLE_LENGTH],
        gherkin=_render(background, scenario), description=description[:DESCRIPTION_LENGTH] if description else None,
        labels=labels, priority=priority, source_key=source_key(result.path, name),
        test_key=test_key(feature_name, result.path, test_name), test_name=test_name, line=line,
    ))


def _labels_and_priority(result: ParsedFile, line: int, tags: List[str]):
    labels: list = []
    priority = None
    for tag in tags:
        bare = tag[1:] if tag.startswith("@") else tag
        if bare.lower().startswith("priority:") and bare.split(":", 1)[1].lower() in PRIORITIES:
            priority = bare.split(":", 1)[1].lower()  # later tags (rule, scenario) win
            continue
        label = bare.lower().replace(":", "-")
        if not LABEL.match(label):
            result.warnings.append(Issue(result.path, line, f"skipped tag {tag}: not a valid label"))
            continue
        if label not in labels:
            labels.append(label)
    if len(labels) > MAX_LABELS:
        result.warnings.append(Issue(result.path, line, f"kept the first {MAX_LABELS} of {len(labels)} tags"))
        labels = labels[:MAX_LABELS]
    return tuple(sorted(labels)), priority


def _first_example_name(name: str, scenario: dict) -> str:
    """cucumber-js names an outline's rows after the outline, with <placeholders> filled from the row."""
    if not PLACEHOLDER.search(name):
        return name
    for examples in scenario.get("examples", []):
        header = examples.get("tableHeader")
        body = examples.get("tableBody") or []
        if header and body:
            values = {h["value"]: c["value"] for h, c in zip(header["cells"], body[0]["cells"])}
            return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), name)
    return name


def _cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "\\n")


def _row(cells: list, indent: str) -> str:
    return indent + "| " + " | ".join(_cell(c["value"]) for c in cells) + " |"


def _steps(steps: list, indent: str) -> List[str]:
    lines = []
    for step in steps:
        lines.append(f"{indent}{step['keyword']}{step['text']}")
        inner = indent + INDENT
        if "dataTable" in step:
            lines += [_row(r["cells"], inner) for r in step["dataTable"]["rows"]]
        if "docString" in step:
            doc = step["docString"]
            fence = doc.get("delimiter", '"""')
            lines.append(f"{inner}{fence}{doc.get('mediaType') or ''}")
            lines += [f"{inner}{text}" if text else "" for text in doc["content"].split("\n")]
            lines.append(f"{inner}{fence}")
    return lines


def _render(background: list, scenario: dict) -> str:
    lines: List[str] = []
    if background:
        lines.append("Background:")
        lines += _steps(background, INDENT)
    lines.append(f"{scenario['keyword']}: {scenario['name'].strip()}")
    lines += _steps(scenario.get("steps", []), INDENT)
    for examples in scenario.get("examples", []):
        title = (examples.get("name") or "").strip()
        lines.append(f"{INDENT}{examples['keyword']}:" + (f" {title}" if title else ""))
        if examples.get("tableHeader"):
            lines.append(_row(examples["tableHeader"]["cells"], INDENT * 2))
        lines += [_row(r["cells"], INDENT * 2) for r in examples.get("tableBody") or []]
    return "\n".join(lines)
```

Note on `Background:`: the rendered word is always the English `Background:`, because that
background's own keyword may differ between the feature and the rule. The Portuguese fixture has
no background, so its test does not depend on this.

- [ ] **Step 5: Run the tests and check they pass**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest -q tests/unit/test_gherkin_parse.py`
Expected: all PASS. If the duplicate-line assertion (`19`) fails, count the line of the second
`Scenario: Pay by card` in the fixture, as written, and fix the number in the test. Do not change
the code.

- [ ] **Step 6: Commit**

```bash
git add platforms/test-management-service
git commit -m "feat(test-management): parse .feature files into cases with Cucumber's own parser

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The import plan, its hash, and applying it

**Files:**
- Create: `platforms/test-management-service/src/casebook/gherkin_import/plan.py`
- Create: `platforms/test-management-service/src/casebook/service/import_service.py`
- Test: `platforms/test-management-service/tests/unit/test_import_plan.py`

**Interfaces:**
- Consumes: `ParsedFile`, `ParsedScenario` and `Issue` from Task 3, and `Case` with its source columns from Task 2.
- Produces:

```python
# plan.py (pure)
@dataclass
class Item:
    action: str                  # create|update|unchanged|move|reactivate|archive|skip
    path: str
    scenario: Optional[str]
    case_id: Optional[int] = None
    case_number: Optional[int] = None
    parsed: Optional[ParsedScenario] = None

@dataclass
class Plan:
    items: List[Item]
    errors: List[Issue]          # parse errors
    warnings: List[Issue]
    plan_hash: str
    def summary(self) -> dict    # {"created","updated","moved","reactivated","archived","unchanged","skipped"}

@dataclass(frozen=True)
class Existing:                  # an imported case, as the planner needs it
    id: int
    number: int
    source_key: str
    source_path: str
    status: str
    title: str
    gherkin: str
    labels: tuple
    priority: str

def build_plan(files: List[ParsedFile], existing: List[Existing], full: bool) -> Plan

# import_service.py
class ImportConflict(Exception): ...
def normalise_path(path: str) -> str      # raises ValueError for a path that is not allowed
def plan_import(db, project_id: int, files: List[tuple], full: bool) -> Plan   # files: [(path, content)], paths already normalised
def apply_plan(db, project_id: int, user_id: int, plan: Plan) -> Plan          # fills case_number; raises ImportConflict
```

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_import_plan.py`

```python
"""The import plan (pure) and its application to the database."""
import pytest

from src.casebook.gherkin_import.parse import parse_feature
from src.casebook.gherkin_import.plan import Existing, build_plan
from src.casebook.models import Case, CaseLabel
from src.casebook.service import import_service

A = "features/a.feature"
FEATURE = "Feature: A\n  @smoke\n  Scenario: one\n    Given x\n  Scenario: two\n    Given y\n"


def existing_from(db, project_id=1):
    return import_service.load_existing(db, project_id)


def run(db, files, full=False, user=1):
    plan = import_service.plan_import(db, 1, files, full)
    return import_service.apply_plan(db, 1, user, plan)


def actions(plan):
    return sorted((i.action, i.path, i.scenario) for i in plan.items)


def test_first_import_creates_numbered_linked_cases(db):
    plan = run(db, [(A, FEATURE)])
    assert plan.summary()["created"] == 2
    one = db.query(Case).filter(Case.title == "one").one()
    assert (one.number, one.source_path, one.status) == (1, A, "draft")
    assert one.gherkin == "Scenario: one\n  Given x"
    assert [l.label for l in one.labels] == ["smoke"]
    assert one.automated_test_key and one.automated_name == "one"


def test_same_batch_twice_is_all_unchanged_and_hash_is_order_free(db):
    b = "features/b.feature"
    first = import_service.plan_import(db, 1, [(A, FEATURE), (b, "Feature: B\n  Scenario: s\n    Given z\n")], False)
    flipped = import_service.plan_import(db, 1, [(b, "Feature: B\n  Scenario: s\n    Given z\n"), (A, FEATURE)], False)
    assert first.plan_hash == flipped.plan_hash
    import_service.apply_plan(db, 1, 1, first)
    again = import_service.plan_import(db, 1, [(A, FEATURE), (b, "Feature: B\n  Scenario: s\n    Given z\n")], False)
    assert {i.action for i in again.items} == {"unchanged"}


def test_changed_steps_update_and_a_gone_scenario_is_archived(db):
    run(db, [(A, FEATURE)])
    plan = run(db, [(A, "Feature: A\n  Scenario: one\n    Given changed\n")])
    assert actions(plan) == [("archive", A, "two"), ("update", A, "one")]
    one = db.query(Case).filter(Case.title == "one").one()
    assert one.gherkin.endswith("Given changed") and one.labels == []
    assert db.query(Case).filter(Case.title == "two").one().status == "archived"


def test_a_returning_scenario_is_reactivated_with_its_number(db):
    run(db, [(A, FEATURE)])
    run(db, [(A, "Feature: A\n  Scenario: one\n    Given x\n")])
    plan = run(db, [(A, FEATURE)])
    assert ("reactivate", A, "two") in actions(plan)
    two = db.query(Case).filter(Case.title == "two").one()
    assert (two.number, two.status) == (2, "draft")


def test_moving_a_file_keeps_numbers(db):
    run(db, [(A, FEATURE)])
    plan = run(db, [("features/moved/a.feature", FEATURE)], full=True)
    assert plan.summary()["moved"] == 2 and plan.summary()["created"] == 0
    one = db.query(Case).filter(Case.title == "one").one()
    assert (one.number, one.source_path) == (1, "features/moved/a.feature")


def test_ambiguous_moves_are_not_moves(db):
    twin = "Feature: A\n  Scenario: same\n    Given x\n"
    run(db, [("x/1.feature", twin), ("x/2.feature", twin)])
    plan = run(db, [("y/1.feature", twin), ("y/2.feature", twin)], full=True)
    assert plan.summary()["moved"] == 0
    assert plan.summary()["created"] == 2 and plan.summary()["archived"] == 2


def test_without_full_only_uploaded_paths_can_be_archived(db):
    run(db, [(A, FEATURE), ("features/b.feature", "Feature: B\n  Scenario: s\n    Given z\n")])
    partial = run(db, [(A, FEATURE)])
    assert partial.summary()["archived"] == 0
    full = run(db, [(A, FEATURE)], full=True)
    assert actions(full)[0] == ("archive", "features/b.feature", "s")


def test_a_broken_file_never_archives_its_cases(db):
    run(db, [(A, FEATURE)])
    plan = run(db, [(A, "Feature: A\n  Scenario: one\n    Given x\n  oops\n")], full=True)
    assert plan.summary()["archived"] == 0 and plan.errors
    assert plan.summary()["skipped"] == 1
    assert db.query(Case).filter(Case.status == "archived").count() == 0


def test_manual_cases_are_never_touched(db):
    db.add(Case(project_id=1, number=1, title="one", steps=[], created_by=1))
    db.commit()
    plan = run(db, [(A, FEATURE)], full=True)
    assert plan.summary()["created"] == 2
    manual = db.query(Case).filter(Case.source_key.is_(None)).one()
    assert manual.status == "draft"
    assert sorted(c.number for c in db.query(Case).all()) == [1, 2, 3]


def test_priority_tag_sets_priority_and_a_manual_link_is_kept(db):
    run(db, [(A, "Feature: A\n  @priority:critical\n  Scenario: one\n    Given x\n")])
    one = db.query(Case).one()
    assert one.priority == "critical"
    one.automated_test_key, one.automated_name = "f" * 64, "picked by hand"
    db.commit()
    run(db, [(A, "Feature: A\n  @priority:critical\n  Scenario: one\n    Given x2\n")])
    db.refresh(one)
    assert one.automated_test_key == "f" * 64


def test_dry_run_plan_writes_nothing_and_new_cases_have_no_number(db):
    plan = import_service.plan_import(db, 1, [(A, FEATURE)], False)
    assert db.query(Case).count() == 0
    assert all(i.case_number is None for i in plan.items)


def test_another_project_is_invisible(db):
    run(db, [(A, FEATURE)])
    plan = import_service.plan_import(db, 2, [(A, FEATURE)], True)
    assert plan.summary()["created"] == 2


@pytest.mark.parametrize("raw, clean", [
    ("tests\\features\\a.feature", "tests/features/a.feature"),
    ("./tests/features/a.feature", "tests/features/a.feature"),
    ("tests/features/a.feature", "tests/features/a.feature"),
])
def test_paths_are_normalised_before_keys_are_computed(raw, clean):
    assert import_service.normalise_path(raw) == clean


@pytest.mark.parametrize("bad", ["", "/etc/a.feature", "C:/a.feature", "a/../b.feature", "x" * 501])
def test_paths_that_are_not_allowed(bad):
    with pytest.raises(ValueError):
        import_service.normalise_path(bad)
```

- [ ] **Step 2: Run the tests and check they fail**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest -q tests/unit/test_import_plan.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.casebook.gherkin_import.plan'`

- [ ] **Step 3: Implement** `src/casebook/gherkin_import/plan.py`

```python
"""Parsed scenarios + the project's imported cases -> what an import would do (ADR-023). Pure."""
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.casebook.gherkin_import.parse import Issue, ParsedFile, ParsedScenario

SUMMARY_NAMES = {"create": "created", "update": "updated", "move": "moved", "reactivate": "reactivated",
                 "archive": "archived", "unchanged": "unchanged", "skip": "skipped"}


@dataclass
class Item:
    action: str
    path: str
    scenario: Optional[str]
    case_id: Optional[int] = None
    case_number: Optional[int] = None
    parsed: Optional[ParsedScenario] = None


@dataclass
class Plan:
    items: List[Item]
    errors: List[Issue] = field(default_factory=list)
    warnings: List[Issue] = field(default_factory=list)
    plan_hash: str = ""

    def summary(self) -> dict:
        counts = {name: 0 for name in SUMMARY_NAMES.values()}
        for item in self.items:
            counts[SUMMARY_NAMES[item.action]] += 1
        return counts


@dataclass(frozen=True)
class Existing:
    id: int
    number: int
    source_key: str
    source_path: str
    status: str
    title: str
    gherkin: str
    labels: tuple
    priority: str


def _differs(case: Existing, scenario: ParsedScenario) -> bool:
    return (
        case.title != scenario.title or case.gherkin != scenario.gherkin or case.labels != scenario.labels
        or (scenario.priority is not None and scenario.priority != case.priority)
    )


def plan_hash(items: List[Item]) -> str:
    """Over the sorted actions, so the order files arrived in never changes it."""
    rows = sorted([i.action, i.path, i.scenario or "", i.case_number or 0] for i in items)
    return hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_plan(files: List[ParsedFile], existing: List[Existing], full: bool) -> Plan:
    plan = Plan(items=[])
    by_key: Dict[str, Existing] = {c.source_key: c for c in existing}
    uploaded = {f.path for f in files}
    broken = {f.path for f in files if f.errors}
    incoming: Dict[str, ParsedScenario] = {}
    for parsed_file in files:
        plan.errors += parsed_file.errors
        plan.warnings += parsed_file.warnings
        if parsed_file.errors:
            plan.items.append(Item("skip", parsed_file.path, None))
        for warning in parsed_file.warnings:
            if warning.message.startswith("skipped a scenario") or warning.message.startswith('skipped "'):
                plan.items.append(Item("skip", parsed_file.path, None))
        for scenario in parsed_file.scenarios:
            incoming[scenario.source_key] = scenario

    creates: List[ParsedScenario] = []
    for key, scenario in incoming.items():
        case = by_key.get(key)
        if case is None:
            creates.append(scenario)
            continue
        if case.status == "archived":
            action = "reactivate"
        elif _differs(case, scenario):
            action = "update"
        else:
            action = "unchanged"
        plan.items.append(Item(action, scenario.path, scenario.name, case.id, case.number, scenario))

    gone = [
        c for c in existing
        if c.source_key not in incoming and c.status != "archived" and c.source_path not in broken
        and (c.source_path in uploaded or full)
    ]

    # A move: exactly one gone case and exactly one new scenario share the same Gherkin text
    gone_by_text, new_by_text = defaultdict(list), defaultdict(list)
    for case in gone:
        gone_by_text[case.gherkin].append(case)
    for scenario in creates:
        new_by_text[scenario.gherkin].append(scenario)
    moved_cases, moved_scenarios = set(), set()
    for text, cases in gone_by_text.items():
        scenarios = new_by_text.get(text, [])
        if len(cases) == 1 and len(scenarios) == 1:
            case, scenario = cases[0], scenarios[0]
            plan.items.append(Item("move", scenario.path, scenario.name, case.id, case.number, scenario))
            moved_cases.add(case.id)
            moved_scenarios.add(scenario.source_key)

    for scenario in creates:
        if scenario.source_key not in moved_scenarios:
            plan.items.append(Item("create", scenario.path, scenario.name, parsed=scenario))
    for case in gone:
        if case.id not in moved_cases:
            plan.items.append(Item("archive", case.source_path, case.title, case.id, case.number))

    plan.items.sort(key=lambda i: (i.path, i.scenario or "", i.action))
    plan.plan_hash = plan_hash(plan.items)
    return plan
```

Then `src/casebook/service/import_service.py`:

```python
"""Gherkin import against the database (ADR-023): load, plan, apply in one transaction."""
import re
from datetime import datetime, timezone
from typing import List, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.casebook.gherkin_import.parse import parse_feature
from src.casebook.gherkin_import.plan import Existing, Plan, build_plan
from src.casebook.models import Case, CaseLabel

PATH_LENGTH = 500
DRIVE = re.compile(r"^[A-Za-z]:")


class ImportConflict(Exception):
    """Another import into the same project committed first."""


def normalise_path(path: str) -> str:
    clean = path.replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    if not clean or clean.startswith("/") or DRIVE.match(clean) or ".." in clean.split("/") or len(clean) > PATH_LENGTH:
        raise ValueError(f"path not allowed: {path!r} (relative to the repository root, no '..')")
    return clean


def load_existing(db: Session, project_id: int) -> List[Existing]:
    rows = db.query(Case).filter(Case.project_id == project_id, Case.source_key.isnot(None)).all()
    return [
        Existing(id=r.id, number=r.number, source_key=r.source_key, source_path=r.source_path or "",
                 status=r.status, title=r.title, gherkin=r.gherkin or "",
                 labels=tuple(sorted(l.label for l in r.labels)), priority=r.priority)
        for r in rows
    ]


def plan_import(db: Session, project_id: int, files: List[Tuple[str, str]], full: bool) -> Plan:
    parsed = [parse_feature(path, content) for path, content in files]
    return build_plan(parsed, load_existing(db, project_id), full)


def _content(row: Case, scenario) -> None:
    row.title = scenario.title
    row.gherkin = scenario.gherkin
    row.labels = [CaseLabel(label=label) for label in scenario.labels]
    if scenario.priority is not None:
        row.priority = scenario.priority
    if not row.automated_test_key:
        row.automated_test_key, row.automated_name = scenario.test_key, scenario.test_name[:1500]


def apply_plan(db: Session, project_id: int, user_id: int, plan: Plan) -> Plan:
    now = datetime.now(timezone.utc)
    ids = [i.case_id for i in plan.items if i.case_id is not None]
    rows = {r.id: r for r in db.query(Case).filter(Case.id.in_(ids)).all()} if ids else {}
    next_number = (db.execute(select(func.max(Case.number)).where(Case.project_id == project_id)).scalar() or 0) + 1
    for item in plan.items:
        if item.action in ("unchanged", "skip"):
            continue
        if item.action == "create":
            s = item.parsed
            row = Case(project_id=project_id, number=next_number, title=s.title, description=s.description,
                       steps=[], gherkin=s.gherkin, source_path=s.path, source_key=s.source_key,
                       priority=s.priority or "medium", created_by=user_id,
                       automated_test_key=s.test_key, automated_name=s.test_name[:1500],
                       labels=[CaseLabel(label=label) for label in s.labels])
            db.add(row)
            item.case_number = next_number
            next_number += 1
            continue
        row = rows[item.case_id]
        if item.action == "archive":
            row.status = "archived"
        else:  # update, move, reactivate
            _content(row, item.parsed)
            row.source_path, row.source_key = item.parsed.path, item.parsed.source_key
            if item.action == "reactivate":
                row.status = "draft"
        row.updated_by, row.updated_at = user_id, now
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ImportConflict() from exc
    return plan
```

- [ ] **Step 4: Run the tests and check they pass**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest -q tests/unit/test_import_plan.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add platforms/test-management-service
git commit -m "feat(test-management): plan and apply a Gherkin import (create, update, move, reactivate, archive)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The endpoint, limits and read-only imported cases

**Files:**
- Create: `platforms/test-management-service/src/casebook/schemas/case_import.py`
- Create: `platforms/test-management-service/src/casebook/api/v1/endpoints/case_import.py`
- Modify: `platforms/test-management-service/src/casebook/api/v1/api.py`
- Modify: `platforms/test-management-service/src/casebook/schemas/case.py`, `service/case_service.py`, `api/v1/endpoints/cases.py`
- Test: `platforms/test-management-service/tests/integration/test_import.py`, `tests/integration/test_cases.py`

**Interfaces:**
- Consumes: `import_service.normalise_path`, `plan_import`, `apply_plan`, `ImportConflict`, and `Plan.summary()`.
- Produces the HTTP contract that the dashboard (Task 7) uses:
  - `POST /api/v1/projects/{id}/cases/import?dry_run=true|false`
  - Body: `{files: [{path, content}], full?: bool, expected_plan_hash?: str}`
  - 200 body: `{plan_hash, summary, items: [{action, path, scenario, case_number}], errors: [{path, line, message}], warnings: [...]}`
  - `CaseOut` gains `source_path: str|null` and `gherkin: str|null`.
  - `GET /cases?origin=manual|imported`.

- [ ] **Step 1: Write the failing tests.** In `tests/integration/test_import.py`:

```python
"""POST /cases/import: dry run, apply, plan hash, limits, roles; imported cases are read-only."""
import pytest

from src.casebook.core.config import settings

URL = "/api/v1/projects/1/cases/import"
FEATURE = "Feature: A\n  @smoke\n  Scenario: one\n    Given x\n"


def body(*files, **extra):
    return {"files": [{"path": p, "content": c} for p, c in files], **extra}


@pytest.fixture
def member(project_role):
    project_role("member")


def test_dry_run_previews_and_writes_nothing(client, auth, member):
    r = client.post(f"{URL}?dry_run=true", json=body(("a.feature", FEATURE)), headers=auth())
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["summary"]["created"] == 1 and len(data["plan_hash"]) == 64
    assert data["items"] == [{"action": "create", "path": "a.feature", "scenario": "one", "case_number": None}]
    assert client.get("/api/v1/projects/1/cases", headers=auth()).json()["total"] == 0


def test_apply_with_the_previewed_hash_imports(client, auth, member):
    preview = client.post(f"{URL}?dry_run=true", json=body(("a.feature", FEATURE)), headers=auth()).json()
    r = client.post(URL, json=body(("a.feature", FEATURE), expected_plan_hash=preview["plan_hash"]), headers=auth())
    assert r.status_code == 200 and r.json()["items"][0]["case_number"] == 1


def test_a_stale_hash_is_409_and_writes_nothing(client, auth, member):
    r = client.post(URL, json=body(("a.feature", FEATURE), expected_plan_hash="0" * 64), headers=auth())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "plan_changed"
    assert client.get("/api/v1/projects/1/cases", headers=auth()).json()["total"] == 0


def test_parse_errors_come_back_with_their_line(client, auth, member):
    r = client.post(f"{URL}?dry_run=true", json=body(("b.feature", "Feature: B\n  oops\n")), headers=auth())
    assert r.status_code == 200
    assert r.json()["errors"][0]["path"] == "b.feature" and r.json()["errors"][0]["line"] == 2


@pytest.mark.parametrize("path", ["/abs.feature", "../up.feature", "C:\\x.feature"])
def test_paths_outside_the_repository_are_422(client, auth, member, path):
    assert client.post(URL, json=body((path, FEATURE)), headers=auth()).status_code == 422


def test_the_same_path_twice_is_422(client, auth, member):
    r = client.post(URL, json=body(("a.feature", FEATURE), ("./a.feature", FEATURE)), headers=auth())
    assert r.status_code == 422


@pytest.mark.parametrize("setting, value, files", [
    ("IMPORT_MAX_FILES", 1, [("a.feature", FEATURE), ("b.feature", FEATURE)]),
    ("IMPORT_MAX_FILE_BYTES", 10, [("a.feature", FEATURE)]),
    ("IMPORT_MAX_TOTAL_BYTES", 50, [("a.feature", FEATURE), ("b.feature", FEATURE)]),
])
def test_limits_are_413_and_name_their_setting(client, auth, member, monkeypatch, setting, value, files):
    monkeypatch.setattr(settings, setting, value)
    r = client.post(URL, json=body(*files), headers=auth())
    assert r.status_code == 413 and setting in r.json()["detail"]


def test_viewer_is_403_and_strangers_404(client, auth, project_role):
    project_role("viewer")
    assert client.post(URL, json=body(("a.feature", FEATURE)), headers=auth()).status_code == 403
    project_role(status_code=404, body={"detail": "Project not found"})
    assert client.post(URL, json=body(("a.feature", FEATURE)), headers=auth()).status_code == 404


def test_imported_cases_are_read_only_where_the_repository_owns_them(client, auth, member):
    client.post(URL, json=body(("a.feature", FEATURE)), headers=auth())
    case = client.get("/api/v1/projects/1/cases/1", headers=auth()).json()
    assert case["source_path"] == "a.feature" and case["gherkin"].startswith("Scenario: one")
    for field, value in [("title", "x"), ("labels", ["y"]), ("steps", []), ("gherkin", "z")]:
        r = client.patch("/api/v1/projects/1/cases/1", json={field: value}, headers=auth())
        assert r.status_code == 422, field
    ok = client.patch("/api/v1/projects/1/cases/1", json={"priority": "high", "status": "ready",
                                                          "description": "d"}, headers=auth())
    assert ok.status_code == 200 and ok.json()["priority"] == "high"


def test_origin_filter_and_search_in_gherkin(client, auth, member):
    client.post(URL, json=body(("a.feature", FEATURE)), headers=auth())
    client.post("/api/v1/projects/1/cases", json={"title": "manual"}, headers=auth())
    cases = "/api/v1/projects/1/cases"
    assert [c["title"] for c in client.get(f"{cases}?origin=imported", headers=auth()).json()["items"]] == ["one"]
    assert [c["title"] for c in client.get(f"{cases}?origin=manual", headers=auth()).json()["items"]] == ["manual"]
    assert [c["title"] for c in client.get(f"{cases}?search=given%20x", headers=auth()).json()["items"]] == ["one"]
```

Also check the `project_role` fixture in `tests/conftest.py`. A 404 from project-service must make
`project_client` raise `ProjectNotFound`, as `test_cases.py` already relies on. If the role
fixture's signature differs, mirror how `test_cases.py` sets up a 404 caller.

- [ ] **Step 2: Run the tests and check they fail**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest -q tests/integration/test_import.py`
Expected: FAIL with 404 or 405 on `/cases/import`.

- [ ] **Step 3: Implement**

`src/casebook/schemas/case_import.py`:

```python
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.casebook.service.import_service import normalise_path


class ImportFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content: str

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        return normalise_path(value)  # ValueError -> 422


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: List[ImportFile] = Field(min_length=1)
    full: bool = False
    expected_plan_hash: Optional[str] = Field(None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("files")
    @classmethod
    def _unique_paths(cls, files: List[ImportFile]) -> List[ImportFile]:
        paths = [f.path for f in files]
        if len(paths) != len(set(paths)):
            raise ValueError("the same path appears twice")
        return files


class ImportIssueOut(BaseModel):
    path: str
    line: Optional[int] = None
    message: str


class ImportItemOut(BaseModel):
    action: Literal["create", "update", "unchanged", "move", "reactivate", "archive", "skip"]
    path: str
    scenario: Optional[str] = None
    case_number: Optional[int] = None


class ImportResult(BaseModel):
    plan_hash: str
    summary: dict
    items: List[ImportItemOut]
    errors: List[ImportIssueOut]
    warnings: List[ImportIssueOut]
```

`src/casebook/api/v1/endpoints/case_import.py`:

```python
"""POST /projects/{id}/cases/import (ADR-023, docs/superpowers/specs/2026-10-06-gherkin-import-design.md)."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.casebook.api.deps import EDIT_ROLES, ProjectAccess, get_db, require_project_role
from src.casebook.core.config import settings
from src.casebook.schemas.case_import import ImportRequest, ImportResult
from src.casebook.service import import_service

router = APIRouter()  # mounted at /projects/{project_id}/cases, before cases.router


def _too_large(message: str, setting: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                         detail=f"{message} (the {setting} setting)")


def _check_limits(payload: ImportRequest) -> None:
    if len(payload.files) > settings.IMPORT_MAX_FILES:
        raise _too_large(f"more than {settings.IMPORT_MAX_FILES} files", "IMPORT_MAX_FILES")
    total = 0
    for f in payload.files:
        size = len(f.content.encode("utf-8"))
        if size > settings.IMPORT_MAX_FILE_BYTES:
            raise _too_large(f"{f.path} is over {settings.IMPORT_MAX_FILE_BYTES} bytes", "IMPORT_MAX_FILE_BYTES")
        total += size
    if total > settings.IMPORT_MAX_TOTAL_BYTES:
        raise _too_large(f"files total over {settings.IMPORT_MAX_TOTAL_BYTES} bytes", "IMPORT_MAX_TOTAL_BYTES")


def _out(plan) -> dict:
    issue = lambda i: {"path": i.path, "line": i.line, "message": i.message}  # noqa: E731
    return {
        "plan_hash": plan.plan_hash, "summary": plan.summary(),
        "items": [{"action": i.action, "path": i.path, "scenario": i.scenario, "case_number": i.case_number}
                  for i in plan.items],
        "errors": [issue(e) for e in plan.errors], "warnings": [issue(w) for w in plan.warnings],
    }


@router.post("/import", response_model=ImportResult)
def import_cases(
    payload: ImportRequest,
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
    access: ProjectAccess = Depends(require_project_role(*EDIT_ROLES)),
):
    _check_limits(payload)
    files = [(f.path, f.content) for f in payload.files]
    plan = import_service.plan_import(db, access.project_id, files, payload.full)
    if dry_run:
        return _out(plan)
    if payload.expected_plan_hash and payload.expected_plan_hash != plan.plan_hash:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "plan_changed", "message": "Something changed since your preview"})
    try:
        import_service.apply_plan(db, access.project_id, access.user_id, plan)
    except import_service.ImportConflict:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail={"code": "import_conflict", "message": "Another import is running; try again"})
    return _out(plan)
```

In `api/v1/api.py`, import `case_import` and add this line **before** the `cases.router` line:
`api_router.include_router(case_import.router, prefix="/projects/{project_id}/cases", tags=["cases"])`

In `schemas/case.py`:
- In `CaseUpdate`, add `gherkin: Optional[str] = None`. It is accepted so that the 422 below can name it; manual cases ignore it.
- In `CaseOut`, add `source_path: Optional[str] = None` and `gherkin: Optional[str] = None`.

In `service/case_service.py`:
- `out()` adds `"source_path": row.source_path, "gherkin": row.gherkin`.
- `list_cases` gains a keyword parameter `origin: Optional[str]`:

```python
    if origin == "imported":
        query = query.filter(Case.source_key.isnot(None))
    elif origin == "manual":
        query = query.filter(Case.source_key.is_(None))
    if search:
        pattern = f"%{_escape_like(search)}%"
        query = query.filter(or_(Case.title.ilike(pattern, escape="\\"), Case.gherkin.ilike(pattern, escape="\\")))
```

  This replaces the existing `if search:` block. Add `or_` to the `sqlalchemy` import.
- Add the guard:

```python
REPOSITORY_FIELDS = ("title", "steps", "labels", "gherkin")


def repository_owned(row: Case, changes: dict) -> list:
    """Fields a PATCH may not change on an imported case: its .feature file owns them (ADR-023)."""
    if row.source_key is None:
        changes.pop("gherkin", None)
        return []
    return [f for f in REPOSITORY_FIELDS if f in changes]
```

In `endpoints/cases.py`:
- `list_cases` gains `origin: Optional[Literal["manual", "imported"]] = Query(None)` (import `Literal` from `typing`) and passes `origin=origin`.
- In `update_case`, after `_case_or_404`:

```python
    changes = payload.model_dump(exclude_unset=True)
    owned = case_service.repository_owned(row, changes)
    if owned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"{', '.join(owned)} come from {row.source_path}; change the .feature file instead")
    row = case_service.update_case(db, row, access.user_id, changes)
```

- [ ] **Step 4: Run the whole suite and check it passes**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest -q`
Expected: all PASS, including the existing `test_cases.py` and `test_suites.py`.

- [ ] **Step 5: Commit**

```bash
git add platforms/test-management-service
git commit -m "feat(test-management): POST /cases/import with dry run, plan hash and limits; imported cases are read-only

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Contract test between the collector's key and the import's key

**Files:**
- Create: `platforms/test-management-service/tests/fixtures/cucumber_report.json`
- Create: `platforms/test-management-service/tests/unit/test_key_contract.py`

**Interfaces:**
- Consumes: `collector/src/qav_collector/formats.parse_file(path) -> ParsedFile` (dict rows with `suite`, `class_name` and `name`), `qav_shared.keys.test_key`, and `parse_feature`.

- [ ] **Step 1: Write the fixture**, `tests/fixtures/cucumber_report.json`. It has the shape cucumber-js's `json` formatter writes for `tests/fixtures/checkout.feature` when run from the repository root as `tests/features/checkout.feature`. The outline rows carry filled names.

```json
[
  {
    "uri": "tests/features/checkout.feature",
    "id": "checkout",
    "keyword": "Feature",
    "name": "Checkout",
    "elements": [
      {"type": "background", "keyword": "Background", "name": "", "steps": [
        {"keyword": "Given ", "name": "a signed-in shopper", "result": {"status": "passed", "duration": 1}}]},
      {"type": "scenario", "keyword": "Scenario", "name": "Pay by card", "steps": [
        {"keyword": "When ", "name": "I pay with a stored card", "result": {"status": "passed", "duration": 1}}]},
      {"type": "scenario", "keyword": "Scenario Outline", "name": "Apply SAVE10", "steps": [
        {"keyword": "When ", "name": "I apply \"SAVE10\"", "result": {"status": "passed", "duration": 1}}]},
      {"type": "scenario", "keyword": "Scenario Outline", "name": "Apply SAVE20", "steps": [
        {"keyword": "When ", "name": "I apply \"SAVE20\"", "result": {"status": "passed", "duration": 1}}]},
      {"type": "scenario", "keyword": "Scenario", "name": "Tag edge cases", "steps": [
        {"keyword": "Given ", "name": "nothing", "result": {"status": "passed", "duration": 1}}]}
    ]
  }
]
```

- [ ] **Step 2: Write the test**

```python
"""The import must compute the very key ingestion stores for the same scenario (ADR-023).

The collector has no dependencies, so its parser is loaded straight from the repository."""
import sys
from pathlib import Path

from qav_shared.keys import test_key
from src.casebook.gherkin_import.parse import parse_feature

REPO = Path(__file__).resolve().parents[4]
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
sys.path.insert(0, str(REPO / "collector" / "src"))
from qav_collector.formats import parse_file  # noqa: E402


def test_imported_cases_link_to_the_keys_results_are_stored_under():
    rows = parse_file(str(FIXTURES / "cucumber_report.json")).results
    stored = {test_key(r["suite"], r["class_name"], r["name"]) for r in rows}
    feature = (FIXTURES / "checkout.feature").read_text(encoding="utf-8")
    imported = parse_feature("tests/features/checkout.feature", feature).scenarios
    assert {s.test_key for s in imported} <= stored
    assert len(imported) == 3
```

- [ ] **Step 3: Run the test**

Run: `SECRET_KEY=test .venv/Scripts/python -m pytest -q tests/unit/test_key_contract.py`
Expected: PASS. If it fails, either the collector strips or cuts the names differently from
`parse.py`, or `REPO` resolves to the wrong place: `parents[4]` of `tests/unit/x.py` is the
repository root. Print both sets and fix `parse.py` so it matches what the collector produces.
Never change the fixture to make the test pass.

- [ ] **Step 4: Commit**

```bash
git add platforms/test-management-service/tests
git commit -m "test(test-management): imported cases carry the key the collector's results are stored under

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Dashboard import page

**Files:**
- Modify: `dashboard/src/api/cases.ts`
- Create: `dashboard/src/pages/CaseImportPage.tsx`
- Create: `dashboard/src/pages/CaseImport.test.tsx`
- Modify: `dashboard/src/App.tsx` (route `cases/import`, before `cases/:caseNumber`)
- Modify: `dashboard/src/pages/CasesPage.tsx` (an "Import from Gherkin" link beside "New case", shown when `canEdit`)

**Interfaces:**
- Consumes the HTTP contract from Task 5.
- Produces in `api/cases.ts`:

```ts
export type ImportAction = "create" | "update" | "unchanged" | "move" | "reactivate" | "archive" | "skip";
export interface ImportIssue { path: string; line: number | null; message: string }
export interface ImportItem { action: ImportAction; path: string; scenario: string | null; case_number: number | null }
export interface ImportResult {
  plan_hash: string;
  summary: Record<"created" | "updated" | "moved" | "reactivated" | "archived" | "unchanged" | "skipped", number>;
  items: ImportItem[];
  errors: ImportIssue[];
  warnings: ImportIssue[];
}
export interface ImportFile { path: string; content: string }
export function importCases(projectId: number, files: ImportFile[], opts: { dryRun: boolean; expectedPlanHash?: string }): Promise<ImportResult>
```

Also add `source_path: string | null` and `gherkin: string | null` to `Case`, and
`origin?: "manual" | "imported"` to `CaseQuery`.

- [ ] **Step 1: Invoke the `ui-ux-pro-max` skill** for a file-import page with a preview table in this dashboard. Follow the dashboard's existing classes (`button primary`, `ErrorBanner`, the table styles on `CasesPage`) and its dark-mode and 375px rules.

- [ ] **Step 2: Write the failing tests** in `dashboard/src/pages/CaseImport.test.tsx`. Reuse the `asRole` and `renderAt` pattern from `TestManagement.test.tsx`, with a route for `/projects/:projectId/cases/import`.

```tsx
const preview = {
  plan_hash: "c".repeat(64),
  summary: { created: 1, updated: 0, moved: 0, reactivated: 0, archived: 1, unchanged: 1, skipped: 0 },
  items: [
    { action: "create", path: "tests/features/a.feature", scenario: "Pay", case_number: null },
    { action: "archive", path: "tests/features/a.feature", scenario: "Old", case_number: 3 },
    { action: "unchanged", path: "tests/features/a.feature", scenario: "Same", case_number: 2 },
  ],
  errors: [{ path: "tests/features/b.feature", line: 4, message: "(4:3): expected ..." }],
  warnings: [],
};

function featureFile(name: string, text: string, relative: string) {
  const file = new File([text], name, { type: "" });
  Object.defineProperty(file, "webkitRelativePath", { value: relative });
  return file;
}

test("previews the chosen .feature files with the prefix, then imports with the previewed hash", async () => {
  asRole("member");
  const bodies: any[] = [];
  server.use(http.post(`${P}/cases/import`, async ({ request }) => {
    const url = new URL(request.url);
    const json = await request.json();
    bodies.push({ dry: url.searchParams.get("dry_run"), json });
    return HttpResponse.json(url.searchParams.get("dry_run") === "true"
      ? preview : { ...preview, items: [{ ...preview.items[0], case_number: 9 }] });
  }));
  renderAt("/projects/42/cases/import");
  const user = userEvent.setup();
  await user.upload(await screen.findByLabelText(/choose folder/i), [
    featureFile("a.feature", "Feature: A", "features/a.feature"),
    featureFile("notes.md", "x", "features/notes.md"),
  ]);
  expect(screen.getByText(/1 \.feature file/i)).toBeInTheDocument();
  await user.type(screen.getByLabelText(/path prefix/i), "tests/");
  await user.click(screen.getByRole("button", { name: /preview/i }));
  expect(await screen.findByText("Pay")).toBeInTheDocument();
  expect(screen.queryByText("Same")).not.toBeInTheDocument();        // unchanged hidden by default
  expect(screen.getByText(/\(4:3\)/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /import 2 changes/i }));
  expect(await screen.findByText(/imported: 1 created/i)).toBeInTheDocument();
  expect(bodies[0]).toEqual({ dry: "true", json: { files: [{ path: "tests/features/a.feature", content: "Feature: A" }], full: false } });
  expect(bodies[1].json.expected_plan_hash).toBe("c".repeat(64));
});

test("a plan that changed since the preview shows the new preview and says so", async () => {
  asRole("member");
  let calls = 0;
  server.use(http.post(`${P}/cases/import`, ({ request }) => {
    calls += 1;
    const dry = new URL(request.url).searchParams.get("dry_run") === "true";
    if (!dry) return HttpResponse.json({ detail: { code: "plan_changed", message: "Something changed since your preview" } }, { status: 409 });
    return HttpResponse.json(calls === 1 ? preview : { ...preview, plan_hash: "d".repeat(64) });
  }));
  renderAt("/projects/42/cases/import");
  const user = userEvent.setup();
  await user.upload(await screen.findByLabelText(/choose folder/i), [featureFile("a.feature", "Feature: A", "f/a.feature")]);
  await user.click(screen.getByRole("button", { name: /preview/i }));
  await user.click(await screen.findByRole("button", { name: /import 2 changes/i }));
  expect(await screen.findByText(/something changed since your preview/i)).toBeInTheDocument();
});

test("viewers do not get the import page's controls", async () => {
  asRole("viewer");
  renderAt("/projects/42/cases/import");
  expect(await screen.findByText(/only editors can import/i)).toBeInTheDocument();
});
```

If `http.ts` reads the 409 body's `detail` as a string, check how `ApiError` exposes an object
`detail`, and match `/plan_changed|something changed/i` in the page logic accordingly.

- [ ] **Step 3: Run the tests and check they fail**

Run, from `dashboard/`: `npx vitest run src/pages/CaseImport.test.tsx`
Expected: FAIL, because the module `./CaseImportPage` is not found.

- [ ] **Step 4: Implement**

In `api/cases.ts`:

```ts
export function importCases(
  projectId: number,
  files: ImportFile[],
  opts: { dryRun: boolean; expectedPlanHash?: string },
): Promise<ImportResult> {
  const body = { files, full: false, ...(opts.expectedPlanHash ? { expected_plan_hash: opts.expectedPlanHash } : {}) };
  return apiFetch(`${base(projectId)}/cases/import?dry_run=${opts.dryRun}`, { method: "POST", body: JSON.stringify(body) });
}
```

Then build `CaseImportPage.tsx`:
- **State:** `files: ImportFile[]`, `prefix: string`, `preview: ImportResult | null`, `result: ImportResult | null`, `changed: boolean`, `filter: ImportAction | null`.
- **Choose:** three inputs.
  - A drop zone.
  - `<input type="file" webkitdirectory multiple aria-label="Choose folder">`. Pass `webkitdirectory` via a spread `{...{ webkitdirectory: "" }}` so TypeScript accepts it.
  - `<input type="file" accept=".feature" multiple aria-label="Choose files">`.
  - The reader keeps names ending in `.feature`, reads them with `file.text()`, and takes the path from `file.webkitRelativePath || file.name`.
  - It shows "N .feature file(s) found".
- **Path prefix:** a labelled text input, "Path prefix", with the hint: "Paths must match what your runner reports, e.g. `tests/` when you chose `features/`". The request path is `prefix.replace(/\/?$/, prefix ? "/" : "") + path`, with no double slash.
- **Preview:** a `useMutation` calling `importCases(id, withPrefix, { dryRun: true })`. It renders:
  - one counter button per summary entry, which sets `filter`;
  - a table of action, path, scenario and `TC-n` (linking to `../{case_number}`). Rows with `action === "unchanged"` are hidden unless `filter === "unchanged"`;
  - an errors block listing `path:line message`.
- **Import:** a button labelled `Import {n} changes`, where `n` is the sum of the summary values except `unchanged` and `skipped`. It is disabled when `n === 0`. It calls `importCases(..., { dryRun: false, expectedPlanHash: preview.plan_hash })`.
  - On an `ApiError` with status 409 whose detail mentions `plan_changed`: re-run the preview, set `changed`, and show the banner "Something changed since your preview".
  - On success: show "Imported: N created, …" and a link to `../?origin=imported`. Invalidate the cases queries (`queryClient.invalidateQueries({ queryKey: ["cases"] })`, matching the key `CasesPage` uses).
- **Viewers:** when `useCanEdit` is false, render "Only editors can import cases" and no controls.

In `App.tsx`, add `<Route path="cases/import" element={<CaseImportPage />} />` before `cases/:caseNumber`.
In `CasesPage.tsx`, next to the "New case" link, add
`{canEdit && <Link className="button" to="import"><Upload size={16} aria-hidden="true" /> Import from Gherkin</Link>}`
and import `Upload` from `lucide-react`.

- [ ] **Step 5: Run the tests and check they pass**

Run: `npx vitest run src/pages/CaseImport.test.tsx src/pages/TestManagement.test.tsx`, then `npx tsc --noEmit`.
Expected: all PASS, with no type errors.

- [ ] **Step 6: Commit**

```bash
git add dashboard/src
git commit -m "feat(dashboard): import cases from a folder of .feature files, with a preview

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Imported cases in the editor and the list

**Files:**
- Create: `dashboard/src/lib/gherkinTokens.ts`, `dashboard/src/lib/gherkinTokens.test.ts`
- Create: `dashboard/src/components/GherkinBlock.tsx`
- Modify: `dashboard/src/pages/CaseEditorPage.tsx`, `dashboard/src/pages/CasesPage.tsx`
- Test: `dashboard/src/pages/TestManagement.test.tsx`

**Interfaces:**
- Produces: `tokenizeLine(line: string): { kind: "keyword" | "tag" | "table" | "docstring" | "comment" | "text"; text: string }[]` and `<GherkinBlock text={string} />`.

- [ ] **Step 1: Invoke the `ui-ux-pro-max` skill** for a read-only code block and a "source" badge in the editor.

- [ ] **Step 2: Write the failing tests**

`lib/gherkinTokens.test.ts`:

```ts
import { tokenizeLine } from "./gherkinTokens";

test("keywords, tags, tables, doc strings and comments", () => {
  expect(tokenizeLine("  Given a cart")).toEqual([{ kind: "text", text: "  " }, { kind: "keyword", text: "Given " }, { kind: "text", text: "a cart" }]);
  expect(tokenizeLine("Scenario Outline: Pay")[1]).toEqual({ kind: "keyword", text: "Scenario Outline:" });
  expect(tokenizeLine("    | a | b |")[1].kind).toBe("table");
  expect(tokenizeLine('    """json')[1].kind).toBe("docstring");
  expect(tokenizeLine("@smoke @ado-1")[0].kind).toBe("tag");
  expect(tokenizeLine("# note")[0].kind).toBe("comment");
  expect(tokenizeLine("  Dado um carrinho")[1]).toEqual({ kind: "keyword", text: "Dado " });
});
```

Append to `TestManagement.test.tsx`:

```tsx
test("an imported case shows its source and Gherkin read-only", async () => {
  asRole("member");
  server.use(http.get(`${P}/cases/7`, () => HttpResponse.json(kase(7, {
    source_path: "tests/features/a.feature", gherkin: "Scenario: Pay\n  Given a cart", labels: ["smoke"],
  }))));
  renderAt("/projects/42/cases/7");
  expect(await screen.findByText(/imported from/i)).toHaveTextContent("tests/features/a.feature");
  expect(screen.getByText("Given")).toBeInTheDocument();
  expect(screen.getByLabelText(/title/i)).toHaveAttribute("readonly");
  expect(screen.queryByRole("button", { name: /add step/i })).not.toBeInTheDocument();
});

test("saving an imported case sends only the fields QA Vision owns", async () => {
  asRole("member");
  let sent: any = null;
  server.use(
    http.get(`${P}/cases/7`, () => HttpResponse.json(kase(7, { source_path: "a.feature", gherkin: "Scenario: x" }))),
    http.patch(`${P}/cases/7`, async ({ request }) => { sent = await request.json(); return HttpResponse.json(kase(7)); }),
  );
  renderAt("/projects/42/cases/7");
  const user = userEvent.setup();
  await user.selectOptions(await screen.findByLabelText(/priority/i), "high");
  await user.click(screen.getByRole("button", { name: /save/i }));
  await vi.waitFor(() => expect(sent).not.toBeNull());
  expect(Object.keys(sent).sort()).toEqual(["description", "priority", "status"]);
});

test("the origin filter reaches the API", async () => {
  asRole("member");
  const seen: string[] = [];
  server.use(
    http.get(`${P}/cases`, ({ request }) => { seen.push(new URL(request.url).searchParams.get("origin") ?? ""); return HttpResponse.json({ total: 0, items: [] }); }),
    http.get(`${P}/case-labels`, () => HttpResponse.json([])),
  );
  renderAt("/projects/42/cases");
  await userEvent.setup().selectOptions(await screen.findByLabelText(/origin/i), "imported");
  await vi.waitFor(() => expect(seen).toContain("imported"));
});
```

Update the existing `kase()` helper's defaults with `source_path: null, gherkin: null`. If the
editor's labels or button names differ (for example "Save case"), match the existing names used
in this file. Do not rename UI text.

- [ ] **Step 3: Run the tests and check they fail**

Run: `npx vitest run src/lib/gherkinTokens.test.ts src/pages/TestManagement.test.tsx`
Expected: the new tests FAIL.

- [ ] **Step 4: Implement**

`lib/gherkinTokens.ts`:

```ts
// Read-only highlighting for imported cases. Keyword lists cover English and Portuguese, the
// languages in use; other languages still render, just without keyword colour.
export type TokenKind = "keyword" | "tag" | "table" | "docstring" | "comment" | "text";
export interface Token { kind: TokenKind; text: string }

const HEADINGS = ["Scenario Outline:", "Scenario Template:", "Scenario:", "Example:", "Examples:", "Background:", "Rule:", "Feature:",
  "Esquema do Cenário:", "Cenário:", "Exemplos:", "Contexto:", "Regra:", "Funcionalidade:"];
const STEPS = ["Given ", "When ", "Then ", "And ", "But ", "* ", "Dado ", "Dada ", "Quando ", "Então ", "E ", "Mas "];

export function tokenizeLine(line: string): Token[] {
  const indent = line.match(/^\s*/)![0];
  const rest = line.slice(indent.length);
  const lead: Token[] = indent ? [{ kind: "text", text: indent }] : [];
  if (rest.startsWith("#")) return [...lead, { kind: "comment", text: rest }];
  if (rest.startsWith("@")) return [...lead, { kind: "tag", text: rest }];
  if (rest.startsWith("|")) return [...lead, { kind: "table", text: rest }];
  if (rest.startsWith('"""') || rest.startsWith("```")) return [...lead, { kind: "docstring", text: rest }];
  const keyword = [...HEADINGS, ...STEPS].find((k) => rest.startsWith(k));
  if (!keyword) return [...lead, { kind: "text", text: rest }];
  const tail = rest.slice(keyword.length);
  return [...lead, { kind: "keyword", text: keyword }, ...(tail ? [{ kind: "text" as const, text: tail }] : [])];
}
```

The test for `"  Given a cart"` expects `{ kind: "keyword", text: "Given " }`, and
`screen.getByText("Given")` matches it through the default whitespace normalisation.

`components/GherkinBlock.tsx` renders `<pre className="gherkin" aria-label="Gherkin">`, with one
`<span className={`gk-${kind}`}>` per token and a newline between lines. Add the `gk-*` colours to
the dashboard stylesheet as tokens, with light and dark values, following the existing CSS
variables.

`CaseEditorPage.tsx`, when `case.source_path`:
- show a badge, "Imported from `<path>`", with a note: "Title, steps and labels come from the .feature file";
- render `<GherkinBlock text={case.gherkin ?? ""} />` instead of the steps editor;
- make the title and labels inputs `readOnly`;
- on save, send `{ priority, status, description }` only, built from the draft. The automated-link widget keeps sending its own PATCH unchanged.

`CasesPage.tsx`:
- add an "Origin" select (All / Manual / Imported) bound to the URL parameter `origin`, like the other filters, and passed to `listCases`;
- in the title cell, show a small `FileCode` icon (from `lucide-react`) with `aria-label="Imported"` when `source_path` is set.

- [ ] **Step 5: Run the tests and check they pass**

Run: `npx vitest run`, then `npx tsc --noEmit`.
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add dashboard/src
git commit -m "feat(dashboard): imported cases show their Gherkin read-only; filter cases by origin

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Gateway body limit, compose settings and smoke

**Files:**
- Modify: `gateway/nginx.conf.template`, `gateway/entrypoint.sh`
- Modify: `docker-compose.yml`, `.env.example`
- Modify: `scripts/smoke_gateway.sh`

**Interfaces:**
- Produces: the env vars `GATEWAY_IMPORT_MAX_BODY`, `IMPORT_MAX_FILES`, `IMPORT_MAX_FILE_BYTES` and `IMPORT_MAX_TOTAL_BYTES`.

- [ ] **Step 1: Write the failing smoke checks.** In `scripts/smoke_gateway.sh`, after the `list suites` check:

```bash
IMPORT_BODY='{"files":[{"path":"tests/features/smoke.feature","content":"Feature: Smoke\n  Scenario: imported\n    Given the gateway\n"}]}'
check "import a .feature -> test-management-service" 200 POST "$BASE/api/v1/projects/$PROJECT_ID/cases/import" \
  "${AUTH[@]}" -H "Content-Type: application/json" -d "$IMPORT_BODY"
body_has "... one case created" '"created":1'
# A body over the gateway's general 10 MB cap must still reach the service on the import path:
# the service answers 413 naming its own setting, not NGINX's bare 413 page
python3 - "$TMP/big.json" <<'PY'
import json, sys
json.dump({"files": [{"path": f"f{i}.feature", "content": "x" * 200000} for i in range(55)]}, open(sys.argv[1], "w"))
PY
check "an 11 MB import reaches the service" 413 POST "$BASE/api/v1/projects/$PROJECT_ID/cases/import" \
  "${AUTH[@]}" -H "Content-Type: application/json" --data-binary "@$TMP/big.json"
body_has "... and the service answered it" 'IMPORT_MAX_TOTAL_BYTES'
```

- [ ] **Step 2: Run the smoke script and check it fails**

Run, from the repository root with the stack up (`$env:SECRET_KEY="dev-secret"; $env:INTERNAL_API_PASSWORD="dev-internal"; docker compose up -d --build`): `bash scripts/smoke_gateway.sh`
Expected: the 11 MB check FAILS, because NGINX answers 413 itself and the body has no `IMPORT_MAX_TOTAL_BYTES`.

- [ ] **Step 3: Implement**

In `gateway/nginx.conf.template`, directly **above** the test-management regex location, add:

```nginx
        # Gherkin import (ADR-023): a whole features/ folder in one request. Its own body cap,
        # GATEWAY_IMPORT_MAX_BODY, must stay above test-management's IMPORT_MAX_TOTAL_BYTES plus
        # JSON escaping; every other route keeps the 10m above
        location ~ ^/api/v1/projects/[0-9]+/cases/import$ {
            client_max_body_size ${GATEWAY_IMPORT_MAX_BODY};
            limit_req zone=api burst=40 nodelay;
            set $upstream http://test-management-service:8000;
            proxy_pass $upstream;
        }
```

NGINX picks the first matching regex location, so this one must come before the general
`(cases|case-labels|suites)` regex.

In `gateway/entrypoint.sh`:

```sh
: "${GATEWAY_HTTPS_PORT:=8443}"
: "${GATEWAY_IMPORT_MAX_BODY:=25m}"
export GATEWAY_HTTPS_PORT GATEWAY_IMPORT_MAX_BODY

# Substitute ONLY these variables, so NGINX's own $host, $request_uri, ... are left alone
envsubst '${GATEWAY_HTTPS_PORT} ${GATEWAY_IMPORT_MAX_BODY}' < /etc/qav/nginx.conf.template > /etc/nginx/nginx.conf
```

In `docker-compose.yml`:
- Under `gateway.environment`, add `GATEWAY_IMPORT_MAX_BODY: ${GATEWAY_IMPORT_MAX_BODY:-25m}`.
- In `x-testmgmt-env`, add:

```yaml
  IMPORT_MAX_FILES: ${IMPORT_MAX_FILES:-2000}
  IMPORT_MAX_FILE_BYTES: ${IMPORT_MAX_FILE_BYTES:-262144}
  IMPORT_MAX_TOTAL_BYTES: ${IMPORT_MAX_TOTAL_BYTES:-10485760}
```

In `.env.example`, after the gateway ports:

```
# Gherkin import limits (test-management-service). Raise them together: the gateway's body cap
# must stay above IMPORT_MAX_TOTAL_BYTES plus JSON escaping (about 2.5x is safe).
#IMPORT_MAX_FILES=2000
#IMPORT_MAX_FILE_BYTES=262144
#IMPORT_MAX_TOTAL_BYTES=10485760
#GATEWAY_IMPORT_MAX_BODY=25m
```

- [ ] **Step 4: Run the smoke script and check it passes**

Run: `docker compose up -d --build gateway test-management-service`, then `bash scripts/smoke_gateway.sh`. Also run `docker compose run --rm gateway nginx -t`.
Expected: every check PASSES and the config is valid.

- [ ] **Step 5: Commit**

```bash
git add gateway docker-compose.yml .env.example scripts/smoke_gateway.sh
git commit -m "feat(gateway): own body limit for Gherkin imports; import limits are settings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Documentation and acceptance on real files

**Files:**
- Create: `docs/architecture/adr/ADR-023-gherkin-import.md` (use `docs/architecture/adr/TEMPLATE.md`)
- Modify: `docs/architecture/adr/INDEX.md`, `docs/superpowers/specs/2026-10-06-test-management-design.md:72`, `IMPLEMENTATION_PLAN.md:59`, `TODO.md:296`
- Modify: `platforms/test-management-service/README.md`

- [ ] **Step 1: Write ADR-023**, "Gherkin import: the repository owns imported cases". Its sections:
  - **Context:** the `.feature` files live in the product test repositories; the Cucumber JSON identity of a result.
  - **Decision:**
    - field ownership;
    - `source_key`;
    - moves matched on the Gherkin text;
    - reactivation;
    - `plan_hash`;
    - one transaction, with archiving scoped to uploaded paths unless `full`;
    - `test_key` in `qav_shared`;
    - a separate gateway body limit.
  - **Consequences:**
    - the link only matches Cucumber JSON results whose `uri` equals the imported path;
    - a mass-archive guard is due with the CLI command.

  Add its row to `INDEX.md`, in the format of the ADR-022 row.

- [ ] **Step 2: Update the docs.**
  - In the first slice's spec, delete "Import from Gherkin or JUnit." from "Out of scope", and add "JUnit import" in its place.
  - In `IMPLEMENTATION_PLAN.md:59`, change "Next slices: versioning, Gherkin import, dynamic suites, ticket links" to "Gherkin import done (ADR-023). Next slices: `qav-collector import-features`, versioning, dynamic suites, ticket links".
  - In `TODO.md`:
    - mark the Gherkin import item `[x]`, with "(Gherkin done 2026-10-06, ADR-023; JUnit still open)";
    - add `- [ ] qav-collector import-features: CI keeps cases in sync; API-key access to test-management; refuse a full import that would archive over half the imported cases without --allow-mass-archive *(suggested)*`.
  - In the service README, add rows for `POST /cases/import?dry_run=` and `GET /cases?origin=`, and a "Limits" paragraph naming the four variables with a `curl` example:

```
curl -k -X POST "https://localhost:8443/api/v1/projects/1/cases/import?dry_run=true" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"files":[{"path":"tests/features/a.feature","content":"Feature: A\n  Scenario: s\n    Given x\n"}]}'
```

- [ ] **Step 3: Commit**

```bash
git add docs IMPLEMENTATION_PLAN.md TODO.md platforms/test-management-service/README.md
git commit -m "docs: ADR-023 Gherkin import; plan, TODO and README updated

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Acceptance on real files (manual, nothing committed)**

With the stack up and a logged-in token, write a throwaway script in the scratchpad. It should:
1. read every `*.feature` under `tests/features` of a real Cucumber test repository;
2. post them to `cases/import?dry_run=true` for a test project, with paths prefixed `tests/features/...`, relative to the repository root.

Expect:
- `errors == []` and about 1 042 scenarios (summary `created` plus `skipped`);
- for a project with results uploaded from that repository's `cucumber-report.json`, at least a sample of the computed keys shows up in `GET /projects/{id}/tests`.

Report the numbers to the user. Do not copy the company's files into this repository.

- [ ] **Step 5: Full verification before push** (project rule: every suite green before every push)

Run:
- every Python service suite;
- `shared/tests`;
- the collector tests;
- `npx vitest run` and `npx tsc --noEmit` in `dashboard/`;
- `bash scripts/smoke_gateway.sh`.

Push to `master` only when all are green, as `carneiru`.
