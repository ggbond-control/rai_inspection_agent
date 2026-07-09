from typing import Any, Type

from pydantic import BaseModel, Field
from rai.tools.ros2.base import BaseROS2Tool
from tf_transformations import euler_from_quaternion


class OdometryCurrentPoseInput(BaseModel):
    pass


class OdometryCurrentPoseTool(BaseROS2Tool):
    name: str = "get_current_pose"
    description: str = (
        "Get the robot's current pose from an odometry topic without subscribing to TF. "
        "The returned pose is in the odometry message frame, usually odom."
    )
    args_schema: Type[OdometryCurrentPoseInput] = OdometryCurrentPoseInput

    topic_name: str = Field(default="/odometry")
    topic_type: str = Field(default="nav_msgs/msg/Odometry")
    timeout_sec: float = Field(default=2.0, ge=0.1)

    def _run(self) -> str:
        if not self.is_readable(self.topic_name):
            raise ValueError(f"Topic {self.topic_name} is not readable")

        message = self.connector.receive_message(
            self.topic_name,
            timeout_sec=self.timeout_sec,
            msg_type=self.topic_type,
        )
        odom = message.payload
        pose = odom.pose.pose
        position = pose.position
        orientation = pose.orientation
        yaw = self._yaw_from_orientation(orientation)
        frame_id = getattr(getattr(odom, "header", None), "frame_id", "")
        child_frame_id = getattr(odom, "child_frame_id", "")

        return (
            "Current Pose from odometry "
            f"(topic: {self.topic_name}, frame_id: {frame_id}, child_frame_id: {child_frame_id}):\n"
            f"  x: {position.x:.4f}\n"
            f"  y: {position.y:.4f}\n"
            f"  z: {position.z:.4f}\n"
            f"  yaw: {yaw:.4f} (radians)"
        )

    def _yaw_from_orientation(self, orientation: Any) -> float:
        quat = [
            orientation.x,
            orientation.y,
            orientation.z,
            orientation.w,
        ]
        _, _, yaw = euler_from_quaternion(quat)
        return yaw
