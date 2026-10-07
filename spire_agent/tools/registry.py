from typing import Dict, Any, List, Optional
from .base import BaseTool, ToolResult
from .calculator import DamageCalculatorTool
from .monster_tool import MonsterDossierTool


class SpireToolRegistry:
    """
    尖塔 Agent 工具注册表（参考 coding-agent 架构设计）
    统一管理所有本地 Python 算力与知识工具，支持向大模型导出 Tool Schema 并安全分发调用。
    """

    def __init__(
        self,
        enable_calculator: bool = True,
        enable_all_tools: bool = True,
        enable_monster_tool: bool = False,
    ):
        self._tools: Dict[str, BaseTool] = {}
        self.enable_calculator = enable_calculator
        self.enable_all_tools = enable_all_tools
        self.enable_monster_tool = enable_monster_tool
        self._register_default_tools()

    def _register_default_tools(self):
        if not self.enable_all_tools:
            return

        tools = []
        if self.enable_calculator:
            tools.append(DamageCalculatorTool())
        if self.enable_monster_tool:
            tools.append(MonsterDossierTool())

        for t in tools:
            self._tools[t.name] = t

    def get_tool(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """导出所有注册工具的 OpenAI / Gemini / DeepSeek 规范 Tool Schema"""
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def execute_tool(self, name: str, params: Dict[str, Any], context: Any = None) -> ToolResult:
        tool = self.get_tool(name)
        if not tool:
            return ToolResult(success=False, data={}, error=f"未知工具: {name}")
        try:
            return tool.execute(params, context=context)
        except Exception as e:
            return ToolResult(success=False, data={}, error=f"工具执行异常: {str(e)}")
