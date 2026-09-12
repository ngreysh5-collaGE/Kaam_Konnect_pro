# AI AGENT HANDOFF & PROJECT CONTEXT
## Kaam Konnect (काम कनेक्ट) — The Bridge to Homes
**Problem Statement ID**: 26089  
**Organization**: Ministry of Cooperation | National Council for Cooperative Training (NCCT)  
**Theme**: Agriculture, FoodTech & Rural Development / Cooperative Gig Economy  
**Status**: Fully operational, verified with 9/9 automated tests passing  

---

> **INSTRUCTION FOR THE NEXT AI AGENT**:  
> You are continuing development on **Kaam Konnect**, a cooperative-owned digital service marketplace for household and community services.  
> Read this document completely to understand the problem statement, architecture, completed features, database schema, and how to continue building without asking the user to re-explain anything.

---

## 1. Problem Statement & Mission (NCCT / Ministry of Cooperation)

### Background:
Labour Cooperative Federations and Societies across India possess a large pool of skilled and semi-skilled workers (electricians, plumbers, carpenters, domestic helpers, caregivers, painters, cleaners, technicians, drivers, gardeners). However, they lack a structured digital platform to connect these workers with households and institutions. Private platforms extract ~25% to 30% commission, treat workers as expendable gig units without social security, and control wages.

### Core Cooperative Differentiators (Built into this Codebase):
1. **Low & Fair Tariff (5% + 5% vs 25% Private Giants)**:
   - **5% from Worker**: Reinvested directly into portable skill certifications (NCCT / NSDC) and group insurance/welfare.
   - **5% from Household**: Non-profit cooperative platform maintenance.
2. **We Do Not Employ Workers (Direct Customer-to-Worker Payment)**:
   - Customers pay workers directly via Cash or UPI upon job completion.
3. **Dual Independent Confirmation Workflow (Dispute Prevention)**:
   - A booking is closed as `Completed` **only** after both:
     - Customer triggers `"Confirm Work Done"` (`work_confirmed_by_customer = 1`)
     - Worker triggers `"Confirm Payment Received"` (`payment_confirmed_by_worker = 1`)
   - If work is done but unpaid, or paid but work unconfirmed, the intermediate state is explicitly surfaced.
4. **Fair Wage Benchmarking**:
   - Compares worker rates against official NCCT urban wage standards (`₹350 - ₹550/hr`).
5. **Configurable GST Calculation**:
   - **Intra-State (Same State)**: CGST 0.25% + SGST 0.25% = **0.50% total GST**.
   - **Inter-State (Different State)**: IGST = **0.50% total GST**.
   - Tax rates stored as configurable values in SQLite `tax_config` table.
6. **Pluggable Government e-KYC**:
   - Validates 12-digit Aadhaar format with the authentic **Verhoeff algorithmic checksum**.
   - Modular architecture (`BaseKYCProvider`) so a live UIDAI/DigiLocker gateway can be swapped in without code refactoring.
7. **Verified Government Schemes Matching Engine**:
   - Evaluates worker eligibility against 6 verified statutory schemes: **e-Shram (NDUW)**, **PM-SYM (Pension)**, **PMSBY (Accident)**, **PMJJBY (Life)**, **PM-JAY (Ayushman Bharat)**, and **State BOCW Welfare Boards**.
   - Direct links to official portals (`https://eshram.gov.in`, `https://maandhan.in`, `https://pmjay.gov.in`).
8. **Visible Helpdesk & Support**:
   - Toll-free helpline `1800-266-0088`, email `support@kaamkonnect.coop.in`, and tracked callback ticketing.

---

## 2. Directory Structure & File Map

```
KaamKonnect/
├── app.py                 # Core Flask backend (REST API, session auth, routing)
├── database.py            # SQLite schema initialization, connection helpers, seed data
├── kyc_service.py         # Pluggable Aadhaar e-KYC service with Verhoeff algorithmic check
├── tax_service.py         # Configurable GST engine (Intra 0.5% vs Inter 0.5%) & fair wages
├── scheme_engine.py       # Verified Indian statutory welfare schemes evaluator
├── test_platform.py       # Comprehensive automated test suite (9 tests covering full lifecycle)
├── requirements.txt       # Python dependencies (flask>=3.0.0)
├── run.bat                # 1-Click Windows launch script
├── README.md              # High-level overview and setup guide
├── AI_HANDOFF.md          # THIS FILE - Complete context and instructions for AI agents
├── kaam_konnect.db        # SQLite database (pre-seeded with Delhi NCR data)
├── static/
│   ├── css/
│   │   └── style.css      # Professional responsive CSS styling (Cooperative Teal & Saffron palette)
│   └── js/
│       └── app.js         # Unified client application: auth state machine, Leaflet map, booking engine
└── templates/
    └── index.html         # Unified web interface (Dedicated Login Gateway + Authenticated Dashboards)
```

---

## 3. Pre-Seeded Demonstration Personas

You can log into any of these accounts with 1-click or via their credentials:

| Persona | Role | State / Location | Trade / Skill | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Priya Sharma** | Customer | Delhi (Saket) | — | Use to test **Intra-State GST** (Delhi &rarr; Delhi: CGST 0.25% + SGST 0.25%) |
| **Anand Verma** | Customer | Haryana (Gurugram) | — | Use to test **Inter-State GST** (Haryana &rarr; Delhi: IGST 0.50%) |
| **Ramesh Kumar** | Worker | Delhi (South Delhi) | Electrician | 9 yrs exp, 4.9 rating, NCCT Certified, Rate: ₹380/hr |
| **Sunita Devi** | Worker | Delhi (Kotla) | Domestic Helper | 7 yrs exp, 4.8 rating, e-Shram registered, Rate: ₹300/hr |
| **Manoj Chauhan** | Worker | Haryana (Gurugram) | Plumber | 6 yrs exp, 4.85 rating, NSDC licensed, Rate: ₹420/hr |

