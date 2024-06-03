import logging
from typing import Dict, List, Any
from llama_index.core import Settings
from llama_index.llms.openai import OpenAI
from llama_index.llms.azure_openai import AzureOpenAI
from llama_index.llms.dashscope import DashScope
from pai_rag.integrations.llms.paieas.base import PaiEAS
from pai_rag.modules.base.configurable_module import ConfigurableModule
from pai_rag.modules.base.module_constants import MODULE_PARAM_CONFIG

logger = logging.getLogger(__name__)


class LlmModule(ConfigurableModule):
    @staticmethod
    def get_dependencies() -> List[str]:
        return []

    def _create_new_instance(self, new_params: Dict[str, Any]):
        config = new_params[MODULE_PARAM_CONFIG]
        source = config["source"].lower()
        if source == "openai":
            logger.info(
                f"""
                [Parameters][LLM:OpenAI]
                    model = {config.get("name", "gpt-3.5-turbo")},
                    temperature = {config.get("temperature", 0.5)},
                    system_prompt = {config.get("system_prompt", "Please answer in Chinese.")}
                """
            )
            llm = OpenAI(
                model=config.get("name", "gpt-3.5-turbo"),
                temperature=config.get("temperature", 0.5),
                system_prompt=config.get("system_prompt", "Please answer in Chinese."),
                api_key=config.get("api_key", None),
            )
        elif source == "azureopenai":
            logger.info(
                f"""
                [Parameters][LLM:AzureOpenAI]
                    model = {config.get("name", "gpt-35-turbo")},
                    temperature = {config.get("temperature", 0.5)},
                    system_prompt = {config.get("system_prompt", "Please answer in Chinese.")}
                """
            )
            llm = AzureOpenAI(
                model=config.get("name", "gpt-35-turbo"),
                temperature=config.get("temperature", 0.5),
                system_prompt=config.get("system_prompt", "Please answer in Chinese."),
            )
        elif source == "dashscope":
            model_name = config.get("name", "qwen-turbo")
            logger.info(
                f"""
                [Parameters][LLM:DashScope]
                    model = {model_name}
                """
            )
            llm = DashScope(model_name=model_name)
        elif source == "paieas":
            model_name = config["name"]
            endpoint = config["endpoint"]
            token = config["token"]
            logger.info(
                f"""
                [Parameters][LLM:PAI-EAS]
                    model = {model_name},
                    endpoint = {endpoint},
                    token = {token}
                """
            )
            llm = PaiEAS(endpoint=endpoint, token=token, model_name=model_name)
        else:
            raise ValueError(f"Unknown LLM source: '{config['llm']['source']}'")

        Settings.llm = llm
        return llm