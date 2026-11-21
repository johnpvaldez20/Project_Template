<!--
SPDX-FileCopyrightText: YEAR COPYRIGHT-HOLDER
SPDX-License-Identifier: LicenseRef-UNSET
-->

# Architecture

Replace each bracket with a project fact.
Keep this page and the fixtures in agreement.
The gate checker reads `docs/design/fixtures/`.
It does not read the brackets on this page.
A change to this page, a use case, or a state machine is its own packet.
The worker role on that packet is OWNER.
Read `docs/governance/GOVERNANCE_LINUS.md` section 16.

## 1. System overview

[One sentence that states what the system does.]

### Core tenets

1. [Tenet. Write a rule a reviewer can enforce.]
2. [Tenet. Write a rule a reviewer can enforce.]
3. [Tenet. Write a rule a reviewer can enforce.]

## 2. Architectural layering

Agents must not move logic across layers.
Set the directory for each layer in `.governance/project.json`.

### Presentation

Rule: [Presentation shows data and sends intent. It does not decide domain rules.]

Paths: `src/presentation/`

### Application

Rule: [Application orders the use case. It does not store data and it does not render a view.]

Paths: `src/application/`

### Domain

Rule: [Domain holds entities, transitions, and use-case rules. It does not call a network.]

Paths: `src/domain/`

### Infrastructure

Rule: [Infrastructure talks to the network, the database, and the clock. It does not own a use-case rule.]

Paths: `src/infrastructure/`

## 3. Core use cases

Do not add a feature that has no use case here.
A new use case needs owner approval and an architecture packet.
Copy this block for each use case. Number the ids `UC-01`, `UC-02`, and so on.

### UC-N [short name]

- Trigger: [What starts the use case.]
- Flow: [The steps, in order.]
- Constraint: [The rule a regression test must enforce.]

The filled example is `docs/design/fixtures/use-cases.json`.
The example packet `PKT-0001` cites that use case.
The constraint test name in the fixture must appear in the packet verification plan.

## 4. Data models and state machines

### [Entity name]

| Field | Type |
|---|---|
| [field] | [type] |

States, in order: `[state]`, `[state]`, `[state]`.

A transition moves to the next state only.
Do not skip a state.
A packet that names this machine lists one regression test for each transition.

The filled example is `docs/design/fixtures/state-machines.json`.
That example is the `Item` machine.
The states are `draft`, then `active`, then `archived`.

## 5. API boundaries and external integrations

- Base URL: `[https://api.example.invalid]`
- Auth: read the token from the environment variable `[API_TOKEN]`. Do not commit the token.
- Rate limit: `[N]` requests in `[window]`. Wait with backoff when the server answers `[429]`.
- Error contract: `[error]` falls back to `[safe behavior]`. Do not invent a success.

## 6. Infrastructure and deployment topology

- Compute: `[service name and host class]`
- Database: `[engine and what it stores]`
- Cache or queue: `[name and what it holds]`
- Storage: `[what is stored and what stays out of the compute service]`
- Rule: the compute service is stateless. It stores state only in the database, the queue, or the object store.
