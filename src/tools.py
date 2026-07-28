"""
🛠️ TOOL REGISTRY — TRỢ LÝ DUYỆT CHI PHÍ DOANH NGHIỆP (Role 2)

Bảy công cụ cho Agent duyệt chi phí. Mọi tham số là chuỗi vì parser dùng format
`Action: tên_tool[a, b]`. Mọi lỗi trả về chuỗi bắt đầu bằng "LỖI:" thay vì raise
— Agent phải đọc được lỗi như một Observation bình thường.
"""

import re

# ============================================================ CHÍNH SÁCH
# nguong_hoa_don = 0 nghĩa là LUÔN LUÔN bắt buộc hoá đơn VAT.
# han_muc là hạn mức cho MỘT ĐƠN VỊ (một người ăn, một thiết bị, một suất học),
# so với ĐƠN GIÁ chứ không phải tổng tiền của dòng.
_POLICY = {
    "an_uong":    {"ten": "Ăn uống nội bộ", "don_vi": "người", "han_muc": 500_000,
                   "nguong_hoa_don": 200_000, "can_pre_approval": False},
    "tiep_khach": {"ten": "Tiếp khách", "don_vi": "lần", "han_muc": 3_000_000,
                   "nguong_hoa_don": 500_000, "can_pre_approval": True},
    "di_lai":     {"ten": "Đi lại (taxi/Grab)", "don_vi": "lần", "han_muc": 1_000_000,
                   "nguong_hoa_don": 500_000, "can_pre_approval": False},
    "cong_tac":   {"ten": "Công tác", "don_vi": "chuyến", "han_muc": 15_000_000,
                   "nguong_hoa_don": 0, "can_pre_approval": True},
    "thiet_bi":   {"ten": "Thiết bị", "don_vi": "thiết bị", "han_muc": 30_000_000,
                   "nguong_hoa_don": 0, "can_pre_approval": True},
    "phan_mem":   {"ten": "Phần mềm/SaaS", "don_vi": "năm", "han_muc": 20_000_000,
                   "nguong_hoa_don": 0, "can_pre_approval": True},
    "dao_tao":    {"ten": "Đào tạo", "don_vi": "suất", "han_muc": 10_000_000,
                   "nguong_hoa_don": 0, "can_pre_approval": True},
}

# ============================================================ NGÂN SÁCH
_BUDGETS = {
    "CC-ENG":   {"ten": "Engineering", "ngan_sach": 500_000_000, "da_tieu": 380_000_000},
    "CC-SALES": {"ten": "Sales",       "ngan_sach": 300_000_000, "da_tieu":  90_000_000},
}

# ============================================================ NGƯỠNG LUẬT
# Thông tư 96/2015/TT-BTC: khoản chi từ 20 triệu trở lên phải thanh toán KHÔNG
# dùng tiền mặt mới được tính là chi phí được trừ khi quyết toán thuế TNDN.
NGUONG_TIEN_MAT = 20_000_000
SO_NGAY_NOP_TOI_DA = 30

# ============================================================ ĐƠN CHI PHÍ
_REPORTS = {
    "EXP-2026-0142": {
        "employee_id": "EMP-001", "employee": "Nguyễn Văn An",
        "cost_center": "CC-ENG", "ngay_nop": "2026-07-25",
        "items": [
            {"ngay": "2026-07-22", "category": "an_uong", "vendor": "Nhà hàng Ngon",
             "so_luong": 6, "don_gia": 400_000, "so_tien": 2_400_000,
             "co_hoa_don_vat": True, "thanh_toan": "chuyen_khoan", "pre_approved": False},
        ],
    },
    # 1 dòng số lượng 5 — KHÔNG tách 5 dòng, nếu tách sẽ kích nhầm quy tắc xé nhỏ
    # hoá đơn (R8) thay vì quy tắc ngân sách (R6) như ý đồ. Đơn giá 28tr nằm dưới
    # hạn mức 30tr để R1 không bắn trước, cho R6 có cơ hội chạy.
    "EXP-2026-0143": {
        "employee_id": "EMP-002", "employee": "Trần Thị Bình",
        "cost_center": "CC-ENG", "ngay_nop": "2026-07-26",
        "items": [
            {"ngay": "2026-07-24", "category": "thiet_bi",
             "vendor": "Công ty TNHH Tin học Phương Nam",
             "so_luong": 5, "don_gia": 28_000_000, "so_tien": 140_000_000,
             "co_hoa_don_vat": True, "thanh_toan": "chuyen_khoan", "pre_approved": True},
        ],
    },
    # 3 suất × 8tr = 24tr: đơn giá dưới hạn mức 10tr nên qua R1, tổng vượt ngưỡng
    # 20tr mà trả tiền mặt nên dính R3.
    "EXP-2026-0144": {
        "employee_id": "EMP-003", "employee": "Lê Minh Cường",
        "cost_center": "CC-ENG", "ngay_nop": "2026-07-27",
        "items": [
            {"ngay": "2026-07-15", "category": "dao_tao", "vendor": "Trung tâm Đào tạo FPT",
             "so_luong": 3, "don_gia": 8_000_000, "so_tien": 24_000_000,
             "co_hoa_don_vat": True, "thanh_toan": "tien_mat", "pre_approved": True},
        ],
    },
    # 3 hoá đơn cùng vendor cùng ngày, mỗi cái dưới hạn mức 3tr — chỉ lộ khi nhìn
    # tổng thể. pre_approved=True để cô lập R8, không cho R4 bắn trước.
    "EXP-2026-0145": {
        "employee_id": "EMP-004", "employee": "Phạm Thu Dung",
        "cost_center": "CC-ENG", "ngay_nop": "2026-07-20",
        "items": [
            {"ngay": "2026-07-18", "category": "tiep_khach", "vendor": "Nhà hàng Sen Vàng",
             "so_luong": 1, "don_gia": 2_900_000, "so_tien": 2_900_000,
             "co_hoa_don_vat": True, "thanh_toan": "chuyen_khoan", "pre_approved": True},
            {"ngay": "2026-07-18", "category": "tiep_khach", "vendor": "Nhà hàng Sen Vàng",
             "so_luong": 1, "don_gia": 2_900_000, "so_tien": 2_900_000,
             "co_hoa_don_vat": True, "thanh_toan": "chuyen_khoan", "pre_approved": True},
            {"ngay": "2026-07-18", "category": "tiep_khach", "vendor": "Nhà hàng Sen Vàng",
             "so_luong": 1, "don_gia": 2_900_000, "so_tien": 2_900_000,
             "co_hoa_don_vat": True, "thanh_toan": "chuyen_khoan", "pre_approved": True},
        ],
    },
    # Trùng với đơn EXP-2026-0138 đã duyệt trong lịch sử.
    "EXP-2026-0146": {
        "employee_id": "EMP-001", "employee": "Nguyễn Văn An",
        "cost_center": "CC-ENG", "ngay_nop": "2026-07-22",
        "items": [
            {"ngay": "2026-07-21", "category": "di_lai", "vendor": "Grab",
             "so_luong": 1, "don_gia": 850_000, "so_tien": 850_000,
             "co_hoa_don_vat": True, "thanh_toan": "chuyen_khoan", "pre_approved": False},
        ],
    },
    # Trùng với EXP-2026-0125 đã thanh toán trong lịch sử: cùng nhân viên, cùng
    # vendor, cùng số tiền. Đây là dữ liệu cho case 9 — kiểu gian lận nộp hai lần
    # cùng một hoá đơn, chỉ lộ khi đối chiếu lịch sử.
    "EXP-2026-0147": {
        "employee_id": "EMP-005", "employee": "Vũ Hoàng Nam",
        "cost_center": "CC-SALES", "ngay_nop": "2026-07-26",
        "items": [
            {"ngay": "2026-07-10", "category": "cong_tac",
             "vendor": "Vietnam Airlines",
             "so_luong": 1, "don_gia": 6_800_000, "so_tien": 6_800_000,
             "co_hoa_don_vat": True, "thanh_toan": "chuyen_khoan", "pre_approved": True},
        ],
    },
    # Tiếp khách 18,5tr: đơn giá VƯỢT hạn mức 3tr/lần của hạng mục tiep_khach nên
    # đúng ra là REJECTED theo R1. Nhưng pre_approved=True và có hoá đơn VAT, nên
    # trường hợp này cần người duyệt giải trình thêm -> NEEDS_INFO. Dữ liệu cho case 10.
    "EXP-2026-0148": {
        "employee_id": "EMP-005", "employee": "Vũ Hoàng Nam",
        "cost_center": "CC-SALES", "ngay_nop": "2026-07-27",
        "items": [
            {"ngay": "2026-07-25", "category": "tiep_khach", "vendor": "Khách sạn Metropole",
             "so_luong": 1, "don_gia": 18_500_000, "so_tien": 18_500_000,
             "co_hoa_don_vat": True, "thanh_toan": "chuyen_khoan", "pre_approved": True},
        ],
    },
}

