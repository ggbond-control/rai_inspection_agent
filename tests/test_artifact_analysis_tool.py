from pathlib import Path
import os
import importlib.util

from langchain_core.messages import AIMessage
from rai.messages import store_artifacts


def _load_tool_class():
    module_path = (
        Path(__file__).parents[1]
        / "rai_inspection_agent"
        / "tools"
        / "artifact_analysis.py"
    )
    spec = importlib.util.spec_from_file_location("artifact_analysis", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.AnalyzeArtifactImageTool


AnalyzeArtifactImageTool = _load_tool_class()


class _FakeVisionModel:
    def __init__(self):
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return AIMessage(content="visible scene looks normal")


class _FakeDocsTool:
    def __init__(self):
        self.queries = []

    def invoke(self, input_):
        self.queries.append(input_["query"])
        return "### 8. 视觉检测要求\n- 安全帽检测\n- 跑冒滴漏检测"


class _FailingDocsTool:
    def __init__(self):
        self.calls = 0

    def invoke(self, input_):
        self.calls += 1
        raise RuntimeError("rag unavailable")


def test_analyze_artifact_image_uses_stored_image_and_returns_text(tmp_path: Path):
    artifact_root = tmp_path / "data" / "artifacts"
    store_artifacts(
        "call-1",
        [{"summary": "captured", "raw_images": ["iVBORw0KGgo="], "images": [], "audios": []}],
        db_path=artifact_root,
    )
    fake_model = _FakeVisionModel()
    tool = AnalyzeArtifactImageTool(
        artifact_root=str(artifact_root),
        llm=fake_model,
    )

    result = tool._run(tool_call_id="call-1", question="What is visible?")

    assert "tool_call_id=call-1" in result
    assert "visible scene looks normal" in result
    assert fake_model.messages is not None
    assert fake_model.messages[0].images == ["iVBORw0KGgo="]


def test_analyze_artifact_image_uses_robot_docs_before_vision_model(tmp_path: Path):
    artifact_root = tmp_path / "data" / "artifacts"
    store_artifacts(
        "call-1",
        [{"summary": "captured", "raw_images": ["iVBORw0KGgo="], "images": [], "audios": []}],
        db_path=artifact_root,
    )
    fake_docs = _FakeDocsTool()
    fake_model = _FakeVisionModel()
    tool = AnalyzeArtifactImageTool(
        artifact_root=str(artifact_root),
        llm=fake_model,
        robot_docs_tool=fake_docs,
    )

    result = tool._run(tool_call_id="call-1", question="What is visible?")

    assert fake_docs.queries == ["视觉检测要求"]
    assert fake_model.messages is not None
    prompt_parts = fake_model.messages[0].content
    prompt_text = "\n".join(
        part["text"] for part in prompt_parts if isinstance(part, dict) and "text" in part
    )
    assert "Visual Inspection Requirements" in prompt_text
    assert "安全帽检测" in prompt_text
    assert "User Question" in prompt_text
    assert "What is visible?" in prompt_text
    assert "evaluate each item exactly once" in prompt_text
    assert "正常|异常|无法判断|不适用" in prompt_text
    assert "## 检测结果" in prompt_text
    assert "## 结论" in prompt_text
    assert "conclusion to at most two short sentences" in prompt_text
    assert "visible scene looks normal" in result


def test_analyze_artifact_image_prompt_keeps_concise_format_without_rag():
    tool = AnalyzeArtifactImageTool(llm=_FakeVisionModel())

    prompt = tool._build_prompt("检查画面", "")

    assert "documented criteria were unavailable" in prompt
    assert "## 检测结果" in prompt
    assert "## 结论" in prompt
    assert "Do not add an introduction, scene overview, detailed report" in prompt


def test_analyze_artifact_image_default_question_requests_checklist():
    tool = AnalyzeArtifactImageTool(llm=_FakeVisionModel())
    default_question = tool.args_schema.model_fields["question"].default

    assert "each retrieved visual inspection requirement" in default_question
    assert "one brief visual reason" in default_question
    assert "short conclusion" in default_question


def test_analyze_artifact_image_caches_robot_docs_requirements(tmp_path: Path):
    artifact_root = tmp_path / "data" / "artifacts"
    for call_id in ("call-1", "call-2"):
        store_artifacts(
            call_id,
            [
                {
                    "summary": "captured",
                    "raw_images": ["iVBORw0KGgo="],
                    "images": [],
                    "audios": [],
                }
            ],
            db_path=artifact_root,
        )
    fake_docs = _FakeDocsTool()
    tool = AnalyzeArtifactImageTool(
        artifact_root=str(artifact_root),
        llm=_FakeVisionModel(),
        robot_docs_tool=fake_docs,
    )

    first = tool._run(tool_call_id="call-1", question="Analyze first image")
    second = tool._run(tool_call_id="call-2", question="Analyze second image")

    assert fake_docs.queries == ["视觉检测要求"]
    assert "visible scene looks normal" in first
    assert "visible scene looks normal" in second


def test_analyze_artifact_image_does_not_cache_failed_requirements_query(
    tmp_path: Path,
):
    artifact_root = tmp_path / "data" / "artifacts"
    for call_id in ("call-1", "call-2"):
        store_artifacts(
            call_id,
            [
                {
                    "summary": "captured",
                    "raw_images": ["iVBORw0KGgo="],
                    "images": [],
                    "audios": [],
                }
            ],
            db_path=artifact_root,
        )
    failing_docs = _FailingDocsTool()
    tool = AnalyzeArtifactImageTool(
        artifact_root=str(artifact_root),
        llm=_FakeVisionModel(),
        robot_docs_tool=failing_docs,
    )

    tool._run(tool_call_id="call-1")
    tool._run(tool_call_id="call-2")

    assert failing_docs.calls == 2


def test_analyze_artifact_image_defaults_to_latest_artifact(tmp_path: Path):
    artifact_root = tmp_path / "data" / "artifacts"
    store_artifacts(
        "older-call",
        [{"summary": "captured", "raw_images": ["iVBORw0KGgo="], "images": [], "audios": []}],
        db_path=artifact_root,
    )
    store_artifacts(
        "newer-call",
        [{"summary": "captured", "raw_images": ["iVBORw0KGgo="], "images": [], "audios": []}],
        db_path=artifact_root,
    )
    os.utime(artifact_root / "newer-call" / "metadata.json", (2_000_000_000, 2_000_000_000))
    tool = AnalyzeArtifactImageTool(
        artifact_root=str(artifact_root),
        llm=_FakeVisionModel(),
    )

    result = tool._run()

    assert "tool_call_id=newer-call" in result


def test_analyze_artifact_image_tool_accepts_robot_docs_attachment(tmp_path: Path):
    artifact_root = tmp_path / "data" / "artifacts"
    store_artifacts(
        "call-1",
        [{"summary": "captured", "raw_images": ["iVBORw0KGgo="], "images": [], "audios": []}],
        db_path=artifact_root,
    )
    fake_docs = _FakeDocsTool()
    tool = AnalyzeArtifactImageTool(
        artifact_root=str(artifact_root),
        llm=_FakeVisionModel(),
    )
    tool.robot_docs_tool = fake_docs

    result = tool._run(tool_call_id="call-1")

    assert fake_docs.queries == ["视觉检测要求"]
    assert "visible scene looks normal" in result
