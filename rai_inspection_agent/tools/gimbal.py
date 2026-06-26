import time
from pathlib import Path
from typing import Any, Literal, Type

from pydantic import BaseModel, Field
from rai.communication.ros2 import ROS2Message
from rai.messages import MultimodalArtifact, preprocess_image
from rai.tools.ros2.base import BaseROS2Tool


class CenterGimbalAndCaptureInput(BaseModel):
    task_id: int = Field(default=0, ge=0, description="Inspection task identifier.")
    camera_type: str = Field(
        default="visible",
        description="Camera channel to use, for example visible, ir, thermal, or depth.",
    )
    photo_count: int = Field(default=1, ge=1, description="Number of photos to take.")
    photo_interval_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description="Delay between photos when photo_count is greater than one.",
    )
    zoom_level: float = Field(
        default=0.0,
        ge=0.0,
        description="Optional optical zoom level. Use 0 to keep current zoom.",
    )
    home_timeout_sec: float = Field(
        default=15.0,
        ge=0.0,
        description="Timeout for gimbal centering. Use 0 for server default.",
    )
    capture_timeout_sec: float = Field(
        default=15.0,
        ge=0.0,
        description="Timeout for capture. Use 0 for server default.",
    )


class CenterGimbalAndCaptureTool(BaseROS2Tool):
    name: str = "center_gimbal_and_capture"
    description: str = (
        "Center the inspection gimbal to its home pose, wait for it to settle, "
        "then capture inspection photo(s). Returns the saved image path and status."
    )
    response_format: Literal["content", "content_and_artifact"] = "content_and_artifact"
    args_schema: Type[CenterGimbalAndCaptureInput] = CenterGimbalAndCaptureInput

    action_name: str = Field(default="/center_gimbal_and_capture")
    action_type: str = Field(
        default="inspection_interfaces/action/CenterGimbalAndCapture"
    )
    goal_accept_timeout_sec: float = Field(default=5.0, ge=0.1)
    result_timeout_sec: float = Field(default=60.0, ge=0.1)
    poll_interval_sec: float = Field(default=0.1, ge=0.01)

    def _run(
        self,
        task_id: int = 0,
        camera_type: str = "visible",
        photo_count: int = 1,
        photo_interval_seconds: float = 0.0,
        zoom_level: float = 0.0,
        home_timeout_sec: float = 15.0,
        capture_timeout_sec: float = 15.0,
    ) -> tuple[str, MultimodalArtifact] | dict[str, Any]:
        if not self.is_writable(self.action_name):
            raise ValueError(f"Action {self.action_name} is not writable")

        goal = {
            "task_id": int(task_id),
            "camera_type": camera_type,
            "photo_count": int(photo_count),
            "photo_interval_seconds": float(photo_interval_seconds),
            "zoom_level": float(zoom_level),
            "home_timeout_sec": float(home_timeout_sec),
            "capture_timeout_sec": float(capture_timeout_sec),
        }
        handle = self.connector.start_action(
            ROS2Message(payload=goal),
            self.action_name,
            timeout_sec=self.goal_accept_timeout_sec,
            msg_type=self.action_type,
        )

        action_api = getattr(self.connector, "_actions_api", None)
        if action_api is None:
            return {"status": "started", "action_id": handle, "goal": goal}

        deadline = time.monotonic() + self.result_timeout_sec
        while time.monotonic() < deadline:
            if action_api.is_goal_done(handle):
                return self._format_result(action_api.get_result(handle), handle)
            time.sleep(self.poll_interval_sec)

        raise TimeoutError(
            f"Timed out waiting for {self.action_name} result after "
            f"{self.result_timeout_sec:.1f}s; action_id={handle}"
        )

    def _format_result(self, action_result: Any, handle: str) -> tuple[str, MultimodalArtifact]:
        result = getattr(action_result, "result", action_result)
        image_uri = getattr(result, "image_uri", "")
        image_paths = self._collect_image_paths(image_uri)
        artifact: MultimodalArtifact = {
            "images": [preprocess_image(str(path)) for path in image_paths],
            "audios": [],
        }
        content = (
            "status="
            + ("succeeded" if getattr(result, "success", False) else "failed")
            + f" action_id={handle}"
            + f" image_uri={image_uri}"
            + f" captured_count={getattr(result, 'captured_count', 0)}"
            + f" elapsed_sec={getattr(result, 'elapsed_sec', 0.0)}"
            + f" error_message={getattr(result, 'error_message', '')}"
        )
        return content, artifact

    def _collect_image_paths(self, image_uri: str) -> list[Path]:
        if not image_uri:
            return []

        primary = Path(image_uri)
        if not primary.exists():
            return []

        image_dir = primary.parent
        candidates = sorted(
            [
                path
                for path in image_dir.iterdir()
                if path.is_file()
                and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
                and path.name.startswith("capture_raw_iter")
            ]
        )
        if candidates:
            return candidates
        return [primary]


def create_center_gimbal_and_capture_tool(
    connector: Any,
    action_name: str = "/center_gimbal_and_capture",
    result_timeout_sec: float = 60.0,
) -> CenterGimbalAndCaptureTool:
    return CenterGimbalAndCaptureTool(
        connector=connector,
        action_name=action_name,
        result_timeout_sec=result_timeout_sec,
    )
