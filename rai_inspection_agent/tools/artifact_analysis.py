from pathlib import Path
from typing import Any, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr
from rai import get_llm_model
from rai.messages import HumanMultimodalMessage, get_stored_artifacts


class AnalyzeArtifactImageInput(BaseModel):
    tool_call_id: str = Field(
        default="latest",
        description=(
            "Tool call id whose artifact images should be analyzed. "
            "Use latest to analyze the most recently stored artifact."
        ),
    )
    question: str = Field(
        default=(
            "Check the image against each retrieved visual inspection requirement. "
            "For every item, report its status and one brief visual reason, then give "
            "a short conclusion."
        ),
        description="Question or inspection instruction for the image analysis.",
    )
    max_images: int = Field(
        default=1,
        ge=1,
        description="Maximum number of artifact images to send to the vision model.",
    )


class AnalyzeArtifactImageTool(BaseTool):
    name: str = "analyze_artifact_image"
    description: str = (
        "Analyze image artifacts produced by previous tool calls. "
        "This reads image files from artifact storage only for this analysis step "
        "and returns a concise requirement-by-requirement Markdown checklist; "
        "it does not persist image data in chat history."
    )
    args_schema: Type[AnalyzeArtifactImageInput] = AnalyzeArtifactImageInput
    artifact_root: str = Field(default="data/artifacts")
    llm: Any | None = Field(default=None, exclude=True)
    robot_docs_tool: Any | None = Field(default=None, exclude=True)
    inspection_requirements_query: str = Field(default="视觉检测要求")
    _inspection_requirements_cache: str | None = PrivateAttr(default=None)
    _inspection_requirements_cache_query: str | None = PrivateAttr(default=None)

    def _run(
        self,
        tool_call_id: str = "latest",
        question: str = AnalyzeArtifactImageInput.model_fields["question"].default,
        max_images: int = 1,
    ) -> str:
        selected_tool_call_id = (
            self._latest_tool_call_id() if tool_call_id == "latest" else tool_call_id
        )
        if selected_tool_call_id is None:
            return "No artifact images are available to analyze."

        images = self._load_images(selected_tool_call_id)
        if not images:
            return f"No artifact images found for tool_call_id={selected_tool_call_id}."

        requirements = self._load_inspection_requirements()
        prompt = self._build_prompt(question, requirements)
        llm = self.llm or get_llm_model("complex_model", streaming=False)
        response = llm.invoke(
            [
                HumanMultimodalMessage(
                    content=prompt,
                    images=images[:max_images],
                )
            ]
        )
        response_content = getattr(response, "content", response)
        return (
            f"tool_call_id={selected_tool_call_id}\n"
            f"analyzed_images={min(len(images), max_images)}\n"
            f"analysis={response_content}"
        )

    def _load_inspection_requirements(self) -> str:
        if self.robot_docs_tool is None:
            return ""
        if (
            self._inspection_requirements_cache is not None
            and self._inspection_requirements_cache_query
            == self.inspection_requirements_query
        ):
            return self._inspection_requirements_cache
        try:
            result = self.robot_docs_tool.invoke(
                {"query": self.inspection_requirements_query}
            )
        except Exception as e:
            return f"(Could not retrieve visual inspection requirements: {type(e).__name__}: {e})"
        content = getattr(result, "content", result)
        requirements = str(content).strip()
        self._inspection_requirements_cache = requirements
        self._inspection_requirements_cache_query = self.inspection_requirements_query
        return requirements

    def _build_prompt(self, question: str, requirements: str) -> str:
        criteria = requirements or (
            "No visual inspection requirements were retrieved. Treat the user question "
            "as the only inspection item and state that the documented criteria were "
            "unavailable."
        )
        return (
            "Analyze the image only from visible evidence. Do not infer details that are "
            "not clearly shown.\n\n"
            "Extract every concrete inspection item from the requirements below and "
            "evaluate each item exactly once. Ignore document source labels, page numbers, "
            "retrieval rankings, repeated text, and explanatory prose. Do not omit, merge, "
            "or invent inspection items.\n\n"
            "Use exactly one of these statuses for every item:\n"
            "- 正常: the relevant target is visible and no problem is found.\n"
            "- 异常: visible evidence clearly shows a problem.\n"
            "- 无法判断: the target is obscured, blurred, too small, outside the view, "
            "or otherwise lacks sufficient evidence.\n"
            "- 不适用: the item does not apply to the visible scene, such as PPE when no "
            "person is present.\n\n"
            "Return only the following concise Markdown structure, in Chinese:\n\n"
            "## 检测结果\n"
            "- **<检测项>**：<正常|异常|无法判断|不适用> — <一句简短的可见依据>\n\n"
            "## 结论\n"
            "<最多两句：概括明确异常；如有无法判断项，说明需要补拍的内容。>\n\n"
            "Do not add an introduction, scene overview, detailed report, requirement "
            "restatement, or analysis process. Keep each item's evidence to one short "
            "sentence and the conclusion to at most two short sentences.\n\n"
            f"## Visual Inspection Requirements\n{criteria}\n\n"
            f"## User Question\n{question}"
        )

    def _latest_tool_call_id(self) -> str | None:
        root = Path(self.artifact_root)
        if not root.is_dir():
            return None
        candidates = [
            path for path in root.iterdir() if path.is_dir() and (path / "metadata.json").is_file()
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda path: (path / "metadata.json").stat().st_mtime)
        return latest.name

    def _load_images(self, tool_call_id: str) -> list[str]:
        artifacts = get_stored_artifacts(tool_call_id, db_path=self.artifact_root)
        images: list[str] = []
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            for key in ("raw_images", "images"):
                value = artifact.get(key, [])
                if isinstance(value, list):
                    images.extend([image for image in value if isinstance(image, str)])
        return images
