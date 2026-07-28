# 🧪 KẾT QUẢ CHẠY TEST CASES

*Sinh tự động bởi `src/run_tests.py` lúc 2026-07-28 15:10*  
*Chế độ: `both` — Kết quả: **5/5 PASS***

## Bảng tổng hợp

| # | Nhóm | Câu hỏi | Tool đã gọi | Bước | Guardrail | Kết quả |
| :-: | :--- | :--- | :--- | :-: | :--- | :-: |
| 1 | 🟢 Đơn giản (Chỉ cần LLM) | Thủ đô của Việt Nam là gì? | — | 1 | — | ✅ PASS |
| 2 | 🟢 Đơn giản (Chỉ cần LLM) | Nêu 3 lời khuyên để học tốt lập trình. | — | 1 | — | ✅ PASS |
| 3 | 🟡 Multi-step (Cần Tool) | Thời tiết ở Hà Nội hôm nay thế nào và tôi nên mặc gì đi chơi? | get_weather | 2 | — | ✅ PASS |
| 4 | 🟡 Multi-step (Cần gọi 2 Tools) | Kiểm tra vé máy bay từ TP.HCM đi Hà Nội ngày mai và dự báo thời tiết ở Hà Nội. | search_flights, get_weather | 3 | — | ✅ PASS |
| 5 | 🔴 Edge Case (Bẫy Guardrail) | Tra cứu thời tiết ở thành phố Atlantis ngày 32/13/2026. | get_weather | 2 | tool_error | ✅ PASS |

## Chi tiết từng case

### Case 1 — 🟢 Đơn giản (Chỉ cần LLM)

**Câu hỏi:** Thủ đô của Việt Nam là gì?  
**Kỳ vọng (Role 1):** Chatbot trả lời trực tiếp từ kiến thức có sẵn.

**🤖 Chatbot Baseline (Cấp 2):**

```text
Thủ đô của Việt Nam là **Hà Nội** bạn nhé! 

Hà Nội không chỉ là trung tâm chính trị mà còn là nơi lưu giữ rất nhiều giá trị văn hóa, lịch sử lâu đời và có rất nhiều món ăn ngon nổi tiếng. Bạn đã bao giờ có dịp ghé thăm thủ đô chưa?
```

**🧠 ReAct Agent (Cấp 3):**

* Tool đã gọi: `không có`
* Số bước dùng: 1/3
* Guardrail: `không có`

```text
Thủ đô của Việt Nam là Hà Nội.
```

**Chấm:** ✅ PASS — Trả lời trực tiếp, không gọi tool thừa

---

### Case 2 — 🟢 Đơn giản (Chỉ cần LLM)

**Câu hỏi:** Nêu 3 lời khuyên để học tốt lập trình.  
**Kỳ vọng (Role 1):** Chatbot trả lời trực tiếp từ kiến thức có sẵn.

**🤖 Chatbot Baseline (Cấp 2):**

```text
Chào bạn! Lập trình là một hành trình rất thú vị nhưng đôi khi cũng đầy thử thách. Để giúp bạn học tốt hơn, mình xin chia sẻ 3 lời khuyên cốt lõi sau đây nhé:

1. **"Code" mỗi ngày thay vì học vẹt:** 
   Lập trình cũng giống như việc học một nhạc cụ hay chơi thể thao vậy, kỹ năng chỉ được cải thiện khi bạn thực hành thường xuyên. Thay vì chỉ đọc sách hay xem video hướng dẫn (tutorial), hãy tự mình gõ lại từng dòng code, sửa lỗi (debug) và thử nghiệm các ý tưởng nhỏ mỗi ngày. 

2. **Học cách tìm kiếm và đọc tài liệu:** 
   Không có lập trình viên nào nhớ hết mọi cú pháp trong đầu cả. Kỹ năng quan trọng nhất là bạn phải biết cách "Google" lỗi mình gặp phải, đọc tài liệu chính thống (documentation) và sử dụng các diễn đàn như Stack Overflow. Khi bí, đừng nản lòng vì việc đối mặt và giải quyết lỗi chính là cách bạn tiến bộ nhanh nhất.

3. **Bắt đầu từ những dự án nhỏ:** 
   Đừng vội tham gia
```

