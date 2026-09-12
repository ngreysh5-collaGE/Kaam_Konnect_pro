"""
Kaam Konnect - Backend Server & API Engine
Problem Statement ID: 26089
Ministry of Cooperation | National Council for Cooperative Training (NCCT)
Tagline: "The bridge to homes"
"""

import os
import math
import json
import sqlite3
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_from_directory

from database import get_db_connection, init_db, seed_data
from kyc_service import kyc_manager, SandboxAadhaarProvider
from tax_service import calculate_booking_breakdown, evaluate_wage_benchmark, get_tax_config, update_tax_config
from scheme_engine import evaluate_worker_eligibility, STATUTORY_SCHEMES

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = "kaam-konnect-coop-secret-key-2026"

# Ensure DB initialized on startup
init_db()
seed_data()


# -------------------------------------------------------------
# HELPER UTILITIES
# -------------------------------------------------------------
def haversine_distance_km(lat1, lon1, lat2, lon2):
    """Compute distance between two geographical points in kilometers."""
    R = 6371.0 # Earth's radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)


# -------------------------------------------------------------
# WEB PAGE ROUTES
# -------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# -------------------------------------------------------------
# AUTHENTICATION & KYC APIS
# -------------------------------------------------------------
@app.route("/api/auth/users", methods=["GET"])
def list_demo_users():
    """List pre-seeded demo users for immediate role switching."""
    conn = get_db_connection()
    users = conn.execute("""
        SELECT u.id, u.role, u.name, u.phone, u.email, u.state, u.city, u.address,
               u.kyc_status, u.kyc_id_masked,
               w.id as worker_id, w.primary_skill, w.cooperative_society_name, w.hourly_rate
        FROM users u
        LEFT JOIN workers w ON u.id = w.user_id
        ORDER BY u.id ASC
    """).fetchall()
    conn.close()
    return jsonify([dict(u) for u in users])


@app.route("/api/auth/verify-kyc", methods=["POST"])
def verify_kyc():
    """Verify Aadhaar or Govt ID using pluggable KYC service."""
    data = request.get_json() or {}
    id_type = data.get("id_type", "Aadhaar")
    id_number = data.get("id_number", "")
    full_name = data.get("full_name", "")
    phone = data.get("phone", "")

    result = kyc_manager.verify(id_type, id_number, full_name, phone)
    return jsonify(result)


@app.route("/api/auth/login", methods=["POST"])
def login():
    """Sign-in for Customer, Worker, or Admin with role verification."""
    data = request.get_json() or {}
    identifier = data.get("identifier", "").strip()
    role = data.get("role", "").strip() # 'customer', 'worker', or 'admin'

    if not identifier:
        return jsonify({"error": "Phone number or email is required to sign in."}), 400

    conn = get_db_connection()
    user = conn.execute("""
        SELECT u.*, w.id as worker_id, w.primary_skill, w.cooperative_society_name, w.hourly_rate
        FROM users u
        LEFT JOIN workers w ON u.id = w.user_id
        WHERE (LOWER(u.email) = LOWER(?) OR u.phone = ? OR u.phone = ?)
    """, (identifier, identifier, f"+91{identifier.replace(' ', '')}")).fetchone()
    conn.close()

    if not user:
        return jsonify({
            "error": "Account not found",
            "message": "No account matched this mobile number or email. Please register your account with government ID verification."
        }), 404

    user_dict = dict(user)
    if role and user_dict["role"] != role:
        return jsonify({
            "error": "Role mismatch",
            "message": f"This account is registered as '{user_dict['role'].capitalize()}', not '{role.capitalize()}'. Please select the correct portal login."
        }), 403

    return jsonify({
        "message": f"Welcome back, {user_dict['name']}!",
        "user": user_dict
    })


