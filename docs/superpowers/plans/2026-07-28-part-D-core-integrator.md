# Phần D — Core Integrator: Plan chi tiết

> **Người thực hiện:** D (Core Integrator)
> **File sở hữu:** `src/app.py`, `src/ai_levels/*`, `tests/test_guardrails.py`, `tests/test_parser.py`
> **Thay thế:** Task 5 và Task 7 trong `2026-07-28-expense-approval-agent.md`

**Goal:** Vòng lặp ReAct chịu được đầu vào bẩn từ LLM thật, và guardrail chặn được write action kể cả khi bị lừa có chủ đích.

**Nguyên tắc:** Task 5 bản gốc chỉ test đường đi đẹp — LLM trả đúng định dạng, tool chạy thành công. Đó là mức "pass yêu cầu cơ bản". Plan này test **đường đi xấu**: LLM trả markdown, tham số có dấu phẩy, tool lỗi, và người dùng cố tình lừa guardrail.

---

## 1. Kết quả rà soát đối kháng `src/app.py`

Đã chạy thử parser hiện tại với đầu vào thực tế. Bằng chứng, không phải phỏng đoán:

```
markdown bold (**Action:**)          -> parse_error          ❌
submit_decision[..., "a, b"]         -> 4 args -> TypeError  ❌
check_budget[CC-ENG, 2,400,000]      -> 3 args -> TypeError  ❌
chữ thường (action:)                 -> parse_error          ❌
Thought nhiều dòng                   -> chỉ lấy dòng đầu     ⚠️
```

### Bảng lỗi và mức ưu tiên

| # | Lỗi | Hậu quả thật | Mức |
|---|---|---|:-:|
| **F1** | Anchor bọc markdown `**Action:**` hoặc viết thường `action:` → `parse_error` | Gemini bọc markdown rất thường xuyên. Mỗi lần là mất 1 vòng lặp trong tổng số 8 | 🔴 |
| **F2** | Tách tham số bằng `split(",")` không giới hạn | `reason` của `submit_decision` là văn bản tự do — LLM viết dấu phẩy là chắc chắn. Mọi quyết định đều `TypeError` | 🔴 |
| **F3** | Số định dạng `2,400,000` bị tách thành 3 tham số | `check_budget` hỏng ngay ở case 3 | 🔴 |
| **F4** | Tiền đề tính bằng **số lần gọi**, không phải **số lần gọi thành công** | Gọi 3 tool với tham số rác đều trả `LỖI` vẫn mở khoá `submit_decision`. Đây là đường lách guardrail | 🔴 |
| **F5** | `submit_decision` không ràng buộc với đơn đã điều tra | Tra chính sách đơn A rồi ghi quyết định cho đơn B, tiền đề vẫn "đủ" | 🟡 |
| **F6** | Ghi quyết định hai lần cho cùng một đơn | Lần sau đè lần trước, không có vết | 🟡 |
| **F7** | Scratchpad phình không giới hạn | 8 vòng × observation dài → prompt phình, tốn token, có thể tràn context | 🟡 |
| **F8** | `observation.startswith(...)` khi tool trả về không phải chuỗi | `AttributeError` làm sập cả vòng lặp | 🟢 |
| **F9** | `Thought` nhiều dòng chỉ lấy dòng đầu | Scratchpad mất ngữ cảnh, LLM lặp lại suy luận cũ | 🟢 |

**F1-F4 bắt buộc làm.** F5-F7 nên làm. F8-F9 làm nếu còn thời gian.

> **Ghi chú gửi C (Prompt Engineer):** `TIMEOUT_SECONDS` trong `prompts.py` được khai
> báo nhưng **không nơi nào dùng**. Tool đều là hàm cục bộ chạy tức thì nên timeout
> vô nghĩa ở đó; chỗ thật sự cần timeout là lời gọi LLM trong `llm_utils.py`. Hoặc
> nối vào provider, hoặc xoá — đừng để config chết trong file.

---

## Task D1: Chuẩn hoá anchor — chịu được markdown và chữ thường

**Files:**
- Modify: `src/app.py`
- Create: `tests/test_parser.py`

**Interfaces:**
- Produces: `_normalize_anchors(text: str) -> str`; `parse_react_output` xử lý được anchor bẩn

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_parser.py`:

```python
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from app import parse_react_output


