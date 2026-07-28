"""
Test guardrail của vòng lặp ReAct — tầng chặn ở CODE, không dựa vào prompt.

Chạy trên registry giả (xem `conftest.py`), không phụ thuộc `src/tools.py` của B
và không gọi LLM thật.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from conftest import TEST_MAX_ITERATIONS as MAX_ITERATIONS, FakeProvider  # noqa: E402
from app import run_baseline_chatbot, run_react_agent  # noqa: E402


DU_TIEN_DE = [
    "Thought: mở hồ sơ\nAction: get_expense_report[EXP-2026-0142]",
    "Thought: tra chính sách\nAction: get_policy[an_uong]",
    "Thought: tra ngân sách\nAction: check_budget[CC-ENG, 2400000]",
    "Thought: dò trùng\nAction: find_duplicate_claims[EMP-001, Nhà hàng Ngon]",
]


# ==================================================== D3: tiền đề write action

#: Mở hồ sơ thành công — dùng để CÔ LẬP guardrail tiền đề khỏi guardrail chủ thể.
#: Nếu không mở hồ sơ trước, `subject_mismatch` sẽ bắn trước và che mất thứ đang đo.
MO_HO_SO = "Thought: mở hồ sơ\nAction: get_expense_report[EXP-2026-0142]"


def test_chan_submit_decision_khi_chua_tra_cuu_gi(recorder):
    """Đã mở hồ sơ nhưng chưa tra chính sách/ngân sách/trùng lặp."""
    provider = FakeProvider([
        MO_HO_SO,
        "Thought: duyệt luôn\nAction: submit_decision[EXP-2026-0142, APPROVED, ok]",
        "Thought: bị chặn\nFinal Answer: Chưa đủ căn cứ.",
    ])
    trace = run_react_agent("Duyệt đơn EXP-2026-0142", provider)

    assert "precondition_violated" in trace["guardrails"]
    assert "submit_decision" not in trace["tools_called"]
    assert recorder.decisions == {}, "tool ghi quyết định KHÔNG được chạy"


def test_ba_loi_goi_HONG_khong_duoc_mo_khoa_submit_decision(recorder):
    """Đường lách chính: gọi đủ 3 tool nhưng tham số rác nên tool nào cũng lỗi.

    Nếu tiền đề đếm theo 'đã gọi' thay vì 'gọi thành công' thì kịch bản này
    mở được khoá — guardrail chỉ là hàng rào giấy.
    """
    provider = FakeProvider([
        MO_HO_SO,
        "Thought: t\nAction: get_policy[hang_muc_khong_co_that]",
        "Thought: t\nAction: check_budget[CC-KHONG-CO, 999]",
        "Thought: t\nAction: find_duplicate_claims[NHAN-VIEN-MA, vendor_ma]",
        "Thought: đủ rồi\nAction: submit_decision[EXP-2026-0142, APPROVED, ok]",
        "Thought: bị chặn\nFinal Answer: Không đủ căn cứ.",
    ])
    trace = run_react_agent("Duyệt đơn EXP-2026-0142", provider)

    assert trace["tools_called"].count("get_policy") == 1, "tool có được gọi thật"
    assert "get_policy" not in trace["successful_tools"], "nhưng nó trả LỖI"
    assert "precondition_violated" in trace["guardrails"]
    assert "submit_decision" not in trace["tools_called"]
    assert recorder.decisions == {}


def test_chua_mo_ho_so_thi_bao_sai_chu_the_truoc_khi_bao_thieu_tien_de():
    """Gọi submit_decision khi chưa làm gì cả: báo lỗi cụ thể nhất trước.

    'Chưa mở hồ sơ đơn này' hành động được ngay, còn 'thiếu 3 tiền đề' thì mơ hồ
    hơn khi agent thậm chí chưa biết đơn đó có tồn tại không.
    """
    provider = FakeProvider([
        "Thought: duyệt luôn\nAction: submit_decision[EXP-2026-0142, APPROVED, ok]",
        "Thought: bị chặn\nFinal Answer: Chưa mở hồ sơ.",
    ])
    trace = run_react_agent("test", provider)

    assert trace["guardrails"] == ["subject_mismatch"]
    assert "submit_decision" not in trace["tools_called"]


def test_cho_qua_khi_ba_tien_de_deu_thanh_cong(recorder):
    provider = FakeProvider(DU_TIEN_DE + [
        "Thought: đủ\nAction: submit_decision[EXP-2026-0142, APPROVED, Đơn giá 400.000 dưới hạn mức]",
        "Thought: xong\nFinal Answer: Đã duyệt EXP-2026-0142.",
    ])
    trace = run_react_agent("Duyệt đơn EXP-2026-0142", provider)

    assert "precondition_violated" not in trace["guardrails"]
    assert "submit_decision" in trace["tools_called"]
    assert recorder.decisions["EXP-2026-0142"]["decision"] == "APPROVED"


def test_trace_phan_biet_tool_da_goi_va_tool_thanh_cong():
    provider = FakeProvider([
        "Thought: t\nAction: get_policy[hang_muc_ma]",
        "Thought: t\nAction: get_policy[an_uong]",
        "Thought: xong\nFinal Answer: xong",
    ])
    trace = run_react_agent("test", provider)

    assert trace["tools_called"].count("get_policy") == 2
    assert trace["successful_tools"].count("get_policy") == 1
    assert "tool_error" in trace["guardrails"]


# ==================================================== D4: ràng buộc chủ thể

def test_chan_ghi_quyet_dinh_cho_don_chua_he_tra_cuu(recorder):
    """Điều tra đơn 0142 nhưng ghi quyết định cho đơn 0143."""
    provider = FakeProvider(DU_TIEN_DE + [
        "Thought: ghi cho đơn khác\nAction: submit_decision[EXP-2026-0143, APPROVED, ok]",
        "Thought: bị chặn\nFinal Answer: Tôi chưa điều tra đơn đó.",
    ])
    trace = run_react_agent("test", provider)

    assert "subject_mismatch" in trace["guardrails"]
    assert "EXP-2026-0143" not in recorder.decisions


def test_chan_ghi_quyet_dinh_lan_thu_hai_cho_cung_mot_don(recorder):
    provider = FakeProvider(DU_TIEN_DE + [
        "Thought: ghi\nAction: submit_decision[EXP-2026-0142, APPROVED, lần đầu]",
        "Thought: đổi ý\nAction: submit_decision[EXP-2026-0142, REJECTED, lần hai]",
        "Thought: xong\nFinal Answer: xong",
    ])
    trace = run_react_agent("test", provider)

    assert "already_decided" in trace["guardrails"]
    assert recorder.decisions["EXP-2026-0142"]["decision"] == "APPROVED", \
        "quyết định lần đầu bị ghi đè"


def test_cho_ghi_khi_dung_don_da_dieu_tra():
    provider = FakeProvider(DU_TIEN_DE + [
        "Thought: ghi\nAction: submit_decision[EXP-2026-0142, APPROVED, đúng đơn]",
        "Thought: xong\nFinal Answer: xong",
    ])
    trace = run_react_agent("test", provider)

    assert "subject_mismatch" not in trace["guardrails"]
    assert "already_decided" not in trace["guardrails"]


def test_mo_ho_so_that_bai_thi_khong_tinh_la_da_dieu_tra(recorder):
    """get_expense_report lỗi thì đơn đó chưa được điều tra."""
    provider = FakeProvider([
        "Thought: mở\nAction: get_expense_report[MA-SAI-DINH-DANG]",
        "Thought: t\nAction: get_policy[an_uong]",
        "Thought: t\nAction: check_budget[CC-ENG, 100]",
        "Thought: t\nAction: find_duplicate_claims[EMP-001, X]",
        "Thought: ghi\nAction: submit_decision[MA-SAI-DINH-DANG, APPROVED, ok]",
        "Thought: xong\nFinal Answer: xong",
    ])
    trace = run_react_agent("test", provider)

    assert "subject_mismatch" in trace["guardrails"]
    assert recorder.decisions == {}


# ==================================================== D5: guardrail còn lại

def test_chan_goi_lap_cung_tool_cung_tham_so():
    provider = FakeProvider([
        "Thought: t\nAction: get_policy[an_uong]",
        "Thought: t\nAction: get_policy[an_uong]",
        "Thought: thôi\nFinal Answer: xong",
    ])
    trace = run_react_agent("test", provider)
    assert "duplicate_call" in trace["guardrails"]


def test_bat_tool_khong_ton_tai():
    provider = FakeProvider([
        "Thought: t\nAction: xoa_toan_bo_du_lieu[all]",
        "Thought: thôi\nFinal Answer: Không có tool đó.",
    ])
    trace = run_react_agent("test", provider)
    assert "unknown_tool" in trace["guardrails"]


def test_bat_sai_so_luong_tham_so():
    provider = FakeProvider([
        "Thought: t\nAction: check_budget[CC-ENG]",
        "Thought: sửa\nFinal Answer: xong",
    ])
    trace = run_react_agent("test", provider)
    assert "bad_args" in trace["guardrails"]


def test_bat_output_sai_dinh_dang():
    provider = FakeProvider([
        "Tôi nghĩ đơn này ổn đấy.",
        "Thought: làm lại\nFinal Answer: Đơn hợp lệ.",
    ])
    trace = run_react_agent("test", provider)
    assert "parse_error" in trace["guardrails"]


def test_cham_tran_max_iterations():
    provider = FakeProvider(
        [f"Thought: t\nAction: get_policy[an_uong_{i}]" for i in range(MAX_ITERATIONS + 5)]
    )
    trace = run_react_agent("test", provider)

    assert "max_iterations" in trace["guardrails"]
    assert trace["ok"] is False
    assert trace["steps"] == MAX_ITERATIONS


def test_loi_llm_duoc_danh_dau_rieng():
    provider = FakeProvider(["[OpenAI Exception]: Error code: 401 - invalid key"])
    trace = run_react_agent("test", provider)

    assert "llm_error" in trace["guardrails"]
    assert trace["ok"] is False


def test_scratchpad_bi_cat_khi_qua_dai():
    """Observation dài × nhiều vòng không được làm prompt phình vô hạn."""
    from app import MAX_SCRATCHPAD_CHARS

    provider = FakeProvider([
        f"Thought: t\nAction: get_expense_report[EXP-2026-{i:04d}]"
        for i in range(MAX_ITERATIONS)
    ])
    trace = run_react_agent("test", provider)

    for prompt in provider.prompts_seen:
        assert len(prompt) < MAX_SCRATCHPAD_CHARS * 3, "prompt phình quá mức"
    assert trace["steps"] <= MAX_ITERATIONS


def test_khong_sap_khi_provider_het_kich_ban():
    trace = run_react_agent("test", FakeProvider([]))
    assert trace["ok"] is True


def test_observation_khong_phai_chuoi_van_khong_lam_sap(monkeypatch):
    """Tool lỡ trả về không phải chuỗi thì .startswith sẽ ném AttributeError."""
    import app

    monkeypatch.setitem(app.AVAILABLE_TOOLS, "get_policy", lambda category: 12345)
    provider = FakeProvider([
        "Thought: t\nAction: get_policy[an_uong]",
        "Thought: xong\nFinal Answer: xong",
    ])
    trace = run_react_agent("test", provider)
    assert trace["ok"] is True


# ==================================================== D8: Chatbot Baseline

def test_baseline_khong_bao_gio_goi_tool(recorder):
    """Cấp 2 phải KHÔNG có khả năng gọi tool — đó là định nghĩa của nó."""
    provider = FakeProvider(["Quy trình duyệt chi phí gồm 4 bước..."])
    out = run_baseline_chatbot("Đơn EXP-2026-0142 có duyệt được không?", provider)

    assert recorder.calls == []
    assert "4 bước" in out


def test_baseline_tra_ve_nguyen_van_loi_provider():
    provider = FakeProvider(["[OpenAI Exception]: Error code: 401"])
    assert run_baseline_chatbot("test", provider).startswith("[OpenAI Exception]")


def test_baseline_dung_dung_system_prompt():
    from prompts import CHATBOT_BASELINE_PROMPT

    provider = FakeProvider(["ok"])
    run_baseline_chatbot("test", provider)
    assert provider.system_prompts_seen[0] == CHATBOT_BASELINE_PROMPT
