"""Re-mask stored results with the masking ingest applies today.

    python -m src.ingestion.jobs.remask [--dry-run] [--project ID] [--batch-size N]

For results stored before masking existed, or before a pattern was added. Message, details, the failed step, the
log and the step text of screenshots are re-masked; a log that changes has its log values read again. Masking skips what is
already masked, so a second pass changes nothing and the command is safe to repeat. Rows are
walked by id in batches, each committed on its own, so a long pass never holds one huge
transaction and can be stopped and run again.
"""
import argparse
import json
import sys
from collections import Counter
from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session, sessionmaker, undefer

from src.ingestion.core.config import settings
from src.ingestion.models import ResultScreenshot, Run, RunResult
from src.ingestion.models.run import FAILED_STEP_DEFINITION_LENGTH, FAILED_STEP_PATTERN_LENGTH, FAILED_STEP_TEXT_LENGTH
from src.ingestion.service import log_pattern_service, log_value_service, masking_pattern_service
from src.ingestion.service.ingest_service import CI_RUN_URL_LENGTH, COMMIT_MESSAGE_LENGTH, mask, truncate_utf8

SCREENSHOT_STEP_TEXT_LENGTH = 1000  # result_screenshots.step_text


class _ProjectPatterns:
    """Each project's patterns (masking, or log-value with `load=log_pattern_service.compiled_for`), loaded once
    per pass."""

    def __init__(self, db: Session, load=masking_pattern_service.compiled_for):
        self.db, self.load, self.cache = db, load, {}

    def __call__(self, project_id: int) -> tuple:
        if project_id not in self.cache:
            self.cache[project_id] = tuple(self.load(self.db, project_id))
        return self.cache[project_id]


def _remask_text(text: Optional[str], patterns: tuple, kinds: Counter) -> tuple[Optional[str], bool, bool]:
    """(new text, changed, cut). Masking can lengthen text past the stored limit: cut it back."""
    masked, found = mask(text, patterns)
    if not found:
        return text, False, False
    kinds.update(found)
    masked, cut = truncate_utf8(masked, settings.MAX_TEXT_BYTES)
    return masked, True, cut


def _results_pass(
    db: Session, project_id: Optional[int], batch_size: int, dry_run: bool, kinds: Counter,
    patterns_for: _ProjectPatterns, log_patterns_for: _ProjectPatterns,
) -> tuple[int, int]:
    scanned = changed = 0
    last_id = 0
    while True:
        query = (
            db.query(RunResult, Run.project_id)
            .join(Run, Run.id == RunResult.run_id)
            .options(undefer(RunResult.log))
            .filter(RunResult.id > last_id)
        )
        if project_id is not None:
            query = query.filter(Run.project_id == project_id)
        batch = query.order_by(RunResult.id).limit(batch_size).all()
        if not batch:
            return scanned, changed
        relogged: dict = {}
        shots: dict = {}
        for shot in db.query(ResultScreenshot).filter(ResultScreenshot.result_id.in_([r.id for r, _ in batch])):
            shots.setdefault(shot.result_id, []).append(shot)
        for row, row_project in batch:
            scanned += 1
            patterns = patterns_for(row_project)
            row_kinds: Counter = Counter()
            message, message_changed, message_cut = _remask_text(row.message, patterns, row_kinds)
            details, details_changed, details_cut = _remask_text(row.details, patterns, row_kinds)
            step, step_changed, step_cut = _remask_text(row.failed_step_text, patterns, row_kinds)
            definition, definition_changed, definition_cut = _remask_text(row.failed_step_definition, patterns, row_kinds)
            pattern, pattern_changed, pattern_cut = _remask_text(row.failed_step_pattern, patterns, row_kinds)
            log, log_changed, _ = _remask_text(row.log, patterns, row_kinds)
            # A screenshot's step text is shown like the failed step's (ADR-036)
            shots_changed = False
            for shot in shots.get(row.id, ()):
                text, text_changed, _ = _remask_text(shot.step_text, patterns, row_kinds)
                if text_changed:
                    shots_changed = True
                    if not dry_run:
                        shot.step_text = text[:SCREENSHOT_STEP_TEXT_LENGTH]
            shown_changed = (message_changed or details_changed or step_changed or definition_changed or pattern_changed
                             or shots_changed)
            if not (shown_changed or log_changed):
                continue
            changed += 1
            # A result counts once per kind, the way ingest's metrics count it
            kinds.update({kind: 1 for kind in row_kinds})
            if not dry_run:
                row.message, row.details = message, details
                row.failed_step_text = step[:FAILED_STEP_TEXT_LENGTH] if step is not None else None
                row.failed_step_definition = (definition[:FAILED_STEP_DEFINITION_LENGTH]
                                              if definition is not None else None)
                row.failed_step_pattern = pattern[:FAILED_STEP_PATTERN_LENGTH] if pattern is not None else None
                # `redacted` and `truncated` stay about the text the run page shows
                row.redacted = row.redacted or shown_changed
                row.truncated = (row.truncated or message_cut or details_cut or step_cut
                                 or definition_cut or pattern_cut)
                if log_changed:
                    row.log = log
                    relogged.setdefault(row_project, []).append((row.id, log))
        # A log that masking changed has its values read again: a value now hidden is no longer captured (ADR-032)
        for row_project, items in relogged.items():
            log_value_service.replace_values(db, items, log_patterns_for(row_project))
        last_id = batch[-1][0].id
        if dry_run:
            db.rollback()
        else:
            db.commit()


