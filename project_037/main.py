from utils import (validate_phone_numbers,login_user,login_manager,is_user_logged_in,is_manager_logged_in,
    Flights,Seat,Reservation,User,RegisteredUser,Guest,db_cur, check_reservation_timeout, cleanup_expired_reservation,
    Employee, Pilot,FlightAttendant,get_available_airplanes,get_available_pilots,get_available_attendants)
from flask import Flask, redirect, render_template, request, session,flash
import mysql.connector
from contextlib import contextmanager
from datetime import datetime, timedelta, time, date
from time import time




app = Flask(__name__)
app.secret_key = "flytau-secret-key"

GUEST_TIMEOUT_MINUTES = 15

@app.before_request
def before_request_handler():
    # Update flight statuses
    Flights.update_completed_flights()
    
    # Guest inactivity timeout (15 minutes)
    if session.get("who_are_you") == "guest":
        last_activity = session.get("last_activity")
        if last_activity:
            elapsed = datetime.now().timestamp() - last_activity
            if elapsed > GUEST_TIMEOUT_MINUTES * 60:
                session.clear()
                flash("Your session has expired due to inactivity.", "error")
                return redirect("/")
        session["last_activity"] = datetime.now().timestamp()

@app.route("/")
def home():
    return render_template("home.html")


@app.route('/guest_login', methods=["POST", "GET"])
def guest_login():
    # Block managers from continuing as guest
    if session.get("who_are_you") == "manager":
        flash("Please logout from manager account to continue as guest.", "error")
        return redirect("/")
    if request.method == "POST":
        session["who_are_you"] = "guest"
        session["guest_email"] = None
        return redirect("/flights")
    return render_template("home.html")


@app.route('/login', methods = ["POST", "GET"])
def login():
    # Block managers from logging in as registered user
    if session.get("who_are_you") == "manager":
        flash("Please logout from manager account to login as user.", "error")
        return redirect("/")
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        with db_cur() as cursor:
            cursor.execute("""SELECT registered_user_email,first_name
                           FROM registered_users
                            WHERE registered_user_email = %s AND password = %s """ ,
                           (email, password))
            r_user = cursor.fetchone()
        if r_user:
            login_user(session, email)
            session["who_are_you"] = "register"
            session["first_name"] = r_user[1]
            return redirect("/flights")
        else:
            return render_template("login.html", message="Incorrect login details")
    return render_template("login.html")

@app.route('/manager_login', methods = ["POST", "GET"])
def manager_login():
    if request.method == "POST":
        manager_id = request.form.get("manager_id")
        password = request.form.get("password")
        with db_cur() as cursor:
            cursor.execute("""SELECT manager_id, first_name
                                       FROM managers
                                    WHERE manager_id  = %s AND password = %s """,
                           (manager_id, password))
            r_manager = cursor.fetchone()
        if r_manager:
            login_manager(session, manager_id)
            session["who_are_you"] = "manager"
            session["manager_id"] = manager_id
            session["first_name"] = r_manager[1]
            return redirect("/manager_dashboard")
        else:
            return render_template("manager_login.html", message="Incorrect login details")
    return render_template("manager_login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")



@app.route('/sign_up', methods = ["POST", "GET"])
def sign_up():
    # Block managers from signing up as registered user
    if session.get("who_are_you") == "manager":
        flash("Please logout from manager account to sign up.", "error")
        return redirect("/")
    if request.method == "POST":
        email=request.form.get("email")
        passport = request.form.get("passport")
        first_name= request.form.get("first_name")
        last_name = request.form.get("last_name")
        phone_numbers = request.form.getlist("phone_numbers")
        registered_time = datetime.now()
        birth_date = request.form.get("birth_date")
        password = request.form.get("password")

        if not validate_phone_numbers(phone_numbers):
            return render_template(
                "sign_up.html",
                message="Phone number must contain exactly 10 digits")

        try:
            with db_cur() as cursor:
                cursor.execute("""INSERT INTO registered_users (registered_user_email,passport_number
                                    ,first_name,last_name,registration_date,birth_date,password)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s )""",(email,passport,first_name,last_name,registered_time,birth_date,password))
                for phone in phone_numbers:
                    p = phone.strip()
                    if p:
                        cursor.execute("""
                                               INSERT INTO phone_numbers
                                               (phone_number, registered_user_email)
                                               VALUES (%s, %s)
                                           """, (p, email))
                session["who_are_you"] = "register"
                session["email"] = email
                session["first_name"] = first_name
                return redirect("/flights")
        except mysql.connector.IntegrityError as err:
            if err.errno == 1062:
                return render_template("sign_up.html",message="One or more of the details you entered already exist")
    return render_template("sign_up.html")
