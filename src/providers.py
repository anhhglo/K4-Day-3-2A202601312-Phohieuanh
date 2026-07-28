"""
🔌 PROVIDERS
Lớp trung gian gọi LLM, hỗ trợ tự động chuyển đổi (failover) giữa nhiều nhà cung cấp miễn phí
(Groq, Google Gemini) khi một bên bị rate-limit / hết quota (HTTP 429), để demo không bị gián đoạn.

⚠️ QUAN TRỌNG VỀ "TRÍ NHỚ": Groq và Gemini đều là API stateless - bản thân LLM KHÔNG tự nhớ
gì giữa các lần gọi, kể cả khi gọi liên tục cùng 1 provider không đổi. Toàn bộ "trí nhớ" của
agent phải nằm ở phía CALLER (app.py) - biến lưu lại toàn bộ lịch sử Thought/Action/Observation
từ đầu phiên tới giờ. Vì vậy `user_message` truyền vào call_llm_with_fallback() PHẢI LUÔN LÀ TOÀN
BỘ lịch sử tính đến hiện tại (không phải chỉ observation/tin nhắn mới nhất) - xem ví dụ ở cuối
file. Nếu làm đúng điều này, việc chuyển đổi Groq <-> Gemini giữa chừng KHÔNG làm mất bất kỳ
ngữ cảnh nào, vì mỗi lần gọi (dù provider nào) đều nhận lại đầy đủ lịch sử y hệt nhau.

Cách dùng trong app.py:
    from providers import call_llm_with_fallback
    reply_text = call_llm_with_fallback(system_prompt=REACT_SYSTEM_PROMPT, user_message=full_history)

Yêu cầu biến môi trường (đặt trong .env):
    GROQ_API_KEY=...
    GEMINI_API_KEY=...
    (có thể chỉ cần 1 trong 2 - vẫn chạy được, chỉ mất khả năng failover)

Yêu cầu package: requests (và tuỳ chọn python-dotenv để tự load .env khi chạy file này độc lập)
"""

import os
import time
import requests

try:  # cho phép chạy `python providers.py` độc lập mà vẫn đọc được .env
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Cấu hình từng provider
# ---------------------------------------------------------------------------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Lưu ý: tên model free-tier của Gemini có thể đổi theo thời gian - kiểm tra lại trong
# Google AI Studio (aistudio.google.com) nếu gặp lỗi "model not found".
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

REQUEST_TIMEOUT_SECONDS = 30  # timeout gọi mạng tới LLM (khác TIMEOUT_SECONDS của tool trong prompts.py)
COOLDOWN_SECONDS = 60         # sau khi 1 provider báo hết quota, tạm bỏ qua nó bao nhiêu giây

# Thứ tự ưu tiên thử: Groq trước (nhanh, quota/phút cao hơn), Gemini là dự phòng.
PROVIDER_ORDER = ["groq", "gemini"]


class ProviderQuotaError(Exception):
    """Provider báo hết quota / bị rate-limit (HTTP 429 hoặc lỗi tương đương)."""

    def __init__(self, message: str, retry_after_seconds: float = COOLDOWN_SECONDS):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderError(Exception):
    """Lỗi khác không liên quan tới quota (thiếu key, lỗi mạng, sai định dạng phản hồi...)."""


# Lưu thời điểm 1 provider bị đánh dấu hết quota -> tạm bỏ qua nó tới hết thời điểm này
_cooldown_until = {name: 0.0 for name in PROVIDER_ORDER}


def _resolve_cooldown_seconds(resp) -> float:
    """
    Xác định thời gian cooldown chính xác dựa trên header 'Retry-After' mà server trả về
    (nếu có) - vì lỗi 429 có thể là hết quota theo PHÚT (chờ vài giây là đủ) hoặc hết quota
    theo NGÀY (phải chờ rất lâu). Dùng COOLDOWN_SECONDS mặc định làm phương án dự phòng khi
    server không cung cấp thông tin này.
    """
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), 1.0)
        except ValueError:
            pass  # một số server trả về dạng HTTP-date thay vì số giây - bỏ qua, dùng mặc định
    return COOLDOWN_SECONDS


