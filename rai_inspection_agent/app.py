from pathlib import Path
from typing import Sequence

import rclpy
import streamlit as st
from langchain_core.tools import BaseTool
from rai import get_llm_model
from rai.communication.ros2 import ROS2Connector
from rai.memory import MemoryManager, create_memory_agent_with_tools, load_memory_config

from rai_inspection_agent.tools import CenterGimbalAndCaptureTool


BASE_SYSTEM_PROMPT = """You are an inspection robot assistant.

Use inspection tools to execute robot runtime tasks. When the user asks to take
an inspection photo with the gimbal, use the center_gimbal_and_capture tool.
"""


@st.cache_resource
def initialize_inspection_tools() -> list[BaseTool]:
    if not rclpy.ok():
        rclpy.init()

    connector = ROS2Connector(
        node_name="rai_inspection_agent",
        executor_type="multi_threaded",
        use_sim_time=False,
    )
    return [
        CenterGimbalAndCaptureTool(
            connector=connector,
            action_name="/center_gimbal_and_capture",
            result_timeout_sec=60.0,
        )
    ]


def build_agent(
    memory_mgr: MemoryManager,
    tools: Sequence[BaseTool] | None = None,
) -> object:
    llm = get_llm_model("complex_model", streaming=True)
    runtime_tools = list(tools) if tools is not None else initialize_inspection_tools()

    return create_memory_agent_with_tools(
        memory_mgr=memory_mgr,
        llm=llm,
        base_system_prompt_builder=lambda _context: BASE_SYSTEM_PROMPT,
        namespace="inspection",
        user_id="default",
        base_tools=runtime_tools,
        extra_tools=[],
        extra_prompt_sections=[],
    )


def initialize_memory_mgr() -> MemoryManager:
    config = load_memory_config()
    memory_mgr = MemoryManager(config=config)
    memory_mgr.start()
    memory_mgr.setup()
    return memory_mgr


def main() -> None:
    st.set_page_config(page_title="RAI Inspection Agent", page_icon=":robot:")
    st.title("RAI Inspection Agent")
    st.write("Inspection agent is configured. Use the tool from code or extend this app UI.")


if __name__ == "__main__":
    main()
