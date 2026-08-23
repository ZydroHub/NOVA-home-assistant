"""
Semantic router for backend: route a user prompt to one of two models.
- qwen_basic: Qwen 0.6B (non-thinking) for general conversation and factual Q&A
- function_gemma: Function Gemma for tool/function calls and real-time lookups

Import and call get_route(prompt) from chat_ai for voice and chat flows.

The router uses FastEmbedEncoder, which downloads a small embedding model (~67MB) from
Hugging Face the first time. We cache it under the project models dir so it only downloads once.
"""
import os
import re
import time
import threading
from pathlib import Path

_llm = None

_router = None
_router_lock = threading.Lock()


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _populate_index(router, routes, encoder) -> None:
    """
    Force-populate the LocalIndex after SemanticRouter init.
    SemanticRouter does not always auto-build LocalIndex on construction,
    which leaves it in a 'not ready' state. This uses the public index.add()
    signature that is stable across semantic-router versions.
    """
    all_utterances: list[str] = []
    all_route_names: list[str] = []

    for route in routes:
        for utterance in route.utterances:
            all_utterances.append(utterance)
            all_route_names.append(route.name)

    if not all_utterances:
        return

    # Encode all utterances in one batch — same call SemanticRouter uses internally
    embeddings = encoder(all_utterances)

    # embeddings may be a numpy array or list depending on version — normalise to list of lists
    try:
        embeddings_list = embeddings.tolist()
    except AttributeError:
        embeddings_list = [list(e) for e in embeddings]

    # Public index.add() signature: add(embeddings, routes, utterances)
    # function_schemas and metadata_list are optional kwargs in newer versions
    try:
        router.index.add(
            embeddings=embeddings_list,
            routes=all_route_names,
            utterances=all_utterances,
            function_schemas=[None] * len(all_utterances),
            metadata_list=[{}] * len(all_utterances),
        )
    except TypeError:
        # Older versions don't accept function_schemas / metadata_list
        router.index.add(
            embeddings=embeddings_list,
            routes=all_route_names,
            utterances=all_utterances,
        )


def init_router():
    """Build and cache the semantic router for fast in-memory route checks."""
    global _router
    if _router is not None:
        return _router
    with _router_lock:
        if _router is not None:
            return _router
        try:
            from semantic_router import Route
            from semantic_router.encoders import FastEmbedEncoder
            from semantic_router.index.local import LocalIndex
            from semantic_router.routers import SemanticRouter
        except ImportError as e:
            raise ImportError(
                "semantic_router not available. Install: pip install 'semantic-router[fastembed]'"
            ) from e

        # Cache embedding model under project models/ so it only downloads once.
        try:
            from config import LOCAL_DIR
            embed_cache = os.path.join(LOCAL_DIR, "fastembed_cache")
        except ImportError:
            embed_cache = str(Path(__file__).resolve().parent / "models" / "fastembed_cache")
        os.makedirs(embed_cache, exist_ok=True)
        encoder = FastEmbedEncoder(cache_dir=embed_cache)

        qwen_basic = Route(
            name="qwen_basic",
            utterances=[
                # Greetings and chitchat
                "hi", "hello", "hey there", "how are you", "what's up", "good morning",
                "good night", "thanks!", "thank you", "bye", "see you", "ok", "got it",
                "that's nice", "cool", "sure", "no problem", "how's it going", "nice to meet you",
                # Simple factual questions — answered from model knowledge, no tool needed
                "what is the largest continent?", "what is the capital of the United States?",
                "what is the capital of France?", "how many continents are there?",
                "what is two plus two?", "who wrote Romeo and Juliet?",
                "what is the speed of light?", "what year did World War II end?",
                "what is the largest ocean?", "name the planets in our solar system",
                "what is the capital of Japan?", "how many days in a week?",
                "what is the biggest country by area?", "simple facts", "give me a quick fact",
                "what's the population of China?", "who is the president of the US?",
                # Reasoning and explanation
                "why does this happen?", "explain the reasoning behind it",
                "what are the steps to solve this?", "analyze this situation",
                "what are the pros and cons?", "how would you approach this problem?",
                "walk me through the logic", "what's the cause of this?",
                "give me a detailed explanation", "what are the implications?",
                "summarize the main points", "how do these relate?",
                "what's the difference between A and B?",
            ],
        )

        function_gemma = Route(
            name="function_gemma",
            utterances=[
                # Weather
                "what is the weather like in New York?", "weather in London",
                "get weather for Boston", "check the weather",
                "what's the temperature outside", "what's the weather today",
                "is it going to rain?", "weather forecast for Stockholm",
                # Web search
                "search the web for latest news", "search for AI news",
                "web search for something", "look up the news",
                "find recent news about something", "search for something online",
                "look something up on the web", "find information online",
                # Network
                "scan my local network", "scan the network",
                # Spotify playback
                "play music", "start the music", "resume the music",
                "put some music on", "play spotify", "turn the music on",
                "spela musik", "starta musiken", "fortsatt spela musiken",
                "satt pa spotify", "satt pa musik",
                "turn off the music", "turn music off", "stop the music",
                "pause the music", "turn off spotify", "stang av musiken",
                "pausa musiken", "stoppa musiken",
                "lower the volume", "turn down the volume", "lower music volume",
                "turn the music down", "make the music quieter", "sank volymen",
                "sank musiken", "skruva ner volymen",
                "lower the volume by 20 percent", "turn the music down by 20 percent",
                "sank volymen med 20 procent", "sank musiken med 20 procent",
                "sank med 20 procent", "lower by 20 percent",
                "raise the volume", "turn up the volume", "increase the volume",
                "raise music volume", "turn the music up", "make the music louder",
                "hoj volymen", "hoj musiken", "skruva upp volymen",
                "raise the volume by 10 percent", "turn the music up by 10 percent",
                "hoj volymen med 10 procent", "hoj med 10 procent", "plus 10 percent",
                # Spotify now playing
                "what song is playing", "what music is playing right now",
                "what's the music right now that i'm playing",
                "what am i listening to", "which track is this", "who is this artist",
                "what is currently playing on spotify", "tell me the current song",
                "vilken lat spelas", "vad lyssnar jag pa", "vad spelas pa spotify",
                "vilken musik spelar just nu",
                # Live data
                "what time is it in Tokyo", "current exchange rate",
                "find out the latest sports scores",
            ],
        )

        routes = [qwen_basic, function_gemma]

        # Init router with empty index — we populate it manually below
        # to guarantee the index is ready regardless of semantic-router version.
        _router = SemanticRouter(
            encoder=encoder,
            routes=routes,
            index=LocalIndex(top_k=3),
        )

        # Force-populate the index so it is ready for queries
        _populate_index(_router, routes, encoder)

        return _router


