from pathlib import Path

from rai_inspection_agent.cli import build_parser
from rai_inspection_agent.tui import build_parser as build_tui_parser


def test_cli_parser_accepts_session_user_namespace_and_history():
    args = build_parser().parse_args(
        [
            "--user",
            "operator",
            "--thread-id",
            "session-1",
            "--namespace",
            "inspection",
            "--history",
            "/tmp/history",
        ]
    )

    assert args.user == "operator"
    assert args.thread_id == "session-1"
    assert args.namespace == "inspection"
    assert Path(args.history) == Path("/tmp/history")


def test_tui_parser_accepts_session_user_and_namespace():
    args = build_tui_parser().parse_args(
        [
            "--user",
            "operator",
            "--thread-id",
            "session-1",
            "--namespace",
            "inspection",
        ]
    )

    assert args.user == "operator"
    assert args.thread_id == "session-1"
    assert args.namespace == "inspection"
