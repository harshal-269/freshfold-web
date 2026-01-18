from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = "freshfold_secret_key"

DB_NAME = "freshfold.db"


# ---------------- DB ----------------
def db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON;")

    # USERS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # ADDRESSES (multiple saved addresses)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS addresses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            address TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # ORDERS
    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            address TEXT NOT NULL,
            pickup_date TEXT NOT NULL,
            pickup_time TEXT NOT NULL,
            service TEXT NOT NULL,
            weight REAL NOT NULL,
            service_price REAL NOT NULL DEFAULT 0,
            delivery_charge REAL NOT NULL DEFAULT 0,
            total_price REAL NOT NULL DEFAULT 0,
            payment_method TEXT NOT NULL DEFAULT 'Not Paid',
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    # Indexes
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_addresses_user_id ON addresses(user_id);")

    conn.commit()
    conn.close()


# ---------------- PRICING ----------------
def calculate_price(service, weight):
    rates = {
        "Wash": 50,
        "Wash + Iron": 80,
        "Dry Clean": 120
    }
    service_price = rates.get(service, 50) * weight
    delivery_charge = 30 if weight <= 5 else 50
    total_price = service_price + delivery_charge
    return service_price, delivery_charge, total_price


# ---------------- HELPERS ----------------
def get_user_by_phone(phone):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE phone=?", (phone,))
    user = cur.fetchone()
    conn.close()
    return user


def get_logged_user():
    phone = session.get("user_phone")
    if not phone:
        return None
    return get_user_by_phone(phone)


def get_user_stats(user_id):
    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS c FROM orders WHERE user_id=?", (user_id,))
    total = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) AS c FROM orders WHERE user_id=? AND status='Pending'", (user_id,))
    pending = cur.fetchone()["c"]

    cur.execute("SELECT COUNT(*) AS c FROM orders WHERE user_id=? AND status='Delivered'", (user_id,))
    delivered = cur.fetchone()["c"]

    conn.close()
    return total, pending, delivered


def get_saved_addresses(user_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, label, address
        FROM addresses
        WHERE user_id=?
        ORDER BY id DESC
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows


def get_last_address(user_id):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT address FROM orders
        WHERE user_id=?
        ORDER BY id DESC
        LIMIT 1
    """, (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["address"] if row else ""


# ---------------- ROUTES ----------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "").strip()

        if not name or not phone or not password:
            flash("All fields are required!", "danger")
            return redirect("/register")

        created_at = datetime.now().strftime("%d-%m-%Y %I:%M %p")

        conn = db()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO users(name, phone, password, created_at)
                VALUES(?,?,?,?)
            """, (name, phone, password, created_at))
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

        user = get_user_by_phone(phone)
        if user and user["password"] == password:
            session["user_phone"] = phone
            flash("Login successful!", "success")
            return redirect("/dashboard")

        flash("Invalid phone or password!", "danger")
        return redirect("/login")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect("/")


@app.route("/dashboard")
def dashboard():
    user = get_logged_user()
    if not user:
        return redirect("/login")

    total, pending, delivered = get_user_stats(user["id"])
    return render_template("dashboard.html", name=user["name"], total=total, pending=pending, delivered=delivered)


# -------- ADD ADDRESS --------
@app.route("/address/add", methods=["POST"])
def add_address():
    user = get_logged_user()
    if not user:
        return redirect("/login")

    label = request.form.get("label", "").strip()
    address = request.form.get("address", "").strip()

    if not label or not address:
        flash("Address label and address are required!", "danger")
        return redirect("/book")

    created_at = datetime.now().strftime("%d-%m-%Y %I:%M %p")

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO addresses(user_id, label, address, created_at)
        VALUES(?,?,?,?)
    """, (user["id"], label, address, created_at))
    conn.commit()
    conn.close()

    flash("Address saved successfully!", "success")
    return redirect("/book")


# -------- BOOK --------
@app.route("/book", methods=["GET", "POST"])
def book():
    user = get_logged_user()
    if not user:
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
            flash("Enter valid weight!", "danger")
            return redirect("/book")

        service_price, delivery_charge, total_price = calculate_price(service, weight)

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

    # GET
    saved_addresses = get_saved_addresses(user["id"])
    last_address = get_last_address(user["id"])
    return render_template("book.html", saved_addresses=saved_addresses, last_address=last_address)


# -------- PAYMENT --------
@app.route("/payment", methods=["GET", "POST"])
def payment():
    user = get_logged_user()
    if not user:
        return redirect("/login")

    pending = session.get("pending_order")
    if not pending:
        flash("No pending order found. Please book again.", "danger")
        return redirect("/book")

    if request.method == "POST":
        method = request.form.get("payment_method", "Cash on Delivery").strip()
        created_at = datetime.now().strftime("%d-%m-%Y %I:%M %p")

        conn = db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO orders(
                user_id, address, pickup_date, pickup_time,
                service, weight, service_price, delivery_charge, total_price,
                payment_method, status, created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?, 'Pending', ?)
        """, (
            user["id"],
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
        order_id = cur.lastrowid
        conn.close()

        session.pop("pending_order", None)
        flash("Order placed successfully!", "success")
        return redirect(f"/invoice/{order_id}")

    return render_template("payment.html", order=pending)


# -------- ORDERS --------
@app.route("/orders")
def orders():
    user = get_logged_user()
    if not user:
        return redirect("/login")

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, service, weight, total_price, status, pickup_date, pickup_time, payment_method
        FROM orders
        WHERE user_id=?
        ORDER BY id DESC
    """, (user["id"],))
    data = cur.fetchall()
    conn.close()

    return render_template("orders.html", orders=data)


# -------- ORDER DETAILS --------
@app.route("/orders/<int:order_id>")
def order_details(order_id):
    user = get_logged_user()
    if not user:
        return redirect("/login")

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, address, pickup_date, pickup_time, service, weight,
               service_price, delivery_charge, total_price,
               payment_method, status, created_at
        FROM orders
        WHERE id=? AND user_id=?
    """, (order_id, user["id"]))
    row = cur.fetchone()
    conn.close()

    if not row:
        flash("Order not found!", "danger")
        return redirect("/orders")

    return render_template("order_details.html", order=row)