@app.route("/flights", methods=["GET", "POST"])
def flights_page():
    if request.method == "POST":
        origin = request.form.get("origin")
        destination = request.form.get("destination")
        search_date_str = request.form.get("date")
        num_of_passengers = request.form.get("num_of_passengers")

        if not all([origin, destination, search_date_str, num_of_passengers]):
            return redirect("/flights")

        search_date = datetime.strptime(search_date_str, "%Y-%m-%d").date()
        if search_date < date.today():
            flash("You cannot search for flights in the past.", "error")
            return redirect("/flights")

        num_of_passengers = int(num_of_passengers)
        session["num_of_passengers"] = num_of_passengers

        with db_cur() as cursor:
            cursor.execute("""
                SELECT f.flight_id
                FROM flights f
                JOIN airports ao ON f.origin_airport_id = ao.airport_id
                JOIN airports ad ON f.destination_airport_id = ad.airport_id
                JOIN seats s ON f.flight_id = s.flight_id
                WHERE ao.city = %s
                  AND ad.city = %s
                  AND f.departure_date = %s
                  AND f.flight_status = 'active'
                  AND TIMESTAMP(f.departure_date, f.departure_time) > NOW()
                  AND s.availability = 'available'
                GROUP BY f.flight_id
                HAVING COUNT(*) >= %s
                ORDER BY f.departure_date, f.departure_time
            """, (origin, destination, search_date, num_of_passengers))

            rows = cursor.fetchall()

        # ❌ אין אף טיסה עם מספיק מושבים
        if not rows:
            flash(
                "No available flights found for the requested details.",
                "error"
            )
            return redirect("/flights")

        # ✅ יש טיסות רלוונטיות
        session["available_flights"] = [r[0] for r in rows]
        return redirect("/flight_choice")

    # ---------------- GET (לא שינינו) ----------------

    flights_board = []
    with db_cur() as cursor:
        cursor.execute("""
            SELECT
                f.flight_id,
                ao.city,
                ad.city,
                f.departure_date,
                f.departure_time,
                r.flight_duration,
                f.flight_status
            FROM flights f
            JOIN airports ao ON f.origin_airport_id = ao.airport_id
            JOIN airports ad ON f.destination_airport_id = ad.airport_id
            JOIN routes r
              ON f.origin_airport_id = r.origin_airport_id
             AND f.destination_airport_id = r.destination_airport_id
            ORDER BY f.departure_date, f.departure_time
        """)
        rows = cursor.fetchall()

        cursor.execute("""
            SELECT DISTINCT city
            FROM airports
            ORDER BY city
        """)
        cities = [row[0] for row in cursor.fetchall()]

    now = datetime.now()
    for r in rows:
        dep_time = r[4]
        if isinstance(dep_time, timedelta):
            dep_time = (datetime.min + dep_time).time()

        dep_dt = datetime.combine(r[3], dep_time)
        arr_dt = dep_dt + r[5]

        if arr_dt < now:
            continue

        status = "IN_AIR" if dep_dt <= now <= arr_dt else "UPCOMING"

        flights_board.append({
            "flight_id": r[0],
            "origin": r[1],
            "destination": r[2],
            "date": r[3],
            "time": dep_time,
            "duration": str(r[5]),
            "status": status
        })

    return render_template(
        "flights_page.html",
        flights=flights_board,
        today=date.today().isoformat(),
        cities=cities
    )


@app.route('/flight_choice', methods=["GET"])
def flight_choice():
    flight_ids = session.get("available_flights")
    if not flight_ids:
        flash("No matching flights were found.", "info")
        return redirect("/flights")
    with db_cur() as cursor:
        cursor.execute("""
            SELECT flight_id, airplane_id, manager_id,
                   origin_airport_id, destination_airport_id,
                   departure_date, departure_time,
                   arrival_date, arrival_time
            FROM flights
            WHERE flight_id IN (%s)
            ORDER BY departure_date, departure_time
        """ % ",".join(["%s"] * len(flight_ids)), tuple(flight_ids))
        rows = cursor.fetchall()
    flights = [Flights(*row) for row in rows]
    return render_template("flight_choice.html", flights=flights)

@app.route('/select_flight', methods=["POST"])
def select_flight():
    flight_id = request.form.get("flight_id")
    num_of_passengers = session.get("num_of_passengers")
    if not flight_id or not num_of_passengers:
        return redirect("/flights")
    with db_cur() as cursor:
        cursor.execute("""
            SELECT flight_status, departure_date, departure_time
            FROM flights
            WHERE flight_id = %s
        """, (flight_id,))
        row = cursor.fetchone()
        
    if not row:
        return redirect("/flights")
        
    status, dep_date, dep_time = row
    
    # Check if flight active and in future
    if isinstance(dep_time, timedelta):
        dep_time = (datetime.min + dep_time).time()
    dep_dt = datetime.combine(dep_date, dep_time)
    
    if status != 'active' or dep_dt <= datetime.now():
        flash("This flight has already departed or is unavailable.", "error")
        return redirect("/flights")
        
    with db_cur() as cursor:
        cursor.execute("""
            SELECT COUNT(*)
            FROM seats
            WHERE flight_id = %s
              AND availability = 'available'
        """, (flight_id,))
        available_count = cursor.fetchone()[0]
    if available_count < num_of_passengers:
        flash(f"Only {available_count} seats are available for this flight. "
            f"Please choose another flight or reduce the number of passengers.",
            "error")
        return redirect("/flights")
    session["selected_flight"] = flight_id
    return redirect("/seat_choice")



