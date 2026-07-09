from rai.communication.ros2 import ROS2Connector
from rai.tools.ros2 import GetROS2TransformConfiguredTool
from rai.tools.ros2.navigation.nav2_blocking import GetCurrentPoseTool

from rai_inspection_agent import runtime
from rai_inspection_agent.tools import CenterGimbalAndCaptureTool, SupervisedNavigateToPoseBlockingTool


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


def test_create_inspection_tools_uses_separate_tf_connector(monkeypatch):
    _FakeConnector.instances = []
    monkeypatch.setattr(runtime.rclpy, "ok", lambda: True)
    monkeypatch.setattr(runtime, "ROS2Connector", _FakeConnector)

    tools = runtime.create_inspection_tools()
    tools_by_name = {tool.name: tool for tool in tools}

    runtime_connector = _FakeConnector.instances[0]
    tf_connector = _FakeConnector.instances[1]

    assert runtime_connector.node_name == "rai_inspection_agent"
    assert runtime_connector.enable_tf is False
    assert runtime_connector.executor_type == "single_threaded"
    assert tf_connector.node_name == "rai_inspection_agent_tf"
    assert tf_connector.enable_tf is True
    assert tf_connector.executor_type == "single_threaded"

    assert tools_by_name["navigate_to_pose_blocking"].connector is runtime_connector
    assert tools_by_name["center_gimbal_and_capture"].connector is runtime_connector
    assert isinstance(tools_by_name["navigate_to_pose_blocking"], SupervisedNavigateToPoseBlockingTool)
    assert isinstance(tools_by_name["center_gimbal_and_capture"], CenterGimbalAndCaptureTool)

    transform_tool = next(tool for tool in tools if isinstance(tool, GetROS2TransformConfiguredTool))
    pose_tool = next(tool for tool in tools if isinstance(tool, GetCurrentPoseTool))
    assert transform_tool.connector is tf_connector
    assert pose_tool.connector is tf_connector
