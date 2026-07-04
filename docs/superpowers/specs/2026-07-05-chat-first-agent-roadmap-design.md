# Chat-First Agent — Product Roadmap & Design

**Date:** 2026-07-05
**Status:** Design approved (brainstorm complete) — ready for per-phase planning
**Author:** brainstormed with the user (internship deliverable for an Australian
e-commerce brand)
**Scope note:** This is a *roadmap* spec spanning several independent subsystems.
It defines the vision, the invariants, and the phase breakdown. **Each phase gets
its own spec + implementation plan when it is built** — the same way the
canonical-foundation redesign (Phases 1–3) was done. Nothing here authorises
building all of it in one pass.

---

## 1. Why

Two forces converge into one product direction:

1. The **BYOD redesign** ([2026-06-26 intelligence-layer spec], Phases 1–3 shipped)
   made the data layer client-agnostic: a canonical `orders`/`order_items`
   contract, an Instacart demo adapter, and an ingestion pipeline with a
   malfunction firewall. The tools, however, are *still bolted to Instacart's
   columns* — the engine can't yet fire on the canonical shape.
2. The **product vision** (this doc): the company runs this tool on a *client's*
   dataset. The right shape for that is **not** a rigid multi-graph dashboard —
   it's a **single chat window that is the whole app**: an agent with tools at its
   disposal that answers known questions with the right tool, answers novel
   questions by computing real numbers, and *learns* reusable actions over time.

These are the same road. The chat-first product literally cannot exist until the
tools run on canonical data. So Phase 4 (wiring) is the first mile of the vision,
not a detour from it.

**This is a real internship deliverable, not a portfolio toy.** Priorities, in
order: **trust** (every number deterministic, never hallucinated), **works on the
client's real data**, **production-ready**, then features.

---

## 2. The trust invariant (must survive every phase)

> The LLM chooses *what to do* and *narrates*. It never invents a business number.
> Every figure the user sees is computed deterministically by code over real data.

This is the professional backbone of the product. It is why "the agent writes and
runs new code at runtime" was **rejected**, and why the out-of-box path is a
*constrained query interface*, not freeform code execution. Any phase that would
break this invariant is out of scope.

---

## 3. Vision in one picture

A chat window. The user types anything. The agent:

- runs a **saved recipe** if the question matches one it has learned, else
- calls a **specific tool** if the question maps to a known intent, else
- runs the **multi-step goal loop** (`run_reflexive`) for a broad objective, else
- uses the **grounded data-query tool** to compute a real answer to a novel question.

After a good novel answer, the agent offers to **save it as a reusable action**
(a recipe) — that is how it "gets smarter over time," with no new code executed.

A single collapsible **"Full numbers"** panel is available for anyone who wants to
see the underlying figures without asking. The 5-tab dashboard is retired.

The whole thing runs on a **production LLM backend** selected by config — free
Gemini keys for development, a company-billed enterprise endpoint in production.

---

## 4. Decisions locked (brainstorm 2026-07-05)

| Question | Decision | Why |
|---|---|---|
| What does "makes a new tool" mean? | **Save reusable recipes** (named parameterised plans over existing tools) — no runtime codegen | Keeps the trust invariant; safe on client data |
| Dashboard fate | **Chat-primary + ONE collapsible "Full numbers" panel** | Matches the vision; still gives a client at-a-glance figures |
| Out-of-box path | **Grounded data-query tool** — a constrained aggregate/filter/correlate interface over canonical tables | Real computed answers; this computation is what a recipe captures |
| Recipe trigger | **User confirms / one click** ("Save this as a reusable action?") | Keeps the recipe library clean and human-controlled |
| Production LLM | **Config-swappable, company-billed backend** — not the user's personal free keys | Personal free-key rotation is a demo hack that exhausts; production needs real limits + data-residency guarantees |
| LLM fix timing | **Right after Phase 4**, before the chat pivot | Chat-first makes the whole app depend on the chat; harden it first |

---

## 5. Root cause: why the chat quota exhausts today

- `generate()` (text/reasoning calls) rotates the full `LLM_ARSENAL` and **fails
  over Gemini → Claude** on quota. Resilient.
- `call_agent()` (the actual **tool-calling** chat — Gemini automatic function
  calling) is **Gemini-only.** The path that matters most has *no* failover.

In a chat-first app, *everything* goes through tool-calling, so this is a single
point of failure that will hit under real demo load. The fix (Phase 4.5) is to make
the **tool-calling loop provider-agnostic** (wire Claude tool-use into the chat, not
just narration) and make the backend **config-selectable** so production can point
at Vertex AI / Amazon Bedrock / a company API key with no code change.

