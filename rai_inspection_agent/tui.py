import argparse

from rai.frontend.cli import shutdown_tool_connectors
from rai.frontend.tui import run_memory_tui

from rai_inspection_agent.cli import create_session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RAI Inspection Agent TUI")
    parser.add_argument(
        "--user",
        default="default",
        help="Initial long-term memory user.",
    )
    parser.add_argument(
        "--thread-id",
        default=None,
        help="Conversation thread/session id. Defaults to a new session.",
    )
    parser.add_argument(
        "--namespace",
        default=None,
        help="Memory namespace. Defaults to config.toml [memory].namespace.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    session, memory_mgr, robot_tools = create_session(
        user=args.user,
        thread_id=args.thread_id,
        namespace=args.namespace,
    )
    try:
        run_memory_tui(session)
    finally:
        shutdown_tool_connectors(robot_tools)
        memory_mgr.stop()


if __name__ == "__main__":
    main()
