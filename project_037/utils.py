from contextlib import contextmanager
import mysql.connector
from datetime import datetime, timedelta
from decimal import Decimal
from abc import ABC, abstractmethod



@contextmanager
def db_cur():
    mydb = None
    cursor = None
    try :
        mydb=mysql.connector.connect(
            host= "localhost",
            user = "root",
            password = "root",
            database = "flytau",
            autocommit = True
        )
        cursor = mydb.cursor()
        yield cursor
        mydb.commit()
    except mysql.connector.Error as err :
        raise err
    finally:
        if cursor:
            cursor.close()
        if mydb:
            mydb.close()

def validate_phone_numbers(phone_numbers):
    for phone in phone_numbers:
        p = phone.strip()
        if p and not (p.isdigit() and len(p) == 10):
            return False
    return True


def login_user(session, email):
    session.clear()
    session["email"] = email

def login_manager(session, manager_id):
    session.clear()
    session["manager_id"] = manager_id


def is_user_logged_in(session):
    return "email" in session

def is_manager_logged_in(session):
    return "manager_id" in session


class Flights:
    def __init__(self,flight_id,airplane_id,manager_id,
                 origin_airport_id,destination_airport_id,departure_date,departure_time,arrival_date,arrival_time):
        self.flight_id = flight_id
        self.airplane_id=airplane_id
        self.manager_id=manager_id
        self.origin_airport_id=origin_airport_id
        self.destination_airport_id =destination_airport_id
        self.departure_date=departure_date
        self.departure_time= departure_time
        self.arrival_date=arrival_date
        self.arrival_time= arrival_time
        self.flight_status = 'active'

    def flight_duration(self):
        with db_cur() as cursor:
            cursor.execute("""
                SELECT r.flight_duration
                FROM flights f
                JOIN routes r
                ON f.origin_airport_id = r.origin_airport_id
                AND f.destination_airport_id = r.destination_airport_id
                WHERE f.flight_id = %s
            """, (self.flight_id,))
            row = cursor.fetchone()
        if row is None:
            return None
        return row[0]

    def is_long_flight(self):
        return self.flight_duration() > time(6, 0, 0)

    def is_future(self):
        dep_time = self.departure_time
        if isinstance(dep_time, timedelta):
            dep_time = (datetime.min + dep_time).time()
        departure_datetime = datetime.combine(self.departure_date, dep_time)
        return departure_datetime > datetime.now()

    def available_seats(self):
        with db_cur() as cursor:
            cursor.execute("""
                SELECT seat_row, seat_column
                FROM seats
                WHERE flight_id = %s
                  AND availability = 'available'
            """, (self.flight_id,))
            return cursor.fetchall()

    def is_full(self):
        if not self.available_seats():
            return True
        return False

    def cancel_flight(self):
        departure_dt = datetime.combine(self.departure_date, self.departure_time)
        if departure_dt - datetime.now() < timedelta(hours=72):
            print("This flight cannot be cancelled less than 72 hours before departure")
            return False
        try:
            with db_cur() as cursor:
                cursor.execute("""
                    UPDATE reservations
                    SET business_class_cost = 0, economy_class_cost =0,
                        reservation_status = 'system cancellation'
                    WHERE reservation_code IN (
                        SELECT reservation_code
                        FROM seats
                        WHERE flight_id = %s)""", (self.flight_id,))
                cursor.execute("DELETE FROM seats WHERE flight_id = %s",
                    (self.flight_id,))
                cursor.execute("DELETE FROM pilots_in_flight WHERE flight_id = %s",
                    (self.flight_id,))
                cursor.execute("DELETE FROM flight_attendants_in_flight WHERE flight_id = %s",
                    (self.flight_id,))
                cursor.execute("DELETE FROM flight WHERE flight_id = %s",
                    (self.flight_id,))
            return True
        except mysql.connector.Error as err:
            print("The flight does not exist")
            return False

    def validate_airplane_and_crew(self):
        duration = self.flight_duration()
        if duration is None:
            return False
        is_long_flight = duration > 6
        with db_cur() as cursor:
            cursor.execute("""
                SELECT airplane_size
                FROM airplanes
                WHERE airplane_id = %s
            """, (self.airplane_id,))
            row = cursor.fetchone()
            if row is None:
                return False
            airplane_size = row[0]
            if is_long_flight and airplane_size == 'small':
                return False
            cursor.execute("""
                SELECT COUNT(*)
                FROM pilots_in_flight
                WHERE flight_id = %s
            """, (self.flight_id,))
            pilots_count = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*)
                FROM flight_attendants_in_flight
                WHERE flight_id = %s
            """, (self.flight_id,))
            attendants_count = cursor.fetchone()[0]

            if airplane_size == 'big':
                if pilots_count != 3 or attendants_count != 6:
                    return False
            else:
                if pilots_count != 2 or attendants_count != 3:
                    return False
            if is_long_flight:
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM pilots p
                    JOIN pilots_in_flight pf ON p.pilot_id = pf.pilot_id
                    WHERE pf.flight_id = %s AND p.certification = FALSE
                """, (self.flight_id,))
                if cursor.fetchone()[0] > 0:
                    return False
                cursor.execute("""
                    SELECT COUNT(*)
                    FROM flight_attendants fa
                    JOIN flight_attendants_in_flight faf ON fa.attendant_id = faf.attendant_id
                    WHERE faf.flight_id = %s AND fa.certification = FALSE
                """, (self.flight_id,))
                if cursor.fetchone()[0] > 0:
                    return False
        return True

    @staticmethod
    def add(flight):
        try:
            with db_cur() as cursor:
                cursor.execute("""INSERT INTO flights(flight_id,airplane_id,manager_id,origin_airport_id,destination_airport_id,
                    departure_date,departure_time,arrival_date,arrival_time,flight_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
                               ,(flight.flight_id,flight.airplane_id,flight.manager_id,flight.origin_airport_id,flight.destination_airport_id,flight.departure_date,flight.departure_time,flight.arrival_date,flight.arrival_time,flight.flight_status ))
            return  True
        except mysql.connector.Error as err:
            raise err
            return False

    @staticmethod
    def update_completed_flights():
        """
        Updates flight_status to 'completed' for flights
        whose arrival datetime is in the past.
        """
        with db_cur() as cursor:
            cursor.execute("""
                UPDATE flights
                SET flight_status = 'completed'
                WHERE flight_status != 'completed'
                  AND CONCAT(arrival_date, ' ', arrival_time) < NOW()
            """)

class Seat:
    def __init__(self, airplane_id, seat_row, seat_col,
                 seat_class, price, availability, reservation_code):
        self.airplane_id = airplane_id
        self.seat_row = seat_row
        self.seat_col = seat_col
        self.seat_class = seat_class
        self.price = price
        self.availability = availability
        self.reservation_code = reservation_code

    @staticmethod
    def get_seats_for_flight(flight_id):
        with db_cur() as cursor:
            cursor.execute("""
                SELECT seat_row, seat_col, seat_class, price, availability
                FROM seats
                WHERE flight_id = %s
            """, (flight_id,))
            return cursor.fetchall()

    @staticmethod
    def get_available_seats(airplane_id):
        with db_cur() as cursor:
            cursor.execute("""
                SELECT airplane_id, seat_row, seat_col,
                       seat_class, price, availability, reservation_code
                FROM seats
                WHERE airplane_id = %s
                  AND availability = 'available'
                  AND reservation_code IS NULL
                ORDER BY seat_row, seat_col
            """, (airplane_id,))
            rows = cursor.fetchall()
        return [Seat(*row) for row in rows]

    @staticmethod
    def reserve_seat(cursor, airplane_id, seat_row, seat_col, reservation_code):
        cursor.execute("""
            UPDATE seats
            SET availability = 'booked',
                reservation_code = %s
            WHERE airplane_id = %s
              AND seat_row = %s
              AND seat_col = %s
              AND availability = 'available'
              AND reservation_code IS NULL
        """, (reservation_code, airplane_id, seat_row, seat_col))
        return cursor.rowcount == 1

    @staticmethod
    def release_seat(cursor, airplane_id, seat_row, seat_col):
        cursor.execute("""
            UPDATE seats
            SET availability = 'available',
                reservation_code = NULL
            WHERE airplane_id = %s
              AND seat_row = %s
              AND seat_col = %s
        """, (airplane_id, seat_row, seat_col))



class Reservation:
    def __init__(self, reservation_code,flight_id, reservation_status,
                 reservation_date, reservation_time, business_class_cost,economy_class_cost,
                 registered_user_email=None, guest_email=None):

        self.reservation_code = reservation_code
        self.flight_id= flight_id
        self.registered_user_email = registered_user_email
        self.guest_email = guest_email
        self.reservation_status = reservation_status
        self.reservation_date = reservation_date
        self.reservation_time = reservation_time
        self.business_class_cost = business_class_cost
        self.economy_class_cost = economy_class_cost

    @staticmethod
    def create(reservation_code, flight_id,
               registered_user_email=None, guest_email=None):
        now = datetime.now()
        with db_cur() as cursor:
            cursor.execute("""
                INSERT INTO reservations (
                    reservation_code,
                    flight_id,
                    registered_user_email,
                    guest_email,
                    reservation_status,
                    reservation_date,
                    reservation_time,
                    business_class_cost,
                    economy_class_cost
                )
                VALUES (%s, %s, %s, %s, 'active', %s, %s, 0, 0)
            """, (
                reservation_code,
                flight_id,
                registered_user_email,
                guest_email,
                now.date(),
                now.time()
            ))

    @staticmethod
    def add_seat(reservation_code, flight_id, seat_row, seat_col):
        with db_cur() as cursor:
            cursor.execute("""
                UPDATE seats
                SET availability = 'booked',
                    reservation_code = %s
                WHERE flight_id = %s
                  AND seat_row = %s
                  AND seat_col = %s
                  AND availability = 'available'
            """, (reservation_code, flight_id, seat_row, seat_col))
            if cursor.rowcount == 0:
                raise Exception("Seat already taken")
            cursor.execute("""
                SELECT price, seat_class
                FROM seats
                WHERE flight_id = %s
                  AND seat_row = %s
                  AND seat_col = %s
            """, (flight_id, seat_row, seat_col))
            price, seat_class = cursor.fetchone()
            if seat_class == 'business':
                cursor.execute("""
                    UPDATE reservations
                    SET business_class_cost = business_class_cost + %s
                    WHERE reservation_code = %s
                """, (price, reservation_code))
            else :
                cursor.execute("""
                    UPDATE reservations
                    SET economy_class_cost = economy_class_cost + %s
                    WHERE reservation_code = %s
                """, (price, reservation_code))

    @staticmethod
    def cancel_by_customer(reservation_code):
        with db_cur() as cursor:
            # 1. שליפת עלויות קיימות
            cursor.execute("""
                SELECT business_class_cost, economy_class_cost
                FROM reservations
                WHERE reservation_code = %s
                  AND reservation_status = 'active'
            """, (reservation_code,))
            row = cursor.fetchone()
            if not row:
                return False
            business_cost, economy_cost = row
            new_business_cost = business_cost * Decimal("0.05")
            new_economy_cost = economy_cost * Decimal("0.05")
            cursor.execute("""
                UPDATE seats
                SET availability = 'available',
                    reservation_code = NULL
                WHERE reservation_code = %s
            """, (reservation_code,))
            cursor.execute("""
                UPDATE reservations
                SET reservation_status = 'cancelled_by_customer',
                    business_class_cost = %s,
                    economy_class_cost = %s
                WHERE reservation_code = %s
            """, (new_business_cost, new_economy_cost, reservation_code))
        return True


class User:
    def __init__(self, email,first_name,last_name):
        self.email = email
        self.first_name = first_name
        self.last_name = last_name

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}"

    def get_phone_numbers(self):
        with db_cur() as cursor:
            cursor.execute("""
                SELECT phone_number
                FROM phone_numbers
                WHERE registered_user_email = %s
            """, (self.email,))
            rows = cursor.fetchall()
        return [row[0] for row in rows]

    def get_reservations(self):
        with db_cur() as cursor:
            cursor.execute("""
                SELECT reservation_code,
                       reservation_status,
                       reservation_date,
                       (business_class_cost + economy_class_cost) AS reservation_cost
                FROM reservations
                WHERE registered_user_email = %s
                   OR guest_email = %s
            """, (self.email, self.email))
            return cursor.fetchall()

    def can_purchase_ticket(self):
        return True

    def view_reservation(self, reservation_code):
        with db_cur() as cursor:
            cursor.execute("""
                SELECT reservation_code,
                       reservation_status,
                       reservation_date,
                       business_class_cost,
                       economy_class_cost,
                       (business_class_cost + economy_class_cost) AS total_cost
                FROM reservations
                WHERE reservation_code = %s
                  AND (registered_user_email = %s OR guest_email = %s)
            """, (reservation_code, self.email, self.email))
            return cursor.fetchone()


class RegisteredUser(User):
    def __init__(self,email, first_name, last_name):
        super().__init__(email, first_name, last_name)

    def filter_status_order_history(self, status):
        with db_cur() as cursor:
            cursor.execute("""
                SELECT reservation_code,
                       reservation_date,
                       (business_class_cost + economy_class_cost) AS reservation_cost
                FROM reservations
                WHERE registered_user_email = %s
                  AND reservation_status = %s
            """, (self.email, status))
            return cursor.fetchall()

    def auto_fill_details(self):
        with db_cur() as cursor:
            cursor.execute("""
                SELECT first_name, last_name, passport_number, birth_date
                FROM registered_users
                WHERE registered_user_email = %s
            """, (self.email,))
            return cursor.fetchone()

class Guest(User):
    def __init__(self, email, first_name="", last_name=""):
        super().__init__(email, first_name, last_name)


def cleanup_expired_reservation(reservation_code):
    with db_cur() as cursor:
        cursor.execute("""
            UPDATE seats
            SET availability = 'available',
                reservation_code = NULL
            WHERE reservation_code = %s
        """, (reservation_code,))
        cursor.execute("""
            DELETE FROM reservations
            WHERE reservation_code = %s
        """, (reservation_code,))

def check_reservation_timeout(reservation_start_time):
    if not reservation_start_time:
        return False
    now = datetime.now().timestamp()
    return now - reservation_start_time > 15 * 60

class Employee(ABC):
    def __init__(self, employee_id, first_name,last_name ):
        self.employee_id = employee_id
        self.first_name = first_name
        self.last_name = last_name
        self.last_location = "Tel Aviv"
        self.assigned_flights = []
        self.flight_hours = []

    def is_available(self, new_flight_start, new_flight_end):
        for flight in self.assigned_flights:
            if not (new_flight_end <= flight.end or new_flight_start >= flight.start):
                return False
        return True

    def is_location_compatible(self, new_flight_origin):
        return self.last_location == new_flight_origin

    def assign_flight(self, flight):
        self.assigned_flights.append(flight)
        self.flight_hours.append(flight.duration_hours)
        self.last_location = flight.destination

    def has_long_flight_certification(self):
        return self.long_flight_certified

    def total_flight_hours(self):
        return sum(self.flight_hours)

    @abstractmethod
    def can_fly_long_flight(self):
        pass

class Pilot(Employee):
    def __init__(self, employee_id,first_name,last_name, long_flight_certified):
        super().__init__(employee_id, first_name,last_name)
        self.long_flight_certified = long_flight_certified

    def can_fly_long_flight(self):
        return self.long_flight_certified

    @classmethod
    def add_employee(cls, employee_id, first_name, last_name, phone_number,
                     start_work_date, city, street, house_number, certification):
        with db_cur() as cursor:
            cursor.execute("""
                INSERT INTO pilots (
                    pilot_id, first_name, last_name, phone_number,
                    start_work_date, city, street, house_number, certification
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                employee_id, first_name, last_name, phone_number,
                start_work_date, city, street, house_number, certification
            ))

