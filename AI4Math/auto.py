#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import argparse
import datetime
import logging
import asyncio
from typing import List, Dict, Any
from tqdm import tqdm
from dotenv import load_dotenv

# 导入 OpenAI
import openai
from openai import OpenAI

# 导入你提供的模块
from arxiv_retriever import ArxivMathPaperRetriever
from extract_latex_text import ArxivLatexExtractor

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("MathKG_Builder")

# ==========================================
# DEFINING THE PROMPT
# ==========================================

SYSTEM_PROMPT_MKG = r"""
**Role:** You are a "Mathematical Knowledge Graph Engineer". Your task is to extract a structured JSON dataset from the provided LaTeX paper to evaluate AI reasoning capabilities, specifically distinguishing between **High-Level Strategy** and **Low-Level Execution**.

-----

## Extraction Protocol

### Phase 1: Problem Definition ($C_{global}$)

Extract the static constraints required to define the problem setup.

1.  **Global Context**: Extract Key Definitions ($\mathcal{D}$) and Assumptions ($\mathcal{A}$) necessary for comprehension.
2.  **Main Goal**: Identify the central mathematical assertion to be proved.
      * **CRITICAL CONSTRAINT (Masking)**: You must define the **Target Object** (LHS) and its dependencies, but you must **MASK** the final explicit bound, rate, or constant (RHS) to prevent data leakage.
      * *Bad Example:* "Prove $||u|| \le C \cdot T^{-1}$."
      * *Good Example:* "Derive an upper bound for error $||u||$ depending on time $T$ and dimension $d$."
      * **Spoiler Naming (FORBIDDEN):** Do NOT mention "Theorem 1.1" or "Main Theorem". Just state the mathematical assertion.

### Phase 2: The Planning Oracle (Strategy)

Extract the high-level roadmap.

  * **CRITICAL CONSTRAINT**: This section acts as a *hint* for retrieval. It must contain **ZERO** specific citations, lemma numbers, or theorem names.

1.  **Strategic Rationale**: A single summary sentence explaining the high-level methodological approach (Diagnosis + Methodology).
2.  **Roadmap**: A sequence of **State Transitions**.
      * *Format:* "Given [Previous State/Context], establish [Target Intermediate Condition]."
      * *Focus:* Describe *what* needs to be proved next, not *how* (which specific tool) to prove it.

### Phase 3: The Execution Ground Truth (Tactics)

For each step in the roadmap, identify the specific mathematical **Tools** used.

1.  **Pure Derivation**: If the step involves pure algebra, calculus, or logic without referencing named theorems, leave `key_tools` as an empty list `[]` and describe the operation in `description`.
2.  **Tool Extraction Rules**:
      * **Type A: External Citation** (Relies on a result explicitly cited in the bibliography)
          * **ID Resolution**: You MUST resolve the raw bracket number (e.g., `[14]`) to the **Author-Year** or **arXiv ID** found in the References section (e.g., "Chen et al. (2023)" or "arXiv:2305.xxxx").
          * **Statement**: Copy the formula *only if* it is explicitly written in the main text. If the author implies it (e.g., "By [14]") without writing the formula, set `statement_latex` to `"NOT_STATED"`.
      * **Type B: Internal/Standard** (Any tool defined in the paper OR standard math theorems)
          * *Scope:* Includes Internal Lemmas (e.g., "Lemma 3.2"), Specific Equations (e.g., "Eq. 5"), or Standard Theorems (e.g., "Young's Inequality", "Gronwall's Lemma").
          * **Statement**: The **Full LaTeX Statement** of the lemma/formula as applied in this step.

-----

## Output Format (JSON)

Output **only** the following valid JSON structure. Ensure all backslashes in LaTeX strings are properly escaped (e.g., `\\nabla`).

```json
{
  "metadata": {
    "paper_id": "String (e.g., arXiv ID)",
    "paper_title": "String"
  },
  "phase_1_problem": {
    "global_context_latex": "String (Definitions & Assumptions)",
    "main_goal_latex": "String (Target defined, Final Answer masked)"
  },
  "phase_2_planning_oracle": {
    "strategic_rationale": "String",
    "roadmap_steps": [
      {
        "step_id": 1,
        "sub_goal_description": "String (State transition: Given A, derive B)"
      },
      {
        "step_id": 2,
        "sub_goal_description": "String"
      }
    ]
  },
  "phase_3_execution_ground_truth": {
    "step_details": [
      {
        "target_step_id": 1,
        "description": "String (Derivation logic summary)",
        "key_tools": [
          {
            "tool_type": "External Citation", 
            "citation_id": "String (Resolved: 'Author-Year' or 'arXiv ID')", 
            "statement_latex": "String (The formula found in text, or 'NOT_STATED')"
          },
          {
            "tool_type": "Internal/Standard",
            "statement_latex": "String (Full formula used in this step)"
          }
        ]
      },
    ]
  }
}
"""

