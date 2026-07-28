"""
🚀 CORE AGENT APP (Dành cho Role 4: Core Agent Developer)
File chính ghép nối tất cả các thành phần: Tools + Prompts + Test Cases + Multi-Provider.
"""

import inspect
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
from tools import AVAILABLE_TOOLS
from prompts import CHATBOT_BASELINE_PROMPT, REACT_SYSTEM_PROMPT, MAX_ITERATIONS
from providers import get_llm_provider
from llm_utils import call_llm, is_provider_error

load_dotenv()

# 🛡️ Guardrail tầng CODE cho write action.
# Prompt đã cấm, nhưng prompt có thể bị LLM phớt lờ hoặc bị người dùng lừa — nên
# chặn thêm một tầng ở đây. Hai tầng tồn tại có chủ đích.
#
# Tiền đề tính trên tool gọi THÀNH CÔNG, không phải tool đã gọi. Nếu tính theo số
# lần gọi thì chỉ cần gọi 3 tool với tham số rác (cả 3 đều trả LỖI) là mở được
# khoá — đó là đường lách, không phải guardrail.
TOOL_PRECONDITIONS = {
    "submit_decision": ["get_policy", "check_budget", "find_duplicate_claims"],
}

# Tool nào "mở hồ sơ" một đơn, và tool nào ghi quyết định cho đơn đó. Quyết định
# chỉ được ghi cho đơn đã thực sự mở hồ sơ thành công trong phiên này.
TOOL_OPENS_SUBJECT = "get_expense_report"
TOOL_DECIDES_SUBJECT = "submit_decision"

# Scratchpad được nạp lại vào prompt MỖI vòng. Với nhiều vòng và observation dài
# (get_expense_report trả cả bảng line item) thì prompt phình rất nhanh — tốn
# token và có thể tràn context. Giữ phần MỚI NHẤT vì nó sát ngữ cảnh hiện tại.
MAX_SCRATCHPAD_CHARS = 6000


def _truncate_scratchpad(scratchpad: str):
    """Cắt bớt phần đầu nếu scratchpad quá dài. Trả về (nội_dung, đã_cắt)."""
    if len(scratchpad) <= MAX_SCRATCHPAD_CHARS:
        return scratchpad, False
    return (
        "\n[... phần đầu đã lược bớt cho gọn ...]\n" + scratchpad[-MAX_SCRATCHPAD_CHARS:],
        True,
    )


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


# Anchor do LLM sinh ra rất hay bị bọc markdown (`**Action:**`), viết thường, hoặc
# đứng sau bullet (`- Action:`). Chuẩn hoá về dạng chuẩn TRƯỚC khi parse.
# Chỉ đụng phần anchor ở ĐẦU DÒNG — tuyệt đối không chạm nội dung tham số, nếu
# không sẽ nuốt mất dấu _ trong tên hạng mục như 'an_uong'.
_ANCHOR_RE = re.compile(
    r"(?im)^[ \t]*(?:[-*>#]+[ \t]*)*\**[ \t]*"
    r"(Thought|Action Input|Action|Final Answer|Observation)"
    r"[ \t]*\**[ \t]*:[ \t]*\**"
)

_ANCHOR_CANON = {
    "thought": "Thought",
    "action input": "Action Input",
    "action": "Action",
    "final answer": "Final Answer",
    "observation": "Observation",
}

# Thought có thể dài nhiều dòng — lấy tới anchor kế tiếp thay vì chỉ dòng đầu,
# nếu không scratchpad mất ngữ cảnh và LLM lặp lại đúng suy luận cũ.
_THOUGHT_RE = re.compile(
    r"Thought:\s*(.*?)(?=\n[ \t]*(?:Action|Action Input|Final Answer|Observation):|\Z)",
    re.DOTALL,
)


def _normalize_anchors(text: str) -> str:
    """Đưa mọi biến thể anchor về đúng dạng 'Thought:' / 'Action:' / ..."""
    return _ANCHOR_RE.sub(lambda m: _ANCHOR_CANON[m.group(1).lower()] + ": ", text)