@app.route('/seat_choice', methods=["GET"])
def seat_choice():
    flight_id = session.get("selected_flight")
    if not flight_id:
        return redirect("/flights")
    with db_cur() as cursor:
        cursor.execute("""
            SELECT flight_status, departure_date, departure_time
            FROM flights
            WHERE flight_id = %s
        """, (flight_id,))
        row = cursor.fetchone()
        
    if not row:
        return redirect("/flights")
        
    status, dep_date, dep_time = row
    
    # Check if flight active and in future
    if isinstance(dep_time, timedelta):
        dep_time = (datetime.min + dep_time).time()
    dep_dt = datetime.combine(dep_date, dep_time)
    
    if status != 'active' or dep_dt <= datetime.now():
        flash("This flight has already departed or is unavailable.", "error")
        return redirect("/flights")
    reservation_start_time = session.get("reservation_start_time")
    reservation_code = session.get("reservation_code")
    if check_reservation_timeout(reservation_start_time):
        #cleanup_expired_reservation(reservation_code)
        #session.clear()
        return redirect("/flights")
    flight_id = session.get("selected_flight")
    if not flight_id:
        return redirect("/flights")
    with db_cur() as cursor:
        cursor.execute("""
            SELECT
                seat_row,
                seat_col,
                seat_class,
                price,
                availability
            FROM seats
            WHERE flight_id = %s
            ORDER BY seat_row, seat_col
        """, (flight_id,))
        seats = cursor.fetchall()
    if not seats:
        return render_template(
            "seat_choice.html",
            message="No seats available for this flight",
            seats=[],
            num_of_passengers=session.get("num_of_passengers", 1))
    return render_template(
        "seat_choice.html",
        seats=seats,
        num_of_passengers=session.get("num_of_passengers", 1))

@app.route('/confirm_seats', methods=["POST"])
def confirm_seats():
    selected_seats_raw = request.form.get("seats")
    flight_id = session.get("selected_flight")
    num_of_passengers = session.get("num_of_passengers")
    if not selected_seats_raw or not flight_id:
        return redirect("/seat_choice")
    selected_seats = selected_seats_raw.split(",")
    if len(selected_seats) != num_of_passengers:
        return redirect("/seat_choice")
    session["selected_seats"] = selected_seats
    session["reservation_start_time"] = datetime.now().timestamp()
    if session.get("email"):
        return redirect("/view_order_details")
    else:
        return redirect("/fill_personal_details")



@app.route('/fill_personal_details', methods=["GET", "POST"])
def fill_personal_details():
    reservation_start_time = session.get("reservation_start_time")
    reservation_code = session.get("reservation_code")
    if check_reservation_timeout(reservation_start_time):
        #cleanup_expired_reservation(reservation_code)
        session.clear()
        return redirect("/")
    if request.method == "POST":
        email = request.form.get("email")
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        passport_number = request.form.get("passport_number")
        birth_date = request.form.get("birth_date")
        phone_numbers = request.form.getlist("phone_numbers")
        phone_numbers = [p.strip() for p in phone_numbers if p.strip()]
        if len(phone_numbers) < 1:
            flash("At least one phone number is required", "error")
            return render_template("fill_personal_details.html")

        if not validate_phone_numbers(phone_numbers):
            flash("Phone number must contain exactly 10 digits", "error")
            return render_template("fill_personal_details.html")
        if not all([email, first_name, last_name, passport_number, birth_date]):
            flash("Please fill all required fields", "error")
            return render_template("fill_personal_details.html")
        session["guest_first_name"] = first_name
        session["guest_last_name"] = last_name
        session["guest_phone_numbers"] = phone_numbers
        session["email"] = email
        return redirect("/view_order_details")
    return render_template("fill_personal_details.html")


@app.route('/view_order_details', methods=["GET"])
def view_order_details():
    reservation_start_time = session.get("reservation_start_time")
    if check_reservation_timeout(reservation_start_time):
        session.clear()
        return redirect("/")
    seats = session.get("selected_seats", [])
    flight_id = session.get("selected_flight")
    if not seats or not flight_id:
        return redirect("/flights")
    with db_cur() as cursor:
        cursor.execute("""
            SELECT f.flight_id,
                   f.departure_date, f.departure_time,
                   f.arrival_date, f.arrival_time,
                   ao.city, ad.city
            FROM flights f
            JOIN airports ao ON f.origin_airport_id = ao.airport_id
            JOIN airports ad ON f.destination_airport_id = ad.airport_id
            WHERE f.flight_id = %s
        """, (flight_id,))
        flight = cursor.fetchone()
    return render_template(
        "view_order_details.html",
        seats=seats,
        flight=flight,
        guest_first_name=session.get("guest_first_name"),
        guest_last_name=session.get("guest_last_name"),
        guest_email=session.get("email"),
        guest_phone_numbers=session.get("guest_phone_numbers"))

@app.route('/confirm_order', methods=["POST"])
def confirm_order():
    selected_seats = session.get("selected_seats")
    flight_id = session.get("selected_flight")

    reservation_code = f"R{int(time())}"

    # 🔹 משתמש רשום
    if session.get("who_are_you") == "register":
        Reservation.create(
            reservation_code=reservation_code,flight_id = flight_id,
            registered_user_email=session["email"],
            guest_email=None
        )

    # 🔹 אורח
    else:
        with db_cur() as cursor:
            cursor.execute("""
                INSERT IGNORE INTO guests (guest_email, first_name, last_name)
                VALUES (%s, %s, %s)
            """, (
                session["email"],
                session["guest_first_name"],
                session["guest_last_name"]
            ))

            for phone in session.get("guest_phone_numbers", []):
                cursor.execute("""
                    INSERT IGNORE INTO phone_numbers (phone_number, guest_email)
                    VALUES (%s, %s)
                """, (phone, session["email"]))

        Reservation.create(
            reservation_code=reservation_code,flight_id = flight_id,
            registered_user_email=None,
            guest_email=session["email"]
        )

    # 🔹 מושבים
    for seat in selected_seats:
        row, col = seat.split("-")
        Reservation.add_seat(
            reservation_code,
            flight_id,
            int(row),
            int(col)
        )

    session["reservation_code"] = reservation_code
    #session.clear()
    return redirect("/order_confirmed")




