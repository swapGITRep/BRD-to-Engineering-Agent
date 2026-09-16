# Business Requirements Document — Pharmacy Information System Modernization (Monolith to Microservices)

## 1. Overview

MeridianRx operates the pharmacy information system ("PharmaCore") used by 214
retail pharmacies, 46 hospital inpatient pharmacies, and 58 affiliated clinic
dispensaries across 14 US states. PharmaCore is a single Java 8 / JSP monolith
first built in 2009, deployed as one WAR file to a fixed pool of on-premises
Tomcat servers, backed by one Oracle database. It handles e-prescribing,
dispensing, clinical review, inventory, and third-party billing for
approximately 2.3 million active patient profiles and 91,000 prescriptions
filled per day network-wide.

The monolith is now the primary constraint on the business: every release
(currently quarterly) requires a full regression pass and a coordinated
overnight deployment across all sites because there is no way to ship one
capability without redeploying all of them; the JSP presentation layer cannot
be reused by the patient-facing mobile app the business wants to launch; and
the fixed server pool cannot scale independently for the pharmacist-facing
dispensing workload versus the patient-facing portal workload, which causes
timeouts during seasonal peaks (flu shot season, Medicare Part D open
enrollment). This BRD defines the requirements for re-platforming PharmaCore
onto a Java (Spring Boot) microservices backend with a React frontend,
migrated incrementally behind a strangler-fig pattern with the existing
monolith, while the system continues to operate as the pharmacies' and
hospitals' system of record for prescription dispensing with no scheduled
downtime.

Project sponsor: VP of Pharmacy Technology, in partnership with the Chief
Pharmacy Officer and the Director of Regulatory Compliance. Target: phased
migration over 6 quarters, with the first strangler-fig service
(Prescription Intake) live in production by the end of Q2.

## 2. Goals

- Reduce lead time from code-complete to production for a single capability
  from the current 11-week quarterly release train to under 1 week.
- Eliminate the shared fixed-server bottleneck so dispensing workflows and
  patient-portal workflows can be scaled independently.
- Cut average prescription fill time (intake to pharmacist verification) from
  9.5 minutes to under 6 minutes through a redesigned React fill workflow.
- Enable a patient-facing mobile app and third-party integrations (new payer
  and EHR partners) without depending on the JSP rendering layer.
- Maintain zero regulatory compliance findings (DEA, state Boards of
  Pharmacy, HIPAA) throughout the migration.
- Improve platform availability from 99.5% to 99.95% measured across all
  facility types, including hospital 24/7 operations.

## 3. Functional Requirements

### 3.1 Patient Management & Registration

3.1.1 The system must capture and maintain patient demographics, contact
      information, primary care and referring prescriber, allergies, and
      insurance coverage (primary, secondary, and tertiary).

3.1.2 The system must record structured allergy and adverse drug reaction
      data (substance, reaction type, severity) usable by the clinical
      review engine, not free text alone.

3.1.3 The system must support a single patient record shared across any
      retail, clinic, or hospital site the patient uses within the network,
      with a full audit trail of which site created or modified each field.

3.1.4 The system must detect and support merging of probable duplicate
      patient records (matched on name, date of birth, and at least one of:
      phone, address, insurance ID) with pharmacist or technician approval
      before any merge is applied.

3.1.5 The system must capture and version HIPAA privacy consent and
      communication preferences (text, email, phone, portal) per patient.

3.1.6 The system must support patient search by name, date of birth, phone,
      prescription number, and insurance member ID, returning results within
      2 seconds for the full 2.3M-patient population.

### 3.2 Prescription Intake & E-Prescribing

3.2.1 The system must receive electronic prescriptions from prescribers via
      the Surescripts network using the NCPDP SCRIPT standard (new
      prescriptions, renewal requests and responses, and cancellations).

3.2.2 The system must validate incoming e-prescriptions against the
      prescriber's NPI and, for controlled substances, DEA registration
      number before the prescription is queued for intake.

3.2.3 The system must support manual intake of prescriptions received by
      fax, phone-in, or paper, including image capture and attachment of the
      original document to the prescription record.

3.2.4 The system must let a pharmacy technician or pharmacist initiate a
      refill authorization request (RxRenewal) to the prescriber via
      Surescripts when no refills remain, and track the request status.

3.2.5 The system must support prescription transfer out to another pharmacy
      and transfer in from another pharmacy, in compliance with state
      transfer regulations, including remaining refill count and transfer
      history.

3.2.6 The system must flag an incoming e-prescription as a duplicate when an
      active, unexpired prescription for the same drug and patient already
      exists, before it reaches pharmacist review.

### 3.3 Clinical Review & Drug Utilization Review (DUR)

3.3.1 The system must perform real-time Drug Utilization Review at the point
      of data entry, checking drug-drug interactions, drug-allergy
      conflicts, therapeutic duplication, and dosage range against the
      patient's active medication profile.

