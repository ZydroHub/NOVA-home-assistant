import requests
import json
import time
import sys
import psutil

# Model configurations
MODELS = [
    {"model": "qwen3:0.6b", "name": "qwen3:0.6b"},
    #{"model": "gemma3:1b", "name": "gemma3:1b"},
    #{"model": "deepseek-r1:1.5b", "name": "deepseek-r1:1.5b"},
] 

# Ground truth Q&A pairs for accuracy testing
QA_PAIRS = [
    # Math
    {"prompt": "What is 15 + 27? Answer with just the number.", "expected": ["42"]},
    {"prompt": "What is 144 divided by 12? Answer with just the number.", "expected": ["12"]},
    {"prompt": "What is the square root of 81? Answer with just the number.", "expected": ["9"]},
    {"prompt": "How many prime numbers are between 1 and 10? Answer with just the number.", "expected": ["4"]},
    {"prompt": "What is 7 x 8? Answer with just the number.", "expected": ["56"]},
    
    # Geography
    {"prompt": "What is the capital of France? Answer with just the city name.", "expected": ["Paris"]},
    {"prompt": "What is the capital of Japan? Answer with just the city name.", "expected": ["Tokyo"]},
    {"prompt": "What is the largest ocean on Earth? Answer with just the name.", "expected": ["Pacific"]},
    {"prompt": "What continent is Egypt in? Answer with just the continent name.", "expected": ["Africa"]},
    {"prompt": "What is the longest river in the world? Answer with just the name.", "expected": ["Nile", "Amazon"]},  # Both accepted
    
    # Science
    {"prompt": "What is the chemical symbol for gold? Answer with just the symbol.", "expected": ["Au"]},
    {"prompt": "What is the chemical symbol for water? Answer with just the formula.", "expected": ["H2O"]},
    {"prompt": "How many planets are in our solar system? Answer with just the number.", "expected": ["8"]},
    {"prompt": "What is the boiling point of water in Celsius? Answer with just the number.", "expected": ["100"]},
    {"prompt": "What gas do plants absorb from the atmosphere? Answer with just the name.", "expected": ["carbon dioxide", "CO2"]},
    
    # History & General Knowledge  
    {"prompt": "In what year did World War II end? Answer with just the year.", "expected": ["1945"]},
    {"prompt": "Who wrote Romeo and Juliet? Answer with just the name.", "expected": ["Shakespeare", "William Shakespeare"]},
    {"prompt": "How many sides does a hexagon have? Answer with just the number.", "expected": ["6"]},
    {"prompt": "What is the freezing point of water in Fahrenheit? Answer with just the number.", "expected": ["32"]},
    {"prompt": "How many days are in a leap year? Answer with just the number.", "expected": ["366"]},
]

URL_GENERATE = "http://127.0.0.1:11434/api/chat"
URL_PS = "http://127.0.0.1:11434/api/ps"

# Persistent session for connection pooling
session = requests.Session()
session.trust_env = False  # Bypasses system proxies (critical for local speed)

def get_ram_usage(model_name):
    """
    Checks System RAM and Model VRAM/Size via Ollama API.
    """
    # 1. Get Total System RAM Usage (in GB)
    mem = psutil.virtual_memory()
    system_used_gb = mem.used / (1024 ** 3)
    
    # 2. Get Model Specific Memory from Ollama API
    model_mem_gb = 0.0
    try:
        response = session.get(URL_PS)
        if response.status_code == 200:
            models_data = response.json().get('models', [])
            for m in models_data:
                # Find our model in the list of running models
                if m['name'] == model_name or m['model'] == model_name:
                    # 'size' is usually bytes in VRAM/RAM
                    model_mem_gb = m.get('size', 0) / (1024 ** 3)
                    break
    except:
        pass

    return system_used_gb, model_mem_gb

