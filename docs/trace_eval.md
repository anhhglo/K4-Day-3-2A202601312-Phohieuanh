# 📊 BÁO CÁO GIÁM SÁT & ĐÁNH GIÁ (OBSERVABILITY TRACE LOGS)
*Dành cho Role 5: Observability & Reviewer*

---

## 🎯 1. BẢNG CHẤM ĐIỂM AGENTIC FIT (SCORING MATRIX)

| Tiêu chí | Điểm (1-5) | Lý do đánh giá |
| :--- | :---: | :--- |
| 🧠 **Multi-step Reasoning** | `4/5` | Cần suy luận từ tra cứu thời tiết đến chọn trang phục. |
| 🛠️ **Tool Interaction** | `5/5` | Cần tra cứu dữ liệu thời gian thực qua API thời tiết/chuyến bay. |
| 🔀 **Dynamic Decision** | `4/5` | Kết quả bước trước quyết định hành động bước sau. |
| ⏳ **Long Horizon** | `3/5` | Quy trình gồm 2-3 bước xử lý ngắn. |
| **TỔNG ĐIỂM FIT** | **16/20** | **KẾT LUẬN: BÀI TOÁN RẤT NÊN DÙNG REACT AGENT!** |

---

## 🔍 2. SO SÁNH PHẢN HỒI (TEST CASE #3)

**Câu hỏi**: *"Thời tiết ở Hà Nội hôm nay thế nào và tôi nên mặc gì đi chơi?"*

### 🤖 Chatbot Baseline:
* **Phản hồi**: *"Tôi không có truy cập Internet thời gian thực nên không biết thời tiết hôm nay ở Hà Nội."*
* **Nhận xét**: An toàn nhưng không giải quyết được nhu cầu thực tế của người dùng.

### 🧠 ReAct Agent:
* **Thought 1**: Cần tra cứu thời tiết Hà Nội.
* **Action 1**: `get_weather['Hà Nội']`
* **Observation 1**: `Thời tiết Hà Nội: 28°C, Nắng nhẹ, Độ ẩm 65%.`
* **Thought 2**: Đã có thông tin 28°C nắng nhẹ, đưa ra lời khuyên trang phục.
* **Final Answer**: *"Thời tiết Hà Nội hôm nay 28°C, nắng nhẹ. Bạn nên mặc quần áo thoáng mát!"*
* **Nhận xét**: Hoàn thành xuất sắc nhiệm vụ nhờ sự kết hợp giữa suy luận và công cụ.

---

## 🎁 3. BONUS CẤP 4 — AUTONOMOUS AGENT (Planning + Self-Eval + Memory)

File: `src/ai_levels/level4_autonomous_agent.py` — chạy bằng `python src/ai_levels/level4_autonomous_agent.py`.

### 3.1. Đối chiếu với hệ production AIchat

Ba cơ chế Cấp 4 ở đây không tự nghĩ ra, mà thu nhỏ từ kiến trúc của dự án
**AIchat** (Agentic RAG on-prem, LangGraph + Qwen2.5-7B, 16 container docker-compose).
Kết quả khảo sát mã nguồn AIchat:

| Trụ Cấp 4 | AIchat production | Bản thu nhỏ trong bài lab |
| :--- | :--- | :--- |
| **Memory** | `modules/chat_history.py` (MongoDB, per `user_id`/`thread_id`, nội dung mã hoá) + ChromaDB long-term + LangGraph `MongoDBSaver` checkpointer | `self.memory` episodic + `save_memory()` ghi `data/agent_memory.json` |
| **Tự đánh giá** | `modules/bertscore_middleware.py` → `/bertscore`, F1 < `BERTSCORE_THRESHOLD` (0.20) thì chặn Final Answer; `_detect_contradiction()`; `_filter_unsupported_urls()` allowlist URL; `semantic_filter_service` → `/evaluate` chạy model phụ Qwen-1.5B | `_evaluate()` LLM-as-judge trả `{score, goal_complete, reason}`, ngưỡng `EVAL_THRESHOLD = 0.5` |
| **Tách model judge** | `llm_engine` phục vụ `/generate` (Qwen-7B GPU) tách khỏi `/evaluate` (Qwen-1.5B CPU) | Planner/Executor dùng `LAB_MODEL`, Evaluator dùng `LAB_MINI_MODEL` |
| **Guardrails** | `MAX_TOTAL_ITERATIONS = 10`, `MAX_CONSECUTIVE_FAILURES = 5`, chống gọi lặp qua `_normalize_query_for_comparison()`, Rule 3 cấm gọi lại tool cùng tham số | `MAX_STEPS = 6`, `MAX_CONSECUTIVE_FAILURES = 3`, `MAX_REPLANS = 2`, chặn lặp bằng chữ ký `tool::args` |
| **Planning** | ❌ **AIchat KHÔNG có.** `grep -rn "plan\|planner\|decompos\|subtask" agents/ modules/` → 0 kết quả. Vòng lặp là `StateGraph(agent → tool → agent)` phản ứng từng bước; `is_info_sufficient` chỉ là cờ dừng sớm heuristic | ✅ `_plan()` rã mục tiêu thành danh sách bước con + re-plan khi bước hỏng |

> **Kết luận khảo sát:** AIchat là ReAct **Cấp 3** được gia cố rất kỹ, đã chạm Cấp 4
> ở Memory và Self-Evaluation, nhưng **thiếu đúng trụ Planning**. Đó chính là phần
> bài lab này bổ sung.

### 3.2. Trace THÀNH CÔNG — agent tự dừng sớm

