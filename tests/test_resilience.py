"""
Test chống chịu sự cố — ba kịch bản sẽ xảy ra thật giữa buổi demo.

  1. Mất mạng (rớt wifi, DNS hỏng, timeout)
  2. Hết token đột ngột giữa vòng lặp ReAct
  3. Key bị thu hồi / sai (401, 403)

Mỗi kịch bản kiểm hai điều: agent **không sập**, và nó **xuống cấp đúng cách**
(xoay key → xoay model → tụt offline có dán nhãn) thay vì im lặng trả kết quả giả.

Không test nào chạm mạng: `providers.requests.post` bị thay bằng bản giả điều
khiển được từng lời gọi một.
"""

import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import key_pool  # noqa: E402
import providers  # noqa: E402
from llm_utils import is_provider_error  # noqa: E402


class PhanHoiGia:
    """Bản giả của `requests.Response` — chỉ đủ thứ mà providers.py thật sự đọc."""

    def __init__(self, status_code=200, noi_dung="xong", headers=None, text=""):
        self.status_code = status_code
        self.headers = headers or {}
        self._noi_dung = noi_dung
        self.text = text or ""

    def json(self):
        return {"choices": [{"finish_reason": "stop",
                             "message": {"role": "assistant", "content": self._noi_dung}}]}


class MangGia:
    """Thay `requests.post`. Trả lần lượt các kịch bản đã soạn, ghi lại key đã dùng."""

    def __init__(self, kich_ban):
        self.kich_ban = list(kich_ban)
        self.key_da_dung = []
        self.model_da_dung = []

    def __call__(self, url, **kwargs):
        auth = (kwargs.get("headers") or {}).get("Authorization", "")
        self.key_da_dung.append(auth.replace("Bearer ", ""))
        self.model_da_dung.append((kwargs.get("json") or {}).get("model"))

        buoc = self.kich_ban.pop(0) if self.kich_ban else PhanHoiGia()
        if isinstance(buoc, Exception):
            raise buoc
        return buoc


@pytest.fixture
def ba_key(monkeypatch):
    """Ba key trong pool dùng chung, mọi biến môi trường đã dựng sẵn."""
    monkeypatch.setenv("OPENAI_API_KEY", "key_A")
    monkeypatch.setenv("OPENAI_API_KEY_2", "key_B")
    monkeypatch.setenv("OPENAI_API_KEY_3", "key_C")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://vi-du.test/v1")
    monkeypatch.setenv("LLM_MODEL", "model-chinh")
    pool = key_pool.KeyPool(["key_A", "key_B", "key_C"])
    key_pool.dat_pool_chung(pool)
    return pool


def _gan_mang(monkeypatch, kich_ban):
    mang = MangGia(kich_ban)
    monkeypatch.setattr(providers.requests, "post", mang)
    return mang


# ==================================================== KỊCH BẢN 1: MẤT MẠNG
def test_mat_mang_khong_lam_sap_ma_tra_chuoi_loi(ba_key, monkeypatch):
    _gan_mang(monkeypatch, [requests.exceptions.ConnectionError("wifi rớt")])
    ket_qua = providers.OpenAIProvider().generate("chào")

    assert is_provider_error(ket_qua)
    assert "NETWORK_DOWN" in ket_qua


@pytest.mark.parametrize("loi", [
    requests.exceptions.ConnectionError("mất mạng"),
    requests.exceptions.Timeout("quá hạn"),
    requests.exceptions.SSLError("chứng chỉ hỏng"),
])
def test_moi_kieu_loi_mang_deu_thanh_NETWORK_DOWN(ba_key, monkeypatch, loi):
    _gan_mang(monkeypatch, [loi])
    assert "NETWORK_DOWN" in providers.OpenAIProvider().generate("chào")


def test_mat_mang_KHONG_duoc_phat_key(ba_key, monkeypatch):
    """Đây là cái bẫy đáng sợ nhất của toàn bộ lớp fallback.

    Mất mạng một giây mà đánh dấu key hỏng thì khi mạng về, pool tưởng không còn
    key nào dùng được nữa — hệ thống tự làm hỏng chính mình vì một sự cố đã qua.
    """
    _gan_mang(monkeypatch, [requests.exceptions.ConnectionError("rớt")])
    providers.OpenAIProvider().generate("chào")

    assert ba_key.con_key_song() is True
    assert ba_key.key_tiep_theo() == "key_A", "key đầu tiên phải còn nguyên vẹn"
    assert all(d["so_lan_hong"] == 0 for d in ba_key.trang_thai())