---

## 4. How the Application Works

### Flow A: Unauthenticated State (Primary Landing Screen)
- Loading `http://127.0.0.1:5000/` displays the **Dedicated Login & Registration Gateway** (`#gateway-section`).
- User selects between:
  - **👤 Customer Portal** (Sign In or Register with Aadhaar e-KYC)
  - **👷 Worker Portal** (Sign In or Register with trade, experience, hourly rate, and Aadhaar e-KYC)
- User can also click any of the **1-Click Demo Personas** to immediately sign in without typing.

### Flow B: Authenticated Dashboards (`#authenticated-section`)
Once logged in:
- Header displays user avatar, name, role badge, masked Aadhaar (`XXXX-XXXX-1122`), and a **"🚪 Sign Out / Switch Portal"** button.
- **Customer View (Role Isolation)**:
  - When a customer interface is opened, the **Worker Portal** and **Govt Welfare Schemes** tabs are completely removed/hidden (`style.display = 'none'` and `.role-customer` CSS rules).
  - The customer only sees **Find Workers & Map** and **My Bookings**.
  - Interactive Leaflet.js OpenStreetMap centered on Delhi NCR with worker pins.
  - Filters: trade category, radius slider (2km to 35km), minimum rating, max hourly rate.
  - Worker cards with NCCT verification badges, hourly rates, and fair wage status.
  - Booking Modal: dynamically calls `/api/bookings/quote` to calculate exact tax breakdown (CGST+SGST vs IGST) before confirmation.
- **Worker View (Role Isolation)**:
  - When a worker interface is opened, the **Find Workers & Map** and **My Bookings** tabs are completely removed/hidden (`style.display = 'none'` and `.role-worker` CSS rules).
  - The worker only sees **Worker Portal** and **Govt Welfare Schemes**.
  - Availability toggle (Online / Busy).
  - Incoming requests queue (`Accept` / `Decline`) and active jobs feed right inside the Worker Portal.
  - Active job milestones with action buttons (`Start Job`, `Mark Work Completed`, `Confirm Payment Received`, `Rate Customer`).
  - Portable Certifications list.
  - Diagnostic questionnaire (Age, Monthly Income, Trade, State, EPFO/ESIC status) evaluating worker against e-Shram, PM-SYM, PMSBY, PMJJBY, PM-JAY, BOCW.

---

## 5. API Endpoints Reference

- `POST /api/auth/login`: `{ identifier: string, role: string }` &rarr; Authenticates user with role check.
- `POST /api/auth/register`: `{ role, name, phone, email, state, city, address, id_number, [primary_skill, etc.] }` &rarr; Validates Aadhaar format/Verhoeff checksum and registers user.
- `POST /api/auth/verify-kyc`: `{ id_type, id_number, full_name, phone }` &rarr; Standalone Aadhaar e-KYC validator.
- `GET /api/auth/users`: Returns seeded demo accounts list.
- `GET /api/workers/discover?category=...&lat=...&lng=...&radius=...&min_rating=...&max_price=...`: Geospatial search.
- `POST /api/bookings/quote`: `{ base_amount, customer_state, worker_state }` &rarr; Computes GST (Intra vs Inter), 5% skill fund, 5% fee, total.
- `POST /api/bookings/create`: Customer initiates booking.
- `GET /api/bookings/my?user_id=...&role=...`: Returns user bookings with confirmation status.
- `POST /api/bookings/<id>/action`: `{ action: "accept" | "reject" | "start" | "mark_completed" | "confirm_work_customer" | "confirm_payment_worker" | "cancel" }`.
- `POST /api/ratings/submit`: Two-way rating submission unlocked upon `Completed` state.
- `POST /api/schemes/evaluate`: Evaluates worker eligibility against statutory welfare schemes.
- `GET /api/admin/metrics`: Federation fund metrics and unaligned confirmation disputes.
- `POST /api/admin/tax-config`: Updates configurable GST and commission rates.
- `POST /api/support/callback`: Creates tracked support ticket.

---

## 6. How to Run & Verify

1. **Start the Platform**:
   ```powershell
   python app.py
   ```
   *(Server starts on `http://127.0.0.1:5000`)*

2. **Run All Automated Tests**:
   ```powershell
   python test_platform.py
   ```
   *(9 unit/integration tests verifying auth, GST math, dual confirmation, and scheme matching)*

3. **Re-seed Database (if needed)**:
   ```powershell
   python database.py
   ```

---

## 7. Recommended Next Steps for Future AI Agents

If the user asks you to continue developing or add new features, consider:
1. **Payment Gateway Simulation**: Adding a mock UPI QR code modal during payment confirmation (e.g. Razorpay sandbox or BHIM UPI cooperative QR).
2. **SMS / WhatsApp Notification Service**: Simulating automated job dispatch SMS in regional languages.
3. **Offline Mode / PWA**: Adding a ServiceWorker and web manifest for mobile installation.
4. **Additional Languages**: Expanding Hindi dictionary to Bengali, Marathi, and Tamil.
