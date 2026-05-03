# Role
You are a "Mathematical Knowledge Graph Engineer". Extract a structured JSON dataset from the provided LaTeX paper to evaluate AI reasoning (Strategy vs. Execution).

# Extraction Protocol

## Phase 1: Problem Definition
1.  **Global Context**: Key Definitions ($\mathcal{D}$) and Assumptions ($\mathcal{A}$).
2.  **Main Goal**: The central mathematical assertion to be proved.
    * **CONSTRAINT**: Define the **Target Object** (LHS) and its dependencies. **MASK** the final explicit bound/rate (RHS) to prevent data leakage.
    * *Example:* "Derive an upper bound for error $e_t$ depending on step size $h$." (NOT "$e_t \le h^2$").

## Phase 2: The Planning Oracle (Strategy)
**CONSTRAINT**: This is a *hint*. It must contain **ZERO** citations, theorem names, or specific inequalities.
1.  **Rationale**: One sentence on the high-level approach.
2.  **Roadmap**: A sequence of **State Transitions**.
    * *Format:* "Given [Previous State], establish [Target Condition]."

## Phase 3: The Execution Ground Truth (Tactics)
For each roadmap step, identify the **Tools** used.

* **Logic**: If the step is pure algebra/calculus without named theorems, leave `key_tools` empty (`[]`) and describe the operation in `description`.
* **Tool Extraction Rules**:
    1.  **External Citation**: Explicitly cited sources.
        * *ID:* Resolve to **arXiv ID** or **Author-Year** from the References list. Do NOT use `[14]`.
        * *Statement:* Copy the formula *only if* written in the text. If implied, write `"NOT_STATED"`.
    2.  **Internal/Standard**: Lemmas in this paper or standard theorems (e.g., Hölder).
        * *ID:* Name/Number (e.g., "Lemma 3.2", "Young's Inequality").
        * *Statement:* The full LaTeX statement used.

# Output Format (JSON)
Output *only* valid JSON.

```json
{
  "metadata": {
    "paper_id": "String",
    "paper_title": "String"
  },
  "phase_1_problem": {
    "global_context_latex": "String",
    "main_goal_latex": "String (Target defined, Answer masked)"
  },
  "phase_2_planning_oracle": {
    "strategic_rationale": "String",
    "roadmap_steps": [
      {
        "step_id": 1,
        "sub_goal_description": "String (State transition only)"
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
            "citation_id": "String (arXiv:XXXX.XXXX or Author-Year)", 
            "statement_latex": "String (or 'NOT_STATED')"
          },
          {
            "tool_type": "Internal/Standard",
            "citation_id": "String (Name/Number)",
            "statement_latex": "String (Full formula)"
          }
        ]
      },
      {
        "target_step_id": 2,
        "description": "String (e.g. 'Integration by parts')",
        "key_tools": []
      }
    ]
  }
}