def unload_model(model_name):
    """Force Ollama to unload the model from memory."""
    try:
        session.post("http://127.0.0.1:11434/api/generate", json={
            "model": model_name,
            "keep_alive": 0
        })
    except Exception as e:
        print(f"Error unloading model: {e}")

def run_benchmark(model_name, prompt):
    """
    Streams the response to calculate TTFT, TPS, and captures response text.
    """
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,    # MUST be True for TTFT
        "options": {
            "temperature": 0.5, 
            "seed": 42
        }
    }

    ttft = 0
    total_tokens = 0
    eval_duration_ns = 0
    response_text = ""
    
    load_duration_ns = 0
    prompt_eval_duration_ns = 0
    
    start_time = time.time()
    first_chunk_received_time = 0
    first_token_received = False
    
    try:
        # Send Request using the pooled session
        with session.post(URL_GENERATE, json=payload, stream=True) as r:
            r.raise_for_status()
            
            for line in r.iter_lines():
                if not line: continue
                
                if first_chunk_received_time == 0:
                    first_chunk_received_time = time.time() - start_time
                
                # Parse Chunk
                try:
                    chunk = json.loads(line.decode('utf-8'))
                except:
                    continue
                
                # Accumulate response text
                content = chunk.get('message', {}).get('content', '')
                response_text += content
                
                # 1. Measure TTFT (Time to First Token)
                if not first_token_received:
                    # As soon as we get the first chunk with content, stop the timer
                    if content:
                        ttft = time.time() - start_time
                        first_token_received = True

                # 2. Capture Final Stats (Ollama sends these in the last chunk)
                if chunk.get('done') is True:
                    total_tokens = chunk.get('eval_count', 0)
                    eval_duration_ns = chunk.get('eval_duration', 0)
                    load_duration_ns = chunk.get('load_duration', 0)
                    prompt_eval_duration_ns = chunk.get('prompt_eval_duration', 0)

        # Calculate TPS (Tokens Per Second)
        if eval_duration_ns > 0:
            tps = total_tokens / (eval_duration_ns / 1_000_000_000)
        else:
            total_time = time.time() - start_time
            tps = total_tokens / total_time if total_time > 0 else 0

        metrics = {
            "tps": tps,
            "ttft": ttft,
            "tokens": total_tokens,
            "response": response_text,
            "load_ms": load_duration_ns / 1_000_000,
            "prompt_eval_ms": prompt_eval_duration_ns / 1_000_000,
            "first_chunk_ms": first_chunk_received_time * 1000
        }

        return metrics

    except Exception as e:
        print(f"\nError: {e}")
        return {"tps": 0, "ttft": 0, "tokens": 0, "response": "", "load_ms": 0, "prompt_eval_ms": 0, "first_chunk_ms": 0}


def check_accuracy(response, expected_answers):
    """
    Check if any of the expected answers appear in the response.
    Case-insensitive matching with unicode subscript normalization.
    """
    # Normalize unicode subscripts to ASCII (e.g., H₂O → H2O, CO₂ → CO2)
    subscript_map = str.maketrans('₀₁₂₃₄₅₆₇₈₉', '0123456789')
    response_normalized = response.translate(subscript_map).lower()
    
    for answer in expected_answers:
        if answer.lower() in response_normalized:
            return True
    return False