3.3.2 The system must present DUR alerts to the pharmacist with a documented
      severity level and require a recorded override reason before
      dispensing may proceed when an alert is not resolved by rejecting the
      fill.

3.3.3 The system must retain every DUR alert, its severity, and the
      pharmacist's disposition (resolved, overridden with reason,
      prescription rejected) as part of the permanent dispensing record.

3.3.4 The system must support pharmacist clinical notes attached to a
      patient's medication profile, visible to any pharmacist reviewing that
      patient across sites.

3.3.5 The system must support documentation of immunizations administered
      by a pharmacist (vaccine, lot number, site, administering pharmacist)
      and must submit that record to the applicable state immunization
      registry.

3.3.6 The system should support enrollment and documentation of Medication
      Therapy Management (MTM) sessions, including the comprehensive
      medication review outcome.

### 3.4 Dispensing & Fill Workflow

3.4.1 The system must guide a technician through data entry, product
      selection at the NDC (National Drug Code) level, and label generation
      for a new fill, and must not allow a fill to proceed to dispensing
      without a completed DUR check.

3.4.2 The system must require a licensed pharmacist to perform a final
      verification step — comparing the filled product, label, and
      prescription — before a prescription is marked ready for pickup or
      administration; this step must not be bypassable by any role other
      than pharmacist.

3.4.3 The system must verify the dispensed product by barcode scan against
      the NDC on the prescription at both the fill step and the point of
      patient pickup or hospital administration.

3.4.4 The system must support partial fills, including tracking the
      remaining quantity owed and the reason for the partial fill (e.g.,
      insurance quantity limit, inventory shortage, controlled-substance
      partial per DEA regulation).

3.4.5 The system must support non-sterile and sterile (IV admixture)
      compounding workflows, including recording the formula, lot numbers of
      each ingredient, and the compounding pharmacist or technician.

3.4.6 The system must apply enhanced handling for Schedule II-V controlled
      substances, including mandatory pharmacist-of-record attribution and,
      where facility policy requires it, a second pharmacist co-verification
      for Schedule II dispensing.

3.4.7 The system must support will-call, patient pickup, mail/delivery
      fulfillment, and — for hospital sites — nurse-administered dispensing
      queues as distinct fulfillment paths from the same fill record.

### 3.5 Inventory & Supply Chain

3.5.1 The system must maintain perpetual, NDC-level inventory for every
      dispensing location, decrementing on dispense and incrementing on
      receipt.

3.5.2 The system must maintain a separate perpetual inventory ledger for
      Schedule II-V controlled substances, reconcilable at any point in
      time, as required for DEA recordkeeping.

3.5.3 The system must support electronic ordering of Schedule II substances
      via a DEA Controlled Substance Ordering System (CSOS)-compliant
      workflow, including electronic Form 222 equivalents.

3.5.4 The system must integrate with primary wholesaler EDI feeds (the
      network currently uses McKesson and Cardinal Health) to receive
      electronic invoices and update inventory automatically on receipt
      confirmation.

3.5.5 The system must track lot number and expiration date at the
      unit-of-use level and must prevent dispensing of an expired lot.

3.5.6 The system must support Drug Supply Chain Security Act (DSCSA)
      track-and-trace data capture and exchange with trading partners for
      every prescription-drug transaction.

3.5.7 The system must generate automatic reorder recommendations based on
      configurable par levels and recent velocity per NDC per site.

3.5.8 The system must support manufacturer or FDA recall processing,
      identifying all affected lots in inventory and all patients dispensed
      from an affected lot within the recall window.

3.5.9 The system must integrate with automated dispensing cabinets at
      hospital and clinic sites (the network currently uses Pyxis and
      Omnicell devices) to reconcile cabinet inventory against the central
      perpetual inventory at least every 4 hours.

### 3.6 Billing, Claims & Adjudication

3.6.1 The system must submit real-time pharmacy claims to Pharmacy Benefit
      Managers (PBMs) using the NCPDP Telecom D.0 standard and process the
      adjudication response (paid, rejected, or captured) within the fill
      workflow before pickup.

3.6.2 The system must support billing to Medicare Part D, state Medicaid
      programs, and commercial payers, including coordination of benefits
      across up to three payers in priority order.

3.6.3 The system must calculate and display the patient's co-pay or
      out-of-pocket cost at the point of dispensing, reflecting the actual
      adjudicated PBM response.

3.6.4 The system must support prior-authorization workflows, including
      tracking PA request status and re-submitting a claim once a PA is
      approved.

3.6.5 The system must support claim reversal and rebilling when a fill is
      voided, returned, or a PBM rejection requires resubmission with
      corrected data.

3.6.6 The system must support cash (self-pay) pricing with a configurable
      pricing schedule independent of insurance adjudication.

