from typing import Dict, Any, Optional
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ToolResult:
    """工具执行结果封装"""
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = self.data.copy()
        if self.error:
            result["error"] = self.error
        if self.metadata:
            result["_metadata"] = self.metadata
        return result


class BaseTool(ABC):
    """所有尖塔 Agent 工具的抽象基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称，供大模型识别"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具功能描述与调用指南"""
        pass

    @property
    @abstractmethod
    def parameters_schema(self) -> Dict[str, Any]:
        """JSON Schema 参数规范"""
        pass

    @abstractmethod
    def execute(self, params: Dict[str, Any], context: Any = None) -> ToolResult:
        """执行工具逻辑并返回 ToolResult"""
        pass

    def to_openai_tool(self) -> Dict[str, Any]:
        """导出符合 OpenAI / Gemini / DeepSeek 规范的 Tool Schema"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }
