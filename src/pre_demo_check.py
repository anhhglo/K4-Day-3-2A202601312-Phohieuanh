"""
🚦 KIỂM THỬ TRƯỚC KHI DEMO

Chạy MỘT lệnh này ngay trước khi lên trình bày. Tám kiểm tra, **không tốn một
lượt quota LLM nào** — vì thứ hay làm hỏng demo không phải là LLM trả lời dở, mà
là những chuyện tầm thường hơn nhiều: quên `git pull` nên thiếu file, `.env`
trỏ sai provider, hoặc một artifact chấm điểm chưa từng được tạo.

    python src/pre_demo_check.py           # 8 kiểm tra offline, ~2 giây
    python src/pre_demo_check.py --live    # thêm ĐÚNG 1 request thật để xem key còn quota

Mã thoát 0 nếu mọi kiểm tra bắt buộc đều đạt, 1 nếu có cái hỏng.
"""

import argparse
import json
import os
import re
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
sys.path.insert(0, SRC_DIR)

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

#: Artifact mà rubric chấm điểm trực tiếp. Thiếu file nào là mất trọn phần trăm đó.
ARTIFACT_BAT_BUOC = {
    "config/test_cases.json": "Tiêu chí 1 — Test Design (20%)",
    "docs/trace_eval.md": "Tiêu chí 1 + 3 — Agentic Fit & Trace log (40%)",
    "docs/test_results.md": "Bằng chứng chạy thật",
    "docs/hybrid_flowchart.mermaid": "Tiêu chí 5 — Hybrid Flowchart (10%)",
    "docs/cross_audit.md": "Tiêu chí 4 — Cross-Audit (20%)",
    "docs/PHAN_CONG_CONG_VIEC.md": "Sổ tay phân vai",
    "docs/HUONG_DAN_CHAY_DEMO.md": "Hướng dẫn cài đặt & chạy demo cho người mới",
}

#: Các trường máy đọc được mà `run_tests.judge()` dựa vào để chấm.
TRUONG_MAY_DOC = ("min_tools", "max_tools", "forbidden_tools",
                  "forbidden_decision", "expected_decision")

#: Dấu hiệu của key CHƯA ĐIỀN. Người mới copy `.env.example` thành `.env` rồi quên
#: thay key thật — mọi kiểm tra vẫn xanh vì nhìn bề ngoài "có key", và chuyện vỡ
#: lở đúng lúc đứng trước lớp. Một bộ kiểm tra báo ĐẠT cho môi trường chưa dùng
#: được thì tệ hơn là không có bộ kiểm tra nào.
DAU_HIEU_KEY_GIA = ("dan_key", "your_", "_here", "xxx", "changeme",
                    "todo", "abc123", "<", "...")


class KetQua:
    def __init__(self):
        self.hong = []
        self.canh_bao = []

    def dat(self, ten, chi_tiet=""):
        print(f"  ✅ {ten}" + (f" — {chi_tiet}" if chi_tiet else ""))

    def truot(self, ten, chi_tiet):
        print(f"  ❌ {ten} — {chi_tiet}")
        self.hong.append(f"{ten}: {chi_tiet}")

    def luu_y(self, ten, chi_tiet):
        print(f"  ⚠️  {ten} — {chi_tiet}")
        self.canh_bao.append(f"{ten}: {chi_tiet}")


# ----------------------------------------------------------------- KIỂM TRA 1
def kiem_tra_pytest(kq: KetQua) -> None:
    print("\n[1/8] Bộ test offline")
    # KHÔNG thêm '-q': pytest.ini đã có sẵn, thêm nữa thành '-qq' và pytest nuốt
    # luôn dòng tổng kết '143 passed' — checker sẽ báo đỏ oan dù test xanh hết.
    # Mã thoát mới là nguồn sự thật; con số chỉ để hiển thị cho đẹp.
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/"],
        cwd=BASE_DIR, capture_output=True, text=True,
    )
    dau = re.search(r"(\d+) passed", proc.stdout)
    so_hong = re.search(r"(\d+) failed", proc.stdout)
    if proc.returncode == 0:
        kq.dat("pytest", f"{dau.group(1)} test xanh" if dau else "xanh")
    else:
        kq.truot("pytest", f"{so_hong.group(1) if so_hong else '?'} test đỏ — "
                           f"chạy `python -m pytest tests/ -v` để xem chi tiết")


# ----------------------------------------------------------------- KIỂM TRA 2
def kiem_tra_test_cases(kq: KetQua) -> None:
    print("\n[2/8] Bộ test case")
    duong_dan = os.path.join(BASE_DIR, "config", "test_cases.json")
    try:
        with open(duong_dan, encoding="utf-8") as f:
            cases = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        kq.truot("test_cases.json", f"không đọc được: {e}")
        return

    if not isinstance(cases, list) or not cases:
        kq.truot("test_cases.json", "phải là danh sách không rỗng")
        return

    thieu = []
    for case in cases:
        vang = [t for t in TRUONG_MAY_DOC if t not in case]
        if vang:
            thieu.append(f"case {case.get('id', '?')} thiếu {', '.join(vang)}")
    if thieu:
        kq.truot("Trường máy đọc", "; ".join(thieu[:3]))
    else:
        kq.dat("test_cases.json", f"{len(cases)} case, đủ 4 trường máy đọc")

    ids = [c.get("id") for c in cases]
    if len(set(ids)) != len(ids):
        kq.truot("Mã case", f"trùng id: {ids}")


# ----------------------------------------------------------------- KIỂM TRA 3
def kiem_tra_registry(kq: KetQua) -> None:
    print("\n[3/8] Registry tool và prompt")
    try:
        import prompts
        import tools
    except Exception as e:  # noqa: BLE001
        kq.truot("Import", f"{type(e).__name__}: {e}")
        return

    ten_tool = set(tools.AVAILABLE_TOOLS)
    if len(ten_tool) != 7:
        kq.truot("Registry", f"có {len(ten_tool)} tool, spec yêu cầu 7: {sorted(ten_tool)}")
    else:
        kq.dat("Registry", "7 tool")

    quang_cao = set(re.findall(r"^\s*\d+\.\s*([a-z_]+)\[", prompts.REACT_SYSTEM_PROMPT, re.M))
    lech = quang_cao ^ ten_tool
    if lech:
        kq.truot("Prompt ↔ registry", f"lệch nhau ở: {sorted(lech)}")
    else:
        kq.dat("Prompt ↔ registry", "khớp hoàn toàn")

    if getattr(prompts, "MAX_ITERATIONS", 0) < 7:
        kq.truot("MAX_ITERATIONS", f"={getattr(prompts, 'MAX_ITERATIONS', None)}, "
                                   f"không đủ cho chuỗi 6 tool + 1 vòng kết luận")
    else:
        kq.dat("MAX_ITERATIONS", str(prompts.MAX_ITERATIONS))


# ----------------------------------------------------------------- KIỂM TRA 4
def kiem_tra_bon_cap_do(kq: KetQua) -> None:
    print("\n[4/8] Bốn cấp độ AI chạy được offline")
    import importlib

    for ten in ("level1_rule_based", "level2_llm_chatbot",
                "level3_reactive_agent", "level4_autonomous_agent"):
        try:
            importlib.import_module(f"ai_levels.{ten}")
            kq.dat(ten)
        except Exception as e:  # noqa: BLE001
            kq.truot(ten, f"{type(e).__name__}: {e}")

    # Vòng lặp ReAct phải chạy trọn vẹn với provider giả — không chạm mạng.
    try:
        import app
        from providers import MockProvider

        trace = app.run_react_agent("Đơn EXP-2026-0142 có duyệt được không?", MockProvider())
        if "llm_error" in trace["guardrails"]:
            kq.truot("Vòng lặp ReAct (offline)", "báo llm_error dù dùng MockProvider")
        else:
            kq.dat("Vòng lặp ReAct (offline)",
                   f"{trace['steps']} bước, tool: {', '.join(trace['tools_called']) or 'không'}")
    except Exception as e:  # noqa: BLE001
        kq.truot("Vòng lặp ReAct (offline)", f"{type(e).__name__}: {e}")


# ----------------------------------------------------------------- KIỂM TRA 5
def kiem_tra_env(kq: KetQua) -> None:
    print("\n[5/8] Cấu hình .env")
    if not os.path.exists(os.path.join(BASE_DIR, ".env")):
        kq.truot(".env", "không tồn tại — copy từ .env.example rồi điền key")
        return

    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BASE_DIR, ".env"))
    except ImportError:
        kq.truot("python-dotenv", "chưa cài — `pip install -r requirements.txt`")
        return

    provider = (os.environ.get("LLM_PROVIDER") or "").lower().strip()
    if not provider:
        kq.truot("LLM_PROVIDER", "chưa đặt — sẽ chạy MockProvider, demo không có LLM thật")
        return

    #: Provider nào cần key nào. Đặt LLM_PROVIDER=openai mà chỉ có GEMINI_API_KEY
    #: là cấu hình chết: factory chọn OpenAIProvider rồi không tìm thấy key.
    KEY_CAN = {
        "openai": "OPENAI_API_KEY", "openai_compat": "OPENAI_API_KEY",
        "openrouter": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
        "groq": "GROQ_API_KEY",
    }
    kq.dat("LLM_PROVIDER", provider)

    if provider == "mock":
        kq.luu_y("Chế độ", "đang để `mock` — demo sẽ KHÔNG gọi LLM thật")
        return

    can = KEY_CAN.get(provider)
    gia_tri = os.environ.get(can) if can else None
    if can and not gia_tri:
        kq.truot(f"Thiếu {can}", f"LLM_PROVIDER={provider} bắt buộc phải có {can}")
    elif can:
        thap = gia_tri.lower()
        if any(dau in thap for dau in DAU_HIEU_KEY_GIA) or len(gia_tri) < 20:
            kq.truot(f"{can} chưa điền",
                     f"đang là giá trị mẫu ({gia_tri[:18]}…) — mở .env dán key thật vào. "
                     f"Lấy key miễn phí tại https://aistudio.google.com/apikey")
        else:
            kq.dat(can, "đã có key thật")

    # Đếm luôn tổng số key: bốn người góp bốn key là gấp bốn hạn mức ngày.
    try:
        import key_pool
        so_key = len(key_pool.doc_key_tu_env())
        if so_key > 1:
            kq.dat("Số key", f"{so_key} key -> ~{so_key * 20} request/ngày/model")
        elif so_key == 1:
            kq.luu_y("Số key", "chỉ 1 key (~20 request/ngày/model). Thêm "
                               "OPENAI_API_KEY_2..N để cả nhóm góp key")
    except Exception:  # noqa: BLE001
        pass

    if provider in ("openai", "openai_compat", "openrouter"):
        base = os.environ.get("OPENAI_BASE_URL", "")
        if base:
            kq.dat("OPENAI_BASE_URL", base)
        else:
            kq.luu_y("OPENAI_BASE_URL", "chưa đặt — sẽ gọi thẳng api.openai.com")

    if not os.environ.get("LLM_MODEL"):
        kq.luu_y("LLM_MODEL", "chưa đặt — dùng model mặc định")
    else:
        kq.dat("LLM_MODEL", os.environ["LLM_MODEL"])

    # Provider thật sự được chọn — đây là chỗ từng có lỗi định tuyến im lặng.
    try:
        from providers import get_llm_provider
        thuc_te = get_llm_provider().__class__.__name__
        if thuc_te == "MockProvider" and provider != "mock":
            kq.truot("Định tuyến provider", f"LLM_PROVIDER={provider} nhưng lại chọn MockProvider")
        else:
            kq.dat("Provider được chọn", thuc_te)
    except Exception as e:  # noqa: BLE001
        kq.truot("Định tuyến provider", f"{type(e).__name__}: {e}")


# ----------------------------------------------------------------- KIỂM TRA 6
def kiem_tra_artifact(kq: KetQua) -> None:
    print("\n[6/8] Artifact chấm điểm")
    for duong_dan, vi_sao in ARTIFACT_BAT_BUOC.items():
        day_du = os.path.join(BASE_DIR, duong_dan)
        if not os.path.exists(day_du):
            kq.truot(duong_dan, f"KHÔNG TỒN TẠI — {vi_sao}")
        elif os.path.getsize(day_du) < 200:
            kq.truot(duong_dan, f"gần như rỗng ({os.path.getsize(day_du)} byte) — {vi_sao}")
        else:
            kq.dat(duong_dan)