@pytest.mark.parametrize("raw", [
    "Thought: tra\nAction: get_policy[an_uong]",
    "Thought: tra\n**Action:** get_policy[an_uong]",
    "**Thought:** tra\n**Action:** get_policy[an_uong]",
    "thought: tra\naction: get_policy[an_uong]",
    "THOUGHT: tra\nACTION: get_policy[an_uong]",
    "Thought: tra\n- Action: get_policy[an_uong]",
    "Thought: tra\n* **Action**: get_policy[an_uong]",
    "Thought: tra\n### Action: get_policy[an_uong]",
    "Thought: tra\nAction : get_policy[an_uong]",
])
def test_nhan_dien_action_du_anchor_bi_boc_markdown(raw):
    r = parse_react_output(raw)
    assert r["type"] == "action", f"không parse được: {raw!r}"
    assert r["tool"] == "get_policy"
    assert r["args"] == ["an_uong"]


@pytest.mark.parametrize("raw", [
    "Thought: xong\nFinal Answer: Đơn hợp lệ.",
    "Thought: xong\n**Final Answer:** Đơn hợp lệ.",
    "thought: xong\nfinal answer: Đơn hợp lệ.",
])
def test_nhan_dien_final_answer_du_anchor_bi_boc(raw):
    r = parse_react_output(raw)
    assert r["type"] == "final"
    assert "Đơn hợp lệ" in r["answer"]


def test_khong_pha_dau_gach_duoi_trong_ten_hang_muc():
    """Chuẩn hoá anchor KHÔNG được đụng vào nội dung tham số."""
    r = parse_react_output("Thought: tra\n**Action:** get_policy[an_uong]")
    assert r["args"] == ["an_uong"], "dấu _ trong an_uong bị nuốt mất"


def test_van_cat_bo_observation_llm_tu_bia():
    r = parse_react_output(
        "Thought: tra\nAction: get_policy[an_uong]\nObservation: tôi tự bịa\nFinal Answer: xong"
    )
    assert r["type"] == "action"


def test_uu_tien_action_hon_final_answer():
    r = parse_react_output("Thought: t\nAction: get_policy[an_uong]\nFinal Answer: xong luôn")
    assert r["type"] == "action"
```

- [ ] **Step 2: Chạy để chắc chắn fail**

Run: `.venv/bin/python -m pytest tests/test_parser.py -v`
Expected: các biến thể markdown/chữ thường FAIL với `type == 'parse_error'`.

- [ ] **Step 3: Thêm `_normalize_anchors` vào `src/app.py`**

Đặt ngay trước `parse_react_output`:

```python
# Anchor do LLM sinh ra rất hay bị bọc markdown (`**Action:**`), viết thường,
# hoặc đứng sau bullet (`- Action:`). Chuẩn hoá về dạng chuẩn TRƯỚC khi parse.
# Chỉ đụng vào phần anchor ở ĐẦU DÒNG — tuyệt đối không chạm nội dung tham số,
# nếu không sẽ nuốt mất dấu _ trong tên hạng mục như 'an_uong'.
_ANCHOR_RE = re.compile(
    r"(?im)^[ \t]*(?:[-*>#]+[ \t]*)*\**[ \t]*"
    r"(Thought|Action Input|Action|Final Answer|Observation)"
    r"[ \t]*\**[ \t]*:[ \t]*\**"
)

_ANCHOR_CANON = {
    "thought": "Thought",
    "action input": "Action Input",
    "action": "Action",
    "final answer": "Final Answer",
    "observation": "Observation",
}


def _normalize_anchors(text: str) -> str:
    """Đưa mọi biến thể anchor về đúng dạng 'Thought:' / 'Action:' / ..."""
    return _ANCHOR_RE.sub(lambda m: _ANCHOR_CANON[m.group(1).lower()] + ": ", text)
```

- [ ] **Step 4: Gọi nó ở đầu `parse_react_output`**

Sửa dòng đầu thân hàm:

```python
def parse_react_output(text: str) -> dict:
    text = _normalize_anchors(text)
    obs_idx = text.find("Observation:")
    ...
```

- [ ] **Step 5: Chạy test xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_parser.py -v`
Expected: toàn bộ PASS.

- [ ] **Step 6: Commit**

```bash
git add src/app.py tests/test_parser.py
git commit -m "fix(parser): chuẩn hoá anchor bọc markdown/chữ thường trước khi parse"
```

---

## Task D2: Tách tham số theo đúng số tham số của tool

**Files:**
- Modify: `src/app.py`
- Modify: `tests/test_parser.py`

**Interfaces:**
- Produces: `_split_args(raw: str, tool_name: str) -> list[str]`