class FlightAttendant(Employee):
    def __init__(self, employee_id, first_name,last_name, long_flight_certified):
        super().__init__(employee_id, first_name,last_name)
        self.long_flight_certified = long_flight_certified

    def can_fly_long_flight(self):
        return self.long_flight_certified

    @classmethod
    def add_employee(cls, employee_id, first_name, last_name, phone_number,
                     start_work_date, city, street, house_number, certification):
        with db_cur() as cursor:
            cursor.execute("""
                INSERT INTO flight_attendants (
                    attendant_id, first_name, last_name, phone_number,
                    start_work_date, city, street, house_number, certification
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                employee_id, first_name, last_name, phone_number,
                start_work_date, city, street, house_number, certification
            ))

def get_available_airplanes(origin, is_long):
    size_needed = "big" if is_long else None
    available_airplanes = []
    with db_cur() as cursor:
        if size_needed:
            cursor.execute("""
                SELECT airplane_id
                FROM airplanes
                WHERE airplane_size = 'big'
            """)
        else:
            cursor.execute("""
                SELECT airplane_id
                FROM airplanes
            """)
        airplanes = [row[0] for row in cursor.fetchall()]
    for airplane_id in airplanes:
        with db_cur() as cursor:
            cursor.execute("""
                SELECT COUNT(*)
                FROM flights
                WHERE airplane_id = %s
                  AND CONCAT(departure_date, ' ', departure_time) > NOW()
            """, (airplane_id,))
            if cursor.fetchone()[0] > 0:
                continue
            cursor.execute("""
                SELECT destination_airport_id
                FROM flights
                WHERE airplane_id = %s
                  AND CONCAT(departure_date, ' ', departure_time) <= NOW()
                ORDER BY departure_date DESC, departure_time DESC
                LIMIT 1
            """, (airplane_id,))
            row = cursor.fetchone()
        last_location = row[0] if row else "TLV"
        if last_location == origin:
            available_airplanes.append(airplane_id)
    return available_airplanes

def get_available_pilots(origin, is_long_flight):
    with db_cur() as cursor:
        cursor.execute("""
            SELECT p.pilot_id, p.first_name, p.last_name
            FROM pilots p
            WHERE (%s = FALSE OR p.certification = TRUE)
              AND p.pilot_id NOT IN (
                  SELECT pf.pilot_id
                  FROM pilots_in_flight pf
                  JOIN flights f ON pf.flight_id = f.flight_id
                  WHERE CONCAT(f.departure_date, ' ', f.departure_time) > NOW()
              )
        """, (is_long_flight,))
        pilots = cursor.fetchall()
    available = []
    for pilot_id, first_name, last_name in pilots:
        with db_cur() as cursor:
            cursor.execute("""
                SELECT f.destination_airport_id
                FROM pilots_in_flight pf
                JOIN flights f ON pf.flight_id = f.flight_id
                WHERE pf.pilot_id = %s
                  AND CONCAT(f.departure_date, ' ', f.departure_time) <= NOW()
                ORDER BY f.departure_date DESC, f.departure_time DESC
                LIMIT 1
            """, (pilot_id,))
            row = cursor.fetchone()
        last_location = row[0] if row else "TLV"
        if last_location == origin:
            available.append((pilot_id, first_name, last_name))
    return available

def get_available_attendants(origin, is_long_flight):
    with db_cur() as cursor:
        cursor.execute("""
            SELECT fa.attendant_id, fa.first_name, fa.last_name
            FROM flight_attendants fa
            WHERE (%s = FALSE OR fa.certification = TRUE)
              AND fa.attendant_id NOT IN (
                  SELECT faf.attendant_id
                  FROM flight_attendants_in_flight faf
                  JOIN flights f ON faf.flight_id = f.flight_id
                  WHERE CONCAT(f.departure_date, ' ', f.departure_time) > NOW()
              )
        """, (is_long_flight,))
        attendants = cursor.fetchall()

    available = []

    for attendant_id, first_name, last_name in attendants:
        with db_cur() as cursor:
            cursor.execute("""
                SELECT f.destination_airport_id
                FROM flight_attendants_in_flight faf
                JOIN flights f ON faf.flight_id = f.flight_id
                WHERE faf.attendant_id = %s
                  AND CONCAT(f.departure_date, ' ', f.departure_time) <= NOW()
                ORDER BY f.departure_date DESC, f.departure_time DESC
                LIMIT 1
            """, (attendant_id,))
            row = cursor.fetchone()
        last_location = row[0] if row else "TLV"
        if last_location == origin:
            available.append((attendant_id, first_name, last_name))
    return available

