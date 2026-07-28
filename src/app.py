"""
🚀 CORE AGENT APP (Dành cho Role 4: Core Agent Developer)
File chính ghép nối tất cả các thành phần: Tools + Prompts + Test Cases + Multi-Provider.
"""

import json
import os
import re
import sys
from dotenv import load_dotenv

# Đảm bảo import các module cùng thư mục src/ hoạt động mượt mà
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Đảm bảo in ra Tiếng Việt và Emojis không bị lỗi trên Windows Console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Import các thành phần từ file của Role 2, Role 3 & Multi-Provider Adapter
from tools import AVAILABLE_TOOLS, get_weather, search_flights
from prompts import CHATBOT_BASELINE_PROMPT, REACT_SYSTEM_PROMPT, MAX_ITERATIONS
from providers import get_llm_provider
from llm_utils import call_llm, is_provider_error

load_dotenv()

def load_test_cases():
    """Đọc bộ test cases từ config/test_cases.json của Role 1"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "test_cases.json")
    
    # Fallback kiểm tra nếu file ở thư mục hiện tại
    if not os.path.exists(config_path):
        config_path = "test_cases.json"
        
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_baseline_chatbot(user_query: str, provider) -> str:
    """
    Dựng Chatbot gốc (Baseline) không có công cụ.
    """
    print(f"\n💬 [CHATBOT BASELINE] Câu hỏi: {user_query}")

    # Gọi LLM Provider thực hiện sinh câu trả lời
    response = call_llm(provider, user_query, system_prompt=CHATBOT_BASELINE_PROMPT)
    print(f"🤖 Chatbot trả lời:\n{response}")
    return response


def parse_react_output(text: str) -> dict:
    """
    Bóc `Thought` / `Action` / `Final Answer` từ output thô của LLM.

    Guardrail quan trọng: cắt bỏ mọi thứ sau 'Observation:' — LLM hay tự bịa
    Observation của chính nó thay vì dừng lại chờ hệ thống thực thi tool.
    """
    obs_idx = text.find("Observation:")
    if obs_idx != -1:
        print("⚠️ [Parser] LLM tự viết 'Observation:' — cắt bỏ phần bịa.")
        text = text[:obs_idx]

    thought_match = re.search(r"Thought:\s*(.+)", text)
    thought = thought_match.group(1).strip() if thought_match else ""

    # Ưu tiên Action hơn Final Answer: khi LLM viết cả hai, phải thực thi tool trước
    action_match = re.search(r"Action:\s*(\w+)\s*\[(.*?)\]", text, re.DOTALL)
    if action_match:
        raw_args = action_match.group(2).strip()
        args = [a.strip().strip("'\"") for a in raw_args.split(",")] if raw_args else []
        return {"type": "action", "thought": thought, "tool": action_match.group(1), "args": args}

    final_match = re.search(r"Final Answer:\s*(.*)", text, re.DOTALL)
    if final_match:
        return {"type": "final", "thought": thought, "answer": final_match.group(1).strip()}

    return {"type": "parse_error", "thought": thought, "raw": text.strip()}


def run_react_agent(user_query: str, provider) -> dict:
    """
    Dựng vòng lặp ReAct Agent (Thought -> Action -> Observation) có Guardrails.

    Vòng lặp do LLM điều khiển thật: mỗi bước nạp scratchpad tích luỹ vào prompt,
    LLM tự quyết định gọi tool nào hay đã đủ thông tin để Final Answer.

    Trả về dict trace để `run_tests.py` chấm được: answer, số bước đã dùng,
    danh sách tool đã gọi và guardrail nào đã kích hoạt.
    """
    print(f"\n🤖 [REACT AGENT] Câu hỏi: {user_query}")
    scratchpad = ""
    seen_calls = set()   # 🛡️ Guardrail chống gọi lặp cùng tool + cùng tham số
    tools_called = []
    guardrails = []

    for step in range(1, MAX_ITERATIONS + 1):
        print(f"\n--- 🔄 Vòng lặp ReAct (Step {step}/{MAX_ITERATIONS}) ---")

        prompt = f"{REACT_SYSTEM_PROMPT}\nCâu hỏi: {user_query}\n{scratchpad}"
        raw = call_llm(provider, prompt)
        if is_provider_error(raw):
            print(f"❌ Lỗi gọi LLM: {raw}")
            return {"answer": raw, "steps": step, "tools_called": tools_called,
                    "guardrails": guardrails + ["llm_error"], "ok": False}

        parsed = parse_react_output(raw)
        if parsed["thought"]:
            print(f"🧠 Thought: {parsed['thought']}")

        if parsed["type"] == "final":
            print(f"🏁 Final Answer: {parsed['answer']}")
            return {"answer": parsed["answer"], "steps": step, "tools_called": tools_called,
                    "guardrails": guardrails, "ok": True}

        if parsed["type"] == "parse_error":
            print("⚠️ Output sai định dạng — yêu cầu LLM làm lại đúng khuôn.")
            guardrails.append("parse_error")
            scratchpad += (
                "\nObservation: LỖI ĐỊNH DẠNG. Bạn phải trả lời theo đúng khuôn "
                "'Thought: ... / Action: tên_tool[tham_số]' hoặc 'Thought: ... / Final Answer: ...'.\n"
            )
            continue

        tool_name, args = parsed["tool"], parsed["args"]
        print(f"🛠️ Action: {tool_name}[{', '.join(args)}]")

        signature = f"{tool_name}::{'|'.join(a.lower() for a in args)}"
        if signature in seen_calls:
            observation = "LỖI: Bạn đã gọi y hệt lời gọi này rồi. Dùng lại kết quả ở trên, đừng gọi lại."
            print(f"🛑 [Guardrail] Chặn gọi lặp: {tool_name}[{', '.join(args)}]")
            guardrails.append("duplicate_call")
        elif tool_name not in AVAILABLE_TOOLS:
            observation = f"LỖI: Tool '{tool_name}' không tồn tại. Chỉ có: {', '.join(AVAILABLE_TOOLS)}."
            guardrails.append("unknown_tool")
        else:
            seen_calls.add(signature)
            tools_called.append(tool_name)
            try:
                observation = AVAILABLE_TOOLS[tool_name](*args)
                if observation.startswith("LỖI"):
                    guardrails.append("tool_error")
            except TypeError as e:
                observation = f"LỖI: Sai số lượng tham số cho '{tool_name}' — {e}"
                guardrails.append("bad_args")

        print(f"👁️ Observation: {observation}")
        scratchpad += f"\nThought: {parsed['thought']}\nAction: {tool_name}[{', '.join(args)}]\nObservation: {observation}\n"

    # 🛡️ Hết số vòng cho phép mà chưa có Final Answer
    print(f"🛡️ GUARDRAIL TRIGGERED: Đã đạt giới hạn tối đa {MAX_ITERATIONS} bước. Ngắt lặp an toàn!")
    return {
        "answer": (
            f"⚠️ Agent đã dùng hết {MAX_ITERATIONS} bước suy luận mà chưa kết luận được. "
            f"Vui lòng đặt lại câu hỏi cụ thể hơn."
        ),
        "steps": MAX_ITERATIONS,
        "tools_called": tools_called,
        "guardrails": guardrails + ["max_iterations"],
        "ok": False,
    }


if __name__ == "__main__":
    print("==================================================")
    print("🏫 ĐẠI HỌC VINUNI - BÀI LAB 3: CHATBOT VS REACT AGENT")
    print("==================================================")
    
    # Khởi tạo Multi-Provider LLM Adapter (Đọc từ biến môi trường LLM_PROVIDER)
    provider = get_llm_provider()
    model_name = getattr(provider, "model_name", "Offline Mock Mode")
    print(f"🔌 LLM Provider đang hoạt động: {provider.__class__.__name__} (Model: {model_name})")
    
    tests = load_test_cases()
    print(f"✅ Đã tải thành công {len(tests)} Test Cases từ config/test_cases.json\n")
    
    # Chạy thử câu test số 3
    sample_query = tests[2]["question"]
    
    print("--- DEMO 1: CHẠY TRÊN CHATBOT BASELINE ---")
    run_baseline_chatbot(sample_query, provider)
    
    print("\n--- DEMO 2: CHẠY TRÊN REACT AGENT ---")
    run_react_agent(sample_query, provider)
