"""
Test cho Autonomous Agent (Cấp 4) — phần bonus +10% điểm.

File `level4_autonomous_agent.py` gần 400 dòng và trước đây không có một test nào.
Test quan trọng nhất ở đây là `test_BO_NHO_MANG_DU_LIEU_BUOC_TRUOC_SANG_BUOC_SAU`:
nó chứng minh Memory có tác dụng nhân quả chứ không phải trang trí.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import ai_levels.level4_autonomous_agent as mod  # noqa: E402
from ai_levels.level4_autonomous_agent import (  # noqa: E402
    MAX_REPLANS,
    AutonomousAgent,
    _extract_json,
)


class ScriptedProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts_seen = []

    def generate(self, prompt, system_prompt=""):
        self.prompts_seen.append(prompt)
        return self.responses.pop(0) if self.responses else "{}"


@pytest.fixture(autouse=True)
def bo_nho_tam(tmp_path, monkeypatch):
    """Ghi bộ nhớ vào thư mục tạm, không đụng `data/` của người dùng."""
    monkeypatch.setattr(mod, "MEMORY_DIR", str(tmp_path))
    return tmp_path


def _agent(main_responses, judge_responses, **kw):
    return AutonomousAgent(
        kw.pop("goal", "mục tiêu"),
        provider=ScriptedProvider(main_responses),
        judge_provider=ScriptedProvider(judge_responses),
        **kw,
    )


# ============================================================ _extract_json

@pytest.mark.parametrize("raw,mong_doi", [
    ('["a","b"]', ["a", "b"]),
    ('```json\n["a","b"]\n```', ["a", "b"]),
    ('```\n{"score": 0.9}\n```', {"score": 0.9}),
    ('Đây là kế hoạch:\n["a"]\nHết.', ["a"]),
    ('{"score": 0.5, "goal_complete": true, "reason": "ok"}',
     {"score": 0.5, "goal_complete": True, "reason": "ok"}),
])
def test_extract_json_moi_dinh_dang(raw, mong_doi):
    assert _extract_json(raw) == mong_doi


@pytest.mark.parametrize("raw", ["", "không có json ở đây", "{hỏng", None])
def test_extract_json_tra_none_khi_hong(raw):
    assert _extract_json(raw) is None


# ============================================================ Planner

def test_planner_khong_sap_khi_provider_loi():
    agent = _agent(["[OpenAI Exception]: Error code: 429 - RESOURCE_EXHAUSTED"], [])
    assert agent._plan() == []


def test_planner_khong_sap_khi_json_hong():
    agent = _agent(["kế hoạch của tôi là làm từng bước một"], [])
    assert agent._plan() == []


def test_planner_cat_bot_theo_so_buoc_con_lai():
    agent = _agent(['["b1","b2","b3","b4","b5"]'], [], max_steps=2)
    assert len(agent._plan()) == 2


def test_planner_nhan_duoc_phan_hoi_khi_replan():
    provider = ScriptedProvider(['["b1"]'])
    agent = AutonomousAgent("m", provider=provider, judge_provider=ScriptedProvider([]))
    agent._plan(feedback="Bước trước hỏng vì thiếu dữ liệu")

    assert "Bước trước hỏng vì thiếu dữ liệu" in provider.prompts_seen[0]


# ============================================================ Evaluator

def test_evaluator_khong_chan_buoc_khi_judge_hong():
    """Judge hỏng thì KHÔNG được đánh trượt bước.

    Cùng nguyên tắc với BERTScore của AIchat: lỗi hạ tầng đánh giá không được
    biến thành phán quyết 'bước này sai'.
    """
    agent = _agent([], ["judge trả về rác không phải JSON"])
    v = agent._evaluate("bước", "kết quả")

    assert v["score"] == 1.0
    assert v["goal_complete"] is False


@pytest.mark.parametrize("raw,mong_doi", [
    ('{"score": 5, "goal_complete": false, "reason": "r"}', 1.0),
    ('{"score": -3, "goal_complete": false, "reason": "r"}', 0.0),
    ('{"score": "hỏng", "goal_complete": false, "reason": "r"}', 0.0),
    ('{"score": 0.75, "goal_complete": false, "reason": "r"}', 0.75),
])
def test_evaluator_kep_diem_ve_khoang_0_1(raw, mong_doi):
    agent = _agent([], [raw])
    assert agent._evaluate("b", "kq")["score"] == mong_doi


def test_evaluator_dung_provider_rieng():
    """Evaluator phải gọi judge_provider, không ăn vào quota của provider chính."""
    main = ScriptedProvider([])
    judge = ScriptedProvider(['{"score": 1.0, "goal_complete": false, "reason": "r"}'])
    agent = AutonomousAgent("m", provider=main, judge_provider=judge)
    agent._evaluate("b", "kq")

    assert len(judge.prompts_seen) == 1
    assert len(main.prompts_seen) == 0


# ============================================================ Guardrails

def test_dung_som_khi_evaluator_bao_hoan_thanh():
    agent = _agent(
        ['["b1","b2","b3"]',
         '{"tool": null, "args": {}, "answer": "đã tổng hợp xong"}',
         "câu trả lời cuối"],
        ['{"score": 1.0, "goal_complete": true, "reason": "đủ"}'],
        max_steps=6,
    )
    agent.run()
    assert len(agent.memory) == 1, "goal_complete=True phải dừng ngay, bỏ b2 và b3"


def test_khong_replan_qua_gioi_han():
    agent = _agent(
        ['["b1"]'] * 10 + ['{"tool": null, "args": {}, "answer": ""}'] * 10 + ["tổng kết"],
        ['{"score": 0.0, "goal_complete": false, "reason": "hỏng"}'] * 10,
        max_steps=6,
    )
    agent.run()
    assert agent.replans <= MAX_REPLANS


def test_khong_vuot_qua_max_steps():
    agent = _agent(
        ['["b1","b2","b3","b4","b5","b6","b7","b8"]']
        + ['{"tool": null, "args": {}, "answer": "xong bước"}'] * 12
        + ["tổng kết"],
        ['{"score": 1.0, "goal_complete": false, "reason": "ok"}'] * 12,
        max_steps=3,
    )
    agent.run()
    assert len(agent.memory) <= 3


def test_tool_khong_ton_tai_bi_bat_chu_khong_lam_sap():
    agent = _agent(
        ['["b1"]',
         '{"tool": "tool_bia_dat", "args": {}, "answer": null}',
         '["b2"]',
         '{"tool": null, "args": {}, "answer": "xong"}',
         "tổng kết"],
        ['{"score": 0.0, "goal_complete": false, "reason": "tool lạ"}',
         '{"score": 1.0, "goal_complete": true, "reason": "ok"}'],
        max_steps=3,
    )
    agent.run()
    assert "không tồn tại" in agent.memory[0]["observation"]


# ============================================================ Memory

def test_bo_nho_ghi_ra_file_json_hop_le(bo_nho_tam):
    agent = _agent(
        ['["Tra chính sách ăn uống"]',
         '{"tool": "get_policy", "args": {"category": "an_uong"}, "answer": null}',
         "tổng kết"],
        ['{"score": 1.0, "goal_complete": true, "reason": "ok"}'],
        max_steps=2,
        goal="mục tiêu thử",
    )
    agent.run()

    duong_dan = bo_nho_tam / "agent_memory.json"
    assert duong_dan.exists()

    data = json.loads(duong_dan.read_text(encoding="utf-8"))
    assert data["goal"] == "mục tiêu thử"
    assert data["steps"][0]["step"] == 1
    assert data["steps"][0]["tool"] == "get_policy"


def test_BO_NHO_MANG_DU_LIEU_BUOC_TRUOC_SANG_BUOC_SAU():
    """Lời tuyên bố cốt lõi của Cấp 4. Đỏ ở đây nghĩa là Memory chỉ để trang trí.

    Bước 1 gọi một tool trả về con số. Bước 2 phải NHÌN THẤY con số đó trong
    prompt — nếu không, agent không thể trừ dần ngân sách qua từng đơn, và Cấp 4
    không hơn gì Cấp 3 chạy nhiều lần.
    """
    provider = ScriptedProvider([
        '["Tra chính sách", "Kết luận"]',
        '{"tool": "get_policy", "args": {"category": "an_uong"}, "answer": null}',
        '{"tool": null, "args": {}, "answer": "Đã đủ căn cứ."}',
        "tổng kết cuối",
    ])
    agent = AutonomousAgent(
        "Duyệt đơn tồn", max_steps=2, provider=provider,
        judge_provider=ScriptedProvider(
            ['{"score": 1.0, "goal_complete": false, "reason": "ok"}'] * 4),
    )
    agent.run()

    quan_sat_buoc_1 = agent.memory[0]["observation"]
    prompt_buoc_2 = provider.prompts_seen[2]
    assert quan_sat_buoc_1[:40] in prompt_buoc_2, \
        "prompt bước 2 KHÔNG chứa kết quả của bước 1 — bộ nhớ đứt gãy"


def test_khong_de_xuat_lai_loi_goi_da_thuc_hien():
    agent = _agent([], [])
    agent.memory = [
        {"step": 1, "subtask": "s", "tool": "get_policy",
         "args": {"category": "an_uong"}, "observation": "o", "score": 1.0, "reason": "r"},
        {"step": 2, "subtask": "s", "tool": "get_policy",
         "args": {"category": "an_uong"}, "observation": "o", "score": 1.0, "reason": "r"},
    ]
    assert agent._executed_calls_digest().count("get_policy") == 1, "lời gọi trùng phải gộp"


def test_bo_nho_rong_van_dung_dinh_dang():
    agent = _agent([], [])
    assert "chưa có bước nào" in agent._memory_digest()
    assert "chưa gọi tool nào" in agent._executed_calls_digest()
