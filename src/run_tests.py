"""
🧪 BỘ CHẠY TEST (Dành cho Role 1 & Role 5)

Chạy toàn bộ test cases trong `config/test_cases.json` qua CẢ HAI đường:
Chatbot Baseline (Cấp 2) và ReAct Agent (Cấp 3), rồi xuất báo cáo so sánh
ra `docs/test_results.md` làm artifact chấm điểm.

Cách dùng:
    python src/run_tests.py                  # chạy cả 5 case, cả 2 chế độ
    python src/run_tests.py --cases 3,5      # chỉ chạy case 3 và 5
    python src/run_tests.py --mode react     # chỉ chạy ReAct Agent

⚠️ Gemini free tier: 5 request/phút VÀ 20 request/ngày, tính riêng từng model.
Chạy đủ 5 case mất vài phút vì `call_llm()` phải chờ hạn mức phút. Nếu hết hạn
mức NGÀY, dùng `--model` đổi sang model khác (hạn mức riêng) thay vì chờ.
"""

import argparse
import json
import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from app import load_test_cases, run_baseline_chatbot, run_react_agent  # noqa: E402
from providers import get_llm_provider  # noqa: E402

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_PATH = os.path.join(BASE_DIR, "docs", "test_results.md")


def _expects_tool(case: dict) -> bool:
    """Case thuộc nhóm Multi-step/Edge case thì Agent BẮT BUỘC phải gọi tool."""
    return "🟢" not in case.get("category", "")


def judge(case: dict, trace: dict) -> tuple:
    """Chấm PASS/FAIL theo `expected_behavior` của Role 1.

    Tiêu chí kiểm được bằng máy (không nhờ LLM chấm để tránh vòng lặp tự khen):
    - Case 🟢 đơn giản  : agent KHÔNG được gọi tool thừa, phải ra Final Answer.
    - Case 🟡 multi-step: PHẢI gọi ít nhất 1 tool và ra Final Answer.
    - Case 🔴 edge case : tool phải báo lỗi VÀ guardrail phải kích hoạt.
    """
    tools, guards, ok = trace["tools_called"], trace["guardrails"], trace["ok"]
    category = case.get("category", "")

    # Lỗi hạ tầng (API 429/401...) KHÔNG phải guardrail — không được tính là PASS,
    # vì như vậy case nào cũng "đạt" chỉ nhờ hết quota.
    if "llm_error" in guards:
        return False, "LỖI HẠ TẦNG: không gọi được LLM (hết quota / sai key) — case chưa thực sự được kiểm tra"

    real_guards = [g for g in guards if g != "llm_error"]

    if "🔴" in category:
        if real_guards and not ok:
            return True, f"Guardrail kích hoạt đúng ({', '.join(sorted(set(real_guards)))}) và agent không bịa câu trả lời"
        if real_guards:
            return True, f"Guardrail kích hoạt ({', '.join(sorted(set(real_guards)))}), agent kết luận có kiểm soát"
        return False, "KHÔNG guardrail nào kích hoạt — agent có thể đã bịa dữ liệu"

    if "🟢" in category:
        if not ok:
            return False, "Câu đơn giản mà agent không đưa được Final Answer"
        if tools:
            return False, f"Gọi tool thừa ({', '.join(tools)}) cho câu chỉ cần kiến thức LLM"
        return True, "Trả lời trực tiếp, không gọi tool thừa"

    # 🟡 Multi-step
    if not ok:
        return False, "Không đưa được Final Answer trong giới hạn bước"
    if not tools:
        return False, "KHÔNG gọi tool nào — câu này cần dữ liệu thời gian thực"
    return True, f"Đã gọi {len(tools)} tool ({', '.join(tools)}) rồi mới kết luận"


