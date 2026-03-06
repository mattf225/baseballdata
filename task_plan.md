# B.L.A.S.T. MLB Automation Task Plan

## Phase 1: Blueprint (Vision & Logic)
- [x] Initial Discovery Questions Answered (MLB Pivot)
- [x] Data-First Rule: Define JSON Data Schema (Inputs/Payload) in `gemini.md`
- [x] Research: Found `pybaseball` for model data and `The Odds API` for live prop odds.
- [x] Write `implementation_plan.md` for the technical realization of the MLB architecture.

## Phase 2: Link (Connectivity)
- [x] Refactor Relational Database (Supabase PostgreSQL schema for MLB tables)
- [x] Verification: Gather API keys and test connections to The Odds API and pybaseball
- [x] Handshake: Build minimal scripts in `tools/` to verify services respond correctly
- [x] Notification Handshake: Test Discord webhook connections (Done)

## Phase 3: Architect (The 3-Layer Build)
- [x] Layer 1: Architecture SOPs written in `architecture/`
   - [x] Data Ingestion SOP (pybaseball)
   - [x] EV Calculation SOP
   - [x] Notification SOP
- [x] Layer 2: Routing Logic (Python orchestrator)
- [x] Layer 3: Deterministic Python scripts in `tools/` 

## Phase 4: Stylize (Refinement & UI)
- [x] Payload Refinement: Format output blocks for Discord into a clean, analytical format for HRs, Strikeouts, etc.
- [x] Feedback: Present stylized results to the user for feedback

## Phase 5: Trigger (Deployment)
- [x] Cloud Transfer: Move logic from local testing to production environment (e.g. cloud cron)
- [x] Automation: Set up execution triggers based on MLB schedules and live odds refreshing
- [x] Documentation: Finalize Maintenance Log in `gemini.md`
