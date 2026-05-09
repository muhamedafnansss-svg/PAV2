"""
VAL Model Governor
==================
Singleton to manage loading, streaming, and unloading models.
Optimized for 8GB VRAM (RTX 4070) with BitsAndBytes 4-bit quantization.
"""

import os
import gc
import torch
import time
import asyncio
from typing import AsyncIterator, Optional, List, Dict, Any
from val.utils.logger import get_logger, LogCategory
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from transformers import TextIteratorStreamer
from threading import Thread

logger = get_logger("val.models.governor", LogCategory.SYSTEM)

DEFAULT_MODEL = os.environ.get("VAL_DEFAULT_MODEL", "qwen")

_MODEL_MAP = {
    "qwen": "Qwen/Qwen2.5-Coder-7B-Instruct",
    "mistral": "mistralai/Mistral-7B-Instruct-v0.3",
    "tinyllama": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
}

class Governor:
    def __init__(self):
        self._active_model = None
        self._model = None
        self._tokenizer = None
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._lock = asyncio.Lock()
        self._force_model = None

    @property
    def active_model(self) -> Optional[str]:
        return self._active_model

    def configure(self, force_model: Optional[str] = None):
        self._force_model = force_model

    async def force_unload(self, reason: str = "manual"):
        logger.info(f"[Governor] Unloading {self._active_model} (Reason: {reason})")
        async with self._lock:
            if self._model is not None:
                del self._model
            if self._tokenizer is not None:
                del self._tokenizer
            self._model = None
            self._tokenizer = None
            self._active_model = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    async def load(self, model_name: str) -> bool:
        model_name = self._force_model or model_name or DEFAULT_MODEL
        if self._active_model == model_name:
            return True

        async with self._lock:
            # Unload existing
            if self._model is not None:
                del self._model
                del self._tokenizer
                self._model = None
                self._tokenizer = None
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                gc.collect()

            target_repo = _MODEL_MAP.get(model_name, model_name)
            logger.info(f"[Governor] Loading model: {target_repo} into {self._device}")

            try:
                # 4-bit quantization config for 8GB VRAM
                bnb_config = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                )

                loop = asyncio.get_running_loop()

                # Load tokenizer and model in separate thread to avoid blocking loop
                def _do_load():
                    tok = AutoTokenizer.from_pretrained(target_repo, trust_remote_code=True)
                    mod = AutoModelForCausalLM.from_pretrained(
                        target_repo,
                        device_map="auto" if self._device == "cuda" else None,
                        quantization_config=bnb_config if self._device == "cuda" else None,
                        trust_remote_code=True,
                        torch_dtype=torch.float16 if self._device == "cuda" else torch.float32,
                        low_cpu_mem_usage=True
                    )
                    return tok, mod

                self._tokenizer, self._model = await loop.run_in_executor(None, _do_load)
                self._active_model = model_name
                logger.info(f"[Governor] Model {model_name} loaded successfully.")
                return True
            except Exception as e:
                logger.error(f"[Governor] Failed to load model {model_name}: {e}")
                return False

    async def stream(self, prompt: str, history: List[dict] = None, model_hint: str = None) -> AsyncIterator[str]:
        target_model = self._force_model or model_hint or self._active_model or DEFAULT_MODEL
        if self._active_model != target_model:
            ok = await self.load(target_model)
            if not ok:
                yield "Error: Could not load model."
                return

        # Prepare inputs
        inputs = self._tokenizer(prompt, return_tensors="pt")
        if self._device == "cuda":
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

        streamer = TextIteratorStreamer(self._tokenizer, skip_prompt=True, skip_special_tokens=True)
        generation_kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=512,
            temperature=0.6,
            top_p=0.9,
            repetition_penalty=1.1,
            pad_token_id=self._tokenizer.eos_token_id
        )

        loop = asyncio.get_running_loop()
        thread = Thread(target=self._model.generate, kwargs=generation_kwargs)
        thread.start()

        for chunk in streamer:
            yield chunk
            await asyncio.sleep(0)  # Yield control

    def generate(self, messages: List[dict], max_new_tokens: int = 512, temperature: float = 0.6) -> str:
        # Synchronous generation
        if not self._model:
            return ""

        prompt = ""
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            prompt += f"{role.capitalize()}: {content}\n"
        prompt += "Assistant: "

        inputs = self._tokenizer(prompt, return_tensors="pt")
        if self._device == "cuda":
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

        outputs = self._model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            pad_token_id=self._tokenizer.eos_token_id
        )
        return self._tokenizer.decode(outputs[0][inputs['input_ids'].shape[1]:], skip_special_tokens=True).strip()

    def status(self) -> dict:
        return {
            "active_model": self._active_model,
            "device": self._device,
            "force_model": self._force_model,
        }

_governor = None
def get_governor() -> Governor:
    global _governor
    if _governor is None:
        _governor = Governor()
    return _governor

def model_path_exists(model_name: str = None) -> bool:
    return True # We use huggingface caching, so we assume true if valid name

tools_pool = {} # Dummy tools pool if accessed directly