@app.route('/order_confirmed')
def order_confirmed():
    reservation_code = session.get("reservation_code")
    if not reservation_code:
        return redirect("/")

    final_code = reservation_code

    # 🔹 אורח – מוחקים הכל
    if session.get("who_are_you") != "register":
        session.clear()

    # 🔹 משתמש רשום – מוחקים רק נתוני הזמנה
    else:
        for key in [
            "reservation_code",
            "selected_seats",
            "selected_flight",
            "reservation_start_time"
        ]:
            session.pop(key, None)

    return render_template(
        "order_confirmed.html",
        reservation_code=final_code
    )




@app.route('/manage_booking', methods=["GET", "POST"])
def manage_booking():
    if request.method == "POST":
        reservation_code = request.form.get("reservation_code")
        email = request.form.get("email")
        if not reservation_code or not email:
            return render_template(
                "manage_booking.html",
                message="Please enter reservation code and email"
            )
        with db_cur() as cursor:
            cursor.execute("""
                SELECT reservation_code
                FROM reservations
                WHERE reservation_code = %s
                  AND reservation_status = 'active'
                  AND (guest_email = %s OR registered_user_email = %s)
            """, (reservation_code, email, email))
            reservation = cursor.fetchone()
        if not reservation:
            return render_template(
                "manage_booking.html",
                message="Reservation not found or details are incorrect"
            )
        session["manage_reservation_code"] = reservation_code
        return redirect("/active_tickets")
    return render_template("manage_booking.html")

@app.route('/active_tickets')
def active_tickets():
    reservation_code = session.get("manage_reservation_code")
    if not reservation_code:
        return redirect("/manage_booking")
    with db_cur() as cursor:
        cursor.execute("""
            SELECT seat_row, seat_col, seat_class, price
            FROM seats
            WHERE reservation_code = %s
            ORDER BY seat_row, seat_col
        """, (reservation_code,))
        seats = cursor.fetchall()
    with db_cur() as cursor:
        cursor.execute("""
            SELECT reservation_status, (business_class_cost+ economy_class_cost) as reservation_cost
            FROM reservations
            WHERE reservation_code = %s
        """, (reservation_code,))
        reservation = cursor.fetchone()
    return render_template(
        "active_tickets.html",
        reservation_code=reservation_code,
        seats=seats,
        reservation=reservation
    )

@app.route('/cancel_reservation', methods=["POST"])
def cancel_reservation():
    reservation_code = session.get("manage_reservation_code")
    if not reservation_code:
        return redirect("/manage_booking")
    with db_cur() as cursor:
        cursor.execute("""
            SELECT f.flight_id, f.departure_date, f.departure_time
            FROM flights f
            JOIN seats s ON f.flight_id = s.flight_id
            WHERE s.reservation_code = %s
            LIMIT 1
        """, (reservation_code,))
        row = cursor.fetchone()
    if not row:
        return render_template(
            "active_tickets.html",
            message="Flight not found"
        )
    flight_id, dep_date, dep_time = row
    if isinstance(dep_time, timedelta):
        dep_time = (datetime.min + dep_time).time()
    departure_dt = datetime.combine(dep_date, dep_time)
    if departure_dt - datetime.now() < timedelta(hours=36):
        return render_template(
            "active_tickets.html",
            message="Cancellation is allowed only up to 36 hours before departure"
        )
    success = Reservation.cancel_by_customer(reservation_code)
    if not success:
        return render_template(
            "active_tickets.html",
            message="Only active reservations can be cancelled"
        )
    with db_cur() as cursor:
        cursor.execute("""
            SELECT COUNT(*)
            FROM seats
            WHERE flight_id = %s
              AND availability = 'available'
        """, (flight_id,))
        available_seats = cursor.fetchone()[0]
        cursor.execute("""
            SELECT flight_status
            FROM flights
            WHERE flight_id = %s
        """, (flight_id,))
        flight_status = cursor.fetchone()[0]
        if flight_status == 'full' and available_seats > 0:
            cursor.execute("""
                UPDATE flights
                SET flight_status = 'active'
                WHERE flight_id = %s
            """, (flight_id,))
    return redirect("/reservation_cancelled")

@app.route('/reservation_cancelled')
def reservation_cancelled():
    return render_template("reservation_cancelled.html")
@app.route('/my_orders')
def my_orders():
    email = session.get("email")
    if not email:
        return redirect("/")
    status_filter = request.args.get("status")
    query = """
        SELECT reservation_code,
               reservation_date,
               reservation_status,
               (business_class_cost + economy_class_cost) AS reservation_cost
        FROM reservations
        WHERE registered_user_email = %s
    """
    params = [email]
    if status_filter:
        query += " AND reservation_status = %s"
        params.append(status_filter)
    query += " ORDER BY reservation_date DESC"
    with db_cur() as cursor:
        cursor.execute(query, tuple(params))
        reservations = cursor.fetchall()
    return render_template(
        "my_orders.html",
        reservations=reservations,
        selected_status=status_filter
    )


