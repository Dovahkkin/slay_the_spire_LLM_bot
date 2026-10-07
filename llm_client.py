import os
import json
import logging
from typing import List, Dict, Any, Optional
import httpx
from openai import OpenAI

from config import LLMConfig
from spire_agent.tools import SpireToolRegistry, ToolResult

logger = logging.getLogger("spire_agent.llm_client")


class SpireLLMClient:
    """
    通用大模型客户端与 ReAct 交互引擎（参考 coding-agent 实现）
    原生支持 DeepSeek-V3/R1、Kimi、Google Gemini（OpenAI 兼容端点）。
    支持标准的 Tool Calling / Function Calling 思考与执行闭环。
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        enable_tools: bool = True,
        enable_calculator: bool = True,
        enable_monster_tool: bool = False,
        tool_registry: Optional[SpireToolRegistry] = None,
        config_prefix: str = "LLM",
    ):
        self.config_prefix = config_prefix
        self.api_key, self.base_url, self.model = LLMConfig.get_credentials(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            prefix=config_prefix,
        )
        self.temperature = LLMConfig.get_temperature(self.model, temperature, prefix=config_prefix)
        self.enable_tools = enable_tools
        self.enable_calculator = enable_calculator
        self.enable_monster_tool = enable_monster_tool
        self.tool_registry = tool_registry or SpireToolRegistry(
            enable_calculator=enable_calculator,
            enable_all_tools=enable_tools,
            enable_monster_tool=enable_monster_tool,
        )
        self.client: Optional[OpenAI] = None

        if self.api_key:
            client_kwargs: Dict[str, Any] = {
                "api_key": self.api_key,
                "base_url": self.base_url,
            }
            # 代理支持
            proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
            if proxy:
                client_kwargs["http_client"] = httpx.Client(proxy=proxy)
                logger.info(f"LLM 客户端挂载代理: {proxy}")

            self.client = OpenAI(**client_kwargs)
            role_desc = "宏观战略" if config_prefix.upper().startswith("MACRO") else "战斗战术"
            logger.info(
                f"[{role_desc}] LLM 客户端初始化成功: Model={self.model} | Endpoint={self.base_url} | Temp={self.temperature}"
            )
        else:
            logger.warning(f"[{config_prefix}] 未检测到 API Key，LLM 客户端处于离线兜底状态。")

    @property
    def is_available(self) -> bool:
        return self.client is not None and bool(self.api_key)

    def _call_completion_with_auto_heal(self, kwargs: Dict[str, Any]):
        """执行 API 请求，并在遇到特定模型的参数限制时自动自愈并重试"""
        try:
            return self.client.chat.completions.create(**kwargs)
        except Exception as e:
            err_msg = str(e).lower()
            # 1. 自动适配 Kimi / DeepSeek 等模型的 temperature=1 限制
            if "invalid temperature" in err_msg or "only 1 is allowed" in err_msg:
                logger.warning(f"检测到模型 {self.model} 限制 temperature 必须为 1，自动自愈调整为 1.0 重新请求...")
                self.temperature = 1.0
                kwargs["temperature"] = 1.0
                return self.client.chat.completions.create(**kwargs)

            # 2. 自动移除不支持的 temperature 参数
            if "temperature" in err_msg and ("unsupported" in err_msg or "not allowed" in err_msg):
                logger.warning(f"检测到模型 {self.model} 不支持 temperature 参数，自动移除重新请求...")
                self.temperature = None
                kwargs.pop("temperature", None)
                return self.client.chat.completions.create(**kwargs)

            # 3. 自动降级处理不支持 tools 的模型
            if "tool" in err_msg and ("not supported" in err_msg or "unsupported" in err_msg):
                logger.warning(f"检测到模型 {self.model} 不支持工具调用 (Function Calling)，降级为纯文本思考模式...")
                kwargs.pop("tools", None)
                kwargs.pop("tool_choice", None)
                return self.client.chat.completions.create(**kwargs)

            raise e

    def run_react_turn(
        self,
        messages: List[Dict[str, Any]],
        context: Any = None,
        max_iterations: int = 5,
        enable_tools: bool = True,
    ) -> str:
        """
        执行 ReAct 思考与工具调用循环：
        1. 携带战场信息与 Tool Schema 发送给大模型；
        2. 若大模型发起 tool_calls（如试算伤害、查怪物机制），本地执行并将结果追加到上下文中；
        3. 继续呼叫大模型，直至大模型完成推演并输出最终回复。
        """
        if not self.is_available:
            return ""

        cur_messages = list(messages)
        tools = self.tool_registry.get_openai_tools() if (enable_tools and self.enable_tools) else None
        effective_max_iterations = max_iterations if tools else 1

        for iteration in range(effective_max_iterations):
            try:
                kwargs: Dict[str, Any] = {
                    "model": self.model,
                    "messages": cur_messages,
                }
                if self.temperature is not None:
                    kwargs["temperature"] = self.temperature

                if tools:
                    kwargs["tools"] = tools
                    kwargs["tool_choice"] = "auto"

                response = self._call_completion_with_auto_heal(kwargs)
                choice = response.choices[0]
                msg = choice.message

                # 检查大模型是否需要调用工具
                if msg.tool_calls:
                    logger.info(f"[ReAct Iter #{iteration + 1}] 模型调用了 {len(msg.tool_calls)} 个本地工具...")

                    # 1. 先将 assistant 的 tool_calls 消息加入上下文
                    tool_calls_data = []
                    for tc in msg.tool_calls:
                        tool_calls_data.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        })

                    cur_messages.append({
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": tool_calls_data,
                    })

                    # 2. 依次执行各个工具并将结果作为 tool 角色消息追加
                    for tc in msg.tool_calls:
                        func_name = tc.function.name
                        try:
                            func_args = json.loads(tc.function.arguments or "{}")
                        except Exception:
                            func_args = {}

                        logger.info(f"--> 执行工具 [{func_name}]: {func_args}")
                        tool_res: ToolResult = self.tool_registry.execute_tool(
                            func_name, func_args, context=context
                        )

                        cur_messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(tool_res.to_dict(), ensure_ascii=False),
                        })

                    # 继续下一次迭代，让大模型阅读工具执行结果
                    continue

                # 无工具调用，推演完毕，返回最终文本
                final_content = msg.content or ""
                return final_content

            except Exception as e:
                logger.error(f"LLM 交互异常: {e}")
                return ""

        logger.warning(f"达到 ReAct 最大迭代次数 ({max_iterations})，返回最后已知输出。")
        return ""
