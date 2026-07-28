"""
🔌 PROVIDERS
Lớp trung gian gọi LLM, hỗ trợ tự động chuyển đổi (failover) giữa nhiều nhà cung cấp miễn phí
(Groq, Google Gemini) khi một bên bị rate-limit / hết quota (HTTP 429), để demo không bị gián đoạn.

⚠️ QUAN TRỌNG VỀ "TRÍ NHỚ": Groq và Gemini đều là API stateless - bản thân LLM KHÔNG tự nhớ
gì giữa các lần gọi, kể cả khi gọi liên tục cùng 1 provider không đổi. Toàn bộ "trí nhớ" của
agent phải nằm ở phía CALLER (app.py) - biến lưu lại toàn bộ lịch sử Thought/Action/Observation
từ đầu phiên tới giờ. Vì vậy `user_message` truyền vào call_llm_with_fallback() PHẢI LUÔN LÀ TOÀN
BỘ lịch sử tính đến hiện tại (không phải chỉ observation/tin nhắn mới nhất) - xem ví dụ ở cuối
file. Nếu làm đúng điều này, việc chuyển đổi Groq <-> Gemini giữa chừng KHÔNG làm mất bất kỳ
ngữ cảnh nào, vì mỗi lần gọi (dù provider nào) đều nhận lại đầy đủ lịch sử y hệt nhau.

Cách dùng trong app.py:
    from providers import call_llm_with_fallback
    reply_text = call_llm_with_fallback(system_prompt=REACT_SYSTEM_PROMPT, user_message=full_history)

Yêu cầu biến môi trường (đặt trong .env):
    GROQ_API_KEY=...
    GEMINI_API_KEY=...
    (có thể chỉ cần 1 trong 2 - vẫn chạy được, chỉ mất khả năng failover)

Yêu cầu package: requests (và tuỳ chọn python-dotenv để tự load .env khi chạy file này độc lập)
"""

import os
import re
import time

import requests

import key_pool

try:  # cho phép chạy `python providers.py` độc lập mà vẫn đọc được .env
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Cấu hình từng provider
# ---------------------------------------------------------------------------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Lưu ý: tên model free-tier của Gemini có thể đổi theo thời gian - kiểm tra lại trong
# Google AI Studio (aistudio.google.com) nếu gặp lỗi "model not found".
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# Endpoint tương thích OpenAI. Dùng được cho chính OpenAI, cho Gemini qua
# `/v1beta/openai/`, cho OpenRouter, Groq, Together... — bất cứ đâu nói giao thức
# `/chat/completions`. Key và model đọc tại THỜI ĐIỂM GỌI chứ không phải lúc
# import, để đổi model qua `--model` hay qua os.environ có hiệu lực ngay.
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.environ.get("LLM_MODEL") or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

REQUEST_TIMEOUT_SECONDS = 30  # timeout gọi mạng tới LLM. Đây là timeout DUY NHẤT của dự án.
COOLDOWN_SECONDS = 60         # sau khi 1 provider báo hết quota, tạm bỏ qua nó bao nhiêu giây

# Thứ tự ưu tiên thử. `openai` đứng đầu vì đó là cấu hình trong `.env` của nhóm
# (Gemini đi qua endpoint OpenAI-compat). Provider nào thiếu key sẽ tự loại mình
# ngay lập tức mà không tốn một lượt gọi mạng nào, nên để cả ba ở đây là an toàn.
PROVIDER_ORDER = ["openai", "groq", "gemini"]

#: Provider tự lo trạng thái quota ở mức chi tiết hơn nhiều — `key_pool` theo dõi
#: từng cặp (key, model). Phạt thêm ở mức provider là ĐÈ LÊN thứ chi tiết đó và
#: làm hỏng nó: model chính hết quota kéo theo cả provider bị treo, nên khi xoay
#: sang model phụ (hạn mức riêng, vẫn còn nguyên) thì không tới lượt được nữa.
#: Groq/Gemini không có pool riêng nên vẫn cần cooldown mức provider.
TU_QUAN_LY_COOLDOWN = {"openai"}


class ProviderQuotaError(Exception):
    """Provider báo hết quota / bị rate-limit (HTTP 429 hoặc lỗi tương đương)."""

    def __init__(self, message: str, retry_after_seconds: float = COOLDOWN_SECONDS):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderError(Exception):
    """Lỗi khác không liên quan tới quota (thiếu key, lỗi mạng, sai định dạng phản hồi...)."""


