"""
Test cho `parse_react_output` — tầng chịu đầu vào bẩn từ LLM.

Toàn bộ chạy offline, không gọi LLM, không tốn quota.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from app import parse_react_output  # noqa: E402


# ============================================================ D1: anchor bẩn

@pytest.mark.parametrize("raw", [
    "Thought: tra\nAction: get_policy[an_uong]",
    "Thought: tra\n**Action:** get_policy[an_uong]",
    "**Thought:** tra\n**Action:** get_policy[an_uong]",
    "thought: tra\naction: get_policy[an_uong]",
    "THOUGHT: tra\nACTION: get_policy[an_uong]",
    "Thought: tra\n- Action: get_policy[an_uong]",
    "Thought: tra\n* **Action**: get_policy[an_uong]",
    "Thought: tra\n### Action: get_policy[an_uong]",
    "Thought: tra\nAction : get_policy[an_uong]",
])
def test_nhan_dien_action_du_anchor_bi_boc_markdown(raw):
    r = parse_react_output(raw)
    assert r["type"] == "action", f"không parse được: {raw!r}"
    assert r["tool"] == "get_policy"
    assert r["args"] == ["an_uong"]


@pytest.mark.parametrize("raw", [
    "Thought: xong\nFinal Answer: Đơn hợp lệ.",
    "Thought: xong\n**Final Answer:** Đơn hợp lệ.",
    "thought: xong\nfinal answer: Đơn hợp lệ.",
    "Thought: xong\n### Final Answer: Đơn hợp lệ.",
])
def test_nhan_dien_final_answer_du_anchor_bi_boc(raw):
    r = parse_react_output(raw)
    assert r["type"] == "final"
    assert "Đơn hợp lệ" in r["answer"]


def test_khong_pha_dau_gach_duoi_trong_ten_hang_muc():
    """Chuẩn hoá anchor KHÔNG được đụng vào nội dung tham số.

    Cách vá ngây thơ là xoá sạch ký tự markdown `*_\\`#` khỏi cả chuỗi — làm vậy
    sẽ nuốt mất dấu _ trong 'an_uong' và tool tra chính sách sẽ luôn lỗi.
    """
    r = parse_react_output("Thought: tra\n**Action:** get_policy[an_uong]")
    assert r["args"] == ["an_uong"]


def test_van_cat_bo_observation_llm_tu_bia():
    r = parse_react_output(
        "Thought: tra\nAction: get_policy[an_uong]\nObservation: tôi tự bịa\nFinal Answer: xong"
    )
    assert r["type"] == "action"


def test_uu_tien_action_hon_final_answer():
    r = parse_react_output("Thought: t\nAction: get_policy[an_uong]\nFinal Answer: xong luôn")
    assert r["type"] == "action"


def test_khong_co_action_lan_final_answer_thi_bao_parse_error():
    r = parse_react_output("Tôi nghĩ đơn này ổn đấy.")
    assert r["type"] == "parse_error"


# ============================================================ D2: tách tham số

def test_ly_do_co_dau_phay_van_gom_thanh_mot_tham_so():
    """Tham số cuối của submit_decision là văn bản tự do — LLM chắc chắn viết phẩy."""
    r = parse_react_output(
        "Thought: xong\n"
        "Action: submit_decision[EXP-2026-0143, REJECTED, Vượt ngân sách, còn thiếu 20 triệu]"
    )
    assert r["args"] == [
        "EXP-2026-0143",
        "REJECTED",
        "Vượt ngân sách, còn thiếu 20 triệu",
    ]


def test_so_tien_co_dau_phay_khong_bi_tach():
    r = parse_react_output("Thought: tra\nAction: check_budget[CC-ENG, 2,400,000]")
    assert r["args"] == ["CC-ENG", "2,400,000"]


def test_so_tien_co_dau_cham_khong_bi_tach():
    r = parse_react_output("Thought: tra\nAction: check_budget[CC-ENG, 2.400.000]")
    assert r["args"] == ["CC-ENG", "2.400.000"]


def test_tool_mot_tham_so_khong_bi_tach():
    r = parse_react_output("Thought: tra\nAction: get_policy[an_uong, thừa, thãi]")
    assert r["args"] == ["an_uong, thừa, thãi"]


def test_tool_khong_ton_tai_van_parse_duoc_de_guardrail_bat():
    """Parser không phải nơi chặn tool lạ — guardrail unknown_tool lo việc đó."""
    r = parse_react_output("Thought: t\nAction: tool_khong_co[a, b]")
    assert r["type"] == "action"
    assert r["tool"] == "tool_khong_co"


def test_tham_so_rong():
    r = parse_react_output("Thought: t\nAction: get_policy[]")
    assert r["args"] == []


def test_bo_dau_nhay_bao_quanh_tham_so():
    r = parse_react_output('Thought: t\nAction: get_policy["an_uong"]')
    assert r["args"] == ["an_uong"]


# ============================================================ D7: dấu ] lồng nhau

def test_tham_so_chua_dau_ngoac_vuong():
    """Lý do từ chối rất hay dẫn chiếu kiểu '[xem policy]'."""
    r = parse_react_output(
        "Thought: t\nAction: submit_decision[EXP-0142, REJECTED, Vượt mức [xem policy]]"
    )
    assert r["args"][2] == "Vượt mức [xem policy]"


def test_van_parse_duoc_khi_co_chu_thua_sau_ngoac():
    r = parse_react_output("Thought: t\nAction: get_policy[an_uong] rồi tôi xem tiếp")
    assert r["tool"] == "get_policy"
    assert r["args"] == ["an_uong"]


def test_van_parse_duoc_khi_con_dong_phia_sau():
    r = parse_react_output("Thought: t\nAction: check_budget[CC-ENG, 2400000]\nTôi chờ kết quả.")
    assert r["args"] == ["CC-ENG", "2400000"]


# ============================================================ Thought

def test_giu_duoc_thought_nhieu_dong():
    r = parse_react_output(
        "Thought: dòng một\ndòng hai quan trọng\nAction: get_policy[an_uong]"
    )
    assert "dòng hai quan trọng" in r["thought"]
