"""
🚀 CẤP ĐỘ 4: AUTONOMOUS AGENT (Agent tự chủ với Planning, Self-Evaluation & Memory)

Khác biệt so với Cấp 3 (ReAct): Cấp 3 phản ứng từng bước một, không biết trước
mình sẽ đi bao xa. Cấp 4 tự RÃ MỤC TIÊU thành kế hoạch nhiều bước (Planner),
tự CHẤM ĐIỂM kết quả từng bước (Evaluator) và LƯU VẾT vào bộ nhớ (Memory) để
lập lại kế hoạch khi đi chệch hướng.

Vòng đời:  Planner → Executor → Evaluator → Memory → (Re-plan nếu cần) → Synthesize

Ba cơ chế Planning / Self-Eval / Memory ở đây mô phỏng kiến trúc production của
dự án AIchat (LangGraph ReAct + BERTScore guard + ChatHistoryService), thu nhỏ
lại cho phù hợp bài lab: BERTScore microservice → LLM-as-judge, MongoDB
chat_history → file JSON.
"""

import json
import os
import re
import sys

# Cho phép import tools.py / providers.py nằm ở thư mục src/ cha
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import AVAILABLE_TOOLS  # noqa: E402
from providers import get_llm_provider, OpenAIProvider  # noqa: E402
from llm_utils import call_llm, is_provider_error  # noqa: E402

# 🛡️ GUARDRAILS — phanh an toàn, tương ứng MAX_TOTAL_ITERATIONS / MAX_CONSECUTIVE_FAILURES của AIchat
MAX_STEPS = 6                 # Tổng số bước thực thi tối đa cho cả mục tiêu
MAX_REPLANS = 2               # Số lần được phép lập lại kế hoạch
MAX_CONSECUTIVE_FAILURES = 3  # Số lần tool lỗi liên tiếp thì dừng khẩn cấp
EVAL_THRESHOLD = 0.5          # Điểm tự đánh giá dưới ngưỡng này ⇒ coi như bước hỏng

MEMORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data"
)

TOOL_SPECS = """- get_weather(location: str): Tra cứu thời tiết hiện tại của một thành phố. Hỗ trợ 'Hà Nội', 'TP.HCM', 'Đà Nẵng'.
- search_flights(origin: str, destination: str): Tra cứu chuyến bay và giá vé giữa 2 thành phố."""


