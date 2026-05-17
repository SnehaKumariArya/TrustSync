from flask import Flask, request, render_template, redirect, url_for, flash, jsonify, session
import sqlite3
import hashlib

app = Flask(__name__)
app.secret_key = "trustsync_secure_session_token_key"
DB_FILE = "trustsync.db"
API_KEY_SECRET = "TrustSyncSecureToken2026"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # EXTENDED: workers table now includes password hashing and a claimed verification check flag
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS workers (
            id_number TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            profession TEXT NOT NULL,
            total_score INTEGER DEFAULT 5,
            count INTEGER DEFAULT 1,
            password_hash TEXT DEFAULT NULL,
            claimed INTEGER DEFAULT 0
        )
    ''')
    # EXTENDED: reviews table now includes a dispute flag
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT,
            rating INTEGER,
            review_text TEXT,
            disputed INTEGER DEFAULT 0,
            FOREIGN KEY(worker_id) REFERENCES workers(id_number)
        )
    ''')
    conn.commit()
    conn.close()

def hash_password(password):
    """Secures password strings into SHA-256 hex signatures."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def get_trust_status(average_score):
    if average_score >= 4.5:
        return "Highly Trusted", "#10B981"
    elif average_score >= 3.0:
        return "Verified / Average", "#F59E0B"
    else:
        return "High Risk / Flagged", "#EF4444"

def calculate_worker_badge(avg_score, total_reviews):
    if total_reviews >= 4 and avg_score >= 4.6:
        return {"text": "🏆 Top Rated", "bg": "bg-amber-50 text-amber-700 border-amber-200"}
    elif total_reviews <= 2 and avg_score >= 4.5:
        return {"text": "⚡ Rising Star", "bg": "bg-blue-50 text-blue-700 border-blue-200"}
    elif avg_score < 2.5:
        return {"text": "⚠️ Under Review", "bg": "bg-rose-50 text-rose-700 border-rose-200"}
    return None

def mask_identity_id(id_string):
    id_clean = str(id_string).strip()
    if len(id_clean) <= 4:
        return "****"
    return f"{'*' * (len(id_clean) - 4)}{id_clean[-4:]}"

def compute_network_stats(directory_list):
    total_workers = len(directory_list)
    if total_workers == 0:
        return {"total": 0, "avg_rating": 5.0, "risk_flags": 0}
    sum_scores = 0
    risk_flags = 0
    for worker in directory_list:
        sum_scores += worker["score"]
        if worker["score"] < 2.5:
            risk_flags += 1
    return {"total": total_workers, "avg_rating": round(sum_scores / total_workers, 2), "risk_flags": risk_flags}

# --- WEB APP DASHBOARD RENDERS ---

@app.route('/')
def index():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM workers")
    rows = cursor.fetchall()
    
    directory = []
    for row in rows:
        avg_score = round(row['total_score'] / row['count'], 1) if row['count'] > 0 else 5.0
        status, color = get_trust_status(avg_score)
        
        cursor.execute("SELECT id, rating, review_text, disputed FROM reviews WHERE worker_id = ?", (row['id_number'],))
        worker_reviews = cursor.fetchall()
        
        directory.append({
            "id": row['id_number'],
            "masked_id": mask_identity_id(row['id_number']),
            "name": row['name'],
            "profession": row['profession'],
            "score": avg_score,
            "status": status,
            "color": color,
            "claimed": row['claimed'],
            "total_reviews": row['count'],
            "badge": calculate_worker_badge(avg_score, row['count']),
            "comments": [dict(r) for r in worker_reviews]
        })
    conn.close()
    
    # NEW: Fetch dynamic information if a worker profile session is authenticated
    logged_in_worker = None
    if 'worker_id' in session:
        logged_in_worker = next((w for w in directory if w['id'] == session['worker_id']), None)

    return render_template('index.html', directory=directory, search_result=None, stats=compute_network_stats(directory), logged_in_worker=logged_in_worker)

# --- AUTHENTICATION & DISPUTE CORE ---

@app.route('/claim_profile', methods=['POST'])
def claim_profile():
    """Allows a worker node to attach security credentials to an existing ID profile match."""
    id_number = request.form.get('id_number', '').strip()
    password = request.form.get('password', '').strip()
    
    if not id_number or not password:
        flash("Identity credentials cannot be empty parameters.", "error")
        return redirect(url_for('index'))
        
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT claimed FROM workers WHERE id_number = ?", (id_number,))
    worker = cursor.fetchone()
    
    if not worker:
        flash("Claim verification error: That identification reference is not initialized inside the network registry.", "error")
    elif worker['claimed'] == 1:
        flash("Security violation: This digital workspace profile identity node has already been securely claimed.", "error")
    else:
        # Secure profile node with pass hash credentials
        cursor.execute(
            "UPDATE workers SET password_hash = ?, claimed = 1 WHERE id_number = ?",
            (hash_password(password), id_number)
        )
        conn.commit()
        session['worker_id'] = id_number
        flash("Identity nodes securely linked. Welcome to your private Trust-Sync metric dashboard area!", "success")
        
    conn.close()
    return redirect(url_for('index'))

@app.route('/login', methods=['POST'])
def login_worker():
    id_number = request.form.get('id_number', '').strip()
    password = request.form.get('password', '').strip()
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash, claimed FROM workers WHERE id_number = ?", (id_number,))
    worker = cursor.fetchone()
    conn.close()
    
    if worker and worker['claimed'] == 1 and worker['password_hash'] == hash_password(password):
        session['worker_id'] = id_number
        flash("Worker portal entry successfully validated.", "success")
    else:
        flash("Portal entry rejected: Invalid unique ID string reference or matching security credentials.", "error")
        
    return redirect(url_for('index'))

@app.route('/logout')
def logout_worker():
    session.pop('worker_id', None)
    flash("Worker secure session cleared.", "success")
    return redirect(url_for('index'))

@app.route('/dispute/<int:review_id>', methods=['POST'])
def dispute_review(review_id):
    """Enforces authentication checking prior to updating explicit dispute status tags inside the review log columns."""
    if 'worker_id' not in session:
        flash("Action validation failed: Please authenticate access credentials to complete modifications.", "error")
        return redirect(url_for('index'))
        
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Ensure this review actually belongs to the logged in worker
    cursor.execute("UPDATE reviews SET disputed = 1 WHERE id = ? AND worker_id = ?", (review_id, session['worker_id']))
    conn.commit()
    conn.close()
    
    flash("Review feedback logged as 'Disputed / Under Corporate Compliance Investigation'.", "success")
    return redirect(url_for('index'))

# --- REUSED REGISTRATION & CORE HANDLERS ---

@app.route('/register', methods=['POST'])
def register_worker():
    name = request.form.get('name', '').strip()
    profession = request.form.get('profession', '').strip()
    id_number = request.form.get('id_number', '').strip()
    if not name or not profession or not id_number:
        flash("All fields are required for profile registration.", "error")
        return redirect(url_for('index'))
    conn = sqlite3.connect(DB_FILE)
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO workers (id_number, name, profession, total_score, count, claimed) VALUES (?, ?, ?, 5, 1, 0)", (id_number, name, profession))
        conn.commit()
        cursor.execute("INSERT INTO reviews (worker_id, rating, review_text) VALUES (?, 5, 'Profile initialized on Trust-Sync network.')", (id_number,))
        conn.commit()
        flash(f"Profile initialized successfully for {name}!", "success")
    except sqlite3.IntegrityError:
        flash("Registration failed: This identity identifier key already exists in the registry pool.", "error")
    finally:
        conn.close()
    return redirect(url_for('index'))

@app.route('/check', methods=['POST'])
def check_worker():
    id_number = request.form.get('id_number', '').strip()
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM workers")
    rows = cursor.fetchall()
    
    directory = []
    search_result = None
    for row in rows:
        avg_score = round(row['total_score'] / row['count'], 1) if row['count'] > 0 else 5.0
        status, color = get_trust_status(avg_score)
        cursor.execute("SELECT id, rating, review_text, disputed FROM reviews WHERE worker_id = ?", (row['id_number'],))
        w_revs = [dict(r) for r in cursor.fetchall()]
        
        item = {
            "id": row['id_number'], "masked_id": mask_identity_id(row['id_number']), "name": row['name'],
            "profession": row['profession'], "score": avg_score, "status": status, "color": color,
            "claimed": row['claimed'], "total_reviews": row['count'], "badge": calculate_worker_badge(avg_score, row['count']),
            "comments": w_revs
        }
        directory.append(item)
        if row['id_number'] == id_number:
            search_result = item

    if not search_result and id_number:
        search_result = {"not_found": True, "queried_id": id_number}
        flash("Query notice: No matching network record found for that identifier key.", "error")
    else:
        flash("Worker record found.", "success")
    conn.close()
    
    logged_in_worker = None
    if 'worker_id' in session:
        logged_in_worker = next((w for w in directory if w['id'] == session['worker_id']), None)
        
    return render_template('index.html', directory=directory, search_result=search_result, stats=compute_network_stats(directory), logged_in_worker=logged_in_worker)

@app.route('/rate', methods=['POST'])
def rate_worker():
    id_number = request.form.get('id_number', '').strip()
    rating = int(request.form.get('rating', 5))
    review_text = request.form.get('review_text', '').strip() or "No written experience left by client."
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM workers WHERE id_number = ?", (id_number,))
    if cursor.fetchone():
        cursor.execute("UPDATE workers SET total_score = total_score + ?, count = count + 1 WHERE id_number = ?", (rating, id_number))
        cursor.execute("INSERT INTO reviews (worker_id, rating, review_text) VALUES (?, ?, ?)", (id_number, rating, review_text))
        conn.commit()
        flash(f"Performance score and written review successfully logged.", "success")
    else:
        flash("Submission failed: Target Reference Identifier is not registered on this server.", "error")
    conn.close()
    return redirect(url_for('index'))

# --- MACHINE TO MACHINE API ENFORCEMENTS ---
@app.route('/api/v1/worker/<string:id_number>', methods=['GET'])
def api_get_worker(id_number):
    client_key = request.headers.get("X-API-KEY")
    if client_key != API_KEY_SECRET:
        return jsonify({"status": "denied", "message": "Unauthorized API token header."}), 401
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM workers WHERE id_number = ?", (id_number.strip(),))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return jsonify({"status": "not_found", "message": "Worker ID is not active."}), 404
    avg_score = round(row['total_score'] / row['count'], 1) if row['count'] > 0 else 5.0
    status, _ = get_trust_status(avg_score)
    cursor.execute("SELECT rating, review_text, disputed FROM reviews WHERE worker_id = ?", (id_number.strip(),))
    reviews = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify({"status": "success", "data": {"name": row['name'], "profession": row['profession'], "trust_score": avg_score, "status_tier": status, "claimed": row['claimed'], "historical_logs": reviews}}), 200

@app.route('/api/v1/rate', methods=['POST'])
def api_post_rating():
    client_key = request.headers.get("X-API-KEY")
    if client_key != API_KEY_SECRET:
        return jsonify({"status": "denied", "message": "Unauthorized API Key token wrapper."}), 401
    data = request.get_json() or {}
    id_number = data.get("id_number", "").strip()
    rating = data.get("rating")
    review_text = data.get("review_text", "Logged automatically via B2B Platform API Integration.").strip()
    if not id_number or rating is None:
        return jsonify({"status": "bad_request", "message": "Missing criteria elements."}), 400
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM workers WHERE id_number = ?", (id_number,))
    if not cursor.fetchone():
        conn.close()
        return jsonify({"status": "not_found", "message": "Target identifier is not registered."}), 404
    cursor.execute("UPDATE workers SET total_score = total_score + ?, count = count + 1 WHERE id_number = ?", (int(rating), id_number))
    cursor.execute("INSERT INTO reviews (worker_id, rating, review_text) VALUES (?, ?, ?)", (id_number, int(rating), review_text))
    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "External platform rating logged successfully."}), 200

if __name__ == '__main__':
    init_db()
    app.run(debug=True, use_reloader=True, reloader_type='stat')