import json
import os
import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import rclpy
import streamlit as st
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from rai import get_embeddings_model, get_llm_model
from rai.communication.ros2 import ROS2Connector
from rai.frontend.memory_streamlit import (
    render_chat_messages_with_tools,
    render_memory_chat_input,
    render_memory_sidebar,
)
from rai.memory import MemoryManager, create_memory_agent_with_tools, load_memory_config
from rai.tools.ros2 import GetROS2ImageConfiguredTool, GetROS2TransformConfiguredTool
from rai.tools.ros2.navigation.nav2_blocking import (
    GetCurrentPoseTool,
    NavigateToPoseBlockingTool,
)
from rai.tools.time import WaitForSecondsTool
from rai_whoami import WhoamiConfig, create_robot_docs_tool, load_whoami_config

from rai_inspection_agent.tools import CenterGimbalAndCaptureTool, ControlSpeakerAlarmTool
from rai_inspection_agent.tools import ReadGasStatusTool, StartGasMonitoringTool, StopGasMonitoringTool


EMBODIMENT_PATH = (
    PROJECT_ROOT / "embodiments" / "inspection_embodiment.json"
)

BASE_SYSTEM_PROMPT_TEMPLATE = """You are an inspection robot assistant. You can move around, observe the environment, take camera images, and execute inspection-specific gimbal photo tasks.

## System Memory (Embodiment)
{embodiment}"""

ROBOT_DOCS_PROMPT_SECTION = """## Robot Documentation Retrieval
If the query_robot_docs tool is available, use it for questions about the robot's static documentation: hardware specifications, sensors, capabilities, URDF details, manuals, or operating limits. Do not use it for user preferences, learned facts, remembered locations, or conversation memory."""

ROSBOT_TOOLS_PROMPT_SECTION = """## Robot Runtime Tools
You can get the robot transform or current navigation pose, read the current camera image, navigate to a target pose in the map frame, and wait for a specified duration.

This app does not include rai_perception object-position tools. If a task requires detecting or locating arbitrary objects, explain that limitation or ask for explicit coordinates."""

INSPECTION_TOOLS_PROMPT_SECTION = """## Inspection Runtime Tools
When the user asks to take an inspection photo with the gimbal, use center_gimbal_and_capture. This tool centers the gimbal first, waits for settling, captures the requested photo(s), and returns the saved image path and execution status.
When the user says "播放检测到气体泄漏", use control_speaker_alarm with command "gas_leak".
When the user says "播放检测到温度异常", use control_speaker_alarm with command "temperature_abnormal".
When the user says "停止播放", use control_speaker_alarm with command "stop".
When the user asks to start gas monitoring, use start_gas_monitoring.
When the user asks to read the current gas sensor state, use read_gas_status.
When the user asks to stop gas monitoring, use stop_gas_monitoring.
Do not remap these alarm meanings to other categories."""


def _load_embodiment(path: Path) -> str:
    if not path.exists():
        return f"(Embodiment file not found at {path})"
    try:
        data = json.loads(path.read_text())
        desc = data.get("description", "")
        rules = data.get("rules", [])
        capabilities = data.get("capabilities", [])

        parts = [desc]
        if rules:
            parts.append("Rules:\n" + "\n".join(f"  - {r}" for r in rules))
        if capabilities:
            parts.append(
                "Capabilities:\n" + "\n".join(f"  - {c}" for c in capabilities)
            )
        return "\n\n".join(parts)
    except Exception as e:
        return f"(Error loading embodiment: {e})"