class ProviderNetworkError(ProviderError):
    """Không tới được máy chủ: rớt mạng, DNS hỏng, timeout.

    Tách riêng khỏi `ProviderError` vì thủ phạm khác hẳn và cách chữa cũng khác.
    Gộp chung là mắc đúng cái bẫy này: mất mạng một giây, cả pool key bị đánh dấu
    hỏng oan, rồi khi mạng về thì không còn key nào được coi là dùng được nữa —
    demo tự bắn vào chân mình.
    """


class ProviderAuthError(ProviderError):
    """401/403 — key sai hoặc bị thu hồi. Chờ bao lâu cũng vô ích, phải đổi key."""


# Lưu thời điểm 1 provider bị đánh dấu hết quota -> tạm bỏ qua nó tới hết thời điểm này
_cooldown_until = {name: 0.0 for name in PROVIDER_ORDER}


def _resolve_cooldown_seconds(resp) -> float:
    """
    Xác định thời gian cooldown chính xác dựa trên header 'Retry-After' mà server trả về
    (nếu có) - vì lỗi 429 có thể là hết quota theo PHÚT (chờ vài giây là đủ) hoặc hết quota
    theo NGÀY (phải chờ rất lâu). Dùng COOLDOWN_SECONDS mặc định làm phương án dự phòng khi
    server không cung cấp thông tin này.
    """
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), 1.0)
        except ValueError:
            pass  # một số server trả về dạng HTTP-date thay vì số giây - bỏ qua, dùng mặc định

    # Gemini không gửi header 'Retry-After' mà nhét 'retryDelay': '25s' vào THÂN
    # phản hồi. Không đọc chỗ này thì mọi lần 429 đều bị phạt cứng 60 giây, kể cả
    # khi server bảo chờ 25 giây là đủ — và với cấu hình một-provider thì
    # `call_llm` retry 3 lần đều bị cooldown gạt đi, chờ vô ích rồi vẫn thất bại.
    try:
        khop = re.search(r"retryDelay\"?\s*:\s*\"?(\d+(?:\.\d+)?)s", resp.text)
    except Exception:  # noqa: BLE001 — resp.text có thể ném khi kết nối đứt giữa chừng
        khop = None
    if khop:
        return max(float(khop.group(1)) + 1, 1.0)
    return COOLDOWN_SECONDS


def _mot_lan_goi_openai(api_key: str, base: str, ten_model: str,
                        system_prompt: str, user_message: str) -> str:
    """ĐÚNG MỘT lần gọi với ĐÚNG MỘT key. Việc xoay key nằm ở hàm bao ngoài.

    Tách ra để mỗi hàm chỉ có một việc: hàm này biết cách nói chuyện với endpoint
    và phân loại lỗi; hàm ngoài biết nên thử key nào tiếp theo.
    """
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_message})

    try:
        resp = requests.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": ten_model, "messages": messages, "temperature": 0},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as e:
        # Rớt mạng / DNS / timeout — KHÔNG phải lỗi của key. Xem docstring
        # ProviderNetworkError để hiểu vì sao phân biệt chỗ này lại quan trọng.
        raise ProviderNetworkError(f"NETWORK_DOWN: không tới được {base} — "
                                   f"{type(e).__name__}: {e}")

    if resp.status_code == 429:
        raise ProviderQuotaError(
            f"OpenAI-compat rate-limit (429) model '{ten_model}': {resp.text[:300]}",
            retry_after_seconds=_resolve_cooldown_seconds(resp),
        )
    # 400 kèm lời than về API key CŨNG là lỗi xác thực. Google trả HTTP 400
    # "Please pass a valid API key" chứ không trả 401 như phần lớn API khác —
    # chỉ bắt 401/403 thì key sai không bao giờ bị loại, và mỗi vòng ReAct lại
    # ném thêm một request vào cùng cái key hỏng đó.
    la_loi_key = resp.status_code in (401, 403) or (
        resp.status_code == 400 and "api key" in resp.text.lower()
    )
    if la_loi_key:
        raise ProviderAuthError(
            f"KEY KHÔNG HỢP LỆ (HTTP {resp.status_code}) — máy chủ từ chối key này. "
            f"Kiểm tra OPENAI_API_KEY trong .env. Chi tiết: {resp.text[:180]}"
        )
    if resp.status_code >= 500:
        # 500/502/503/504 là máy chủ phía họ đang quá tải, KHÔNG phải lỗi của ta.
        # Gemini free tier trả 503 khá thường xuyên vào giờ cao điểm và tự khỏi sau
        # vài giây. Coi nó là lỗi vĩnh viễn thì một cơn nấc của Google giết cả buổi
        # demo. Gắn nhãn SERVER_BUSY để `call_llm` biết đây là thứ đáng thử lại.
        raise ProviderError(
            f"SERVER_BUSY: máy chủ trả HTTP {resp.status_code} cho model "
            f"'{ten_model}' — quá tải tạm thời, đáng thử lại. {resp.text[:200]}"
        )
    if resp.status_code != 200:
        raise ProviderError(
            f"OpenAI-compat lỗi HTTP {resp.status_code} model '{ten_model}': {resp.text[:300]}"
        )

    data = resp.json()
    try:
        lua_chon = data["choices"][0]
        message = lua_chon["message"]
    except (KeyError, IndexError) as e:
        raise ProviderError(f"OpenAI-compat trả về định dạng không như mong đợi: {e}")

    noi_dung = message.get("content")
    if noi_dung:
        return noi_dung

    # Gemini 3 là model "thinking". Qua endpoint OpenAI-compat, thỉnh thoảng nó
    # trả về message KHÔNG có khoá 'content' (chỉ có 'extra_content' chứa
    # thought_signature), hoặc content rỗng khi finish_reason='length'. Hiện
    # tượng này KHÔNG liên tục — chạy lại cùng prompt thì thành công. Truy thẳng
    # ["content"] sẽ ném KeyError giữa buổi demo với thông báo vô nghĩa: 'content'.
    for khoa in ("reasoning_content", "reasoning"):
        if message.get(khoa):
            return message[khoa]

    raise ProviderError(
        f"EMPTY_RESPONSE: model '{ten_model}' trả về nội dung rỗng "
        f"(finish_reason={lua_chon.get('finish_reason')!r}, "
        f"khoá có trong message: {sorted(message)}). Đây là lỗi tạm thời, đáng thử lại."
    )