def _get_router():
    """Return the cached semantic router, initializing it once if needed."""
    return init_router()


def get_route(prompt: str) -> str:
    """
    Route a user prompt to a model. Returns one of:
    "qwen_basic", "function_gemma".
    Defaults to "qwen_basic" if no route matches or on error.
    """
    if not (prompt or "").strip():
        return "qwen_basic"
    try:
        router = _get_router()
        choice = router(prompt)
        name = choice.name if choice else None
        return name if name in ("qwen_basic", "function_gemma") else "qwen_basic"
    except Exception as e:
        print(f"[semantic_router_ai] route failed: {e}")
        return "qwen_basic"


def _strip_think(text: str) -> str:
    """Remove <think>...</think> blocks for display."""
    if not text or not text.strip():
        return text
    out = re.sub(r'<\s*think\s*>.*?<\s*/\s*think\s*>', '', text, flags=re.DOTALL | re.IGNORECASE)
    out = re.sub(r'<\s*think\s*>[\s\S]*$', '', out, flags=re.IGNORECASE)
    out = out.replace('</think>', '').replace('<think>', '')
    return out.strip()


def _get_llm():
    """Load and cache the Qwen LLM (same config as chat_ai)."""
    global _llm
    if _llm is not None:
        return _llm
    try:
        from config import LOCAL_DIR, CHAT_REPO_ID as REPO_ID, CHAT_FILENAME as FILENAME, CHAT_MODEL_PATH as MODEL_PATH
        from huggingface_hub import hf_hub_download
        from llama_cpp import Llama
    except ImportError as e:
        raise ImportError("Need config, huggingface_hub, llama_cpp for REPL Qwen. Install: pip install llama-cpp-python huggingface-hub") from e
    if not os.path.exists(MODEL_PATH):
        print("Downloading Qwen model...")
        os.makedirs(LOCAL_DIR, exist_ok=True)
        hf_hub_download(repo_id=REPO_ID, filename=FILENAME, local_dir=LOCAL_DIR)
    print("Loading Qwen LLM...")
    llm_threads = _env_int("NOVA_LLM_THREADS", min(4, os.cpu_count() or 4))
    _llm = Llama(model_path=MODEL_PATH, n_ctx=4096, n_threads=llm_threads, verbose=False)
    return _llm


def _generate_sync(prompt: str) -> str:
    """Run Qwen on one user message; returns full raw response."""
    llm = _get_llm()
    user_content = prompt + " /no_think"
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": user_content},
    ]
    stream = llm.create_chat_completion(
        messages=messages,
        max_tokens=2048,
        temperature=0.7,
        top_p=0.8,
        top_k=20,
        min_p=0.0,
        presence_penalty=1.5,
        stream=True,
    )
    full = ""
    for chunk in stream:
        if chunk.get("choices") and len(chunk["choices"]) > 0:
            delta = chunk["choices"][0].get("delta", {})
            if "content" in delta:
                content = delta["content"]
                full += content
                print(content, end="", flush=True)
    print()
    return full


# --- REPL for manual testing ---
def main():
    print("Loading router...")
    get_route("warmup")  # force init
    print("Loading Qwen...")
    _get_llm()
    print("Semantic router ready. Type a prompt (empty to quit). function_gemma route is skipped in REPL.\n")
    while True:
        try:
            prompt = input("Prompt> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not prompt:
            break
        t0 = time.perf_counter()
        r = get_route(prompt)
        route_ms = (time.perf_counter() - t0) * 1000
        print(f"  -> {r}  (routing: {route_ms:.1f} ms)")
        if r == "function_gemma":
            print("  (function_gemma skipped in REPL)\n")
            continue
        gen_t0 = time.perf_counter()
        _generate_sync(prompt)
        gen_ms = (time.perf_counter() - gen_t0) * 1000
        print(f"  (generation: {gen_ms:.0f} ms)\n")
    print("Bye.")


if __name__ == "__main__":
    main()
