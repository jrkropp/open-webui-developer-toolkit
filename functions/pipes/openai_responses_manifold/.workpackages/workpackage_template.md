> **Agent instruction (read first):**
>
> * Treat this workpackage as the **single source of truth** for this task.
> * Keep the checklist below up to date: change `[ ]` → `[x]` as you complete tasks, and add new items when you discover more work.
> * Update placeholders (`{{LIKE_THIS}}`) with concrete details as you learn them.
> * Prefer small, incremental commits aligned to checklist items.
> * If you must change the plan, **update this document first**, then the code.

---

## Work Package Checklist

* [ ] {{CHECK_TASK_1_SUMMARY}}
* [ ] {{CHECK_TASK_2_SUMMARY}}
* [ ] {{CHECK_TASK_3_SUMMARY}}
* [ ] {{CHECK_TASK_4_SUMMARY}}
* [ ] {{CHECK_TASK_5_SUMMARY}}

> **Agent note:**
> Add or remove checklist items as needed. Keep brief status notes inline, e.g.:
> `- [x] {{CHECK_TASK_1_SUMMARY}} — {{SHORT_STATUS_OR_COMMIT_REF}}`

---

# {{WORKPACKAGE_TITLE}}

## 1. Objective

**Goal:**
{{OBJECTIVE_GOAL}}

You will:

* {{OBJECTIVE_SUBTASK_1}}
* {{OBJECTIVE_SUBTASK_2}}
* {{OBJECTIVE_SUBTASK_3}}

The result should:

* {{RESULT_CRITERION_1}}
* {{RESULT_CRITERION_2}}

---

## 2. Context (What you are starting from)

{{CONTEXT_CURRENT_STATE}}

Examples of what to capture here (replace with actual content):

* Existing structure: {{CONTEXT_EXISTING_STRUCTURE}}
* Current behavior / expectations: {{CONTEXT_BEHAVIOR}}
* Known issues / pain points: {{CONTEXT_PAIN_POINTS}}
* Hard constraints (APIs, platforms, consumers): {{CONTEXT_CONSTRAINTS}}

---

## 3. Target architecture / structure (ideal)

{{TARGET_ARCHITECTURE_SUMMARY}}

> **Agent instruction:**
>
> * Keep this section in sync with reality.
> * If the design changes while coding, update this section and the file tree below.

```text
{{PROJECT_ROOT}}/
  {{SRC_ROOT}}/
    {{LAYER_OR_MODULE_1}}/
    {{LAYER_OR_MODULE_2}}/
    {{LAYER_OR_MODULE_3}}/
  {{TEST_ROOT}}/
    {{TEST_STRUCTURE}}
  {{SCRIPTS_OR_TOOLS}}/
    {{SCRIPT_FILES}}
```

---

## 4. Design (for this workpackage)

### 4.1 Design goals

* {{DESIGN_GOAL_CLARITY}}
* {{DESIGN_GOAL_MAINTAINABILITY}}
* {{DESIGN_GOAL_SCALABILITY}}

### 4.2 Key components / modules

* {{COMPONENT_1_NAME}} — {{COMPONENT_1_ROLE}}
* {{COMPONENT_2_NAME}} — {{COMPONENT_2_ROLE}}
* {{COMPONENT_3_NAME}} — {{COMPONENT_3_ROLE}}

### 4.3 Key flows / pipelines

* {{FLOW_1_NAME}} — {{FLOW_1_STEPS}}
* {{FLOW_2_NAME}} — {{FLOW_2_STEPS}}

### 4.4 Open questions / decisions

* {{OPEN_QUESTION_1}}
* {{OPEN_QUESTION_2}}

> **Agent instruction:**
> If you answer a question or make a design decision, replace the placeholder with the final decision and (optionally) a brief rationale.

---

## 5. Implementation & notes for agents

{{IMPLEMENTATION_NOTES}}

Example things to put here (as placeholders to fill):

* {{CODING_STANDARDS_OR_STYLE}}
* {{TESTING_REQUIREMENTS}}
* {{PERFORMANCE_OR_SECURITY_NOTES}}
