# Business Requirements Document — Order Orchestration Hub

## 1. Overview

Orders today touch six different systems in an ad-hoc, point-to-point way:
a 20-year-old mainframe inventory system, a SOAP-based ERP, a modern REST
billing service, a third-party shipping carrier API, a legacy on-prem
warehouse management system that only accepts nightly flat-file batches, and
a message queue used by the fulfillment team. This BRD covers an
orchestration hub that centralizes these integrations behind one coherent
order-processing workflow.

Sponsor: Director of Supply Chain Systems. Target: pilot with one product
category within two quarters.

## 2. Goals

- Replace today's tangle of point-to-point integrations with one
  orchestration layer that owns the order lifecycle end-to-end.
- Make it possible to add a new fulfillment partner without touching every
  other system's integration code.
- Reduce order-processing errors currently caused by systems falling out of
  sync with each other.

## 3. Functional Requirements

3.1 The system must query real-time stock availability from the mainframe
    inventory system, which only exposes a fixed-width flat-file interface
    over an overnight SFTP batch — no real-time API exists.

3.2 The system must create and update purchase orders in the ERP system via
    its existing SOAP API.

3.3 The system must charge and refund customers through the modern billing
    service's REST API.

3.4 The system must request shipping labels and tracking numbers from the
    shipping carrier's REST API, and handle its webhook callbacks for
    delivery status updates.

3.5 The system must submit fulfillment instructions to the on-prem warehouse
    management system, which only accepts a specific flat-file format dropped
    into a directory, processed once nightly at 01:00.

3.6 The system must publish order-state-change events onto the existing
    fulfillment team's message queue, in the message format they already
    consume.

3.7 The system must reconcile inventory shown to customers against the
    mainframe's true (batch-delayed) stock levels, and must not oversell
    beyond what the last batch confirmed.

3.8 The system must provide a single "order status" view that merges state
    from all six systems into one coherent timeline for customer support to
    use.

3.9 The system must retry failed calls to the billing and shipping REST APIs
    with backoff, and must alert a human if an order is stuck across any
    integration for more than 4 hours.

3.10 Adding a new fulfillment partner in the future must not require changes
     to the mainframe, ERP, or billing integrations — only a new adapter
     behind the orchestration layer's existing interface.

## 4. Non-Functional Requirements

4.1 The orchestration hub must tolerate any single downstream system being
    unavailable without losing or corrupting an in-flight order — the order
    must resume once the system recovers.

4.2 Given the mainframe and warehouse system are batch-only (nightly), the
    hub must be designed around eventual consistency for those two
    integrations specifically, while the billing and shipping integrations
    remain real-time.

4.3 The hub must not introduce a new single point of failure for order
    creation; if the hub itself is down, orders already accepted must
    continue processing via their in-flight state.

4.4 All cross-system order state changes must be traceable end-to-end for
    support and audit purposes, across all six systems.

4.5 The system must handle the ERP SOAP API's documented reliability
    (occasional multi-second latency spikes, no formal SLA offered by that
    system's vendor).

## 5. Constraints and Assumptions

- The mainframe and on-prem warehouse system cannot be modified or replaced
  in this project's timeframe; their existing batch interfaces are fixed
  constraints, not negotiable.
- The team is 4 engineers with strong REST/cloud experience and no prior
  SOAP or mainframe flat-file integration experience.
- The ERP vendor's SOAP API and its WSDL are stable but poorly documented
  beyond the WSDL itself.
- Existing infrastructure is on Azure; the mainframe and warehouse system are
  reached via an existing site-to-site VPN to the on-prem data center.

## 6. Out of Scope

- Replacing or modernizing the mainframe or on-prem warehouse system
  themselves.
- Real-time inventory sync with the mainframe (batch-delayed is accepted for
  this phase).

## 7. Success Metrics

- Order-processing errors caused by cross-system state drift reduced by 70%.
- A new fulfillment partner can be onboarded by building one adapter, with
  zero changes to the mainframe, ERP, or billing integration code.
- Support can resolve an "order status" inquiry using the merged timeline
  view alone, without contacting engineering.
