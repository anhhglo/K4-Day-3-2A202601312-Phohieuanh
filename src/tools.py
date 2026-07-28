"""
🛠️ TOOL REGISTRY & SCHEMAS (Dành cho Role 2: Tool & Spec Engineer)
Nơi khai báo tất cả các "món đồ nghề" mà ReAct Agent có thể gọi để duyệt chi phí doanh nghiệp.
"""

# Giả lập database ngân sách phòng ban
BUDGET_DB = {
    "Marketing": 10000000.0,  # 10 triệu VNĐ
    "HR": 2000000.0,          # 2 triệu VNĐ
    "IT": 50000000.0          # 50 triệu VNĐ
}

# Giả lập database hạn mức chính sách chi tiêu của công ty
POLICY_DB = {
    "tiếp khách": 5000000.0,  # Tối đa 5 triệu VNĐ/lần
    "công tác": 10000000.0,   # Tối đa 10 triệu VNĐ/chuyến
    "thiết bị": 15000000.0    # Tối đa 15 triệu VNĐ/thiết bị
}

def check_department_budget(department: str) -> str:
    """
    Tra cứu số dư ngân sách còn lại của một phòng ban cụ thể.
    
    Args:
        department (str): Tên phòng ban (Ví dụ: 'Marketing', 'HR', 'IT')
        
    Returns:
        str: Thông tin ngân sách còn lại hoặc thông báo lỗi nếu không tìm thấy phòng ban.
    """
    dep_lower = department.strip().lower()
    matched_dep = None
    for dep in BUDGET_DB:
        if dep.lower() == dep_lower:
            matched_dep = dep
            break
            
    if matched_dep:
        return f"Ngân sách còn lại của phòng {matched_dep} là {BUDGET_DB[matched_dep]:,} VNĐ."
    else:
        return f"LỖI: Không tìm thấy dữ liệu ngân sách cho phòng ban '{department}'. Các phòng ban hiện có: {', '.join(BUDGET_DB.keys())}."


def verify_expense_policy(category: str, amount: float) -> str:
    """
    Xác minh chi phí đề xuất có tuân thủ chính sách hạn mức của công ty hay không.
    
    Args:
        category (str): Danh mục chi phí (Ví dụ: 'tiếp khách', 'công tác', 'thiết bị')
        amount (float): Số tiền đề xuất hoàn phí (VNĐ)
        
    Returns:
        str: Kết quả kiểm tra chính sách (HỢP LỆ hoặc VI PHẠM định mức kèm chi tiết).
    """
    cat_lower = category.strip().lower()
    matched_cat = None
    for cat in POLICY_DB:
        if cat.lower() == cat_lower:
            matched_cat = cat
            break
            
    if not matched_cat:
        return f"LỖI: Danh mục chi phí '{category}' không nằm trong danh sách kiểm tra chính sách. Các danh mục khả dụng: {', '.join(POLICY_DB.keys())}."
        
    try:
        val_amount = float(amount)
    except ValueError:
        return f"LỖI: Số tiền '{amount}' không hợp lệ."
        
    limit = POLICY_DB[matched_cat]
    if val_amount <= limit:
        return f"HỢP LỆ: Chi phí '{matched_cat}' trị giá {val_amount:,} VNĐ nằm trong hạn mức cho phép (Tối đa: {limit:,} VNĐ)."
    else:
        return f"VI PHẠM: Chi phí '{matched_cat}' trị giá {val_amount:,} VNĐ vượt quá hạn mức tối đa cho phép là {limit:,} VNĐ."


def submit_expense_approval(claim_id: str, status: str, reason: str) -> str:
    """
    Thực hiện lệnh duyệt hoặc từ chối yêu cầu thanh toán chi phí và ghi nhận lý do.
    
    Args:
        claim_id (str): Mã yêu cầu thanh toán (Ví dụ: 'CLAIM-123')
        status (str): Trạng thái quyết định ('Duyệt' hoặc 'Từ chối')
        reason (str): Lý do phê duyệt hoặc từ chối cụ thể
        
    Returns:
        str: Thông báo xác nhận kết quả xử lý thành công.
    """
    clean_status = status.strip().lower()
    if "duyệt" in clean_status or "approve" in clean_status:
        return f"THÀNH CÔNG: Yêu cầu {claim_id} đã được DUYỆT. Lý do: {reason}."
    elif "từ chối" in clean_status or "reject" in clean_status:
        return f"THÀNH CÔNG: Yêu cầu {claim_id} đã bị TỪ CHỐI. Lý do: {reason}."
    else:
        return f"LỖI: Trạng thái '{status}' không hợp lệ. Phải là 'Duyệt' hoặc 'Từ chối'."


