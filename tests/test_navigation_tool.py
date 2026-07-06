from types import MethodType, SimpleNamespace

import rclpy
from action_msgs.msg import GoalStatus
from rai.communication.ros2 import ROS2Connector
from rai_inspection_agent.tools.navigation import SupervisedNavigateToPoseBlockingTool


class _FakeActionAPI:
    def __init__(self, done_after=1, feedbacks=None, result=None):
        self.done_after = done_after
        self.feedbacks = feedbacks or []
        self.result = result or SimpleNamespace(
            status=GoalStatus.STATUS_SUCCEEDED,
            result=SimpleNamespace(error_code=0, error_msg=""),
        )
        self.done_checks = 0

    def is_goal_done(self, handle):
        self.done_checks += 1
        return self.done_checks >= self.done_after

    def get_feedback(self, handle):
        count = min(self.done_checks, len(self.feedbacks))
        return self.feedbacks[:count]

    def get_result(self, handle):
        return self.result

    def shutdown(self):
        pass


def _connector(action_api):
    if not rclpy.ok():
        rclpy.init()
    connector = ROS2Connector(node_name="test_supervised_navigation_tool")
    connector._actions_api = action_api
    starts = []
    cancels = []

    def fake_start_action(self, action_data, target, timeout_sec, msg_type):
        starts.append(
            {
                "payload": action_data.payload,
                "target": target,
                "timeout_sec": timeout_sec,
                "msg_type": msg_type,
            }
        )
        return "nav-1"

    def fake_terminate_action(self, handle):
        cancels.append(handle)

    connector.start_action = MethodType(fake_start_action, connector)
    connector.terminate_action = MethodType(fake_terminate_action, connector)
    return connector, starts, cancels


def _feedback(distance_remaining):
    return SimpleNamespace(distance_remaining=distance_remaining)


def test_supervised_navigation_returns_success_without_cancel():
    connector, starts, cancels = _connector(_FakeActionAPI(done_after=1))
    try:
        tool = SupervisedNavigateToPoseBlockingTool(
            connector=connector,
            poll_interval_sec=0.01,
        )
        result = tool._run(x=1.0, y=2.0, z=0.0, yaw=0.5)
    finally:
        connector.shutdown()

    assert result.startswith("status=success")
    assert cancels == []
    assert starts[0]["target"] == "navigate_to_pose"
    assert starts[0]["msg_type"] == "nav2_msgs/action/NavigateToPose"
    assert starts[0]["payload"]["pose"]["pose"]["position"] == {
        "x": 1.0,
        "y": 2.0,
        "z": 0.0,
    }


def test_supervised_navigation_times_out_and_cancels():
    connector, _, cancels = _connector(_FakeActionAPI(done_after=1000))
    try:
        tool = SupervisedNavigateToPoseBlockingTool(
            connector=connector,
            poll_interval_sec=0.01,
            stall_timeout_sec=10.0,
        )
        result = tool._run(
            x=1.0,
            y=2.0,
            z=0.0,
            yaw=0.5,
            max_duration_sec=0.12,
        )
    finally:
        connector.shutdown()

    assert result.startswith("status=timeout")
    assert "max_duration_sec=0.1" in result
    assert cancels == ["nav-1"]


def test_supervised_navigation_detects_stall_and_cancels():
    connector, _, cancels = _connector(
        _FakeActionAPI(
            done_after=1000,
            feedbacks=[_feedback(5.0), _feedback(4.98), _feedback(4.97)],
        )
    )
    try:
        tool = SupervisedNavigateToPoseBlockingTool(
            connector=connector,
            poll_interval_sec=0.01,
            max_duration_sec=10.0,
            min_progress_m=0.2,
        )
        result = tool._run(
            x=1.0,
            y=2.0,
            z=0.0,
            yaw=0.5,
            stall_timeout_sec=0.12,
        )
    finally:
        connector.shutdown()

    assert result.startswith("status=stalled")
    assert "no progress of at least 0.200m" in result
    assert cancels == ["nav-1"]


def test_supervised_navigation_reports_aborted_result():
    connector, _, cancels = _connector(
        _FakeActionAPI(
            done_after=1,
            result=SimpleNamespace(
                status=GoalStatus.STATUS_ABORTED,
                result=SimpleNamespace(error_code=7, error_msg="goal is occupied"),
            ),
        )
    )
    try:
        tool = SupervisedNavigateToPoseBlockingTool(
            connector=connector,
            poll_interval_sec=0.01,
        )
        result = tool._run(x=1.0, y=2.0, z=0.0, yaw=0.5)
    finally:
        connector.shutdown()

    assert result.startswith("status=aborted")
    assert "goal is occupied" in result
    assert cancels == []
