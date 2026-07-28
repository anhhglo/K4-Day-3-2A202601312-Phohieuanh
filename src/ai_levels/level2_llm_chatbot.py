"""
💬 CẤP ĐỘ 2: LLM CHATBOT (Baseline Chatbot không có Tool)

Dùng LLM thật sinh câu trả lời tự nhiên mượt mà, nhưng KHÔNG được cấp công cụ nào
nên không tra cứu được đơn chi phí cụ thể. Đây chính là hạn chế mà Cấp 3 khắc phục.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_utils import call_llm  # noqa: E402
from prompts import CHATBOT_BASELINE_PROMPT  # noqa: E402
from providers import get_llm_provider  # noqa: E402

if __name__ == "__main__":
    print("=== DEMO CẤP ĐỘ 2: LLM CHATBOT BASELINE ===\n")
    provider = get_llm_provider()
    print(f"🔌 Provider: {provider.__class__.__name__} "
          f"({getattr(provider, 'model_name', 'mock')})")

    cau_hoi = "Đơn chi phí EXP-2026-0142 của công ty tôi có được duyệt không?"
    print(f"\n👤 {cau_hoi}")
    print(f"🤖 {call_llm(provider, cau_hoi, system_prompt=CHATBOT_BASELINE_PROMPT)}")

    print("\n💡 Nhận xét: câu trả lời trôi chảy nhưng KHÔNG tra được số liệu thật — "
          "chatbot không biết đơn này bao nhiêu tiền, hạng mục gì, ngân sách còn không.")
