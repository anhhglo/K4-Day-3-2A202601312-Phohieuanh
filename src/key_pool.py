"""
🔑 KEY POOL — xoay nhiều API key khi một key hết quota

Vì sao cần: free tier Gemini giới hạn **20 request/ngày, tính riêng từng model,
từng project**. Một buổi demo chạy vài case là chạm trần. Bốn thành viên góp bốn
key thì thành 80 request/ngày — đây là cách duy nhất thật sự thoát khỏi cái trần
đó mà không phải trả tiền.

Cách khai báo trong `.env` (dùng được cả ba dạng, gộp lại và khử trùng lặp):

    OPENAI_API_KEY=key_cua_ban_A
    OPENAI_API_KEY_2=key_cua_ban_B
    OPENAI_API_KEY_3=key_cua_ban_C
    OPENAI_API_KEYS=key_cua_ban_D,key_cua_ban_E   # phân cách bằng dấu phẩy

⚠️ Module này **tuyệt đối không gọi mạng**. Nó chỉ ghi nhớ chuyện gì đã xảy ra với
từng key và trả lời câu hỏi "giờ nên dùng key nào". Nhờ vậy toàn bộ logic xoay key
test được offline — thứ mà nếu phải debug bằng quota thật thì mỗi lần thử là mất
một phần hạn mức ngày.
"""

import os
import time

#: Ngưỡng để phân biệt "nghỉ một lát" với "hết quota ngày". Gemini trả retryDelay
#: vài chục giây cho hạn mức PHÚT, và hàng trăm/nghìn giây cho hạn mức NGÀY.
NGUONG_HET_NGAY_GIAY = 600

#: Số hậu tố tối đa dò tìm: OPENAI_API_KEY_2 ... OPENAI_API_KEY_10
SO_HAU_TO_TOI_DA = 10

# Trạng thái một key
ALIVE = "alive"           # dùng được ngay
COOLDOWN = "cooldown"     # dính 429 hạn mức phút, chờ hết giờ là dùng lại được
EXHAUSTED = "exhausted"   # hết hạn mức ngày, coi như mất tới khi sang ngày mới
INVALID = "invalid"       # 401/403 — key sai/bị thu hồi, loại vĩnh viễn trong phiên

#: Nhãn tiếng Việt cho giao diện.
NHAN = {
    ALIVE: "Sẵn sàng",
    COOLDOWN: "Đang nghỉ",
    EXHAUSTED: "Hết quota ngày",
    INVALID: "Key không hợp lệ",
}


def che_key(key: str) -> str:
    """`AQ.Xy9kLm...pqr3f2` -> `AQ.Xy9…3f2`. Đủ để phân biệt, không đủ để dùng lại.

    Giao diện web hiển thị bảng key cho cả lớp nhìn. In nguyên key lên màn chiếu
    là phát khoá API cho cả phòng.
    """
    if not key:
        return "(rỗng)"
    if len(key) <= 12:
        return key[:3] + "…"
    return f"{key[:6]}…{key[-3:]}"


def doc_key_tu_env(env: dict = None) -> list:
    """Gom key từ cả ba dạng khai báo, giữ thứ tự, khử trùng lặp.

    Thứ tự có ý nghĩa: key đầu tiên được dùng trước và dùng cho tới khi hỏng.
    Không luân phiên đều — dồn vào một key rồi mới sang key kế giúp người demo
    biết chắc mình đang tiêu quota của ai, thay vì tiêu lem nhem cả bốn.
    """
    env = env if env is not None else os.environ
    ung_vien = [env.get("OPENAI_API_KEY", "")]
    for i in range(2, SO_HAU_TO_TOI_DA + 1):
        ung_vien.append(env.get(f"OPENAI_API_KEY_{i}", ""))
    ung_vien.extend((env.get("OPENAI_API_KEYS") or "").split(","))

    ket_qua = []
    for raw in ung_vien:
        key = (raw or "").strip().strip("'\"")
        if key and key not in ket_qua:
            ket_qua.append(key)
    return ket_qua


