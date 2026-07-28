# 📊 BÁO CÁO GIÁM SÁT & ĐÁNH GIÁ (OBSERVABILITY TRACE LOGS)

*Dành cho Role 5: Observability & Reviewer*

---

# 🎯 1. BẢNG CHẤM ĐIỂM AGENTIC FIT (SCORING MATRIX)

| Tiêu chí                    | Điểm (1-5) | Lý do đánh giá                                                                                                                 |
| --------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------ |
| 🧠 **Multi-step Reasoning** | **5/5**    | Cần suy luận nhiều bước: đọc hóa đơn → phân loại chi phí → đối chiếu chính sách → tính mức hoàn ứng → đưa ra quyết định duyệt. |
| 🛠️ **Tool Interaction**    | **5/5**    | Cần gọi nhiều công cụ như OCR hóa đơn, tra cứu chính sách công ty, kiểm tra ngân sách và tính toán hoàn ứng.                   |
| 🔀 **Dynamic Decision**     | **5/5**    | Kết quả kiểm tra chứng từ quyết định việc tiếp tục đối chiếu chính sách hay yêu cầu bổ sung hồ sơ.                             |
| ⏳ **Long Horizon**          | **4/5**    | Quy trình gồm nhiều bước nghiệp vụ liên tiếp và có thể cần tương tác bổ sung với nhân viên.                                    |
| **TỔNG ĐIỂM FIT**           | **19/20**  | **KẾT LUẬN: BÀI TOÁN RẤT PHÙ HỢP TRIỂN KHAI REACT AGENT!**                                                                     |

---

# 🔍 2. SO SÁNH PHẢN HỒI (TEST CASE #3)

## Câu hỏi

**“Tôi có hóa đơn taxi 350.000đ và hóa đơn ăn tối tiếp khách 1.200.000đ, công ty có duyệt được không?”**

### 🤖 Chatbot Baseline

**Phản hồi:**

> “Điều này phụ thuộc vào chính sách công ty của bạn. Bạn nên hỏi phòng kế toán.”

**Nhận xét:** Trả lời chung chung, không hỗ trợ ra quyết định.

---

### 🧠 ReAct Agent

**Thought 1:** Cần đọc và phân loại các khoản chi phí.

**Action 1:** `extract_expense_items([taxi_receipt, dinner_receipt])`

**Observation 1:** `Taxi: 350.000đ | Tiếp khách: 1.200.000đ`

**Thought 2:** Cần tra cứu chính sách công tác và tiếp khách.

**Action 2:** `get_company_policy([transport, entertainment])`

**Observation 2:** `Taxi ≤ 500.000đ/chuyến; Tiếp khách ≤ 1.000.000đ/buổi`

**Thought 3:** So sánh từng khoản với chính sách.

### Final Answer

> “Khoản taxi 350.000đ nằm trong hạn mức nên có thể duyệt. Khoản tiếp khách 1.200.000đ vượt hạn mức 1.000.000đ nên cần phê duyệt bổ sung của quản lý hoặc chỉ được hoàn tối đa 1.000.000đ tùy quy định công ty.”

**Nhận xét:** Agent đưa ra quyết định cụ thể dựa trên dữ liệu nghiệp vụ và chính sách doanh nghiệp.

---

# 🎁 3. BONUS CẤP 4 — AUTONOMOUS AGENT (Planning + Self-Eval + Memory)

**File:** `src/ai_levels/level4_autonomous_agent.py`

**Chạy bằng:**

```bash
python src/ai_levels/level4_autonomous_agent.py
```

---

## 3.1. Mục tiêu nghiệp vụ

**Yêu cầu người dùng:**

> “Kiểm tra bộ hồ sơ công tác Hà Nội gồm vé máy bay 2.400.000đ, khách sạn 1.800.000đ/đêm × 2 đêm, taxi 350.000đ và ăn tối tiếp khách 1.200.000đ; cho biết khoản nào được duyệt và số tiền hoàn ứng tối đa.”

---

## 3.2. Trace THÀNH CÔNG — agent tự dừng sớm

```text
📋 [Planning] Kế hoạch 4 bước:
    1. Trích xuất các khoản chi từ bộ hồ sơ
    2. Tra cứu chính sách công tác hiện hành
    3. Tính mức được duyệt cho từng khoản
    4. Tổng hợp số tiền hoàn ứng tối đa và kết luận

--- 🔄 Bước 1/6: Trích xuất khoản chi ---
🛠️ [Execution] extract_expense_items(expense_pack)
👁️ [Observation]
    - Vé máy bay: 2.400.000đ
    - Khách sạn: 1.800.000đ × 2 đêm
    - Taxi: 350.000đ
    - Tiếp khách: 1.200.000đ
⚖️ [Self-Eval] ✅ score=1.00 | goal_complete=False
💾 [Memory] Đã ghi bước 1

--- 🔄 Bước 2/6: Tra cứu chính sách ---
🛠️ [Execution] get_company_policy(business_trip)
👁️ [Observation]
    - Vé máy bay nội địa: tối đa 3.000.000đ/chuyến
    - Khách sạn Hà Nội: tối đa 1.500.000đ/đêm
    - Taxi: tối đa 500.000đ/chuyến
    - Tiếp khách: tối đa 1.000.000đ/buổi
⚖️ [Self-Eval] ✅ score=1.00 | goal_complete=False
💾 [Memory] Đã ghi bước 2

--- 🔄 Bước 3/6: Tính mức duyệt ---
🧠 [Execution] Tổng hợp từ bộ nhớ
👁️ [Observation]
    - Vé máy bay: duyệt 2.400.000đ
    - Khách sạn: duyệt 3.000.000đ (1.500.000đ × 2)
    - Taxi: duyệt 350.000đ
    - Tiếp khách: duyệt tối đa 1.000.000đ
⚖️ [Self-Eval] ✅ score=1.00 | goal_complete=True
🎯 [Goal Evaluation] Agent xác định đã đủ thông tin và dừng sớm.
```

