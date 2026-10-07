import os
import logging
from typing import Optional, Dict, Any, Tuple
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent
load_dotenv(project_root / ".env")
logger = logging.getLogger("spire_agent.config")


class LLMConfig:
    """LLM 配置管理器，统一适配 DeepSeek、Kimi、Gemini 等 OpenAI 兼容提供商"""

    PROVIDER_PRESETS: Dict[str, Dict[str, str]] = {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "default_model": "deepseek-chat",
            "env_key": "DEEPSEEK_API_KEY",
        },
        "kimi": {
            "base_url": "https://api.moonshot.cn/v1",
            "default_model": "moonshot-v1-8k",
            "env_key": "KIMI_API_KEY",
        },
        "gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "default_model": "gemini-2.0-flash",
            "env_key": "GEMINI_API_KEY",
        },
    }

    @classmethod
    def get_credentials(
        cls,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        prefix: str = "LLM",
    ) -> Tuple[str, str, str]:
        """
        获取当前激活的 (api_key, base_url, model)。
        支持区分战斗战术模型 (LLM) 与宏观长线战略模型 (MACRO_LLM)。
        优先级: 显式传参 > MACRO专属环境变量 (若为MACRO) > 对应提供商环境变量 > 通用环境变量
        """
        is_macro = prefix.upper().startswith("MACRO")

        # 1. 确定 Provider
        if provider:
            active_provider = provider.lower()
        elif is_macro and os.environ.get("MACRO_LLM_PROVIDER"):
            active_provider = os.environ.get("MACRO_LLM_PROVIDER", "").strip().lower()
        else:
            active_provider = os.environ.get("LLM_PROVIDER", "deepseek").strip().lower()

        preset = cls.PROVIDER_PRESETS.get(active_provider, {})

        # 2. 确定 API Key
        final_key = api_key
        if not final_key and is_macro:
            final_key = os.environ.get("MACRO_LLM_API_KEY") or os.environ.get("MACRO_API_KEY")
        if not final_key and preset.get("env_key"):
            final_key = os.environ.get(preset["env_key"])
        if not final_key:
            final_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")

        # 3. 确定 Base URL
        final_base_url = base_url
        if not final_base_url and is_macro:
            final_base_url = os.environ.get("MACRO_LLM_BASE_URL") or os.environ.get("MACRO_BASE_URL")
        if not final_base_url:
            env_url_key = f"{active_provider.upper()}_BASE_URL"
            final_base_url = os.environ.get(env_url_key, preset.get("base_url", "https://api.deepseek.com/v1"))

        # 4. 确定 Model
        final_model = model
        if not final_model and is_macro:
            final_model = os.environ.get("MACRO_LLM_MODEL") or os.environ.get("MACRO_MODEL")
        if not final_model:
            env_model_key = f"{active_provider.upper()}_MODEL"
            final_model = os.environ.get(env_model_key, preset.get("default_model", "deepseek-chat"))

        # 5. 代理检查
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

        role_desc = "宏观战略模型 (Macro)" if is_macro else "战斗战术模型 (Combat)"
        logger.info(
            f"加载 LLM 配置 [{role_desc}]: Provider={active_provider} | Model={final_model} | BaseURL={final_base_url} | Proxy={'已配置' if proxy else '未配置'}"
        )
        return final_key or "", final_base_url, final_model

    @classmethod
    def get_temperature(
        cls,
        model: str,
        explicit_temp: Optional[float] = None,
        prefix: str = "LLM",
    ) -> Optional[float]:
        """
        获取最适配当前模型的 temperature。
        某些模型（如 kimi-k2.7-code、deepseek-reasoner、o1/o3）严格限制 temperature 只能为 1 或不支持自定义。
        """
        if explicit_temp is not None:
            return explicit_temp

        is_macro = prefix.upper().startswith("MACRO")
        if is_macro:
            env_temp = os.environ.get("MACRO_LLM_TEMPERATURE") or os.environ.get("LLM_TEMPERATURE")
        else:
            env_temp = os.environ.get("LLM_TEMPERATURE")

        if env_temp is not None:
            try:
                return float(env_temp)
            except ValueError:
                pass

        m_lower = (model or "").lower()
        # kimi-k 系列或推理类模型通常强制要求 temperature=1.0 或不传
        if any(kw in m_lower for kw in ["kimi-k", "k2", "reasoner", "o1", "o3", "r1"]):
            return 1.0

        return 0.6 if is_macro else 0.3

    @classmethod
    def get_enable_tools(cls, explicit: Optional[bool] = None) -> bool:
        """获取是否开启工具调用模式 (默认 True)"""
        if explicit is not None:
            return explicit
        env_val = os.environ.get("ENABLE_TOOLS", "true").strip().lower()
        return env_val not in ("false", "0", "no", "off")

    @classmethod
    def get_enable_calculator(cls, explicit: Optional[bool] = None) -> bool:
        """获取是否向大模型暴露伤害与格挡试算器 (默认 True)"""
        if explicit is not None:
            return explicit
        env_val = os.environ.get("ENABLE_CALCULATOR", "true").strip().lower()
        return env_val not in ("false", "0", "no", "off")

