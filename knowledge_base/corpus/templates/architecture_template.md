# Solution Architecture Template

A high-level design that an EM and senior engineers can review in 30 minutes.

## Context

One paragraph: the system's purpose, its users, and the systems it talks to.
A context description should name every external system from the BRD's
"integrations" and "referenced systems".

## Components

List logical components. For each: name, single responsibility, the technology
area (web, service, worker, datastore, queue), and the interfaces it exposes or
consumes. Prefer 4–8 components; more than 12 means the altitude is too low.

## Data Flows

For each significant flow: source → destination, the data carried, the protocol
(HTTP, gRPC, event, file), and whether it is synchronous or asynchronous.
Include the "unhappy path" for anything the BRD calls out (retries, dead-letter).

## NFR Mapping

A table: NFR category → the requirement ids it covers → the architectural tactic
that satisfies it → how it will be verified. Every non_functional requirement in
the BRD must appear here. Untraceable NFRs are the most common review failure.

## Key Decisions

3–6 decisions with rationale and the alternatives rejected. Examples: sync vs
event-driven integration, single vs multi datastore, build vs buy for a
capability, deployment topology.

## Diagram

Provide a Mermaid `graph` or C4-style container diagram showing components and
their primary flows.
