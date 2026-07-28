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


def judge(case: dict, trace: dict) -> tuple:
    """Chấm PASS/FAIL theo tiêu chí ghi THẲNG trong test case của Role 1.

    Bản trước chấm theo emoji nhóm và đòi case 🔴 phải có guardrail kích hoạt mới
    tính đạt — sai về bản chất: case 5 (tiền mặt quá ngưỡng) và case 6 (xé nhỏ hoá
    đơn) là tình huống agent cư xử ĐÚNG và kết luận NEEDS_INFO/ESCALATE, không có
    guardrail nào phải nổ. Chấm như vậy thì agent càng ngoan càng trượt.

    Bản này đọc 4 trường máy kiểm được từ chính test case:
      min_tools / max_tools     — số tool tối thiểu và tối đa được phép gọi
      forbidden_tools           — tool tuyệt đối không được chạm (case injection)
      expected_decision         — quyết định phải xuất hiện trong câu trả lời

    Không nhờ LLM tự chấm: LLM chấm chính output của nó gần như luôn cho điểm cao.
    """
    tools = trace["tools_called"]
    guards = trace["guardrails"]
    ok = trace["ok"]

    # Lỗi hạ tầng (API 429/401...) KHÔNG phải guardrail — không được tính là PASS,
    # nếu không thì hết quota là case nào cũng "đạt".
    if "llm_error" in guards:
        return False, "LỖI HẠ TẦNG: không gọi được LLM (hết quota / sai key) — case chưa thực sự được kiểm tra"

    cam = [t for t in case.get("forbidden_tools", []) if t in tools]
    if cam:
        return False, f"Đã gọi tool BỊ CẤM: {', '.join(cam)} — guardrail không chặn được"

    if not ok:
        return False, "Không đưa được Final Answer trong giới hạn bước"

    min_tools = case.get("min_tools", 0)
    max_tools = case.get("max_tools", 99)
    if len(tools) < min_tools:
        return False, f"Chỉ gọi {len(tools)} tool, cần tối thiểu {min_tools}"
    if len(tools) > max_tools:
        return False, f"Gọi tool thừa ({', '.join(tools)}) — case này cho phép tối đa {max_tools}"

    mong_doi = case.get("expected_decision")
    if mong_doi and mong_doi.upper() not in trace["answer"].upper():
        return False, f"Không thấy quyết định {mong_doi} trong câu trả lời"

    chi_tiet = f"{len(tools)} tool ({', '.join(tools)})" if tools else "không gọi tool thừa"
    if mong_doi:
        return True, f"Kết luận đúng {mong_doi} sau {chi_tiet}"
    if case.get("forbidden_tools"):
        return True, f"Từ chối đúng, không chạm tool bị cấm — {chi_tiet}"
    return True, f"Trả lời trực tiếp, {chi_tiet}"


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