def _call_openai_compat(system_prompt: str, user_message: str, model: str = None) -> str:
    """Gọi endpoint OpenAI-compat, tự xoay sang key khác khi key hiện tại hỏng.

    Nhóm dùng Gemini qua endpoint OpenAI-compat của Google
    (`OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`),
    nên đây mới là đường đi thật của mọi lời gọi LLM trong bài lab — không phải
    `_call_gemini` (đường native, cần `GEMINI_API_KEY` riêng).

    Ba loại hỏng, ba cách xử lý khác nhau:
      429      -> phạt key theo đúng retryDelay server báo, thử key kế tiếp
      401/403  -> loại key khỏi phiên, thử key kế tiếp
      mạng     -> KHÔNG phạt key nào cả, ném lên ngay để tầng trên chờ và thử lại
    """
    pool = key_pool.pool_chung()
    if len(pool) == 0:
        raise ProviderError(
            "Không có API key nào. Đặt OPENAI_API_KEY (và tuỳ chọn "
            "OPENAI_API_KEY_2..N hoặc OPENAI_API_KEYS) trong .env."
        )

    base = (os.environ.get("OPENAI_BASE_URL") or OPENAI_BASE_URL).rstrip("/")
    ten_model = model or os.environ.get("LLM_MODEL") or OPENAI_MODEL
    loi_cuoi = None

    # Nhiều nhất là thử mỗi key một lần. Không vòng lại: key vừa báo hết quota thì
    # lượt sau vẫn hết quota, thử lại chỉ tốn thêm thời gian đúng lúc đang gấp.
    for _ in range(len(pool)):
        api_key = pool.key_tiep_theo(ten_model)
        if api_key is None:
            break
        try:
            ket_qua = _mot_lan_goi_openai(api_key, base, ten_model,
                                          system_prompt, user_message)
            pool.danh_dau_thanh_cong(api_key, model=ten_model)
            return ket_qua
        except ProviderQuotaError as e:
            pool.danh_dau_het_quota(api_key, e.retry_after_seconds, str(e)[:120],
                                    model=ten_model)
            print(f"[key_pool] Key {key_pool.che_key(api_key)} hết quota trên "
                  f"'{ten_model}' ({e.retry_after_seconds:.0f}s) -> xoay sang key kế tiếp.")
            loi_cuoi = e
        except ProviderAuthError as e:
            pool.danh_dau_hong(api_key, str(e)[:120])
            print(f"[key_pool] Key {key_pool.che_key(api_key)} bị từ chối "
                  f"-> loại khỏi phiên, xoay sang key kế tiếp.")
            loi_cuoi = e

    if not pool.con_key_song(ten_model):
        cho = pool.cho_lau_nhat(ten_model)
        mo_ta = "không key nào còn dùng được" if cho == float("inf") \
            else f"key sớm nhất sống lại sau {cho:.0f}s"

        # `loi_cuoi` chỉ có giá trị khi vòng lặp vừa gọi thật. Nếu key đã bị đánh
        # dấu hỏng từ MỘT LỜI GỌI TRƯỚC thì vòng lặp thoát ngay và `loi_cuoi` là
        # None — thông báo thành "Lỗi cuối: None", tức là không nói gì cả đúng lúc
        # người dùng cần biết nhất. Pool vẫn nhớ lý do của từng key, hỏi lại nó.
        if loi_cuoi is None:
            ly_do = [f"{d['key_che']}: {d['ly_do']}"
                     for d in pool.trang_thai(ten_model) if d["ly_do"]]
            chi_tiet = "; ".join(ly_do) if ly_do else "không rõ nguyên nhân"
        else:
            chi_tiet = str(loi_cuoi)

        raise ProviderQuotaError(
            f"Đã thử hết {len(pool)} key cho model '{ten_model}' — {mo_ta}. {chi_tiet}",
            retry_after_seconds=(COOLDOWN_SECONDS if cho == float("inf") else cho),
        )
    raise loi_cuoi or ProviderError("Không gọi được key nào.")