@app.route("/api/auth/register", methods=["POST"])
def register():
    """Register Customer or Worker with KYC verification check."""
    data = request.get_json() or {}
    role = data.get("role")
    if role not in ["customer", "worker"]:
        return jsonify({"error": "Invalid role. Must be 'customer' or 'worker'."}), 400

    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    email = data.get("email", "").strip()
    state = data.get("state", "").strip()
    city = data.get("city", "").strip()
    address = data.get("address", "").strip()
    id_number = data.get("id_number", "").strip()

    if not (name and phone and email and state and city and address and id_number):
        return jsonify({"error": "All profile and identity fields are required."}), 400

    # Execute KYC validation
    kyc_result = kyc_manager.verify("Aadhaar", id_number, name, phone)
    if not kyc_result.get("is_verified"):
        return jsonify({
            "error": "Government ID verification failed",
            "details": kyc_result.get("message")
        }), 422

    now_str = datetime.now().isoformat()
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO users (role, name, phone, email, state, city, address, kyc_status, kyc_type, kyc_id_masked, kyc_verified_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'verified', 'Aadhaar', ?, ?, ?)
        """, (role, name, phone, email, state, city, address, kyc_result["masked_id"], now_str, now_str))
        user_id = cursor.lastrowid

        worker_id = None
        if role == "worker":
            coop_name = data.get("cooperative_society_name", "District Labour Welfare Cooperative Society")
            primary_skill = data.get("primary_skill", "Electrician")
            sec_skills = data.get("secondary_skills", "")
            exp_years = int(data.get("experience_years", 3))
            hourly_rate = float(data.get("hourly_rate", 380.0))
            bio = data.get("bio", f"Cooperative skilled {primary_skill} with verified credentials.")
            lat = float(data.get("latitude", 28.5355))
            lng = float(data.get("longitude", 77.2185))

            cursor.execute("""
            INSERT INTO workers (user_id, cooperative_society_name, primary_skill, secondary_skills, experience_years, hourly_rate, bio, latitude, longitude, is_available, jobs_completed, avg_rating, rating_count, response_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, 5.0, 0, 100.0)
            """, (user_id, coop_name, primary_skill, sec_skills, exp_years, hourly_rate, bio, lat, lng))
            worker_id = cursor.lastrowid

            # Add sample default certification
            cursor.execute("""
            INSERT INTO certifications (worker_id, title, issuing_body, issue_date, certificate_number, is_verified)
            VALUES (?, ?, 'National Council for Cooperative Training (NCCT)', ?, ?, 1)
            """, (worker_id, f"Verified {primary_skill} Skill Certificate", now_str[:10], f"NCCT-VER-{worker_id}-2026"))

            # Create default scheme profile
            cursor.execute("""
            INSERT INTO worker_eligibility_profiles (worker_id, age, monthly_income, occupation, state, has_epfo_esic, existing_schemes_json, last_assessed_at)
            VALUES (?, 32, 16000.0, ?, ?, 0, '[]', ?)
            """, (worker_id, primary_skill, state, now_str))

        conn.commit()
        return jsonify({
            "message": "Registration & KYC verification successful",
            "user": {
                "id": user_id,
                "role": role,
                "name": name,
                "email": email,
                "phone": phone,
                "state": state,
                "city": city,
                "worker_id": worker_id,
                "kyc_id_masked": kyc_result["masked_id"]
            }
        })
    except sqlite3.IntegrityError as e:
        return jsonify({"error": f"Email or phone already registered: {str(e)}"}), 409
    finally:
        conn.close()


# -------------------------------------------------------------
# WORKER DISCOVERY & GEOSPATIAL SEARCH
# -------------------------------------------------------------
@app.route("/api/workers/discover", methods=["GET"])
def discover_workers():
    """Geospatial search and ranking of cooperative workers."""
    category = request.args.get("category", "").strip()
    client_lat = float(request.args.get("lat", 28.5355)) # Default to South Delhi Saket center
    client_lng = float(request.args.get("lng", 77.2185))
    radius_km = float(request.args.get("radius", 25.0))
    min_rating = float(request.args.get("min_rating", 0.0))
    max_price = float(request.args.get("max_price", 2000.0))
    available_only = request.args.get("available_only", "0") == "1"

    conn = get_db_connection()
    query = """
    SELECT w.*, u.name, u.phone, u.email, u.state, u.city, u.address, u.kyc_status, u.kyc_id_masked
    FROM workers w
    JOIN users u ON w.user_id = u.id
    WHERE w.hourly_rate <= ?
      AND w.avg_rating >= ?
    """
    params = [max_price, min_rating]

    if category and category != "All":
        query += " AND (w.primary_skill = ? OR w.secondary_skills LIKE ?)"
        params.extend([category, f"%{category}%"])

    if available_only:
        query += " AND w.is_available = 1"

    workers_rows = conn.execute(query, params).fetchall()
    
    # Fetch certifications for all
    certs_by_worker = {}
    certs_rows = conn.execute("SELECT * FROM certifications WHERE is_verified = 1").fetchall()
    for c in certs_rows:
        wid = c["worker_id"]
        certs_by_worker.setdefault(wid, []).append(dict(c))

    conn.close()

    matched_workers = []
    for row in workers_rows:
        w_dict = dict(row)
        dist = haversine_distance_km(client_lat, client_lng, w_dict["latitude"], w_dict["longitude"])
        if dist <= radius_km:
            w_dict["distance_km"] = dist
            w_dict["certifications"] = certs_by_worker.get(w_dict["id"], [])
            w_dict["wage_benchmark"] = evaluate_wage_benchmark(w_dict["primary_skill"], w_dict["hourly_rate"])
            # Rank score: combination of distance (lower is better), rating (higher is better), and response rate
            score = (w_dict["avg_rating"] * 20) + (w_dict["response_rate"] * 0.2) - (dist * 1.2)
            w_dict["match_score"] = round(score, 1)
            matched_workers.append(w_dict)

    # Sort workers by match score descending
    matched_workers.sort(key=lambda x: x["match_score"], reverse=True)

    return jsonify({
        "total_matched": len(matched_workers),
        "center": {"lat": client_lat, "lng": client_lng},
        "radius_km": radius_km,
        "workers": matched_workers
    })


@app.route("/api/workers/<int:worker_id>", methods=["GET"])
def get_worker_detail(worker_id):
    """Retrieve full worker profile, stats, certifications, and reviews."""
    conn = get_db_connection()
    worker = conn.execute("""
    SELECT w.*, u.name, u.phone, u.email, u.state, u.city, u.address, u.kyc_status, u.kyc_id_masked
    FROM workers w
    JOIN users u ON w.user_id = u.id
    WHERE w.id = ?
    """, (worker_id,)).fetchone()

    if not worker:
        conn.close()
        return jsonify({"error": "Worker not found"}), 404

    certs = conn.execute("SELECT * FROM certifications WHERE worker_id = ?", (worker_id,)).fetchall()
    
    # Reviews received by this worker
    reviews = conn.execute("""
    SELECT r.*, u.name as reviewer_name, b.service_type, b.booking_code
    FROM ratings r
    JOIN bookings b ON r.booking_id = b.id
    JOIN users u ON r.from_user_id = u.id
    WHERE r.to_user_id = ? AND r.rating_type = 'customer_to_worker'
    ORDER BY r.created_at DESC
    """, (worker["user_id"],)).fetchall()

    conn.close()

    result = dict(worker)
    result["certifications"] = [dict(c) for c in certs]
    result["reviews"] = [dict(r) for r in reviews]
    result["wage_benchmark"] = evaluate_wage_benchmark(worker["primary_skill"], worker["hourly_rate"])
    return jsonify(result)


# -------------------------------------------------------------
# BOOKING LIFECYCLE & DUAL INDEPENDENT CONFIRMATION ENGINE
# -------------------------------------------------------------
@app.route("/api/bookings/quote", methods=["POST"])
def get_booking_quote():
    """Calculate pre-booking tax, cooperative fund, and total breakdown."""
    data = request.get_json() or {}
    base_amount = float(data.get("base_amount", 500.0))
    customer_state = data.get("customer_state", "Delhi")
    worker_state = data.get("worker_state", "Delhi")

    breakdown = calculate_booking_breakdown(base_amount, customer_state, worker_state)
    return jsonify(breakdown)


@app.route("/api/bookings/create", methods=["POST"])
def create_booking():
    """Customer initiates a new booking request."""
    data = request.get_json() or {}
    customer_id = data.get("customer_id")
    worker_id = data.get("worker_id")
    service_type = data.get("service_type")
    scheduled_time = data.get("scheduled_time")
    notes = data.get("notes", "")
    base_amount = float(data.get("base_amount", 400.0))

    if not (customer_id and worker_id and service_type and scheduled_time):
        return jsonify({"error": "Missing mandatory booking fields."}), 400

    conn = get_db_connection()
    cust = conn.execute("SELECT state FROM users WHERE id = ?", (customer_id,)).fetchone()
    worker = conn.execute("""
        SELECT w.id, u.state
        FROM workers w
        JOIN users u ON w.user_id = u.id
        WHERE w.id = ?
    """, (worker_id,)).fetchone()

    if not cust or not worker:
        conn.close()
        return jsonify({"error": "Customer or Worker record not found"}), 404

    breakdown = calculate_booking_breakdown(base_amount, cust["state"], worker["state"])
    
    booking_code = f"KK-{datetime.now().strftime('%Y%m%d')}-{int(datetime.now().timestamp()) % 10000}"
    now_str = datetime.now().isoformat()

    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO bookings (
        booking_code, customer_id, worker_id, service_type, scheduled_time, notes,
        base_amount, tax_type, tax_rate, tax_amount, worker_fund_contribution, platform_fee, total_payable,
        customer_state, worker_state, status,
        work_confirmed_by_customer, payment_confirmed_by_worker,
        created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Requested', 0, 0, ?, ?)
    """, (
        booking_code, customer_id, worker_id, service_type, scheduled_time, notes,
        breakdown["base_amount"], breakdown["tax_type"], breakdown["tax_rate"],
        breakdown["tax_amount"], breakdown["worker_fund_contribution"],
        breakdown["platform_fee"], breakdown["total_payable"],
        breakdown["customer_state"], breakdown["worker_state"],
        now_str, now_str
    ))
    booking_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        "message": "Booking request successfully submitted.",
        "booking_id": booking_id,
        "booking_code": booking_code,
        "status": "Requested",
        "breakdown": breakdown
    }), 201