3.6.7 The system must support 340B split-billing for eligible covered
      entities, correctly distinguishing 340B-eligible dispenses from
      non-eligible dispenses for the same NDC and patient population.

3.6.8 The system must generate patient statements for any outstanding
      patient-responsibility balance.

### 3.7 Hospital & Clinic-Specific Operations

3.7.1 The system must support unit-dose dispensing and packaging for
      hospital inpatient pharmacy, distinct from the retail multi-dose fill
      workflow.

3.7.2 The system must maintain a site-specific drug formulary and must warn
      when a prescribed or ordered drug is non-formulary, offering
      formulary-equivalent alternatives where configured.

3.7.3 The system must exchange medication orders and results with hospital
      and clinic EHR systems (the network's largest hospital sites run Epic
      and Cerner) using HL7v2 and FHIR interfaces.

3.7.4 The system must support Barcode Medication Administration (BCMA)
      verification, confirming the "five rights" (right patient, drug, dose,
      route, time) at the point of nurse administration.

3.7.5 The system must track IV admixture preparation including sterile
      compounding checklists consistent with USP <797> requirements.

3.7.6 The system must support clinic-based point-of-care dispensing for a
      limited formulary at clinic sites that do not operate a full pharmacy.

### 3.8 Regulatory Reporting & Compliance

3.8.1 The system must submit controlled-substance dispensing data to each
      applicable state's Prescription Drug Monitoring Program (PDMP) on the
      reporting cadence that state requires (several states in the network's
      footprint require near-real-time, same-day reporting).

3.8.2 The system must support DEA ARCOS (Automation of Reports and
      Consolidated Orders System) reporting for applicable controlled
      substance transactions.

3.8.3 The system must record an immutable audit trail of every access to,
      and modification of, a patient record and every dispensing event,
      including user identity, timestamp, and the action taken.

3.8.4 The system must support electronic signature workflows compliant with
      21 CFR Part 11 wherever an electronic signature replaces a wet
      signature in the dispensing or clinical record.

3.8.5 The system must support per-state configurable business rules
      (e.g., controlled-substance prescription validity periods, transfer
      limits, PDMP query requirements) since pharmacy regulation varies by
      state and the network operates in 14 states.

### 3.9 Patient-Facing & Portal

3.9.1 The system must provide a patient-facing web portal (React) for
      requesting refills, viewing medication history, and viewing
      prescription status.

3.9.2 The system must let a patient schedule an immunization or clinical
      service appointment at a participating retail or clinic location
      through the portal.

3.9.3 The system must support secure, HIPAA-compliant messaging between a
      patient and the dispensing pharmacist.

3.9.4 The portal must be usable on mobile browsers and must meet WCAG 2.1 AA
      accessibility guidelines.

3.9.5 The portal should support English and Spanish at initial launch, with
      the content model designed to add further languages without code
      changes.

### 3.10 Reporting & Analytics

3.10.1 The system must provide operational dashboards showing fill volume,
       average fill time, DUR override rate, and wait time, filterable by
       site and by facility type (retail, clinic, hospital).

3.10.2 The system must generate the regulatory reports required by section
       3.8 in the format each receiving agency requires, on a schedule, and
       must retain proof of successful submission.

3.10.3 The system must provide financial reconciliation reports reconciling
       adjudicated PBM payments against claims submitted, by site and by
       payer.

3.10.4 Access to reports containing patient-identifiable data must be
       restricted by role and logged in the same audit trail as section
       3.8.3.

### 3.11 Migration-Specific Requirements

3.11.1 The system must be migrated using a strangler-fig approach: each
       capability area (e.g., Prescription Intake, then Clinical
       Review/DUR, then Dispensing, then Billing, then Inventory) is
       extracted into its own Spring Boot service and cut over behind a
       routing layer while the remaining capabilities continue to run in
       the existing JSP monolith.

3.11.2 Each capability's cutover must be zero-downtime for pharmacy
       operations; no cutover may require a scheduled outage during
       pharmacy or hospital operating hours.

3.11.3 During the transition period, a strangled capability's data changes
       must be kept consistent between the new service's data store and the
       monolith's Oracle database (via dual-write or change-data-capture,
       implementer's choice) so that any capability still running in the
       monolith reads correct data.

3.11.4 Every cutover must include a rollback path that returns traffic for
       that capability to the monolith without data loss, exercisable within
       15 minutes of a decision to roll back.

3.11.5 All existing external integrations — Surescripts, PBM claim
       submission, wholesaler EDI feeds, state PDMP reporting, and
       automated dispensing cabinet interfaces — must continue to function
       without interruption or contract changes throughout the migration,
       regardless of whether the capability that owns the integration has
       been migrated yet.

