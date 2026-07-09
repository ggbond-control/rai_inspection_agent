from types import SimpleNamespace

from rai.communication.ros2 import ROS2Connector
from rai_inspection_agent.tools.pose import OdometryCurrentPoseTool


class _FakeConnector(ROS2Connector):
    def __init__(self, message):
        self.message = message
        self.calls = []

    def receive_message(self, source, timeout_sec, msg_type):
        self.calls.append(
            {
                "source": source,
                "timeout_sec": timeout_sec,
                "msg_type": msg_type,
            }
        )
        return SimpleNamespace(payload=self.message)

    def get_transform(self, *args, **kwargs):
        raise AssertionError("OdometryCurrentPoseTool must not use TF")


def test_odometry_current_pose_tool_reads_odom_without_tf():
    odom = SimpleNamespace(
        header=SimpleNamespace(frame_id="odom"),
        child_frame_id="base_link",
        pose=SimpleNamespace(
            pose=SimpleNamespace(
                position=SimpleNamespace(x=1.25, y=-2.5, z=0.0),
                orientation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
            )
        ),
    )
    connector = _FakeConnector(odom)
    tool = OdometryCurrentPoseTool(
        connector=connector,
        topic_name="/odom",
        topic_type="nav_msgs/msg/Odometry",
        timeout_sec=1.5,
    )

    result = tool._run()

    assert connector.calls == [
        {
            "source": "/odom",
            "timeout_sec": 1.5,
            "msg_type": "nav_msgs/msg/Odometry",
        }
    ]
    assert "frame_id: odom" in result
    assert "child_frame_id: base_link" in result
    assert "x: 1.2500" in result
    assert "y: -2.5000" in result
    assert "yaw: 0.0000" in result