@app.route("/api/bookings/my", methods=["GET"])
def get_my_bookings():
    """Retrieve bookings for active user filtered by their role."""
    user_id = request.args.get("user_id", type=int)
    role = request.args.get("role", "customer")

    if not user_id:
        return jsonify({"error": "user_id is required"}), 400

    conn = get_db_connection()
    if role == "worker":
        # Worker sees jobs assigned to their worker record
        worker_rec = conn.execute("SELECT id FROM workers WHERE user_id = ?", (user_id,)).fetchone()
        if not worker_rec:
            conn.close()
            return jsonify([])
        bookings = conn.execute("""
            SELECT b.*,
                   w.user_id as worker_user_id,
                   cu.name as customer_name, cu.phone as customer_phone, cu.address as customer_address,
                   wu.name as worker_name, wu.phone as worker_phone,
                   w.primary_skill
            FROM bookings b
            JOIN users cu ON b.customer_id = cu.id
            JOIN workers w ON b.worker_id = w.id
            JOIN users wu ON w.user_id = wu.id
            WHERE b.worker_id = ?
            ORDER BY b.id DESC
        """, (worker_rec["id"],)).fetchall()
    else:
        # Customer sees their bookings
        bookings = conn.execute("""
            SELECT b.*,
                   w.user_id as worker_user_id,
                   cu.name as customer_name, cu.phone as customer_phone, cu.address as customer_address,
                   wu.name as worker_name, wu.phone as worker_phone,
                   w.primary_skill, w.cooperative_society_name
            FROM bookings b
            JOIN users cu ON b.customer_id = cu.id
            JOIN workers w ON b.worker_id = w.id
            JOIN users wu ON w.user_id = wu.id
            WHERE b.customer_id = ?
            ORDER BY b.id DESC
        """, (user_id,)).fetchall()

    # Check rating completion status for each booking
    results = []
    for row in bookings:
        b_dict = dict(row)
        b_id = b_dict["id"]
        ratings = conn.execute("SELECT rating_type, score FROM ratings WHERE booking_id = ?", (b_id,)).fetchall()
        b_dict["ratings_submitted"] = [r["rating_type"] for r in ratings]
        results.append(b_dict)

    conn.close()
    return jsonify(results)


