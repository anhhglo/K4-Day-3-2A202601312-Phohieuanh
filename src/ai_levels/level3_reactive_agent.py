"""
🧠 CẤP ĐỘ 3: REACTIVE AGENT (ReAct Loop — Thought → Action → Observation)

Dùng lại ĐÚNG vòng lặp production trong `src/app.py`, không viết bản rút gọn riêng
— demo mà khác code thật thì demo vô nghĩa.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import run_react_agent  # noqa: E402
from providers import get_llm_provider  # noqa: E402

if __name__ == "__main__":
    print("=== DEMO CẤP ĐỘ 3: REACTIVE AGENT (ReAct Loop) ===")
    trace = run_react_agent(
        "Đơn EXP-2026-0144 có duyệt được không?", get_llm_provider()
    )

    print(f"\n💡 Đã gọi {len(trace['tools_called'])} tool: "
          f"{', '.join(trace['tools_called']) or 'không có'}")
    print(f"   Trong đó thành công: {', '.join(trace['successful_tools']) or 'không có'}")
    print(f"   Guardrail kích hoạt: {', '.join(sorted(set(trace['guardrails']))) or 'không có'}")
    print("\n   Khác Cấp 2 ở chỗ: mọi con số trong câu trả lời đều lấy từ Observation thật, "
          "không phải LLM tự bịa.")
