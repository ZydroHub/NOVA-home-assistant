# FunctionGemma Pocket (Q4_K_M)

A 4-bit quantized GGUF model for **function/tool calling**, based on FunctionGemma and fine-tuned for a small set of tools (weather, web search, network scan). Optimized for edge and resource-constrained devices (e.g. Raspberry Pi) via llama.cpp.

---

## Model description

- **Format:** GGUF (Q4_K_M quantization)
- **Base:** FunctionGemma (Gemma-based model for function calling)
- **Purpose:** Map natural-language user queries to structured tool/function calls
- **Context length:** 2048 tokens (recommended)
- **Chat roles:** `developer`, `user`, `assistant`; assistant replies with tool calls in the form `<start_function_call>{"name": "...", "arguments": {...}}<end_function_call>`

Fine-tuning was done on ~1000 examples generated from a fixed tool schema so the model learns to select the right function and fill arguments from natural language.

---

## Intended use

- **In scope:** Choosing one of the supported tools and producing a single, well-formed function call (name + arguments) from a short user message.
- **Out of scope:** General chat, long-form generation, or tools not present in the training schema. Not intended for high-stakes or safety-critical decisions without human oversight.

---

## Supported tools (training schema)

| Tool | Description |
|------|-------------|
| `get_weather` | Weather or forecast for a location (`location`: string) |
| `web_search` | Web search for current info (`query`: string) |
| `network_scan` | Scan LAN for devices and open ports (no args) |

---

## Usage

### Download and load with llama-cpp-python

```python
from huggingface_hub import hf_hub_download
from llama_cpp import Llama

# Replace with your repo id, e.g. "your-username/functiongemma-pocket-q4_k_m"
REPO_ID = "YOUR_USERNAME/functiongemma-pocket-q4_k_m"
FILENAME = "functiongemma-pocket-q4_k_m.gguf"

path = hf_hub_download(repo_id=REPO_ID, filename=FILENAME)
llm = Llama(
    model_path=path,
    n_ctx=2048,
    n_threads=4,
    n_gpu_layers=-1,  # use GPU if available; 0 for CPU-only
    use_mmap=True,
    verbose=False,
)
```

### Function-calling example

```python
import json

tools = [
    {"type": "function", "function": {"name": "get_weather", "description": "Weather for a location.", "parameters": {"type": "object", "properties": {"location": {"type": "string"}}, "required": ["location"]}}},
    # ... add other tools in the same format
]

messages = [
    {"role": "developer", "content": "You are a model that can do function calling with the provided functions."},
    {"role": "user", "content": "What's the weather in Tokyo?"}
]

out = llm.create_chat_completion(
    messages=messages,
    tools=tools,
    max_tokens=128,
    temperature=0.1,
    stop=["<end_function_call>", "<eos>"],
)

# Parse assistant message for tool name and arguments
content = out["choices"][0]["message"].get("content", "")
# content may contain <start_function_call>{"name": "get_weather", "arguments": {"location": "Tokyo"}}<end_function_call>
```

---

## Training details

- **Data:** ~1000 synthetic examples mapping a user query to a single tool call, derived from the tool schema above.
- **Roles:** System-style instruction in `developer`, user query in `user`, target tool call in `assistant` with `tool_calls`.
- **Quantization:** Q4_K_M (4-bit) GGUF for smaller size and faster inference on CPU/edge.

---

## Limitations

- Trained only on the five tools listed; performance on other tools or schemas is undefined.
- Small model; may occasionally misselect the tool or omit/alter arguments.
- Not evaluated for safety or alignment beyond the described use case.

---

## License

Apache 2.0 (align with the base model's license when distributing).