@app.route("/api/bookings/<int:booking_id>/action", methods=["POST"])
def booking_action(booking_id):
    """
    Execute booking lifecycle transitions with independent dual confirmation.
    Supported actions:
    - accept (Worker)
    - reject (Worker)
    - start (Worker)
    - mark_completed (Worker signals job finished)
    - confirm_work_customer (Customer triggers 'Confirm Work Done')
    - confirm_payment_worker (Worker triggers 'Confirm Payment Received')
    - cancel (Customer or Worker)
    """
    data = request.get_json() or {}
    action = data.get("action")
    actor_user_id = data.get("user_id")
    reason = data.get("reason", "")
    now_str = datetime.now().isoformat()

    conn = get_db_connection()
    b = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not b:
        conn.close()
        return jsonify({"error": "Booking not found"}), 404

    current_status = b["status"]
    work_confirmed = b["work_confirmed_by_customer"]
    payment_confirmed = b["payment_confirmed_by_worker"]

    new_status = current_status
    updated_fields = {"updated_at": now_str}

    if action == "accept":
        if current_status != "Requested":
            conn.close()
            return jsonify({"error": f"Cannot accept booking in state '{current_status}'"}), 400
        new_status = "Accepted"

    elif action == "reject":
        if current_status not in ["Requested", "Accepted"]:
            conn.close()
            return jsonify({"error": f"Cannot reject booking in state '{current_status}'"}), 400
        new_status = "Cancelled"
        updated_fields["cancel_reason"] = reason or "Declined by worker"

    elif action == "start":
        if current_status != "Accepted":
            conn.close()
            return jsonify({"error": f"Cannot start booking in state '{current_status}'"}), 400
        new_status = "In Progress"

    elif action == "mark_completed":
        # Worker indicates work is finished on their side
        if current_status not in ["In Progress", "Accepted"]:
            conn.close()
            return jsonify({"error": f"Cannot mark completed from '{current_status}'"}), 400
        new_status = "Work Completed - Pending Customer Confirmation"

    elif action == "confirm_work_customer":
        # Dedicated action in Customer view: "Confirm Work Done"
        work_confirmed = 1
        updated_fields["work_confirmed_by_customer"] = 1
        updated_fields["work_confirmed_at"] = now_str
        
        # Check if worker has also confirmed payment
        if payment_confirmed == 1:
            new_status = "Completed"
        else:
            # Payment pending
            new_status = "Work Completed - Pending Customer Confirmation"

    elif action == "confirm_payment_worker":
        # Dedicated action in Worker view: "Confirm Payment Received"
        payment_confirmed = 1
        updated_fields["payment_confirmed_by_worker"] = 1
        updated_fields["payment_confirmed_at"] = now_str

        # Check if customer has confirmed work
        if work_confirmed == 1:
            new_status = "Completed"
        else:
            # Work done confirmation from customer is still pending
            new_status = "Work Completed - Pending Customer Confirmation"

    elif action == "cancel":
        if current_status in ["Completed", "Cancelled"]:
            conn.close()
            return jsonify({"error": "Cannot cancel finished or already cancelled booking."}), 400
        new_status = "Cancelled"
        updated_fields["cancel_reason"] = reason or "Cancelled by user"

    else:
        conn.close()
        return jsonify({"error": f"Unknown action '{action}'"}), 400

    updated_fields["status"] = new_status

    # Construct update query
    set_clauses = [f"{k} = ?" for k in updated_fields.keys()]
    values = list(updated_fields.values()) + [booking_id]

    conn.execute(f"UPDATE bookings SET {', '.join(set_clauses)} WHERE id = ?", values)

    # If completed, increment worker jobs_completed
    if new_status == "Completed" and current_status != "Completed":
        conn.execute("UPDATE workers SET jobs_completed = jobs_completed + 1 WHERE id = ?", (b["worker_id"],))

    conn.commit()
    conn.close()

    return jsonify({
        "message": f"Action '{action}' processed successfully.",
        "booking_id": booking_id,
        "status": new_status,
        "work_confirmed_by_customer": work_confirmed,
        "payment_confirmed_by_worker": payment_confirmed,
        "is_fully_completed": (new_status == "Completed")
    })


