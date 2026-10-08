"""路由决策的数据模型（结构化输出）"""

from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator


class RouteDecision(BaseModel):
    """路由决策（结构化输出）"""
    tier: Literal["fast", "balanced", "strong", "unknown", "out_of_scope"] = Field(
        description="模型档位：fast=快模型, balanced=中等, strong=强模型, unknown=无法识别, out_of_scope=领域外"
    )
    model: str = Field(description="具体模型名")
    max_tokens: int = Field(default=500, description="最大输出 token 数")
    temperature: float = Field(default=0.3, description="生成温度")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度")
    reason: str = Field(default="", description="路由理由")
    needs_clarification: bool = Field(default=False, description="是否需要追问用户")
    clarification_question: str = Field(default="", description="追问问题（needs_clarification=True 时）")
    intent: str = Field(default="balanced", description="识别的意图类型")
    # ── 结构化槽位（SLU：槽位填充部分）──
    slots: dict = Field(default_factory=dict, description="已抽取的槽位，如 {time:'上周', doc_type:'部署文档'}")
    missing_slots: list = Field(default_factory=list, description="缺失的必填槽位名")

    model_config = ConfigDict(use_enum_values=True)

    @field_validator("missing_slots")
    @classmethod
    def _coerce_missing(cls, v):
        """容忍上游误传 tuple/None，统一为 list[str]"""
        if not v:
            return []
        return [str(x) for x in v]