def _extract_json(text: str):
    """Bóc JSON ra khỏi output LLM (thường bị bọc trong ```json ... ```)."""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    match = re.search(r"[\{\[].*[\}\]]", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _build_judge_provider():
    """Provider riêng cho Evaluator, dùng model nhỏ LAB_MINI_MODEL nếu có."""
    mini = os.getenv("LAB_MINI_MODEL")
    if mini and (os.getenv("LLM_PROVIDER") or "").lower().strip() == "openai":
        print(f"[Agent] ⚖️ Evaluator dùng model phụ: {mini}")
        return OpenAIProvider(model=mini)
    return get_llm_provider()


class AutonomousAgent:
    """Agent tự chủ: tự lập kế hoạch, tự thực thi, tự chấm điểm và ghi nhớ."""

    def __init__(self, goal: str, provider=None, judge_provider=None, max_steps: int = MAX_STEPS):
        self.goal = goal
        # Model chính lo Planner / Executor / Synthesizer
        self.provider = provider or get_llm_provider()
        # Model nhỏ lo Evaluator — giống AIchat tách `/generate` (Qwen-7B) khỏi
        # `/evaluate` (Qwen-1.5B). Ở đây còn thêm lợi ích: quota Gemini tính
        # riêng theo từng model nên judge không ăn vào hạn mức của agent chính.
        self.judge_provider = judge_provider or _build_judge_provider()
        self.max_steps = max_steps
        self.memory = []          # Bộ nhớ episodic: mọi bước đã đi qua
        self.replans = 0
        self.consecutive_failures = 0
        self._seen_calls = set()  # Chống gọi lặp cùng tool + cùng tham số

    # ------------------------------------------------------------------ MEMORY
    def _remember(self, entry: dict) -> None:
        entry["step"] = len(self.memory) + 1
        self.memory.append(entry)
        print(f"💾 [Memory] Đã ghi bước {entry['step']}: {entry.get('subtask', '')[:60]}")

    def _memory_digest(self) -> str:
        """Nén bộ nhớ thành context ngắn để nạp lại cho Planner / Synthesizer."""
        if not self.memory:
            return "(chưa có bước nào)"
        lines = []
        for m in self.memory:
            lines.append(
                f"Bước {m['step']}: {m['subtask']}\n"
                f"  - Tool: {m.get('tool') or 'không dùng tool'}\n"
                f"  - Kết quả: {m.get('observation', '')}\n"
                f"  - Tự chấm: {m.get('score', 0):.2f} ({m.get('reason', '')})"
            )
        return "\n".join(lines)

    def _executed_calls_digest(self) -> str:
        """Liệt kê các lời gọi tool đã thực hiện — Planner PHẢI tránh lặp lại.

        Tương ứng Rule 3 trong system prompt của AIchat: "KHÔNG gọi lại cùng tool
        với cùng tham số nếu đã thất bại hoặc trả kết quả rỗng."
        """
        calls = [
            f"- {m['tool']}({json.dumps(m.get('args', {}), ensure_ascii=False)})"
            for m in self.memory if m.get("tool")
        ]
        return "\n".join(dict.fromkeys(calls)) if calls else "(chưa gọi tool nào)"

    def save_memory(self) -> str:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        path = os.path.join(MEMORY_DIR, "agent_memory.json")
        payload = {"goal": self.goal, "steps": self.memory}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return path

    # ----------------------------------------------------------------- PLANNER
    def _plan(self, feedback: str = "") -> list:
        """Tự rã mục tiêu lớn thành danh sách các bước con (goal decomposition)."""
        correction = ""
        if feedback:
            correction = (
                f"\n⚠️ KẾ HOẠCH TRƯỚC ĐÃ ĐI CHỆCH HƯỚNG. Phản hồi từ bộ đánh giá:\n{feedback}\n"
                f"Hãy lập kế hoạch MỚI khắc phục điểm yếu đó, KHÔNG lặp lại bước đã thành công."
            )

        prompt = f"""Bạn là Planner của một Autonomous Agent.

MỤC TIÊU CẦN ĐẠT: "{self.goal}"

CÔNG CỤ CÓ SẴN:
{TOOL_SPECS}

NHỮNG GÌ ĐÃ LÀM (bộ nhớ):
{self._memory_digest()}

⛔ CÁC LỜI GỌI TOOL ĐÃ THỰC HIỆN — TUYỆT ĐỐI KHÔNG lập kế hoạch gọi lại y hệt.
Dữ liệu của chúng đã nằm sẵn trong bộ nhớ ở trên, hãy DÙNG LẠI thay vì tra cứu lần nữa:
{self._executed_calls_digest()}
{correction}

Hãy rã mục tiêu thành TỐI ĐA {self.max_steps - len(self.memory)} bước con, mỗi bước
phải cụ thể và khả thi bằng công cụ ở trên (hoặc bằng suy luận tổng hợp).
Nếu dữ liệu còn thiếu KHÔNG thể lấy bằng công cụ hiện có, hãy lập bước tổng hợp
từ dữ liệu đã có thay vì cố gọi lại tool.

Chỉ trả về JSON array các chuỗi, không giải thích thêm. Ví dụ:
["Tra cứu thời tiết Hà Nội", "Tìm chuyến bay TP.HCM đến Hà Nội"]"""

        raw = call_llm(self.provider, prompt)
        if is_provider_error(raw):
            print(f"❌ [Planning] Không gọi được LLM: {raw[:160]}")
            return []

        plan = _extract_json(raw)
        if not isinstance(plan, list) or not plan:
            print(f"❌ [Planning] Kế hoạch trả về không hợp lệ: {raw[:160]}")
            return []

        plan = [str(p) for p in plan][: self.max_steps - len(self.memory)]
        print(f"\n📋 [Planning] Kế hoạch {len(plan)} bước:")
        for i, step in enumerate(plan, 1):
            print(f"    {i}. {step}")
        return plan

    # ---------------------------------------------------------------- EXECUTOR
    def _execute(self, subtask: str) -> dict:
        """Chọn tool phù hợp cho 1 bước con rồi thực thi (một nhịp ReAct)."""
        prompt = f"""Bạn là Executor của một Autonomous Agent.

MỤC TIÊU TỔNG: "{self.goal}"
BƯỚC CẦN LÀM NGAY: "{subtask}"

CÔNG CỤ CÓ SẴN:
{TOOL_SPECS}

DỮ LIỆU ĐÃ THU THẬP:
{self._memory_digest()}

Chọn ĐÚNG MỘT công cụ để hoàn thành bước này. Nếu bước này chỉ cần tổng hợp
dữ liệu đã có mà không cần công cụ, đặt "tool" là null và viết kết quả tổng hợp
bằng tiếng Việt vào "answer".

Chỉ trả về JSON, không giải thích:
{{"tool": "get_weather", "args": {{"location": "Hà Nội"}}, "answer": null}}
hoặc
{{"tool": null, "args": {{}}, "answer": "nội dung tổng hợp bằng tiếng Việt"}}"""

        raw = call_llm(self.provider, prompt)
        if is_provider_error(raw):
            return {"tool": None, "observation": raw, "ok": False}

        decision = _extract_json(raw)
        if not isinstance(decision, dict):
            return {"tool": None, "observation": f"LỖI: Executor trả JSON hỏng — {raw[:120]}", "ok": False}

        tool_name = decision.get("tool")
        args = decision.get("args") or {}

        # Không dùng tool → tổng hợp bằng suy luận
        if not tool_name:
            answer = decision.get("answer") or ""
            print(f"🧠 [Execution] Không cần tool, tổng hợp từ bộ nhớ.")
            return {"tool": None, "args": {}, "observation": answer, "ok": bool(answer.strip())}

        if tool_name not in AVAILABLE_TOOLS:
            return {
                "tool": tool_name,
                "args": args,
                "observation": f"LỖI: Tool '{tool_name}' không tồn tại trong registry.",
                "ok": False,
            }

        # 🛡️ Guardrail chống lặp: cùng tool + cùng tham số đã gọi rồi thì chặn
        signature = f"{tool_name}::{json.dumps(args, sort_keys=True, ensure_ascii=False).lower()}"
        if signature in self._seen_calls:
            print(f"🛑 [Guardrail] Chặn gọi lặp: {tool_name}({args})")
            return {
                "tool": tool_name,
                "args": args,
                "observation": "LỖI: Bước này lặp lại y hệt một lời gọi đã thực hiện trước đó.",
                "ok": False,
            }
        self._seen_calls.add(signature)

        print(f"🛠️ [Execution] {tool_name}({args})")
        try:
            observation = AVAILABLE_TOOLS[tool_name](**args)
        except TypeError as e:
            observation = f"LỖI: Sai tham số cho '{tool_name}' — {e}"
        ok = not observation.startswith("LỖI")
        print(f"👁️ [Observation] {observation}")
        return {"tool": tool_name, "args": args, "observation": observation, "ok": ok}

    # --------------------------------------------------------------- EVALUATOR
    def _evaluate(self, subtask: str, observation: str) -> dict:
        """LLM-as-judge: chấm xem kết quả có bám dữ liệu và có đưa mục tiêu tiến lên không.

        Tương ứng lớp BERTScore guard + semantic_filter `/evaluate` của AIchat.
        """
        prompt = f"""Bạn là Evaluator (giám khảo) của một Autonomous Agent. Hãy chấm KHÁCH QUAN.

MỤC TIÊU TỔNG: "{self.goal}"
BƯỚC ĐÃ THỰC HIỆN: "{subtask}"
KẾT QUẢ THU ĐƯỢC: "{observation}"

TOÀN BỘ TIẾN ĐỘ:
{self._memory_digest()}

Chấm theo 2 tiêu chí:
- score (0.0 đến 1.0): kết quả có thực sự giải quyết bước con này và bám sát dữ liệu thật không.
  Nếu kết quả là thông báo lỗi hoặc rỗng, cho điểm dưới 0.3.
- goal_complete (true/false): TOÀN BỘ mục tiêu tổng đã đủ dữ liệu để kết luận chưa.

Chỉ trả về JSON, không giải thích:
{{"score": 0.9, "goal_complete": false, "reason": "lý do ngắn gọn bằng tiếng Việt"}}"""

        raw = call_llm(self.judge_provider, prompt)
        verdict = _extract_json(raw)

        # Fallback an toàn: LLM judge hỏng thì KHÔNG chặn bước (giống BERTScore lỗi → return 1.0)
        if not isinstance(verdict, dict):
            print("⚠️ [Evaluator] Judge trả JSON hỏng — bỏ qua, không chặn bước.")
            return {"score": 1.0, "goal_complete": False, "reason": "evaluator lỗi, bỏ qua"}

        try:
            score = float(verdict.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))
        result = {
            "score": score,
            "goal_complete": bool(verdict.get("goal_complete", False)),
            "reason": str(verdict.get("reason", "")),
        }
        flag = "✅" if score >= EVAL_THRESHOLD else "❌"
        print(f"⚖️ [Self-Eval] {flag} score={score:.2f} | goal_complete={result['goal_complete']} | {result['reason']}")
        return result

    # ------------------------------------------------------------- SYNTHESIZER
    def _synthesize(self) -> str:
        prompt = f"""Bạn là Autonomous Agent đang tổng kết công việc.

MỤC TIÊU: "{self.goal}"

TOÀN BỘ DỮ LIỆU ĐÃ THU THẬP:
{self._memory_digest()}

Viết câu trả lời cuối cùng bằng TIẾNG VIỆT cho người dùng. CHỈ dùng số liệu có
thật trong dữ liệu trên, TUYỆT ĐỐI không bịa thêm. Không viết tiền tố
"Final Answer:" hay "Thought:"."""
        answer = call_llm(self.provider, prompt)
        if is_provider_error(answer):
            return f"⚠️ Không tổng hợp được câu trả lời cuối: {answer}"
        return answer.strip()

    # --------------------------------------------------------------------- RUN
    def run(self) -> str:
        print(f"🚀 === AUTONOMOUS GOAL: {self.goal} ===")
        plan = self._plan()
        goal_complete = False

        while len(self.memory) < self.max_steps:
            if not plan:
                # Hết kế hoạch mà mục tiêu chưa xong → lập lại kế hoạch
                if goal_complete or self.replans >= MAX_REPLANS:
                    break
                self.replans += 1
                print(f"\n🔁 [Re-plan {self.replans}/{MAX_REPLANS}] Kế hoạch cũ đã hết, mục tiêu chưa xong.")
                plan = self._plan(feedback="Kế hoạch trước chưa đủ để hoàn thành mục tiêu.")
                continue

            subtask = plan.pop(0)
            print(f"\n--- 🔄 Bước {len(self.memory) + 1}/{self.max_steps}: {subtask} ---")

            outcome = self._execute(subtask)
            verdict = self._evaluate(subtask, outcome["observation"])

            self._remember({
                "subtask": subtask,
                "tool": outcome.get("tool"),
                "args": outcome.get("args", {}),
                "observation": outcome["observation"],
                "score": verdict["score"],
                "reason": verdict["reason"],
            })

            step_failed = (not outcome["ok"]) or verdict["score"] < EVAL_THRESHOLD
            if step_failed:
                self.consecutive_failures += 1
                # 🛡️ Guardrail: quá nhiều lỗi liên tiếp thì dừng khẩn cấp
                if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print(f"\n🛑 [Guardrail] {self.consecutive_failures} bước hỏng liên tiếp — DỪNG KHẨN CẤP.")
                    break
                # Bước hỏng → vứt phần kế hoạch còn lại và lập lại kế hoạch
                if self.replans < MAX_REPLANS:
                    self.replans += 1
                    print(f"\n🔁 [Re-plan {self.replans}/{MAX_REPLANS}] Bước vừa rồi chưa đạt, điều chỉnh kế hoạch.")
                    plan = self._plan(feedback=f"Bước '{subtask}' thất bại: {verdict['reason']}")
                continue

            self.consecutive_failures = 0
            if verdict["goal_complete"]:
                goal_complete = True
                print("\n🎯 [Goal Evaluation] Agent tự xác định MỤC TIÊU ĐÃ HOÀN THÀNH — dừng sớm.")
                break

        if len(self.memory) >= self.max_steps and not goal_complete:
            print(f"\n🛑 [Guardrail] Đã dùng hết {self.max_steps} bước — dừng theo giới hạn an toàn.")

        print("\n=== 🏁 TỔNG HỢP KẾT QUẢ ===")
        final = self._synthesize()
        print(final)

        path = self.save_memory()
        print(f"\n💾 [Memory] Đã lưu {len(self.memory)} bước vào: {path}")
        return final


if __name__ == "__main__":
    print("=== DEMO CẤP ĐỘ 4: AUTONOMOUS AGENT (Planning + Self-Eval + Memory) ===\n")
    agent = AutonomousAgent(
        "Lên kế hoạch chuyến đi Hà Nội 3 ngày 2 đêm khởi hành từ TP.HCM: "
        "cần biết thời tiết điểm đến, chuyến bay phù hợp và gợi ý trang phục."
    )
    agent.run()
