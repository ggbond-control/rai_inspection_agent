import json
import os
import sys
from pathlib import Path
from typing import Sequence

import rclpy
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from rai import get_embeddings_model, get_llm_model
from rai.agents.langchain.core import ToolCallGuard, ToolPolicy
from rai.communication.ros2 import ROS2Connector
from rai.memory import MemoryManager, create_memory_agent_with_tools, load_memory_config
from rai.tools.ros2 import GetROS2TransformConfiguredTool
from rai.tools.ros2.navigation.nav2_blocking import GetCurrentPoseTool
from rai.tools.time import WaitForSecondsTool
from rai_whoami import WhoamiConfig, create_robot_docs_tool, load_whoami_config

from rai_inspection_agent.tools import (
    AnalyzeArtifactImageTool,
    CenterGimbalAndCaptureTool,
    ControlSpeakerAlarmTool,
    ReadGasStatusTool,
    StartGasMonitoringTool,
    StopGasMonitoringTool,
    SupervisedNavigateToPoseBlockingTool,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

EMBODIMENT_PATH = PROJECT_ROOT / "embodiments" / "inspection_embodiment.json"

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
When the user asks to analyze, inspect, describe, or judge a previously captured inspection photo, use analyze_artifact_image. Use tool_call_id "latest" unless the user gives a specific tool call id.
When the user says "播放检测到气体泄漏", use control_speaker_alarm with command "gas_leak".
When the user says "播放检测到温度异常", use control_speaker_alarm with command "temperature_abnormal".
When the user says "停止播放", use control_speaker_alarm with command "stop".
When the user asks to start gas monitoring, use start_gas_monitoring.
When the user asks to read the current gas sensor state, use read_gas_status.
When the user asks to stop gas monitoring, use stop_gas_monitoring.
Do not remap these alarm meanings to other categories."""


def install_inspection_tool_policy_override() -> None:
    original = ToolCallGuard.with_default_policies

    if getattr(ToolCallGuard, "_rai_inspection_policy_override", False):
        return

    @classmethod
    def with_inspection_policies(cls) -> ToolCallGuard:
        guard = original()
        guard.max_total_calls_per_turn = 20
        guard.policies["navigate_to_pose_blocking"] = ToolPolicy(
            max_calls_per_turn=12,
            max_consecutive_calls=12,
        )
        return guard

    ToolCallGuard.with_default_policies = with_inspection_policies
    ToolCallGuard._rai_inspection_policy_override = True


def load_embodiment(path: Path) -> str:
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


def attach_robot_docs_to_artifact_analysis(
    tools: list[BaseTool],
    robot_docs_tool: BaseTool | None,
) -> None:
    for tool in tools:
        if isinstance(tool, AnalyzeArtifactImageTool):
            tool.robot_docs_tool = robot_docs_tool


def create_inspection_tools() -> list[BaseTool]:
    if not rclpy.ok():
        rclpy.init()

    connector = ROS2Connector(
        node_name="rai_inspection_agent",
        executor_type="single_threaded",
        use_sim_time=True,
        enable_tf=False,
    )
    tf_connector = ROS2Connector(
        node_name="rai_inspection_agent_tf",
        executor_type="single_threaded",
        use_sim_time=True,
        enable_tf=True,
    )
    return [
        GetROS2TransformConfiguredTool(
            connector=tf_connector,
            source_frame="map",
            target_frame="base_link",
            timeout_sec=5.0,
        ),
        WaitForSecondsTool(),
        SupervisedNavigateToPoseBlockingTool(
            connector=connector,
            frame_id="map",
            action_name="navigate_to_pose",
        ),
        GetCurrentPoseTool(
            connector=tf_connector,
            frame_id="map",
            robot_frame_id="base_link",
        ),
        CenterGimbalAndCaptureTool(
            connector=connector,
            action_name="/center_gimbal_and_capture",
            result_timeout_sec=60.0,
        ),
        AnalyzeArtifactImageTool(),
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


def build_inspection_agent(
    memory_mgr: MemoryManager,
    embodiment_path: Path = EMBODIMENT_PATH,
    user_id: str = "default",
    namespace: str = "inspection",
    robot_docs_config: WhoamiConfig | None = None,
    embeddings_model=None,
    robot_tools: Sequence[BaseTool] | None = None,
) -> object:
    install_inspection_tool_policy_override()
    llm = get_llm_model("complex_model", streaming=True)
    embodiment_text = load_embodiment(embodiment_path)
    robot_docs_config = robot_docs_config or load_whoami_config()
    if robot_docs_config.enabled and embeddings_model is None:
        embeddings_model = get_embeddings_model()
    robot_docs_tool = create_robot_docs_tool(robot_docs_config, embeddings_model)
    runtime_tools = list(robot_tools) if robot_tools is not None else create_inspection_tools()
    attach_robot_docs_to_artifact_analysis(runtime_tools, robot_docs_tool)

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


def initialize_inspection_memory_mgr() -> MemoryManager:
    config = load_memory_config()
    if not config.enabled:
        raise RuntimeError("Memory is disabled. Enable it in config.toml [memory] section.")
    if config.backend == "postgres" and not config.connection:
        raise RuntimeError(
            "PostgreSQL backend selected but no connection string in config.toml."
        )

    try:
        embeddings = get_embeddings_model()
        memory_mgr = MemoryManager(config=config, embeddings=embeddings)
    except Exception:
        memory_mgr = MemoryManager(config=config)

    memory_mgr.start()
    memory_mgr.setup()
    return memory_mgr


def welcome_message() -> AIMessage:
    return AIMessage(
        content=(
            "Hi. I'm an inspection robot assistant with persistent memory. "
            "I can navigate, inspect camera images, and take centered gimbal photos."
        )
    )

