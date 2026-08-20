import json
import os
import time
from llama_cpp import Llama

# 1. Model Configuration
MODEL_PATH = "./models/functiongemma-pocket-q4_k_m.gguf"

if not os.path.exists(MODEL_PATH):
    print(f"Error: Model not found at {MODEL_PATH}")
    exit(1)

# 2. Performance Settings
PERF = {
    "n_ctx": 2048,           # Context length (tokens)
    "n_threads": 4,          # CPU threads for inference
    "n_threads_batch": 4,    # CPU threads for batch (prompt) processing
    "n_batch": 512,          # Prompt batch size; larger = faster prompt eval, more RAM
    "n_gpu_layers": -1,      # -1 = offload all layers to GPU if available; 0 = CPU only
    "use_mmap": True,       # Memory-map weights for faster load and lower RAM use
    "use_mlock": False,     # Lock model in RAM (can OOM on small devices)
    "verbose": False,
}
# Generation (create_chat_completion)
GEN_PERF = {
    "max_tokens": 128,
    "temperature": 0.1,
}

# 3. Initialize Model
print(f"Loading FunctionGemma model: {MODEL_PATH}...")
llm = Llama(
    model_path=MODEL_PATH,
    n_ctx=PERF["n_ctx"],
    n_threads=PERF["n_threads"],
    n_threads_batch=PERF["n_threads_batch"],
    n_batch=PERF["n_batch"],
    n_gpu_layers=PERF["n_gpu_layers"],
    use_mmap=PERF["use_mmap"],
    use_mlock=PERF["use_mlock"],
    verbose=PERF["verbose"],
)

# 4. Load Tools
print("Loading tools from tools.json...")
tools_path = "tools.json"

if not os.path.exists(tools_path):
    print(f"Error: Tools file not found at {tools_path}")
    exit(1)

with open(tools_path, "r") as f:
    tools = json.load(f)

# 5. Define test queries mapping to our tools
queries = [
    "What is the weather like in New York?",           # Expected: get_weather
    "Search the web for the latest news on AI.",       # Expected: web_search
    "Can you scan my local network?",                  # Expected: network_scan
]

# 6. Format Tools for API
chat_tools = []
for tool in tools:
    chat_tools.append({
        "type": "function",
        "function": tool
    })

# 6b. Keep only the first function call; normalize so it always ends with <end_function_call>
def first_function_call_only(text: str) -> str:
    end_marker = "<end_function_call>"
    idx = text.find(end_marker)
    if idx != -1:
        return text[: idx + len(end_marker)]
    # Stop token was hit so backend omitted <end_function_call>; append it for a complete call
    if "<start_function_call>" in text and text.strip().endswith("}"):
        return text.rstrip() + "<end_function_call>"
    return text

# 7. Run tests (with timing: time to first token, tokens/sec)
print("\n--- Starting Tests ---")
for query in queries:
    print(f"\nUser Query: {query}")
    
    messages = [
        {"role": "developer", "content": "You are a model that can do function calling with the provided functions."},
        {"role": "user", "content": query}
    ]
    
    t_start = time.perf_counter()
    first_token_time = None
    stream = llm.create_chat_completion(
        messages=messages,
        tools=chat_tools,
        max_tokens=GEN_PERF["max_tokens"],
        temperature=GEN_PERF["temperature"],
        stop=["<end_function_call>", "<eos>"],
        stream=True,
    )
    content_parts = []
    usage = {}
    for chunk in stream:
        choice = chunk.get("choices", [{}])[0]
        delta = choice.get("delta", {})
        text = delta.get("content") or ""
        if text and first_token_time is None:
            first_token_time = time.perf_counter() - t_start
        if text:
            content_parts.append(text)
        if "usage" in chunk:
            usage = chunk["usage"]
    t_end = time.perf_counter()
    total_time = t_end - t_start
    
    # Reconstruct message for display (streaming returns deltas)
    raw = "".join(content_parts)
    # Get generated token count (usage keys vary: completion_tokens / eval_count)
    n_tokens = usage.get("completion_tokens") or usage.get("eval_count") or 0
    if n_tokens == 0 and raw:
        n_tokens = None  # unknown
    tokens_per_sec = (n_tokens / total_time) if n_tokens and total_time > 0 else None
    
    print(f"Model Output (Text):\n{first_function_call_only(raw)}")
    
    # Timing
    if first_token_time is not None:
        print(f"  Time to first token: {first_token_time*1000:.1f} ms")
    if tokens_per_sec is not None:
        print(f"  Tokens per second:   {tokens_per_sec:.1f} ({n_tokens} tokens in {total_time:.2f} s)")
    else:
        print(f"  Total time:         {total_time:.2f} s")

print("\n--- Tests Complete ---")