def test_mat_mang_chi_ton_dung_mot_lan_goi(ba_key, monkeypatch):
    """Mạng hỏng thì xoay key vô nghĩa — cả ba key đều đi qua cùng sợi dây mạng đó."""
    mang = _gan_mang(monkeypatch, [requests.exceptions.ConnectionError("rớt")])
    providers.OpenAIProvider().generate("chào")

    assert len(mang.key_da_dung) == 1, (
        f"Thử {len(mang.key_da_dung)} key cho một sự cố mạng — lãng phí thời gian "
        f"đúng lúc đang cần nối lại nhanh nhất."
    )


def test_mat_mang_duoc_call_llm_thu_lai(ba_key, monkeypatch):
    """Mạng chập chờn thường tự hồi. Lần thử thứ hai phải thành công."""
    from llm_utils import call_llm

    _gan_mang(monkeypatch, [
        requests.exceptions.ConnectionError("rớt"),
        PhanHoiGia(noi_dung="đã nối lại được"),
    ])
    assert call_llm(providers.OpenAIProvider(), "chào") == "đã nối lại được"


# ============================================== KỊCH BẢN 2: HẾT TOKEN ĐỘT NGỘT
def test_het_quota_thi_xoay_sang_key_ke_tiep(ba_key, monkeypatch):
    mang = _gan_mang(monkeypatch, [
        PhanHoiGia(429, headers={"Retry-After": "30"}, text="quota"),
        PhanHoiGia(noi_dung="key B trả lời"),
    ])
    assert providers.OpenAIProvider().generate("chào") == "key B trả lời"
    assert mang.key_da_dung == ["key_A", "key_B"]


def test_xoay_qua_ca_ba_key_truoc_khi_bo_cuoc(ba_key, monkeypatch):
    mang = _gan_mang(monkeypatch, [
        PhanHoiGia(429, headers={"Retry-After": "30"}, text="quota"),
        PhanHoiGia(429, headers={"Retry-After": "30"}, text="quota"),
        PhanHoiGia(429, headers={"Retry-After": "30"}, text="quota"),
    ])
    ket_qua = providers.OpenAIProvider().generate("chào")

    assert mang.key_da_dung == ["key_A", "key_B", "key_C"]
    assert is_provider_error(ket_qua)
    assert ba_key.con_key_song("model-chinh") is False
    assert ba_key.con_key_song("model-phu") is True, (
        "hết quota trên model này KHÔNG được kéo theo model khác — hạn mức tính riêng"
    )


def test_khong_thu_lai_key_vua_bao_het_quota(ba_key, monkeypatch):
    """Key vừa nói 'hết quota' thì một giây sau vẫn hết quota."""
    mang = _gan_mang(monkeypatch, [PhanHoiGia(429, headers={"Retry-After": "60"},
                                              text="q")] * 6)
    providers.OpenAIProvider().generate("chào")

    assert len(mang.key_da_dung) == 3, "mỗi key chỉ được thử đúng một lần"
    assert sorted(mang.key_da_dung) == ["key_A", "key_B", "key_C"]


def test_doc_duoc_retryDelay_trong_than_phan_hoi(ba_key, monkeypatch):
    """Gemini không gửi header Retry-After mà nhét retryDelay vào thân JSON."""
    _gan_mang(monkeypatch, [PhanHoiGia(429, text='{"error":{"retryDelay":"42s"}}')])
    providers.OpenAIProvider().generate("chào")

    assert ba_key.trang_thai("model-chinh")[0]["con_cho_giay"] == pytest.approx(43, abs=1)


def test_het_quota_ngay_danh_dau_khac_han_muc_phut(ba_key, monkeypatch):
    _gan_mang(monkeypatch, [PhanHoiGia(429, text='{"error":{"retryDelay":"3600s"}}')])
    providers.OpenAIProvider().generate("chào")

    assert ba_key.trang_thai("model-chinh")[0]["trang_thai"] == key_pool.EXHAUSTED


