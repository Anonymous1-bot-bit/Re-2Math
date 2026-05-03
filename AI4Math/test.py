import json
import os
import re
import asyncio
import logging
import argparse
from typing import List, Dict, Any, Optional

# 第三方库
from openai import AsyncOpenAI, APIError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from tqdm.asyncio import tqdm

# ================= CONFIGURATION =================

# 建议在环境变量中设置 API KEY，或者在此处填入
API_KEY = os.getenv("OPENAI_API_KEY", "YOUR_API_KEY_HERE")
BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL_NAME = "gpt-4-turbo-preview"  # 务必使用支持 JSON Mode 的强推理模型

# 并发控制：同时发起的请求数量 (根据你的 API Rate Limit 调整)
MAX_CONCURRENCY = 5 

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pipeline.log", encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# 初始化客户端
client = AsyncOpenAI(api_key=API_KEY, base_url=BASE_URL)

# ================= ENHANCED PROMPT TEMPLATES =================

SYSTEM_PROMPT = """
You are a "Mathematical Knowledge Graph Engineer" and an expert in Formal Mathematics.
Your role is to deconstruct complex LaTeX proofs into structured, machine-readable datasets for AI training.

## CORE DIRECTIVES
1. **Precision**: Distinguish between a "High-Level Strategy" (What to prove) and "Low-Level Execution" (How to prove it).
2. **LaTeX Safety**: You MUST double-escape all backslashes in your JSON output. 
   - Wrong: "\\nabla" (Invalid JSON)
   - Right: "\\\\nabla" (Valid JSON)
3. **No Markdown**: Output raw JSON only. No ```json blocks.
"""

# Mode A: "The Tactician" (Fill in the details for a given plan)
PROMPT_TEMPLATE_MODE_A = """
## Input Context
You are given a mathematical problem ($C_{{global}}$) and a fixed high-level roadmap (The Planning Oracle).
Your task is to act as the **Execution Engine**. You must determine the specific mathematical tactics and tools used to achieve each step in the roadmap.

### Phase 1: Problem Definition
{phase_1_json}

### Phase 2: Strategic Plan (The Roadmap)
{phase_2_json}

## Task: Extract Execution Ground Truth (Phase 3)
For EACH step in the `roadmap_steps` provided above, generate the `step_details`.

### Strict Analysis Protocol:
1.  **Gap Analysis**: Look at the `sub_goal_description`. What implies the transition from the previous state to this goal?
2.  **Tool Identification**:
    * **Named Theorems**: If the proof uses a standard result (e.g., "Sobolev Embedding", "Gronwall's Lemma"), you MUST formulate its statement as applied here.
    * **Paper-Specific Lemmas**: If the proof relies on a prior lemma in the paper (e.g., "Lemma 3.1"), explicitly state what that lemma asserts.
    * **Citation Resolution**: If the text says "By [12]", you MUST verify the References (if provided in context) or use your internal knowledge to resolve it to "Author (Year)" or "Theorem Name".
3.  **Derivation Logic**: Briefly summarize the algebraic manipulation (e.g., "Multiply by test function $\\\\phi$ and integrate by parts").

## Output Schema (JSON)
{{
  "phase_3_execution_ground_truth": {{
    "step_details": [
      {{
        "target_step_id": <int, matching the input roadmap>,
        "description": "<String: The tactical derivation logic (e.g., 'Apply Ito isometry to bound the noise term')>",
        "key_tools": [
          {{
            "tool_type": "External Citation",
            "citation_id": "<String: e.g., 'Vaswani et al. (2017)' or '[12]'>",
            "statement_latex": "<String: The specific formula imported from the citation>"
          }},
          {{
            "tool_type": "Internal/Standard",
            "statement_latex": "<String: The FULL LaTeX statement of the theorem/lemma used>"
          }}
        ]
      }}
    ]
  }}
}}
"""

