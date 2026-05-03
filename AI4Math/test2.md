# Role
You are a "Mathematical Knowledge Graph Engineer". Your task is to extract a structured JSON dataset from the provided LaTeX paper to evaluate AI reasoning capabilities, specifically distinguishing between **High-Level Strategy** and **Low-Level Execution**.

---

# Extraction Protocol

## Phase 1: Problem Definition ($C_{global}$)
Extract the static constraints required to define the problem setup.

1.  **Global Context**: Extract Key Definitions ($\mathcal{D}$) and Assumptions ($\mathcal{A}$) necessary for comprehension.
2.  **Main Goal**: Identify the central mathematical assertion to be proved.
    * **CRITICAL CONSTRAINT (Masking)**: You must define the **Target Object** (LHS) and its dependencies, but you must **MASK** the final explicit bound, rate, or constant (RHS) to prevent data leakage.
    * *Bad Example:* "Prove $||u|| \le C \cdot T^{-1}$."
    * *Good Example:* "Derive an upper bound for error $||u||$ depending on time $T$ and dimension $d$."
    * **Spoiler Naming (FORBIDDEN):** Do NOT mention "Theorem 1.1" or "Main Theorem". Just state the mathematical assertion.

## Phase 2: The Planning Oracle (Strategy)
**Objective**: Reverse-engineer the "Architect's Blueprint" and the **Logical Dependency Graph** of the proof.

**CRITICAL CONSTRAINT**: This section serves as a *semantic search query* for the tools used in Phase 3. It must contain **ZERO** specific citations (e.g., no "[12]"), theorem names (e.g., no "Gronwall"), or specific constants.

1.  **Strategic Rationale**:
    * Infer the high-level logic connecting the problem's core difficulty (Diagnosis) to the chosen solution path (Methodology).
    * *Example:* "To handle the singularity at the origin, the strategy is to regularize the equation via a cutoff function and then pass to the limit."

2.  **Abstract Roadmap (The Logical DAG)**:
    * Break the proof into a sequence of **Logical Milestones**.
    * **Inference Rule**: If steps are not explicit, deduce them from the proof's flow.
    * **Dependency Tracking**:
        * You must model the proof as a **Directed Acyclic Graph (DAG)**.
        * For each step, identify specific **Previous Step IDs** that are strict logical prerequisites.
        * *Sequential:* If Step 2 modifies Step 1's result, `dependencies = [1]`.
        * *Independent:* If Step 2 starts a new line of reasoning (e.g., proving a helper lemma from scratch), `dependencies = []`.
        * *Synthesis:* If Step 4 combines results from Step 2 and Step 3, `dependencies = [2, 3]`.
    * **Structure per Step**:
        * **Input/Prerequisites**: What previous results (IDs) or assumptions are required?
        * **Target Action**: What abstract operation is performed? (e.g., "Construct a Lyapunov function", "Apply a bootstrap argument")
        * **Output State**: What condition is established for future steps?

### Phase 3: The Execution Ground Truth (Tactics)

For each step in the roadmap, identify the specific mathematical **Tools** used.

1.  **Pure Derivation**: If the step involves pure algebra, calculus, or logic without referencing named theorems, leave `key_tools` as an empty list `[]` and describe the operation in `description`.
2.  **Tool Extraction Rules**:
      * **Type A: External Citation** (Relies on a result explicitly cited in the bibliography)
        * **ID Resolution**: You MUST resolve the raw bracket number (e.g., `[14]`) to the **Author-Year** or **arXiv ID** found in the References section (e.g., "Chen et al. (2023)" or "arXiv:2305.xxxx").
        * **Statement**: 
            * If the author implies the result (e.g., "By [14]") without writing the formula, set `statement_latex` to `"NOT_STATED"`.
            * If the formula **IS** explicitly written, extract the **Full, Self-Contained LaTeX Statement**.
            * **CRITICAL CONSTRAINT (De-referencing)**: Do NOT extract pointers like "Theorem 3.1 in [14]" or "The bound in [12]". You must extract the **actual mathematical content** (e.g., "$||f|| \le C$").
      * **Type B: Internal** (Any tool defined in the paper OR standard math theorems)
        * *Scope:* Includes Internal Lemmas (e.g., "Lemma 3.2"), Specific Equations (e.g., "Eq. 5"), or Standard Theorems (e.g., "Young's Inequality").
        * **ID**: The Name or Number exactly as used in the text.
        * **Statement**: The **Full, Self-Contained LaTeX Statement**.
            * **CRITICAL CONSTRAINT (De-referencing)**: You must **RESOLVE** all context-dependent pointers.
            * *Bad:* "Under Assumption 1, Eq. (5) holds." (Dependent on lookup)
            * *Good:* "If $f$ is L-Lipschitz (Assumption 1 content), then $|f(x)-f(y)| \le L|x-y|$ (Eq. 5 content)."
            * *Action:* Replace "Assumption A" or "Eq. 6" with their actual mathematical content so the statement stands alone.

-----

# Output Format (JSON)

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
        "sub_goal_description": "String (State transition: Given A, derive B)",
        "dependencies": [ ]
      },
      {
        "step_id": 2,
        "sub_goal_description": "String",
        "dependencies": [1]
      },
      {
        "step_id": 3,
        "sub_goal_description": "String",
        "dependencies": [1, 2]
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
            "tool_type": "Internal",
            "citation_id": "String (e.g., 'Lemma 3.2', 'Eq. 5', 'Young\\'s Inequality')",
            "statement_latex": "String (Full formula used in this step)"
          }
        ]
      },
      {
        "target_step_id": 2,
        "description": "String (e.g., 'Integration by parts on the boundary term')",
        "key_tools": []
      }
    ]
  }
}