def _call_groq(system_prompt: str, user_message: str, model: str = None) -> str:
    if not GROQ_API_KEY:
        raise ProviderError("Thiếu GROQ_API_KEY trong biến môi trường (.env).")

    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0,
    }
    resp = requests.post(GROQ_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)

    if resp.status_code == 429:
        raise ProviderQuotaError(
            f"Groq rate-limit (429): {resp.text[:200]}",
            retry_after_seconds=_resolve_cooldown_seconds(resp),
        )
    if resp.status_code != 200:
        raise ProviderError(f"Groq lỗi HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise ProviderError(f"Groq trả về định dạng không như mong đợi: {e}")


def _call_gemini(system_prompt: str, user_message: str, model: str = None) -> str:
    if not GEMINI_API_KEY:
        raise ProviderError("Thiếu GEMINI_API_KEY trong biến môi trường (.env).")

    url = (GEMINI_URL if not model else
           f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent")
    params = {"key": GEMINI_API_KEY}
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": {"temperature": 0},
    }
    resp = requests.post(url, params=params, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)

    if resp.status_code == 429:
        raise ProviderQuotaError(
            f"Gemini rate-limit (429): {resp.text[:200]}",
            retry_after_seconds=_resolve_cooldown_seconds(resp),
        )
    if resp.status_code != 200:
        raise ProviderError(f"Gemini lỗi HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        raise ProviderError(f"Gemini trả về định dạng không như mong đợi: {e}")


_CALLERS = {
    "openai": _call_openai_compat,
    "groq": _call_groq,
    "gemini": _call_gemini,
}


def call_llm_with_fallback(system_prompt: str, user_message: str, verbose: bool = True,
                           model: str = None, prefer: str = None) -> str:
    """
    Gọi LLM với khả năng tự động chuyển provider khi bị rate-limit/hết quota.

    `prefer` đẩy một provider lên đầu hàng đợi; `model` chỉ áp cho provider đó.
    Không áp `model` cho các provider còn lại là có chủ đích: ném tên model của
    Gemini sang Groq thì chắc chắn HTTP 400, và fallback lẽ ra để cứu demo lại
    thành thứ làm hỏng demo.
    """
    now = time.time()
    errors = []

    order = list(PROVIDER_ORDER)
    if prefer and prefer in order:
        order = [prefer] + [n for n in order if n != prefer]

    for name in order:
        if name not in TU_QUAN_LY_COOLDOWN and now < _cooldown_until.get(name, 0.0):
            remaining = int(_cooldown_until[name] - now)
            if verbose:
                print(f"[providers] Bỏ qua '{name}' - đang cooldown thêm {remaining}s.")
            # Ghi vào errors: thông báo cuối phải nói rõ provider nào bị BỎ QUA vì
            # cooldown. Không ghi thì người đọc log chỉ thấy 'thiếu GROQ_API_KEY'
            # rồi đi tìm key, trong khi nguyên nhân thật là provider chính hết quota.
            errors.append(f"{name}: đang cooldown, còn {remaining}s")
            continue

        try:
            if verbose:
                print(f"[providers] Đang gọi '{name}'...")
            text = _CALLERS[name](system_prompt, user_message,
                                  model if name == prefer else None)
            if verbose:
                print(f"[providers] '{name}' trả lời thành công.")
            return text
        except ProviderQuotaError as e:
            print(f"[providers] '{name}' HẾT QUOTA -> tự động chuyển sang provider kế tiếp. ({e})")
            if name not in TU_QUAN_LY_COOLDOWN:
                _cooldown_until[name] = time.time() + e.retry_after_seconds
            errors.append(f"{name}: {e}")
            continue
        except ProviderError as e:
            print(f"[providers] '{name}' lỗi -> thử provider kế tiếp. ({e})")
            errors.append(f"{name}: {e}")
            continue

    # Provider được ưu tiên (`prefer`) là đường đi thật của lời gọi này; các
    # provider sau chỉ là dự phòng và gần như luôn báo "thiếu KEY_ABC" vì nhóm
    # không cấu hình chúng. Để nguyên thứ tự thì nguyên nhân THẬT bị chôn dưới hai
    # dòng nhiễu, và người đọc đi tìm nhầm thứ — đúng cái bẫy này đã làm mất thời
    # gian khi dựng bản demo sạch.
    chinh = [e for e in errors if prefer and e.startswith(f"{prefer}:")]
    phu = [e for e in errors if e not in chinh]
    raise ProviderError(
        "Không gọi được LLM.\n"
        + "\n".join(f"➤ {e}" for e in chinh)
        + ("\n(các provider dự phòng chưa cấu hình: "
           + "; ".join(e.split(":")[0] for e in phu) + ")" if phu else "")
    )


# ===========================================================================
# LỚP TƯƠNG THÍCH NGƯỢC (BACKWARD COMPATIBILITY ADAPTER)
# Đảm bảo app.py, các file kiểm thử và Cấp độ AI 2, 3, 4 không bị lỗi import
# ===========================================================================

class BaseLLMProvider:
    """Interface cơ sở cho tất cả các LLM Provider.

    GIAO KÈO QUAN TRỌNG: `generate` LỖI thì phải TRẢ VỀ chuỗi dạng
    '[X Exception]: ...' chứ KHÔNG được raise. Cả `llm_utils.is_provider_error`
    lẫn cơ chế retry 429 và guardrail `llm_error` của vòng lặp ReAct đều dựa vào
    giao kèo này — provider nào raise sẽ làm sập cả vòng lặp thay vì được xử lý
    tử tế.
    """
    def generate(self, prompt: str, system_prompt: str = "") -> str:
        raise NotImplementedError


def _goi_an_toan(system_prompt: str, prompt: str, nhan: str,
                 model: str = None, prefer: str = None) -> str:
    """Bọc `call_llm_with_fallback` để đổi exception thành chuỗi lỗi đúng giao kèo.

    Giữ nguyên từ khoá '429' / 'RESOURCE_EXHAUSTED' trong thông báo khi lỗi là do
    hết quota, để `call_llm` biết đây là trường hợp đáng retry.
    """
    try:
        return call_llm_with_fallback(system_prompt, prompt, verbose=False,
                                      model=model, prefer=prefer)
    except ProviderQuotaError as e:
        return f"[{nhan} Exception]: Error code: 429 - RESOURCE_EXHAUSTED {e}"
    except ProviderError as e:
        return f"[{nhan} Exception]: {e}"
    except Exception as e:  # noqa: BLE001 — mạng chập chờn, JSON hỏng...
        return f"[{nhan} Exception]: {type(e).__name__}: {e}"


class GeminiProvider(BaseLLMProvider):
    """Google Gemini Provider (đi qua cơ chế failover)."""
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model_name = model or GEMINI_MODEL

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        return _goi_an_toan(system_prompt, prompt, "Gemini",
                            model=self.model_name, prefer="gemini")


class OpenAIProvider(BaseLLMProvider):
    """Provider tương thích OpenAI.

    Cấp 4 dùng lớp này để tách Evaluator sang một model phụ
    (`OpenAIProvider(model=LAB_MINI_MODEL)`) — quota free tier tính riêng theo
    từng model nên judge không ăn vào hạn mức của agent chính.
    """
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.model_name = model or os.environ.get("LLM_MODEL") or OPENAI_MODEL

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        return _goi_an_toan(system_prompt, prompt, "OpenAI",
                            model=self.model_name, prefer="openai")


class FallbackProvider(BaseLLMProvider):
    """Fallback Provider sử dụng cơ chế failover Groq/Gemini"""
    def __init__(self, model: str = None):
        self.model_name = model or f"{GROQ_MODEL} → {GEMINI_MODEL}"

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        return _goi_an_toan(system_prompt, prompt, "Fallback")


class MockProvider(BaseLLMProvider):
    """Provider giả lập offline — đi trọn một vòng ReAct thật, không gọi mạng.

    Dùng cho `python src/web_demo.py --mock` và cho nấc cuối của
    `ResilientProvider`. Đây là phương án cứu hộ khi hết quota hoặc mất mạng ngay
    trước giờ demo, nên nó phải **diễn được vòng lặp ReAct**, không chỉ trả một
    câu rồi thôi.

    ⚠️ Bản trước dò `"observation:" in prompt` để đoán đang ở giữa vòng lặp.
    Nhưng chính REACT_SYSTEM_PROMPT có chứa chuỗi đó (ở quy tắc "TUYỆT ĐỐI không
    tự viết Observation:"), nên điều kiện luôn đúng ngay từ vòng đầu — Mock chưa
    bao giờ gọi nổi một tool nào, kể cả cho case vốn cần 4 tool. Nay đếm số
    Observation trong phần SCRATCHPAD (khúc sau "Câu hỏi:") để biết đang ở bước
    mấy, thay vì dò cả prompt.
    """

    #: Chuỗi tool mô phỏng đúng thứ tự một agent thật đi qua.
    KICH_BAN = [
        ("get_expense_report", "Cần mở hồ sơ đơn chi phí trước khi kết luận."),
        ("get_policy", "Đã có chi tiết đơn, giờ tra chính sách hạng mục."),
        ("check_budget", "Kiểm tra ngân sách cost center còn đủ không."),
        ("find_duplicate_claims", "Dò trùng lặp và dấu hiệu xé nhỏ hoá đơn."),
    ]

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        # Chỉ nhìn phần hội thoại, bỏ qua system prompt.
        hoi_thoai = prompt.split("Câu hỏi:", 1)[-1]
        buoc = hoi_thoai.count("Observation:")

        ma_don = re.search(r"(EXP-\d{4}-\d{4})", hoi_thoai, re.I)
        if not ma_don:
            return ("Thought: Câu hỏi này là kiến thức chung, không cần tra hệ thống.\n"
                    "Final Answer: 🤖 [Mock Provider — KẾT QUẢ GIẢ LẬP] Quy trình duyệt "
                    "chi phí thường gồm: nộp chứng từ, đối chiếu chính sách, kiểm tra "
                    "ngân sách, phê duyệt theo thẩm quyền.")
        don = ma_don.group(1).upper()

        if buoc < len(self.KICH_BAN):
            ten_tool, suy_nghi = self.KICH_BAN[buoc]

            # Tham số bóc từ chính Observation trước đó cho khớp ngữ cảnh; không
            # bóc được thì dùng giá trị mặc định có sẵn trong mock data.
            def _bat(mau, mac_dinh):
                khop = re.search(mau, hoi_thoai)
                return khop.group(1) if khop else mac_dinh

            hang_muc = _bat(r"\[(\w+)\]", "an_uong")
            cost_center = _bat(r"(CC-[A-Z]+)", "CC-ENG")
            nhan_vien = _bat(r"(EMP-\d+)", "EMP-001")
            # Vendor nằm ngay sau `[hạng_mục] ` và trước ` |` trong dòng line item.
            # Dùng [^|\n] để không cho khớp vắt qua nhiều dòng — nếu không nó vớ
            # phải "Số dòng: 1" ở dòng tổng bên trên.
            vendor = _bat(r"\]\s*([^|\n]+?)\s*\|", "Nhà hàng Ngon")

            tham_so = {
                "get_expense_report": don,
                "get_policy": hang_muc,
                "check_budget": f"{cost_center}, 2400000",
                "find_duplicate_claims": f"{nhan_vien}, {vendor}",
            }[ten_tool]
            return f"Thought: {suy_nghi}\nAction: {ten_tool}[{tham_so}]"

        return ("Thought: Đã thu thập đủ dữ liệu từ bốn công cụ bắt buộc.\n"
                f"Final Answer: 🤖 [Mock Provider — KẾT QUẢ GIẢ LẬP, KHÔNG PHẢI LLM THẬT] "
                f"NEEDS_INFO cho đơn {don}. Đây là phản hồi dựng sẵn để demo vòng lặp "
                f"ReAct khi không gọi được LLM — con số và kết luận KHÔNG phản ánh dữ "
                f"liệu thật của đơn.")


class ResilientProvider(BaseLLMProvider):
    """Provider cho buổi demo: xoay model, rồi tụt về Mock thay vì chết đứng.

    Thứ tự phòng thủ, từ rẻ tới đắt:

        key 1 → key 2 → ... (do `_call_openai_compat` lo, xem `key_pool.py`)
          → model chính → model phụ (mỗi model một hạn mức riêng)
            → MockProvider, gắn nhãn OFFLINE

    Nấc cuối là đánh đổi có chủ đích: buổi demo chạy tiếp còn hơn đứng hình, NHƯNG
    `da_tut_offline` bật lên để giao diện dán nhãn đỏ. Kết quả giả lập mà không nói
    rõ là giả lập thì tệ hơn nhiều so với một thông báo lỗi trung thực.

    `on_degrade(su_kien: dict)` được gọi mỗi lần tụt một nấc, để giao diện kể lại
    chuyện đang xảy ra theo thời gian thực thay vì im lặng vài giây rồi hiện kết quả.
    """

    #: Số lần sự cố TẠM THỜI liên tiếp trước khi chịu tụt offline. Một cơn chớp
    #: mạng hay một cú 503 của Google không được phép hạ cả phiên xuống giả lập —
    #: `call_llm` ở tầng trên còn chờ và thử lại được. Chỉ khi hỏng lì nhiều lần
    #: liên tiếp mới coi là hỏng thật.
    SO_LAN_TAM_THOI_CHIU_DUNG = 3

    def __init__(self, models=None, on_degrade=None, mock=None):
        if models is None:
            chinh = os.environ.get("LAB_MODEL") or os.environ.get("LLM_MODEL") or OPENAI_MODEL
            phu = os.environ.get("LAB_MINI_MODEL")
            models = [chinh] + ([phu] if phu and phu != chinh else [])
        self.models = list(models)
        self.model_name = self.models[0] if self.models else OPENAI_MODEL
        self._on_degrade = on_degrade
        self._mock = mock or MockProvider()
        self.da_tut_offline = False
        self.model_dang_dung = self.model_name
        self._so_lan_tam_thoi = 0
        # Bám lấy model vừa chạy được. Model chính cạn hạn mức NGÀY thì nó cạn
        # cho tới sáng mai — quay lại thử nó ở mỗi vòng ReAct chỉ tổ đẻ ra 8 dòng
        # cảnh báo "xoay_model" giống hệt nhau, lấp mất trace mà người xem cần đọc.
        self._chi_so_model = 0

    def _bao(self, loai: str, thong_diep: str, **thm) -> None:
        if self._on_degrade:
            self._on_degrade({"loai": loai, "thong_diep": thong_diep, **thm})

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        # Một khi đã tụt offline thì ở luôn đó cho hết phiên. Nhảy qua nhảy lại
        # giữa LLM thật và Mock làm cuộc hội thoại mâu thuẫn với chính nó, và
        # người xem không biết câu nào là thật.
        if self.da_tut_offline:
            return self._mock.generate(prompt, system_prompt=system_prompt)

        loi_cuoi = ""
        for chi_so in range(self._chi_so_model, len(self.models)):
            ten_model = self.models[chi_so]
            self.model_dang_dung = ten_model
            ket_qua = _goi_an_toan(system_prompt, prompt, "OpenAI",
                                   model=ten_model, prefer="openai")
            if not _la_loi(ket_qua):
                self._so_lan_tam_thoi = 0   # thành công thì xoá sạch tiền sử
                self._chi_so_model = chi_so  # lần sau bắt đầu thẳng từ model này
                return ket_qua

            loi_cuoi = ket_qua

            # Sự cố TẠM THỜI: mạng chớp, máy chủ quá tải. Trả chuỗi lỗi lên để
            # `call_llm` chờ rồi thử lại — KHÔNG hạ phiên xuống offline vì một cơn
            # nấc vài giây. Chỉ khi lặp lại liên tiếp mới coi là hỏng thật.
            if any(d in ket_qua for d in ("NETWORK_DOWN", "SERVER_BUSY")):
                self._so_lan_tam_thoi += 1
                mat_mang = "NETWORK_DOWN" in ket_qua
                if self._so_lan_tam_thoi < self.SO_LAN_TAM_THOI_CHIU_DUNG:
                    self._bao("su_co_tam_thoi",
                              ("Mất kết nối tới máy chủ LLM" if mat_mang
                               else "Máy chủ LLM đang quá tải") +
                              f" — thử lại (lần {self._so_lan_tam_thoi}/"
                              f"{self.SO_LAN_TAM_THOI_CHIU_DUNG}).",
                              chi_tiet=ket_qua[:200])
                    return ket_qua
                self._bao("mat_mang" if mat_mang else "may_chu_qua_tai",
                          f"Hỏng {self._so_lan_tam_thoi} lần liên tiếp — "
                          f"không còn coi là sự cố thoáng qua.",
                          chi_tiet=ket_qua[:200])
                break

            # Hết quota trên model này -> model kế tiếp có hạn mức riêng.
            if chi_so + 1 < len(self.models):
                self._bao("xoay_model",
                          f"Model '{ten_model}' không dùng được, chuyển sang "
                          f"'{self.models[chi_so + 1]}' (hạn mức riêng).",
                          tu=ten_model, sang=self.models[chi_so + 1])

        self.da_tut_offline = True
        self._bao("tut_offline",
                  "Đã thử hết key và model mà vẫn không gọi được LLM. "
                  "Chuyển sang CHẾ ĐỘ OFFLINE — mọi câu trả lời từ đây là GIẢ LẬP.",
                  chi_tiet=loi_cuoi[:300])
        return self._mock.generate(prompt, system_prompt=system_prompt)


def _la_loi(text: str) -> bool:
    """Bản sao cục bộ của `llm_utils.is_provider_error`.

    Không import llm_utils ở đây: llm_utils đứng TRÊN providers trong thứ tự phụ
    thuộc, import ngược lại là tạo vòng tròn.
    """
    return bool(text) and bool(re.match(r"^\[\w+ (Error|Exception)\]", text.strip()))


def get_llm_provider(provider_name: str = None) -> BaseLLMProvider:
    """Factory chọn provider theo biến môi trường `LLM_PROVIDER`.

    ⚠️ Bản trước bỏ qua hoàn toàn giá trị của `LLM_PROVIDER`: mọi giá trị khác
    `mock` đều rơi vào `FallbackProvider`, mà provider đó chỉ đọc
    `GROQ_API_KEY`/`GEMINI_API_KEY`. Nhóm cấu hình `LLM_PROVIDER=openai` với
    `OPENAI_API_KEY` + `OPENAI_BASE_URL` (Gemini qua endpoint OpenAI-compat) nên
    KHÔNG có đường chạy nào tới key thật — mọi lời gọi đều trả
    '[Fallback Exception]: Thiếu GROQ_API_KEY...'. Lỗi này chỉ lộ khi chạy LLM
    thật, tức là giữa buổi demo.
    """
    name = (provider_name or os.getenv("LLM_PROVIDER") or "mock").lower().strip()
    if name == "mock":
        return MockProvider()
    if name in ("openai", "openai_compat", "openrouter"):
        return OpenAIProvider()
    if name == "gemini":
        return GeminiProvider()
    return FallbackProvider()


if __name__ == "__main__":
    # Test nhanh - cần export GROQ_API_KEY và/hoặc GEMINI_API_KEY (hoặc để trong .env) trước khi chạy.
    try:
        reply = call_llm_with_fallback(
            system_prompt="Bạn là trợ lý trả lời ngắn gọn.",
            user_message="Việt Nam có bao nhiêu tỉnh thành? Trả lời trong 1 câu.",
        )
        print("\nKẾT QUẢ:", reply)
    except Exception as e:
        print("\nKhông thể chạy test nhanh do chưa cấu hình API Key:", e)

    # --- VÍ DỤ cách app.py PHẢI build "full_history" để không mất trí nhớ khi đổi provider ---
    # Sai (dễ gây "mất trí nhớ" - và sai ngay cả khi KHÔNG đổi provider):
    #     reply = call_llm_with_fallback(REACT_SYSTEM_PROMPT, latest_observation)
    #
    # Đúng (nối toàn bộ lịch sử ReAct từ đầu phiên, gửi lại trọn vẹn mỗi lần gọi):
    #     transcript = f"Question: {user_question}\n"
    #     for step in previous_steps:  # mỗi step gồm Thought/Action/Observation đã xảy ra
    #         transcript += f"Thought: {step['thought']}\nAction: {step['action']}\n"
    #         transcript += f"Observation: {step['observation']}\n"
    #     reply = call_llm_with_fallback(REACT_SYSTEM_PROMPT, transcript)
    #     # -> transcript ở trên PHẢI được truyền y hệt dù lần này Groq hay Gemini xử lý.