class MathKGPipeline:
    def __init__(self, output_dir: str, model_name: str = "gpt-4o"):
        self.output_dir = output_dir
        self.model_name = model_name
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # Initialize paths
        self.retrieved_papers_path = os.path.join(output_dir, "raw_arxiv")
        self.latex_dataset_path = os.path.join(output_dir, "latex_source")
        self.final_json_path = os.path.join(output_dir, "math_knowledge_graph.json")
        
        os.makedirs(output_dir, exist_ok=True)

    def step_1_retrieve_papers(self, year: int, month: int, category: str, max_results: int):
        """
        Uses ArxivMathPaperRetriever to get paper metadata.
        """
        logger.info(">>> STEP 1: Retrieving papers from arXiv...")
        start_time = datetime.datetime(year, month, 1)
        retriever = ArxivMathPaperRetriever(start_time, category=category)
        
        # Save dataset to disk
        retriever.save_dataset(output_path=self.retrieved_papers_path, max_results=max_results)
        logger.info(f"Papers retrieved and saved to {self.retrieved_papers_path}")

    def step_2_extract_latex(self):
        """
        Uses ArxivLatexExtractor to download source and extract main .tex content.
        """
        logger.info(">>> STEP 2: Downloading and extracting LaTeX source...")
        
        # Initialize extractor with the path from Step 1
        extractor = ArxivLatexExtractor(dataset_path=self.retrieved_papers_path)
        
        # Build the full text dataset (download source, unzip, find main.tex, clean comments)
        # Using a small batch size to save progress frequently
        extractor.build_full_text_dataset(
            output_path=self.latex_dataset_path,
            batch_size=5, 
            processes=2, # Adjust based on CPU
            overwrite=True
        )
        logger.info(f"LaTeX source extracted to {self.latex_dataset_path}")

    def _call_llm_extraction(self, paper_id: str, title: str, latex_content: str) -> Dict:
        """
        Calls OpenAI API to process the LaTeX content into JSON.
        """
        user_prompt = f"""
        Here is the LaTeX source code of a mathematics paper.
        
        METADATA:
        ID: {paper_id}
        Title: {title}
        
        LATEX CONTENT (Truncated if too long):
        ```latex
        {latex_content[:100000]} 
        ```
        
        Please extract the Knowledge Graph JSON according to the System Protocol.
        """

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT_MKG},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.2 
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as e:
            logger.error(f"Error processing paper {paper_id}: {e}")
            return None

    def step_3_generate_knowledge_graph(self):
        """
        Iterates through the extracted LaTeX dataset and uses LLM to generate the KG JSON.
        """
        logger.info(">>> STEP 3: Generating Knowledge Graph via LLM...")
        
        from datasets import load_from_disk
        
        if not os.path.exists(self.latex_dataset_path):
            logger.error("LaTeX dataset not found. Run Step 2 first.")
            return

        dataset = load_from_disk(self.latex_dataset_path)
        logger.info(f"Loaded {len(dataset)} papers for processing.")
        
        results = []
        
        # Check if we have existing results to resume
        if os.path.exists(self.final_json_path):
            try:
                with open(self.final_json_path, 'r', encoding='utf-8') as f:
                    results = json.load(f)
                    existing_ids = {r['metadata']['paper_id'] for r in results}
                    logger.info(f"Found {len(results)} existing records. Resuming...")
            except:
                existing_ids = set()
        else:
            existing_ids = set()

        for paper in tqdm(dataset, desc="LLM Extraction"):
            p_id = paper.get('id', 'unknown')
            p_title = paper.get('title', 'No Title')
            p_text = paper.get('full_text', '')
            
            if not p_text or len(p_text) < 500:
                logger.warning(f"Skipping {p_id} (Text too short or empty)")
                continue
            
            if p_id in existing_ids:
                continue

            # Process with LLM
            kg_json = self._call_llm_extraction(p_id, p_title, p_text)
            
            if kg_json:
                # Add/Overwrite metadata just in case LLM hallucinated the ID
                if 'metadata' not in kg_json:
                    kg_json['metadata'] = {}
                kg_json['metadata']['paper_id'] = p_id
                kg_json['metadata']['paper_title'] = p_title
                
                results.append(kg_json)
                
                # Save incrementally
                with open(self.final_json_path, 'w', encoding='utf-8') as f:
                    json.dump(results, f, indent=2, ensure_ascii=False)

        logger.info(f"Pipeline Complete. Data saved to {self.final_json_path}")


def main():
    parser = argparse.ArgumentParser(description="Automated Math Knowledge Graph Construction Pipeline")
    parser.add_argument("--output", type=str, default="math_kg_output", help="Output directory")
    parser.add_argument("--year", type=int, default=2023, help="Arxiv Year")
    parser.add_argument("--month", type=int, default=1, help="Arxiv Month")
    parser.add_argument("--category", type=str, default="math.OC", help="Arxiv Category (e.g., math.OC, math.ST)")
    parser.add_argument("--max-papers", type=int, default=10, help="Max papers to retrieve")
    parser.add_argument("--model", type=str, default="gpt-4o", help="Model to use (gpt-4o or o3-mini)")
    parser.add_argument("--skip-retrieve", action="store_true", help="Skip Step 1 (Retrieval) if data exists")
    parser.add_argument("--skip-extract", action="store_true", help="Skip Step 2 (LaTeX Extraction) if data exists")
    
    args = parser.parse_args()
    
    pipeline = MathKGPipeline(output_dir=args.output, model_name=args.model)
    
    # Execution Flow
    if not args.skip_retrieve:
        pipeline.step_1_retrieve_papers(args.year, args.month, args.category, args.max_papers)
    
    if not args.skip_extract:
        pipeline.step_2_extract_latex()
        
    pipeline.step_3_generate_knowledge_graph()

if __name__ == "__main__":
    main()