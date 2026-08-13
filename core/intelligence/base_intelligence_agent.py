"""Base class for all intelligence layer agents.

Uses native LangGraph tool-calling when a cloud backend is active (OpenAI, Anthropic, xAI).
Falls back to a manual prompt-based ReAct loop for local Ollama models that don't
reliably support structured function calls.
"""

import json
import structlog
import re
from typing import Any, Dict, List, Optional

logger = structlog.get_logger(__name__)

try:
    from langgraph.prebuilt import create_react_agent
    from langchain_core.messages import HumanMessage
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False
    logger.warning(
        "langgraph/langchain-core not installed — intelligence agents will use "
        "prompt-based ReAct. Install with: pip install langgraph langchain-core"
    )

from core.llm.llm_interface import LLMBackend, get_llm

CLOUD_BACKENDS = {LLMBackend.OPENAI, LLMBackend.ANTHROPIC, LLMBackend.XAI}

REACT_SYSTEM_PROMPT = """You are a research intelligence assistant. Answer the user's request by
reasoning step-by-step and using the available tools.

Available tools:
{tool_descriptions}

Format EXACTLY like this (repeat Thought/Action/Observation until done):
Thought: <your reasoning>
Action: <tool_name>
Action Input: <JSON dict of arguments>
Observation: <tool result>
...
Final Answer: <your complete answer>

Only write "Final Answer:" when you have all the information you need."""

MAX_REACT_ITERATIONS = 6


class BackendAwareReActAgent:
    """
    Intelligence agent that adapts its ReAct strategy to the active LLM backend.

    Subclasses implement:
        - get_system_prompt() -> str
        - format_query(input_data) -> str
        - parse_result(final_answer: str, input_data) -> Dict
    """

    def __init__(self, llm_config: Optional[Dict] = None):
        self.llm = get_llm(llm_config)
        self._tools: List = []

    def set_tools(self, tools: List) -> None:
        self._tools = tools

    def get_system_prompt(self) -> str:
        raise NotImplementedError

    def format_query(self, input_data: Dict) -> str:
        raise NotImplementedError

    def parse_result(self, final_answer: str, input_data: Dict) -> Dict:
        raise NotImplementedError

    async def arun(self, input_data: Dict) -> Dict:
        """Run the agent and return structured output."""
        if LANGGRAPH_AVAILABLE and self._tools and self.llm.backend in CLOUD_BACKENDS:
            return await self._run_langgraph(input_data)
        return await self._run_react_loop(input_data)

    # ── LangGraph path (cloud backends with native function calling) ─────────

    async def _run_langgraph(self, input_data: Dict) -> Dict:
        try:
            llm_wrapper = self._build_langchain_llm()
            agent = create_react_agent(llm_wrapper, self._tools)
            query = self.format_query(input_data)
            system = self.get_system_prompt()
            result = await agent.ainvoke({"messages": [HumanMessage(content=f"{system}\n\n{query}")]})
            messages = result.get("messages", [])
            final_text = messages[-1].content if messages else ""
            return self.parse_result(final_text, input_data)
        except Exception as e:
            logger.error("langgraph_agent_error", exc_info=e)
            return await self._run_react_loop(input_data)

    def _build_langchain_llm(self):
        """Build a LangChain-compatible LLM wrapper from the active backend."""
        try:
            if self.llm.backend == LLMBackend.OPENAI:
                from langchain_openai import ChatOpenAI
                import os
                return ChatOpenAI(model=self.llm.model_name, api_key=os.environ.get("OPENAI_API_KEY"))
            elif self.llm.backend == LLMBackend.ANTHROPIC:
                from langchain_anthropic import ChatAnthropic
                import os
                return ChatAnthropic(model=self.llm.model_name, api_key=os.environ.get("ANTHROPIC_API_KEY"))
            elif self.llm.backend == LLMBackend.XAI:
                from langchain_openai import ChatOpenAI
                import os
                return ChatOpenAI(
                    model=self.llm.model_name,
                    api_key=os.environ.get("XAI_API_KEY"),
                    base_url="https://api.x.ai/v1",
                )
        except ImportError as e:
            logger.warning("langchain_wrapper_unavailable", error=str(e))
        return None

    # ── Manual ReAct loop (local Ollama / no function-calling support) ────────

    async def _run_react_loop(self, input_data: Dict) -> Dict:
        tool_map = {t.name if hasattr(t, "name") else t.__name__: t for t in self._tools}
        tool_descriptions = "\n".join(
            f"- {name}: {getattr(t, 'description', '')}"
            for name, t in tool_map.items()
        )

        system = REACT_SYSTEM_PROMPT.format(tool_descriptions=tool_descriptions)
        query = self.format_query(input_data)
        conversation = query

        for _ in range(MAX_REACT_ITERATIONS):
            response = await self.llm.generate(conversation, system_prompt=system)
            conversation += "\n" + response

            # Check for final answer
            if "Final Answer:" in response:
                final = response.split("Final Answer:", 1)[1].strip()
                return self.parse_result(final, input_data)

            # Parse and execute Action
            action_match = re.search(r"Action:\s*(\w+)", response)
            input_match = re.search(r"Action Input:\s*(\{.*?\})", response, re.DOTALL)

            if not action_match:
                break

            tool_name = action_match.group(1).strip()
            tool_input_str = input_match.group(1).strip() if input_match else "{}"

            try:
                tool_input = json.loads(tool_input_str)
            except json.JSONDecodeError:
                tool_input = {}

            tool_fn = tool_map.get(tool_name)
            if tool_fn:
                try:
                    if hasattr(tool_fn, "invoke"):
                        obs = tool_fn.invoke(tool_input)
                    else:
                        obs = tool_fn(**tool_input)
                except Exception as e:
                    obs = f"Error: {e}"
                conversation += f"\nObservation: {obs}"
            else:
                conversation += f"\nObservation: Tool '{tool_name}' not found."

        # If loop ends without final answer, do one last direct call without tools
        query_no_tools = self.format_query(input_data)
        direct = await self.llm.generate(query_no_tools, system_prompt=self.get_system_prompt())
        return self.parse_result(direct, input_data)