@st.cache_resource
def initialize_inspection_tools() -> list[BaseTool]:
    if not rclpy.ok():
        rclpy.init()

    connector = ROS2Connector(
        node_name="rai_inspection_agent",
        executor_type="multi_threaded",
        use_sim_time=True,
    )
    return [
        GetROS2TransformConfiguredTool(
            connector=connector,
            source_frame="map",
            target_frame="base_link",
            timeout_sec=5.0,
        ),
        GetROS2ImageConfiguredTool(
            connector=connector,
            topic="/camera/camera/color/image_raw",
        ),
        WaitForSecondsTool(),
        NavigateToPoseBlockingTool(
            connector=connector,
            frame_id="map",
            action_name="navigate_to_pose",
        ),
        GetCurrentPoseTool(
            connector=connector,
            frame_id="map",
            robot_frame_id="base_link",
        ),
        CenterGimbalAndCaptureTool(
            connector=connector,
            action_name="/center_gimbal_and_capture",
            result_timeout_sec=60.0,
        ),
        ControlSpeakerAlarmTool(
            connector=connector,
            service_name="/alarm_aggregator_node/set_parameters",
            timeout_sec=5.0,
        ),
        StartGasMonitoringTool(
            connector=connector,
            service_name="/monitor/gas/start",
            timeout_sec=5.0,
        ),
        ReadGasStatusTool(
            connector=connector,
            topic_name="/monitor/gas/status",
            topic_type="diagnostic_msgs/msg/DiagnosticStatus",
        ),
        StopGasMonitoringTool(
            connector=connector,
            service_name="/monitor/gas/stop",
            timeout_sec=5.0,
        ),
    ]


def build_memory_agent(
    memory_mgr: MemoryManager,
    embodiment_path: Path,
    user_id: str = "default",
    namespace: str = "inspection",
    robot_docs_config: WhoamiConfig | None = None,
    embeddings_model=None,
    robot_tools: Sequence[BaseTool] | None = None,
) -> object:
    llm = get_llm_model("complex_model", streaming=True)
    embodiment_text = _load_embodiment(embodiment_path)
    robot_docs_config = robot_docs_config or load_whoami_config()
    robot_docs_tool = create_robot_docs_tool(robot_docs_config, embeddings_model)
    runtime_tools = (
        list(robot_tools) if robot_tools is not None else initialize_inspection_tools()
    )

    def build_base_system_prompt(_context) -> str:
        return BASE_SYSTEM_PROMPT_TEMPLATE.format(embodiment=embodiment_text)

    extra_prompt_sections = [ROSBOT_TOOLS_PROMPT_SECTION, INSPECTION_TOOLS_PROMPT_SECTION]
    if robot_docs_tool:
        extra_prompt_sections.append(ROBOT_DOCS_PROMPT_SECTION)

    return create_memory_agent_with_tools(
        memory_mgr=memory_mgr,
        llm=llm,
        base_system_prompt_builder=build_base_system_prompt,
        namespace=namespace,
        user_id=user_id,
        base_tools=runtime_tools,
        extra_tools=[robot_docs_tool],
        extra_prompt_sections=extra_prompt_sections,
    )


def initialize_memory_mgr() -> MemoryManager:
    config = load_memory_config()
    if not config.enabled:
        st.error("Memory is disabled. Enable it in config.toml [memory] section.")
        st.stop()

    if config.backend == "postgres" and not config.connection:
        st.error(
            "PostgreSQL backend selected but no connection string in config.toml. "
            "Add: connection = 'postgresql://user:pass@host:5432/db'"
        )
        st.stop()

    memory_mgr = MemoryManager(config=config)
    try:
        embeddings = get_embeddings_model()
        memory_mgr = MemoryManager(config=config, embeddings=embeddings)
    except Exception as e:
        st.warning(f"Could not load embeddings, semantic search disabled: {e}")
        memory_mgr = MemoryManager(config=config)

    memory_mgr.start()
    memory_mgr.setup()
    return memory_mgr


def _welcome_message() -> AIMessage:
    return AIMessage(
        content=(
            "Hi. I'm an inspection robot assistant with persistent memory. "
            "I can navigate, inspect camera images, and take centered gimbal photos."
        )
    )


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
        graph = build_memory_agent(
            memory_mgr,
            EMBODIMENT_PATH,
            user_id=user_id,
            namespace=config.namespace,
            robot_docs_config=robot_docs_config,
        )
        st.session_state[graph_key] = graph
        st.session_state["_last_user"] = user_id

    graph = st.session_state[graph_key]
    sidebar_state = render_memory_sidebar(
        memory_mgr=memory_mgr,
        graph=graph,
        namespace=config.namespace,
        welcome_message_factory=_welcome_message,
    )
    if sidebar_state.user_id != user_id:
        graph = build_memory_agent(
            memory_mgr,
            EMBODIMENT_PATH,
            user_id=sidebar_state.user_id,
            namespace=config.namespace,
            robot_docs_config=robot_docs_config,
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