# ============================================================ LỊCH SỬ
_CLAIM_HISTORY = [
    {"report_id": "EXP-2026-0138", "employee_id": "EMP-001", "vendor": "Grab",
     "so_tien": 850_000, "ngay": "2026-07-20", "trang_thai": "APPROVED"},
    {"report_id": "EXP-2026-0131", "employee_id": "EMP-002",
     "vendor": "Công ty TNHH Tin học Phương Nam",
     "so_tien": 12_000_000, "ngay": "2026-06-30", "trang_thai": "APPROVED"},
    # Cặp trùng của EXP-2026-0147: cùng EMP-005, cùng Vietnam Airlines, cùng
    # 6.800.000 ₫ — chuyến công tác này đã được thanh toán một lần rồi.
    {"report_id": "EXP-2026-0125", "employee_id": "EMP-005",
     "vendor": "Vietnam Airlines",
     "so_tien": 6_800_000, "ngay": "2026-07-12", "trang_thai": "APPROVED"},
]

# Nơi submit_decision ghi quyết định vào (in-memory).
_DECISIONS = {}

QUYET_DINH_HOP_LE = ("APPROVED", "REJECTED", "NEEDS_INFO", "ESCALATE")


def _parse_amount(raw: str) -> int:
    """Đọc số tiền từ chuỗi: '25.000.000 VNĐ' -> 25000000.

    Raise ValueError nếu không đọc được — hàm gọi có nhiệm vụ đổi thành 'LỖI:'.
    """
    if raw is None:
        raise ValueError("số tiền rỗng")
    cleaned = re.sub(r"(?i)(₫|vnđ|vnd|đồng|đ)\s*$", "", str(raw).strip())
    cleaned = re.sub(r"[.,\s]", "", cleaned)
    if not cleaned or not cleaned.isdigit():
        raise ValueError(f"không đọc được số tiền từ '{raw}'")
    return int(cleaned)


def _tien(so: int) -> str:
    """2400000 -> '2,400,000 ₫'"""
    return f"{so:,} ₫"


# ============================================================ 7 CÔNG CỤ

def get_expense_report(report_id: str) -> str:
    """
    Lấy chi tiết một đơn chi phí theo mã đơn.

    Args:
        report_id (str): Mã đơn, ví dụ 'EXP-2026-0142'

    Returns:
        str: Người nộp, cost center, ngày nộp và toàn bộ line item.
    """
    rid = report_id.strip().upper()
    report = _REPORTS.get(rid)
    if not report:
        return (f"LỖI: Không tìm thấy đơn chi phí '{report_id}'. "
                f"Các đơn hiện có: {', '.join(_REPORTS)}.")

    tong = sum(i["so_tien"] for i in report["items"])
    dong = [
        f"Đơn {rid} — {report['employee']} ({report['employee_id']})",
        f"Cost center: {report['cost_center']} | Ngày nộp: {report['ngay_nop']}",
        f"Tổng tiền: {_tien(tong)} | Số dòng: {len(report['items'])}",
        "Chi tiết:",
    ]
    for idx, item in enumerate(report["items"], 1):
        dong.append(
            f"  {idx}. [{item['category']}] {item['vendor']} | ngày {item['ngay']} | "
            f"SL {item['so_luong']} × đơn giá {_tien(item['don_gia'])} "
            f"= {_tien(item['so_tien'])} | "
            f"hoá đơn VAT: {'có' if item['co_hoa_don_vat'] else 'KHÔNG'} | "
            f"thanh toán: {item['thanh_toan']} | "
            f"pre-approval: {'có' if item['pre_approved'] else 'KHÔNG'}"
        )
    return "\n".join(dong)