# Mode B: "The Architect" (Design the plan AND the details)
PROMPT_TEMPLATE_MODE_B = """
## Input Context
You are provided with a mathematical problem setup ($C_{{global}}$).
Your task is to reconstruct the **Full Proof Structure**, including the High-Level Strategy (Phase 2) and the Low-Level Tactics (Phase 3).

### Phase 1: Problem Definition
{phase_1_json}

## Task Guidelines

### Phase 2: The Planning Oracle (Strategy)
* **Goal**: Create a roadmap of 3 to 7 logical steps.
* **State Transitions**: Each step should represent a significant change in the mathematical state (e.g., "Establish local existence" $\\to$ "Derive a priori bounds" $\\to$ "Extend to global existence").
* **Strategic Rationale**: Identify the core method used (e.g., "Fixed Point Theorem", "Energy Method", "Induction").

### Phase 3: The Execution Ground Truth (Tactics)
* For each step defined in Phase 2, identify the *specific* inequalities, identities, or theorems required to bridge the gap.

## Output Schema (JSON)
{{
  "phase_2_planning_oracle": {{
    "strategic_rationale": "<String: Summary of the proof method (e.g., 'Bootstrap argument on the energy functional')>",
    "roadmap_steps": [
      {{ 
        "step_id": 1, 
        "sub_goal_description": "<String: State Transition (e.g., 'Construct the approximate solution sequence')>" 
      }}
    ]
  }},
  "phase_3_execution_ground_truth": {{
    "step_details": [
      {{
        "target_step_id": 1, 
        "description": "<String: Tactical logic>",
        "key_tools": [
            {{ "tool_type": "Internal/Standard", "statement_latex": "<String: DOUBLE ESCAPED LATEX>" }}
        ]
      }}
    ]
  }}
}}
"""

# ================= ROBUST UTILS =================

def extract_json_robust(text: str) -> Dict:
    """
    鲁棒的 JSON 提取器，专门处理 LaTeX 转义问题。
    """
    text = text.strip()
    
    # 1. 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 移除 Markdown 代码块标记
    clean_text = re.sub(r"^```(json)?", "", text, flags=re.MULTILINE)
    clean_text = re.sub(r"^```", "", clean_text, flags=re.MULTILINE).strip()
    try:
        return json.loads(clean_text)
    except json.JSONDecodeError:
        pass

    # 3. 正则提取最外层 JSON 对象
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        candidate = match.group(1)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
            
    # 4. LaTeX 救星：尝试修复反斜杠
    # 这是一个危险操作，只有在前面都失败时才尝试
    # 将 \ 替换为 \\，但要小心不要破坏已经转义的 \\
    try:
        # 简单策略：先全部变成双反斜杠，再尝试解析
        # 注意：这无法完美处理所有情况，但在 GPT-4 输出中通常有效
        fixed_text = clean_text.replace("\\", "\\\\")
        # 修正可能出现的四反斜杠 (原文本本身就是 \\ 的情况)
        fixed_text = fixed_text.replace("\\\\\\\\", "\\\\") 
        return json.loads(fixed_text)
    except json.JSONDecodeError:
        # 如果还是失败，截取部分内容抛出异常以便调试
        raise ValueError(f"CRITICAL: Failed to parse JSON. Raw start: {text[:100]}...")