def _tool_arity(tool_name: str):
    """Số tham số của tool, hoặc None nếu không biết tool đó."""
    fn = AVAILABLE_TOOLS.get(tool_name)
    if fn is None:
        return None
    return len(inspect.signature(fn).parameters)


def _split_args(raw: str, tool_name: str) -> list:
    """Tách tham số theo ĐÚNG số tham số mà tool nhận.

    Tham số cuối của `submit_decision` là lý do dạng văn bản tự do — LLM chắc chắn
    viết dấu phẩy trong đó. Giới hạn số lần tách để phần đuôi được giữ nguyên vẹn.
    Cũng nhờ vậy mà số tiền '2,400,000' không bị xé thành ba tham số.
    """
    if not raw.strip():
        return []
    arity = _tool_arity(tool_name)
    if arity is None or arity < 1:
        parts = raw.split(",")          # tool lạ — guardrail unknown_tool sẽ bắt
    else:
        parts = raw.split(",", arity - 1)
    return [p.strip().strip("'\"") for p in parts]


def parse_react_output(text: str) -> dict:
    """
    Bóc `Thought` / `Action` / `Final Answer` từ output thô của LLM.

    Guardrail quan trọng: cắt bỏ mọi thứ sau 'Observation:' — LLM hay tự bịa
    Observation của chính nó thay vì dừng lại chờ hệ thống thực thi tool.
    """
    text = _normalize_anchors(text)

    obs_idx = text.find("Observation:")
    if obs_idx != -1:
        print("⚠️ [Parser] LLM tự viết 'Observation:' — cắt bỏ phần bịa.")
        text = text[:obs_idx]

    thought_match = _THOUGHT_RE.search(text)
    thought = thought_match.group(1).strip() if thought_match else ""

    # Ưu tiên bám cuối dòng để lấy dấu ']' NGOÀI CÙNG — lý do từ chối hay dẫn
    # chiếu kiểu '[xem policy]', regex non-greedy sẽ cắt cụt ở dấu ] đầu tiên.
    action_match = re.search(r"(?m)^.*?Action:\s*(\w+)\s*\[(.*)\][ \t]*$", text)
    if not action_match:
        # Dự phòng: LLM viết thêm chữ đuôi sau dấu ']'
        action_match = re.search(r"Action:\s*(\w+)\s*\[(.*?)\]", text, re.DOTALL)

    # Ưu tiên Action hơn Final Answer: khi LLM viết cả hai, phải thực thi tool trước
    if action_match:
        tool_name = action_match.group(1)
        args = _split_args(action_match.group(2).strip(), tool_name)
        return {"type": "action", "thought": thought, "tool": tool_name, "args": args}

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
    seen_calls = set()      # 🛡️ Guardrail chống gọi lặp cùng tool + cùng tham số
    tools_called = []       # mọi tool đã cố gọi
    successful_tools = []   # chỉ tool chạy xong KHÔNG trả LỖI — dùng để xét tiền đề
    investigated = set()    # report_id đã mở hồ sơ thành công
    decided = set()         # report_id đã ghi quyết định
    guardrails = []

    def _trace(answer, step, ok):
        return {"answer": answer, "steps": step, "tools_called": tools_called,
                "successful_tools": successful_tools, "guardrails": guardrails, "ok": ok}

    for step in range(1, MAX_ITERATIONS + 1):
        print(f"\n--- 🔄 Vòng lặp ReAct (Step {step}/{MAX_ITERATIONS}) ---")

        scratchpad, da_cat = _truncate_scratchpad(scratchpad)
        if da_cat and "scratchpad_truncated" not in guardrails:
            guardrails.append("scratchpad_truncated")

        prompt = f"{REACT_SYSTEM_PROMPT}\nCâu hỏi: {user_query}\n{scratchpad}"
        raw = call_llm(provider, prompt)
        if is_provider_error(raw):
            print(f"❌ Lỗi gọi LLM: {raw}")
            guardrails.append("llm_error")
            return _trace(raw, step, False)

        parsed = parse_react_output(raw)
        if parsed["thought"]:
            print(f"🧠 Thought: {parsed['thought']}")

        if parsed["type"] == "final":
            print(f"🏁 Final Answer: {parsed['answer']}")
            return _trace(parsed["answer"], step, True)

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
        subject = args[0].strip().upper() if args else ""
        # Tiền đề xét trên successful_tools, KHÔNG phải tools_called — xem chú
        # thích ở TOOL_PRECONDITIONS.
        thieu = [t for t in TOOL_PRECONDITIONS.get(tool_name, []) if t not in successful_tools]

        if signature in seen_calls:
            observation = "LỖI: Bạn đã gọi y hệt lời gọi này rồi. Dùng lại kết quả ở trên, đừng gọi lại."
            print(f"🛑 [Guardrail] Chặn gọi lặp: {tool_name}[{', '.join(args)}]")
            guardrails.append("duplicate_call")
        elif tool_name not in AVAILABLE_TOOLS:
            observation = f"LỖI: Tool '{tool_name}' không tồn tại. Chỉ có: {', '.join(AVAILABLE_TOOLS)}."
            guardrails.append("unknown_tool")
        elif tool_name == TOOL_DECIDES_SUBJECT and subject in decided:
            observation = (
                f"LỖI: Đơn {subject} đã có quyết định rồi, không được ghi đè. Nếu cần "
                f"đổi, hãy nêu rõ trong Final Answer thay vì ghi lại."
            )
            print(f"🛑 [Guardrail] Chặn ghi đè quyết định đơn {subject}")
            guardrails.append("already_decided")
        elif tool_name == TOOL_DECIDES_SUBJECT and subject not in investigated:
            observation = (
                f"LỖI: Chưa mở hồ sơ đơn {subject}. Phải gọi "
                f"{TOOL_OPENS_SUBJECT}[{subject}] thành công trước khi ghi quyết định."
            )
            print(f"🛑 [Guardrail] Chặn ghi quyết định cho đơn chưa điều tra: {subject}")
            guardrails.append("subject_mismatch")
        elif thieu:
            observation = (
                f"LỖI: Chưa đủ căn cứ để gọi '{tool_name}'. Bắt buộc phải có kết quả "
                f"THÀNH CÔNG của {', '.join(thieu)} trước đã."
            )
            print(f"🛑 [Guardrail] Chặn '{tool_name}' — thiếu tiền đề: {', '.join(thieu)}")
            guardrails.append("precondition_violated")
        else:
            seen_calls.add(signature)
            tools_called.append(tool_name)
            try:
                # str() bọc ngoài: tool lỡ trả về không phải chuỗi thì .startswith
                # sẽ ném AttributeError làm sập cả vòng lặp.
                observation = str(AVAILABLE_TOOLS[tool_name](*args))
                if observation.startswith("LỖI"):
                    guardrails.append("tool_error")
                else:
                    successful_tools.append(tool_name)
                    if tool_name == TOOL_OPENS_SUBJECT and subject:
                        investigated.add(subject)
                    elif tool_name == TOOL_DECIDES_SUBJECT and subject:
                        decided.add(subject)
            except TypeError as e:
                observation = f"LỖI: Sai số lượng tham số cho '{tool_name}' — {e}"
                guardrails.append("bad_args")

        print(f"👁️ Observation: {observation}")
        scratchpad += f"\nThought: {parsed['thought']}\nAction: {tool_name}[{', '.join(args)}]\nObservation: {observation}\n"

    # 🛡️ Hết số vòng cho phép mà chưa có Final Answer
    print(f"🛡️ GUARDRAIL TRIGGERED: Đã đạt giới hạn tối đa {MAX_ITERATIONS} bước. Ngắt lặp an toàn!")
    guardrails.append("max_iterations")
    return _trace(
        f"⚠️ Agent đã dùng hết {MAX_ITERATIONS} bước suy luận mà chưa kết luận được. "
        f"Vui lòng đặt lại câu hỏi cụ thể hơn.",
        MAX_ITERATIONS,
        False,
    )


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