def get_policy(category: str) -> str:
    """
    Tra chính sách chi phí của một hạng mục.

    Args:
        category (str): Mã hạng mục, ví dụ 'tiep_khach', 'thiet_bi'

    Returns:
        str: Hạn mức trên một đơn vị, ngưỡng bắt buộc hoá đơn VAT, pre-approval.
    """
    key = category.strip().lower()
    policy = _POLICY.get(key)
    if not policy:
        return (f"LỖI: Không có hạng mục '{category}'. "
                f"Các hạng mục hợp lệ: {', '.join(_POLICY)}.")

    nguong = ("Luôn bắt buộc" if policy["nguong_hoa_don"] == 0
              else f"khi ≥ {_tien(policy['nguong_hoa_don'])}")
    return (
        f"Chính sách hạng mục '{key}' ({policy['ten']}):\n"
        f"- Hạn mức: {_tien(policy['han_muc'])} / 1 {policy['don_vi']} "
        f"(so với ĐƠN GIÁ, không phải tổng tiền)\n"
        f"- Hoá đơn VAT: {nguong}\n"
        f"- Cần pre-approval: {'Có' if policy['can_pre_approval'] else 'Không'}\n"
        f"- Lưu ý chung: tổng đơn từ {_tien(NGUONG_TIEN_MAT)} trở lên BẮT BUỘC "
        f"thanh toán không dùng tiền mặt (TT96/2015).\n"
        f"- Hạn nộp: trong {SO_NGAY_NOP_TOI_DA} ngày kể từ ngày phát sinh."
    )


def check_budget(cost_center: str, amount: str) -> str:
    """
    Kiểm tra ngân sách còn lại của cost center có đủ chi khoản này không.

    Args:
        cost_center (str): Mã cost center, ví dụ 'CC-ENG'
        amount (str): Số tiền cần chi, ví dụ '140000000'

    Returns:
        str: Ngân sách kỳ, đã tiêu, còn lại và kết luận ĐỦ / KHÔNG ĐỦ.
    """
    key = cost_center.strip().upper()
    budget = _BUDGETS.get(key)
    if not budget:
        return f"LỖI: Không có cost center '{cost_center}'. Hợp lệ: {', '.join(_BUDGETS)}."
    try:
        can_chi = _parse_amount(amount)
    except ValueError as e:
        return f"LỖI: {e}"

    con_lai = budget["ngan_sach"] - budget["da_tieu"]
    return (
        f"Ngân sách {key} ({budget['ten']}):\n"
        f"- Ngân sách kỳ: {_tien(budget['ngan_sach'])}\n"
        f"- Đã tiêu: {_tien(budget['da_tieu'])}\n"
        f"- Còn lại: {_tien(con_lai)}\n"
        f"- Cần chi: {_tien(can_chi)}\n"
        f"=> Kết luận: {'ĐỦ' if con_lai >= can_chi else 'KHÔNG ĐỦ'}"
    )


def find_duplicate_claims(employee_id: str, vendor: str) -> str:
    """
    Dò đơn trùng lặp và dấu hiệu xé nhỏ hoá đơn.

    Args:
        employee_id (str): Mã nhân viên, ví dụ 'EMP-001'
        vendor (str): Tên nhà cung cấp, ví dụ 'Grab'

    Returns:
        str: Các đơn đã nộp trước đó và cảnh báo XÉ NHỎ HOÁ ĐƠN nếu có.
    """
    emp = employee_id.strip().upper()
    ven = vendor.strip().lower()

    trung = [h for h in _CLAIM_HISTORY
             if h["employee_id"] == emp and h["vendor"].lower() == ven]

    # Dò xé nhỏ: gom line item theo ngày trong các đơn đang chờ của nhân viên này.
    theo_ngay = {}
    for rid, r in _REPORTS.items():
        if r["employee_id"] != emp or rid in _DECISIONS:
            continue
        for item in r["items"]:
            if item["vendor"].lower() == ven:
                theo_ngay.setdefault(item["ngay"], []).append(item)

    dong = []
    if trung:
        dong.append(f"Phát hiện {len(trung)} đơn TRÙNG đã nộp trước đó của {emp} với '{vendor}':")
        for h in trung:
            dong.append(f"- {h['report_id']} | ngày {h['ngay']} | "
                        f"{_tien(h['so_tien'])} | {h['trang_thai']}")
    else:
        dong.append(f"Không tìm thấy đơn trùng nào của {emp} với '{vendor}' trong lịch sử.")

    for ngay, items in sorted(theo_ngay.items()):
        if len(items) >= 3:
            tong = sum(i["so_tien"] for i in items)
            dong.append(
                f"⚠️ CẢNH BÁO XÉ NHỎ HOÁ ĐƠN: {len(items)} hoá đơn cùng vendor "
                f"'{vendor}' cùng ngày {ngay}, mỗi hoá đơn dưới hạn mức nhưng tổng "
                f"cộng {_tien(tong)}."
            )
    return "\n".join(dong)


