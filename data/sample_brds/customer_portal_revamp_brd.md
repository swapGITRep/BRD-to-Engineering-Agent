# BUSINESS REQUIREMENTS DOCUMENT

## CUSTOMER SELF-SERVICE PORTAL REVAMP

1. Background

The current customer portal is a 9-year-old server-rendered application. Support
ticket volume for "cannot find my invoice" and "how do I change my plan" is the
single largest driver of tier-1 contact volume. The business wants a modern,
mobile-friendly portal that deflects these contacts.

Sponsor: Chief Customer Officer. Desired launch: within two quarters.

2. Objectives

- Cut tier-1 support contacts for self-serviceable tasks by 40%.
- Achieve a mobile Lighthouse performance score of at least 85.
- Ship a design system the marketing site can also adopt later.

3. Functional Requirements

3.1 Customers must authenticate with email + password and with Google / Apple SSO.

3.2 Customers must be able to view and download invoices from the last 24 months.

3.3 Customers must be able to upgrade, downgrade, or cancel their subscription
    plan, with prorated billing shown before confirmation.

3.4 Customers should be able to update payment methods without contacting support.

3.5 Customers must be able to open a support ticket with an attachment.

3.6 The portal should show a personalized usage dashboard for the current billing
    period.

3.7 Admins at a customer organization must be able to invite and remove users and
    assign roles.

4. Non-Functional Requirements

4.1 The portal must support 20,000 monthly active users with peak concurrency of
    800 sessions.

4.2 Pages must reach interactive state in under 2.5 seconds on a mid-range mobile
    device over 4G.

4.3 The portal must meet WCAG 2.1 AA accessibility.

4.4 Personal data handling must comply with GDPR, including data export and
    deletion on request.

4.5 The system must integrate with the existing billing service (REST) and the
    identity provider (OIDC).

5. Constraints and Assumptions

- The billing service API is owned by another team and changes are out of scope.
- The engineering team of 6 is strong in TypeScript and React, new to native mobile.
- Hosting must stay within the company's existing Azure subscription.
- Brand guidelines and design tokens will be provided by the design team in week 2.

6. Out of Scope

- A native iOS/Android app (a responsive web app is acceptable for launch).
- Migrating historical support tickets from the legacy system.
- Localization beyond English for the initial release.

7. Success Metrics

- 40% reduction in self-serviceable tier-1 contacts within 3 months of launch.
- Task success rate above 90% in post-launch usability testing.
- Less than 1% error rate on plan-change transactions.