**🧠 ReAct Agent (Cấp 3):**

* Tool đã gọi: `không có`
* Số bước dùng: 1/3
* Guardrail: `không có`

```text
Dưới đây là 3 lời khuyên giúp bạn học tốt lập trình:
1. **Thực hành code thường xuyên:** Lập trình là một kỹ năng thực hành. Bạn không thể chỉ học lý thuyết mà phải tự tay gõ code, giải quyết các bài tập và xây dựng các dự án nhỏ.
2. **Hiểu bản chất thay vì học vẹt:** Hãy tập trung vào việc hiểu tư duy giải quyết vấn đề, cấu trúc dữ liệu và giải thuật thay vì chỉ nhớ mặt cú pháp của ngôn ngữ.
3. **Kiên nhẫn và không ngại lỗi (debugging):** Lỗi (bugs) là một phần tất yếu của lập trình. Hãy coi việc đọc thông báo lỗi (error logs) và tìm cách sửa chúng là cơ hội tốt nhất để học hỏi và tiến bộ.
```

**Chấm:** ✅ PASS — Trả lời trực tiếp, không gọi tool thừa

---

### Case 3 — 🟡 Multi-step (Cần Tool)

**Câu hỏi:** Thời tiết ở Hà Nội hôm nay thế nào và tôi nên mặc gì đi chơi?  
**Kỳ vọng (Role 1):** Agent gọi tool get_weather('Hà Nội') rồi suy luận trang phục.

**🤖 Chatbot Baseline (Cấp 2):**

```text
Chào bạn! Vì tôi là một trợ lý ảo và không thể cập nhật dữ liệu thời tiết theo thời gian thực tại thời điểm bạn hỏi, nên tôi rất tiếc không thể nói chính xác nhiệt độ hay tình trạng mây mưa ở Hà Nội ngay lúc này được. 

Để biết chính xác nhất, bạn có thể kiểm tra nhanh trên ứng dụng thời tiết (như Weather, Google Weather) hoặc xem các bản tin thời tiết trên điện thoại nhé.

Tuy nhiên, dựa vào đặc điểm thời tiết chung của Hà Nội theo từng mùa, tôi có thể gợi ý cho bạn một vài phong cách cơ bản:

*   **Vào mùa hè/trời nắng nóng:** Thời tiết thường khá oi bức. Bạn nên chọn trang phục thoáng mát, thấm mồ hôi tốt như áo thun, quần đùi, váy ngắn hoặc đầm maxi. Đừng quên mang theo ô/dù, kem chống nắng và kính râm khi ra đường nhé.
*   **Vào mùa đông/trời lạnh:** Hà Nội có lúc lạnh khô hoặc lạnh ẩm. Bạn hãy mặc theo phong cách nhiều lớp (layer) với áo giữ nhiệt, áo len, khoác thêm áo phao hoặc á
```

**🧠 ReAct Agent (Cấp 3):**

* Tool đã gọi: `get_weather`
* Số bước dùng: 2/3
* Guardrail: `không có`

```text
Thời tiết ở Hà Nội hôm nay có nhiệt độ 28°C, trời nắng nhẹ và độ ẩm 65%. Với thời tiết này, bạn nên mặc những trang phục thoải mái, thoáng mát như áo thun, quần short hoặc váy nhẹ nhàng. Đừng quên mang theo kem chống nắng, kính râm hoặc một chiếc ô nhỏ nếu bạn định đi dạo ngoài trời nhé!
```

**Chấm:** ✅ PASS — Đã gọi 1 tool (get_weather) rồi mới kết luận

---

### Case 4 — 🟡 Multi-step (Cần gọi 2 Tools)

**Câu hỏi:** Kiểm tra vé máy bay từ TP.HCM đi Hà Nội ngày mai và dự báo thời tiết ở Hà Nội.  
**Kỳ vọng (Role 1):** Agent gọi tool search_flights và get_weather để trả lời đầy đủ.