def get_approval_matrix(amount: str) -> str:
    """
    Tra ma trận phân quyền duyệt (DoA) xem mức tiền này ai được duyệt.

    Args:
        amount (str): Số tiền của đơn, ví dụ '24000000'

    Returns:
        str: Cấp có thẩm quyền duyệt mức tiền này.
    """
    try:
        so_tien = _parse_amount(amount)
    except ValueError as e:
        return f"LỖI: {e}"

    if so_tien < 5_000_000:
        cap = "Team Lead"
    elif so_tien <= 50_000_000:
        cap = "Engineering Manager"
    elif so_tien <= 200_000_000:
        cap = "Director"
    else:
        cap = "CFO"
    return (
        f"Ma trận phân quyền (DoA) cho {_tien(so_tien)}:\n"
        f"=> Cấp có thẩm quyền duyệt: {cap}\n"
        f"(< 5tr: Team Lead | 5-50tr: Engineering Manager | "
        f"50-200tr: Director | > 200tr: CFO)"
    )


def submit_decision(report_id: str, decision: str, reason: str) -> str:
    """
    Ghi quyết định duyệt cho một đơn chi phí. ĐÂY LÀ HÀNH ĐỘNG GHI DỮ LIỆU —
    chỉ gọi sau khi đã tra đủ chính sách, ngân sách và lịch sử trùng lặp.

    Args:
        report_id (str): Mã đơn, ví dụ 'EXP-2026-0142'
        decision (str): APPROVED / REJECTED / NEEDS_INFO / ESCALATE
        reason (str): Lý do cụ thể, dẫn số liệu từ Observation

    Returns:
        str: Xác nhận đã ghi, hoặc chuỗi lỗi.
    """
    rid = report_id.strip().upper()
    quyet_dinh = decision.strip().upper()

    if rid not in _REPORTS:
        return f"LỖI: Không tìm thấy đơn '{report_id}' để ghi quyết định."
    if quyet_dinh not in QUYET_DINH_HOP_LE:
        return (f"LỖI: Quyết định '{decision}' không hợp lệ. "
                f"Chỉ chấp nhận: {', '.join(QUYET_DINH_HOP_LE)}.")
    if not reason or not reason.strip():
        return "LỖI: Phải có lý do cụ thể cho quyết định, không được để trống."

    _DECISIONS[rid] = {"decision": quyet_dinh, "reason": reason.strip()}
    return (f"Đã ghi quyết định THÀNH CÔNG: {quyet_dinh} cho đơn {rid}. "
            f"Lý do: {reason.strip()}")


def list_pending_reports(cost_center: str) -> str:
    """
    Liệt kê các đơn chi phí đang chờ duyệt của một cost center.

    Args:
        cost_center (str): Mã cost center, ví dụ 'CC-ENG'

    Returns:
        str: Danh sách mã đơn kèm người nộp và tổng tiền.
    """
    key = cost_center.strip().upper()
    if key not in _BUDGETS:
        return f"LỖI: Không có cost center '{cost_center}'. Hợp lệ: {', '.join(_BUDGETS)}."

    cho_duyet = [(rid, r) for rid, r in _REPORTS.items()
                 if r["cost_center"] == key and rid not in _DECISIONS]
    if not cho_duyet:
        return f"Không có đơn nào đang chờ duyệt ở {key}."

    dong = [f"Đơn chờ duyệt tại {key} ({len(cho_duyet)} đơn):"]
    for rid, r in cho_duyet:
        tong = sum(i["so_tien"] for i in r["items"])
        dong.append(f"- {rid} | {r['employee']} | {_tien(tong)}")
    return "\n".join(dong)


# Danh sách tool được đăng ký để Agent sử dụng
AVAILABLE_TOOLS = {
    "get_expense_report": get_expense_report,
    "get_policy": get_policy,
    "check_budget": check_budget,
    "find_duplicate_claims": find_duplicate_claims,
    "get_approval_matrix": get_approval_matrix,
    "submit_decision": submit_decision,
    "list_pending_reports": list_pending_reports,
}