# ----------------------------------------------------------------- KIỂM TRA 7
def kiem_tra_flowchart(kq: KetQua) -> None:
    """Kiểm tra cấu trúc file mermaid mà không cần cài mermaid-cli.

    Không phải trình phân tích cú pháp đầy đủ — chỉ bắt ba kiểu hỏng khiến sơ đồ
    không render được và người chấm chỉ nhìn thấy một ô trống: sai từ khoá mở
    đầu, ngoặc/ngoặc kép lệch, và `class` trỏ tới node chưa khai báo.
    """
    print("\n[7/8] Cấu trúc Hybrid Flowchart")
    duong_dan = os.path.join(BASE_DIR, "docs", "hybrid_flowchart.mermaid")
    if not os.path.exists(duong_dan):
        kq.truot("hybrid_flowchart.mermaid", "không tồn tại")
        return

    with open(duong_dan, encoding="utf-8") as f:
        noi_dung = f.read()

    dong_that = [d for d in noi_dung.splitlines()
                 if d.strip() and not d.strip().startswith("%%")]
    if not dong_that or not re.match(r"^(flowchart|graph)\s+(TD|TB|LR|RL|BT)",
                                     dong_that[0].strip()):
        kq.truot("Từ khoá mở đầu",
                 f"dòng đầu là {dong_that[0].strip()[:40]!r}, cần 'flowchart TD' hoặc tương đương")
        return

    for ky_tu, ten in (("[", "]"), ("{", "}"), ("(", ")")):
        if noi_dung.count(ky_tu) != noi_dung.count(ten):
            kq.truot("Ngoặc lệch",
                     f"'{ky_tu}' xuất hiện {noi_dung.count(ky_tu)} lần, "
                     f"'{ten}' {noi_dung.count(ten)} lần")
            return
    if noi_dung.count('"') % 2 != 0:
        kq.truot("Ngoặc kép lệch", f"{noi_dung.count(chr(34))} dấu — phải là số chẵn")
        return

    #: Node được khai báo khi có hình dạng đi kèm: A["..."], B{{"..."}}, C(["..."])
    khai_bao = set(re.findall(r"(\w+)\s*[\[\{\(]", noi_dung))
    gan_class = set()
    # `\s` khớp cả xuống dòng nên `[\w,\s]+` sẽ nuốt liền mấy dòng `class` kế
    # tiếp thành một cụm. Giới hạn ở khoảng trắng TRONG dòng.
    for dong in re.findall(r"^[ \t]*class[ \t]+([\w,][\w,  \t]*?)[ \t]+\w+[ \t]*$", noi_dung, re.M):
        gan_class |= {t.strip() for t in dong.split(",") if t.strip()}

    mo_coi = gan_class - khai_bao
    if mo_coi:
        kq.truot("class trỏ tới node lạ", f"{sorted(mo_coi)} chưa được khai báo")
        return

    kq.dat("hybrid_flowchart.mermaid",
           f"{len(khai_bao)} node, ngoặc cân, class hợp lệ")


