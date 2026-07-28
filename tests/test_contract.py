"""
🔗 TEST HỢP ĐỒNG LIÊN VAI — chỗ duy nhất KHÔNG dùng registry giả.

Mọi test khác của D chạy trên stub để D không phải chờ B. Cái giá của việc đó là
không gì bắt được khi `prompts.py` (C) và `tools.py` (B) nói về hai bộ tool khác
nhau — agent sẽ gọi tool không tồn tại và hỏng ở runtime chứ không hỏng ở test.

File này bịt đúng khe hở đó: nó chạy trên registry THẬT và bắt lệch hợp đồng ngay
tại thời điểm ai đó push, thay vì lúc cả nhóm đang demo trước lớp.

Dùng `@pytest.mark.no_stub_tools` để `conftest.patch_tools` không thay registry.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import app  # noqa: E402
import prompts  # noqa: E402
import tools  # noqa: E402

pytestmark = pytest.mark.no_stub_tools


#: Tên tool mà prompt quảng cáo với LLM, bóc từ các dòng "N. tên_tool[...]"
_TOOL_TRONG_PROMPT = re.compile(r"^\s*\d+\.\s*([a-z_]+)\[", re.MULTILINE)


def _tool_prompt_quang_cao() -> set:
    return set(_TOOL_TRONG_PROMPT.findall(prompts.REACT_SYSTEM_PROMPT))


def _tool_thuc_te() -> set:
    return set(tools.AVAILABLE_TOOLS)


def test_prompt_khong_quang_cao_tool_khong_ton_tai():
    """Prompt nói LLM có tool X mà registry không có X — agent sẽ gọi vào hư không."""
    thua = _tool_prompt_quang_cao() - _tool_thuc_te()
    assert not thua, (
        f"prompts.py (C) quảng cáo tool KHÔNG có trong tools.py (B): {sorted(thua)}.\n"
        f"Registry thật hiện có: {sorted(_tool_thuc_te())}"
    )


def test_moi_tool_that_deu_duoc_prompt_gioi_thieu():
    """Registry có tool mà prompt không nhắc — LLM không bao giờ biết để gọi."""
    bi_bo_quen = _tool_thuc_te() - _tool_prompt_quang_cao()
    assert not bi_bo_quen, (
        f"tools.py (B) có tool mà prompts.py (C) không giới thiệu: {sorted(bi_bo_quen)}.\n"
        f"LLM sẽ không bao giờ gọi tới chúng."
    )


def test_tool_precondition_tro_toi_tool_co_that():
    """`TOOL_PRECONDITIONS` của D phải trỏ tới tool có thật, nếu không guardrail vô hiệu."""
    thuc_te = _tool_thuc_te()
    for tool_dich, tien_de in app.TOOL_PRECONDITIONS.items():
        assert tool_dich in thuc_te, (
            f"TOOL_PRECONDITIONS canh giữ '{tool_dich}' nhưng tool này không tồn tại "
            f"— guardrail không bao giờ kích hoạt."
        )
        thieu = [t for t in tien_de if t not in thuc_te]
        assert not thieu, (
            f"Tiền đề của '{tool_dich}' trỏ tới tool không tồn tại: {thieu} "
            f"— điều kiện không bao giờ thoả, agent bị chặn vĩnh viễn."
        )


def test_tool_mo_ho_so_va_ghi_quyet_dinh_co_that():
    thuc_te = _tool_thuc_te()
    assert app.TOOL_OPENS_SUBJECT in thuc_te, (
        f"'{app.TOOL_OPENS_SUBJECT}' không có trong registry — guardrail "
        f"subject_mismatch sẽ chặn mọi quyết định vĩnh viễn."
    )
    assert app.TOOL_DECIDES_SUBJECT in thuc_te


def test_max_iterations_du_cho_chuoi_dai_nhat():
    """Cần đủ nhịp cho: mở hồ sơ + 3 tiền đề + tra DoA + ghi quyết định + kết luận."""
    so_tool_toi_thieu = 1 + len(app.TOOL_PRECONDITIONS["submit_decision"]) + 1 + 1
    can_toi_thieu = so_tool_toi_thieu + 1  # +1 vòng ra Final Answer

    assert prompts.MAX_ITERATIONS >= can_toi_thieu, (
        f"MAX_ITERATIONS={prompts.MAX_ITERATIONS} không đủ. Chuỗi đầy đủ cần "
        f"{so_tool_toi_thieu} tool + 1 vòng kết luận = {can_toi_thieu}. "
        f"Agent sẽ chạm trần trước khi kịp kết luận."
    )


def test_provider_khong_duoc_raise_ma_phai_tra_chuoi_loi():
    """Giao kèo của tầng provider: LỖI thì TRẢ chuỗi '[X Exception]: ...', không raise.

    Cả `llm_utils.is_provider_error` lẫn cơ chế retry 429 đều dựa vào giao kèo này.
    Provider nào raise sẽ làm sập cả vòng lặp ReAct thay vì được retry tử tế.
    """
    import providers
    from llm_utils import is_provider_error

    for ten in ("OpenAIProvider", "GeminiProvider", "FallbackProvider"):
        assert hasattr(providers, ten), (
            f"providers.py thiếu '{ten}' — Cấp 4 và các demo import trực tiếp lớp này."
        )

    # Không có API key hợp lệ trong môi trường test => chắc chắn thất bại.
    p = providers.FallbackProvider()
    try:
        ket_qua = p.generate("xin chào")
    except Exception as e:  # noqa: BLE001
        pytest.fail(
            f"FallbackProvider NÉM {type(e).__name__} thay vì trả chuỗi lỗi. "
            f"Vòng lặp ReAct sẽ sập thay vì ghi guardrail llm_error."
        )
    assert isinstance(ket_qua, str)
    assert is_provider_error(ket_qua), (
        f"Chuỗi trả về phải khớp định dạng '[X Exception]: ...' để is_provider_error "
        f"nhận ra. Thực tế nhận: {ket_qua[:120]!r}"
    )


def test_openai_provider_nhan_duoc_tham_so_model():
    """Cấp 4 tách Evaluator sang model phụ bằng `OpenAIProvider(model=...)`."""
    import providers

    p = providers.OpenAIProvider(model="model-phu-nao-do")
    assert getattr(p, "model_name", None) == "model-phu-nao-do"


def test_moi_tool_that_deu_tra_ve_chuoi():
    """Giao kèo với B: tool lỗi phải TRẢ chuỗi 'LỖI:', không được raise."""
    for ten, fn in tools.AVAILABLE_TOOLS.items():
        import inspect

        so_tham_so = len(inspect.signature(fn).parameters)
        try:
            ket_qua = fn(*["gia_tri_chac_chan_sai"] * so_tham_so)
        except Exception as e:  # noqa: BLE001
            pytest.fail(
                f"tool '{ten}' NÉM exception {type(e).__name__} khi nhận tham số sai. "
                f"Giao kèo là trả chuỗi bắt đầu bằng 'LỖI:' để agent đọc như Observation."
            )
        assert isinstance(ket_qua, str), (
            f"tool '{ten}' trả về {type(ket_qua).__name__}, phải là str."
        )
