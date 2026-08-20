import os
from huggingface_hub import hf_hub_download
from llama_cpp import Llama

# 1. Model Configuration
REPO_ID = "Edge-Quant/Nanbeige4.1-3B-Q4_K_M-GGUF"
FILENAME = "nanbeige4.1-3b-q4_k_m.gguf"
LOCAL_DIR = "./models"
MODEL_PATH = os.path.join(LOCAL_DIR, FILENAME)


def _env_int(name, default):
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


LLM_THREADS = _env_int("NOVA_CODE_LLM_THREADS", min(4, os.cpu_count() or 4))

# 2. Auto-Download Logic
if not os.path.exists(MODEL_PATH):
    print(f"Model not found at {MODEL_PATH}. Downloading from Hugging Face...")
    os.makedirs(LOCAL_DIR, exist_ok=True)
    # This securely downloads the file and caches it in your local directory
    MODEL_PATH = hf_hub_download(
        repo_id=REPO_ID,
        filename=FILENAME,
        local_dir=LOCAL_DIR
    )
    print("Download complete!")

# 3. Initialize Model
print("Loading code model into memory...")
llm = Llama(
    model_path=MODEL_PATH,
    n_ctx=2048,   # Context window size keeps RAM usage safe
    n_threads=LLM_THREADS,
    verbose=False # Hides the messy loading logs from the terminal
)

# 4. Initialize Chat History with Strict System Prompt
# The system prompt enforces the "code only" rule
messages = [
    {
        "role": "system",
        "content": "You are an expert programmer. You must reply ONLY with raw, executable code. Do not include markdown formatting tags (like ```python), explanations, greetings, or conversational text. Your entire response must be valid code."
    }
]

print("\n--- AI Coding Assistant Ready (Type 'exit' to quit) ---")

# 5. Interactive Chat Loop
while True:
    user_input = input("\nYou: ")
    if user_input.lower() in ['exit', 'quit']:
        print("Goodbye!")
        break
        
    # Append the user's prompt to the conversation history
    messages.append({"role": "user", "content": user_input})
    
    print("AI:\n", end="", flush=True)
    
    # Generate the response
    response = llm.create_chat_completion(
        messages=messages,
        max_tokens=512,
        temperature=0.1, # Low temperature keeps the code precise and stops it from hallucinating
        stream=True      # Streams the output live, which is much better for slower CPU generation
    )
    
    # Process the streaming chunks as they arrive
    full_reply = ""
    for chunk in response:
        delta = chunk['choices'][0]['delta']
        if 'content' in delta:
            text = delta['content']
            print(text, end="", flush=True)
            full_reply += text
            
    # Save the AI's final response to the chat history so it remembers context
    messages.append({"role": "assistant", "content": full_reply})
    print() # Add a final newline for readability