**Vì sao không tách đơn giản bằng `split(",")`:** tham số cuối của `submit_decision`
là lý do dạng văn bản tự do. LLM chắc chắn viết dấu phẩy trong đó. Cách đúng là hỏi
chính hàm tool xem nó nhận mấy tham số, rồi giới hạn số lần tách.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_parser.py`:

```python
def test_ly_do_co_dau_phay_van_gom_thanh_mot_tham_so():
    r = parse_react_output(
        "Thought: xong\n"
        "Action: submit_decision[EXP-2026-0143, REJECTED, Vượt ngân sách, còn thiếu 20 triệu]"
    )
    assert r["args"] == [
        "EXP-2026-0143",
        "REJECTED",
        "Vượt ngân sách, còn thiếu 20 triệu",
    ]


def test_so_tien_co_dau_phay_khong_bi_tach():
    r = parse_react_output("Thought: tra\nAction: check_budget[CC-ENG, 2,400,000]")
    assert r["args"] == ["CC-ENG", "2,400,000"]


def test_so_tien_co_dau_cham_khong_bi_tach():
    r = parse_react_output("Thought: tra\nAction: check_budget[CC-ENG, 2.400.000]")
    assert r["args"] == ["CC-ENG", "2.400.000"]


def test_tool_mot_tham_so_khong_bi_tach():
    r = parse_react_output("Thought: tra\nAction: get_policy[an_uong, thừa, thãi]")
    assert r["args"] == ["an_uong, thừa, thãi"]


def test_tool_khong_ton_tai_van_parse_duoc_de_guardrail_bat():
    r = parse_react_output("Thought: t\nAction: tool_khong_co[a, b]")
    assert r["type"] == "action"
    assert r["tool"] == "tool_khong_co"


def test_tham_so_rong():
    r = parse_react_output("Thought: t\nAction: get_policy[]")
    assert r["args"] == []


def test_bo_dau_nhay_bao_quanh_tham_so():
    r = parse_react_output('Thought: t\nAction: get_policy["an_uong"]')
    assert r["args"] == ["an_uong"]
```

- [ ] **Step 2: Chạy để chắc chắn fail**

Run: `.venv/bin/python -m pytest tests/test_parser.py -k "dau_phay or tach" -v`
Expected: FAIL — args bị tách thành 4 phần tử.

- [ ] **Step 3: Thêm `_split_args` vào `src/app.py`**

Thêm `import inspect` vào khối import, rồi đặt cạnh `_normalize_anchors`:

```python
def _tool_arity(tool_name: str) -> int | None:
    """Số tham số của tool, hoặc None nếu không biết tool đó."""
    fn = AVAILABLE_TOOLS.get(tool_name)
    if fn is None:
        return None
    return len(inspect.signature(fn).parameters)


def _split_args(raw: str, tool_name: str) -> list:
    """Tách tham số theo ĐÚNG số tham số mà tool nhận.

    Tham số cuối của submit_decision là lý do dạng văn bản tự do — LLM chắc chắn
    viết dấu phẩy trong đó. Giới hạn số lần tách để phần đuôi được giữ nguyên vẹn.
    Cũng nhờ vậy mà số tiền '2,400,000' không bị xé thành ba tham số.
    """
    if not raw.strip():
        return []
    arity = _tool_arity(tool_name)
    if arity is None or arity < 1:
        parts = raw.split(",")           # tool lạ — guardrail unknown_tool sẽ bắt
    else:
        parts = raw.split(",", arity - 1)
    return [p.strip().strip("'\"") for p in parts]
```

- [ ] **Step 4: Dùng nó trong `parse_react_output`**

Thay khối xử lý `action_match`:

```python
    action_match = re.search(r"Action:\s*(\w+)\s*\[(.*?)\]", text, re.DOTALL)
    if action_match:
        tool_name = action_match.group(1)
        args = _split_args(action_match.group(2).strip(), tool_name)
        return {"type": "action", "thought": thought, "tool": tool_name, "args": args}
```

- [ ] **Step 5: Chạy test xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_parser.py -v`
Expected: toàn bộ PASS.

- [ ] **Step 6: Commit**

```bash
git add src/app.py tests/test_parser.py
git commit -m "fix(parser): tách tham số theo arity của tool, không xé lý do có dấu phẩy"
```

---

## Task D3: Tiền đề phải là lời gọi THÀNH CÔNG

**Files:**
- Modify: `src/app.py`
- Create: `tests/test_guardrails.py`

**Interfaces:**
- Consumes: `AVAILABLE_TOOLS` (7 tool của B), `MAX_ITERATIONS` (của C)
- Produces: `TOOL_PRECONDITIONS`; trace có thêm khoá `successful_tools: list[str]`