---

## ✅ Kết luận nghiệp vụ

| Khoản chi  | Chi thực tế | Được duyệt |
| ---------- | ----------- | ---------- |
| Vé máy bay | 2.400.000đ  | 2.400.000đ |
| Khách sạn  | 3.600.000đ  | 3.000.000đ |
| Taxi       | 350.000đ    | 350.000đ   |
| Tiếp khách | 1.200.000đ  | 1.000.000đ |

### Tổng hoàn ứng tối đa: **6.750.000đ**

### Khoản vượt chính sách

* Khách sạn vượt **600.000đ**
* Tiếp khách vượt **200.000đ**

---

# ❌ 3.3. Trace THẤT BẠI — guardrails bắt lỗi

**Tình huống:** Nhân viên gửi hóa đơn khách sạn nhưng thiếu ngày lưu trú.

```text
--- 🔄 Bước 1/6: Trích xuất khoản chi ---
🛠️ [Execution] extract_expense_items(hotel_receipt)
👁️ [Observation] Khách sạn 1.800.000đ nhưng không có số đêm lưu trú.
⚖️ [Self-Eval] ❌ score=0.20 | Thiếu thông tin số đêm nên chưa thể tính mức hoàn ứng.
🔁 [Re-plan 1/2] Yêu cầu bổ sung thông tin số đêm.

--- 🔄 Bước 2/6: Chờ bổ sung chứng từ ---
🛠️ [Execution] request_missing_info(number_of_nights)
👁️ [Observation] Người dùng chưa cung cấp thêm dữ liệu.
⚖️ [Self-Eval] ❌ score=0.10 | Chưa đủ dữ liệu để tiếp tục.

--- 🔄 Bước 3/6: Thử tính toán lại ---
🛑 [Guardrail] Chặn suy đoán số đêm lưu trú từ hóa đơn thiếu dữ liệu.
⚖️ [Self-Eval] ❌ score=0.00
🛑 [Guardrail] 3 bước hỏng liên tiếp — DỪNG KHẨN CẤP.
```

### Ý nghĩa của trace lỗi

* **Self-Evaluation** phát hiện thiếu dữ liệu đầu vào.
* **Guardrail chống hallucination** ngăn agent tự suy đoán số đêm lưu trú.
* **Emergency stop** dừng quy trình sau nhiều lần thất bại liên tiếp để tránh quyết định sai.

Đây là hành vi mong muốn trong hệ thống duyệt chi phí thực tế vì quyết định tài chính không được phép dựa trên dữ liệu thiếu.

---

# 🧠 3.4. Vai trò của Memory trong bài toán duyệt chi phí

Agent lưu lại các bước đã xử lý:

* Các khoản chi đã đọc.
* Chính sách đã tra cứu.
* Các chứng từ còn thiếu.
* Kết quả tính toán trung gian.

Ví dụ:

```json
{
  "expense_id": "EXP-2026-0715",
  "approved_items": [
    {"type": "flight", "amount": 2400000},
    {"type": "hotel", "amount": 3000000},
    {"type": "taxi", "amount": 350000}
  ],
  "pending_items": [
    {"type": "entertainment", "reason": "Vượt hạn mức"}
  ]
}
```

Memory giúp agent tiếp tục xử lý ở phiên sau mà không cần đọc lại toàn bộ hồ sơ.

---

# ⚠️ 3.5. Giới hạn hiện tại của bản lab

* Chưa kết nối OCR thật; dữ liệu hóa đơn đang mô phỏng.
* Chưa kiểm tra tính hợp lệ của hóa đơn VAT (mã số thuế, ngày phát hành, chữ ký số).
* Chưa kết nối hệ thống ERP/kế toán để kiểm tra ngân sách phòng ban.
* Memory mới lưu cục bộ trong file JSON, chưa hỗ trợ đa người dùng.
* Chưa có workflow phê duyệt nhiều cấp (nhân viên → quản lý → kế toán → tài chính).

---

# 🏁 4. KẾT LUẬN CHUNG

Bài toán **Trợ Lý Duyệt Chi Phí Doanh Nghiệp** đạt **19/20 điểm Agentic Fit**, rất phù hợp với kiến trúc **ReAct Agent** vì cần:

* suy luận nhiều bước,
* sử dụng công cụ nghiệp vụ,
* ra quyết định động,
* kiểm soát lỗi và chống hallucination.

Trace quan sát cho thấy agent không chỉ trả lời câu hỏi mà còn thực hiện đúng quy trình nghiệp vụ tài chính:

**kiểm tra chứng từ → đối chiếu chính sách → tính hoàn ứng → tự đánh giá → quyết định duyệt hoặc yêu cầu bổ sung hồ sơ.**

Điều này chứng minh mô hình Agentic AI mang lại giá trị thực tế cao hơn chatbot truyền thống trong bài toán **duyệt chi phí doanh nghiệp**.