# ================================================ KỊCH BẢN 3: KEY BỊ THU HỒI
@pytest.mark.parametrize("ma", [401, 403])
def test_key_bi_tu_choi_thi_loai_va_xoay(ba_key, monkeypatch, ma):
    mang = _gan_mang(monkeypatch, [
        PhanHoiGia(ma, text="invalid api key"),
        PhanHoiGia(noi_dung="key B ổn"),
    ])
    assert providers.OpenAIProvider().generate("chào") == "key B ổn"
    assert mang.key_da_dung == ["key_A", "key_B"]
    assert ba_key.trang_thai("model-chinh")[0]["trang_thai"] == key_pool.INVALID
    assert ba_key.trang_thai("model-phu")[0]["trang_thai"] == key_pool.INVALID, (
        "key sai thì sai với MỌI model — khác hẳn hết quota"
    )


def test_key_hong_khong_bao_gio_duoc_chon_lai(ba_key, monkeypatch):
    _gan_mang(monkeypatch, [PhanHoiGia(401, text="sai key"),
                            PhanHoiGia(noi_dung="ok")])
    providers.OpenAIProvider().generate("lần 1")

    mang2 = _gan_mang(monkeypatch, [PhanHoiGia(noi_dung="ok")])
    providers.OpenAIProvider().generate("lần 2")
    assert mang2.key_da_dung == ["key_B"], "key hỏng vẫn bị chọn lại"


def test_google_tra_400_cho_key_sai_van_phai_coi_la_key_hong(ba_key, monkeypatch):
    """Google trả HTTP 400 "Please pass a valid API key", KHÔNG phải 401.

    Tìm ra khi dựng bản clone sạch với key mẫu chưa thay. Chỉ bắt 401/403 thì key
    sai không bao giờ bị loại — mỗi vòng ReAct lại ném thêm một request vào đúng
    cái key hỏng đó, và người dùng chờ mãi không hiểu vì sao.
    """
    mang = _gan_mang(monkeypatch, [
        PhanHoiGia(400, text='{"error":{"message":"Please pass a valid API key"}}'),
        PhanHoiGia(noi_dung="key B ổn"),
    ])
    assert providers.OpenAIProvider().generate("chào") == "key B ổn"
    assert mang.key_da_dung == ["key_A", "key_B"]
    assert ba_key.trang_thai("model-chinh")[0]["trang_thai"] == key_pool.INVALID


def test_400_khong_lien_quan_key_thi_KHONG_loai_key(ba_key, monkeypatch):
    """Đừng vơ đũa cả nắm: 400 vì prompt sai định dạng không phải lỗi của key."""
    _gan_mang(monkeypatch, [PhanHoiGia(400, text='{"error":{"message":"invalid temperature"}}')])
    providers.OpenAIProvider().generate("chào")

    assert ba_key.trang_thai("model-chinh")[0]["trang_thai"] != key_pool.INVALID


def test_thong_bao_loi_neu_nguyen_nhan_that_len_dau(ba_key, monkeypatch):
    """Nguyên nhân thật không được chôn dưới nhiễu của provider dự phòng.

    Bản trước liệt kê cả ba provider ngang hàng, nên lỗi thật (key sai) nằm dưới
    hai dòng "Thiếu GROQ_API_KEY / GEMINI_API_KEY" — người đọc đi lấy nhầm key.
    """
    _gan_mang(monkeypatch, [PhanHoiGia(400, text='{"error":{"message":"Please pass a valid API key"}}')] * 3)
    ket_qua = providers.OpenAIProvider().generate("chào")

    truoc_groq = ket_qua.find("KEY KHÔNG HỢP LỆ")
    vi_tri_groq = ket_qua.lower().find("groq")
    assert truoc_groq != -1, f"thiếu nguyên nhân thật: {ket_qua!r}"
    assert vi_tri_groq == -1 or truoc_groq < vi_tri_groq, (
        f"nguyên nhân thật bị chôn dưới nhiễu provider dự phòng:\n{ket_qua}"
    )


def test_loi_goi_sau_van_noi_ro_vi_sao_key_khong_dung_duoc(ba_key, monkeypatch):
    """Lời gọi thứ hai trở đi vẫn phải giải thích được nguyên nhân.

    Key bị đánh dấu hỏng ở lời gọi TRƯỚC thì vòng lặp thoát ngay, biến `loi_cuoi`
    chưa từng được gán — thông báo thành "Lỗi cuối: None", đúng lúc người dùng
    cần biết nhất thì không nói gì cả.
    """
    _gan_mang(monkeypatch, [
        PhanHoiGia(400, text='{"error":{"message":"Please pass a valid API key"}}')] * 3)
    providers.OpenAIProvider().generate("lần 1")   # đốt hết key

    lan_hai = providers.OpenAIProvider().generate("lần 2")
    assert "None" not in lan_hai, f"thông báo rỗng nghĩa: {lan_hai!r}"
    assert "401/403" in lan_hai or "KEY" in lan_hai.upper(), (
        f"phải nêu được vì sao key không dùng được: {lan_hai!r}"
    )


