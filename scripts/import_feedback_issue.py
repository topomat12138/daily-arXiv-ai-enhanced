#!/usr/bin/env python3
"""Validate a feedback-sync Issue and merge new events into a JSONL ledger."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


SYNC_MARKER = "<!-- daily-arxiv-feedback-sync:v1 -->"
TITLE_PREFIX = "[feedback-sync]"
SCHEMA_VERSION = 1
MAX_BATCH_EVENTS = 20
EVENT_FIELDS = {"paper_id", "label", "source_date", "updated_at"}
PAYLOAD_FIELDS = {"schema_version", "batch_id", "generated_at", "events"}
EVENT_ID_RE = re.compile(r"^[0-9a-f]{64}$")
BATCH_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_UTC_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
JS_UTC_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)
JSON_FENCE_RE = re.compile(r"```json[ \t]*\r?\n(.*?)\r?\n```", re.DOTALL)


class FeedbackImportError(ValueError):
    """A sanitized validation error suitable for an Issue comment."""


def utc_timestamp() -> str:
    """Return a JavaScript-compatible UTC timestamp."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def feedback_event_id(record: dict[str, Any]) -> str:
    """Return the deterministic ID for the four feedback semantics fields."""
    label = "null" if record["label"] is None else record["label"]
    canonical = "\n".join(
        (
            record["paper_id"],
            label,
            record["source_date"],
            record["updated_at"],
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_utc_timestamp(
    value: Any,
    field_name: str,
    *,
    javascript_compatible: bool = False,
) -> str:
    timestamp_pattern = (
        JS_UTC_TIMESTAMP_RE if javascript_compatible else ISO_UTC_TIMESTAMP_RE
    )
    if not isinstance(value, str) or not timestamp_pattern.fullmatch(value):
        raise FeedbackImportError(f"{field_name} must be an ISO-8601 UTC timestamp")
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise FeedbackImportError(
            f"{field_name} must be an ISO-8601 UTC timestamp"
        ) from error
    return value


def _validate_source_date(value: Any, event_index: int) -> str:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise FeedbackImportError(
            f"events[{event_index}].source_date must use YYYY-MM-DD"
        )
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise FeedbackImportError(
            f"events[{event_index}].source_date must be a real calendar date"
        ) from error
    return value


def _validate_paper_id(value: Any, event_index: int) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise FeedbackImportError(
            f"events[{event_index}].paper_id must be a non-empty bounded string"
        )
    if value != value.strip() or not value.isprintable():
        raise FeedbackImportError(
            f"events[{event_index}].paper_id contains unsafe characters"
        )
    return value


def validate_feedback_event(
    event: Any,
    event_index: int,
    *,
    allow_extra_fields: bool = False,
) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise FeedbackImportError(f"events[{event_index}] must be an object")
    fields = set(event)
    if not EVENT_FIELDS.issubset(fields) or (not allow_extra_fields and fields != EVENT_FIELDS):
        raise FeedbackImportError(
            f"events[{event_index}] must contain only the four feedback fields"
        )

    label = event["label"]
    if not (label is None or label == "focus" or label == "interested"):
        raise FeedbackImportError(
            f"events[{event_index}].label must be focus, interested, or null"
        )

    return {
        "paper_id": _validate_paper_id(event["paper_id"], event_index),
        "label": label,
        "source_date": _validate_source_date(event["source_date"], event_index),
        "updated_at": _validate_utc_timestamp(
            event["updated_at"],
            f"events[{event_index}].updated_at",
            javascript_compatible=True,
        ),
    }


def validate_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != PAYLOAD_FIELDS:
        raise FeedbackImportError("payload must contain the expected schema fields")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise FeedbackImportError("schema_version must be 1")

    batch_id = payload["batch_id"]
    if not isinstance(batch_id, str) or not BATCH_ID_RE.fullmatch(batch_id):
        raise FeedbackImportError("batch_id contains unsupported characters or length")

    generated_at = _validate_utc_timestamp(payload["generated_at"], "generated_at")
    events = payload["events"]
    if not isinstance(events, list) or not events:
        raise FeedbackImportError("events must be a non-empty list")
    if len(events) > MAX_BATCH_EVENTS:
        raise FeedbackImportError(f"events must contain at most {MAX_BATCH_EVENTS} items")

    validated_events = [
        validate_feedback_event(event, index) for index, event in enumerate(events)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "batch_id": batch_id,
        "generated_at": generated_at,
        "events": validated_events,
    }


def extract_payload(issue_body: Any) -> dict[str, Any]:
    if not isinstance(issue_body, str):
        raise FeedbackImportError("Issue body is missing")
    if issue_body.count(SYNC_MARKER) != 1:
        raise FeedbackImportError("Issue body must contain exactly one feedback-sync marker")

    body_after_marker = issue_body.split(SYNC_MARKER, 1)[1]
    match = JSON_FENCE_RE.search(body_after_marker)
    if not match:
        raise FeedbackImportError("Issue body must contain a fenced JSON payload after the marker")
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as error:
        raise FeedbackImportError("Issue payload is not valid JSON") from error
    return validate_payload(payload)


def validate_github_event(event: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(event, dict):
        raise FeedbackImportError("GitHub event must be an object")
    issue = event.get("issue")
    repository = event.get("repository")
    if not isinstance(issue, dict) or not isinstance(repository, dict):
        raise FeedbackImportError("GitHub event is missing Issue metadata")

    title = issue.get("title")
    if not isinstance(title, str) or not title.startswith(TITLE_PREFIX):
        raise FeedbackImportError("Issue title does not identify a feedback sync")

    owner = repository.get("owner")
    author = issue.get("user")
    owner_login = owner.get("login") if isinstance(owner, dict) else None
    author_login = author.get("login") if isinstance(author, dict) else None
    if not owner_login or author_login != owner_login:
        raise FeedbackImportError("Issue author is not the repository owner")

    issue_number = issue.get("number")
    if not isinstance(issue_number, int) or isinstance(issue_number, bool) or issue_number <= 0:
        raise FeedbackImportError("Issue number is invalid")

    payload = extract_payload(issue.get("body"))
    issue_metadata = {
        "issue_number": issue_number,
        "issue_author": author_login,
    }
    return payload, issue_metadata


def read_ledger(ledger_path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    if not ledger_path.exists():
        return [], set()

    rows: list[dict[str, Any]] = []
    event_ids: set[str] = set()
    with ledger_path.open("r", encoding="utf-8") as ledger_file:
        for line_number, raw_line in enumerate(ledger_file, start=1):
            if not raw_line.strip():
                continue
            try:
                row = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise FeedbackImportError(
                    f"Existing ledger line {line_number} is not valid JSON"
                ) from error
            try:
                core = validate_feedback_event(
                    row, line_number - 1, allow_extra_fields=True
                )
            except FeedbackImportError as error:
                raise FeedbackImportError(
                    f"Existing ledger line {line_number} is invalid"
                ) from error

            computed_id = feedback_event_id(core)
            stored_id = row.get("event_id")
            if stored_id is not None and (
                not isinstance(stored_id, str)
                or not EVENT_ID_RE.fullmatch(stored_id)
                or stored_id != computed_id
            ):
                raise FeedbackImportError(
                    f"Existing ledger line {line_number} has an invalid event_id"
                )

            normalized_row = dict(row)
            normalized_row["event_id"] = computed_id
            rows.append(normalized_row)
            event_ids.add(computed_id)

    return rows, event_ids


def _write_ledger_atomically(ledger_path: Path, rows: list[dict[str, Any]]) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=ledger_path.parent,
            prefix=f".{ledger_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = temporary_file.name
            for row in rows:
                temporary_file.write(
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
                )
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, ledger_path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def import_feedback_event(
    github_event: Any,
    ledger_path: Path,
    *,
    imported_at: str | None = None,
) -> dict[str, Any]:
    """Validate one GitHub event and atomically merge its feedback batch."""
    payload, issue_metadata = validate_github_event(github_event)
    import_timestamp = _validate_utc_timestamp(
        imported_at or utc_timestamp(), "imported_at", javascript_compatible=True
    )
    existing_rows, existing_ids = read_ledger(ledger_path)

    new_rows: list[dict[str, Any]] = []
    duplicates = 0
    seen_ids = set(existing_ids)
    for event in payload["events"]:
        event_id = feedback_event_id(event)
        if event_id in seen_ids:
            duplicates += 1
            continue
        seen_ids.add(event_id)
        new_rows.append(
            {
                "event_id": event_id,
                **event,
                "imported_at": import_timestamp,
                "batch_id": payload["batch_id"],
                "issue_number": issue_metadata["issue_number"],
                "issue_author": issue_metadata["issue_author"],
            }
        )

    if new_rows:
        _write_ledger_atomically(ledger_path, existing_rows + new_rows)

    return {
        "status": "success",
        "batch_id": payload["batch_id"],
        "new_events": len(new_rows),
        "duplicates_ignored": duplicates,
        "ledger_events": len(existing_rows) + len(new_rows),
    }


def load_github_event(event_path: Path) -> Any:
    try:
        with event_path.open("r", encoding="utf-8") as event_file:
            return json.load(event_file)
    except (OSError, json.JSONDecodeError) as error:
        raise FeedbackImportError("GitHub event file could not be read") from error


def _write_result(result_path: Path | None, result: dict[str, Any]) -> None:
    if result_path is None:
        return
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_github_output(output_path: Path | None, result: dict[str, Any]) -> None:
    if output_path is None:
        return
    keys = ("status", "batch_id", "new_events", "duplicates_ignored", "ledger_events", "error")
    with output_path.open("a", encoding="utf-8") as output_file:
        for key in keys:
            value = result.get(key, "")
            output_file.write(f"{key}={value}\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--event-path",
        type=Path,
        default=Path(os.environ["GITHUB_EVENT_PATH"])
        if os.environ.get("GITHUB_EVENT_PATH")
        else None,
    )
    parser.add_argument("--ledger", type=Path, default=Path("feedback/events.jsonl"))
    parser.add_argument("--result-file", type=Path)
    parser.add_argument("--github-output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.event_path is None:
        result = {"status": "invalid", "error": "GitHub event path is missing"}
        _write_result(args.result_file, result)
        _write_github_output(args.github_output, result)
        return 2

    try:
        github_event = load_github_event(args.event_path)
        result = import_feedback_event(github_event, args.ledger)
    except FeedbackImportError as error:
        result = {"status": "invalid", "error": str(error)}
        _write_result(args.result_file, result)
        _write_github_output(args.github_output, result)
        print(f"Feedback import rejected: {error}", file=sys.stderr)
        return 2
    except Exception:
        result = {"status": "error", "error": "Unexpected importer failure"}
        _write_result(args.result_file, result)
        _write_github_output(args.github_output, result)
        print("Feedback import failed unexpectedly", file=sys.stderr)
        return 1

    _write_result(args.result_file, result)
    _write_github_output(args.github_output, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