@retry(
    stop=stop_after_attempt(3),             # 最大重试次数
    wait=wait_exponential(multiplier=1, min=2, max=10), # 指数退避
    retry=retry_if_exception_type(Exception) # 任何异常都重试 (包括解析失败)
)
async def run_inference_async(mode: str, data_entry: Dict) -> Dict:
    """
    单次推理任务，包含自动重试逻辑。
    """
    # 准备 Input Context
    phase_1_data = data_entry.get("phase_1_problem", {})
    phase_1_str = json.dumps(phase_1_data, indent=2)

    if mode == "A":
        # Mode A 必须有 Phase 2 数据
        phase_2_data = data_entry.get("phase_2_planning_oracle", {})
        if not phase_2_data:
            raise ValueError(f"Mode A requires 'phase_2_planning_oracle' in input data (Paper ID: {data_entry.get('metadata', {}).get('paper_id')})")
        
        phase_2_str = json.dumps(phase_2_data, indent=2)
        user_content = PROMPT_TEMPLATE_MODE_A.format(
            phase_1_json=phase_1_str, 
            phase_2_json=phase_2_str
        )
        
    elif mode == "B":
        user_content = PROMPT_TEMPLATE_MODE_B.format(
            phase_1_json=phase_1_str
        )
    else:
        raise ValueError("Invalid Mode. Use 'A' or 'B'.")

    try:
        # 调用 OpenAI API
        response = await client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            temperature=0.1, # 保持低温以确保逻辑严谨和格式正确
            response_format={"type": "json_object"} # 强制 JSON 模式
        )
        
        raw_content = response.choices[0].message.content
        
        # 鲁棒解析
        parsed_result = extract_json_robust(raw_content)
        return parsed_result

    except Exception as e:
        # log warning 会被 retry 捕获并重试
        logger.warning(f"Inference failed for {data_entry.get('metadata', {}).get('paper_id')}: {e}. Retrying...")
        raise e

# ================= BATCH PROCESSOR =================

async def process_batch(dataset: List[Dict], output_file: str, mode: str):
    """
    批量并发处理控制器
    """
    results = []
    sem = asyncio.Semaphore(MAX_CONCURRENCY) # 限制并发数

    async def worker(entry):
        async with sem:
            paper_id = entry.get("metadata", {}).get("paper_id", "unknown_id")
            
            result_record = {
                "metadata": entry.get("metadata"),
                "input_mode": mode,
                "status": "pending"
            }

            try:
                # 执行推理
                llm_output = await run_inference_async(mode, entry)
                
                result_record["status"] = "success"
                result_record["model_prediction"] = llm_output
                
                # 保留 Ground Truth (如果原数据中有) 以便后续评估
                result_record["ground_truth_reference"] = {
                    "phase_2": entry.get("phase_2_planning_oracle") if mode == "A" else None,
                    "phase_3": entry.get("phase_3_execution_ground_truth")
                }
                
                return result_record

            except Exception as e:
                logger.error(f"FINAL FAILURE for {paper_id}: {e}")
                result_record["status"] = "failed"
                result_record["error"] = str(e)
                # 失败时也返回记录，保证数据对齐
                return result_record

    # 创建任务列表
    tasks = [worker(entry) for entry in dataset]
    
    print(f"Starting processing {len(dataset)} entries in MODE {mode} with Concurrency={MAX_CONCURRENCY}...")
    
    # 使用 tqdm 显示异步进度条
    results = await tqdm.gather(*tasks)

    # 统计结果
    success_count = sum(1 for r in results if r['status'] == 'success')
    failed_count = len(results) - success_count
    
    logger.info(f"Batch processing complete. Success: {success_count}, Failed: {failed_count}")

    # 保存结果
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Results saved to: {output_file}")
    except IOError as e:
        logger.error(f"Failed to write output file: {e}")

# ================= MAIN ENTRY POINT =================

def main():
    parser = argparse.ArgumentParser(description="Mathematical Knowledge Graph Extraction Pipeline")
    parser.add_argument("--input", required=True, help="Path to input JSON dataset")
    parser.add_argument("--output", required=True, help="Path to save output JSON")
    parser.add_argument("--mode", choices=["A", "B"], default="B", help="Mode A: Tactician (Plan->Tools), Mode B: Architect (Problem->Plan+Tools)")
    
    args = parser.parse_args()

    # 1. 验证输入文件
    if not os.path.exists(args.input):
        logger.error(f"Input file not found: {args.input}")
        return

    # 2. 加载数据
    try:
        with open(args.input, 'r', encoding='utf-8') as f:
            dataset = json.load(f)
            # 兼容单条数据或列表数据
            if isinstance(dataset, dict):
                dataset = [dataset]
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in input file: {args.input}")
        return

    # 3. 运行主循环
    if dataset:
        asyncio.run(process_batch(dataset, args.output, args.mode))
    else:
        logger.warning("Dataset is empty.")

if __name__ == "__main__":
    main()