# ----------------------------------------------------------------- KIỂM TRA 8
def kiem_tra_giao_dien(kq: KetQua) -> None:
    """Dựng server thật trên cổng tạm, gọi thật các route, rồi tắt.

    Import được không có nghĩa là chạy được. Lỗi hay gặp nhất của tầng web là
    route trả 500 hoặc thiếu header — chỉ lộ khi thật sự gửi một request.
    """
    print("\n[8/8] Giao diện web")
    import json as _json
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer

    try:
        import web_demo
    except Exception as e:  # noqa: BLE001
        kq.truot("web_demo", f"không import được — {type(e).__name__}: {e}")
        return

    web_demo.Handler.dung_mock = True
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", 0), web_demo.Handler)
    except OSError as e:
        kq.truot("Mở cổng", f"{e}")
        return

    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.02},
                     daemon=True).start()
    goc = f"http://127.0.0.1:{srv.server_port}"
    try:
        with urllib.request.urlopen(goc + "/", timeout=5) as r:
            trang = r.read().decode("utf-8")
        kq.dat("Trang chủ", f"{len(trang):,} byte HTML")

        with urllib.request.urlopen(goc + "/api/health", timeout=5) as r:
            suc_khoe = _json.loads(r.read().decode("utf-8"))
        kq.dat("/api/health", f"{suc_khoe['so_key']} key, "
                              f"{'còn key sống' if suc_khoe['con_key_song'] else 'KHÔNG còn key sống'}")

        # Không key nào là chuyện thường khi mới clone về — cảnh báo, không chặn.
        if suc_khoe["so_key"] == 0:
            kq.luu_y("API key", "chưa có key nào — demo sẽ chạy ở chế độ offline")

        # Key thật tuyệt đối không được lọt vào HTML gửi ra trình duyệt.
        import key_pool
        for key in key_pool.pool_chung().keys:
            if key and key in trang:
                kq.truot("RÒ RỈ KEY", "key thật xuất hiện nguyên văn trong HTML")
                break
        else:
            kq.dat("Che key", "không có key nào lọt vào HTML")
    except Exception as e:  # noqa: BLE001
        kq.truot("Gọi thử route", f"{type(e).__name__}: {e}")
    finally:
        srv.shutdown()
        srv.server_close()


# ------------------------------------------------------------------- TUỲ CHỌN
def kiem_tra_live(kq: KetQua) -> None:
    """Bắn ĐÚNG MỘT request thật để xác nhận key còn quota."""
    print("\n[+] Kiểm tra quota thật (1 request)")
    from llm_utils import is_provider_error
    from providers import get_llm_provider

    provider = get_llm_provider()
    if provider.__class__.__name__ == "MockProvider":
        kq.luu_y("Bỏ qua", "đang ở chế độ mock, không có gì để kiểm tra")
        return

    tra_loi = provider.generate("Trả lời đúng một từ: OK")
    if is_provider_error(tra_loi):
        if "429" in tra_loi or "RESOURCE_EXHAUSTED" in tra_loi:
            kq.truot("Quota", "ĐÃ HẾT — đổi model bằng `--model`, hoặc chờ sang ngày mới")
        else:
            kq.truot("Gọi LLM", tra_loi[:200])
    else:
        model = getattr(provider, "model_name", "?")
        kq.dat("Quota", f"model `{model}` còn dùng được — trả lời: {tra_loi.strip()[:60]!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Kiểm thử trước khi chạy demo")
    parser.add_argument("--live", action="store_true",
                        help="Bắn thêm ĐÚNG 1 request thật để xem key còn quota không")
    args = parser.parse_args()

    print("=" * 68)
    print("🚦 KIỂM THỬ TRƯỚC DEMO — Trợ Lý Duyệt Chi Phí (Lab 3)")
    print("=" * 68)

    kq = KetQua()
    kiem_tra_pytest(kq)
    kiem_tra_test_cases(kq)
    kiem_tra_registry(kq)
    kiem_tra_bon_cap_do(kq)
    kiem_tra_env(kq)
    kiem_tra_artifact(kq)
    kiem_tra_flowchart(kq)
    kiem_tra_giao_dien(kq)
    if args.live:
        kiem_tra_live(kq)

    print("\n" + "=" * 68)
    if kq.canh_bao:
        print(f"⚠️  {len(kq.canh_bao)} cảnh báo (không chặn demo):")
        for c in kq.canh_bao:
            print(f"   - {c}")
    if kq.hong:
        print(f"❌ {len(kq.hong)} KIỂM TRA HỎNG — SỬA TRƯỚC KHI DEMO:")
        for h in kq.hong:
            print(f"   - {h}")
        print("=" * 68)
        return 1

    print("✅ TẤT CẢ KIỂM TRA ĐẠT — sẵn sàng demo.")
    if not args.live:
        print("   (Chạy lại với `--live` để xác nhận API key còn quota.)")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    sys.exit(main())