@app.route('/manager_dashboard')
def manager_dashboard():
    if not session.get("who_are_you") == "manager":
        return redirect("/manager_login")
    return render_template("manager_dashboard.html")

@app.route("/add_employee", methods=["GET", "POST"])
def add_employee():
    if request.method == "POST":
        employee_type = request.form["employee_type"]
        data = {
            "employee_id": request.form["employee_id"],
            "first_name": request.form["first_name"],
            "last_name": request.form["last_name"],
            "phone_number": request.form["phone_number"],
            "start_work_date": request.form["start_work_date"],
            "city": request.form["city"],
            "street": request.form["street"],
            "house_number": request.form["house_number"],
            "certification": request.form["certification"]}
        if employee_type == "pilot":
            Pilot.add_employee(**data)
            flash("The pilot was added successfully!", "success")
        elif employee_type == "attendant":
            FlightAttendant.add_employee(**data)
            flash("The flight attendant was added successfully!", "success")
        return redirect("/manager_dashboard")
    return render_template("add_employee.html")

@app.route("/add_airplane", methods=["GET", "POST"])
def add_airplane():
    if request.method == "POST":
        airplane_id = request.form["airplane_id"]
        purchase_date = request.form["purchase_date"]
        manufacturer= request.form["manufacturer"]
        airplane_size = request.form["airplane_size"]
        with db_cur() as cursor:
            cursor.execute("""
                       INSERT INTO airplanes (
                           airplane_id, purchase_date, manufacturer, airplane_size
                       )
                       VALUES (%s, %s, %s, %s)
                   """, (
                airplane_id, purchase_date, manufacturer, airplane_size,
            ))
            flash("The airplane  was added successfully!", "success")
        return redirect("/manager_dashboard")
    return render_template("add_airplane.html")

@app.route("/add_flight", methods=["GET", "POST"])
def add_flight():
    if request.method == "POST":
        origin_airport_id = request.form["origin_airport_id"]
        destination_airport_id = request.form["destination_airport_id"]
        with db_cur() as cursor:
            cursor.execute("""
                SELECT flight_duration
                FROM routes
                WHERE origin_airport_id = %s
                  AND destination_airport_id = %s
            """, (origin_airport_id, destination_airport_id))
            row = cursor.fetchone()
        if row is None:
            flash("No route exists between the selected airports.", "error")
            return redirect("/add_flight")
        departure_date_str = request.form["departure_date"]
        departure_time_str = request.form["departure_time"]
        departure_dt = datetime.strptime(
            f"{departure_date_str} {departure_time_str}",
            "%Y-%m-%d %H:%M"
        )
        if departure_dt < datetime.now():
            flash("You cannot add a flight in the past.", "error")
            return redirect("/add_flight")
        duration = row[0]
        is_long_flight = duration > timedelta(hours=6)
        session["origin_airport"] = origin_airport_id
        session["is_long_flight"] = is_long_flight
        available_airplanes = get_available_airplanes(origin_airport_id, is_long_flight)
        if not available_airplanes:
            flash("No available airplanes match the flight requirements.", "error")
            return redirect("/add_flight")
        session["flight_data"] = {
            "origin": origin_airport_id,
            "destination": destination_airport_id,
            "duration": str(duration),
            "departure_date": departure_date_str,
            "departure_time": departure_time_str
        }
        session["available_airplanes"] = available_airplanes
        return redirect("/select_airplane")
    with db_cur() as cursor:
        cursor.execute("""
            SELECT airport_id
            FROM airports
            ORDER BY airport_id
        """)
        airports = [row[0] for row in cursor.fetchall()]
    return render_template(
        "add_flight.html",
        today=date.today().isoformat(),
        airports=airports)


@app.route("/select_airplane", methods=["GET", "POST"])
def select_airplane():
    if request.method == "POST":
        airplane_id = request.form["airplane_id"]
        session["selected_airplane"] = airplane_id
        return redirect("/select_crew")
    available_airplanes = session.get("available_airplanes")
    not_enough_airplanes = len(available_airplanes) == 0
    if not available_airplanes:
        flash("Please add a flight before selecting an airplane.", "error")
        return redirect("/add_flight")
    return render_template("select_airplane.html", available_airplanes=available_airplanes,not_enough_airplanes=not_enough_airplanes)


