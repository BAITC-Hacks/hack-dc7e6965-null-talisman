# HackAlem AI 2026 — Agent Instructions

## Context

This repository is being developed during HackAlem AI 2026.

- Competition date: 23 September 2026
- Development window: 13:00–18:00
- Team size: 3 developers
- Development time: 5 hours

This is a hackathon project.

Our objective is to build the smallest reliable solution that satisfies the official task and evaluation criteria.

Do not optimize for production-scale architecture.
Optimize for:
1. Task requirements
2. Evaluation score
3. Working end-to-end functionality
4. Reliability
5. Easy setup and testing
6. Clear demo
7. Additional features

---

## CRITICAL HACKATHON RULES

### Development repository

This repository is the official and primary development repository.

All important implementation work must exist here.

Do not move primary development to another repository.

Do not keep essential code only locally.

### Development timing

Core functionality corresponding to the hackathon task must be implemented during the official competition period.

Do not present previously completed products or prebuilt task solutions as newly developed work.

Reusable infrastructure, libraries, templates and development tooling may be used where allowed.

### Hourly progress

The team must have a verifiable intermediate result after every competition hour.

Prefer small, functional increments that can be committed regularly.

Do not spend multiple hours creating a large uncommitted implementation.

### Third-party components

All meaningful third-party components must be disclosed, including:

- libraries
- APIs
- models
- datasets
- templates
- open-source code
- external services

Never present third-party work as original team work.

### AI tools

AI coding tools and AI agents are allowed.

AI may assist with:

- implementation
- debugging
- testing
- architecture
- UI
- data processing
- AI pipelines
- documentation

Generated code must remain understandable and maintainable by the team.

---

# DEVELOPMENT BEHAVIOR

## Before coding

Before implementing a significant feature:

1. Read the official task specification.
2. Identify which requirement or scoring criterion the feature satisfies.
3. Determine the smallest implementation that satisfies it.
4. Check whether another developer is already working on the same area.
5. Preserve existing working functionality.

If requirements are unclear, do not invent major product requirements.

Prefer asking for clarification or implementing the safest minimal interpretation.

---

## Do not overengineer

Avoid unnecessary:

- microservices
- message brokers
- distributed architecture
- complicated design patterns
- excessive abstraction
- premature optimization
- unnecessary databases
- unnecessary dependencies
- major refactors during the final stages

Prefer simple architecture.

A simple feature that definitely works is better than an advanced feature that may fail.

---

## End-to-end first

Prioritize one complete user scenario:

USER INPUT
→ PROCESSING
→ CORE LOGIC / AI
→ RESULT
→ VISIBLE OUTPUT

Do not build many disconnected features before the main flow works.

---

## Preserve working code

Do not rewrite functioning modules unless there is a clear reason.

Prefer targeted changes.

Before modifying an existing API contract, inspect where it is already used.

Do not unexpectedly rename:

- endpoints
- request fields
- response fields
- environment variables
- database fields
- public functions

without updating all consumers.

---

# TEAM DEVELOPMENT

Three developers may work simultaneously.

Avoid creating conflicts with unrelated files.

When possible, keep responsibilities separated between:

- frontend
- backend/integration
- AI/data/testing

Do not overwrite another developer's unrelated changes.

Do not revert existing changes merely because you would implement them differently.

---

# GIT

Keep changes logically grouped.

Use meaningful commits.

Examples:

- feat: initialize FastAPI backend
- feat: add analysis endpoint
- feat: integrate AI analysis
- feat: connect frontend to API
- fix: handle malformed input
- docs: add setup and demo instructions

Before considering a task complete:

- inspect changed files
- run relevant checks
- ensure the project still starts
- ensure no secrets were added

Do not commit API keys, passwords, tokens or private credentials.

---

# DEPENDENCIES

Do not add a dependency when the same task can reasonably be solved with an existing dependency or standard library.

Before adding a dependency:

1. Verify it is actually needed.
2. Prefer stable, common packages.
3. Add it to the appropriate dependency manifest.
4. Ensure installation instructions remain reproducible.

---

# ENVIRONMENT

Secrets must use environment variables.

Maintain `.env.example` containing variable names but no secrets.

Example:

```env
AI_API_KEY=
DATABASE_URL=
```

Code should fail with a clear error when required configuration is missing.

---

# ERROR HANDLING

The main demo scenario must not crash on predictable errors.

At minimum consider:

- invalid input
- empty input
- missing environment variables
- external API failure
- network timeout
- malformed external response

Prefer clear user-visible error messages over raw stack traces.

---

# TESTING

Before declaring a feature complete:

1. Test the normal scenario.
2. Test at least one obvious failure scenario.
3. Verify integration with existing components.

During the final hour, prioritize fixing failures over adding new functionality.

---

# README

README.md is intended for hackathon technical experts.

Keep it accurate as the project evolves.

The final README must include:

- project purpose
- problem
- solution
- architecture
- technologies
- dependencies
- environment variables
- installation
- startup commands
- main verification scenario
- third-party components
- models/APIs/datasets used

Startup instructions must work on a fresh environment.

Never document commands that have not been tested.

---

# DEFINITION OF DONE

A feature is DONE only when:

- code is implemented
- it actually runs
- it integrates with the project
- obvious errors are handled
- another developer can test it
- it can be demonstrated
- required configuration is documented

Partially implemented features are not considered done.

---

# FINAL HOUR MODE

Near the end of the hackathon:

Prioritize:

1. Main scenario reliability
2. Critical bug fixes
3. Integration
4. Fresh-start installation test
5. README
6. Demo data
7. Environment configuration
8. Final repository cleanup

Avoid starting large new features.

---

# FINAL PRINCIPLE

When choosing between:

- sophisticated but risky
- simple and reliable

choose simple and reliable.

The final repository must be understandable, runnable and demonstrable without additional explanations from the team.
