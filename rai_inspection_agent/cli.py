import argparse
from pathlib import Path

from rai.frontend.cli import (
    CliRenderer,
    MemoryCliSession,
    run_memory_cli,
    shutdown_tool_connectors,
)
from rai.memory import load_memory_config
from rai_whoami import load_whoami_config

from rai_inspection_agent.runtime import (
    EMBODIMENT_PATH,
    build_inspection_agent,
    create_inspection_tools,
    initialize_inspection_memory_mgr,
    welcome_message,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RAI Inspection Agent CLI")
    parser.add_argument("--user", default="default", help="Initial long-term memory user.")
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
    parser.add_argument(
        "--history",
        default=str(Path.home() / ".rai_inspection_agent" / "cli_history"),
        help="Prompt history file used by prompt_toolkit.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    memory_config = load_memory_config()
    namespace = args.namespace or memory_config.namespace
    robot_docs_config = load_whoami_config()

    memory_mgr = initialize_inspection_memory_mgr()
    robot_tools = create_inspection_tools()

    def graph_factory(user_id: str):
        return build_inspection_agent(
            memory_mgr,
            EMBODIMENT_PATH,
            user_id=user_id,
            namespace=namespace,
            robot_docs_config=robot_docs_config,
            robot_tools=robot_tools,
        )

    graph = graph_factory(args.user)
    session_kwargs = {}
    if args.thread_id:
        session_kwargs["thread_id"] = args.thread_id
    session = MemoryCliSession(
        memory_mgr=memory_mgr,
        graph=graph,
        namespace=namespace,
        user_id=args.user,
        graph_factory=graph_factory,
        welcome_message_factory=welcome_message,
        **session_kwargs,
    )

    try:
        run_memory_cli(
            session,
            renderer=CliRenderer(),
            history_path=args.history,
        )
    finally:
        shutdown_tool_connectors(robot_tools)
        memory_mgr.stop()


if __name__ == "__main__":
    main()
