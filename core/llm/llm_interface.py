"""Local LLM integration layer with Ollama primary and transformers fallback.

Supports:
- Ollama (recommended): Easy setup, streaming responses
- Transformers: Direct Python integration, heavier memory
- OpenAI: Cloud API via openai package
- Anthropic: Cloud API via anthropic package
- xAI (Grok): OpenAI-compatible API via openai package + XAI_API_KEY
- Groq: Ultra-fast inference via openai package + GROQ_API_KEY
- Fallback chain: Ollama → Transformers → Template-based
"""

import asyncio
import structlog
from typing import Optional, Dict, Any, List, AsyncIterator
from enum import Enum
import json

import re

logger = structlog.get_logger(__name__)

_THINK_CLOSED_RE = re.compile(r'<think>.*?</think>', re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r'<think>.*$', re.DOTALL | re.IGNORECASE)


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> reasoning blocks from reasoning models (Qwen3, DeepSeek-R1, etc.).

    Handles both closed blocks and truncated blocks (model hit max_tokens inside <think>).
    """
    text = _THINK_CLOSED_RE.sub('', text)
    text = _THINK_OPEN_RE.sub('', text)
    return text.strip()

# Ollama support (optional)
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

# Transformers support
try:
    from transformers import AutoTokenizer, AutoModelForCausalLM
    import torch
    TRANSFORMERS_AVAILABLE = True
except (ImportError, ValueError, Exception):
    TRANSFORMERS_AVAILABLE = False

# OpenAI support (optional — pip install openai)
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# Anthropic support (optional — pip install anthropic)
try:
    from anthropic import AsyncAnthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


class LLMBackend(Enum):
    """Available LLM backends."""
    OLLAMA = "ollama"
    TRANSFORMERS = "transformers"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    XAI = "xai"
    GROQ = "groq"
    TEMPLATE = "template"


class LocalLLM:
    """
    Unified interface for local LLM inference.
    
    Priority order:
    1. Ollama (if configured and available)
    2. Transformers (if model specified)
    3. Template-based fallback
    """
    
    def __init__(
        self,
        backend: str = "ollama",
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7
    ):
        """
        Initialize LLM interface.
        
        Args:
            backend: 'ollama', 'transformers', or 'auto'
            model_name: Model identifier
                - Ollama: 'qwen2.5:3b', 'phi3:mini', etc.
                - Transformers: 'microsoft/phi-3-mini-4k-instruct', etc.
            device: 'cuda' or 'cpu' (auto-detected if None)
            max_tokens: Maximum generation length
            temperature: Sampling temperature
        """
        import os
        # PAPERMIND_LLM_BACKEND selects the backend family; defaults to ollama
        self.backend_name = os.environ.get('PAPERMIND_LLM_BACKEND', backend)
        # env var override → explicit arg → default
        self.model_name = (
            os.environ.get('PAPERMIND_LLM_MODEL')
            or model_name
            or 'qwen2.5:3b'
        )
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._openai_client: Optional['AsyncOpenAI'] = None
        self._anthropic_client: Optional['AsyncAnthropic'] = None
        self._xai_client: Optional['AsyncOpenAI'] = None
        self._groq_client: Optional['AsyncOpenAI'] = None
        
        if device is None:
            if TRANSFORMERS_AVAILABLE:
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            else:
                self.device = "cpu"
        else:
            self.device = device
        
        self.backend: Optional[LLMBackend] = None
        self.model = None
        self.tokenizer = None
        
        # Try to initialize
        self._initialize()
    
    def _initialize(self):
        """Initialize the configured backend, trying in priority order."""
        if self.backend_name == "openai":
            if self._init_openai():
                return
        elif self.backend_name == "anthropic":
            if self._init_anthropic():
                return
        elif self.backend_name == "xai":
            if self._init_xai():
                return
        elif self.backend_name == "groq":
            if self._init_groq():
                return
        elif self.backend_name in ("ollama", "auto"):
            if self._init_ollama():
                return
        elif self.backend_name == "transformers":
            if self._init_transformers():
                return

        # auto: try remaining backends in order
        if self.backend_name == "auto":
            for init_fn in (self._init_groq, self._init_xai, self._init_openai, self._init_anthropic, self._init_transformers):
                if init_fn():
                    return

        logger.warning("no_llm_backend_available", using="template_based_generation")
        self.backend = LLMBackend.TEMPLATE
    
    def _init_ollama(self) -> bool:
        """Initialize Ollama backend."""
        if not OLLAMA_AVAILABLE:
            logger.warning("ollama_not_installed", instruction="pip install ollama")
            return False
        
        try:
            # Check if Ollama server is running and model exists
            result = ollama.list()
            model_names = [m.model for m in result.models] if hasattr(result, 'models') else []

            # If the env-var / default model isn't pulled, try the smaller fallback
            preferred = self.model_name
            fallback = 'qwen2.5:3b'
            chosen = None
            for candidate in [preferred, fallback]:
                if any(candidate in name for name in model_names):
                    chosen = candidate
                    break

            if chosen is None:
                logger.error(
                    "ollama_model_not_found",
                    model=preferred,
                    instruction=f"ollama pull {preferred}"
                )
                return False

            self.model_name = chosen
            self.backend = LLMBackend.OLLAMA
            logger.info("ollama_initialized", model=self.model_name)
            return True
            
        except Exception as e:
            logger.exception("ollama_init_failed", error=str(e), instruction="ollama serve")
            return False
    
    def _init_transformers(self) -> bool:
        """Initialize Transformers backend."""
        if not TRANSFORMERS_AVAILABLE:
            logger.warning("transformers_not_available")
            return False
        
        try:
            logger.info("loading_transformer_model", model=self.model_name)
            
            self.tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                trust_remote_code=True
            )
            
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                torch_dtype=torch.float16 if self.device == "cuda" else torch.float32,
                device_map="auto" if self.device == "cuda" else None,
                trust_remote_code=True,
                low_cpu_mem_usage=True
            )
            
            if self.device == "cpu":
                self.model = self.model.to(self.device)
            
            self.backend = LLMBackend.TRANSFORMERS
            logger.info("transformers_initialized", model=self.model_name, device=self.device)
            return True
            
        except Exception as e:
            logger.exception("transformers_init_failed", error=str(e))
            return False
    
    def _init_openai(self) -> bool:
        """Initialize OpenAI backend."""
        import os
        if not OPENAI_AVAILABLE:
            logger.warning("openai_not_installed", instruction="pip install openai")
            return False
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            logger.warning("openai_api_key_missing", instruction="set OPENAI_API_KEY env var")
            return False
        self._openai_client = AsyncOpenAI(api_key=api_key)
        self.model_name = os.environ.get('PAPERMIND_LLM_MODEL', 'gpt-4o-mini')
        self.backend = LLMBackend.OPENAI
        logger.info("openai_initialized", model=self.model_name)
        return True

    def _init_anthropic(self) -> bool:
        """Initialize Anthropic backend."""
        import os
        if not ANTHROPIC_AVAILABLE:
            logger.warning("anthropic_not_installed", instruction="pip install anthropic")
            return False
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            logger.warning("anthropic_api_key_missing", instruction="set ANTHROPIC_API_KEY env var")
            return False
        self._anthropic_client = AsyncAnthropic(api_key=api_key)
        self.model_name = os.environ.get('PAPERMIND_LLM_MODEL', 'claude-haiku-4-5-20251001')
        self.backend = LLMBackend.ANTHROPIC
        logger.info("anthropic_initialized", model=self.model_name)
        return True

    def _init_xai(self) -> bool:
        """Initialize xAI (Grok) backend using OpenAI-compatible API."""
        import os
        if not OPENAI_AVAILABLE:
            logger.warning("openai_not_installed", instruction="pip install openai")
            return False
        api_key = os.environ.get('XAI_API_KEY')
        if not api_key:
            logger.warning("xai_api_key_missing", instruction="set XAI_API_KEY env var")
            return False
        self._xai_client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
        )
        self.model_name = os.environ.get('PAPERMIND_LLM_MODEL', 'grok-beta')
        self.backend = LLMBackend.XAI
        logger.info("xai_initialized", model=self.model_name)
        return True

    def _init_groq(self) -> bool:
        """Initialize Groq backend using OpenAI-compatible API."""
        import os
        if not OPENAI_AVAILABLE:
            logger.warning("openai_not_installed", instruction="pip install openai")
            return False
        api_key = os.environ.get('GROQ_API_KEY')
        if not api_key:
            logger.warning("groq_api_key_missing", instruction="set GROQ_API_KEY env var")
            return False
        self._groq_client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        self.model_name = os.environ.get('PAPERMIND_LLM_MODEL', 'llama-3.3-70b-versatile')
        self.backend = LLMBackend.GROQ
        logger.info("groq_initialized", model=self.model_name)
        return True

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stop_sequences: Optional[List[str]] = None
    ) -> str:
        """
        Generate text from prompt.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system instruction
            max_tokens: Override default max tokens
            temperature: Override default temperature
            stop_sequences: Sequences to stop generation
        
        Returns:
            Generated text
        """
        max_tokens = max_tokens or self.max_tokens
        temperature = temperature or self.temperature
        
        if self.backend == LLMBackend.OPENAI:
            return await self._generate_openai(prompt, system_prompt, max_tokens, temperature)
        elif self.backend == LLMBackend.ANTHROPIC:
            return await self._generate_anthropic(prompt, system_prompt, max_tokens, temperature)
        elif self.backend == LLMBackend.XAI:
            return await self._generate_openai(
                prompt, system_prompt, max_tokens, temperature, client=self._xai_client
            )
        elif self.backend == LLMBackend.GROQ:
            return await self._generate_openai(
                prompt, system_prompt, max_tokens, temperature, client=self._groq_client
            )
        elif self.backend == LLMBackend.OLLAMA:
            return await self._generate_ollama(prompt, system_prompt, max_tokens, temperature)
        elif self.backend == LLMBackend.TRANSFORMERS:
            return await self._generate_transformers(prompt, system_prompt, max_tokens, temperature, stop_sequences)
        else:
            return self._generate_template(prompt)
    
    async def _generate_ollama(
        self,
        prompt: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float
    ) -> str:
        """Generate using Ollama."""
        try:
            messages = []
            if system_prompt:
                messages.append({'role': 'system', 'content': system_prompt})
            messages.append({'role': 'user', 'content': prompt})
            
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: ollama.chat(
                    model=self.model_name,
                    messages=messages,
                    options={
                        'num_predict': max_tokens,
                        'num_ctx': 4096,
                        'temperature': temperature
                    }
                )
            )
            
            return _strip_think_tags(response['message']['content'])

        except Exception as e:
            logger.exception("ollama_generation_error", error=str(e), fallback="template")
            return self._generate_template(prompt)
    
    # Reasoning models that emit <think> blocks — we disable thinking via API param when possible.
    _REASONING_MODELS = frozenset({
        'qwen/qwen3-32b', 'qwen/qwen3-8b', 'qwen/qwen3-14b', 'qwen/qwen3-72b',
        'qwq-32b', 'deepseek-r1', 'deepseek-r1-distill-llama-70b',
    })

    async def _generate_openai(
        self,
        prompt: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
        client: Optional['AsyncOpenAI'] = None,
    ) -> str:
        """Generate using OpenAI-compatible API (also used by xAI/Grok)."""
        try:
            active_client = client or self._openai_client
            messages = []
            if system_prompt:
                messages.append({'role': 'system', 'content': system_prompt})
            messages.append({'role': 'user', 'content': prompt})

            extra_body: dict = {}
            # Groq supports reasoning_format to suppress <think> tokens for reasoning models
            if active_client is self._groq_client and self.model_name in self._REASONING_MODELS:
                extra_body['reasoning_format'] = 'hidden'

            response = await active_client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **({"extra_body": extra_body} if extra_body else {}),
            )
            raw = response.choices[0].message.content or ''
            return _strip_think_tags(raw)
        except Exception as e:
            logger.exception("openai_generation_error", error=str(e), fallback="template")
            return self._generate_template(prompt)

    async def _generate_anthropic(
        self,
        prompt: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Generate using Anthropic API."""
        try:
            kwargs: dict = dict(
                model=self.model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{'role': 'user', 'content': prompt}],
            )
            if system_prompt:
                kwargs['system'] = system_prompt

            response = await self._anthropic_client.messages.create(**kwargs)
            raw = response.content[0].text if response.content else ''
            return _strip_think_tags(raw)
        except Exception as e:
            logger.exception("anthropic_generation_error", error=str(e), fallback="template")
            return self._generate_template(prompt)

    async def _generate_transformers(
        self,
        prompt: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
        stop_sequences: Optional[List[str]]
    ) -> str:
        """Generate using Transformers."""
        try:
            # Format prompt with system instruction
            if system_prompt:
                full_prompt = f"{system_prompt}\n\n{prompt}"
            else:
                full_prompt = prompt
            
            # Tokenize
            inputs = self.tokenizer(
                full_prompt,
                return_tensors="pt",
                truncation=True,
                max_length=2048
            ).to(self.device)
            
            # Generate in executor
            loop = asyncio.get_event_loop()
            
            def _generate():
                with torch.no_grad():
                    outputs = self.model.generate(
                        **inputs,
                        max_new_tokens=max_tokens,
                        temperature=temperature,
                        do_sample=temperature > 0,
                        pad_token_id=self.tokenizer.eos_token_id
                    )
                return self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            
            generated = await loop.run_in_executor(None, _generate)
            
            # Remove prompt from output
            if generated.startswith(full_prompt):
                generated = generated[len(full_prompt):].strip()
            
            return generated
            
        except Exception as e:
            logger.exception("transformers_generation_error", error=str(e), fallback="template")
            return self._generate_template(prompt)
    
    def _generate_template(self, prompt: str) -> str:
        """Template-based fallback (no LLM)."""
        # Extract key information from prompt for basic template
        if "summarize" in prompt.lower():
            return "This paper presents a novel approach to the problem. The method demonstrates improved performance over baselines."
        elif "contributions" in prompt.lower():
            return "The main contributions include a new methodology and experimental validation."
        else:
            return "Analysis complete. See extracted data for details."
    
    async def stream_generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None
    ) -> AsyncIterator[str]:
        """
        Generate text with streaming (Ollama only currently).
        
        Yields:
            Text chunks as they're generated
        """
        if self.backend != LLMBackend.OLLAMA:
            # Non-streaming fallback
            result = await self.generate(prompt, system_prompt)
            yield result
            return
        
        try:
            messages = []
            if system_prompt:
                messages.append({'role': 'system', 'content': system_prompt})
            messages.append({'role': 'user', 'content': prompt})
            
            # Ollama streaming
            stream = ollama.chat(
                model=self.model_name,
                messages=messages,
                stream=True
            )
            
            for chunk in stream:
                if 'message' in chunk and 'content' in chunk['message']:
                    yield chunk['message']['content']
                    
        except Exception as e:
            logger.exception("streaming_error", error=str(e), fallback="template")
            yield self._generate_template(prompt)
    
    def get_info(self) -> Dict[str, Any]:
        """Get LLM backend information."""
        return {
            'backend': self.backend.value if self.backend else 'none',
            'model_name': self.model_name,
            'device': self.device,
            'max_tokens': self.max_tokens,
            'temperature': self.temperature,
            'available_backends': {
                'ollama': OLLAMA_AVAILABLE,
                'transformers': TRANSFORMERS_AVAILABLE,
                'openai': OPENAI_AVAILABLE,
                'anthropic': ANTHROPIC_AVAILABLE,
                'xai': OPENAI_AVAILABLE,   # xAI reuses the openai package
                'groq': OPENAI_AVAILABLE,  # Groq reuses the openai package
            },
        }


# Singleton instance
_llm_instance: Optional[LocalLLM] = None


def get_llm(config: Optional[Dict[str, Any]] = None) -> LocalLLM:
    """
    Get global LLM instance.
    
    Args:
        config: Optional config dict with:
            - backend: 'ollama' or 'transformers'
            - model_name: Model identifier
            - device: 'cuda' or 'cpu'
            - max_tokens: Max generation length
            - temperature: Sampling temperature
    
    Returns:
        LocalLLM instance
    """
    global _llm_instance
    
    if _llm_instance is None:
        if config:
            _llm_instance = LocalLLM(**config)
        else:
            _llm_instance = LocalLLM()
    
    return _llm_instance