# -------------------------------------------------------------
# TWO-WAY RATINGS API
# -------------------------------------------------------------
@app.route("/api/ratings/submit", methods=["POST"])
def submit_rating():
    """Two-way rating submission unlocked once booking is Completed."""
    data = request.get_json() or {}
    booking_id = data.get("booking_id")
    rating_type = data.get("rating_type") # 'customer_to_worker' or 'worker_to_customer'
    score = int(data.get("score", 5))
    safety_score = int(data.get("aspect_score_safety", 5))
    punctuality_score = int(data.get("aspect_score_punctuality", 5))
    comments = data.get("comments", "")
    now_str = datetime.now().isoformat()

    if not booking_id or not rating_type:
        return jsonify({"error": "Missing booking_id or rating_type"}), 400

    conn = get_db_connection()
    b = conn.execute("""
        SELECT b.id, b.status, b.customer_id, b.worker_id, w.user_id as worker_user_id
        FROM bookings b
        JOIN workers w ON b.worker_id = w.id
        WHERE b.id = ?
    """, (booking_id,)).fetchone()

    if not b:
        conn.close()
        return jsonify({"error": "Booking not found"}), 404

    if b["status"] != "Completed":
        conn.close()
        return jsonify({"error": "Ratings are only allowed after the booking is fully Completed by both parties."}), 403

    if rating_type == "customer_to_worker":
        real_from_user_id = b["customer_id"]
        real_to_user_id = b["worker_user_id"]
        worker_record_id = b["worker_id"]
    elif rating_type == "worker_to_customer":
        real_from_user_id = b["worker_user_id"]
        real_to_user_id = b["customer_id"]
        worker_record_id = b["worker_id"]
    else:
        conn.close()
        return jsonify({"error": "Invalid rating_type. Must be 'customer_to_worker' or 'worker_to_customer'."}), 400

    # Explicit check if already submitted for clean status
    existing = conn.execute(
        "SELECT id FROM ratings WHERE booking_id = ? AND rating_type = ?",
        (booking_id, rating_type)
    ).fetchone()
    if existing:
        conn.close()
        return jsonify({"error": "Rating for this booking has already been submitted."}), 409

    try:
        conn.execute("""
        INSERT INTO ratings (booking_id, from_user_id, to_user_id, rating_type, score, aspect_score_safety, aspect_score_punctuality, comments, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (booking_id, real_from_user_id, real_to_user_id, rating_type, score, safety_score, punctuality_score, comments, now_str))

        # If customer rated worker, recalculate worker's public average rating
        if rating_type == "customer_to_worker":
            calc = conn.execute("""
            SELECT AVG(score) as avg_s, COUNT(*) as cnt
            FROM ratings
            WHERE to_user_id = ? AND rating_type = 'customer_to_worker'
            """, (real_to_user_id,)).fetchone()
            new_avg = round(calc["avg_s"] or 5.0, 2)
            new_cnt = calc["cnt"] or 0
            conn.execute("UPDATE workers SET avg_rating = ?, rating_count = ? WHERE id = ?", (new_avg, new_cnt, worker_record_id))

        conn.commit()
        conn.close()
        return jsonify({
            "message": "Rating successfully recorded. Thank you for fostering a trusted community!",
            "booking_id": booking_id,
            "rating_type": rating_type,
            "score": score
        })
    except sqlite3.IntegrityError as e:
        conn.close()
        if "UNIQUE constraint failed" in str(e):
            return jsonify({"error": "Rating for this booking has already been submitted."}), 409
        return jsonify({"error": f"Rating submission error: {str(e)}"}), 400


# -------------------------------------------------------------
# GOVERNMENT WELFARE SCHEMES APIS
# -------------------------------------------------------------
@app.route("/api/schemes/statutory-list", methods=["GET"])
def get_statutory_schemes():
    """Return all curated, verified statutory welfare schemes with criteria & official links."""
    return jsonify(STATUTORY_SCHEMES)


@app.route("/api/schemes/evaluate", methods=["POST"])
def evaluate_schemes():
    """Evaluate worker profile against verified statutory schemes."""
    data = request.get_json() or {}
    results = evaluate_worker_eligibility(data)
    return jsonify({
        "evaluated_at": datetime.now().isoformat(),
        "total_schemes": len(results),
        "schemes": results
    })


@app.route("/api/schemes/my-profile/<int:worker_id>", methods=["GET", "POST"])
def worker_scheme_profile(worker_id):
    """Retrieve or save worker welfare eligibility profile."""
    conn = get_db_connection()
    if request.method == "POST":
        data = request.get_json() or {}
        age = int(data.get("age", 30))
        income = float(data.get("monthly_income", 15000.0))
        occupation = data.get("occupation", "Electrician")
        state = data.get("state", "Delhi")
        has_epfo = int(bool(data.get("has_epfo_esic", False)))
        existing = data.get("existing_schemes", [])
        if isinstance(existing, list):
            existing_json = json.dumps(existing)
        else:
            existing_json = str(existing)

        now_str = datetime.now().isoformat()
        conn.execute("""
        INSERT INTO worker_eligibility_profiles (worker_id, age, monthly_income, occupation, state, has_epfo_esic, existing_schemes_json, last_assessed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(worker_id) DO UPDATE SET
            age = excluded.age,
            monthly_income = excluded.monthly_income,
            occupation = excluded.occupation,
            state = excluded.state,
            has_epfo_esic = excluded.has_epfo_esic,
            existing_schemes_json = excluded.existing_schemes_json,
            last_assessed_at = excluded.last_assessed_at
        """, (worker_id, age, income, occupation, state, has_epfo, existing_json, now_str))
        conn.commit()

    profile = conn.execute("SELECT * FROM worker_eligibility_profiles WHERE worker_id = ?", (worker_id,)).fetchone()
    conn.close()

    if not profile:
        return jsonify({
            "age": 32,
            "monthly_income": 15000.0,
            "occupation": "Electrician",
            "state": "Delhi",
            "has_epfo_esic": 0,
            "existing_schemes": []
        })

    p_dict = dict(profile)
    try:
        p_dict["existing_schemes"] = json.loads(p_dict.get("existing_schemes_json") or "[]")
    except Exception:
        p_dict["existing_schemes"] = []
    return jsonify(p_dict)


# -------------------------------------------------------------
# COOPERATIVE FEDERATION ADMIN APIS
# -------------------------------------------------------------
@app.route("/api/admin/metrics", methods=["GET"])
def get_admin_metrics():
    """Cooperative Federation oversight: welfare fund, fair wage compliance, disputes."""
    conn = get_db_connection()
    
    total_workers = conn.execute("SELECT COUNT(*) FROM workers").fetchone()[0]
    verified_workers = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'worker' AND kyc_status = 'verified'").fetchone()[0]
    total_bookings = conn.execute("SELECT COUNT(*) FROM bookings").fetchone()[0]
    completed_bookings = conn.execute("SELECT COUNT(*) FROM bookings WHERE status = 'Completed'").fetchone()[0]
    
    # 5% Worker Skill & Welfare Fund accumulated
    fund_res = conn.execute("SELECT SUM(worker_fund_contribution) FROM bookings WHERE status = 'Completed'").fetchone()[0]
    total_welfare_fund = round(fund_res or 0.0, 2)

    # Platform revenue
    platform_res = conn.execute("SELECT SUM(platform_fee) FROM bookings WHERE status = 'Completed'").fetchone()[0]
    total_platform_fee = round(platform_res or 0.0, 2)

    # Disputed or unaligned confirmations:
    # 1. Work done by customer confirmed, but worker payment unconfirmed
    # 2. Payment confirmed by worker, but customer work unconfirmed
    disputes = conn.execute("""
        SELECT b.*, cu.name as customer_name, wu.name as worker_name
        FROM bookings b
        JOIN users cu ON b.customer_id = cu.id
        JOIN workers w ON b.worker_id = w.id
        JOIN users wu ON w.user_id = wu.id
        WHERE (b.work_confirmed_by_customer = 1 AND b.payment_confirmed_by_worker = 0)
           OR (b.work_confirmed_by_customer = 0 AND b.payment_confirmed_by_worker = 1)
    """).fetchall()

    # Fair wage compliance rate
    workers_all = conn.execute("SELECT primary_skill, hourly_rate FROM workers").fetchall()
    compliant_count = sum(
        1 for w in workers_all
        if evaluate_wage_benchmark(w["primary_skill"], w["hourly_rate"])["status"] in ["FAIR_WAGE_COMPLIANT", "PREMIUM_SPECIALIST"]
    )
    compliance_rate = round((compliant_count / max(total_workers, 1)) * 100, 1)

    # Current tax configuration
    tax_cfg = get_tax_config()

    conn.close()

    return jsonify({
        "total_workers": total_workers,
        "verified_workers": verified_workers,
        "total_bookings": total_bookings,
        "completed_bookings": completed_bookings,
        "total_welfare_fund_collected": total_welfare_fund,
        "total_platform_fee_collected": total_platform_fee,
        "compliance_rate_percent": compliance_rate,
        "disputes_count": len(disputes),
        "disputes": [dict(d) for d in disputes],
        "tax_config": tax_cfg
    })


@app.route("/api/admin/tax-config", methods=["GET", "POST"])
def manage_tax_config():
    """View and update configurable GST rates & commission fees."""
    if request.method == "POST":
        data = request.get_json() or {}
        cgst = float(data.get("cgst_rate", 0.0025))
        sgst = float(data.get("sgst_rate", 0.0025))
        igst = float(data.get("igst_rate", 0.0050))
        worker_contrib = float(data.get("worker_contribution_rate", 0.05))
        platform_fee = float(data.get("platform_fee_rate", 0.05))
        update_tax_config(cgst, sgst, igst, worker_contrib, platform_fee)
        return jsonify({"message": "Tax and commission tariff updated successfully."})
    return jsonify(get_tax_config())


# -------------------------------------------------------------
# SUPPORT & CALLBACK TICKETING
# -------------------------------------------------------------
@app.route("/api/support/callback", methods=["POST"])
def request_callback():
    """Submit a callback request for onboarding / verification assistance."""
    data = request.get_json() or {}
    name = data.get("name", "User").strip()
    phone = data.get("phone", "").strip()
    role = data.get("role", "customer").strip()
    issue = data.get("issue_category", "Verification Assistance").strip()
    details = data.get("details", "").strip()

    if not (name and phone):
        return jsonify({"error": "Name and phone are required for callback"}), 400

    ticket_no = f"TCK-{datetime.now().strftime('%Y%m%d')}-{int(datetime.now().timestamp()) % 1000}"
    now_str = datetime.now().isoformat()

    conn = get_db_connection()
    conn.execute("""
    INSERT INTO support_tickets (ticket_number, name, phone, role, issue_category, details, status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, 'open', ?)
    """, (ticket_no, name, phone, role, issue, details, now_str))
    conn.commit()
    conn.close()

    return jsonify({
        "message": "Callback request submitted. An NCCT Cooperative Representative will call you within 15 minutes.",
        "ticket_number": ticket_no,
        "support_phone": "+91 1800 266 0088",
        "support_email": "support@kaamkonnect.coop.in"
    }), 201


if __name__ == "__main__":
    print("Starting Kaam Konnect server on port 5000...")
    app.run(host="0.0.0.0", port=5000, debug=True)