def main():
    model_names = [m["name"] for m in MODELS]
    print(f"Benchmark: {', '.join(model_names)}")
    print(f"Testing with {len(QA_PAIRS)} ground truth Q&A pairs\n")
    print(f"{'MODEL':<25} | {'METRIC':<12} | {'VALUE':<10} | {'INFO'}")
    print("-" * 95)

    all_results = []

    for config in MODELS:
        model = config["model"]
        display_name = config["name"]
        
        # --- 1. WARMUP & RAM CHECK ---
        sys.stdout.write(f"Loading {display_name}...\r")
        sys.stdout.flush()
        
        try:
            # Simple warmup
            run_benchmark(model, "hi") 
            
            # Now that it's loaded, check RAM
            sys_ram, model_ram = get_ram_usage(model)
        except Exception as e:
            print(f"Could not load {display_name}: {e}")
            continue

        # --- 2. RUN TESTS ---
        total_tps = 0
        total_ttft = 0
        total_load = 0
        total_peval = 0
        count = 0
        correct = 0
        wrong_answers = []
        
        print(f"{display_name:<25} | {'RAM (Sys)':<12} | {sys_ram:.1f} GB     | Total System Memory Used")
        print(f"{display_name:<25} | {'VRAM/Size':<12} | {model_ram:.1f} GB     | Model Size in Memory")

        for i, qa in enumerate(QA_PAIRS):
            sys.stdout.write(f"  Testing {display_name}: {i+1}/{len(QA_PAIRS)}...\r")
            sys.stdout.flush()
            
            res = run_benchmark(model, qa["prompt"])
            
            if res["tps"] > 0:
                total_tps += res["tps"]
                total_ttft += res["ttft"]
                total_load += res["load_ms"]
                total_peval += res["prompt_eval_ms"]
                count += 1
                
                # Check accuracy
                if check_accuracy(res["response"], qa["expected"]):
                    correct += 1
                else:
                    wrong_answers.append({
                        "q": qa["prompt"][:40] + "...",
                        "expected": qa["expected"],
                        "got": res["response"].strip()[:50]
                    })

        # --- 3. RESULTS ---
        if count > 0:
            avg_tps = total_tps / count
            avg_ttft = total_ttft / count
            avg_load = total_load / count
            avg_peval = total_peval / count
            accuracy = (correct / len(QA_PAIRS)) * 100
            
            # Print Final Stats for this model
            print(f"{display_name:<25} | {'Avg Speed':<12} | {avg_tps:<6.1f} T/s | Generation Speed")
            print(f"{display_name:<25} | {'Avg TTFT':<12} | {avg_ttft*1000:<6.0f} ms   | Time to First Token (Wall)")
            print(f"{display_name:<25} | {'Avg Load':<12} | {avg_load:<6.0f} ms   | Model Load Time (API)")
            print(f"{display_name:<25} | {'Avg Prep':<12} | {avg_peval:<6.0f} ms   | Prompt Eval Time (API)")
            print(f"{display_name:<25} | {'Accuracy':<12} | {correct}/{len(QA_PAIRS)} ({accuracy:.0f}%) | Ground Truth Score")
            
            # Show wrong answers if any (optional verbose)
            if wrong_answers and len(wrong_answers) <= 5:
                for w in wrong_answers:
                    print(f"  [X] Expected {w['expected']}, got: {w['got']}")
            elif wrong_answers:
                print(f"  [X] {len(wrong_answers)} incorrect answers")
            
            all_results.append({
                "name": display_name,
                "tps": avg_tps,
                "ttft": avg_ttft * 1000,
                "accuracy": accuracy,
                "vram": model_ram
            })
                
            print("-" * 85)
        else:
            print(f"{display_name:<25} | Failed to run tests.")

        # --- UNLOAD THE MODEL ---
        sys.stdout.write(f"Unloading {display_name}...\n")
        sys.stdout.flush()
        unload_model(model)

    # --- 4. FINAL COMPARISON ---
    if all_results:
        print("\n\n" + "=" * 85)
        print(f"{'FINAL MODEL COMPARISON':^85}")
        print("=" * 85)
        print(f"{'MODEL':<25} | {'SPEED (T/s)':<12} | {'TTFT (ms)':<10} | {'VRAM (GB)':<10} | {'ACCURACY'}")
        print("-" * 95)
        for r in sorted(all_results, key=lambda x: x['tps'], reverse=True):
            print(f"{r['name']:<25} | {r['tps']:<12.1f} | {r['ttft']:<10.0f} | {r['vram']:<10.1f} | {r['accuracy']:.0f}%")
        print("=" * 95)

if __name__ == "__main__":
    main()
