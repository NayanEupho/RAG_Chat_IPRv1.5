# ADG

## Simply Innovative

### 1. Introduction

#### 1.1 Purpose

This Software Requirements Specification (SRS) document defines what the IPR website will do, how it will work, and the value it will deliver to IPR and its stakeholders. The solution shall be implemented using open-source software and tools to meet all requirements outlined in this SRS, ensuring there are no additional licensing, subscription, or recurring costs to IPR.

**Objective & Value to IPR:**

1.  Acts as a single source of truth for design, development, deployment, testing, and acceptance.
2.  Ensures compliance with Government of India standards (GIGW 3.0, WCAG 2.1 AA, W3C, DBIM 3.0).
3.  Reduces ambiguity, rework, and implementation risk.
4.  Enables measurable acceptance and audit readiness.
5.  Serves as a baseline document for future enhancements and maintenance.

#### 1.2 Scope

The scope includes end-to-end lifecycle delivery of the IPR website:

1.  Design, development, testing, and deployment of a responsive, bilingual website.
2.  Develop and submit three interactive design themes for IPR's approval.
3.  Languages supported:
    *   English
    *   Hindi
    *   Hindi via BHASHINI (AI-based translation)
4.  Custom translation management (manual + AI-assisted).
5.  Compliance with:
    *   GIGW 3.0
    *   WCAG 2.1 AA
    *   W3C
    *   DBIM v3.0 (Digital Brand Identity Manual - STQC)
6.  Migration of existing content with enhanced UI/UX.
7.  Certification, security audits, training, documentation.
8.  One-year post-acceptance warranty & support.

#### 1.3 Definitions, Acronyms, and Abbreviations

| Term | Description |
| :--- | :--- |
| IPR | Institute for Plasma Research |
| SRS | Software Requirements Specification |
| GIGW | Guidelines for Indian Government Websites |
| WCAG | Web Content Accessibility Guidelines |
| PwDs | Persons with Disabilities |
| RBAC | Role-Based Access Control |
| SSL/TLS | Secure Sockets Layer / Transport Layer Security |
| WAF | Web Application Firewall |
| WQC | Website Quality Certificate |
| UAT | User Acceptance Testing |

#### 1.4 References

*   GIGW 3.0 Guidelines
*   WCAG 2.1 AA (W3C)
*   DBIM 3.0 (Digital Brand Identity Manual - STQC)
*   CERT-In / STQC Security Guidelines
*   ISO/IEC Software Quality Standards

### 2. Overall Description

#### 2.1 Product Perspective

The IPR website will replace the existing website and function as the official digital presence of IPR. It will be a modular, scalable web application supporting future enhancements without architectural disruption.

#### 2.2 User Classes and Characteristics

| User Class | Description |
| :--- | :--- |
| General Public | Visitors accessing information and resources |
| Content Editors | Create and update website content |
| Reviewers/Approvers | Review and approve content |
| Administrators | Manage users, roles, security, and configuration |
| Super Administrator | Full system-level control |

#### 2.3 Operating Environment

1.  **Hosting Location:** IPR Gandhinagar
2.  **Server OS:** Oracle 10.x
3.  **Web Server:** Apache
4.  **Database:** MySQL
5.  **Browsers:** Chrome, Firefox, Edge, Safari
6.  **Platforms:** Windows, Linux, Android, iOS, macOS
7.  **Open source CMS Used:** WordPress
8.  **Modern Front-end tech stack:** HTML, CSS, JS
9.  **Back-end tech stack:** Laravel

#### 2.4 Constraints

1.  Completion timeline: 165 days from award of contract.
2.  No third-party tracking scripts or hidden backlinks.
3.  Hosting, DNS, and SSL provided by IPR.
4.  Compliance with Indian Government regulations.

#### 2.5 Assumptions and Dependencies

1.  Internet access will not be provided; only secure HTTPS traffic through port 443 will be permitted.
2.  IPR will provide an offline local server for staging and deployment. The website will be developed on ADG's server and migrated to the IPR server after completion of security certification and audit requirements.
3.  Timely content and approvals from IPR.

### 3. Functional Requirements

#### 3.1 Website Design & Content Management

*   **FR-01:** Responsive bilingual UI (English, Hindi, BHASHINI).
*   **FR-02:** Device-aware content visibility and navigation.
*   **FR-03:** Content migration with improved UX.
*   **FR-05:** Content workflow (Create → Review → Approve → Publish).
*   **FR-04:** Dashboard for create/update/delete/upload.
*   **FR-06:** Scheduled publishing/unpublishing by date & time.

#### 3.2 Search and Navigation

*   Autocomplete search.
*   Fuzzy matching.
*   Ranked results.
*   XML-based routing.

#### 3.3 Institutional Structure Pages (NEW)

