"""Tests for history_import.claude_code: Claude Code session .jsonl -> Envelope v1."""

from __future__ import annotations

import json
from pathlib import Path

from tinyagentos.history_import.claude_code import (
    iter_records,
    manifest,
    to_envelopes,
    to_index_lines,
)

FIXTURE = (
    Path(__file__).parent / "fixtures" / "history_import" / "claude_code_session.jsonl"
)


def _redact(text: str) -> str:
    """Test redactor: masks 'SECRET' so tests can prove redact ran on text fields."""
    return text.replace("SECRET", "[REDACTED]")


def _is_secret_file_read(path: str) -> bool:
    """Test predicate: paths ending in .cred are secret files."""
    return path.endswith(".cred")


class TestIterRecords:
    def test_yields_eight_records_from_nine_line_fixture(self):
        records = list(iter_records(FIXTURE))
        assert len(records) == 8

    def test_skipped_line_not_present(self):
        records = list(iter_records(FIXTURE))
        for r in records:
            assert isinstance(r, dict)
            assert isinstance(r.get("type"), str)

    def test_first_record_is_user_text(self):
        records = list(iter_records(FIXTURE))
        first = records[0]
        assert first["type"] == "user"
        assert first["session_id"] == "sess-1"
        assert first["uuid"] == "rec-u1"
        assert first["timestamp"] == "2026-10-10T10:00:00.000Z"


class TestToEnvelopes:
    def _envelopes(self, **kw):
        records = list(iter_records(FIXTURE))
        defaults = {
            "agent_name": "claude-code",
            "redact": _redact,
            "is_secret_file_read": _is_secret_file_read,
        }
        defaults.update(kw)
        return to_envelopes(records, **defaults)

    def test_kind_sequence(self):
        env = self._envelopes()
        kinds = [e["kind"] for e in env]
        assert kinds == [
            "message_in",  # rec-u1: user text (list)
            "message_out",  # rec-a1: assistant text (thinking dropped, image replaced)
            "tool_call",  # rec-a2: Bash
            "tool_result",  # rec-u2: Bash result
            "tool_call",  # rec-a3: Read
            "tool_result",  # rec-u3: Read result (secret)
            "message_in",  # rec-u9: user text (string)
        ]

    def test_envelope_top_level_fields(self):
        env = self._envelopes()
        e = env[0]
        assert e["v"] == 1
        assert e["kind"] == "message_in"
        assert e["trace_id"] == "sess-1"
        assert e["id"] == "rec-u1"
        assert e["agent_name"] == "claude-code"
        assert e["payload"]["from"] == "user"
        assert "text" in e["payload"]

    def test_created_at_is_epoch_float(self):
        env = self._envelopes()
        e = env[0]
        assert isinstance(e["created_at"], float)
        assert e["created_at"] == 1791626400.0

    def test_redact_applied_to_message_text(self):
        env = self._envelopes()
        msg_in = env[0]
        assert "SECRET" not in msg_in["payload"]["text"]
        assert "[REDACTED]" in msg_in["payload"]["text"]
        msg_out = env[1]
        assert "SECRET" not in msg_out["payload"]["content"]
        assert "[REDACTED]" in msg_out["payload"]["content"]

    def test_thinking_block_dropped(self):
        env = self._envelopes()
        blob = json.dumps(env)
        assert "internal reasoning" not in blob

    def test_image_replaced_with_placeholder(self):
        env = self._envelopes()
        msg_out = env[1]
        assert "content_blocks" in msg_out["payload"]
        blocks = msg_out["payload"]["content_blocks"]
        assert blocks == [{"text": "[image omitted]"}]

    def test_tool_call_id_is_tool_use_id(self):
        env = self._envelopes()
        calls = [e for e in env if e["kind"] == "tool_call"]
        assert calls[0]["id"] == "tu-bash"
        assert calls[1]["id"] == "tu-read"

    def test_tool_call_payload(self):
        env = self._envelopes()
        tc = env[2]
        assert tc["payload"]["tool"] == "Bash"
        assert tc["payload"]["args"] == {"command": "ls -la /tmp"}
        assert tc["payload"]["caller"] == "claude-code"

    def test_tool_result_parent_id_links_to_tool_call(self):
        env = self._envelopes()
        bash_result = env[3]
        assert bash_result["kind"] == "tool_result"
        assert bash_result["parent_id"] == "tu-bash"
        assert bash_result["id"] == "rec-u2"
        read_result = env[5]
        assert read_result["parent_id"] == "tu-read"
        assert read_result["id"] == "rec-u3"

    def test_tool_result_success_flag(self):
        env = self._envelopes()
        bash_result = env[3]
        assert bash_result["payload"]["success"] is True
        read_result = env[5]
        assert read_result["payload"]["success"] is True

    def test_secret_file_read_result_omitted(self):
        env = self._envelopes()
        read_result = env[5]
        assert read_result["payload"]["result"] == "[secret file read omitted]"
        assert "KEY=SUPERSECRET" not in read_result["payload"]["result"]

    def test_non_secret_tool_result_has_redacted_text(self):
        env = self._envelopes()
        bash_result = env[3]
        assert bash_result["payload"]["result"] == "[REDACTED] token in output\na.txt"
        assert bash_result["payload"]["tool"] == "Bash"

    def test_without_secret_predicate_result_is_redacted_not_omitted(self):
        env = self._envelopes(is_secret_file_read=None)
        read_result = env[5]
        assert read_result["payload"]["result"] != "[secret file read omitted]"
        assert "SUPERSECRET" not in read_result["payload"]["result"]

    def test_string_content_user_prompt_becomes_message_in(self):
        env = self._envelopes()
        msg_in = [
            e for e in env
            if e["kind"] == "message_in" and e["payload"]["text"] == "plain string prompt"
        ]
        assert len(msg_in) == 1
        assert msg_in[0]["payload"]["from"] == "user"
        assert msg_in[0]["payload"]["text"] == "plain string prompt"
        assert msg_in[0]["id"] == "rec-u9"

    def test_is_meta_user_record_skipped(self):
        env = self._envelopes()
        blob = json.dumps(env)
        assert "skill body injection" not in blob
        assert all(e["id"] != "rec-u10" for e in env)


