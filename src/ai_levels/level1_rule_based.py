"""
🤖 CẤP ĐỘ 1: RULE-BASED BOT (Chatbot dựa trên luật if/else cố định)

Khớp từ khoá với câu trả lời sẵn có. Không dùng LLM, không tra cứu được gì.
Minh hoạ lịch sử: nhanh và rẻ, nhưng chỉ trả lời đúng những câu đã lường trước.
"""


def rule_based_bot(user_input: str) -> str:
    text = user_input.lower()
    if "chào" in text or "hello" in text:
        return "Xin chào! Tôi là Rule-Based Bot (Cấp độ 1). Tôi tra được hạn mức và quy trình."
    elif "hạn mức" in text and "tiếp khách" in text:
        return "Hạn mức tiếp khách: 3.000.000 ₫/lần, cần pre-approval."
    elif "hạn mức" in text and "ăn uống" in text:
        return "Hạn mức ăn uống: 500.000 ₫/người."
    elif "quy trình" in text:
        return "Quy trình: Nộp đơn → Kiểm tra chính sách → Kiểm tra ngân sách → Duyệt → Thanh toán."
    elif "liên hệ" in text or "hotline" in text:
        return "Phòng Kế toán: 1900-1234, Email: finance@vinuni.edu.vn"
    else:
        return "Xin lỗi, câu hỏi của bạn nằm ngoài tập luật (keywords) được cài đặt sẵn!"


if __name__ == "__main__":
    print("=== DEMO CẤP ĐỘ 1: RULE-BASED BOT ===")
    test_queries = [
        "Chào bạn",
        "Hạn mức tiếp khách là bao nhiêu?",
        "Đơn EXP-2026-0142 có duyệt được không?",
    ]
    for q in test_queries:
        print(f"User: {q}")
        print(f"Bot : {rule_based_bot(q)}\n")
    print("💡 Nhận xét: câu thứ ba bot chịu chết — nó không có khái niệm "
          "'đơn chi phí', cũng không tra cứu được dữ liệu nào.")
