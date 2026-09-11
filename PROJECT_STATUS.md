# Tandem Project Status

| Phase | Description | Status | Verification / Artifacts |
|---|---|---|---|
| **PHASE 0** | Specification + Architecture Research | **COMPLETED** | `docs/product-spec.md`, `docs/architecture-research.md` |
| **PHASE 1** | Repository Scaffolding + Python Environment | **COMPLETED** | `pyproject.toml`, `.venv` (Python 3.12.10), Playwright Chromium, `Makefile` |
| **PHASE 2** | Core Banking Simulator (Hostile UI) | **COMPLETED** | `simulators/core_bank/` (framesets, tables, fuzzy search, transposed IDs, memos, compliance) |
| **PHASE 3** | Processor & Notice Simulators | Pending | `simulators/processor/`, `simulators/documents/` (failure switch, timeout) |
| **PHASE 4** | Domain Models & Capability Schema | Pending | `tandem/domain/` (Pydantic models, effect classes, commit metadata) |
| **PHASE 5** | SQLite Procedure Ledger | Pending | `tandem/ledger/` (append-only events, WAL mode, state reconstruction) |
| **PHASE 6** | Surface Abstraction | Pending | `tandem/surfaces/` (semantic targets, locator strategy, container guards) |
| **PHASE 7** | Raw Playwright Deterministic Capability | Pending | Direct Playwright execution without LLM |
| **PHASE 8** | Effect Protocol (Precheck -> Guard -> Commit -> Postcheck -> Reconcile) | Pending | `tandem/replay/guards.py`, `precheck.py`, `postcheck.py`, `reconciliation.py` |
| **PHASE 9** | Reg E Workflow State Machine | Pending | `tandem/workflow/reg_e.py`, `deadlines.py` (business day calculation) |
| **PHASE 10**| Crash Recovery | Pending | `PROCESS_KILL_AFTER` injection, recovery test suite |
| **PHASE 11**| Discovery Agent | Pending | `tandem/discovery/agent.py` (controlled browser agent) |
| **PHASE 12**| Discovery Recorder & Capability Compiler | Pending | `tandem/discovery/recorder.py`, `compiler.py` (versioned artifacts) |
| **PHASE 13**| Replay Compiled Artifact (Zero LLM Calls) | Pending | `tandem/replay/executor.py` asserting `llm_call_count == 0` |
| **PHASE 14**| Human Handoff | Pending | `tandem/handoff/coordinator.py`, single-owner lease (`AUTOMATION` vs `HUMAN`) |
| **PHASE 15**| Second Institution + Overlays/Drift | Pending | Second skin simulator, overlay mapping, drift detection |
| **PHASE 16**| Uncertain-Effect Handling | Pending | Dropped connection postcheck/reconciliation, `UNCERTAIN_EFFECT` routing |
| **PHASE 17**| Minimal Operator / Audit UI | Pending | `tandem/api/` (FastAPI + HTML/Jinja audit timeline & handoff) |
| **PHASE 18**| Full Tests (Unit, Integration, E2E) | Pending | Pytest suite covering all 8 scenarios and edge cases |
| **PHASE 19**| CI & Docker | Pending | `.github/workflows/ci.yml`, `Dockerfile`, `docker-compose.yml` |
| **PHASE 20**| Documentation & Demo Script | Pending | `README.md`, `ARCHITECTURE.md`, `DEMO.md`, `SECURITY.md`, `docs/interviewer-questions.md` |
| **PHASE 21**| Final Clean-Room Verification | Pending | Fresh setup, all 8 demos executed, `FINAL_REPORT.md` |

---

## Current Milestones Completed
- [x] Read and extracted complete problem and specification from `Tandem-Problem-and-Solution.pdf`.
- [x] Evaluated ecosystem repositories (browser-use, playwright, pydantic, fastapi, sqlalchemy, temporalio, langgraph).
- [x] Authored `docs/product-spec.md` with explicit problem boundaries and scenario definitions.
- [x] Authored `docs/architecture-research.md`.
