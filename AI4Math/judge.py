import json
import os
import re
from typing import Dict, Any

# ==========================================
# 1. 配置与 LLM 调用 (Configuration)
# ==========================================

# 请在此处填入您的 API Key 或配置
# os.environ["OPENAI_API_KEY"] = "sk-..."

def call_judge_llm(system_prompt: str, user_prompt: str, model: str = "gpt-4o") -> Dict:
    """
    调用 LLM 作为裁判，并强制要求返回 JSON 格式。
    """
    # ---------------------------------------------------------
    # 真实调用示例 (OpenAI):
    # import openai
    # client = openai.OpenAI()
    # response = client.chat.completions.create(
    #     model=model,
    #     messages=[
    #         {"role": "system", "content": system_prompt},
    #         {"role": "user", "content": user_prompt}
    #     ],
    #     response_format={"type": "json_object"}, # 强制 JSON
    #     temperature=0
    # )
    # return json.loads(response.choices[0].message.content)
    # ---------------------------------------------------------
    
    # [MOCK RETURN FOR DEMO]
    # 这里模拟裁判的返回结果
    print(f"\n[Mock Judge] Judging...")
    return {
        "score": 0.85,
        "reasoning": "The student correctly identified the external citation and derived the bound, but missed one internal lemma regarding the initialization error.",
        "details": [
            {"step_id": 1, "status": "Correct", "comment": "Correctly retrieved Lemma B.2"},
            {"step_id": 2, "status": "Partial", "comment": "Missed the specific Gaussian form"}
        ]
    }

# ==========================================
# 2. 裁判提示词 (Judge Prompts)
# ==========================================

# 评测 Execution (Phase 3) 的 Prompt
JUDGE_PROMPT_EXECUTION = """
You are a strict **Mathematics Examiner**.
Compare the Student's Derivation against the Ground Truth (GT).

**Evaluation Criteria:**
1. **Tool Retrieval (Critical)**: 
   - Did the student identify the correct **External Citations** (e.g., matching arXiv ID or Author-Year)?
   - Did the student identify the correct **Internal/Standard Tools** (functionally equivalent inequalities)?
2. **Derivation Logic**: Is the mathematical logic sound and consistent with the GT steps?
3. **Availability Compliance**: If the GT says a tool is "NOT_STATED", the student should NOT hallucinate a formula.

**Input Data:**
- **Ground Truth Steps**: {gt_json}
- **Student Response**: {student_text}

**Output Format (JSON Only):**
{{
  "steps_analysis": [
    {{
      "step_id": 1,
      "score": 0.0 to 1.0, 
      "retrieval_status": "Hit/Miss/Hallucinated",
      "comment": "..."
    }}
  ],
  "total_score": 0.0 to 1.0,
  "summary": "Brief summary of performance."
}}
"""

# 评测 Planning (Phase 2) 的 Prompt
JUDGE_PROMPT_PLANNING = """
You are a **Strategic Mathematician**.
Compare the Student's Strategic Plan against the Oracle Roadmap.

**Evaluation Criteria:**
1. **Alignment**: Does the student's roadmap follow the same logical "State Transitions" as the Oracle?
2. **Rationale**: Is the high-level diagnosis similar?
3. **No Spoilers**: Did the student avoid hallucinating specific theorem numbers in the planning phase?

**Input Data:**
- **Oracle Roadmap**: {oracle_json}
- **Student Plan**: {student_text}

**Output Format (JSON Only):**
{{
  "alignment_score": 0.0 to 1.0,
  "reasoning": "..."
}}
"""

# ==========================================
# 3. 评测逻辑类 (Judge Logic)
# ==========================================

class MathBenchmarkJudge:
    def __init__(self, input_file="results/benchmark_output.json", output_dir="results"):
        self.input_file = input_file
        self.output_dir = output_dir

    def extract_blocks_from_mode_b(self, text: str) -> Dict[str, str]:
        """
        从 Mode B 的输出中解析 <PLANNING> 和 <EXECUTION> 块。
        """
        planning_match = re.search(r'## Block 1: <PLANNING>(.*?)## Block 2: <EXECUTION>', text, re.DOTALL)
        execution_match = re.search(r'## Block 2: <EXECUTION>(.*)', text, re.DOTALL)
        
        return {
            "planning": planning_match.group(1).strip() if planning_match else "",
            "execution": execution_match.group(1).strip() if execution_match else text # 如果没分块，假设全是 Execution
        }

    def evaluate_paper(self, record: Dict) -> Dict:
        """对单篇论文进行完整评测"""
        paper_id = record['paper_id']
        gt = record['ground_truth']
        
        # --- 1. Evaluate Mode A (With Plan) ---
        print(f"Judging Mode A for {paper_id}...")
        res_a_exec = call_judge_llm(
            system_prompt=JUDGE_PROMPT_EXECUTION.format(
                gt_json=json.dumps(gt['phase_3_execution_ground_truth']),
                student_text=record['mode_a_with_plan']['response']
            ),
            user_prompt="Grade the student's execution."
        )

        # --- 2. Evaluate Mode B (No Plan) ---
        print(f"Judging Mode B for {paper_id}...")
        mode_b_text = record['mode_b_no_plan']['response']
        blocks = self.extract_blocks_from_mode_b(mode_b_text)

        # 2.1 Judge Planning
        res_b_plan = call_judge_llm(
            system_prompt=JUDGE_PROMPT_PLANNING.format(
                oracle_json=json.dumps(gt['phase_2_planning_oracle']),
                student_text=blocks['planning']
            ),
            user_prompt="Grade the student's strategic plan."
        )

        # 2.2 Judge Execution
        res_b_exec = call_judge_llm(
            system_prompt=JUDGE_PROMPT_EXECUTION.format(
                gt_json=json.dumps(gt['phase_3_execution_ground_truth']),
                student_text=blocks['execution']
            ),
            user_prompt="Grade the student's execution."
        )

        return {
            "paper_id": paper_id,
            "scores": {
                "mode_a_execution_score": res_a_exec.get("total_score", 0),
                "mode_b_planning_score": res_b_plan.get("alignment_score", 0),
                "mode_b_execution_score": res_b_exec.get("total_score", 0)
            },
            "details": {
                "mode_a_exec_details": res_a_exec,
                "mode_b_plan_details": res_b_plan,
                "mode_b_exec_details": res_b_exec
            }
        }

    def run(self):
        with open(self.input_file, 'r', encoding='utf-8') as f:
            raw_results = json.load(f)

        judged_results = []
        for record in raw_results:
            judged_results.append(self.evaluate_paper(record))

        # 保存结果
        output_path = os.path.join(self.output_dir, "judge_report.json")
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(judged_results, f, indent=2, ensure_ascii=False)
        
        # 打印简单摘要
        print(f"\n=== Evaluation Summary ===")
        for res in judged_results:
            s = res['scores']
            print(f"Paper: {res['paper_id']}")
            print(f"  Mode A (Exec): {s['mode_a_execution_score']:.2f} (Given Plan)")
            print(f"  Mode B (Plan): {s['mode_b_planning_score']:.2f} (Self Plan)")
            print(f"  Mode B (Exec): {s['mode_b_execution_score']:.2f} (Self Exec)")
            
            # 计算 Planning Gap
            delta = s['mode_a_execution_score'] - s['mode_b_execution_score']
            print(f"  --> Planning Gap (Delta): {delta:.2f}")

# ==========================================
# 4. 运行入口
# ==========================================

if __name__ == "__main__":
    # 确保先运行过 benchmark_runner.py 并生成了 json
    judge = MathBenchmarkJudge()
    judge.run()