def test_khong_co_key_nao_thi_bao_ro_rang(monkeypatch):
    key_pool.dat_pool_chung(key_pool.KeyPool([]))
    ket_qua = providers.OpenAIProvider().generate("chào")

    assert is_provider_error(ket_qua)
    assert "OPENAI_API_KEY" in ket_qua, "thông báo phải chỉ ra cần đặt biến nào"


# ====================================== RESILIENT PROVIDER: XOAY MODEL → OFFLINE
def test_xoay_sang_model_phu_khi_model_chinh_het_quota(ba_key, monkeypatch):
    """Mỗi model một hạn mức riêng — model chính cạn không có nghĩa là hết đường."""
    monkeypatch.setenv("LAB_MODEL", "model-chinh")
    monkeypatch.setenv("LAB_MINI_MODEL", "model-phu")
    mang = _gan_mang(monkeypatch, [
        PhanHoiGia(429, headers={"Retry-After": "30"}, text="q"),
        PhanHoiGia(429, headers={"Retry-After": "30"}, text="q"),
        PhanHoiGia(429, headers={"Retry-After": "30"}, text="q"),
        PhanHoiGia(noi_dung="model phụ trả lời"),
    ])
    su_kien = []
    p = providers.ResilientProvider(on_degrade=su_kien.append)

    assert p.generate("chào") == "model phụ trả lời"
    assert "model-phu" in mang.model_da_dung
    assert any(e["loai"] == "xoay_model" for e in su_kien)
    assert p.da_tut_offline is False


def test_tut_ve_mock_khi_het_ca_key_lan_model(ba_key, monkeypatch):
    monkeypatch.setenv("LAB_MODEL", "model-chinh")
    monkeypatch.setenv("LAB_MINI_MODEL", "model-phu")
    _gan_mang(monkeypatch, [PhanHoiGia(429, headers={"Retry-After": "30"},
                                       text="q")] * 12)
    su_kien = []
    p = providers.ResilientProvider(on_degrade=su_kien.append)
    ket_qua = p.generate("Đơn EXP-2026-0142 có duyệt được không?")

    assert p.da_tut_offline is True
    assert not is_provider_error(ket_qua), "phải trả lời được, không phải chuỗi lỗi"
    assert any(e["loai"] == "tut_offline" for e in su_kien), (
        "tụt về kết quả giả lập mà KHÔNG báo là dối người xem"
    )


def test_da_tut_offline_thi_o_luon_khong_nhay_qua_lai(ba_key, monkeypatch):
    """Nửa hội thoại thật nửa giả lập thì người xem không biết tin câu nào."""
    _gan_mang(monkeypatch, [PhanHoiGia(429, headers={"Retry-After": "5"}, text="q")] * 12)
    p = providers.ResilientProvider()
    p.generate("câu 1")
    assert p.da_tut_offline is True

    mang2 = _gan_mang(monkeypatch, [PhanHoiGia(noi_dung="LLM thật đã sống lại")])
    ket_qua = p.generate("câu 2")
    assert ket_qua != "LLM thật đã sống lại"
    assert mang2.key_da_dung == [], "không được gọi mạng nữa sau khi đã chốt offline"


def test_mat_mang_thi_khong_phi_cong_xoay_model(ba_key, monkeypatch):
    """Cùng một endpoint không tới được — đổi tên model chẳng giúp gì.

    Mạng chết hẳn nên phải gọi đủ số lần chịu đựng thì mới tới lúc chốt offline;
    trong suốt thời gian đó KHÔNG được phí một lời gọi nào cho model phụ.
    """
    monkeypatch.setenv("LAB_MODEL", "model-chinh")
    monkeypatch.setenv("LAB_MINI_MODEL", "model-phu")
    mang = _gan_mang(monkeypatch, [requests.exceptions.ConnectionError("rớt")] * 20)
    su_kien = []
    p = providers.ResilientProvider(on_degrade=su_kien.append)
    for _ in range(providers.ResilientProvider.SO_LAN_TAM_THOI_CHIU_DUNG):
        p.generate("chào")

    assert any(e["loai"] == "mat_mang" for e in su_kien)
    assert "model-phu" not in mang.model_da_dung
    assert p.da_tut_offline is True


