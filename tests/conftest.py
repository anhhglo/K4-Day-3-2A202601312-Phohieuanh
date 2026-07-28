"""
Fixture dùng chung cho test của phần D.

Nguyên tắc: **test của D không lệ thuộc vào `src/tools.py` của B.** Nếu để test
guardrail chạy trên dữ liệu thật của B thì hai chuyện xấu xảy ra cùng lúc — D
không làm được gì cho tới khi B xong, và mỗi lần B chỉnh một con số trong mock
data là test của D đỏ oan.

Thay vào đó D chạy trên một registry giả với đúng tên và đúng số tham số của 7
tool, do chính D kiểm soát.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))


import llm_utils  # noqa: E402


@pytest.fixture(autouse=True)
def khong_ngu_that(monkeypatch):
    """Chặn `time.sleep` của `call_llm` cho MỌI test.

    Bất kỳ test nào để provider giả trả lỗi 429 đều khiến `call_llm` ngủ thật 20
    giây. Chỉ một test như vậy là cả bộ test từ 0,1 giây thành 20 giây — đủ để
    người ta bỏ thói quen chạy test trước khi commit.

    Trả về danh sách các khoảng đã "ngủ" để test khẳng định được thời gian chờ.
    """
    da_ngu = []
    monkeypatch.setattr(llm_utils.time, "sleep", lambda s: da_ngu.append(s))
    return da_ngu


class ToolRecorder:
    """Ghi lại mọi lời gọi tool để test khẳng định được tool nào đã thật sự chạy."""

    def __init__(self):
        self.calls = []          # [(tên_tool, (tham_số,...)), ...]
        self.decisions = {}      # report_id -> decision, mô phỏng _DECISIONS của B

    def names(self):
        return [ten for ten, _ in self.calls]


@pytest.fixture
def recorder():
    return ToolRecorder()


@pytest.fixture
def stub_registry(recorder):
    """Registry giả: đúng 7 tên tool và đúng arity như spec của B.

    Arity quan trọng vì `_split_args` đọc `inspect.signature` để biết tách tham
    số làm mấy phần — sai arity là test tách tham số vô nghĩa.
    """

    def get_expense_report(report_id):
        recorder.calls.append(("get_expense_report", (report_id,)))
        if not report_id.upper().startswith("EXP-"):
            return f"LỖI: Không tìm thấy đơn chi phí '{report_id}'."
        return (f"Đơn {report_id.upper()} — Nguyễn Văn An (EMP-001)\n"
                f"Cost center: CC-ENG | Tổng tiền: 2.400.000 ₫")

    def get_policy(category):
        recorder.calls.append(("get_policy", (category,)))
        if category not in ("an_uong", "tiep_khach", "thiet_bi", "dao_tao"):
            return f"LỖI: Không có hạng mục '{category}'."
        return f"Chính sách '{category}': hạn mức 500.000 ₫ / 1 người"

    def check_budget(cost_center, amount):
        recorder.calls.append(("check_budget", (cost_center, amount)))
        if cost_center.upper() != "CC-ENG":
            return f"LỖI: Không có cost center '{cost_center}'."
        return f"Ngân sách CC-ENG: còn lại 120.000.000 ₫ | Cần chi: {amount} => ĐỦ"

    def find_duplicate_claims(employee_id, vendor):
        recorder.calls.append(("find_duplicate_claims", (employee_id, vendor)))
        if not employee_id.upper().startswith("EMP-"):
            return f"LỖI: Mã nhân viên '{employee_id}' không hợp lệ."
        return f"Không tìm thấy đơn trùng nào của {employee_id} với '{vendor}'."

    def get_approval_matrix(amount):
        recorder.calls.append(("get_approval_matrix", (amount,)))
        return f"Mức {amount} => Cấp có thẩm quyền duyệt: Team Lead"

    def submit_decision(report_id, decision, reason):
        recorder.calls.append(("submit_decision", (report_id, decision, reason)))
        recorder.decisions[report_id.upper()] = {"decision": decision, "reason": reason}
        return f"Đã ghi quyết định {decision} cho đơn {report_id.upper()}."

    def list_pending_reports(cost_center):
        recorder.calls.append(("list_pending_reports", (cost_center,)))
        return f"Đơn chờ duyệt tại {cost_center}: EXP-2026-0142, EXP-2026-0143"

    return {
        "get_expense_report": get_expense_report,
        "get_policy": get_policy,
        "check_budget": check_budget,
        "find_duplicate_claims": find_duplicate_claims,
        "get_approval_matrix": get_approval_matrix,
        "submit_decision": submit_decision,
        "list_pending_reports": list_pending_reports,
    }


#: Ngân sách vòng lặp dùng cho test của D. Cố định ở đây thay vì đọc
#: `prompts.MAX_ITERATIONS` (file của C) — chuỗi đầy đủ cần 5 tool + 1 vòng kết
#: luận, nên nếu C còn để giá trị cũ là 3 thì test guardrail của D đỏ oan.
TEST_MAX_ITERATIONS = 8


@pytest.fixture(autouse=True)
def patch_tools(request, monkeypatch):
    """Thay AVAILABLE_TOOLS và MAX_ITERATIONS trong app.py bằng bản của D.

    Autouse để mọi test của D chạy trên cùng một tập tool và cùng ngân sách vòng
    lặp xác định, không phụ thuộc `src/tools.py` (B) hay `src/prompts.py` (C)
    đang ở trạng thái nào.
    """
    if "no_stub_tools" in request.keywords:
        return None
    import app
    monkeypatch.setattr(app, "MAX_ITERATIONS", TEST_MAX_ITERATIONS)
    registry = request.getfixturevalue("stub_registry")
    monkeypatch.setattr(app, "AVAILABLE_TOOLS", registry)
    return registry


class FakeProvider:
    """Provider giả trả kịch bản soạn sẵn — không gọi LLM thật, không tốn quota."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts_seen = []
        self.system_prompts_seen = []

    def generate(self, prompt, system_prompt=""):
        self.prompts_seen.append(prompt)
        self.system_prompts_seen.append(system_prompt)
        if not self.responses:
            return "Thought: hết kịch bản\nFinal Answer: hết kịch bản"
        return self.responses.pop(0)
