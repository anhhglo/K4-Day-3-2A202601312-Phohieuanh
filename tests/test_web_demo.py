"""
Test cho giao diện web — dựng server thật trên cổng ngẫu nhiên, gọi bằng HTTP thật.

Không dùng mock cho tầng HTTP: chính tầng đó là chỗ hay hỏng (thiếu header SSE,
JSON sai charset, route trả 500 khi thiếu tham số). Mock nó đi thì test xanh mà
demo vẫn trắng màn hình.

Toàn bộ chạy với `MockProvider` nên không tốn một lượt quota nào.
"""

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import key_pool  # noqa: E402
import web_demo  # noqa: E402


@pytest.fixture
def may_chu(tmp_path, monkeypatch):
    """Server thật trên cổng do hệ điều hành cấp, luôn ở chế độ mock."""
    monkeypatch.setattr(web_demo, "THU_MUC_PHIEN", str(tmp_path / "sessions"))
    monkeypatch.setattr(web_demo, "_phien", {})
    web_demo.Handler.dung_mock = True

    srv = ThreadingHTTPServer(("127.0.0.1", 0), web_demo.Handler)
    # poll_interval nhỏ vì `shutdown()` chờ tới hết một chu kỳ poll. Để mặc định
    # 0,5s thì riêng việc dọn dẹp đã ngốn ~11 giây cho cả file test này — đủ lâu
    # để người ta bỏ thói quen chạy test trước khi commit.
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02},
                     daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    srv.server_close()


def _get(goc, duong):
    with urllib.request.urlopen(goc + duong, timeout=10) as r:
        return r.status, r.read().decode("utf-8"), dict(r.headers)


