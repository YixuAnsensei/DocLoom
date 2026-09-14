"""Web API 的请求体模型（Pydantic）。"""

from pydantic import BaseModel


class ModifyBody(BaseModel):
    index: int
    instruction: str


class RunBody(BaseModel):
    index: int | None = None


class NewTaskBody(BaseModel):
    name: str
    template: str | None = None


class SaveTemplateBody(BaseModel):
    name: str
    description: str = ""
    force: bool = False


class ResearchBody(BaseModel):
    queries: list[str] = []
    chapter_index: int | None = None
    name: str = ""


class AddChapterBody(BaseModel):
    chapter: str
    prompt: str = ""


class MoveChapterBody(BaseModel):
    delta: int


class IngestBody(BaseModel):
    kind: str  # parse | extract-images | caption
