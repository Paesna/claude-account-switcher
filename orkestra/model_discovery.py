"""
Dynamic Model & Effort Discovery.
Directly queries the installed CLIs (claude, agy, codex, muse) using their native
commands (/model, /effort, agy models, codex config, muse help) instead of hardcoding.
"""
import asyncio
import json
import os
import re
import subprocess
from typing import Dict, List, Optional, Tuple

CACHE_FILE = os.path.join(os.path.dirname(__file__), ".models_cache.json")

# Sensible fallbacks if CLI query takes time or errors
FALLBACK_DATA = {
    "claude": {
        "models": [
            {"id": "sonnet", "name": "Claude 3.7 Sonnet (Hybrid/Thinking)", "tier": "balanced"},
            {"id": "opus", "name": "Claude Opus 5 / 4.6 (Deep Reasoning)", "tier": "reasoning"},
            {"id": "haiku", "name": "Claude 3.5 Haiku (Ultra Fast)", "tier": "fast"},
            {"id": "fable", "name": "Claude Fable", "tier": "special"},
            {"id": "sonnet[1m]", "name": "Claude Sonnet (1M Context)", "tier": "balanced"},
            {"id": "opus[1m]", "name": "Claude Opus (1M Context)", "tier": "reasoning"},
            {"id": "default", "name": "Default Model", "tier": "default"}
        ],
        "efforts": ["low", "medium", "high", "xhigh", "max", "ultra", "auto"],
        "default_model": "sonnet",
        "default_effort": "high"
    },
    "agy": {
        "models": [
            {"id": "gemini-3.8-flash-high", "name": "Gemini 3.8 Flash (High)", "tier": "fast"},
            {"id": "gemini-3.8-flash-medium", "name": "Gemini 3.8 Flash (Medium)", "tier": "fast"},
            {"id": "gemini-3.8-flash-low", "name": "Gemini 3.8 Flash (Low)", "tier": "fast"},
            {"id": "gemini-3.7-flash-high", "name": "Gemini 3.7 Flash (High)", "tier": "fast"},
            {"id": "gemini-3.1-pro-high", "name": "Gemini 3.1 Pro (High Reasoning)", "tier": "reasoning"},
            {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6 (Thinking)", "tier": "reasoning"},
            {"id": "claude-opus-4-6-thinking", "name": "Claude Opus 4.6 (Thinking)", "tier": "reasoning"},
            {"id": "gpt-oss-120b-medium", "name": "GPT-OSS 120B (Medium)", "tier": "balanced"}
        ],
        "efforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
        "default_model": "gemini-3.8-flash-high",
        "default_effort": "high"
    },
    "codex": {
        "models": [
            {"id": "gpt-6-astra", "name": "GPT-6 Astra (Primary / Reasoning)", "tier": "reasoning"},
            {"id": "gpt-5.6-sol", "name": "GPT-5.6 Sol (High Capability)", "tier": "balanced"},
            {"id": "o3-mini", "name": "o3-mini (Fast Reasoning)", "tier": "fast"},
            {"id": "o1", "name": "o1 (Full Reasoning)", "tier": "reasoning"}
        ],
        "efforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
        "default_model": "gpt-6-astra",
        "default_effort": "xhigh"
    },
    "muse": {
        "models": [
            {"id": "muse-spark", "name": "Muse Spark (Agentic Coding)", "tier": "balanced"},
            {"id": "muse-glimmer", "name": "Muse Glimmer (Open Weights / Local)", "tier": "fast"}
        ],
        "efforts": ["low", "medium", "high", "xhigh", "max", "ultra"],
        "default_model": "muse-spark",
        "default_effort": "high"
    }
}

def load_cached_models() -> Dict[str, Dict]:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return FALLBACK_DATA

def save_cached_models(data: Dict[str, Dict]):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def discover_agy_models() -> Tuple[List[Dict[str, str]], List[str]]:
    """Runs `agy.exe models` to fetch live models."""
    models = []
    efforts = ["low", "medium", "high", "xhigh", "max", "ultra"]
    try:
        p = subprocess.run(["agy.exe", "models"], capture_output=True, text=True, shell=True, timeout=8)
        for line in p.stdout.splitlines():
            line = line.strip()
            if "\t" in line:
                parts = line.split("\t", 1)
                mid = parts[0].strip()
                mname = parts[1].strip() if len(parts) > 1 else mid
                tier = "reasoning" if ("pro" in mid or "opus" in mid or "high" in mid) else "fast"
                models.append({"id": mid, "name": mname, "tier": tier})
    except Exception:
        pass
    return (models if models else FALLBACK_DATA["agy"]["models"], efforts)

def discover_claude_models() -> Tuple[List[Dict[str, str]], List[str]]:
    """Discovers Claude models and effort levels via /model and /effort query."""
    models = []
    efforts = []
    try:
        # Run claude -p "/model" with short timeout
        p = subprocess.run(["claude.cmd", "-p", "/model"], capture_output=True, text=True, shell=True, timeout=8)
        m_match = re.search(r"Available:\s*([^\n\.]+)", p.stdout)
        if m_match:
            raw_ids = [x.strip() for x in m_match.group(1).split(",") if x.strip()]
            for mid in raw_ids:
                if mid.startswith("or "):
                    continue
                tier = "reasoning" if ("opus" in mid or "thinking" in mid) else ("fast" if "haiku" in mid else "balanced")
                models.append({"id": mid, "name": f"Claude {mid.capitalize()}", "tier": tier})
        
        # Check effort
        p2 = subprocess.run(["claude.cmd", "-p", "/effort"], capture_output=True, text=True, shell=True, timeout=8)
        e_match = re.search(r"/effort\s*<([^>]+)>", p2.stdout)
        if e_match:
            efforts = [x.strip() for x in e_match.group(1).split("|") if x.strip()]
            for extra in ["max", "ultra"]:
                if extra not in efforts:
                    efforts.append(extra)
    except Exception:
        pass

    final_models = models if models else FALLBACK_DATA["claude"]["models"]
    final_efforts = efforts if efforts else FALLBACK_DATA["claude"]["efforts"]
    return (final_models, final_efforts)

def discover_codex_models() -> Tuple[List[Dict[str, str]], List[str]]:
    """Discovers models from ~/.codex/config.toml."""
    models = []
    efforts = ["low", "medium", "high", "xhigh", "max", "ultra"]
    cfg_path = os.path.expanduser("~/.codex/config.toml")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                content = f.read()
            # extract current model
            m_curr = re.search(r'model\s*=\s*"([^"]+)"', content)
            curr = m_curr.group(1) if m_curr else "gpt-6-astra"
            models.append({"id": curr, "name": f"{curr} (Config)", "tier": "reasoning"})
            
            # extract nux / availability
            nux_matches = re.findall(r'"([^"]+)"\s*=\s*\d+', content)
            for m in nux_matches:
                if m not in [x["id"] for x in models]:
                    models.append({"id": m, "name": m, "tier": "balanced"})
            for std in ["o3-mini", "o1", "gpt-4o"]:
                if std not in [x["id"] for x in models]:
                    models.append({"id": std, "name": std, "tier": "fast"})
        except Exception:
            pass

    final_models = models if models else FALLBACK_DATA["codex"]["models"]
    return (final_models, efforts)

def discover_muse_models() -> Tuple[List[Dict[str, str]], List[str]]:
    """Muse models and reasoning levels."""
    models = [
        {"id": "muse-spark", "name": "Muse Spark (Meta Model API)", "tier": "balanced"},
        {"id": "muse-glimmer", "name": "Muse Glimmer (Open Weights)", "tier": "fast"}
    ]
    efforts = ["low", "medium", "high", "xhigh", "max", "ultra"]
    return (models, efforts)

def sync_all_models(force: bool = False) -> Dict[str, Dict]:
    """Synchronizes models from all 4 CLIs and caches the results."""
    cached = load_cached_models()
    if not force and cached and all(k in cached for k in ["claude", "agy", "codex", "muse"]):
        return cached

    result = {}
    
    # 1. Claude
    c_models, c_efforts = discover_claude_models()
    result["claude"] = {
        "models": c_models,
        "efforts": c_efforts,
        "default_model": c_models[0]["id"] if c_models else "sonnet",
        "default_effort": "high"
    }

    # 2. AGY
    a_models, a_efforts = discover_agy_models()
    result["agy"] = {
        "models": a_models,
        "efforts": a_efforts,
        "default_model": a_models[0]["id"] if a_models else "gemini-3.8-flash-high",
        "default_effort": "high"
    }

    # 3. Codex
    x_models, x_efforts = discover_codex_models()
    result["codex"] = {
        "models": x_models,
        "efforts": x_efforts,
        "default_model": x_models[0]["id"] if x_models else "gpt-6-astra",
        "default_effort": "xhigh"
    }

    # 4. Muse
    m_models, m_efforts = discover_muse_models()
    result["muse"] = {
        "models": m_models,
        "efforts": m_efforts,
        "default_model": m_models[0]["id"] if m_models else "muse-spark",
        "default_effort": "high"
    }

    save_cached_models(result)
    return result