**Lỗ hổng đang vá:** bản Task 5 gốc đếm tiền đề bằng `tools_called`, mà `tools_called`
được ghi **trước khi** biết tool trả `LỖI` hay không. Kẻ tấn công chỉ cần gọi ba tool
với tham số rác — cả ba đều lỗi — là mở được khoá `submit_decision`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/test_guardrails.py`:

```python
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import tools as tools_mod
from app import run_react_agent


class FakeProvider:
    """Provider giả trả kịch bản soạn sẵn — không gọi LLM thật, không tốn quota."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts_seen = []

    def generate(self, prompt, system_prompt=""):
        self.prompts_seen.append(prompt)
        if not self.responses:
            return "Thought: hết kịch bản\nFinal Answer: hết kịch bản"
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def reset_decisions():
    """_DECISIONS là state toàn cục trong tools.py — phải dọn giữa các test."""
    tools_mod._DECISIONS.clear()
    yield
    tools_mod._DECISIONS.clear()


# ---------------------------------------------------------- tiền đề

def test_chan_submit_decision_khi_chua_goi_gi():
    provider = FakeProvider([
        "Thought: duyệt luôn\nAction: submit_decision[EXP-2026-0142, APPROVED, ok]",
        "Thought: bị chặn\nFinal Answer: Chưa đủ căn cứ.",
    ])
    trace = run_react_agent("Duyệt đơn EXP-2026-0142", provider)
    assert "precondition_violated" in trace["guardrails"]
    assert "submit_decision" not in trace["tools_called"]
    assert "EXP-2026-0142" not in tools_mod._DECISIONS


def test_ba_loi_goi_HONG_khong_duoc_mo_khoa_submit_decision():
    """Đường lách chính: gọi đủ 3 tool nhưng tham số rác nên tool nào cũng lỗi."""
    provider = FakeProvider([
        "Thought: t\nAction: get_policy[hang_muc_khong_co_that]",
        "Thought: t\nAction: check_budget[CC-KHONG-CO, 999]",
        "Thought: t\nAction: find_duplicate_claims[EMP-XXX, vendor_ma]",
        "Thought: đủ rồi\nAction: submit_decision[EXP-2026-0142, APPROVED, ok]",
        "Thought: bị chặn\nFinal Answer: Không đủ căn cứ.",
    ])
    trace = run_react_agent("Duyệt đơn EXP-2026-0142", provider)

    assert "precondition_violated" in trace["guardrails"]
    assert "submit_decision" not in trace["tools_called"]
    assert "EXP-2026-0142" not in tools_mod._DECISIONS


def test_cho_qua_khi_ba_tien_de_deu_thanh_cong():
    provider = FakeProvider([
        "Thought: t\nAction: get_expense_report[EXP-2026-0142]",
        "Thought: t\nAction: get_policy[an_uong]",
        "Thought: t\nAction: check_budget[CC-ENG, 2400000]",
        "Thought: t\nAction: find_duplicate_claims[EMP-001, Nhà hàng Ngon]",
        "Thought: đủ\nAction: submit_decision[EXP-2026-0142, APPROVED, Đơn giá 400.000 dưới hạn mức]",
        "Thought: xong\nFinal Answer: Đã duyệt EXP-2026-0142.",
    ])
    trace = run_react_agent("Duyệt đơn EXP-2026-0142", provider)

    assert "precondition_violated" not in trace["guardrails"]
    assert "submit_decision" in trace["tools_called"]
    assert tools_mod._DECISIONS["EXP-2026-0142"]["decision"] == "APPROVED"


def test_trace_phan_biet_tool_da_goi_va_tool_thanh_cong():
    provider = FakeProvider([
        "Thought: t\nAction: get_policy[hang_muc_ma]",
        "Thought: t\nAction: get_policy[an_uong]",
        "Thought: xong\nFinal Answer: xong",
    ])
    trace = run_react_agent("test", provider)
    assert trace["tools_called"].count("get_policy") == 2
    assert trace["successful_tools"].count("get_policy") == 1
```

- [ ] **Step 2: Chạy để chắc chắn fail**

Run: `.venv/bin/python -m pytest tests/test_guardrails.py -v`
Expected: `test_ba_loi_goi_HONG_...` và `test_trace_phan_biet...` FAIL.

- [ ] **Step 3: Thêm `TOOL_PRECONDITIONS` vào `src/app.py`**

Đặt sau khối import:

```python
# 🛡️ Guardrail tầng CODE cho write action.
# Quy tắc 3 ở prompt đã cấm, nhưng prompt có thể bị LLM phớt lờ hoặc bị người dùng
# lừa — nên chặn thêm một tầng ở đây. Hai tầng tồn tại có chủ đích.
#
# Tiền đề tính trên tool gọi THÀNH CÔNG, không phải tool đã gọi. Nếu tính theo
# số lần gọi thì chỉ cần gọi 3 tool với tham số rác (cả 3 đều trả LỖI) là mở
# được khoá — đó là đường lách, không phải guardrail.
TOOL_PRECONDITIONS = {
    "submit_decision": ["get_policy", "check_budget", "find_duplicate_claims"],
}
```

- [ ] **Step 4: Sửa `run_react_agent` — thêm `successful_tools`**

Khởi tạo cùng chỗ với `tools_called`:

```python
    tools_called = []
    successful_tools = []
```

Thay khối phân nhánh xử lý tool bằng:

```python
        signature = f"{tool_name}::{'|'.join(a.lower() for a in args)}"
        thieu = [t for t in TOOL_PRECONDITIONS.get(tool_name, []) if t not in successful_tools]

        if signature in seen_calls:
            observation = "LỖI: Bạn đã gọi y hệt lời gọi này rồi. Dùng lại kết quả ở trên, đừng gọi lại."
            print(f"🛑 [Guardrail] Chặn gọi lặp: {tool_name}[{', '.join(args)}]")
            guardrails.append("duplicate_call")
        elif tool_name not in AVAILABLE_TOOLS:
            observation = f"LỖI: Tool '{tool_name}' không tồn tại. Chỉ có: {', '.join(AVAILABLE_TOOLS)}."
            guardrails.append("unknown_tool")
        elif thieu:
            observation = (
                f"LỖI: Chưa đủ căn cứ để gọi '{tool_name}'. Bắt buộc phải có kết quả "
                f"THÀNH CÔNG của {', '.join(thieu)} trước đã."
            )
            print(f"🛑 [Guardrail] Chặn '{tool_name}' — thiếu tiền đề: {', '.join(thieu)}")
            guardrails.append("precondition_violated")
        else:
            seen_calls.add(signature)
            tools_called.append(tool_name)
            try:
                observation = str(AVAILABLE_TOOLS[tool_name](*args))
                if observation.startswith("LỖI"):
                    guardrails.append("tool_error")
                else:
                    successful_tools.append(tool_name)
            except TypeError as e:
                observation = f"LỖI: Sai số lượng tham số cho '{tool_name}' — {e}"
                guardrails.append("bad_args")
```

`str(...)` bọc ngoài là để vá F8: tool lỡ trả về không phải chuỗi thì `.startswith`
sẽ ném `AttributeError` làm sập cả vòng lặp.

- [ ] **Step 5: Thêm `successful_tools` vào cả ba điểm return**

Cả ba `return` của `run_react_agent` (lỗi LLM, có Final Answer, chạm trần lặp) đều
phải kèm `"successful_tools": successful_tools`.

- [ ] **Step 6: Chạy test xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_guardrails.py -v`
Expected: 4 PASS.

- [ ] **Step 7: Commit**

```bash
git add src/app.py tests/test_guardrails.py
git commit -m "fix(guardrail): tiền đề tính theo lời gọi THÀNH CÔNG, chặn đường lách bằng tool lỗi"
```

---

## Task D4: Ràng buộc quyết định với đúng đơn đã điều tra

**Files:**
- Modify: `src/app.py`
- Modify: `tests/test_guardrails.py`

**Interfaces:**
- Produces: guardrail `subject_mismatch`, `already_decided`

**Vấn đề:** tiền đề chỉ kiểm tra "đã gọi đủ 3 tool", không kiểm tra "3 tool đó nói về
đúng cái đơn này". Agent hoàn toàn có thể tra chính sách cho đơn A rồi ghi quyết định
cho đơn B. Và hiện chưa có gì chặn việc ghi quyết định hai lần cho cùng một đơn.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_guardrails.py`:

```python
def test_chan_ghi_quyet_dinh_cho_don_chua_he_tra_cuu():
    """Điều tra đơn 0142 nhưng ghi quyết định cho đơn 0143."""
    provider = FakeProvider([
        "Thought: t\nAction: get_expense_report[EXP-2026-0142]",
        "Thought: t\nAction: get_policy[an_uong]",
        "Thought: t\nAction: check_budget[CC-ENG, 2400000]",
        "Thought: t\nAction: find_duplicate_claims[EMP-001, Nhà hàng Ngon]",
        "Thought: ghi cho đơn khác\nAction: submit_decision[EXP-2026-0143, APPROVED, ok]",
        "Thought: bị chặn\nFinal Answer: Tôi chưa điều tra đơn đó.",
    ])
    trace = run_react_agent("test", provider)

    assert "subject_mismatch" in trace["guardrails"]
    assert "EXP-2026-0143" not in tools_mod._DECISIONS


def test_chan_ghi_quyet_dinh_lan_thu_hai_cho_cung_mot_don():
    provider = FakeProvider([
        "Thought: t\nAction: get_expense_report[EXP-2026-0142]",
        "Thought: t\nAction: get_policy[an_uong]",
        "Thought: t\nAction: check_budget[CC-ENG, 2400000]",
        "Thought: t\nAction: find_duplicate_claims[EMP-001, Nhà hàng Ngon]",
        "Thought: ghi\nAction: submit_decision[EXP-2026-0142, APPROVED, lần đầu]",
        "Thought: đổi ý\nAction: submit_decision[EXP-2026-0142, REJECTED, lần hai]",
        "Thought: xong\nFinal Answer: xong",
    ])
    trace = run_react_agent("test", provider)

    assert "already_decided" in trace["guardrails"]
    assert tools_mod._DECISIONS["EXP-2026-0142"]["decision"] == "APPROVED", \
        "quyết định lần đầu bị đè — phải giữ nguyên"


def test_cho_ghi_khi_dung_don_da_dieu_tra():
    provider = FakeProvider([
        "Thought: t\nAction: get_expense_report[EXP-2026-0142]",
        "Thought: t\nAction: get_policy[an_uong]",
        "Thought: t\nAction: check_budget[CC-ENG, 2400000]",
        "Thought: t\nAction: find_duplicate_claims[EMP-001, Nhà hàng Ngon]",
        "Thought: ghi\nAction: submit_decision[EXP-2026-0142, APPROVED, đúng đơn]",
        "Thought: xong\nFinal Answer: xong",
    ])
    trace = run_react_agent("test", provider)
    assert "subject_mismatch" not in trace["guardrails"]
    assert "already_decided" not in trace["guardrails"]
```

- [ ] **Step 2: Chạy để chắc chắn fail**

Run: `.venv/bin/python -m pytest tests/test_guardrails.py -k "subject or lan_thu_hai" -v`
Expected: FAIL — chưa có hai guardrail này.

- [ ] **Step 3: Thêm bảng ràng buộc chủ thể vào `src/app.py`**

Đặt cạnh `TOOL_PRECONDITIONS`:

```python
# Tool nào "mở hồ sơ" một đơn, và tool nào ghi quyết định cho đơn đó.
# Quyết định chỉ được ghi cho đơn đã thực sự mở hồ sơ trong phiên này.
TOOL_OPENS_SUBJECT = "get_expense_report"
TOOL_DECIDES_SUBJECT = "submit_decision"
```

- [ ] **Step 4: Theo dõi chủ thể trong `run_react_agent`**

Khởi tạo cùng chỗ với `successful_tools`:

```python
    investigated = set()   # report_id đã mở hồ sơ thành công
    decided = set()        # report_id đã ghi quyết định
```

Chèn hai nhánh **trước** nhánh `elif thieu:` (thứ tự quan trọng — chặn sai chủ thể
trước khi báo thiếu tiền đề thì thông báo lỗi mới đúng nguyên nhân):

```python
        subject = args[0].strip().upper() if args else ""

        if signature in seen_calls:
            ...
        elif tool_name not in AVAILABLE_TOOLS:
            ...
        elif tool_name == TOOL_DECIDES_SUBJECT and subject in decided:
            observation = (
                f"LỖI: Đơn {subject} đã có quyết định rồi, không được ghi đè. "
                f"Nếu cần đổi, phải nêu rõ trong Final Answer thay vì ghi lại."
            )
            print(f"🛑 [Guardrail] Chặn ghi đè quyết định đơn {subject}")
            guardrails.append("already_decided")
        elif tool_name == TOOL_DECIDES_SUBJECT and subject not in investigated:
            observation = (
                f"LỖI: Chưa mở hồ sơ đơn {subject}. Phải gọi "
                f"{TOOL_OPENS_SUBJECT}[{subject}] trước khi ghi quyết định cho nó."
            )
            print(f"🛑 [Guardrail] Chặn ghi quyết định cho đơn chưa điều tra: {subject}")
            guardrails.append("subject_mismatch")
        elif thieu:
            ...
```

Trong nhánh `else` thực thi thành công, cập nhật hai tập:

```python
                else:
                    successful_tools.append(tool_name)
                    if tool_name == TOOL_OPENS_SUBJECT and subject:
                        investigated.add(subject)
                    elif tool_name == TOOL_DECIDES_SUBJECT and subject:
                        decided.add(subject)
```

- [ ] **Step 5: Chạy test xác nhận pass**

Run: `.venv/bin/python -m pytest tests/test_guardrails.py -v`
Expected: 7 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/app.py tests/test_guardrails.py
git commit -m "fix(guardrail): quyết định phải gắn đúng đơn đã điều tra, cấm ghi đè"
```

---

## Task D5: Các guardrail còn lại + giới hạn scratchpad

**Files:**
- Modify: `src/app.py`
- Modify: `tests/test_guardrails.py`

**Interfaces:**
- Produces: `MAX_SCRATCHPAD_CHARS`; guardrail `scratchpad_truncated`

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/test_guardrails.py`:

```python
def test_chan_goi_lap_cung_tool_cung_tham_so():
    provider = FakeProvider([
        "Thought: t\nAction: get_policy[an_uong]",
        "Thought: t\nAction: get_policy[an_uong]",
        "Thought: thôi\nFinal Answer: xong",
    ])
    trace = run_react_agent("test", provider)
    assert "duplicate_call" in trace["guardrails"]


def test_bat_tool_khong_ton_tai():
    provider = FakeProvider([
        "Thought: t\nAction: xoa_toan_bo_du_lieu[all]",
        "Thought: thôi\nFinal Answer: Không có tool đó.",
    ])
    trace = run_react_agent("test", provider)
    assert "unknown_tool" in trace["guardrails"]


def test_bat_sai_so_luong_tham_so():
    provider = FakeProvider([
        "Thought: t\nAction: check_budget[CC-ENG]",
        "Thought: sửa\nFinal Answer: xong",
    ])
    trace = run_react_agent("test", provider)
    assert "bad_args" in trace["guardrails"]


def test_bat_output_sai_dinh_dang():
    provider = FakeProvider([
        "Tôi nghĩ đơn này ổn đấy.",
        "Thought: làm lại\nFinal Answer: Đơn hợp lệ.",
    ])
    trace = run_react_agent("test", provider)
    assert "parse_error" in trace["guardrails"]


def test_cham_tran_max_iterations():
    provider = FakeProvider(["Thought: t\nAction: get_policy[an_uong]"] * 30)
    trace = run_react_agent("test", provider)
    assert "max_iterations" in trace["guardrails"]
    assert trace["ok"] is False


def test_scratchpad_bi_cat_khi_qua_dai():
    """Observation dài × nhiều vòng không được làm prompt phình vô hạn."""
    provider = FakeProvider([
        f"Thought: t\nAction: get_expense_report[EXP-2026-014{i}]" for i in range(2, 7)
    ] + ["Thought: xong\nFinal Answer: xong"])
    trace = run_react_agent("test", provider)

    prompt_cuoi = provider.prompts_seen[-1]
    from app import MAX_SCRATCHPAD_CHARS
    assert len(prompt_cuoi) < MAX_SCRATCHPAD_CHARS * 2, "prompt phình quá mức"


def test_khong_sap_khi_het_kich_ban():
    """FakeProvider hết kịch bản vẫn phải kết thúc gọn, không ném exception."""
    provider = FakeProvider([])
    trace = run_react_agent("test", provider)
    assert trace["ok"] is True
```

- [ ] **Step 2: Chạy để chắc chắn fail**

Run: `.venv/bin/python -m pytest tests/test_guardrails.py -k scratchpad -v`
Expected: FAIL — `ImportError: cannot import name 'MAX_SCRATCHPAD_CHARS'`

- [ ] **Step 3: Thêm giới hạn scratchpad vào `src/app.py`**

Đặt cạnh `TOOL_PRECONDITIONS`:

```python
# Scratchpad được nạp lại vào prompt MỖI vòng. Với 8 vòng và observation dài
# (get_expense_report trả cả bảng line item) thì prompt phình rất nhanh — tốn
# token và có thể tràn context. Giữ phần MỚI NHẤT vì nó sát ngữ cảnh hiện tại.
MAX_SCRATCHPAD_CHARS = 6000


def _truncate_scratchpad(scratchpad: str) -> tuple:
    """Cắt bớt phần đầu nếu scratchpad quá dài. Trả về (nội_dung, đã_cắt)."""
    if len(scratchpad) <= MAX_SCRATCHPAD_CHARS:
        return scratchpad, False
    giu_lai = scratchpad[-MAX_SCRATCHPAD_CHARS:]
    return "\n[... phần đầu đã lược bớt cho gọn ...]\n" + giu_lai, True
```

- [ ] **Step 4: Gọi trước khi dựng prompt**

Trong `run_react_agent`, ngay đầu mỗi vòng lặp:

```python
        scratchpad, da_cat = _truncate_scratchpad(scratchpad)
        if da_cat and "scratchpad_truncated" not in guardrails:
            guardrails.append("scratchpad_truncated")

        prompt = f"{REACT_SYSTEM_PROMPT}\nCâu hỏi: {user_query}\n{scratchpad}"
```

- [ ] **Step 5: Chạy toàn bộ test**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: toàn bộ PASS, không lần nào gọi LLM thật.

- [ ] **Step 6: Commit**

```bash
git add src/app.py tests/test_guardrails.py
git commit -m "feat(app): giới hạn scratchpad + phủ kín test guardrail còn lại"
```

---

## Task D6: Bốn demo cấp độ AI

**Files:**
- Modify: `src/ai_levels/level1_rule_based.py`, `level2_llm_chatbot.py`, `level3_reactive_agent.py`, `level4_autonomous_agent.py`

Nội dung bốn file này lấy nguyên từ **Task 7** của plan gốc
(`2026-07-28-expense-approval-agent.md`) — không thay đổi gì.

Một điểm bổ sung: `level4_autonomous_agent.py` phải đổi `TOOL_SPECS` sang 7 tool mới
**và** đổi goal sang bài duyệt hàng loạt có ngân sách hao dần.

- [ ] **Step 1: Làm Task 7 Step 1-4 của plan gốc**
- [ ] **Step 2: Chạy demo Cấp 1 (không tốn quota)**

Run: `.venv/bin/python src/ai_levels/level1_rule_based.py`
Expected: câu hỏi về đơn chi phí → bot trả "không hiểu".

- [ ] **Step 3: Commit**

```bash
git add src/ai_levels/
git commit -m "feat(ai_levels): 4 demo cấp độ chuyển sang domain duyệt chi phí"
```

---

## 2. Ma trận test của phần D

| Guardrail | Kích hoạt khi | Test |
|---|---|---|
| `duplicate_call` | Gọi lại cùng tool cùng tham số | `test_chan_goi_lap_cung_tool_cung_tham_so` |
| `unknown_tool` | Tool không có trong registry | `test_bat_tool_khong_ton_tai` |
| `bad_args` | Sai số lượng tham số | `test_bat_sai_so_luong_tham_so` |
| `tool_error` | Tool trả chuỗi `LỖI:` | `test_trace_phan_biet_tool_da_goi_va_tool_thanh_cong` |
| `precondition_violated` | Ghi quyết định khi chưa đủ 3 tiền đề **thành công** | `test_chan_submit_decision_khi_chua_goi_gi`, `test_ba_loi_goi_HONG_khong_duoc_mo_khoa_submit_decision` |
| `subject_mismatch` | Ghi quyết định cho đơn chưa mở hồ sơ | `test_chan_ghi_quyet_dinh_cho_don_chua_he_tra_cuu` |
| `already_decided` | Ghi quyết định lần hai cho cùng đơn | `test_chan_ghi_quyet_dinh_lan_thu_hai_cho_cung_mot_don` |
| `parse_error` | Output không có Action lẫn Final Answer | `test_bat_output_sai_dinh_dang` |
| `max_iterations` | Hết số vòng cho phép | `test_cham_tran_max_iterations` |
| `scratchpad_truncated` | Scratchpad vượt 6000 ký tự | `test_scratchpad_bi_cat_khi_qua_dai` |

**Tổng: 9 test parser + 12 test guardrail = 21 test, toàn bộ chạy offline.**

## 3. Điều cần nói với cả nhóm

1. **Ba lỗi parser F1-F3 sẽ nổ ở mọi nhóm dùng cùng boilerplate này.** Nếu nhóm khác
   chưa vá, Agent của họ sẽ `parse_error` mỗi khi Gemini bọc markdown, và `TypeError`
   mỗi khi lý do có dấu phẩy. Đây là đạn tốt cho vòng cross-audit Mốc 4.

2. **F4 là thứ đáng nói nhất khi thuyết trình.** Guardrail đếm "đã gọi 3 tool" nghe
   thì chặt, nhưng gọi 3 tool với tham số rác cũng tính là đủ. Sửa thành "3 tool
   **thành công**" mới thật sự là phanh. Chỗ này thể hiện rõ khác biệt giữa guardrail
   hình thức và guardrail thật.

3. **Phần D không phụ thuộc B để bắt đầu.** Test parser (D1, D2) chạy được ngay với
   `tools.py` hiện tại. Chỉ từ D3 trở đi mới cần 7 tool của B.

4. **Đừng chạy LLM thật để tìm lỗi mà pytest bắt được miễn phí.** 21 test này chạy
   trong dưới một giây và không tốn một lượt quota nào.
