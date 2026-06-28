import gc
import importlib.util
import json
import os
import sys
from importlib import metadata
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m backend.app.core.expert_runtime_worker <payload.json>")

    payload_path = Path(sys.argv[1]).resolve()
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    report_path = Path(payload["report_path"]).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "ok": False,
        "adapter_path": payload["adapter_path"],
        "base_model_path": payload["base_model_path"],
        "device": payload.get("device") or "auto",
        "dtype": payload.get("dtype") or "auto",
        "prompt": payload["prompt"],
        "prompts": payload.get("prompts") or [payload["prompt"]],
        "max_new_tokens": int(payload.get("max_new_tokens") or 48),
        "max_new_tokens_per_prompt": [int(item) for item in (payload.get("max_new_tokens_per_prompt") or [])],
        "repetition_penalty": float(payload.get("repetition_penalty") or 1.1),
        "no_repeat_ngram_size": int(payload.get("no_repeat_ngram_size") or 4),
        "packages": _package_versions(),
        "response_text": "",
        "responses": [],
        "error": "",
        "unloaded": False,
    }

    tokenizer = None
    model = None
    adapter_model = None
    try:
        _disable_unneeded_transformers_optional_imports()
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        base_model_path = str(Path(payload["base_model_path"]).resolve())
        adapter_path = str(Path(payload["adapter_path"]).resolve())
        dtype = _torch_dtype(torch, str(payload.get("dtype") or "auto"))
        quantization_config = _quantization_config(BitsAndBytesConfig)
        tokenizer = AutoTokenizer.from_pretrained(base_model_path, local_files_only=True, trust_remote_code=False)
        if tokenizer.pad_token is None and tokenizer.eos_token is not None:
            tokenizer.pad_token = tokenizer.eos_token
        model = AutoModelForCausalLM.from_pretrained(
            base_model_path,
            local_files_only=True,
            trust_remote_code=False,
            torch_dtype=dtype,
            quantization_config=quantization_config,
            **_load_kwargs(
                torch,
                device=str(payload.get("device") or "auto"),
                report_dir=report_path.parent,
                quantized=quantization_config is not None,
            ),
        )
        adapter_model = PeftModel.from_pretrained(
            model,
            adapter_path,
            is_trainable=False,
            local_files_only=True,
        )
        if quantization_config is None:
            target_device = _target_device(torch, str(payload.get("device") or "auto"))
            if target_device is not None:
                adapter_model = adapter_model.to(target_device)
        adapter_model.eval()
        model_device = next(adapter_model.parameters()).device
        responses = []
        for index, prompt in enumerate(report["prompts"]):
            inputs = _tokenize_prompt(tokenizer, str(prompt))
            inputs = {key: value.to(model_device) for key, value in inputs.items()}
            prompt_max_new_tokens = (
                int(report["max_new_tokens_per_prompt"][index])
                if index < len(report["max_new_tokens_per_prompt"])
                else int(payload.get("max_new_tokens") or 48)
            )
            generated = adapter_model.generate(
                **inputs,
                max_new_tokens=prompt_max_new_tokens,
                do_sample=False,
                repetition_penalty=max(1.0, float(report["repetition_penalty"])),
                no_repeat_ngram_size=max(0, int(report["no_repeat_ngram_size"])),
                pad_token_id=tokenizer.pad_token_id,
            )
            prompt_length = inputs["input_ids"].shape[-1]
            text = tokenizer.decode(generated[0][prompt_length:], skip_special_tokens=True).strip()
            responses.append({"prompt": str(prompt), "response_text": text})
        report["responses"] = responses
        report["response_text"] = responses[0]["response_text"] if responses else ""
        if not any(item["response_text"] for item in responses):
            raise RuntimeError("Adapter-backed generation returned empty responses.")
        report["ok"] = True
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        del adapter_model
        del model
        del tokenizer
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        report["unloaded"] = True

    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1


def _torch_dtype(torch_module, raw_dtype: str):
    value = raw_dtype.strip().lower()
    if value in {"", "auto"}:
        return "auto"
    if value == "float16":
        return torch_module.float16
    if value == "bfloat16":
        return torch_module.bfloat16
    if value == "float32":
        return torch_module.float32
    raise RuntimeError(f"Unsupported runtime dtype: {raw_dtype}")


def _device_map(raw_device: str):
    value = raw_device.strip().lower()
    if value in {"", "auto"}:
        return "auto"
    if value == "cpu":
        return {"": "cpu"}
    return {"": raw_device}


def _target_device(torch_module, raw_device: str) -> str | None:
    value = raw_device.strip().lower()
    if value == "cpu":
        return "cpu"
    if value in {"", "auto", "cuda"}:
        if torch_module.cuda.is_available():
            return "cuda"
        return None
    return raw_device


def _load_kwargs(torch_module, *, device: str, report_dir: Path, quantized: bool) -> dict:
    value = device.strip().lower()
    kwargs: dict = {}
    if quantized:
        kwargs = {"device_map": _device_map(device), "low_cpu_mem_usage": True}
        if value in {"", "auto", "cuda"} and torch_module.cuda.is_available():
            kwargs["device_map"] = "auto"
        return kwargs
    if value == "cpu":
        kwargs["device_map"] = {"": "cpu"}
    return kwargs


def _quantization_config(bits_and_bytes_config_cls):
    mode = os.environ.get("CML_LORA_RUNTIME_QUANTIZATION", "").strip().lower()
    if not mode or mode == "none":
        return None
    if mode not in {"4bit", "8bit"}:
        raise RuntimeError(f"Unsupported runtime quantization mode: {mode}")
    if mode == "8bit":
        return bits_and_bytes_config_cls(load_in_8bit=True)
    return bits_and_bytes_config_cls(
        load_in_4bit=True,
        bnb_4bit_compute_dtype="float16",
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
    )


def _tokenize_prompt(tokenizer, prompt: str) -> dict:
    chat_template = getattr(tokenizer, "chat_template", None)
    if chat_template:
        try:
            input_ids = tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                add_generation_prompt=True,
                return_tensors="pt",
            )
            import torch

            return {"input_ids": input_ids, "attention_mask": torch.ones_like(input_ids)}
        except Exception:
            pass
    return tokenizer(prompt, return_tensors="pt")


def _package_versions() -> dict[str, str | None]:
    packages: dict[str, str | None] = {}
    for name in ("torch", "transformers", "peft"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    return packages


def _disable_unneeded_transformers_optional_imports() -> None:
    blocked = {"sklearn", "pandas", "pyarrow"}
    real_find_spec = importlib.util.find_spec

    def find_spec_without_optional_generation_extras(name, *args, **kwargs):
        if str(name).split(".", 1)[0] in blocked:
            return None
        return real_find_spec(name, *args, **kwargs)

    importlib.util.find_spec = find_spec_without_optional_generation_extras


if __name__ == "__main__":
    raise SystemExit(main())
