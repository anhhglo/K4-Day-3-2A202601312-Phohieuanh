"""
Test cho `call_llm` — chỗ duy nhất xử lý hết quota.

Sai ở đây thì cả nhóm ngồi chờ retry vô ích, hoặc bỏ cuộc quá sớm khi chỉ cần
đợi vài chục giây. Test chặn `time.sleep` nên chạy tức thì.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from llm_utils import _retry_delay, call_llm, is_provider_error  # noqa: E402


LOI_429 = ("[OpenAI Exception]: Error code: 429 - RESOURCE_EXHAUSTED "
           "{'retryDelay': '25s'}")
LOI_429_KHONG_RO_DELAY = "[OpenAI Exception]: Error code: 429 - quá tải"
LOI_401 = "[OpenAI Exception]: Error code: 401 - invalid api key"


class Seq:
    """Provider trả lần lượt các phản hồi đã soạn, đếm số lần bị gọi."""

    def __init__(self, outs):
        self.outs = list(outs)
        self.so_lan = 0
        self.system_seen = "CHUA_GOI"

    def generate(self, prompt, system_prompt=""):
        self.so_lan += 1
        self.system_seen = system_prompt
        return self.outs.pop(0) if self.outs else "cạn kịch bản"


def test_nhan_dien_loi_provider():
    assert is_provider_error(LOI_429)
    assert is_provider_error(LOI_401)
    assert not is_provider_error("Xin chào")
    assert not is_provider_error("")
    assert not is_provider_error("[Không phải] định dạng lỗi")


def test_boc_duoc_retry_delay():
    assert _retry_delay(LOI_429) == 26.0        # 25 + 1 giây đệm


def test_retry_delay_mac_dinh_khi_khong_co_thong_tin():
    assert _retry_delay(LOI_429_KHONG_RO_DELAY) == 20.0


def test_tra_ve_ngay_khi_thanh_cong(khong_ngu_that):
    p = Seq(["Kết quả thật"])
    assert call_llm(p, "hỏi") == "Kết quả thật"
    assert p.so_lan == 1
    assert khong_ngu_that == []


def test_retry_khi_429_roi_thanh_cong(khong_ngu_that):
    p = Seq([LOI_429, LOI_429, "Kết quả thật"])
    assert call_llm(p, "hỏi") == "Kết quả thật"
    assert p.so_lan == 3
    assert khong_ngu_that == [26.0, 26.0], "phải chờ đúng thời gian server yêu cầu"


def test_khong_retry_khi_loi_khong_phai_429(khong_ngu_that):
    """401 là sai key — retry chỉ tổ mất thời gian."""
    p = Seq([LOI_401, "không bao giờ tới đây"])
    assert call_llm(p, "hỏi").startswith("[OpenAI Exception]: Error code: 401")
    assert p.so_lan == 1
    assert khong_ngu_that == []


def test_tra_loi_cuoi_cung_khi_het_so_lan_retry(khong_ngu_that):
    p = Seq([LOI_429] * 10)
    out = call_llm(p, "hỏi", retries=2)
    assert is_provider_error(out)
    assert p.so_lan == 3, "retries=2 nghĩa là 1 lần đầu + 2 lần thử lại"
    assert len(khong_ngu_that) == 2


def test_truyen_system_prompt_khi_co():
    p = Seq(["ok"])
    call_llm(p, "hỏi", system_prompt="BẠN LÀ AI")
    assert p.system_seen == "BẠN LÀ AI"


def test_khong_truyen_system_prompt_khi_rong():
    """Provider nào không nhận system_prompt vẫn phải gọi được."""

    class ChiNhanPrompt:
        def __init__(self):
            self.so_lan = 0

        def generate(self, prompt):
            self.so_lan += 1
            return "ok"

    p = ChiNhanPrompt()
    assert call_llm(p, "hỏi") == "ok"
    assert p.so_lan == 1