def _runs_pass(
    db: Session, project_id: Optional[int], dry_run: bool, kinds: Counter, patterns_for: _ProjectPatterns
) -> int:
    query = db.query(Run).filter(or_(Run.ci_run_url.isnot(None), Run.commit_message.isnot(None)))
    if project_id is not None:
        query = query.filter(Run.project_id == project_id)
    changed = 0
    for run in query.all():
        patterns = patterns_for(run.project_id)
        url, url_found = mask(run.ci_run_url, patterns)
        subject, subject_found = mask(run.commit_message, patterns)
        found = url_found | subject_found
        if not found:
            continue
        changed += 1
        kinds.update({kind: 1 for kind in found})
        if not dry_run:
            if url_found:
                run.ci_run_url = url[:CI_RUN_URL_LENGTH]
            if subject_found:
                run.commit_message = subject[:COMMIT_MESSAGE_LENGTH]
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return changed


def run_pass(db: Session, *, project_id: Optional[int], batch_size: int, dry_run: bool) -> dict:
    kinds: Counter = Counter()
    patterns_for = _ProjectPatterns(db)
    log_patterns_for = _ProjectPatterns(db, log_pattern_service.compiled_for)
    scanned, results_changed = _results_pass(db, project_id, batch_size, dry_run, kinds, patterns_for, log_patterns_for)
    runs_changed = _runs_pass(db, project_id, dry_run, kinds, patterns_for)
    return {
        "event": "remask",
        "project_id": project_id,
        "results_scanned": scanned,
        "results_changed": results_changed,
        "runs_changed": runs_changed,
        "kinds": dict(sorted(kinds.items())),
        "dry_run": dry_run,
    }


def main(argv: Optional[List[str]] = None, *, session_factory: Optional[sessionmaker] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.ingestion.jobs.remask",
        description="Re-apply today's masking to results already stored. Safe to repeat.",
    )
    parser.add_argument("--dry-run", action="store_true", help="report what would change; change nothing")
    parser.add_argument("--project", type=int, metavar="ID", help="only this project's results")
    parser.add_argument("--batch-size", type=int, default=500, metavar="N", help="rows per transaction (default 500)")
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1")

    if session_factory is None:
        from src.ingestion.db.session import SessionLocal

        session_factory = SessionLocal
    try:
        with session_factory() as db:
            summary = run_pass(db, project_id=args.project, batch_size=args.batch_size, dry_run=args.dry_run)
    except Exception as exc:  # report and fail; everything committed so far stays masked
        print(json.dumps({"event": "remask_failed", "error": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        return 1
    print(json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
