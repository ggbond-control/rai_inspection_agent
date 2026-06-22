from types import MethodType, SimpleNamespace

import rclpy
from rai.communication.ros2 import ROS2Connector
from rai_inspection_agent.tools.gimbal import CenterGimbalAndCaptureTool


class _FakeActionAPI:
    def __init__(self):
        self.done_checks = 0

    def is_goal_done(self, handle):
        self.done_checks += 1
        return True

    def get_result(self, handle):
        return SimpleNamespace(
            result=SimpleNamespace(
                success=True,
                image_uri="/tmp/capture.jpg",
                captured_count=1,
                elapsed_sec=1.25,
                error_message="",
            )
        )

    def shutdown(self):
        pass


def test_center_gimbal_and_capture_tool_sends_expected_goal():
    if not rclpy.ok():
        rclpy.init()
    connector = ROS2Connector(node_name="test_center_gimbal_tool")
    connector._actions_api = _FakeActionAPI()
    calls = []

    def fake_start_action(self, action_data, target, timeout_sec, msg_type):
        calls.append(
            {
                "payload": action_data.payload,
                "target": target,
                "timeout_sec": timeout_sec,
                "msg_type": msg_type,
            }
        )
        return "action-1"

    connector.start_action = MethodType(fake_start_action, connector)
    try:
        tool = CenterGimbalAndCaptureTool(
            connector=connector,
            action_name="/center_gimbal_and_capture",
            result_timeout_sec=1.0,
            poll_interval_sec=0.01,
        )

        result = tool._run(task_id=7, camera_type="thermal", zoom_level=2.0)
    finally:
        connector.shutdown()

    assert calls == [
        {
            "payload": {
                "task_id": 7,
                "camera_type": "thermal",
                "photo_count": 1,
                "photo_interval_seconds": 0.0,
                "zoom_level": 2.0,
                "home_timeout_sec": 15.0,
                "capture_timeout_sec": 15.0,
            },
            "target": "/center_gimbal_and_capture",
            "timeout_sec": 5.0,
            "msg_type": "inspection_interfaces/action/CenterGimbalAndCapture",
        }
    ]
    assert result["status"] == "succeeded"
    assert result["image_uri"] == "/tmp/capture.jpg"
    assert result["captured_count"] == 1