class KeyPool:
    """Quản lý một tập API key và quyết định lượt dùng.

    ⚠️ **Trạng thái theo dõi theo cặp (key, model), không phải theo key.** Hạn mức
    free tier của Gemini tính riêng cho từng *model* của từng *project*, mà key
    chính là thứ xác định project. Nói cách khác: key A cạn quota trên
    `gemini-3.5-flash` **vẫn còn nguyên** hạn mức trên `gemini-3.5-flash-lite`.

    Theo dõi theo key thôi thì sau khi model chính cạn, mọi key bị coi là đang
    nghỉ, model phụ không bao giờ được thử — và cả cơ chế "mỗi model một hạn mức
    riêng" trở thành vô dụng đúng vào lúc cần nó nhất. Chính một test đã bắt được
    chuyện này (`test_xoay_sang_model_phu_khi_model_chinh_het_quota`).

    Riêng 401/403 thì ngược lại: key sai là sai với **mọi** model, nên
    `danh_dau_hong` loại key khỏi tất cả các model cùng lúc.

    `time_fn` tiêm được để test kiểm tra chuyện hết cooldown mà không phải ngủ thật.
    """

    def __init__(self, keys=None, time_fn=time.time):
        self._time = time_fn
        self._keys = list(keys) if keys is not None else doc_key_tu_env()
        self._trang_thai = {}   # (key, model) -> info
        self._key_hong = set()  # key sai/bị thu hồi — hỏng với mọi model

    # ------------------------------------------------------------------ ĐỌC
    def __len__(self):
        return len(self._keys)

    @property
    def keys(self) -> list:
        return list(self._keys)

    def _info(self, key: str, model: str) -> dict:
        return self._trang_thai.setdefault((key, model), {
            "trang_thai": ALIVE,
            "cho_den": 0.0,
            "so_lan_dung": 0,
            "so_lan_hong": 0,
            "lan_cuoi": None,
            "ly_do": "",
        })

    def _trang_thai_hien_tai(self, key: str, model: str) -> str:
        if key in self._key_hong:
            return INVALID
        info = self._info(key, model)
        if info["trang_thai"] in (COOLDOWN, EXHAUSTED) and self._time() >= info["cho_den"]:
            # Hết giờ phạt thì tự sống lại — không cần ai gọi hàm dọn dẹp.
            info["trang_thai"] = ALIVE
            info["ly_do"] = ""
        return info["trang_thai"]

    def key_kha_dung(self, model: str = "") -> list:
        return [k for k in self._keys if self._trang_thai_hien_tai(k, model) == ALIVE]

    def con_key_song(self, model: str = "") -> bool:
        return bool(self.key_kha_dung(model))

    def key_tiep_theo(self, model: str = ""):
        """Key nên dùng cho model này, hoặc None nếu không còn key nào dùng được."""
        kha_dung = self.key_kha_dung(model)
        return kha_dung[0] if kha_dung else None

    def cho_lau_nhat(self, model: str = "") -> float:
        """Số giây tới lúc key sớm nhất sống lại. 0 nếu đang có key sống.

        Trả về `float('inf')` khi mọi key đều hỏng vĩnh viễn — lúc đó chờ là vô
        ích, phải đổi model hoặc tụt về chế độ offline.
        """
        if self.con_key_song(model):
            return 0.0
        cac_moc = [self._info(k, model)["cho_den"] for k in self._keys
                   if self._trang_thai_hien_tai(k, model) in (COOLDOWN, EXHAUSTED)]
        if not cac_moc:
            return float("inf")
        return max(min(cac_moc) - self._time(), 0.0)

    def trang_thai(self, model: str = "") -> list:
        """Bảng trạng thái cho giao diện. Key đã được che, an toàn để hiển thị."""
        bang = []
        for chi_so, key in enumerate(self._keys, 1):
            tt = self._trang_thai_hien_tai(key, model)
            info = self._info(key, model)
            con_lai = (max(info["cho_den"] - self._time(), 0.0)
                       if tt in (COOLDOWN, EXHAUSTED) and info["cho_den"] != float("inf")
                       else 0.0)
            bang.append({
                "chi_so": chi_so,
                "key_che": che_key(key),
                "model": model,
                "trang_thai": tt,
                "nhan": NHAN[tt],
                "con_cho_giay": round(con_lai),
                "so_lan_dung": info["so_lan_dung"],
                "so_lan_hong": info["so_lan_hong"],
                "lan_cuoi": info["lan_cuoi"],
                "ly_do": info["ly_do"] if key not in self._key_hong else "HTTP 401/403",
            })
        return bang

    # ------------------------------------------------------------------ GHI
    def danh_dau_thanh_cong(self, key: str, model: str = "") -> None:
        if key not in self._keys:
            return
        info = self._info(key, model)
        info["trang_thai"] = ALIVE
        info["cho_den"] = 0.0
        info["ly_do"] = ""
        info["so_lan_dung"] += 1
        info["lan_cuoi"] = self._time()

    def danh_dau_het_quota(self, key: str, cho_giay: float, ly_do: str = "",
                           model: str = "") -> None:
        """429. Chờ ngắn là hạn mức phút; chờ dài nghĩa là hết hạn mức ngày.

        Chỉ phạt cặp (key, model) này. Cùng key trên model khác vẫn dùng được.
        """
        if key not in self._keys:
            return
        info = self._info(key, model)
        info["so_lan_hong"] += 1
        info["lan_cuoi"] = self._time()
        info["ly_do"] = ly_do or "HTTP 429"
        info["cho_den"] = self._time() + cho_giay
        info["trang_thai"] = EXHAUSTED if cho_giay >= NGUONG_HET_NGAY_GIAY else COOLDOWN

    def danh_dau_hong(self, key: str, ly_do: str = "") -> None:
        """401/403. Key sai hoặc bị thu hồi — hỏng với MỌI model, chờ cũng vô ích.

        Khác hẳn 429 ở hai điểm: không giới hạn theo model, và không hết hạn. Phạt
        tạm thời một key hỏng vĩnh viễn thì cứ hết cooldown nó lại được chọn, và
        mỗi lần chọn lại là một request ném đi.
        """
        if key not in self._keys:
            return
        self._key_hong.add(key)
        info = self._info(key, "")
        info["so_lan_hong"] += 1
        info["lan_cuoi"] = self._time()
        info["ly_do"] = ly_do or "HTTP 401/403"

    def dat_lai(self) -> None:
        """Cho mọi key sống lại. Dùng cho nút 'Cho key sống lại' trên giao diện."""
        self._key_hong.clear()
        for info in self._trang_thai.values():
            info["trang_thai"] = ALIVE
            info["cho_den"] = 0.0
            info["ly_do"] = ""


#: Pool dùng chung toàn tiến trình. Trạng thái key phải sống xuyên suốt các lời
#: gọi, nếu không thì mỗi request lại tưởng mọi key đều còn tốt và thử lại từ đầu.
_POOL = None


def pool_chung() -> KeyPool:
    global _POOL
    if _POOL is None:
        _POOL = KeyPool()
    return _POOL


def dat_pool_chung(pool) -> None:
    """Thay pool dùng chung — cho test và cho việc nạp lại .env khi đang chạy."""
    global _POOL
    _POOL = pool
