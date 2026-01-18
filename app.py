from flask import Flask, render_template, request, redirect, session, url_for, flash
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = "freshfold_secret_key"

DB_NAME = "freshfold.db"

# ---------------- DB ----------------
def db():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_phone TEXT NOT NULL,
            address TEXT NOT NULL,
            pickup_date TEXT NOT NULL,
            pickup_time TEXT NOT NULL,
            service TEXT NOT NULL,
            weight REAL NOT NULL,
            service_price REAL NOT NULL,
            delivery_charge REAL NOT NULL,
            total_price REAL NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'Not Paid',
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()

# ---------------- PRICING ----------------
def calculate_bill(service, weight):
    rates = {
        "Wash": 50,
        "Wash + Iron": 80,
        "Dry Clean": 120
    }
    service_price = rates.get(service, 50) * weight
    delivery_charge = 30 if weight <= 5 else 50
    total = service_price + delivery_charge
    return service_price, delivery_charge, total

# ---------------- AUTH HELPERS ----------------
def user_logged_in():
    return "user_phone" in session

def admin_logged_in():
    return session.get("admin") == True

# ---------------- ROUTES ----------------
@app.route("/")
def index():
    return render_template("index.html")

# -------- USER AUTH --------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()

        if not name or not phone or not password:
            flash("All fields are required!", "danger")
            return redirect("/register")

        conn = db()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO users(name, phone, password) VALUES(?,?,?)", (name, phone, password))
            conn.commit()
            flash("Registration successful! Please login.", "success")
            return redirect("/login")
        except sqlite3.IntegrityError:
            flash("Phone already registered!", "danger")
            return redirect("/register")
        finally:
            conn.close()

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()

        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE phone=? AND password=?", (phone, password))
        user = cur.fetchone()
        conn.close()

        if user:
            session["user_phone"] = phone
            flash("Login successful!", "success")
            return redirect("/dashboard")
        else:
            flash("Invalid phone or password!", "danger")
            return redirect("/login")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# -------- USER PAGES --------
@app.route("/dashboard")
def dashboard():
    if not user_logged_in():
        return redirect("/login")

    phone = session["user_phone"]

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT name FROM users WHERE phone=?", (phone,))
    name = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM orders WHERE user_phone=?", (phone,))
    total = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM orders WHERE user_phone=? AND status='Pending'", (phone,))
    pending = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM orders WHERE user_phone=? AND status='Delivered'", (phone,))
    delivered = cur.fetchone()[0]

    conn.close()

    return render_template("dashboard.html", name=name, total=total, pending=pending, delivered=delivered)

@app.route("/book", methods=["GET", "POST"])
def book():
    if not user_logged_in():
        return redirect("/login")

    if request.method == "POST":
        address = request.form.get("address", "").strip()
        pickup_date = request.form.get("pickup_date", "").strip()
        pickup_time = request.form.get("pickup_time", "").strip()
        service = request.form.get("service", "").strip()
        weight_text = request.form.get("weight", "").strip()

        if not address or not pickup_date or not pickup_time or not service or not weight_text:
            flash("Please fill all fields!", "danger")
            return redirect("/book")

        try:
            weight = float(weight_text)
            if weight <= 0:
                raise ValueError
        except:
            flash("Enter valid weight in kg!", "danger")
            return redirect("/book")

        service_price, delivery_charge, total_price = calculate_bill(service, weight)

        # store temporarily in session for payment
        session["pending_order"] = {
            "address": address,
            "pickup_date": pickup_date,
            "pickup_time": pickup_time,
            "service": service,
            "weight": weight,
            "service_price": service_price,
            "delivery_charge": delivery_charge,
            "total_price": total_price
        }

        return redirect("/payment")

    return render_template("book.html")

@app.route("/payment", methods=["GET", "POST"])
def payment():
    if not user_logged_in():
        return redirect("/login")

    pending = session.get("pending_order")
    if not pending:
        flash("No pending order found. Please book again.", "danger")
        return redirect("/book")

    if request.method == "POST":
        method = request.form.get("payment_method", "Cash on Delivery")

        created_at = datetime.now().strftime("%d-%m-%Y %I:%M %p")
        phone = session["user_phone"]

        conn = db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO orders(
                user_phone, address, pickup_date, pickup_time, service, weight,
                service_price, delivery_charge, total_price,
                payment_method, status, created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?, 'Pending', ?)
        """, (
            phone,
            pending["address"],
            pending["pickup_date"],
            pending["pickup_time"],
            pending["service"],
            pending["weight"],
            pending["service_price"],
            pending["delivery_charge"],
            pending["total_price"],
            method,
            created_at
        ))
        conn.commit()
        conn.close()

        session.pop("pending_order", None)
        flash("Order placed successfully!", "success")
        return redirect("/orders")

    return render_template("payment.html", order=pending)

@app.route("/orders")
def orders():
    if not user_logged_in():
        return redirect("/login")

    phone = session["user_phone"]

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, service, weight, total_price, status, pickup_date, pickup_time, payment_method, created_at
        FROM orders
        WHERE user_phone=?
        ORDER BY id DESC
    """, (phone,))
    data = cur.fetchall()
    conn.close()

    return render_template("orders.html", orders=data)

@app.route("/orders/<int:order_id>")
def order_details(order_id):
    if not user_logged_in():
        return redirect("/login")

    phone = session["user_phone"]

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, address, pickup_date, pickup_time, service, weight,
               service_price, delivery_charge, total_price,
               payment_method, status, created_at
        FROM orders
        WHERE id=? AND user_phone=?
    """, (order_id, phone))
    order = cur.fetchone()
    conn.close()

    if not order:
        flash("Order not found!", "danger")
        return redirect("/orders")

    return render_template("order_details.html", order=order)

# -------- ADMIN --------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if username == "admin" and password == "admin123":
            session["admin"] = True
            flash("Admin login successful!", "success")
            return redirect("/admin/panel")
        else:
            flash("Invalid admin credentials!", "danger")
            return redirect("/admin/login")

    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    flash("Admin logged out.", "success")
    return redirect("/")

@app.route("/admin/panel")
def admin_panel():
    if not admin_logged_in():
        return redirect("/admin/login")

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_phone, service, weight, total_price, payment_method, status, pickup_date, pickup_time, address, created_at
        FROM orders
        ORDER BY id DESC
    """)
    data = cur.fetchall()
    conn.close()

    return render_template("admin_panel.html", orders=data)

@app.route("/admin/update/<int:order_id>", methods=["POST"])
def admin_update(order_id):
    if not admin_logged_in():
        return redirect("/admin/login")

    new_status = request.form.get("status", "Pending")

    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status=? WHERE id=?", (new_status, order_id))
    conn.commit()
    conn.close()

    flash(f"Order #{order_id} updated to {new_status}", "success")
    return redirect("/admin/panel")

# ---------------- RUN ----------------
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
