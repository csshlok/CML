from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


MODEL_PATH = os.environ.get("LOCAL_QWEN_MODEL_PATH", r"T:\hf-models\Qwen2.5-3B-Instruct")
MODEL_ALIAS = os.environ.get("LOCAL_QWEN_MODEL_ALIAS", "qwen2.5-3b-instruct-4bit")
MAX_INPUT_TOKENS = int(os.environ.get("LOCAL_QWEN_MAX_INPUT_TOKENS", "16384"))
GPU_MEMORY = os.environ.get("LOCAL_QWEN_GPU_MEMORY", "5GiB")
CPU_MEMORY = os.environ.get("LOCAL_QWEN_CPU_MEMORY", "24GiB")
MAX_GENERATION_SECONDS = float(os.environ.get("LOCAL_QWEN_MAX_GENERATION_SECONDS", "60"))

_tokenizer = None
_model = None
_torch = None
_generation_lock = threading.Lock()


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = MODEL_ALIAS
    messages: list[ChatMessage]
    temperature: float = 0.0
    max_tokens: int = Field(default=160, ge=1, le=1024)
    n: int = Field(default=1, ge=1, le=1)
    stream: bool = False


def _load_model() -> None:
    global _model, _tokenizer, _torch
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    quantization = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)
    tokenizer.truncation_side = "left"
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_PATH,
        local_files_only=True,
        quantization_config=quantization,
        device_map="auto",
        max_memory={0: GPU_MEMORY, "cpu": CPU_MEMORY},
        low_cpu_mem_usage=True,
    )
    model.eval()
    _torch = torch
    _tokenizer = tokenizer
    _model = model


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _load_model()
    yield


app = FastAPI(title="Local Qwen OpenAI-compatible API", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ready" if _model is not None else "loading",
        "model": MODEL_ALIAS,
        "model_path": MODEL_PATH,
        "max_input_tokens": MAX_INPUT_TOKENS,
        "max_generation_seconds": MAX_GENERATION_SECONDS,
    }


@app.get("/v1/models")
def models() -> dict:
    return {
        "object": "list",
        "data": [{"id": MODEL_ALIAS, "object": "model", "owned_by": "local"}],
    }


@app.post("/v1/chat/completions")
def chat_completions(payload: ChatCompletionRequest) -> dict:
    if payload.stream:
        raise HTTPException(status_code=400, detail="Streaming is not supported by this benchmark server")
    if _model is None or _tokenizer is None or _torch is None:
        raise HTTPException(status_code=503, detail="Model is still loading")
    messages = [{"role": item.role, "content": item.content} for item in payload.messages]
    rendered = _tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = _tokenizer(
        rendered,
        return_tensors="pt",
        truncation=True,
        max_length=MAX_INPUT_TOKENS,
    ).to(_model.device)
    prompt_tokens = int(inputs["input_ids"].shape[1])
    started = time.perf_counter()
    with _generation_lock, _torch.inference_mode():
        output = _model.generate(
            **inputs,
            max_new_tokens=payload.max_tokens,
            max_time=MAX_GENERATION_SECONDS,
            do_sample=False,
            repetition_penalty=1.05,
            pad_token_id=_tokenizer.eos_token_id,
        )
    generated = output[0, prompt_tokens:]
    content = _tokenizer.decode(generated, skip_special_tokens=True).strip()
    completion_tokens = int(generated.shape[0])
    return {
        "id": f"chatcmpl-{uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": MODEL_ALIAS,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "benchmark": {"wall_seconds": round(time.perf_counter() - started, 4)},
    }
