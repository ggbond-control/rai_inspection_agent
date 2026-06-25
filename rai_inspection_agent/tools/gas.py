from typing import Any, Dict, Type
from pydantic import BaseModel, Field
from rai.communication.ros2 import ROS2Message
from rai.tools.ros2.base import BaseROS2Tool


class StartGasMonitoringInput(BaseModel):
    pass


class StopGasMonitoringInput(BaseModel):
    pass


class ReadGasStatusInput(BaseModel):
    timeout_sec: float = Field(default=2.0, ge=0.1, description="Timeout in seconds for receiving gas status.")


class StartGasMonitoringTool(BaseROS2Tool):
    name: str = "start_gas_monitoring"
    description: str = "Start the gas sensor monitoring driver."
    args_schema: Type[StartGasMonitoringInput] = StartGasMonitoringInput

    service_name: str = Field(default="/monitor/gas/start")
    service_type: str = Field(default="std_srvs/srv/Trigger")
    timeout_sec: float = Field(default=5.0, ge=0.1)

    def _run(self) -> dict[str, Any]:
        return _call_trigger_service(
            tool=self,
            service_name=self.service_name,
            service_type=self.service_type,
            timeout_sec=self.timeout_sec,
        )


class StopGasMonitoringTool(BaseROS2Tool):
    name: str = "stop_gas_monitoring"
    description: str = "Stop the gas sensor monitoring driver."
    args_schema: Type[StopGasMonitoringInput] = StopGasMonitoringInput

    service_name: str = Field(default="/monitor/gas/stop")
    service_type: str = Field(default="std_srvs/srv/Trigger")
    timeout_sec: float = Field(default=5.0, ge=0.1)

    def _run(self) -> dict[str, Any]:
        return _call_trigger_service(
            tool=self,
            service_name=self.service_name,
            service_type=self.service_type,
            timeout_sec=self.timeout_sec,
        )


class ReadGasStatusTool(BaseROS2Tool):
    name: str = "read_gas_status"
    description: str = "Read the latest structured gas sensor status summary."
    args_schema: Type[ReadGasStatusInput] = ReadGasStatusInput

    topic_name: str = Field(default="/monitor/gas/status")
    topic_type: str = Field(default="diagnostic_msgs/msg/DiagnosticStatus")

    def _run(self, timeout_sec: float = 2.0) -> dict[str, Any]:
        if not self.is_readable(self.topic_name):
            raise ValueError(f"Topic {self.topic_name} is not readable")

        try:
            response = self.connector.receive_message(
                self.topic_name,
                timeout_sec=timeout_sec,
                msg_type=self.topic_type,
            )
            payload = response.payload
            return {
                "status": "succeeded",
                "topic": self.topic_name,
                "level": getattr(payload, "level", None),
                "name": getattr(payload, "name", ""),
                "message": getattr(payload, "message", ""),
                "hardware_id": getattr(payload, "hardware_id", ""),
                "values": _summarize_gas_values(getattr(payload, "values", [])),
                "error_message": "",
            }
        except Exception as exc:
            return {
                "status": "failed",
                "topic": self.topic_name,
                "level": None,
                "name": "",
                "message": "",
                "hardware_id": "",
                "values": {},
                "error_message": f"{type(exc).__name__}: {exc}",
            }


def _call_trigger_service(
    tool: BaseROS2Tool,
    service_name: str,
    service_type: str,
    timeout_sec: float,
) -> dict[str, Any]:
    if not tool.is_writable(service_name):
        raise ValueError(f"Service {service_name} is not writable")

    request: Dict[str, Any] = {}
    try:
        response = tool.connector.service_call(
            ROS2Message(payload=request),
            service_name,
            msg_type=service_type,
            timeout_sec=timeout_sec,
        )
        return {
            "status": "succeeded",
            "service_name": service_name,
            "response": str(response.payload),
            "error_message": "",
        }
    except Exception as exc:
        return {
            "status": "failed",
            "service_name": service_name,
            "response": "",
            "error_message": f"{type(exc).__name__}: {exc}",
        }


def _summarize_gas_values(values: list[Any]) -> dict[str, Any]:
    flattened = {
        getattr(item, "key", ""): getattr(item, "value", "")
        for item in values
    }
    sensor_count = flattened.get("sensor_count", "")
    sensor_ids = flattened.get("sensor_ids", "")

    sensor_summaries: list[str] = []
    for sensor_id in _parse_sensor_ids(sensor_ids):
        prefix = f"sensor_{sensor_id}."
        gas = flattened.get(prefix + "gas", "")
        concentration = flattened.get(prefix + "concentration", "")
        unit = flattened.get(prefix + "unit", "")
        low_alarm = flattened.get(prefix + "low_alarm", "")
        high_alarm = flattened.get(prefix + "high_alarm", "")
        status = flattened.get(prefix + "status", "")

        parts = []
        if gas:
            parts.append(f"{gas}: {concentration}{unit}")
        elif concentration or unit:
            parts.append(f"{concentration}{unit}")
        if low_alarm:
            parts.append(f"low_alarm: {low_alarm}")
        if high_alarm:
            parts.append(f"high_alarm: {high_alarm}")
        if status:
            parts.append(f"status: {status}")

        if parts:
            sensor_summaries.append(" ".join(parts))

    return {
        "sensor_count": sensor_count,
        "sensor_ids": sensor_ids,
        "sensors": sensor_summaries,
    }


def _parse_sensor_ids(sensor_ids: str) -> list[str]:
    if not sensor_ids:
        return []
    return [part.strip() for part in sensor_ids.split(",") if part.strip()]
