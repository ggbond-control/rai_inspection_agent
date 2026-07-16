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