def _post(goc, duong, du_lieu=None):
    body = json.dumps(du_lieu or {}).encode("utf-8")
    req = urllib.request.Request(goc + duong, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def _doi_xong(goc, session_id, han=15.0):
    """Chờ agent chạy xong, trả về phiên."""
    het = time.time() + han
    while time.time() < het:
        _, phien = _post(goc, "/api/resume", {"session_id": session_id})
        if phien.get("xong"):
            return phien
        time.sleep(0.05)
    raise AssertionError(f"Phiên {session_id} không xong sau {han}s")


# ==================================================================== TRANG
def test_trang_chu_tra_html(may_chu):
    ma, body, headers = _get(may_chu, "/")
    assert ma == 200
    assert "text/html" in headers["Content-Type"]
    assert "charset=utf-8" in headers["Content-Type"], (
        "thiếu charset thì tiếng Việt hiện thành ký tự rác trên máy chiếu"
    )
    assert "Trợ Lý Duyệt Chi Phí" in body


def test_trang_chu_khong_lo_key_that(may_chu, monkeypatch):
    key_pool.dat_pool_chung(key_pool.KeyPool(["sk-tuyet-mat-khong-duoc-lo-123"]))
    _, body, _ = _get(may_chu, "/")
    assert "sk-tuyet-mat-khong-duoc-lo-123" not in body


def test_duong_dan_la_tra_404(may_chu):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(may_chu, "/khong-ton-tai")
    assert e.value.code == 404


# =================================================================== HEALTH
def test_health_tra_du_thong_tin_cho_giao_dien(may_chu, monkeypatch):
    key_pool.dat_pool_chung(key_pool.KeyPool(["key_A", "key_B"]))
    ma, body, _ = _get(may_chu, "/api/health")
    d = json.loads(body)

    assert ma == 200
    assert d["so_key"] == 2
    assert len(d["keys"]) == 2
    assert d["con_key_song"] is True
    assert {"chi_so", "key_che", "trang_thai", "nhan"} <= set(d["keys"][0])


def test_health_khong_bao_gio_goi_mang(may_chu, monkeypatch):
    """Panel này tự động làm mới mỗi 15 giây. Nếu nó gọi mạng thì chính nó đốt
    sạch quota mà nó đang theo dõi."""
    import providers

    def _chan(*a, **k):
        raise AssertionError("/api/health vừa gọi mạng thật")

    monkeypatch.setattr(providers.requests, "post", _chan)
    key_pool.dat_pool_chung(key_pool.KeyPool(["key_A"]))

    for _ in range(5):
        assert _get(may_chu, "/api/health")[0] == 200


def test_health_bao_khong_con_key_song(may_chu):
    pool = key_pool.KeyPool(["key_A"])
    pool.danh_dau_hong("key_A")
    key_pool.dat_pool_chung(pool)

    d = json.loads(_get(may_chu, "/api/health")[1])
    assert d["con_key_song"] is False
    assert d["cho_giay"] is None, "chờ vô ích thì phải nói rõ là vô ích"


def test_health_khong_co_key_nao(may_chu):
    key_pool.dat_pool_chung(key_pool.KeyPool([]))
    d = json.loads(_get(may_chu, "/api/health")[1])
    assert d["so_key"] == 0
    assert d["keys"] == []


# ====================================================================== ASK
def test_hoi_thieu_cau_hoi_bi_tu_choi(may_chu):
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(may_chu, "/api/ask", {"cau_hoi": "   "})
    assert e.value.code == 400


def test_hoi_tra_ve_session_id(may_chu):
    ma, d = _post(may_chu, "/api/ask", {"cau_hoi": "Đơn EXP-2026-0142?"})
    assert ma == 200
    assert d["session_id"]


def test_che_do_khong_hop_le_mac_dinh_ve_react(may_chu):
    _, d = _post(may_chu, "/api/ask", {"cau_hoi": "xin chào", "che_do": "linh tinh"})
    phien = _doi_xong(may_chu, d["session_id"])
    assert phien["che_do"] == "react"


def test_chay_react_sinh_du_dong_su_kien(may_chu):
    _, d = _post(may_chu, "/api/ask", {"cau_hoi": "Đơn EXP-2026-0142 có duyệt được không?"})
    phien = _doi_xong(may_chu, d["session_id"])

    loai = [e["loai"] for e in phien["su_kien"]]
    assert loai[0] == "tut_offline", "chế độ --mock phải báo offline ngay từ đầu"
    assert "bat_dau" in loai
    assert "ket_luan" in loai
    assert "tom_tat" in loai
    assert loai[-1] == "xong"


def test_chay_chatbot_khong_co_tom_tat_tool(may_chu):
    _, d = _post(may_chu, "/api/ask",
                 {"cau_hoi": "Quy trình duyệt chi phí gồm những bước nào?",
                  "che_do": "chatbot"})
    phien = _doi_xong(may_chu, d["session_id"])

    loai = [e["loai"] for e in phien["su_kien"]]
    assert "ket_luan" in loai
    assert "tom_tat" not in loai, "Chatbot Cấp 2 không gọi tool nên không có tóm tắt tool"


def test_moi_su_kien_co_chi_so_tang_dan(may_chu):
    """Chỉ số là thứ giúp SSE nối lại đúng chỗ sau khi đứt."""
    _, d = _post(may_chu, "/api/ask", {"cau_hoi": "Đơn EXP-2026-0142?"})
    phien = _doi_xong(may_chu, d["session_id"])

    chi_so = [e["chi_so"] for e in phien["su_kien"]]
    assert chi_so == list(range(len(chi_so)))


def test_mock_luon_danh_dau_offline(may_chu):
    """Kết quả giả lập mà không dán nhãn là dối người xem."""
    _, d = _post(may_chu, "/api/ask", {"cau_hoi": "Đơn EXP-2026-0142?"})
    phien = _doi_xong(may_chu, d["session_id"])
    assert phien["offline"] is True


# =================================================================== RESUME
def test_resume_phien_khong_ton_tai_tra_404(may_chu):
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(may_chu, "/api/resume", {"session_id": "khong-co-that"})
    assert e.value.code == 404


def test_backend_chet_giua_chung_van_noi_lai_duoc(may_chu, monkeypatch):
    """Kịch bản: người dùng đang hỏi dở thì backend sập, bật lại rồi mở lại trang.

    Phiên phải đọc lại được TỪ ĐĨA, không phải từ RAM — vì RAM đã mất theo tiến trình.
    """
    _, d = _post(may_chu, "/api/ask", {"cau_hoi": "Đơn EXP-2026-0142?"})
    session_id = d["session_id"]
    goc = _doi_xong(may_chu, session_id)

    # Mô phỏng tiến trình khởi động lại: RAM sạch trơn, chỉ còn file trên đĩa.
    monkeypatch.setattr(web_demo, "_phien", {})

    _, phuc_hoi = _post(may_chu, "/api/resume", {"session_id": session_id})
    assert phuc_hoi["cau_hoi"] == goc["cau_hoi"]
    assert len(phuc_hoi["su_kien"]) == len(goc["su_kien"])
    assert phuc_hoi["xong"] is True


def test_file_phien_hong_khong_lam_sap_server(may_chu, tmp_path):
    duong = os.path.join(web_demo.THU_MUC_PHIEN, "hong.json")
    os.makedirs(web_demo.THU_MUC_PHIEN, exist_ok=True)
    with open(duong, "w", encoding="utf-8") as f:
        f.write("{ đây không phải JSON")

    with pytest.raises(urllib.error.HTTPError) as e:
        _post(may_chu, "/api/resume", {"session_id": "hong"})
    assert e.value.code == 404, "file hỏng phải thành 404 tử tế, không phải 500"


# ====================================================================== SSE
def test_stream_tra_dung_header_sse(may_chu):
    _, d = _post(may_chu, "/api/ask", {"cau_hoi": "Đơn EXP-2026-0142?"})
    _doi_xong(may_chu, d["session_id"])

    with urllib.request.urlopen(
            f"{may_chu}/api/stream?session_id={d['session_id']}", timeout=10) as r:
        headers = dict(r.headers)
        body = r.read().decode("utf-8")

    assert "text/event-stream" in headers["Content-Type"]
    assert headers.get("Cache-Control") == "no-cache"
    assert "data: " in body
    assert "id: 0" in body, "thiếu id thì trình duyệt không nối lại đúng chỗ được"


def test_stream_phat_lai_duoc_tu_giua_chung(may_chu):
    """Đứt kết nối rồi nối lại chỉ nhận phần còn thiếu, không nhận lại từ đầu."""
    _, d = _post(may_chu, "/api/ask", {"cau_hoi": "Đơn EXP-2026-0142?"})
    phien = _doi_xong(may_chu, d["session_id"])
    tong = len(phien["su_kien"])

    with urllib.request.urlopen(
            f"{may_chu}/api/stream?session_id={d['session_id']}&tu={tong - 1}",
            timeout=10) as r:
        body = r.read().decode("utf-8")

    assert body.count("data: ") == 1, "chỉ được gửi đúng sự kiện còn thiếu"


def test_stream_ton_tai_session_la_tra_404(may_chu):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(may_chu, "/api/stream?session_id=bia-dat")
    assert e.value.code == 404


def test_stream_thieu_tham_so_khong_lam_sap(may_chu):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(may_chu, "/api/stream")
    assert e.value.code == 404


# ============================================================== RESET KEYS
def test_nut_cho_key_song_lai(may_chu):
    pool = key_pool.KeyPool(["key_A"])
    pool.danh_dau_hong("key_A")
    key_pool.dat_pool_chung(pool)
    assert json.loads(_get(may_chu, "/api/health")[1])["con_key_song"] is False

    ma, d = _post(may_chu, "/api/reset-keys")
    assert ma == 200
    assert d["con_key_song"] is True


# ========================================================== NHIỀU PHIÊN SONG SONG
def test_ba_phien_cung_luc_khong_lan_du_lieu(may_chu):
    """Cả lớp cùng mở trang thì mỗi người phải thấy đúng phiên của mình."""
    cau_hoi = ["Đơn EXP-2026-0142?", "Đơn EXP-2026-0143?", "Đơn EXP-2026-0145?"]
    ids = [_post(may_chu, "/api/ask", {"cau_hoi": c})[1]["session_id"] for c in cau_hoi]

    assert len(set(ids)) == 3, "session_id phải là duy nhất"
    for sid, mong_doi in zip(ids, cau_hoi):
        assert _doi_xong(may_chu, sid)["cau_hoi"] == mong_doi
