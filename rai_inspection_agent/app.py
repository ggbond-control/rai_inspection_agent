import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import streamlit as st
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool
from rai.frontend.memory_streamlit import (
    render_chat_messages_with_tools,
    render_memory_chat_input,
    render_memory_sidebar,
)
from rai.memory import MemoryManager, load_memory_config
from rai_whoami import load_whoami_config

from rai_inspection_agent.runtime import (
    EMBODIMENT_PATH,
    build_inspection_agent,
    create_inspection_tools,
    initialize_inspection_memory_mgr,
    welcome_message,
)


@st.cache_resource
def initialize_inspection_tools() -> list[BaseTool]:
    return create_inspection_tools()


def initialize_memory_mgr() -> MemoryManager:
    try:
        return initialize_inspection_memory_mgr()
    except Exception as e:
        st.error(str(e))
        st.stop()


def run_memory_app() -> None:
    st.set_page_config(page_title="RAI Inspection Agent", page_icon=":robot:")
    st.title(":robot: RAI Inspection Agent")
    st.sidebar.header("Configuration")

    config = load_memory_config()
    robot_docs_config = load_whoami_config()
    st.sidebar.markdown(
        f"**Backend:** `{config.backend}`\n**Namespace:** `{config.namespace}`"
    )
    if robot_docs_config.enabled:
        st.sidebar.markdown(f"**Robot Docs:** `{robot_docs_config.root_dir}`")
    st.sidebar.markdown("---")

    if "memory_mgr" not in st.session_state:
        st.session_state["memory_mgr"] = initialize_memory_mgr()
    memory_mgr = st.session_state["memory_mgr"]

    user_id = st.session_state.get("user_id", "default")
    graph_key = "graph"
    if graph_key not in st.session_state or st.session_state.get("_last_user") != user_id:
        graph = build_inspection_agent(
            memory_mgr,
            EMBODIMENT_PATH,
            user_id=user_id,
            namespace=config.namespace,
            robot_docs_config=robot_docs_config,
            robot_tools=initialize_inspection_tools(),
        )
        st.session_state[graph_key] = graph
        st.session_state["_last_user"] = user_id

    graph = st.session_state[graph_key]
    sidebar_state = render_memory_sidebar(
        memory_mgr=memory_mgr,
        graph=graph,
        namespace=config.namespace,
        welcome_message_factory=welcome_message,
    )
    if sidebar_state.user_id != user_id:
        graph = build_inspection_agent(
            memory_mgr,
            EMBODIMENT_PATH,
            user_id=sidebar_state.user_id,
            namespace=config.namespace,
            robot_docs_config=robot_docs_config,
            robot_tools=initialize_inspection_tools(),
        )
        st.session_state[graph_key] = graph
        st.session_state["_last_user"] = sidebar_state.user_id

    st.sidebar.markdown("---")
    render_chat_messages_with_tools(sidebar_state.messages)

    st.sidebar.header("Tool Calls")
    for msg in sidebar_state.messages:
        if isinstance(msg, ToolMessage):
            with st.sidebar.expander(f"Tool: {msg.name}", expanded=False):
                st.code(msg.content, language="json")

    render_memory_chat_input(graph, sidebar_state, config.namespace)


if __name__ == "__main__":
    run_memory_app()