class TestToIndexLines:
    def _lines(self):
        records = list(iter_records(FIXTURE))
        env = to_envelopes(
            records,
            agent_name="claude-code",
            redact=_redact,
            is_secret_file_read=_is_secret_file_read,
        )
        return to_index_lines(env)

    def test_five_index_lines_for_eight_envelopes(self):
        lines = self._lines()
        assert len(lines) == 5

    def test_no_tool_result_lines(self):
        lines = self._lines()
        for line in lines:
            assert "result" not in line
        blob = json.dumps(lines)
        assert "token in output" not in blob
        assert "a.txt" not in blob
        assert "SUPERSECRET" not in blob
        assert "secret file read omitted" not in blob

    def test_message_in_index_line(self):
        lines = self._lines()
        msg_in = [l for l in lines if l["role"] == "user"]
        assert len(msg_in) == 2
        assert msg_in[0]["trace_id"] == "sess-1"
        assert "[REDACTED]" in msg_in[0]["text"]
        assert "SECRET" not in msg_in[0]["text"]
        assert msg_in[1]["text"] == "plain string prompt"

    def test_message_out_index_line(self):
        lines = self._lines()
        msg_out = [l for l in lines if l["role"] == "assistant"]
        assert len(msg_out) == 1
        assert msg_out[0]["trace_id"] == "sess-1"
        assert "[REDACTED]" in msg_out[0]["text"]

    def test_tool_call_index_lines(self):
        lines = self._lines()
        tool_lines = [l for l in lines if l["role"] == "tool"]
        assert len(tool_lines) == 2
        bash_line = tool_lines[0]
        assert bash_line["ref"] == "tu-bash"
        assert "Bash" in bash_line["text"]
        assert "ls -la /tmp" in bash_line["text"]
        read_line = tool_lines[1]
        assert read_line["ref"] == "tu-read"
        assert "Read" in read_line["text"]
        assert "foo.cred" in read_line["text"]


class TestManifest:
    def test_manifest_counts(self):
        records = list(iter_records(FIXTURE))
        env = to_envelopes(
            records,
            agent_name="claude-code",
            redact=_redact,
            is_secret_file_read=_is_secret_file_read,
        )
        index_lines = to_index_lines(env)
        m = manifest(FIXTURE, env, index_lines)
        assert m["envelopes"] == 7
        assert m["index_lines"] == 5
        assert m["skipped_lines"] == 1
        assert isinstance(m["bytes_in"], int)
        assert m["bytes_in"] > 0
        assert isinstance(m["index_bytes"], int)
        assert m["index_bytes"] > 0

    def test_manifest_bytes_in_matches_file_size(self):
        records = list(iter_records(FIXTURE))
        env = to_envelopes(
            records,
            agent_name="claude-code",
            redact=_redact,
            is_secret_file_read=_is_secret_file_read,
        )
        index_lines = to_index_lines(env)
        m = manifest(FIXTURE, env, index_lines)
        assert m["bytes_in"] == FIXTURE.stat().st_size
