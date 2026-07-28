"""
🔌 MULTI-PROVIDER LLM ADAPTER (OpenAI, Gemini, Anthropic, OpenRouter & Offline Mock)
Hỗ trợ chuyển đổi linh hoạt giữa các nhà cung cấp AI chỉ bằng cách đổi biến môi trường LLM_PROVIDER.
"""

import os
import sys
import json
import requests
from dotenv import load_dotenv

# Đảm bảo in ra Tiếng Việt và Emojis không bị lỗi trên Windows Console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

class BaseLLMProvider:
    """Interface cơ sở cho tất cả các LLM Provider"""
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        raise NotImplementedError


class GeminiProvider(BaseLLMProvider):
    """Google Gemini Provider"""
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "gemini-2.5-flash"
        
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not self.api_key or self.api_key == "your_gemini_api_key_here":
            return "[Gemini Error]: Chưa cấu hình GEMINI_API_KEY trong file .env!"
        try:
            from google import genai
            client = genai.Client(api_key=self.api_key)
            contents = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
            response = client.models.generate_content(
                model=self.model_name,
                contents=contents
            )
            return response.text
        except Exception as e:
            return f"[Gemini Exception]: {str(e)}"


class OpenAIProvider(BaseLLMProvider):
    """OpenAI Provider (GPT-4o, GPT-3.5-turbo, etc.)"""
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "gpt-4o-mini"
        
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not self.api_key or self.api_key == "your_openai_api_key_here":
            return "[OpenAI Error]: Chưa cấu hình OPENAI_API_KEY trong file .env!"
        try:
            import openai
            client = openai.OpenAI(api_key=self.api_key)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            response = client.chat.completions.create(
                model=self.model_name,
                messages=messages
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"[OpenAI Exception]: {str(e)}"


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Claude Provider (Claude 3.5 Sonnet, Claude 3 Haiku)"""
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "claude-3-haiku-20240307"
        
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not self.api_key or self.api_key == "your_anthropic_api_key_here":
            return "[Anthropic Error]: Chưa cấu hình ANTHROPIC_API_KEY trong file .env!"
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            kwargs = {
                "model": self.model_name,
                "max_tokens": 1000,
                "messages": [{"role": "user", "content": prompt}]
            }
            if system_prompt:
                kwargs["system"] = system_prompt
                
            response = client.messages.create(**kwargs)
            return response.content[0].text
        except Exception as e:
            return f"[Anthropic Exception]: {str(e)}"


class OpenRouterProvider(BaseLLMProvider):
    """OpenRouter Provider (Hỗ trợ gọi mọi model qua OpenRouter API)"""
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "google/gemini-2.5-flash"
        
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not self.api_key or self.api_key == "your_openrouter_api_key_here":
            return "[OpenRouter Error]: Chưa cấu hình OPENROUTER_API_KEY trong file .env!"
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            payload = {
                "model": self.model_name,
                "messages": messages
            }
            res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=30)
            if res.status_code == 200:
                data = res.json()
                return data["choices"][0]["message"]["content"]
            else:
                return f"[OpenRouter API Error {res.status_code}]: {res.text}"
        except Exception as e:
            return f"[OpenRouter Exception]: {str(e)}"


class MockProvider(BaseLLMProvider):
    """Offline Mock Provider (Cho bài test không cần kết nối API).

    Trả kịch bản ReAct đúng định dạng của domain duyệt chi phí, để chạy offline
    vẫn thấy được vòng lặp Thought → Action → Observation thay vì một câu trả lời
    cụt lủn.
    """
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        text = prompt.lower()
        # Đã có Observation nghĩa là tool chạy xong — chốt lại thay vì gọi tiếp,
        # nếu không mock sẽ lặp mãi tới khi chạm trần MAX_ITERATIONS.
        da_co_observation = "observation:" in text
        if "exp-" in text and not da_co_observation:
            return ("Thought: Cần mở hồ sơ đơn chi phí trước khi kết luận.\n"
                    "Action: get_expense_report[EXP-2026-0142]")
        if ("chính sách" in text or "hạn mức" in text) and not da_co_observation:
            return ("Thought: Cần tra chính sách hạng mục.\n"
                    "Action: get_policy[an_uong]")
        return ("Thought: Đây là phản hồi giả lập offline.\n"
                "Final Answer: 🤖 [Mock Provider] Phản hồi giả lập offline cho bài test.")


class GroqProvider(BaseLLMProvider):
    """Groq Provider (Llama-3)"""
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model_name = model or os.getenv("LLM_MODEL") or "llama-3.3-70b-versatile"
        
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        if not self.api_key:
            return "[Groq Error]: Chưa cấu hình GROQ_API_KEY trong file .env!"
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
            }
            resp = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload, timeout=30)
            if resp.status_code == 429:
                return f"[Groq Error] Groq rate-limit (429): {resp.text[:200]}"
            if resp.status_code != 200:
                return f"[Groq Error] Groq lỗi HTTP {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[Groq Exception]: {str(e)}"


class FallbackProvider(BaseLLMProvider):
    """Fallback Provider that wraps Groq and Gemini calling with fallback logic"""
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        try:
            return call_llm_with_fallback(system_prompt, prompt, verbose=False)
        except Exception as e:
            return f"[Fallback Exception]: {str(e)}"


def get_llm_provider(provider_name: str = None) -> BaseLLMProvider:
    """Factory function tự chọn Provider từ biến môi trường LLM_PROVIDER"""
    name = (provider_name or os.getenv("LLM_PROVIDER") or "mock").lower().strip()
    
    if name == "gemini":
        return GeminiProvider()
    elif name == "openai":
        return OpenAIProvider()
    elif name == "anthropic":
        return AnthropicProvider()
    elif name == "openrouter":
        return OpenRouterProvider()
    elif name == "groq":
        return GroqProvider()
    elif name == "fallback":
        return FallbackProvider()
    else:
        return MockProvider()


# ---------------------------------------------------------------------------
# Cấu hình từng provider phục vụ call_llm_with_fallback
# ---------------------------------------------------------------------------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

REQUEST_TIMEOUT_SECONDS = 30  # timeout gọi mạng tới LLM
COOLDOWN_SECONDS = 60         # sau khi 1 provider báo hết quota, tạm bỏ qua nó bao nhiêu giây

# Thứ tự ưu tiên thử: Groq trước (nhanh, quota/phút cao hơn), Gemini là dự phòng.
PROVIDER_ORDER = ["groq", "gemini"]

class ProviderQuotaError(Exception):
    """Provider báo hết quota / bị rate-limit (HTTP 429 hoặc lỗi tương đương)."""

class ProviderError(Exception):
    """Lỗi khác không liên quan tới quota (thiếu key, lỗi mạng, sai định dạng phản hồi...)."""

import time
# Lưu thời điểm 1 provider bị đánh dấu hết quota -> tạm bỏ qua nó tới hết COOLDOWN_SECONDS
_cooldown_until = {name: 0.0 for name in PROVIDER_ORDER}


def _call_groq(system_prompt: str, user_message: str) -> str:
    api_key = os.environ.get("GROQ_API_KEY", "") or GROQ_API_KEY
    if not api_key:
        raise ProviderError("Thiếu GROQ_API_KEY trong biến môi trường (.env).")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0,
    }
    resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)

    if resp.status_code == 429:
        raise ProviderQuotaError(f"Groq rate-limit (429): {resp.text[:200]}")
    if resp.status_code != 200:
        raise ProviderError(f"Groq lỗi HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise ProviderError(f"Groq trả về định dạng không như mong đợi: {e}")


def _call_gemini(system_prompt: str, user_message: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "") or GEMINI_API_KEY
    if not api_key:
        raise ProviderError("Thiếu GEMINI_API_KEY trong biến môi trường (.env).")

    params = {"key": api_key}
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": {"temperature": 0},
    }
    resp = requests.post(GEMINI_URL, params=params, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)

    if resp.status_code == 429:
        raise ProviderQuotaError(f"Gemini rate-limit (429): {resp.text[:200]}")
    if resp.status_code != 200:
        raise ProviderError(f"Gemini lỗi HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise ProviderError(f"Gemini trả về định dạng không như mong đợi: {e}")


_CALLERS = {
    "groq": _call_groq,
    "gemini": _call_gemini,
}


def call_llm_with_fallback(system_prompt: str, user_message: str, verbose: bool = True) -> str:
    """
    Gọi LLM với khả năng tự động chuyển provider khi bị rate-limit/hết quota.
    """
    now = time.time()
    errors = []

    for name in PROVIDER_ORDER:
        if now < _cooldown_until[name]:
            if verbose:
                remaining = int(_cooldown_until[name] - now)
                print(f"[providers] Bỏ qua '{name}' - đang cooldown thêm {remaining}s.")
            continue

        try:
            if verbose:
                print(f"[providers] Đang gọi '{name}'...")
            text = _CALLERS[name](system_prompt, user_message)
            if verbose:
                print(f"[providers] '{name}' trả lời thành công.")
            return text
        except ProviderQuotaError as e:
            print(f"[providers] '{name}' HẾT QUOTA -> tự động chuyển sang provider kế tiếp. ({e})")
            _cooldown_until[name] = time.time() + COOLDOWN_SECONDS
            errors.append(f"{name}: {e}")
            continue
        except ProviderError as e:
            print(f"[providers] '{name}' lỗi -> thử provider kế tiếp. ({e})")
            errors.append(f"{name}: {e}")
            continue

    raise ProviderError(
        "TẤT CẢ provider đều thất bại hoặc đang cooldown:\n" + "\n".join(errors)
    )


if __name__ == "__main__":
    print("=== TEST MULTI-PROVIDER LLM ADAPTER ===")
    provider = get_llm_provider()
    print(f"✅ Provider đang dùng: {provider.__class__.__name__}")
    print(f"🤖 User Query: Hello")
    print(f"💬 Response  : {provider.generate('Hello')}")