# ============ SỰ CỐ THOÁNG QUA — HAI LỖI TÌM RA KHI CHẠY DEMO ĐẦU-CUỐI
@pytest.mark.parametrize("ma", [500, 502, 503, 504])
def test_may_chu_qua_tai_duoc_danh_dau_dang_thu_lai(ba_key, monkeypatch, ma):
    """Gemini free tier trả 503 khá thường xuyên vào giờ cao điểm rồi tự khỏi.

    Tìm ra khi chạy demo thật: `gemini-3.5-flash` trả 503, code cũ coi đó là lỗi
    vĩnh viễn nên không thử lại — một cơn nấc của Google giết cả buổi demo.
    """
    _gan_mang(monkeypatch, [PhanHoiGia(ma, text="server busy")])
    ket_qua = providers.OpenAIProvider().generate("chào")

    assert "SERVER_BUSY" in ket_qua
    from llm_utils import LOI_DANG_THU_LAI
    assert any(d in ket_qua for d in LOI_DANG_THU_LAI)


def test_503_thoang_qua_duoc_call_llm_thu_lai(ba_key, monkeypatch):
    from llm_utils import call_llm

    _gan_mang(monkeypatch, [
        PhanHoiGia(503, text="quá tải"),
        PhanHoiGia(noi_dung="lần hai thì ổn"),
    ])
    assert call_llm(providers.OpenAIProvider(), "chào") == "lần hai thì ổn"


def test_MOT_lan_mat_mang_KHONG_duoc_chot_offline_vinh_vien(ba_key, monkeypatch):
    """Lỗi tìm ra khi chạy demo thật: một `ReadTimeout` duy nhất hạ cả phiên.

    Đo lại ngay sau đó thì model trả lời trong 1,5 giây — tức là mạng chỉ chớp
    một cái, nhưng phiên đã rơi xuống giả lập vĩnh viễn TRƯỚC KHI `call_llm` kịp
    thử lại. Sự cố thoáng qua phải được thử lại, không phải bị kết án.
    """
    mang = _gan_mang(monkeypatch, [
        requests.exceptions.ReadTimeout("chậm một nhịp"),
        PhanHoiGia(noi_dung="mạng vẫn tốt mà"),
    ])
    su_kien = []
    p = providers.ResilientProvider(on_degrade=su_kien.append)

    dau = p.generate("câu 1")
    assert is_provider_error(dau), "lần đầu trả lỗi để tầng trên thử lại"
    assert p.da_tut_offline is False, "một lần chớp mạng không được chốt offline"
    assert any(e["loai"] == "su_co_tam_thoi" for e in su_kien)

    assert p.generate("câu 2") == "mạng vẫn tốt mà"
    assert p.da_tut_offline is False
    assert len(mang.key_da_dung) == 2


def test_hong_li_nhieu_lan_lien_tiep_thi_moi_chot_offline(ba_key, monkeypatch):
    """Ngưỡng chịu đựng có giới hạn — hỏng thật thì vẫn phải tụt, có dán nhãn."""
    _gan_mang(monkeypatch, [requests.exceptions.ConnectionError("mạng chết hẳn")] * 20)
    su_kien = []
    p = providers.ResilientProvider(on_degrade=su_kien.append)

    for _ in range(providers.ResilientProvider.SO_LAN_TAM_THOI_CHIU_DUNG):
        p.generate("thử")

    assert p.da_tut_offline is True
    assert any(e["loai"] == "tut_offline" for e in su_kien)


def test_thanh_cong_xoa_sach_tien_su_su_co(ba_key, monkeypatch):
    """Hai lần chớp mạng cách nhau một lần thành công không được cộng dồn."""
    _gan_mang(monkeypatch, [
        requests.exceptions.ConnectionError("chớp 1"),
        PhanHoiGia(noi_dung="ổn"),
        requests.exceptions.ConnectionError("chớp 2"),
        requests.exceptions.ConnectionError("chớp 3"),
        PhanHoiGia(noi_dung="lại ổn"),
    ])
    p = providers.ResilientProvider()
    p.generate("1")
    assert p.generate("2") == "ổn"
    p.generate("3")
    p.generate("4")

    assert p.da_tut_offline is False, (
        "3 lần chớp rải rác qua 2 lần thành công không phải là hỏng lì"
    )
    assert p.generate("5") == "lại ổn"