```text
📋 [Planning] Kế hoạch 4 bước:
    1. Tra cứu thời tiết hiện tại của Hà Nội
    2. Tìm kiếm chuyến bay từ TP.HCM đi Hà Nội
    3. Lựa chọn chuyến bay phù hợp và gợi ý trang phục dựa trên thời tiết
    4. Lập kế hoạch chi tiết lịch trình chuyến đi Hà Nội 3 ngày 2 đêm

--- 🔄 Bước 1/6: Tra cứu thời tiết hiện tại của Hà Nội ---
🛠️ [Execution] get_weather({'location': 'Hà Nội'})
👁️ [Observation] Thời tiết Hà Nội: 28°C, Nắng nhẹ, Độ ẩm 65%.
⚖️ [Self-Eval] ✅ score=1.00 | goal_complete=False | Đã hoàn thành việc tra cứu thời tiết,
   nhưng vẫn còn thiếu thông tin về chuyến bay và gợi ý trang phục để đạt mục tiêu tổng.
💾 [Memory] Đã ghi bước 1

--- 🔄 Bước 2/6: Tìm kiếm chuyến bay từ TP.HCM đi Hà Nội ---
🛠️ [Execution] search_flights({'origin': 'TP.HCM', 'destination': 'Hà Nội'})
👁️ [Observation] VN123 (08:00) 1,500,000 VNĐ | VJ456 (14:30) 1,200,000 VNĐ
⚖️ [Self-Eval] ✅ score=1.00 | goal_complete=False
💾 [Memory] Đã ghi bước 2

--- 🔄 Bước 3/6: Lựa chọn chuyến bay phù hợp và gợi ý trang phục ---
⏳ [RateLimit] Hết quota, chờ 52s rồi thử lại (1/3)...
🧠 [Execution] Không cần tool, tổng hợp từ bộ nhớ.
⚖️ [Self-Eval] ✅ score=1.00 | goal_complete=True
🎯 [Goal Evaluation] Agent tự xác định MỤC TIÊU ĐÃ HOÀN THÀNH — dừng sớm.
```

**Điểm đáng chú ý:** Planner lập 4 bước nhưng Evaluator tự kết luận `goal_complete=True`
ở bước 3 → agent **bỏ bước 4 và dừng sớm**. Đây là khác biệt bản chất so với Cấp 3:
vòng lặp không kết thúc vì hết iteration mà vì agent tự đánh giá là đã đủ.

### 3.3. Trace THẤT BẠI — guardrails bắt lỗi (bằng chứng cho tiêu chí 3)

Lần chạy trước khi vá lỗi Planner, với cùng mục tiêu:

```text
--- 🔄 Bước 3/6: Phân tích chuyến bay để chọn vé khứ hồi ---
🛠️ [Execution] search_flights({'origin': 'Hà Nội', 'destination': 'TP.HCM'})
⚖️ [Self-Eval] ❌ score=0.00 | Kết quả hiển thị chuyến bay Hà Nội → TP.HCM thay vì
   TP.HCM → Hà Nội như yêu cầu, bị ngược chiều hành trình.
🔁 [Re-plan 1/2] Bước vừa rồi chưa đạt, điều chỉnh kế hoạch.

--- 🔄 Bước 4/6: Tra cứu chuyến bay khứ hồi Hà Nội về TP.HCM ---
🛑 [Guardrail] Chặn gọi lặp: search_flights({'origin': 'Hà Nội', 'destination': 'TP.HCM'})
⚖️ [Self-Eval] ❌ score=0.00
🔁 [Re-plan 2/2]

--- 🔄 Bước 5/6: Tra cứu chuyến bay từ Hà Nội về TP.HCM ---
🛑 [Guardrail] Chặn gọi lặp
⚖️ [Self-Eval] ❌ score=0.00
🛑 [Guardrail] 3 bước hỏng liên tiếp — DỪNG KHẨN CẤP.
```

**Ba guardrail cùng nổ đúng lúc:** (1) Evaluator phát hiện tool trả dữ liệu sai
chiều; (2) chống-gọi-lặp chặn hai lần đề xuất trùng; (3) `MAX_CONSECUTIVE_FAILURES`
dừng khẩn cấp thay vì đốt hết quota.

**Lỗi thật tìm ra từ trace này:** Planner không nhìn thấy danh sách lời gọi đã
thực hiện nên cứ đề xuất lại lời gọi vừa bị chặn — vòng re-plan bị kẹt. Đã vá bằng
`_executed_calls_digest()` nạp vào prompt Planner (mô phỏng Rule 3 của AIchat).
Sau khi vá, agent đi thẳng đến trace 3.2 ở trên.

**Ghi nhận trung thực:** phần tổng hợp cuối của lần chạy hỏng KHÔNG bịa dữ liệu —
agent nói rõ *"Chuyến bay khứ hồi: Chưa thể xác định chính xác"* và *"Gợi ý trang
phục: Chưa có thông tin nào được thu thập"*. Đây là hành vi mong muốn, tương ứng
lớp chống hallucination của AIchat.

### 3.4. Giới hạn đã biết

* Free tier Gemini giới hạn **5 request/phút mỗi model** → agent có `call_llm()`
  retry/backoff đọc `retryDelay` từ lỗi 429. Một lần chạy đầy đủ mất 2-4 phút.
* Registry chỉ có 2 tool nên mục tiêu "vé khứ hồi" vốn không giải được — chính giới
  hạn này tạo ra trace 3.3.
* `data/agent_memory.json` bị ghi đè mỗi lần chạy (bộ nhớ theo từng mục tiêu, chưa
  phải bộ nhớ tích luỹ đa phiên như `chat_history` của AIchat).