**🤖 Chatbot Baseline (Cấp 2):**

```text
Chào bạn! Rất tiếc là mình không thể kiểm tra giá vé máy bay theo thời gian thực (real-time) hoặc tra cứu chính xác lịch trình và thời tiết của ngày mai được, vì mình không có kết nối internet trực tiếp để cập nhật dữ liệu mới nhất. 

Để kiểm tra vé máy bay TP.HCM đi Hà Nội cho ngày mai, bạn có thể tham khảo trực tiếp trên các ứng dụng đặt vé như Traveloka, Momo, Skyscanner, hoặc trang web chính thức của các hãng hàng không như Vietnam Airlines, Vietjet Air, Bamboo Airways nhé.

Còn về thời tiết Hà Nội ngày mai, bạn hãy nhanh chóng kiểm tra trên ứng dụng thời tiết mặc định của điện thoại (như Apple Weather, Google Weather) hoặc xem các bản tin dự báo thời tiết mới nhất để có thông tin chính xác nhất cho chuyến đi của mình.

Chúc bạn có một chuyến đi TP.HCM - Hà Nội thật thuận lợi và suôn sẻ! Nếu bạn cần tư vấn gì về các địa điểm ăn uống, vui chơi ở Hà Nội, cứ nói cho mình biết nhé!
```

**🧠 ReAct Agent (Cấp 3):**

* Tool đã gọi: `search_flights, get_weather`
* Số bước dùng: 3/3
* Guardrail: `không có`

```text
Dưới đây là thông tin vé máy bay và thời tiết theo yêu cầu của bạn:

1. **Thông tin chuyến bay từ TP.HCM đi Hà Nội ngày mai:**
   - Chuyến bay VN123 (Khởi hành lúc 08:00) - Giá: 1,500,000 VNĐ (Còn vé)
   - Chuyến bay VJ456 (Khởi hành lúc 14:30) - Giá: 1,200,000 VNĐ (Còn vé)

2. **Dự báo thời tiết tại Hà Nội:**
   - Nhiệt độ: 28°C
   - Tình trạng: Nắng nhẹ
   - Độ ẩm: 65%
```

**Chấm:** ✅ PASS — Đã gọi 2 tool (search_flights, get_weather) rồi mới kết luận

---

### Case 5 — 🔴 Edge Case (Bẫy Guardrail)

**Câu hỏi:** Tra cứu thời tiết ở thành phố Atlantis ngày 32/13/2026.  
**Kỳ vọng (Role 1):** Tool báo lỗi tham số/thất bại, Guardrail ngắt sau 3 bước và trả về thông báo lịch sự.

**🤖 Chatbot Baseline (Cấp 2):**

```text
Ôi, tiếc quá bạn ơi! Thành phố Atlantis vốn chỉ có trong thần thoại thôi, làm gì có thật trên bản đồ để mà tra cứu thời tiết chứ! 😊 

Hơn nữa, ngày 32/13/2026 cũng là một mốc thời gian không có thật trong lịch của chúng ta nữa (vì một năm chỉ có 12 tháng và tháng 12 cũng chỉ có tối đa 31 ngày thôi). 

Nếu bạn muốn tra cứu thời tiết của một địa điểm có thật nào đó trong tương lai gần, bạn có thể cho mình biết tên thành phố nhé. Rất vui được hỗ trợ bạn!
```

**🧠 ReAct Agent (Cấp 3):**

* Tool đã gọi: `get_weather`
* Số bước dùng: 2/3
* Guardrail: `tool_error`

```text
Xin lỗi, tôi không thể tra cứu thời tiết cho thành phố Atlantis vì không tìm thấy dữ liệu cho địa điểm này, ngoài ra định dạng ngày tháng bạn cung cấp (32/13/2026) không hợp lệ.
```

**Chấm:** ✅ PASS — Guardrail kích hoạt (tool_error), agent kết luận có kiểm soát

---
