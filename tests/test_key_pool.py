"""
Test cho `key_pool` — logic xoay API key.

Toàn bộ chạy trên đồng hồ giả, không ngủ thật, không gọi mạng. Đây là lý do
module được viết tách khỏi phần gọi HTTP: nếu logic xoay key chỉ kiểm chứng được
bằng cách làm hết quota thật, thì mỗi lần sửa một dòng là mất một hạn mức ngày.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from key_pool import (  # noqa: E402
    ALIVE,
    COOLDOWN,
    EXHAUSTED,
    INVALID,
    NGUONG_HET_NGAY_GIAY,
    KeyPool,
    che_key,
    doc_key_tu_env,
)


class DongHo:
    """Đồng hồ giả — test kiểm tra chuyện hết cooldown mà không phải ngủ thật."""

    def __init__(self, bat_dau=1000.0):
        self.luc = bat_dau

    def __call__(self):
        return self.luc

    def tien(self, giay):
        self.luc += giay


@pytest.fixture
def dong_ho():
    return DongHo()


# ------------------------------------------------------------------- CHE KEY
@pytest.mark.parametrize("key,mong_doi", [
    ("AQ.Xy9kLxxxxxxxxxxxxxx3f2", "AQ.Xy9…3f2"),
    ("sk-proj-1234567890abcdef", "sk-pro…def"),
])
def test_che_key_giu_lai_du_de_phan_biet(key, mong_doi):
    assert che_key(key) == mong_doi


def test_che_key_khong_lo_key_ngan():
    """Key ngắn mà che kiểu đầu-cuối thì lộ gần hết. Che nhiều hơn."""
    assert che_key("abc123") == "abc…"
    assert "123" not in che_key("abc123")


def test_che_key_rong():
    assert che_key("") == "(rỗng)"


# ------------------------------------------------------------------- ĐỌC ENV
def test_doc_ba_dang_khai_bao_va_gop_lai():
    env = {
        "OPENAI_API_KEY": "key_A",
        "OPENAI_API_KEY_2": "key_B",
        "OPENAI_API_KEY_3": "key_C",
        "OPENAI_API_KEYS": "key_D, key_E",
    }
    assert doc_key_tu_env(env) == ["key_A", "key_B", "key_C", "key_D", "key_E"]


def test_khu_trung_lap_giu_thu_tu():
    """Dán nhầm cùng một key vào hai biến là chuyện thường khi 4 người cùng sửa .env.

    Không khử thì pool tưởng có 2 key, key hỏng là 'xoay' sang chính nó rồi hỏng lần nữa.
    """
    env = {"OPENAI_API_KEY": "key_A", "OPENAI_API_KEY_2": "key_A",
           "OPENAI_API_KEYS": "key_B,key_A"}
    assert doc_key_tu_env(env) == ["key_A", "key_B"]


def test_bo_qua_o_trong_va_dau_nhay():
    env = {"OPENAI_API_KEY": "  'key_A'  ", "OPENAI_API_KEY_2": "   ",
           "OPENAI_API_KEYS": ",,key_B,"}
    assert doc_key_tu_env(env) == ["key_A", "key_B"]


def test_khong_co_key_nao_thi_tra_danh_sach_rong():
    assert doc_key_tu_env({}) == []


# ------------------------------------------------------------------ XOAY KEY
def test_dung_key_dau_tien_khi_moi_thu_binh_thuong(dong_ho):
    pool = KeyPool(["A", "B", "C"], time_fn=dong_ho)
    assert pool.key_tiep_theo() == "A"
    pool.danh_dau_thanh_cong("A")
    assert pool.key_tiep_theo() == "A", "thành công thì không có lý do gì đổi key"


def test_het_quota_thi_xoay_sang_key_ke_tiep(dong_ho):
    pool = KeyPool(["A", "B"], time_fn=dong_ho)
    pool.danh_dau_het_quota("A", 30)
    assert pool.key_tiep_theo() == "B"


def test_key_song_lai_khi_het_gio_phat(dong_ho):
    pool = KeyPool(["A", "B"], time_fn=dong_ho)
    pool.danh_dau_het_quota("A", 30)
    assert pool.key_tiep_theo() == "B"

    dong_ho.tien(31)
    assert pool.key_tiep_theo() == "A", "hết cooldown là phải tự sống lại"


def test_cho_dai_thi_danh_dau_het_quota_ngay(dong_ho):
    """Phân biệt 'nghỉ 30 giây' với 'hết hạn mức ngày' — hai chuyện khác hẳn nhau."""
    pool = KeyPool(["A"], time_fn=dong_ho)
    pool.danh_dau_het_quota("A", NGUONG_HET_NGAY_GIAY + 1)
    assert pool.trang_thai()[0]["trang_thai"] == EXHAUSTED


def test_cho_ngan_thi_chi_la_nghi_mot_lat(dong_ho):
    pool = KeyPool(["A"], time_fn=dong_ho)
    pool.danh_dau_het_quota("A", 25)
    assert pool.trang_thai()[0]["trang_thai"] == COOLDOWN


def test_key_hong_bi_loai_vinh_vien(dong_ho):
    """401/403 khác 429: chờ bao lâu key sai vẫn sai.

    Nếu chỉ phạt tạm thời thì cứ hết cooldown là nó lại được chọn, và mỗi lần
    chọn lại là một request ném vào thùng rác.
    """
    pool = KeyPool(["A", "B"], time_fn=dong_ho)
    pool.danh_dau_hong("A")

    dong_ho.tien(100_000)
    assert pool.key_tiep_theo() == "B"
    assert pool.trang_thai()[0]["trang_thai"] == INVALID


def test_het_sach_key_thi_tra_none(dong_ho):
    pool = KeyPool(["A", "B"], time_fn=dong_ho)
    pool.danh_dau_het_quota("A", 60)
    pool.danh_dau_het_quota("B", 60)
    assert pool.key_tiep_theo() is None
    assert pool.con_key_song() is False


def test_pool_rong_khong_lam_sap():
    pool = KeyPool([])
    assert len(pool) == 0
    assert pool.key_tiep_theo() is None
    assert pool.con_key_song() is False
    assert pool.trang_thai() == []


def test_danh_dau_key_khong_thuoc_pool_khong_lam_sap(dong_ho):
    pool = KeyPool(["A"], time_fn=dong_ho)
    pool.danh_dau_het_quota("KEY_LA", 30)
    pool.danh_dau_hong("KEY_LA")
    pool.danh_dau_thanh_cong("KEY_LA")
    assert pool.key_tiep_theo() == "A"


# ------------------------------------------------- QUOTA TÍNH THEO (KEY, MODEL)
def test_het_quota_mot_model_khong_keo_theo_model_khac(dong_ho):
    """Hạn mức Gemini tính riêng từng model của từng project (key = project).

    Đây là cả lý do tồn tại của cơ chế xoay model. Nếu phạt key ở mọi model thì
    sau khi model chính cạn, model phụ không bao giờ được thử — cơ chế dự phòng
    chết đúng lúc cần nó nhất.
    """
    pool = KeyPool(["A"], time_fn=dong_ho)
    pool.danh_dau_het_quota("A", 3600, model="flash")

    assert pool.con_key_song("flash") is False
    assert pool.key_tiep_theo("lite") == "A"


def test_key_sai_thi_hong_voi_moi_model(dong_ho):
    """Ngược với 429: key sai là sai ở mọi nơi, đổi model không cứu được."""
    pool = KeyPool(["A", "B"], time_fn=dong_ho)
    pool.danh_dau_hong("A")

    assert pool.key_tiep_theo("flash") == "B"
    assert pool.key_tiep_theo("lite") == "B"
    assert pool.trang_thai("lite")[0]["trang_thai"] == INVALID


def test_dem_su_dung_tach_rieng_theo_model(dong_ho):
    pool = KeyPool(["A"], time_fn=dong_ho)
    pool.danh_dau_thanh_cong("A", model="flash")
    pool.danh_dau_thanh_cong("A", model="flash")
    pool.danh_dau_thanh_cong("A", model="lite")

    assert pool.trang_thai("flash")[0]["so_lan_dung"] == 2
    assert pool.trang_thai("lite")[0]["so_lan_dung"] == 1


def test_het_quota_ngay_cung_tu_song_lai_khi_qua_thoi_han(dong_ho):
    """EXHAUSTED không phải bản án chung thân — sang ngày mới là dùng lại được."""
    pool = KeyPool(["A"], time_fn=dong_ho)
    pool.danh_dau_het_quota("A", 3600, model="flash")
    assert pool.con_key_song("flash") is False

    dong_ho.tien(3601)
    assert pool.key_tiep_theo("flash") == "A"


# ------------------------------------------------------------------ CHỜ BAO LÂU
def test_cho_lau_nhat_bang_0_khi_con_key_song(dong_ho):
    pool = KeyPool(["A", "B"], time_fn=dong_ho)
    pool.danh_dau_het_quota("A", 60)
    assert pool.cho_lau_nhat() == 0.0


def test_cho_lau_nhat_lay_key_som_nhat_song_lai(dong_ho):
    pool = KeyPool(["A", "B"], time_fn=dong_ho)
    pool.danh_dau_het_quota("A", 90)
    pool.danh_dau_het_quota("B", 20)
    assert pool.cho_lau_nhat() == pytest.approx(20.0)


def test_cho_lau_nhat_vo_han_khi_moi_key_deu_hong(dong_ho):
    """Chờ là vô ích — tầng trên phải đổi model hoặc tụt offline, đừng ngồi đợi."""
    pool = KeyPool(["A", "B"], time_fn=dong_ho)
    pool.danh_dau_hong("A")
    pool.danh_dau_hong("B")
    assert pool.cho_lau_nhat() == float("inf")


# ------------------------------------------------------------------ TRẠNG THÁI
def test_bang_trang_thai_khong_bao_gio_lo_key_that(dong_ho):
    """Bảng này hiện trên màn chiếu trước cả lớp."""
    pool = KeyPool(["sk-bi-mat-tuyet-doi-12345"], time_fn=dong_ho)
    hien_thi = str(pool.trang_thai())
    assert "sk-bi-mat-tuyet-doi-12345" not in hien_thi
    assert "bi-mat" not in hien_thi


def test_bang_trang_thai_dem_dung_so_lan_dung_va_hong(dong_ho):
    pool = KeyPool(["A"], time_fn=dong_ho)
    pool.danh_dau_thanh_cong("A")
    pool.danh_dau_thanh_cong("A")
    pool.danh_dau_het_quota("A", 10)

    dong = pool.trang_thai()[0]
    assert dong["so_lan_dung"] == 2
    assert dong["so_lan_hong"] == 1
    assert dong["chi_so"] == 1


def test_dem_nguoc_cooldown_giam_dan(dong_ho):
    pool = KeyPool(["A"], time_fn=dong_ho)
    pool.danh_dau_het_quota("A", 60)
    assert pool.trang_thai()[0]["con_cho_giay"] == 60

    dong_ho.tien(45)
    assert pool.trang_thai()[0]["con_cho_giay"] == 15


def test_dat_lai_cho_moi_key_song_lai(dong_ho):
    """Nút 'Cho key sống lại' — dùng khi người ta vừa dán key mới vào .env."""
    pool = KeyPool(["A", "B"], time_fn=dong_ho)
    pool.danh_dau_hong("A")
    pool.danh_dau_het_quota("B", 9999)
    assert pool.con_key_song() is False

    pool.dat_lai()
    assert pool.key_tiep_theo() == "A"
    assert all(d["trang_thai"] == ALIVE for d in pool.trang_thai())


def test_thanh_cong_xoa_trang_thai_phat_truoc_do(dong_ho):
    pool = KeyPool(["A"], time_fn=dong_ho)
    pool.danh_dau_het_quota("A", 30)
    dong_ho.tien(31)
    pool.danh_dau_thanh_cong("A")
    assert pool.trang_thai()[0]["trang_thai"] == ALIVE
    assert pool.trang_thai()[0]["ly_do"] == ""