# -------- CANCEL ORDER --------
@app.route("/orders/<int:order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    user = get_logged_user()
    if not user:
        return redirect("/login")

    conn = db()
    cur = conn.cursor()

    # only cancel if pending and belongs to user
    cur.execute("""
        SELECT status FROM orders
        WHERE id=? AND user_id=?
    """, (order_id, user["id"]))
    row = cur.fetchone()

    if not row:
        conn.close()
        flash("Order not found!", "danger")
        return redirect("/orders")

    if row["status"] != "Pending":
        conn.close()
        flash("Only Pending orders can be cancelled!", "danger")
        return redirect(f"/orders/{order_id}")

    cur.execute("""
        UPDATE orders SET status='Cancelled'
        WHERE id=? AND user_id=?
    """, (order_id, user["id"]))
    conn.commit()
    conn.close()

    flash("Order cancelled successfully!", "success")
    return redirect("/orders")


# -------- INVOICE --------
@app.route("/invoice/<int:order_id>")
def invoice(order_id):
    user = get_logged_user()
    if not user:
        return redirect("/login")

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, address, pickup_date, pickup_time, service, weight,
               service_price, delivery_charge, total_price,
               payment_method, status, created_at
        FROM orders
        WHERE id=? AND user_id=?
    """, (order_id, user["id"]))
    row = cur.fetchone()
    conn.close()

    if not row:
        flash("Invoice not found!", "danger")
        return redirect("/orders")

    return render_template("invoice.html", order=row, name=user["name"], phone=user["phone"])


# ---------------- ADMIN ----------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if username == "admin" and password == "admin123":
            session["admin"] = True
            flash("Admin login successful!", "success")
            return redirect("/admin/panel")

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
    if not session.get("admin"):
        return redirect("/admin/login")

    conn = db()
    cur = conn.cursor()

    # Orders list (with join)
    cur.execute("""
        SELECT o.id, u.phone AS user_phone, o.service, o.weight, o.total_price,
               o.payment_method, o.status, o.pickup_date, o.pickup_time, o.address, o.created_at
        FROM orders o
        JOIN users u ON u.id = o.user_id
        ORDER BY o.id DESC
    """)
    orders = cur.fetchall()

    # Revenue analytics
    cur.execute("SELECT COUNT(*) AS total_orders FROM orders")
    total_orders = cur.fetchone()["total_orders"]

    cur.execute("SELECT COUNT(*) AS pending_orders FROM orders WHERE status='Pending'")
    pending_orders = cur.fetchone()["pending_orders"]

    cur.execute("SELECT COUNT(*) AS delivered_orders FROM orders WHERE status='Delivered'")
    delivered_orders = cur.fetchone()["delivered_orders"]

    cur.execute("SELECT COUNT(*) AS cancelled_orders FROM orders WHERE status='Cancelled'")
    cancelled_orders = cur.fetchone()["cancelled_orders"]

    cur.execute("SELECT COALESCE(SUM(total_price), 0) AS revenue FROM orders WHERE status!='Cancelled'")
    revenue = cur.fetchone()["revenue"]

    conn.close()

    return render_template(
        "admin_panel.html",
        orders=orders,
        total_orders=total_orders,
        pending_orders=pending_orders,
        delivered_orders=delivered_orders,
        cancelled_orders=cancelled_orders,
        revenue=revenue
    )


@app.route("/admin/update/<int:order_id>", methods=["POST"])
def admin_update(order_id):
    if not session.get("admin"):
        return redirect("/admin/login")

    new_status = request.form.get("status", "Pending").strip()

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
