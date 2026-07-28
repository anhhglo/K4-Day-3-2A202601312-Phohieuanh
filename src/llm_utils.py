"""
🔁 TIỆN ÍCH GỌI LLM CÓ RETRY

Gemini free tier có HAI hạn mức, đều TÍNH RIÊNG TỪNG MODEL:
  - 5 request/phút  (GenerateRequestsPerMinutePerProjectPerModel)  → chờ là qua
  - 20 request/NGÀY (GenerateRequestsPerDayPerProjectPerModel)     → chờ vô ích

providers.py không raise exception mà trả về chuỗi '[OpenAI Exception]: ...',
nên chỗ nào gọi LLM cũng cần lớp bọc này để tự chờ và thử lại khi gặp 429.
Hết hạn mức NGÀY thì retry không cứu được — đổi sang model khác (mỗi model một
hạn mức riêng) hoặc chờ sang ngày mới.
"""

import re
import time

MAX_LLM_RETRIES = 3


def is_provider_error(text: str) -> bool:
    """providers.py trả chuỗi '[... Error]' / '[... Exception]' thay vì raise."""
    return bool(text) and bool(re.match(r"^\[\w+ (Error|Exception)\]", text.strip()))


def _retry_delay(err: str) -> float:
    """Bóc 'retryDelay': '25s' từ thông báo 429 của Gemini; mặc định 20 giây."""
    match = re.search(r"retryDelay'?[:\s\"']+(\d+(?:\.\d+)?)s", err)
    return float(match.group(1)) + 1 if match else 20.0


def call_llm(provider, prompt: str, system_prompt: str = "", retries: int = MAX_LLM_RETRIES) -> str:
    """Gọi LLM có retry/backoff khi hết quota (HTTP 429)."""
    out = ""
    for attempt in range(retries + 1):
        out = provider.generate(prompt, system_prompt=system_prompt) if system_prompt \
            else provider.generate(prompt)
        if not is_provider_error(out):
            return out
        if "429" not in out and "RESOURCE_EXHAUSTED" not in out:
            return out  # Lỗi khác (401, 404...) — retry vô ích
        if attempt == retries:
            return out
        wait = _retry_delay(out)
        print(f"⏳ [RateLimit] Hết quota, chờ {wait:.0f}s rồi thử lại ({attempt + 1}/{retries})...")
        time.sleep(wait)
    return out