**Production backend is not chosen yet** (company's cloud access is unknown). The
design requirement is only that the abstraction be clean enough to swap by config.
Given the Australian client and that the model sees *their customer data*, the
professional target is an enterprise endpoint (Vertex AI or Bedrock) for regional
data-residency and no-training guarantees; the simplest fallback is one
company-billed direct API key.

---

## 6. Phase breakdown

Each phase ships independently and leaves the app working. Order is deliberate:
plumbing → reliability → minimal degradation/upload → the visible pivot → the
intelligence unlocks.

### Phase 4 — Re-anchor consumers + wire canonical data
Retire the `get_app_data()` Instacart special path; load the canonical demo (or an
upload) into session_state; renormalise scoring over *available* levers; dynamic
sidebar sliders (one per active lever); churn switches to `recency_days`; rebuild
committed artifacts to canonical shape. *No visible chat change yet.* Already the
planned next step; clean seams already exist (`build_canonical`, `ValidationResult`,
`mapping_store`, reader file-like support).

### Phase 4.5 — Provider-agnostic tool loop + config-swappable backend
Make `call_agent` (the tool-using chat) fail over Gemini → Claude, reusing/extending
`providers.py`. Introduce a single config setting selecting the LLM backend
(dev free keys → prod enterprise endpoint / company key) with **no code change** to
swap. Fixes the quota death before the app depends entirely on chat.

### Phase 5 — Degradation, MINIMAL
The agent states, *in chat*, when a lever or tool can't run on the current dataset
("I can't compute reorder rate — your upload has no product-line data"). No
elaborate per-tab empty-state cards — those die with the dashboard. Just enough that
nothing silently breaks or lies.

### Phase 6 — Upload + mapping-confirm UI, MINIMAL
The front-end for the Phase-3 ingestion backend: upload a CSV/Excel, the LLM
proposes column mappings, the user confirms before any analysis runs. Lives in the
sidebar or an onboarding step. Functional, not fancy.

### Phase 7 — Chat-first shell
Chat becomes the landing screen. The 5 analytical tabs collapse into one optional
**"Full numbers"** panel (tools already render charts/tables inline, so this is
mostly re-layout). Implement the **dispatch ladder** per message:
**match saved recipe → known tool → multi-step goal (`run_reflexive`) → grounded
query.** The recipe library sits *in front of* dispatch so a learned question runs
directly, deterministically, without re-reasoning.

### Phase 8 — Grounded data-query tool
One new tool: a **constrained** interface to compute aggregations, filters, and
correlations over the canonical `orders` / `order_items` / feature matrix. NOT
arbitrary code — a bounded query surface whose every output is a real computed
number. This is the "out-of-box" escape hatch that lets the agent answer questions
no purpose-built tool covers.

### Phase 9 — Recipes
After the grounded query tool answers a novel question well, the agent offers to
**save it as a named reusable action**. A recipe stores the parameterised plan
(which tool/query + arguments), not raw data or generated code. Saved recipes
appear first in the dispatch ladder (Phase 7) and can be re-run on demand. A
best-effort JSON store like the existing `.app_state/*.json` stores.

---

## 7. What is explicitly OUT of scope

- Runtime code generation / self-executing tools (breaks the trust invariant).
- Choosing/standing up the final production LLM host now (unknown; config-swappable
  abstraction only).
- Elaborate per-surface degradation cards (the dashboard they targeted is retired).
- Auto-saving every novel answer as a recipe (chosen: user-confirmed, one-click).
- Similarity-based auto-recipe-on-repeat (more moving parts than the timeline allows;
  can revisit after Phase 9).

---

## 8. Success criteria

- A client can upload their own orders and hold a useful conversation with the agent
  without any crash or fabricated number.
- Known questions hit the right tool; novel questions get a real computed answer.
- A good novel answer can be saved and re-run as a one-click recipe.
- The chat keeps working when Gemini's free quota is exhausted.
- Switching to a production LLM backend is a config change, not a code change.

---

## 9. Build order & planning

`4 → 4.5 → 5 → 6 → 7 → 8 → 9`. Phase 4 is the immediate actionable work and is
planned next. Each subsequent phase gets its own spec + implementation plan when it
is reached. This roadmap is the single source of truth for *why* and *in what order*;
the per-phase docs own the *how*.

[2026-06-26 intelligence-layer spec]: ./2026-06-26-intelligence-layer-byod-design.md