# Dữ liệu mock bổ sung cho 4 tool mới
REPORT_DB = {
    "EXP-001": {
        "employee": "Nguyễn Văn An",
        "department": "IT",
        "amount": 2500000,
        "category": "tiếp khách",
        "status": "PENDING"
    },
    "EXP-002": {
        "employee": "Trần Thị Bình",
        "department": "HR",
        "amount": 12000000,
        "category": "công tác",
        "status": "PENDING"
    }
}

CLAIM_HISTORY = [
    {"employee": "Nguyễn Văn An", "vendor": "Grab", "amount": 850000, "date": "2026-07-20"},
    {"employee": "Trần Thị Bình", "vendor": "Công ty TNHH Tin học Phương Nam", "amount": 12000000, "date": "2026-06-30"},
]


def get_expense_report(report_id: str) -> str:
    """Trả về thông tin chi tiết của một expense report theo mã đơn."""
    report = REPORT_DB.get(report_id)
    if not report:
        return f"LỖI: Không tìm thấy expense report '{report_id}'."
    return (
        f"Expense Report {report_id}: nhân viên={report['employee']}, phòng={report['department']}, "
        f"số tiền={report['amount']:,} VNĐ, danh mục={report['category']}, trạng thái={report['status']}"
    )


def get_policy(category: str) -> str:
    """Trả về chính sách hạn mức cho một hạng mục chi phí."""
    cat_lower = category.strip().lower()
    for cat, limit in POLICY_DB.items():
        if cat.lower() == cat_lower:
            return f"Chính sách '{cat}': hạn mức tối đa {limit:,} VNĐ/lần."
    return f"LỖI: Không tìm thấy chính sách cho danh mục '{category}'."


def check_budget(department: str, amount: float) -> str:
    """Kiểm tra ngân sách còn lại của phòng ban cho một khoản chi."""
    dep_lower = department.strip().lower()
    for dep, budget in BUDGET_DB.items():
        if dep.lower() == dep_lower:
            try:
                val_amount = float(amount)
            except (TypeError, ValueError):
                return f"LỖI: Số tiền '{amount}' không hợp lệ."
            remaining = budget - val_amount
            if remaining >= 0:
                return f"Ngân sách còn lại của phòng {dep} là {remaining:,.0f} VNĐ sau khi chi {val_amount:,.0f} VNĐ."
            return f"LỖI: Phòng {dep} không đủ ngân sách. Còn lại {remaining:,.0f} VNĐ."
    return f"LỖI: Không tìm thấy phòng ban '{department}'."


def find_duplicate_claims(employee: str, vendor: str) -> str:
    """Tìm các claim trùng lặp theo nhân viên và vendor."""
    matches = [
        item for item in CLAIM_HISTORY
        if item["employee"].lower() == employee.strip().lower() and item["vendor"].lower() == vendor.strip().lower()
    ]
    if not matches:
        return f"Không tìm thấy claim trùng cho nhân viên '{employee}' và vendor '{vendor}'."
    lines = [f"Tìm thấy {len(matches)} claim trùng:"]
    for item in matches:
        lines.append(f"- {item['employee']} | {item['vendor']} | {item['amount']:,} VNĐ | ngày {item['date']}")
    return "\n".join(lines)


# Danh sách các tool được đăng ký để Agent sử dụng
AVAILABLE_TOOLS = {
    "check_department_budget": check_department_budget,
    "verify_expense_policy": verify_expense_policy,
    "submit_expense_approval": submit_expense_approval,
    "get_expense_report": get_expense_report,
    "get_policy": get_policy,
    "check_budget": check_budget,
    "find_duplicate_claims": find_duplicate_claims,
}