def _call_groq(system_prompt: str, user_message: str) -> str:
    if not GROQ_API_KEY:
        raise ProviderError("Thiếu GROQ_API_KEY trong biến môi trường (.env).")

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
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
        raise ProviderQuotaError(
            f"Groq rate-limit (429): {resp.text[:200]}",
            retry_after_seconds=_resolve_cooldown_seconds(resp),
        )
    if resp.status_code != 200:
        raise ProviderError(f"Groq lỗi HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise ProviderError(f"Groq trả về định dạng không như mong đợi: {e}")


def _call_gemini(system_prompt: str, user_message: str) -> str:
    if not GEMINI_API_KEY:
        raise ProviderError("Thiếu GEMINI_API_KEY trong biến môi trường (.env).")

    params = {"key": GEMINI_API_KEY}
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": {"temperature": 0},
    }
    resp = requests.post(GEMINI_URL, params=params, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)

    if resp.status_code == 429:
        raise ProviderQuotaError(
            f"Gemini rate-limit (429): {resp.text[:200]}",
            retry_after_seconds=_resolve_cooldown_seconds(resp),
        )
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
            _cooldown_until[name] = time.time() + e.retry_after_seconds
            errors.append(f"{name}: {e}")
            continue
        except ProviderError as e:
            print(f"[providers] '{name}' lỗi -> thử provider kế tiếp. ({e})")
            errors.append(f"{name}: {e}")
            continue

    raise ProviderError(
        "TẤT CẢ provider đều thất bại hoặc đang cooldown:\n" + "\n".join(errors)
    )


# ===========================================================================
# LỚP TƯƠNG THÍCH NGƯỢC (BACKWARD COMPATIBILITY ADAPTER)
# Đảm bảo app.py, các file kiểm thử và Cấp độ AI 2, 3, 4 không bị lỗi import
# ===========================================================================

class BaseLLMProvider:
    """Interface cơ sở cho tất cả các LLM Provider"""
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        raise NotImplementedError


class GeminiProvider(BaseLLMProvider):
    """Google Gemini Provider đóng vai trò Fallback"""
    def __init__(self, api_key: str = None, model: str = None):
        pass
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        return call_llm_with_fallback(system_prompt, prompt, verbose=False)


class FallbackProvider(BaseLLMProvider):
    """Fallback Provider sử dụng cơ chế failover Groq/Gemini"""
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        return call_llm_with_fallback(system_prompt, prompt, verbose=False)


class MockProvider(BaseLLMProvider):
    """Offline Mock Provider cho bộ test offline"""
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        text = prompt.lower()
        da_co_observation = "observation:" in text
        if "exp-" in text and not da_co_observation:
            return ("Thought: Cần mở hồ sơ đơn chi phí trước khi kết luận.\n"
                    "Action: get_expense_report[EXP-2026-0142]")
        if ("chính sách" in text or "hạn mức" in text) and not da_co_observation:
            return ("Thought: Cần tra chính sách hạng mục.\n"
                    "Action: get_policy[an_uong]")
        return ("Thought: Đây là phản hồi giả lập offline.\n"
                "Final Answer: 🤖 [Mock Provider] Phản hồi giả lập offline cho bài test.")


def get_llm_provider(provider_name: str = None) -> BaseLLMProvider:
    """Factory function tự động điều phối Provider"""
    name = (provider_name or os.getenv("LLM_PROVIDER") or "mock").lower().strip()
    if name == "mock":
        return MockProvider()
    return FallbackProvider()


if __name__ == "__main__":
    # Test nhanh - cần export GROQ_API_KEY và/hoặc GEMINI_API_KEY (hoặc để trong .env) trước khi chạy.
    try:
        reply = call_llm_with_fallback(
            system_prompt="Bạn là trợ lý trả lời ngắn gọn.",
            user_message="Việt Nam có bao nhiêu tỉnh thành? Trả lời trong 1 câu.",
        )
        print("\nKẾT QUẢ:", reply)
    except Exception as e:
        print("\nKhông thể chạy test nhanh do chưa cấu hình API Key:", e)

    # --- VÍ DỤ cách app.py PHẢI build "full_history" để không mất trí nhớ khi đổi provider ---
    # Sai (dễ gây "mất trí nhớ" - và sai ngay cả khi KHÔNG đổi provider):
    #     reply = call_llm_with_fallback(REACT_SYSTEM_PROMPT, latest_observation)
    #
    # Đúng (nối toàn bộ lịch sử ReAct từ đầu phiên, gửi lại trọn vẹn mỗi lần gọi):
    #     transcript = f"Question: {user_question}\n"
    #     for step in previous_steps:  # mỗi step gồm Thought/Action/Observation đã xảy ra
    #         transcript += f"Thought: {step['thought']}\nAction: {step['action']}\n"
    #         transcript += f"Observation: {step['observation']}\n"
    #     reply = call_llm_with_fallback(REACT_SYSTEM_PROMPT, transcript)
    #     # -> transcript ở trên PHẢI được truyền y hệt dù lần này Groq hay Gemini xử lý.
