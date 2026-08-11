import json
import tempfile
import unittest
from pathlib import Path

from scripts.import_feedback_issue import (
    FeedbackImportError,
    MAX_BATCH_EVENTS,
    SYNC_MARKER,
    feedback_event_id,
    import_feedback_event,
)


KNOWN_EVENT_ID = "c90b6ceeb29ae15d126b22310819cc59e9ae9787e966e91b00c85eda7adecb0c"
IMPORTED_AT = "2026-08-11T22:30:00.000Z"


def feedback_event(**overrides):
    event = {
        "paper_id": "2607.08845",
        "label": "focus",
        "source_date": "2026-07-13",
        "updated_at": "2026-07-13T18:25:00.000Z",
    }
    event.update(overrides)
    return event


def payload(events=None, **overrides):
    value = {
        "schema_version": 1,
        "batch_id": "batch-1",
        "generated_at": "2026-08-11T22:30:00.000Z",
        "events": [feedback_event()] if events is None else events,
    }
    value.update(overrides)
    return value


def issue_body(payload_value):
    return f"{SYNC_MARKER}\n\n```json\n{json.dumps(payload_value)}\n```"


def github_event(payload_value=None, **overrides):
    event = {
        "issue": {
            "number": 123,
            "title": "[feedback-sync] batch-1",
            "body": issue_body(payload() if payload_value is None else payload_value),
            "user": {"login": "topomat12138"},
        },
        "repository": {"owner": {"login": "topomat12138"}},
    }
    for dotted_key, value in overrides.items():
        section, key = dotted_key.split("__", 1)
        event[section][key] = value
    return event


def read_ledger(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class FeedbackImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.ledger_path = Path(self.temporary_directory.name) / "feedback" / "events.jsonl"

    def import_event(self, event):
        return import_feedback_event(event, self.ledger_path, imported_at=IMPORTED_AT)

    def assert_rejected(self, event):
        with self.assertRaises(FeedbackImportError):
            self.import_event(event)
        self.assertEqual(read_ledger(self.ledger_path), [])

    def test_valid_focus_event(self):
        result = self.import_event(github_event(payload([feedback_event(label="focus")])))
        rows = read_ledger(self.ledger_path)
        self.assertEqual(result["new_events"], 1)
        self.assertEqual(rows[0]["label"], "focus")
        self.assertEqual(rows[0]["issue_number"], 123)
        self.assertEqual(rows[0]["issue_author"], "topomat12138")

    def test_valid_interested_event(self):
        self.import_event(github_event(payload([feedback_event(label="interested")])))
        self.assertEqual(read_ledger(self.ledger_path)[0]["label"], "interested")

    def test_valid_cancellation_event(self):
        self.import_event(github_event(payload([feedback_event(label=None)])))
        self.assertIsNone(read_ledger(self.ledger_path)[0]["label"])

    def test_multi_event_batch(self):
        events = [
            feedback_event(),
            feedback_event(
                paper_id="2607.09437",
                label="interested",
                updated_at="2026-07-14T01:10:00.000Z",
            ),
        ]
        result = self.import_event(github_event(payload(events)))
        self.assertEqual(result["new_events"], 2)
        self.assertEqual(len(read_ledger(self.ledger_path)), 2)

    def test_invalid_label_rejected(self):
        self.assert_rejected(github_event(payload([feedback_event(label="dislike")])))

    def test_invalid_source_date_rejected(self):
        self.assert_rejected(
            github_event(payload([feedback_event(source_date="2026-02-30")]))
        )

    def test_invalid_updated_at_rejected(self):
        self.assert_rejected(
            github_event(payload([feedback_event(updated_at="2026-07-13 18:25:00")]))
        )

    def test_missing_marker_rejected(self):
        event = github_event()
        event["issue"]["body"] = "```json\n{}\n```"
        self.assert_rejected(event)

    def test_malformed_json_rejected(self):
        event = github_event()
        event["issue"]["body"] = f"{SYNC_MARKER}\n\n```json\n{{bad json\n```"
        self.assert_rejected(event)

    def test_wrong_schema_version_rejected(self):
        self.assert_rejected(github_event(payload(schema_version=2)))

    def test_empty_events_rejected(self):
        self.assert_rejected(github_event(payload([])))

    def test_more_than_twenty_events_rejected(self):
        events = [
            feedback_event(
                paper_id=f"paper-{index}",
                updated_at=f"2026-07-13T18:25:{index:02d}.000Z",
            )
            for index in range(MAX_BATCH_EVENTS + 1)
        ]
        self.assert_rejected(github_event(payload(events)))

    def test_unauthorized_issue_author_rejected(self):
        self.assert_rejected(
            github_event(issue__user={"login": "public-contributor"})
        )

    def test_event_id_matches_javascript_known_vector(self):
        self.assertEqual(feedback_event_id(feedback_event()), KNOWN_EVENT_ID)

    def test_duplicate_event_is_ignored(self):
        event = github_event()
        first = self.import_event(event)
        second = self.import_event(event)
        self.assertEqual(first["new_events"], 1)
        self.assertEqual(second["new_events"], 0)
        self.assertEqual(second["duplicates_ignored"], 1)
        self.assertEqual(len(read_ledger(self.ledger_path)), 1)

    def test_mixed_new_and_duplicate_appends_only_new(self):
        duplicate = feedback_event()
        self.import_event(github_event(payload([duplicate])))
        new_event = feedback_event(
            paper_id="2607.09437",
            label=None,
            updated_at="2026-07-14T01:10:00.000Z",
        )
        result = self.import_event(github_event(payload([duplicate, new_event])))
        self.assertEqual(result["new_events"], 1)
        self.assertEqual(result["duplicates_ignored"], 1)
        self.assertEqual(len(read_ledger(self.ledger_path)), 2)

    def test_processing_same_batch_twice_does_not_duplicate_rows(self):
        events = [
            feedback_event(),
            feedback_event(
                paper_id="2607.09437",
                updated_at="2026-07-14T01:10:00.000Z",
            ),
        ]
        event = github_event(payload(events))
        self.import_event(event)
        result = self.import_event(event)
        self.assertEqual(result["new_events"], 0)
        self.assertEqual(result["duplicates_ignored"], 2)
        self.assertEqual(len(read_ledger(self.ledger_path)), 2)

    def test_malformed_batch_causes_zero_partial_writes(self):
        valid = feedback_event()
        invalid = feedback_event(
            paper_id="2607.09437",
            label="invalid",
            updated_at="2026-07-14T01:10:00.000Z",
        )
        self.assert_rejected(github_event(payload([valid, invalid])))

    def test_legacy_row_without_event_id_is_used_for_deduplication(self):
        self.ledger_path.parent.mkdir(parents=True)
        self.ledger_path.write_text(
            json.dumps(feedback_event()) + "\n", encoding="utf-8"
        )
        result = self.import_event(github_event())
        self.assertEqual(result["new_events"], 0)
        self.assertEqual(result["duplicates_ignored"], 1)
        self.assertEqual(len(read_ledger(self.ledger_path)), 1)

    def test_legacy_rows_receive_ids_when_a_new_event_is_appended(self):
        self.ledger_path.parent.mkdir(parents=True)
        self.ledger_path.write_text(
            json.dumps(feedback_event()) + "\n", encoding="utf-8"
        )
        new_event = feedback_event(
            paper_id="2607.09437",
            updated_at="2026-07-14T01:10:00.000Z",
        )
        self.import_event(github_event(payload([new_event])))
        rows = read_ledger(self.ledger_path)
        self.assertEqual(rows[0]["event_id"], KNOWN_EVENT_ID)
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