*   **FR-NEW-07:** Dedicated webpage for each facility of IPR.
*   **FR-NEW-08:** Members listing per facility.
*   **FR-NEW-09:** R&D Activities structured as: Group → Division → Section.

#### 3.4 Media and Gallery Management

*   **FR-10:** The system shall provide default templates for image and video galleries.
*   **FR-11:** ADG shall create/manage images, videos, audio, and infographics using raw content provided by IPR.

#### 3.5 User and Role Management

*   **FR-12:** The system shall implement RBAC with hierarchical user roles.
*   **FR-13:** Access to the administrator panel shall be restricted.

#### 3.6 Analytics and Reporting

*   **FR-14:** The system shall provide analytics in form of Graphs and Tables with export to PDF option including:
    *   Number of users
    *   Hit rate
    *   Source domains/IP addresses
    *   Referrers
    *   Page-wise hit rates
*   **FR-15:** The system shall generate reports on content modification activities with timeline filters, username and title of page.

### 4. Non-Functional Requirements

#### 4.1 Performance

*   Optimized assets (minified JS/CSS, compressed images).
*   Lazy loading.
*   Fast response time: 1 second under normal load.
*   Graceful degradation during peak load.

#### 4.2 Usability & UI/UX

*   Fully responsive design across devices and orientations.
*   Compatibility with all major browsers and platforms.
*   Optimized navigation and content visibility.

#### 4.3 Accessibility

*   Compliance with WCAG 2.1 AA.
*   DBIM - [DBIM Manual V 3.0](https://www.stac.gov.in/sites/default/files/2025-06/DBIM%20Manual%20V%203%200.pdf) (Optional, subject to design requirements and project needs).
*   Full accessibility for Persons with Disabilities (PwDs).

#### 4.4 Security

**Tools & Techniques:**

*   HTTPS with SSL/TLS.
*   CAPTCHA.
*   Input validation (client & server).
*   Account lockout policies.
*   Protection against SQLI, XSS, CSRF, DOS/DDoS.
*   Secure session handling.
*   Open-Source WAF Implementation Includes:
    *   OWASP Core Rule Set
    *   Request filtering
    *   IP reputation blocking
    *   Rate limiting
    *   Real-time attack logging and alerting

**Additional Controls:**

*   Separate application & data paths.
*   Hidden server file paths.
*   XML routing with HTTP 404 for invalid paths.
*   Multi-level error handling (UI, middleware, backend).
*   Source code never exposed on errors.
*   Malware scanning for uploads.
*   Automatic daily backups.
*   Backup storage on a dedicated storage server and automatic recovery in case of failure.
*   Implement searchable and achievable audit trails on the web page of all user actions.

#### 4.5 SEO

*   Metadata optimization.
*   Secure URLs.
*   Structured data.
*   Search Console integration.

#### 4.6 Scalability

*   Layered, modular architecture to support future modules, schemes, and forms.

### 5. Deployment Architecture

#### 5.1 Server Architecture

1.  **Primary Server:** Global Live
2.  **Secondary Server:** Local Live (post-approval migration)
3.  **Staging Server:** Testing & UAT
4.  **Storage Server:** Backup & Disaster Recovery

#### 5.2 Deployment Automation

*   Deployment scripts provided.
*   Rollback capability.
*   Automated build & deployment process.

#### 5.3 Public Dashboard

Public-facing dashboard showing:

*   Page usage statistics.
*   Visitor trends.
*   Content popularity.

### 6. Certificates and Audit Requirements

The vendor shall obtain and submit:

1.  Safe-to-Host Certificate (CERT-In/STQC/NIC empanelled auditors).
2.  Website Quality Certificate (WQC) from STQC.
3.  Web Accessibility Audit Report from empanelled auditors under Department of Empowerment of Persons with Disabilities, Ministry of Social Justice & Empowerment, GoI.

### 7. Warranty and Support Requirements

*   One-year functional warranty after acceptance.
*   Dedicated single point of contact.
*   Bug fixing and error rectification.
*   Patch management and upgrades.
*   Restoration in case of crashes.
*   Protection against spam, ransomware, and cyber threats.

### 8. Acceptance Criteria and Deliverables

Final acceptance shall be granted after submission and approval of:

1.  Approved SRS document.
2.  Design document (UI/UX design in Figma).
3.  Test cases and UAT report.
4.  Website deployment and Go-Live.
5.  Source code and credentials.
6.  User training resources and technical manuals explaining how to operate the system.
7.  All required certificates and audit reports.

### 9. Ownership and Confidentiality

*   IPR shall retain full ownership of all data, source code, and software.
*   No logo, watermark, or branding of ADG or vendor on IPR Website.
*   Vendor shall submit a signed Non-Disclosure Agreement (NDA) as per IPR format.