def test_bam_lay_model_dang_chay_duoc_khong_thu_lai_model_da_can(ba_key, monkeypatch):
    """Model chính cạn hạn mức NGÀY thì nó cạn tới sáng mai.

    Tìm ra khi xem trace demo thật: `xoay_model` bắn ở CẢ TÁM vòng ReAct, mỗi
    vòng một dòng cảnh báo y hệt nhau, lấp mất phần trace mà người xem cần đọc.
    """
    monkeypatch.setenv("LAB_MODEL", "model-chinh")
    monkeypatch.setenv("LAB_MINI_MODEL", "model-phu")
    mang = _gan_mang(monkeypatch, [
        PhanHoiGia(429, text='{"error":{"retryDelay":"3600s"}}'),   # A hết ngày
        PhanHoiGia(429, text='{"error":{"retryDelay":"3600s"}}'),   # B hết ngày
        PhanHoiGia(429, text='{"error":{"retryDelay":"3600s"}}'),   # C hết ngày
        PhanHoiGia(noi_dung="vòng 1 — model phụ"),
        PhanHoiGia(noi_dung="vòng 2 — model phụ"),
        PhanHoiGia(noi_dung="vòng 3 — model phụ"),
    ])
    su_kien = []
    p = providers.ResilientProvider(on_degrade=su_kien.append)

    assert p.generate("vòng 1") == "vòng 1 — model phụ"
    assert p.generate("vòng 2") == "vòng 2 — model phụ"
    assert p.generate("vòng 3") == "vòng 3 — model phụ"

    assert sum(1 for e in su_kien if e["loai"] == "xoay_model") == 1, (
        f"Báo xoay model {sum(1 for e in su_kien if e['loai'] == 'xoay_model')} lần "
        f"cho cùng một sự việc — trace bị lấp bởi cảnh báo trùng lặp."
    )
    assert mang.model_da_dung.count("model-chinh") == 3, (
        "chỉ được thử model đã cạn trong lần đầu (3 key), không thử lại ở vòng sau"
    )


def test_resilient_thanh_cong_thi_khong_bao_gi_ca(ba_key, monkeypatch):
    _gan_mang(monkeypatch, [PhanHoiGia(noi_dung="ổn")])
    su_kien = []
    p = providers.ResilientProvider(on_degrade=su_kien.append)

    assert p.generate("chào") == "ổn"
    assert su_kien == []
    assert p.da_tut_offline is False


# ================================ VÒNG LẶP ReAct SỐNG SÓT QUA SỰ CỐ GIỮA CHỪNG
@pytest.mark.no_stub_tools
def test_react_khong_mat_scratchpad_khi_het_quota_giua_chung(ba_key, monkeypatch):
    """Hết token ở bước 3 — agent phải đi tiếp từ bước 3, không chạy lại từ đầu.

    Chạy lại từ đầu là đốt thêm quota đúng vào lúc đang thiếu quota.
    """
    from app import run_react_agent

    monkeypatch.setenv("LAB_MODEL", "model-chinh")
    monkeypatch.delenv("LAB_MINI_MODEL", raising=False)
    _gan_mang(monkeypatch, [
        PhanHoiGia(noi_dung="Thought: mở hồ sơ\nAction: get_expense_report[EXP-2026-0142]"),
        PhanHoiGia(noi_dung="Thought: tra chính sách\nAction: get_policy[an_uong]"),
        # Từ đây trở đi hết quota sạch -> ResilientProvider tụt về Mock.
        *[PhanHoiGia(429, headers={"Retry-After": "30"}, text="q")] * 9,
    ])
    su_kien = []
    p = providers.ResilientProvider(on_degrade=su_kien.append)
    trace = run_react_agent("Đơn EXP-2026-0142 có duyệt được không?", p)

    assert trace["tools_called"][:2] == ["get_expense_report", "get_policy"], (
        "hai bước làm được TRƯỚC sự cố phải được giữ nguyên trong trace"
    )
    assert "llm_error" not in trace["guardrails"], "tụt offline chứ không được chết"
    assert p.da_tut_offline is True


