from langchain_core.messages import AIMessage, HumanMessage, ToolCall
from rai.communication.ros2 import ROS2Connector

from rai_inspection_agent import runtime
from rai_inspection_agent.tools import (
    CenterGimbalAndCaptureTool,
    OdometryCurrentPoseTool,
    SupervisedNavigateToPoseBlockingTool,
)


class _FakeConnector(ROS2Connector):
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.node_name = kwargs.get("node_name")
        self.enable_tf = kwargs.get("enable_tf")
        self.executor_type = kwargs.get("executor_type")
        _FakeConnector.instances.append(self)

    def shutdown(self):
        pass


def test_create_inspection_tools_uses_only_no_tf_connector(monkeypatch):
    _FakeConnector.instances = []
    monkeypatch.setattr(runtime.rclpy, "ok", lambda: True)
    monkeypatch.setattr(runtime, "ROS2Connector", _FakeConnector)

    tools = runtime.create_inspection_tools()
    tools_by_name = {tool.name: tool for tool in tools}

    runtime_connector = _FakeConnector.instances[0]

    assert len(_FakeConnector.instances) == 1
    assert runtime_connector.node_name == "rai_inspection_agent"
    assert runtime_connector.enable_tf is False
    assert runtime_connector.executor_type == "single_threaded"

    assert tools_by_name["navigate_to_pose_blocking"].connector is runtime_connector
    assert tools_by_name["center_gimbal_and_capture"].connector is runtime_connector
    assert tools_by_name["get_current_pose"].connector is runtime_connector
    assert isinstance(tools_by_name["navigate_to_pose_blocking"], SupervisedNavigateToPoseBlockingTool)
    assert isinstance(tools_by_name["center_gimbal_and_capture"], CenterGimbalAndCaptureTool)
    assert isinstance(tools_by_name["get_current_pose"], OdometryCurrentPoseTool)


def test_inspection_prompt_relays_visual_result_without_expansion():
    prompt = runtime.INSPECTION_TOOLS_PROMPT_SECTION

    assert "relay its requirement checklist and short conclusion directly" in prompt
    assert "Do not expand, rewrite, or duplicate it" in prompt
    assert "do not add claims that are absent from the tool result" in prompt


def test_inspection_policy_allows_repeated_visual_analysis(monkeypatch):
    monkeypatch.setattr(
        runtime.ToolCallGuard,
        "with_default_policies",
        runtime.ToolCallGuard.__dict__["with_default_policies"],
    )
    monkeypatch.delattr(
        runtime.ToolCallGuard,
        "_rai_inspection_policy_override",
        raising=False,
    )

    runtime.install_inspection_tool_policy_override()
    guard = runtime.ToolCallGuard.with_default_policies()
    policy = guard.policies["analyze_artifact_image"]

    assert policy.max_calls_per_turn == 12
    assert policy.max_consecutive_calls == 12
    assert policy.block_similar_args is False
    assert guard.max_total_calls_per_turn == 20

    calls = [
        ToolCall(
            name="analyze_artifact_image",
            args={"tool_call_id": f"capture-{index}"},
            id=f"analysis-{index}",
        )
        for index in range(13)
    ]
    messages = [
        HumanMessage(content="分析所有巡检图片"),
        AIMessage(content="", tool_calls=calls),
    ]

    assert guard.check(calls[11], messages, current_call_index=11) is None
    blocked = guard.check(calls[12], messages, current_call_index=12)
    assert blocked is not None
    assert "already called 12 time(s)" in blocked
