import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from tools import (
    _parse_amount,
    get_expense_report,
    get_policy,
    check_budget,
    find_duplicate_claims,
    get_approval_matrix,
    submit_decision,
    list_pending_reports,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("25000000", 25_000_000),
        ("25.000.000", 25_000_000),
        ("25,000,000", 25_000_000),
        ("25000000 ₫", 25_000_000),
        ("25.000.000 VNĐ", 25_000_000),
        ("  140000000  ", 140_000_000),
    ],
)
def test_parse_amount_chap_nhan_moi_dinh_dang(raw, expected):
    assert _parse_amount(raw) == expected


@pytest.mark.parametrize("raw", ["", "hai lăm triệu", "abc", "12abc34"])
def test_parse_amount_bao_loi_khi_khong_doc_duoc(raw):
    with pytest.raises(ValueError):
        _parse_amount(raw)


def test_get_expense_report_tra_thong_tin_don():
    result = get_expense_report("EXP-2026-0142")
    assert "EXP-2026-0142" in result
    assert "2,400,000" in result or "2400000" in result


def test_get_policy_tra_chinh_sach_hang_muc():
    result = get_policy("thiet_bi")
    assert "30,000,000" in result or "30000000" in result
    assert "pre-approval" in result.lower() or "pre_approval" in result.lower()


def test_check_budget_tra_so_du_con_lai():
    result = check_budget("CC-ENG", "10000000")
    assert "còn lại" in result.lower() or "con lai" in result.lower()
    assert "120,000,000" in result or "120000000" in result


def test_find_duplicate_claims_phat_hien_trung_lap():
    result = find_duplicate_claims("EMP-001", "Grab")
    assert "trùng" in result.lower() or "trung" in result.lower()
    assert "EXP-2026-0138" in result


def test_get_approval_matrix_tra_cap_duyet():
    result = get_approval_matrix("4,500,000")
    assert "Team Lead" in result


def test_submit_decision_ghi_quyet_dinh():
    result = submit_decision("EXP-2026-0142", "APPROVED", "Đủ căn cứ")
    assert "THÀNH CÔNG" in result
    assert "EXP-2026-0142" in result


def test_list_pending_reports_tra_danh_sach():
    result = list_pending_reports("CC-ENG")
    assert "EXP-2026-0142" in result
