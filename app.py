from flask import Flask, render_template, request, redirect, session, url_for, flash
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.secret_key = "freshfold_secret_key"

DB_NAME = "freshfold.db"

# ---------- DB ----------
def init_db():
    conn = sqlite3.connect(DB_NAME)
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
            service_price REAL NOT NULL DEFAULT 0,
            delivery_charge REAL NOT NULL DEFAULT 0,
            total_price REAL NOT NULL DEFAULT 0,
            payment_method TEXT NOT NULL DEFAULT 'Not Paid',
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def calculate_price(service, weight):
    rates = {
        "Wash": 50,
        "Wash + Iron": 80,
        "Dry Clean": 120
    }
    service_price = rates.get(service, 50) * weight

    delivery_charge = 30
    if weight > 5:
        delivery_charge = 50

    total_price = service_price + delivery_charge
    return service_price, delivery_charge, total_price


def db():
    return sqlite3.connect(DB_NAME)


def get_user_name(phone):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT name FROM users WHERE phone=?", (phone,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else "User"


def get_user_stats(phone):
    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM orders WHERE user_phone=?", (phone,))
    total_orders = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM orders WHERE user_phone=? AND status='Pending'", (phone,))
    pending_orders = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM orders WHERE user_phone=? AND status='Delivered'", (phone,))
    delivered_orders = cur.fetchone()[0]

    conn.close()
    return total_orders, pending_orders, delivered_orders


def get_last_address(phone):
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT address FROM orders
        WHERE user_phone=?
        ORDER BY id DESC
        LIMIT 1
    """, (phone,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else ""


# ---------- ROUTES ----------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        phone = request.form["phone"].strip()
        password = request.form["password"].strip()

        conn = db()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO users(name, phone, password) VALUES(?,?,?)", (name, phone, password))
            conn.commit()
        except:
            conn.close()
            flash("Phone already registered!", "danger")
            return redirect("/register")

        conn.close()
        flash("Registration successful! Please login.", "success")
        return redirect("/login")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        phone = request.form["phone"].strip()
        password = request.form["password"].strip()

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
            flash("Invalid login!", "danger")
            return redirect("/login")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user_phone" not in session:
        return redirect("/login")

    phone = session["user_phone"]
    name = get_user_name(phone)
    total, pending, delivered = get_user_stats(phone)

    return render_template("dashboard.html", name=name, total=total, pending=pending, delivered=delivered)


# -------- BOOK (now with last address auto-fill) --------
@app.route("/book", methods=["GET", "POST"])
def book():
    if "user_phone" not in session:
        return redirect("/login")

    phone = session["user_phone"]

    if request.method == "POST":
        address = request.form["address"].strip()
        pickup_date = request.form["pickup_date"].strip()
        pickup_time = request.form["pickup_time"].strip()
        service = request.form["service"].strip()
        weight = request.form["weight"].strip()

        if not address or not pickup_date or not pickup_time or not service or not weight:
            flash("Please fill all fields!", "danger")
            return redirect("/book")

        try:
            weight = float(weight)
            if weight <= 0:
                raise ValueError
        except:
            flash("Enter valid weight!", "danger")
            return redirect("/book")

        # calculate bill
        service_price, delivery_charge, total_price = calculate_price(service, weight)

        # store in session as "pending order"
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
    last_address = get_last_address(phone)
    return render_template("book.html", last_address=last_address)


# -------- PAYMENT --------
@app.route("/payment", methods=["GET", "POST"])
def payment():
    if "user_phone" not in session:
        return redirect("/login")

    if "pending_order" not in session:
        flash("No pending order found. Please book again.", "danger")
        return redirect("/book")

    order = session["pending_order"]

    if request.method == "POST":
        payment_method = request.form["payment_method"].strip()
        created_at = datetime.now().strftime("%d-%m-%Y %I:%M %p")

        conn = db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO orders(
                user_phone, address, pickup_date, pickup_time,
                service, weight, service_price, delivery_charge, total_price,
                payment_method, status, created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?, 'Pending', ?)
        """, (
            session["user_phone"],
            order["address"],
            order["pickup_date"],
            order["pickup_time"],
            order["service"],
            order["weight"],
            order["service_price"],
            order["delivery_charge"],
            order["total_price"],
            payment_method,
            created_at
        ))
        conn.commit()

        order_id = cur.lastrowid
        conn.close()

        session.pop("pending_order", None)
        flash("Order placed successfully!", "success")

        # go directly to invoice
        return redirect(f"/invoice/{order_id}")

    return render_template("payment.html", order=order)


# -------- ORDERS --------
@app.route("/orders")
def orders():
    if "user_phone" not in session:
        return redirect("/login")

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, service, weight, total_price, status, pickup_date, pickup_time, payment_method
        FROM orders
        WHERE user_phone=?
        ORDER BY id DESC
    """, (session["user_phone"],))
    data = cur.fetchall()
    conn.close()

    return render_template("orders.html", orders=data)


# -------- ORDER DETAILS --------
@app.route("/orders/<int:order_id>")
def order_details(order_id):
    if "user_phone" not in session:
        return redirect("/login")

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, address, pickup_date, pickup_time, service, weight,
               service_price, delivery_charge, total_price,
               payment_method, status, created_at
        FROM orders
        WHERE id=? AND user_phone=?
    """, (order_id, session["user_phone"]))
    row = cur.fetchone()
    conn.close()

    if not row:
        flash("Order not found!", "danger")
        return redirect("/orders")

    return render_template("order_details.html", order=row)


# -------- INVOICE / BILL PAGE --------
@app.route("/invoice/<int:order_id>")
def invoice(order_id):
    if "user_phone" not in session:
        return redirect("/login")

    phone = session["user_phone"]
    name = get_user_name(phone)

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, address, pickup_date, pickup_time, service, weight,
               service_price, delivery_charge, total_price,
               payment_method, status, created_at
        FROM orders
        WHERE id=? AND user_phone=?
    """, (order_id, phone))
    row = cur.fetchone()
    conn.close()

    if not row:
        flash("Invoice not found!", "danger")
        return redirect("/orders")

    return render_template("invoice.html", order=row, name=name, phone=phone)


# -------- ADMIN LOGIN --------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        if username == "admin" and password == "admin123":
            session["admin"] = True
            flash("Admin login successful!", "success")
            return redirect("/admin/panel")

        flash("Invalid admin credentials!", "danger")
        return redirect("/admin/login")

    return render_template("admin_login.html")


@app.route("/admin/panel")
def admin_panel():
    if not session.get("admin"):
        return redirect("/admin/login")

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_phone, service, weight, total_price, payment_method, status, pickup_date, pickup_time, address
        FROM orders
        ORDER BY id DESC
    """)
    orders = cur.fetchall()
    conn.close()

    return render_template("admin_panel.html", orders=orders)


@app.route("/admin/update/<int:order_id>", methods=["POST"])
def admin_update(order_id):
    if not session.get("admin"):
        return redirect("/admin/login")

    new_status = request.form["status"].strip()

    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status=? WHERE id=?", (new_status, order_id))
    conn.commit()
    conn.close()

    flash(f"Order #{order_id} updated to {new_status}", "success")
    return redirect("/admin/panel")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    flash("Admin logged out.", "success")
    return redirect("/")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect("/")


# ---------- RUN ----------
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
