from types import MethodType, SimpleNamespace
import rclpy
from rai.communication.ros2 import ROS2Connector
from rai_inspection_agent.tools.gas import ReadGasStatusTool, StartGasMonitoringTool, StopGasMonitoringTool


class _FakeKeyValue:
    def __init__(self, key, value):
        self.key = key
        self.value = value


def test_start_gas_monitoring_tool_calls_expected_service():
    if not rclpy.ok():
        rclpy.init()
    connector = ROS2Connector(node_name="test_start_gas_monitoring_tool")
    calls = []

    def fake_service_call(self, message, target, msg_type, timeout_sec):
        calls.append(
            {
                "payload": message.payload,
                "target": target,
                "msg_type": msg_type,
                "timeout_sec": timeout_sec,
            }
        )
        return SimpleNamespace(payload="Trigger_Response(success=True, message='气体传感器已启动')")

    connector.service_call = MethodType(fake_service_call, connector)
    try:
        tool = StartGasMonitoringTool(connector=connector)
        result = tool._run()
    finally:
        connector.shutdown()

    assert calls == [
        {
            "payload": {},
            "target": "/monitor/gas/start",
            "msg_type": "std_srvs/srv/Trigger",
            "timeout_sec": 5.0,
        }
    ]
    assert result["status"] == "succeeded"
    assert result["service_name"] == "/monitor/gas/start"


def test_stop_gas_monitoring_tool_calls_expected_service():
    if not rclpy.ok():
        rclpy.init()
    connector = ROS2Connector(node_name="test_stop_gas_monitoring_tool")
    calls = []

    def fake_service_call(self, message, target, msg_type, timeout_sec):
        calls.append(
            {
                "payload": message.payload,
                "target": target,
                "msg_type": msg_type,
                "timeout_sec": timeout_sec,
            }
        )
        return SimpleNamespace(payload="Trigger_Response(success=True, message='气体传感器已停止')")

    connector.service_call = MethodType(fake_service_call, connector)
    try:
        tool = StopGasMonitoringTool(connector=connector)
        result = tool._run()
    finally:
        connector.shutdown()

    assert calls == [
        {
            "payload": {},
            "target": "/monitor/gas/stop",
            "msg_type": "std_srvs/srv/Trigger",
            "timeout_sec": 5.0,
        }
    ]
    assert result["status"] == "succeeded"
    assert result["service_name"] == "/monitor/gas/stop"


def test_read_gas_status_tool_summarizes_values():
    if not rclpy.ok():
        rclpy.init()
    connector = ROS2Connector(node_name="test_read_gas_status_tool")

    payload = SimpleNamespace(
        level=2,
        name="gas_sensor",
        message="气体传感器状态异常：低报",
        hardware_id="/dev/ttyUSB0",
        values=[
            _FakeKeyValue("sensor_count", "6"),
            _FakeKeyValue("sensor_ids", "1,2,3,4,5,6"),
            _FakeKeyValue("sensor_6.gas", "O3"),
            _FakeKeyValue("sensor_6.concentration", "0.120"),
            _FakeKeyValue("sensor_6.unit", "ppm"),
            _FakeKeyValue("sensor_6.low_alarm", "0.100"),
            _FakeKeyValue("sensor_6.high_alarm", "0.500"),
            _FakeKeyValue("sensor_6.status", "低报"),
        ],
    )

    def fake_receive_message(self, source, timeout_sec=1.0, msg_type=None, **kwargs):
        return SimpleNamespace(payload=payload, metadata={"topic": source, "msg_type": msg_type})

    connector.receive_message = MethodType(fake_receive_message, connector)
    try:
        tool = ReadGasStatusTool(connector=connector)
        result = tool._run(timeout_sec=2.0)
    finally:
        connector.shutdown()

    assert result["status"] == "succeeded"
    assert result["level"] == 2
    assert result["name"] == "gas_sensor"
    assert result["message"] == "气体传感器状态异常：低报"
    assert result["hardware_id"] == "/dev/ttyUSB0"
    assert result["values"] == {
        "sensor_count": "6",
        "sensor_ids": "1,2,3,4,5,6",
        "sensors": ["O3: 0.120ppm low_alarm: 0.100 high_alarm: 0.500 status: 低报"],
    }


def test_read_gas_status_tool_handles_receive_error():
    if not rclpy.ok():
        rclpy.init()
    connector = ROS2Connector(node_name="test_read_gas_status_tool_error")

    def fake_receive_message(self, source, timeout_sec=1.0, msg_type=None, **kwargs):
        raise TimeoutError("Message from /monitor/gas/status not received in 2.0 seconds")

    connector.receive_message = MethodType(fake_receive_message, connector)
    try:
        tool = ReadGasStatusTool(connector=connector)
        result = tool._run(timeout_sec=2.0)
    finally:
        connector.shutdown()

    assert result["status"] == "failed"
    assert result["values"] == {}
    assert "TimeoutError" in result["error_message"]