@pytest.mark.no_stub_tools
def test_react_phat_su_kien_theo_dung_thu_tu(ba_key, monkeypatch):
    """Giao diện dựa vào dòng sự kiện này để vẽ trace dần từng bước."""
    from app import run_react_agent

    _gan_mang(monkeypatch, [
        PhanHoiGia(noi_dung="Thought: mở hồ sơ\nAction: get_expense_report[EXP-2026-0142]"),
        PhanHoiGia(noi_dung="Thought: đủ rồi\nFinal Answer: NEEDS_INFO — cần thêm dữ liệu."),
    ])
    su_kien = []
    run_react_agent("Đơn EXP-2026-0142?", providers.OpenAIProvider(),
                    on_event=su_kien.append)

    loai = [e["loai"] for e in su_kien]
    assert loai[0] == "bat_dau"
    assert loai[-1] == "ket_luan"
    for can_co in ("buoc", "thought", "action", "observation"):
        assert can_co in loai, f"thiếu sự kiện '{can_co}' — giao diện sẽ không vẽ được"


@pytest.mark.no_stub_tools
def test_giao_dien_hong_khong_lam_chet_vong_lap(ba_key, monkeypatch):
    """Cái màn hình đang xem agent không được quyền giết agent."""
    from app import run_react_agent

    _gan_mang(monkeypatch, [
        PhanHoiGia(noi_dung="Thought: xong\nFinal Answer: Đã xong."),
    ])

    def quan_sat_hong(_su_kien):
        raise RuntimeError("giao diện sập")

    trace = run_react_agent("câu hỏi", providers.OpenAIProvider(), on_event=quan_sat_hong)
    assert trace["ok"] is True
    assert trace["answer"] == "Đã xong."


# ======================================= MOCK PROVIDER — PHƯƠNG ÁN CỨU HỘ DEMO
@pytest.mark.no_stub_tools
def test_mock_di_tron_vong_react_chu_khong_tra_loi_ngay():
    """`--mock` là phương án cứu hộ khi hết quota ngay trước giờ demo.

    Nó phải DIỄN ĐƯỢC vòng lặp ReAct, không chỉ trả một câu rồi thôi — nếu không
    thì lời hứa "mọi thứ hỏng hết thì chạy --mock" trong hướng dẫn là lời hứa rỗng.

    Bản trước dò `"observation:" in prompt` để đoán đang ở giữa vòng lặp, nhưng
    chính REACT_SYSTEM_PROMPT chứa chuỗi đó (quy tắc "TUYỆT ĐỐI không tự viết
    Observation:") nên điều kiện luôn đúng ngay vòng đầu — Mock chưa bao giờ gọi
    nổi một tool nào.
    """
    from app import run_react_agent

    trace = run_react_agent("Đơn EXP-2026-0142 có duyệt được không?",
                            providers.MockProvider())

    assert len(trace["tools_called"]) >= 4, (
        f"Mock chỉ gọi {len(trace['tools_called'])} tool: {trace['tools_called']}. "
        f"Demo offline sẽ không cho thấy vòng lặp ReAct nào cả."
    )
    assert trace["tools_called"][0] == "get_expense_report"
    assert "llm_error" not in trace["guardrails"]
    assert trace["ok"] is True


@pytest.mark.no_stub_tools
def test_mock_bam_dung_ma_don_trong_cau_hoi():
    """Hỏi đơn nào thì phải mở hồ sơ đơn đó, không cứng nhắc một mã duy nhất."""
    from app import run_react_agent

    trace = run_react_agent("Đơn EXP-2026-0145 có gì bất thường không?",
                            providers.MockProvider())
    assert "EXP-2026-0145" in trace["answer"]


@pytest.mark.no_stub_tools
def test_mock_luon_tu_nhan_la_gia_lap():
    """Kết quả giả lập mà không nói rõ là giả lập thì tệ hơn một thông báo lỗi."""
    from app import run_react_agent

    trace = run_react_agent("Đơn EXP-2026-0142?", providers.MockProvider())
    assert "GIẢ LẬP" in trace["answer"].upper()


@pytest.mark.no_stub_tools
def test_mock_khong_goi_tool_cho_cau_hoi_kien_thuc_chung():
    """Câu không có mã đơn thì trả lời thẳng — đúng như agent thật được dạy."""
    from app import run_react_agent

    trace = run_react_agent("Quy trình duyệt chi phí gồm những bước nào?",
                            providers.MockProvider())
    assert trace["tools_called"] == []
    assert trace["ok"] is True