@app.route("/select_crew", methods=["GET", "POST"])
def select_crew():
    if request.method == "POST":
        selected_pilots = request.form.getlist("selected_pilots")
        selected_attendants = request.form.getlist("selected_attendants")
        required_pilots = session.get("required_pilots")
        required_attendants = session.get("required_attendants")
        if len(selected_pilots) != required_pilots or len(selected_attendants) != required_attendants:
            flash("Please select the required number of crew members.", "error")
            return redirect("/select_crew")
        session["selected_pilots"] = selected_pilots
        session["selected_attendants"] = selected_attendants
        return redirect("/set_price")
    origin = session.get("origin_airport")
    is_long_flight = session.get("is_long_flight")
    airplane_id = session.get("selected_airplane")
    if not origin or not airplane_id:
        flash("Please complete previous steps first.", "error")
        return redirect("/add_flight")
    with db_cur() as cursor:
        cursor.execute("""
            SELECT airplane_size
            FROM airplanes
            WHERE airplane_id = %s
        """, (airplane_id,))
        airplane_size = cursor.fetchone()[0]
    session["airplane_size"] = airplane_size
    if airplane_size == "big":
        required_pilots = 3
        required_attendants = 6
    else:
        required_pilots = 2
        required_attendants = 3
    session["required_pilots"] = required_pilots
    session["required_attendants"] = required_attendants
    with db_cur() as cursor:
        cursor.execute("""
            SELECT pilot_id, first_name, last_name
            FROM pilots
        """)
        pilots = cursor.fetchall()
        cursor.execute("""
            SELECT attendant_id, first_name, last_name
            FROM flight_attendants
        """)
        attendants = cursor.fetchall()
    return render_template(
        "select_crew.html",
        pilots=pilots,
        attendants=attendants,
        required_pilots=required_pilots,
        required_attendants=required_attendants
    )


@app.route("/set_price", methods=["GET", "POST"])
def set_price():
    airplane_id = session.get("selected_airplane")
    flight_data = session.get("flight_data")
    manager_id = session.get("manager_id")
    if request.method == "POST":
        economy_price = request.form["economy_price"]
        business_price = request.form.get("business_price")
        session["prices"] = {
            "economy": economy_price,
            "business": business_price}
        return redirect("/flight_summary")
    with db_cur() as cursor:
        cursor.execute("""
            SELECT airplane_size
            FROM airplanes
            WHERE airplane_id = %s
        """, (airplane_id,))
        airplane_size = cursor.fetchone()[0]
    return render_template(
        "set_price.html",
        airplane_size=airplane_size)

@app.route("/flight_summary", methods=["GET", "POST"])
def flight_summary():
    flight_data = session.get("flight_data")
    airplane_id = session.get("selected_airplane")
    prices = session.get("prices")
    if not flight_data:
        flash("Flight data is missing.", "error")
        return redirect("/add_flight")

    return render_template(
        "flight_summary.html",
        flight_data=flight_data,
        airplane_id=airplane_id,
        prices=prices)


