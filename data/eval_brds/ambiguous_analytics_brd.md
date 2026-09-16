# Business Requirements Document — Internal Analytics Hub

## 1. Overview

Various teams keep asking for "better visibility" into product usage. This BRD
covers building some kind of internal analytics thing so people stop pulling
numbers by hand. Scope is still being worked out with stakeholders.

Sponsor: someone in the Product org, TBD. Target go-live: sometime next year,
maybe sooner if it goes well.

## 2. Goals

- Make it easier for teams to see how the product is being used.
- Reduce the number of one-off data requests to the analytics team, probably.
- Support "self-serve" analytics, whatever that ends up meaning for us.

## 3. Functional Requirements

3.1 The system should probably let users build some kind of dashboard with
    charts, similar to what other companies seem to have.

3.2 Users should be able to look at usage trends over time, at whatever
    granularity makes sense.

3.3 The system might need to support exporting data, format TBD — CSV is an
    option but stakeholders mentioned "maybe Excel too."

3.4 There should be some way to share a dashboard with other people, though
    it's unclear if that means a link, an export, or a scheduled email.

3.5 Admins should have more access than regular users, presumably to manage
    who can see what, details not finalized.

3.6 The system could support alerting if a metric does something unusual,
    but this might be a phase 2 thing depending on time.

3.7 It would be good if the tool could eventually connect to more than one
    data source, though right now everyone seems to only care about the main
    product database.

## 4. Non-Functional Requirements

4.1 The tool should be reasonably fast — nobody wants to wait forever for a
    chart to load, though no one has given a specific number.

4.2 It should be secure, obviously, in whatever way is standard for us.

4.3 Uptime should be good enough that people trust the numbers, no formal
    SLA has been discussed.

## 5. Constraints and Assumptions

- Team size and stack are not yet decided — engineering leadership is still
  staffing this.
- It's assumed the main product database can be queried directly, but this
  hasn't been confirmed with the DBA team.
- Budget is "limited," no figure has been shared.

## 6. Out of Scope

- Not clear yet — needs a follow-up conversation with stakeholders.

## 7. Success Metrics

- People seem happier with analytics, roughly speaking.
- Fewer ad-hoc data requests, though nobody is currently counting them.
