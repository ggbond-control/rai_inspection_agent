import time
from typing import Any, Literal, Type

from action_msgs.msg import GoalStatus
from pydantic import BaseModel, Field
from rai.communication.ros2 import ROS2Message
from rai.tools.ros2.base import BaseROS2Tool
from tf_transformations import quaternion_from_euler


class SupervisedNavigateToPoseInput(BaseModel):
    x: float = Field(..., description="The x coordinate of the pose")
    y: float = Field(..., description="The y coordinate of the pose")
    z: float = Field(..., description="The z coordinate of the pose")
    yaw: float = Field(..., description="The yaw angle of the pose")
    max_duration_sec: float | None = Field(
        default=None,
        ge=0.1,
        description="Maximum time to wait for navigation before canceling.",
    )
    stall_timeout_sec: float | None = Field(
        default=None,
        ge=0.1,
        description="Maximum time without enough distance_remaining progress.",
    )
    min_progress_m: float | None = Field(
        default=None,
        ge=0.0,
        description="Minimum distance_remaining decrease treated as progress.",
    )


class SupervisedNavigateToPoseBlockingTool(BaseROS2Tool):
    name: str = "navigate_to_pose_blocking"
    description: str = (
        "Navigate to a specific pose with deterministic supervision. The tool "
        "cancels navigation and returns timeout or stalled instead of blocking "
        "forever when the robot cannot reach the goal."
    )
    args_schema: Type[SupervisedNavigateToPoseInput] = SupervisedNavigateToPoseInput

    frame_id: str = Field(default="map")
    action_name: str = Field(default="navigate_to_pose")
    action_type: str = Field(default="nav2_msgs/action/NavigateToPose")
    goal_accept_timeout_sec: float = Field(default=5.0, ge=0.1)
    max_duration_sec: float = Field(default=300.0, ge=0.1)
    stall_timeout_sec: float = Field(default=6.0, ge=0.1)
    min_progress_m: float = Field(default=0.15, ge=0.0)
    poll_interval_sec: float = Field(default=1, ge=0.01)

    def _run(
        self,
        x: float,
        y: float,
        z: float,
        yaw: float,
        max_duration_sec: float | None = None,
        stall_timeout_sec: float | None = None,
        min_progress_m: float | None = None,
    ) -> str:
        if not self.is_writable(self.action_name):
            raise ValueError(f"Action {self.action_name} is not writable")

        effective_max_duration = max_duration_sec or self.max_duration_sec
        effective_stall_timeout = stall_timeout_sec or self.stall_timeout_sec
        effective_min_progress = (
            self.min_progress_m if min_progress_m is None else min_progress_m
        )

        quat = quaternion_from_euler(0, 0, yaw)
        goal = {
            "pose": {
                "header": {
                    "frame_id": self.frame_id,
                    "stamp": self.connector.node.get_clock().now().to_msg(),
                },
                "pose": {
                    "position": {"x": x, "y": y, "z": z},
                    "orientation": {
                        "x": quat[0],
                        "y": quat[1],
                        "z": quat[2],
                        "w": quat[3],
                    },
                },
            }
        }

        try:
            handle = self.connector.start_action(
                ROS2Message(payload=goal),
                self.action_name,
                timeout_sec=self.goal_accept_timeout_sec,
                msg_type=self.action_type,
            )
        except Exception as e:
            return self._format_terminal_status(
                "aborted",
                f"failed to start action: {type(e).__name__}: {e}",
            )

        action_api = getattr(self.connector, "_actions_api", None)
        if action_api is None:
            return self._format_terminal_status(
                "aborted",
                f"action started but connector has no action API; action_id={handle}",
            )

        started_at = time.monotonic()
        last_progress_at = started_at
        best_distance_remaining: float | None = None
        last_distance_remaining: float | None = None
        last_feedback_count = 0

        while True:
            now = time.monotonic()
            if action_api.is_goal_done(handle):
                return self._format_result(action_api.get_result(handle), handle)

            feedbacks = action_api.get_feedback(handle)
            if len(feedbacks) > last_feedback_count:
                for feedback in feedbacks[last_feedback_count:]:
                    distance_remaining = self._extract_distance_remaining(feedback)
                    if distance_remaining is None:
                        continue
                    last_distance_remaining = distance_remaining
                    if best_distance_remaining is None:
                        best_distance_remaining = distance_remaining
                        last_progress_at = now
                    elif (
                        best_distance_remaining - distance_remaining
                        >= effective_min_progress
                    ):
                        best_distance_remaining = distance_remaining
                        last_progress_at = now
                last_feedback_count = len(feedbacks)

            elapsed = now - started_at
            stalled_for = now - last_progress_at
            if elapsed >= effective_max_duration:
                self._cancel_action(handle)
                return self._format_terminal_status(
                    "timeout",
                    (
                        f"navigation exceeded max_duration_sec={effective_max_duration:.1f}; "
                        f"action_id={handle}; "
                        f"last_distance_remaining={self._format_optional_float(last_distance_remaining)}"
                    ),
                )

            if stalled_for >= effective_stall_timeout:
                self._cancel_action(handle)
                return self._format_terminal_status(
                    "stalled",
                    (
                        f"no progress of at least {effective_min_progress:.3f}m for "
                        f"stall_timeout_sec={effective_stall_timeout:.1f}; "
                        f"action_id={handle}; "
                        f"last_distance_remaining={self._format_optional_float(last_distance_remaining)}"
                    ),
                )

            time.sleep(self.poll_interval_sec)

    def _cancel_action(self, handle: str) -> None:
        try:
            self.connector.terminate_action(handle)
        except Exception:
            pass

    def _format_result(self, action_result: Any, handle: str) -> str:
        status = getattr(action_result, "status", GoalStatus.STATUS_UNKNOWN)
        result = getattr(action_result, "result", action_result)
        error_msg = getattr(result, "error_msg", "")

        if status == GoalStatus.STATUS_SUCCEEDED:
            return self._format_terminal_status(
                "success", f"navigation reached the goal; action_id={handle}"
            )
        if status == GoalStatus.STATUS_CANCELED:
            return self._format_terminal_status(
                "canceled",
                (
                    "navigation was canceled by Nav2 or an external caller; "
                    f"action_id={handle}; error_msg={error_msg}"
                ),
            )
        return self._format_terminal_status(
            "aborted",
            (
                f"navigation finished with status={self._status_name(status)}; "
                f"action_id={handle}; error_code={getattr(result, 'error_code', '')}; "
                f"error_msg={error_msg}"
            ),
        )

    def _extract_distance_remaining(self, feedback: Any) -> float | None:
        feedback = getattr(feedback, "feedback", feedback)
        distance_remaining = getattr(feedback, "distance_remaining", None)
        if distance_remaining is None:
            return None
        return float(distance_remaining)

    def _format_terminal_status(
        self,
        status: Literal["success", "timeout", "stalled", "aborted", "canceled"],
        message: str,
    ) -> str:
        return f"status={status} message={message}"

    def _status_name(self, status: int) -> str:
        names = {
            GoalStatus.STATUS_UNKNOWN: "unknown",
            GoalStatus.STATUS_ACCEPTED: "accepted",
            GoalStatus.STATUS_EXECUTING: "executing",
            GoalStatus.STATUS_CANCELING: "canceling",
            GoalStatus.STATUS_SUCCEEDED: "succeeded",
            GoalStatus.STATUS_CANCELED: "canceled",
            GoalStatus.STATUS_ABORTED: "aborted",
        }
        return names.get(status, f"unknown_{status}")

    def _format_optional_float(self, value: float | None) -> str:
        if value is None:
            return "None"
        return f"{value:.3f}"