def write_report(results: list, mode: str) -> str:
    passed = sum(1 for r in results if r.get("passed"))
    total = len(results)

    lines = [
        "# 🧪 KẾT QUẢ CHẠY TEST CASES",
        "",
        f"*Sinh tự động bởi `src/run_tests.py` lúc {datetime.now():%Y-%m-%d %H:%M}*  ",
        f"*Chế độ: `{mode}` — Kết quả: **{passed}/{total} PASS***",
        "",
        "## Bảng tổng hợp",
        "",
        "| # | Nhóm | Câu hỏi | Tool đã gọi | Bước | Guardrail | Kết quả |",
        "| :-: | :--- | :--- | :--- | :-: | :--- | :-: |",
    ]
    for r in results:
        if "passed" not in r:
            continue
        tools = ", ".join(r["trace"]["tools_called"]) or "—"
        guards = ", ".join(sorted(set(r["trace"]["guardrails"]))) or "—"
        question = r["case"]["question"].replace("|", "\\|")
        lines.append(
            f"| {r['case']['id']} | {r['case']['category']} | {question} | "
            f"{tools} | {r['trace']['steps']} | {guards} | "
            f"{'✅ PASS' if r['passed'] else '❌ FAIL'} |"
        )

    lines += ["", "## Chi tiết từng case", ""]
    for r in results:
        case = r["case"]
        lines += [
            f"### Case {case['id']} — {case['category']}",
            "",
            f"**Câu hỏi:** {case['question']}  ",
            f"**Kỳ vọng (Role 1):** {case['expected_behavior']}",
            "",
        ]
        if "baseline" in r:
            lines += ["**🤖 Chatbot Baseline (Cấp 2):**", "", "```text",
                      r["baseline"].strip()[:900], "```", ""]
        if "trace" in r:
            trace = r["trace"]
            lines += [
                "**🧠 ReAct Agent (Cấp 3):**",
                "",
                f"* Tool đã gọi: `{', '.join(trace['tools_called']) or 'không có'}`",
                f"* Số bước dùng: {trace['steps']}/{r['max_iterations']}",
                f"* Guardrail: `{', '.join(sorted(set(trace['guardrails']))) or 'không có'}`",
                "",
                "```text",
                trace["answer"].strip()[:900],
                "```",
                "",
                f"**Chấm:** {'✅ PASS' if r['passed'] else '❌ FAIL'} — {r['reason']}",
                "",
            ]
        lines.append("---")
        lines.append("")

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return REPORT_PATH


def main():
    parser = argparse.ArgumentParser(description="Chạy test cases qua Chatbot Baseline và ReAct Agent")
    parser.add_argument("--cases", help="Danh sách id case, ví dụ: 1,3,5 (mặc định: tất cả)")
    parser.add_argument("--mode", choices=["both", "chatbot", "react"], default="both",
                        help="Chạy chế độ nào (mặc định: both)")
    parser.add_argument("--model", help="Ghi đè LLM_MODEL, ví dụ: gemini-3.5-flash-lite "
                                        "(mỗi model có hạn mức free tier RIÊNG)")
    args = parser.parse_args()

    if args.model:
        os.environ["LLM_MODEL"] = args.model

    from prompts import MAX_ITERATIONS

    cases = load_test_cases()
    if args.cases:
        wanted = {int(c.strip()) for c in args.cases.split(",")}
        cases = [c for c in cases if c["id"] in wanted]

    provider = get_llm_provider()
    model_name = getattr(provider, "model_name", "Offline Mock Mode")
    print("=" * 70)
    print(f"🧪 CHẠY {len(cases)} TEST CASE — Provider: {provider.__class__.__name__} ({model_name})")
    print(f"   Chế độ: {args.mode} | Giới hạn ReAct: {MAX_ITERATIONS} bước")
    print("=" * 70)

    results = []
    for case in cases:
        print(f"\n{'=' * 70}\n📌 CASE {case['id']} — {case['category']}\n{'=' * 70}")
        record = {"case": case, "max_iterations": MAX_ITERATIONS}

        if args.mode in ("both", "chatbot"):
            record["baseline"] = run_baseline_chatbot(case["question"], provider)

        if args.mode in ("both", "react"):
            trace = run_react_agent(case["question"], provider)
            record["trace"] = trace
            record["passed"], record["reason"] = judge(case, trace)
            print(f"\n{'✅ PASS' if record['passed'] else '❌ FAIL'} — {record['reason']}")

        results.append(record)

    print(f"\n{'=' * 70}\n📊 TỔNG KẾT\n{'=' * 70}")
    scored = [r for r in results if "passed" in r]
    for r in scored:
        print(f"  {'✅' if r['passed'] else '❌'} Case {r['case']['id']}: {r['reason']}")
    if scored:
        passed = sum(1 for r in scored if r["passed"])
        print(f"\n🎯 KẾT QUẢ: {passed}/{len(scored)} PASS")

    path = write_report(results, args.mode)
    print(f"📄 Báo cáo đã ghi: {path}")
    return 0 if all(r["passed"] for r in scored) else 1


if __name__ == "__main__":
    sys.exit(main())