@app.route("/confirm_flight", methods=["POST"])
def confirm_flight():
    flight_data = session.get("flight_data")
    airplane_id = session.get("selected_airplane")
    manager_id = session.get("manager_id")
    selected_pilots = session.get("selected_pilots", [])
    selected_attendants = session.get("selected_attendants", [])
    prices = session.get("prices")
    if not all([flight_data, airplane_id, manager_id, prices]):
        flash("Missing flight data", "error")
        return redirect("/add_flight")
    flight_id = f"FL{int(datetime.now().timestamp())}"
    departure_dt = datetime.strptime(
        f"{flight_data['departure_date']} {flight_data['departure_time']}",
        "%Y-%m-%d %H:%M"
    )
    hours, minutes, _ = flight_data["duration"].split(":")
    arrival_dt = departure_dt + timedelta(
        hours=int(hours),
        minutes=int(minutes)
    )
    try:
        with db_cur() as cursor:
            cursor.execute("""
                INSERT INTO flights (
                    flight_id, airplane_id, manager_id,
                    origin_airport_id, destination_airport_id,
                    departure_date, departure_time,
                    arrival_date, arrival_time
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                flight_id,
                airplane_id,
                manager_id,
                flight_data["origin"],
                flight_data["destination"],
                departure_dt.date(),
                departure_dt.time(),
                arrival_dt.date(),
                arrival_dt.time()))
            for pilot_id in selected_pilots:
                cursor.execute("""
                    INSERT INTO pilots_in_flight (flight_id, pilot_id)
                    VALUES (%s, %s)
                """, (flight_id, pilot_id))
            for attendant_id in selected_attendants:
                cursor.execute("""
                    INSERT INTO flight_attendants_in_flight (flight_id, attendant_id)
                    VALUES (%s, %s)
                """, (flight_id, attendant_id))
            cursor.execute("""
                SELECT airplane_size
                FROM airplanes
                WHERE airplane_id = %s
            """, (airplane_id,))
            airplane_size = cursor.fetchone()[0]
            if airplane_size == "big":
                rows, cols = 30, 6
                business_rows = 3
            else:
                rows, cols = 15, 4
                business_rows = 0
            for r in range(1, rows + 1):
                for c in range(1, cols + 1):
                    seat_class = "business" if r <= business_rows else "economy"
                    price = prices["business"] if seat_class == "business" else prices["economy"]
                    cursor.execute("""
                        INSERT INTO seats (
                            seat_row, seat_col, flight_id,
                            seat_class, price, availability
                        )
                        VALUES (%s, %s, %s, %s, %s, 'available')
                    """, (r, c, flight_id, seat_class, price))
        flash("The flight was added successfully!", "success")
        for key in [
            "flight_data", "selected_airplane", "prices",
            "selected_pilots", "selected_attendants",
            "available_airplanes", "required_pilots",
            "required_attendants", "is_long_flight",
            "origin_airport", "airplane_size"]:
            session.pop(key, None)
        return redirect("/manager_dashboard")
    except mysql.connector.Error as err:
        flash(f"Database error: {err}", "error")
        return redirect("/add_flight")



@app.route("/manager_cancel_flights", methods=["GET", "POST"])
def manager_cancel_flights():

    if request.method == "POST":
        flight_id = request.form.get("flight_id")

        if not flight_id:
            flash("Flight cancellation failed: missing flight ID.", "error")
            return redirect("/manager_dashboard")

        try:
            with db_cur() as cursor:
                cursor.execute("START TRANSACTION")

                cursor.execute("""
                    SELECT departure_date, departure_time
                    FROM flights
                    WHERE flight_id = %s
                """, (flight_id,))
                row = cursor.fetchone()

                if not row:
                    cursor.execute("ROLLBACK")
                    flash("Flight cancellation failed: flight not found.", "error")
                    return redirect("/manager_dashboard")

                dep_date, dep_time = row
                if isinstance(dep_time, timedelta):
                    dep_time = (datetime.min + dep_time).time()

                dep_dt = datetime.combine(dep_date, dep_time)

                if dep_dt - datetime.now() < timedelta(hours=72):
                    cursor.execute("ROLLBACK")
                    flash("Flight cancellation failed: less than 72 hours before departure.", "error")
                    return redirect("/manager_dashboard")

                cursor.execute("""
                    UPDATE reservations
                    SET reservation_status = 'system_cancellation',
                        business_class_cost =0 
                        economy_class_cost = 0
                    WHERE reservation_code IN (
                        SELECT DISTINCT reservation_code
                        FROM seats
                        WHERE flight_id = %s
                          AND reservation_code IS NOT NULL
                    )
                """, (flight_id,))
                cursor.execute("""
                    UPDATE seats
                    SET availability = 'unavailable',
                        reservation_code = NULL
                    WHERE flight_id = %s
                """, (flight_id,))

                # 4️⃣ הסרת צוות
                cursor.execute("""DELETE FROM pilots_in_flight WHERE flight_id = %s""", (flight_id,))
                cursor.execute("""DELETE FROM flight_attendants_in_flight WHERE flight_id = %s""", (flight_id,))

                cursor.execute("""UPDATE flights 
                                SET flight_status = 'cancelled'
                                WHERE flight_id = %s""", (flight_id,))

                cursor.execute("COMMIT")

            flash("Flight cancelled successfully.", "success")
            return redirect("/manager_dashboard")

        except Exception as e:
            flash(f"Flight cancellation failed: {e}", "error")
            return redirect("/manager_dashboard")

    with db_cur() as cursor:
        cursor.execute("""
            SELECT
                f.flight_id,
                ao.city,
                ad.city,
                f.departure_date,
                f.departure_time
            FROM flights f
            JOIN airports ao ON f.origin_airport_id = ao.airport_id
            JOIN airports ad ON f.destination_airport_id = ad.airport_id
            WHERE CONCAT(f.departure_date, ' ', f.departure_time) > NOW()
            ORDER BY f.departure_date, f.departure_time
        """)
        rows = cursor.fetchall()
    flights = [{
        "flight_id": r[0],
        "origin": r[1],
        "destination": r[2],
        "departure_date": r[3],
        "departure_time": r[4]
    } for r in rows]
    return render_template("manager_cancel_flights.html", flights=flights)

@app.route("/manager_flights_board", methods=["GET"])
def manager_flights_board():
    if session.get("who_are_you") != "manager":
        return redirect("/manager_login")

    status = request.args.get("status")
    origin = request.args.get("origin")
    destination = request.args.get("destination")
    flight_date = request.args.get("date")

    query = """
        SELECT
            f.flight_id,
            ao.city AS origin,
            ad.city AS destination,
            f.departure_date,
            f.departure_time,
            f.flight_status
        FROM flights f
        JOIN airports ao ON f.origin_airport_id = ao.airport_id
        JOIN airports ad ON f.destination_airport_id = ad.airport_id
        WHERE 1=1
    """
    params = []

    if status:
        query += " AND f.flight_status = %s"
        params.append(status)

    if origin:
        query += " AND ao.city = %s"
        params.append(origin)

    if destination:
        query += " AND ad.city = %s"
        params.append(destination)

    if flight_date:
        query += " AND f.departure_date = %s"
        params.append(flight_date)

    query += " ORDER BY f.departure_date, f.departure_time"

    with db_cur() as cursor:
        cursor.execute(query, tuple(params))
        flights = cursor.fetchall()

        cursor.execute("""
            SELECT DISTINCT city
            FROM airports
            ORDER BY city
        """)
        cities = [row[0] for row in cursor.fetchall()]

    return render_template(
        "manager_flights_board.html",
        flights=flights,
        cities=cities,
        selected_status=status,
        hide_nav = True
    )



@app.route('/view_reports')
def view_reports():
    return render_template('view_reports.html')

@app.route('/report_occupancy')
def report_occupancy():
    query = """
    SELECT AVG(flight_occupancy) AS avg_flight_occupancy
    FROM (
        SELECT
            s.flight_id,
            COUNT(s.reservation_code) * 1.0 / COUNT(*) AS flight_occupancy
        FROM seats s
        JOIN flights f ON s.flight_id = f.flight_id
        WHERE f.flight_status = 'completed'
        GROUP BY s.flight_id
    ) AS occupancies;
    """
    with db_cur() as cursor:
        cursor.execute(query)
        result = cursor.fetchone()
    
    avg_occupancy = result[0] if result and result[0] is not None else 0
    return render_template('report_occupancy.html', avg_occupancy=avg_occupancy)

@app.route('/report_revenue')
def report_revenue():
    query = """
    SELECT manufacturer, airplane_size, seat_class, SUM(revenue) AS total_revenue
    FROM (
        SELECT a.manufacturer, a.airplane_size, 'Business' AS seat_class, r.business_class_cost AS revenue
        FROM reservations r
        JOIN flights f ON r.flight_id = f.flight_id
        JOIN airplanes a ON f.airplane_id = a.airplane_id
        WHERE r.business_class_cost > 0
        UNION ALL
        SELECT a.manufacturer, a.airplane_size, 'Economy' AS seat_class, r.economy_class_cost AS revenue
        FROM reservations r
        JOIN flights f
            ON r.flight_id = f.flight_id
        JOIN airplanes a
            ON f.airplane_id = a.airplane_id
        WHERE r.economy_class_cost > 0
    ) AS revenues
    GROUP BY manufacturer, airplane_size, seat_class
    ORDER BY manufacturer, airplane_size, seat_class;
    """
    with db_cur() as cursor:
        cursor.execute(query)
        results = cursor.fetchall()
    return render_template('report_revenue.html', results=results)

@app.route('/report_staff_hours')
def report_staff_hours():
    query = """
    SELECT
        base_staff.employee_id,
        COALESCE(SEC_TO_TIME(SUM(CASE WHEN r.flight_duration < '06:00:00' THEN TIME_TO_SEC(r.flight_duration) ELSE 0 END)), '00:00:00') AS short_flights_hours,
        COALESCE(SEC_TO_TIME(SUM(CASE WHEN r.flight_duration >= '06:00:00' THEN TIME_TO_SEC(r.flight_duration) ELSE 0 END)), '00:00:00') AS long_flights_hours
    FROM (
        SELECT pilot_id AS employee_id FROM pilots
        UNION
        SELECT attendant_id AS employee_id FROM flight_attendants
    ) AS base_staff
    LEFT JOIN (
        SELECT pilot_id AS emp_id, flight_id FROM pilots_in_flight
        UNION ALL
        SELECT attendant_id AS emp_id, flight_id FROM flight_attendants_in_flight
    ) AS assignments ON base_staff.employee_id = assignments.emp_id
    LEFT JOIN flights f ON assignments.flight_id = f.flight_id
    LEFT JOIN routes r ON f.origin_airport_id = r.origin_airport_id
                      AND f.destination_airport_id = r.destination_airport_id
    GROUP BY base_staff.employee_id;
    """
    with db_cur() as cursor:
        cursor.execute(query)
        results = cursor.fetchall()
    return render_template('report_staff_hours.html', results=results)

@app.route('/report_cancellation')
def report_cancellation():
    query = """
    SELECT
        YEAR(reservation_date) AS reservation_year,
        MONTH(reservation_date) AS reservation_month,
        (SUM(CASE WHEN reservation_status = 'cancelled_by_customer' THEN 1 ELSE 0 END) / COUNT(*)) * 100 AS cancellation_rate
    FROM
        reservations
    GROUP BY
        YEAR(reservation_date),
        MONTH(reservation_date)
    ORDER BY
        reservation_year DESC,
        reservation_month DESC;
    """
    with db_cur() as cursor:
        cursor.execute(query)
        results = cursor.fetchall()
    return render_template('report_cancellation.html', results=results)
    
@app.route('/report_utilization')
def report_utilization():
    query = """
    WITH flights_by_month AS (
        SELECT
            airplane_id,
            departure_date,
            origin_airport_id,
            destination_airport_id,
            flight_status,
            YEAR(departure_date) AS year,
            MONTH(departure_date) AS month
        FROM flights)
    SELECT
        f.airplane_id,
        f.year,
        f.month,
        SUM(CASE 
            WHEN f.flight_status = 'completed' THEN 1 
            ELSE 0 
        END) AS completed_flights,
        SUM(CASE 
            WHEN f.flight_status = 'system_cancellation' THEN 1 
            ELSE 0 
        END) AS cancelled_flights,
        COUNT(DISTINCT CASE 
            WHEN f.flight_status = 'completed' THEN f.departure_date 
        END) / 30.0 AS utilization_rate,
        (
            SELECT CONCAT(f2.origin_airport_id, '-', f2.destination_airport_id)
            FROM flights_by_month f2
            WHERE f2.airplane_id = f.airplane_id
              AND f2.year = f.year
              AND f2.month = f.month
            GROUP BY f2.origin_airport_id, f2.destination_airport_id
            ORDER BY COUNT(*) DESC
            LIMIT 1
        ) AS dominant_route

    FROM flights_by_month f
    GROUP BY
        f.airplane_id,
        f.year,
        f.month
    ORDER BY
        f.airplane_id,
        f.year,
        f.month;
    """
    with db_cur() as cursor:
        cursor.execute(query)
        results = cursor.fetchall()
    return render_template('report_utilization.html', results=results)


if __name__ == "__main__":
    app.run(debug=True)
