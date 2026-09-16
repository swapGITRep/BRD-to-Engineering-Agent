# Business Requirements Document — On-Call Handoff Notes

## 1. Overview

On-call engineers currently hand off shift notes in a Slack thread that
gets lost after a week. We want a tiny internal tool to log and read past
handoff notes.

Sponsor: Eng Manager, Platform team.

## 2. Goals

- Stop losing on-call handoff context between shifts.

## 3. Functional Requirements

3.1 An engineer must be able to submit a handoff note with free text and a
    timestamp.

3.2 Anyone on the team must be able to view the last 10 handoff notes.

## 4. Non-Functional Requirements

4.1 The tool must only be accessible to the Platform team.

## 5. Constraints and Assumptions

- One engineer will build this in spare time; no dedicated budget.

## 6. Out of Scope

- Everything not listed above.

## 7. Success Metrics

- The team actually uses it instead of Slack.
