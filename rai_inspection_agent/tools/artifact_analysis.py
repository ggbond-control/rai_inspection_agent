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
            "Analyze this inspection image. Describe visible equipment, scene state, "
            "and any obvious anomalies. If there is insufficient visual evidence, say so."
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
        "and returns a text result; it does not persist image data in chat history."
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
        if not requirements:
            return question
        return (
            "Use the following robot documentation requirements as the inspection "
            "criteria for this image analysis.\n\n"
            f"## Visual Inspection Requirements\n{requirements}\n\n"
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
