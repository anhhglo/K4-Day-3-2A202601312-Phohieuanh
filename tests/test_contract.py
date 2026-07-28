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


@pytest.mark.parametrize("ten_bien,lop_mong_doi", [
    ("mock", "MockProvider"),
    ("openai", "OpenAIProvider"),
    ("gemini", "GeminiProvider"),
    ("groq", "FallbackProvider"),
])
def test_factory_ton_trong_bien_LLM_PROVIDER(ten_bien, lop_mong_doi):
    """`LLM_PROVIDER` trong .env phải thực sự quyết định provider nào được dùng.

    Bản trước bỏ qua giá trị này: mọi thứ khác 'mock' đều thành FallbackProvider,
    nên `.env` đặt `LLM_PROVIDER=openai` với OPENAI_API_KEY vẫn đi tìm
    GROQ_API_KEY rồi báo thiếu key. Chỉ lộ khi chạy LLM thật.
    """
    import providers

    assert providers.get_llm_provider(ten_bien).__class__.__name__ == lop_mong_doi


def test_openai_provider_goi_dung_endpoint_va_dung_model(monkeypatch):
    """`OpenAIProvider(model=X)` phải thật sự gửi model X tới endpoint OpenAI-compat.

    Cấp 4 tách Evaluator sang `LAB_MINI_MODEL` để judge không ăn vào hạn mức của
    agent chính. Nếu tham số `model` bị nuốt thì hai model dùng chung một hạn mức
    và cách tách quota đó chỉ là trang trí.
    """
    import providers

    da_gui = {}

    class FakeResp:
        status_code = 200
        headers = {}

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "xong"}}]}

    def _bat(url, **kwargs):
        da_gui["url"] = url
        da_gui["payload"] = kwargs.get("json")
        da_gui["timeout"] = kwargs.get("timeout")
        return FakeResp()

    monkeypatch.setenv("OPENAI_API_KEY", "khoa-gia-cho-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    monkeypatch.setattr(providers.requests, "post", _bat)

    ket_qua = providers.OpenAIProvider(model="model-phu").generate("chào", system_prompt="hệ thống")

    assert ket_qua == "xong"
    assert da_gui["url"].endswith("/chat/completions"), da_gui["url"]
    assert da_gui["payload"]["model"] == "model-phu", (
        f"Gửi model {da_gui['payload']['model']!r} thay vì 'model-phu' — tham số "
        f"model bị nuốt, Cấp 4 không tách được quota judge."
    )
    assert da_gui["timeout"] == providers.REQUEST_TIMEOUT_SECONDS
    assert da_gui["payload"]["messages"][0]["role"] == "system"


def test_response_thieu_khoa_content_khong_lam_sap_ma_bao_dang_thu_lai(monkeypatch):
    """Model thinking đôi khi trả message chỉ có 'extra_content', không có 'content'.

    Truy thẳng `["content"]` thì ném KeyError với thông báo đúng một chữ:
    'content' — không ai đoán được chuyện gì xảy ra khi đang demo. Phải đổi thành
    lỗi có nhãn EMPTY_RESPONSE để `call_llm` biết đây là lỗi tạm thời và thử lại.
    """
    import providers
    from llm_utils import is_provider_error

    class FakeResp:
        status_code = 200
        headers = {}

        @staticmethod
        def json():
            return {"choices": [{"finish_reason": "stop",
                                 "message": {"role": "assistant",
                                             "extra_content": {"google": {}}}}]}

    monkeypatch.setenv("OPENAI_API_KEY", "khoa-gia-cho-test")
    monkeypatch.setattr(providers.requests, "post", lambda *a, **k: FakeResp())

    ket_qua = providers.OpenAIProvider(model="m").generate("chào")

    assert is_provider_error(ket_qua), f"Phải trả chuỗi lỗi đúng giao kèo, nhận: {ket_qua!r}"
    assert "EMPTY_RESPONSE" in ket_qua, (
        f"Thiếu nhãn EMPTY_RESPONSE nên `call_llm` sẽ bỏ cuộc thay vì thử lại. "
        f"Nhận: {ket_qua!r}"
    )


def test_openai_provider_nhan_duoc_tham_so_model():
    """Cấp 4 tách Evaluator sang model phụ bằng `OpenAIProvider(model=...)`."""
    import providers

    p = providers.OpenAIProvider(model="model-phu-nao-do")
    assert getattr(p, "model_name", None) == "model-phu-nao-do"


#: Tên tool trong ví dụ JSON của Cấp 4: {"tool": "get_policy", ...}
_TOOL_TRONG_VI_DU_JSON = re.compile(r'"tool":\s*"([a-z_]+)"')
#: Tên tool trong TOOL_SPECS của Cấp 4: '- get_policy(category: str): ...'
_TOOL_TRONG_SPECS = re.compile(r"^-\s*([a-z_]+)\(", re.MULTILINE)


def test_prompt_cap_4_khong_vi_du_bang_tool_khong_ton_tai():
    """Ví dụ trong prompt là thứ LLM bắt chước sát nhất — ví dụ sai còn hại hơn thiếu.

    Bài lab từng đổi domain (du lịch -> duyệt chi phí). Registry và TOOL_SPECS được
    đổi theo, nhưng hai ví dụ JSON trong Planner/Executor bị bỏ sót, vẫn dạy agent
    gọi `get_weather`. Test này chặn đúng kiểu sót đó tái diễn.
    """
    nguon = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src", "ai_levels", "level4_autonomous_agent.py",
    )
    with open(nguon, encoding="utf-8") as f:
        ma_nguon = f.read()

    nhac_toi = set(_TOOL_TRONG_VI_DU_JSON.findall(ma_nguon))
    nhac_toi |= set(_TOOL_TRONG_SPECS.findall(ma_nguon))
    ma = set(tools.AVAILABLE_TOOLS)

    khong_ton_tai = {t for t in nhac_toi if t not in ma}
    assert not khong_ton_tai, (
        f"level4_autonomous_agent.py dạy agent gọi tool KHÔNG có trong registry: "
        f"{sorted(khong_ton_tai)}.\nRegistry thật: {sorted(ma)}"
    )


def test_khong_con_hang_so_timeout_chet_o_prompts():
    """`TIMEOUT_SECONDS` từng nằm ở prompts.py mà không nơi nào đọc — phanh giả.

    Timeout thật là timeout gọi mạng tới LLM, sống ở providers.REQUEST_TIMEOUT_SECONDS.
    """
    assert not hasattr(prompts, "TIMEOUT_SECONDS"), (
        "prompts.TIMEOUT_SECONDS đã quay lại. Nó không được code nào đọc — khai báo "
        "một guardrail không ai thi hành là tự tạo điểm trừ khi bị hỏi. Timeout thật "
        "thuộc về providers.REQUEST_TIMEOUT_SECONDS."
    )


def test_moi_loi_goi_mang_deu_co_timeout():
    """Một `requests.post` không timeout sẽ treo demo vô hạn khi mạng lỗi."""
    import providers

    assert getattr(providers, "REQUEST_TIMEOUT_SECONDS", 0) > 0

    nguon = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src", "providers.py"
    )
    with open(nguon, encoding="utf-8") as f:
        ma_nguon = f.read()

    for loi_goi in re.finditer(r"requests\.post\((.*?)\)\s*$", ma_nguon, re.MULTILINE | re.DOTALL):
        assert "timeout=" in loi_goi.group(1), (
            f"Có requests.post không truyền timeout — demo sẽ treo vô hạn nếu mạng "
            f"lỗi:\n{loi_goi.group(0)[:200]}"
        )


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