3.11.6 Historical dispensing, billing, and clinical data from the legacy
       Oracle schema must be migrated to the new services' data stores with
       a reconciliation report demonstrating record-count and financial-total
       parity before the legacy data path for that capability is retired.

## 4. Non-Functional Requirements

4.1 Hospital-site capabilities must be available 24/7 at 99.95% measured
    monthly; retail and clinic capabilities must be available 99.9% during
    published operating hours (06:00–24:00 local).

4.2 Real-time PBM claim adjudication must return a result within 3 seconds
    at the 95th percentile under normal load.

4.3 Real-time DUR checks must complete within 1.5 seconds at the 95th
    percentile so they do not perceptibly slow the fill workflow.

4.4 The platform must handle at least 3x normal daily transaction volume
    without degradation during seasonal peaks (flu immunization season,
    Medicare Part D open enrollment in Q4).

4.5 All Protected Health Information (PHI) must be encrypted at rest and in
    transit, and access must follow HIPAA minimum-necessary and role-based
    access control principles.

4.6 Every capability service must support independent deployment with no
    coordinated release train, and a single service's deployment failure
    must not degrade any other capability.

4.7 The platform must maintain a documented Recovery Point Objective (RPO)
    of 5 minutes and Recovery Time Objective (RTO) of 1 hour for every
    capability that touches active dispensing.

4.8 All PHI must be stored within US data centers/regions; no PHI may be
    processed or stored outside the United States.

4.9 The React frontend must meet WCAG 2.1 AA accessibility standards for
    both the pharmacist/technician workstation UI and the patient portal.

4.10 All interoperability interfaces must conform to the relevant published
     standard version (NCPDP SCRIPT and Telecom D.0, HL7v2.5.1/FHIR R4) so
     existing prescriber, payer, and EHR trading partners require no changes
     on their end.

4.11 The platform must support zero-downtime deployment (rolling or
     blue/green) for every migrated service.

4.12 Every access to, and change to, a patient or dispensing record must be
     logged to a tamper-evident audit store retained for a minimum of 7
     years, consistent with state pharmacy recordkeeping requirements.

4.13 The pharmacist/technician workstation UI must support keyboard-only
     operation for the core fill and verification workflow, matching current
     workstation ergonomics in a high-volume pharmacy.

## 5. Constraints and Assumptions

- The legacy Oracle schema and its stored procedures remain the system of
  record for any capability not yet migrated; migrated services must not
  write directly to legacy tables outside the agreed dual-write mechanism.
- Surescripts, PBM switch, wholesaler EDI, and state PDMP integration
  contracts and credentials are fixed for the duration of the migration and
  cannot be renegotiated to suit the new architecture.
- The engineering organization's current skill set is predominantly Java/JSP;
  the React frontend and Spring Boot microservices target require ramping
  frontend and cloud-native skills, assumed to happen via training and
  targeted hiring within the first two quarters.
- Hospital sites' existing network and data-residency policies require
  hospital-facing services to be deployable within each hospital's approved
  data center or private cloud boundary, not solely public cloud.
- Controlled-substance ordering (CSOS) and DEA reporting integrations must
  remain continuously available throughout migration; no capability
  extraction may put a gap in controlled-substance compliance.
- The 6-quarter migration timeline assumes capability extraction proceeds in
  the sequence in section 3.11.1 and is not reordered mid-migration.

## 6. Out of Scope

- Replacing the wholesaler/distributor systems themselves (McKesson,
  Cardinal Health) — only the existing EDI integration is in scope.
- Replacing the PBM adjudication systems or the Surescripts network — only
  integration via their existing standards (NCPDP Telecom D.0, NCPDP
  SCRIPT) is in scope.
- Replacing hospital or clinic EHR systems (Epic, Cerner, or others) at
  partner sites — only HL7/FHIR integration with those systems is in scope.
- Building a net-new mobile native app — the React portal must be
  mobile-responsive, but a native iOS/Android app is a separate,
  future initiative.
- International (non-US) pharmacy operations or regulatory regimes.

## 7. Success Metrics

- Lead time from code-complete to production for a single capability drops
  from 11 weeks to under 1 week within 2 quarters of that capability's
  cutover.
- Average prescription fill time (intake to pharmacist verification) drops
  from 9.5 minutes to under 6 minutes within 1 quarter of the Dispensing
  capability's cutover.
- Platform availability reaches 99.95% for hospital sites and 99.9% for
  retail/clinic sites within 2 quarters of full migration.
- Zero DEA, state Board of Pharmacy, or HIPAA compliance findings
  attributable to the migration, verified at each capability cutover and at
  the program's next scheduled compliance audit.
- Each capability's data-reconciliation report (section 3.11.6) shows 100%
  record-count and financial-total parity before its legacy path is
  retired.
- System sustains 3x normal daily transaction volume during the first
  post-migration seasonal peak (flu season or Part D open enrollment)
  without an availability or performance incident.
