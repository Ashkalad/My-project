
import datetime
import logging
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import flet as ft
from flet import border, border_radius, padding

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "hotel.db"
RECEIPT_DIR = BASE_DIR / "receipts"

HOTEL_NAME = "Infrequent's Hotel"
ROOM_TYPES = ["Regular", "VIP", "Suite"]
DURATIONS = [3, 10, 12, 24]  # hours
ID_TYPES = ["Driver's License", "Passport", "National ID", "SSS ID",
            "PhilHealth ID", "TIN ID", "Voter's ID"]

PRICING_PHP = {
    "Regular": {3: 300, 10: 550, 12: 750, 24: 1100},
    "VIP": {3: 500, 10: 900, 12: 1200, 24: 1800},
    "Suite": {3: 800, 10: 1500, 12: 2000, 24: 3000},
}


ROOM_LAYOUT = {
    "Regular": ["101", "102", "103", "104", "105"],
    "VIP": ["201", "202", "203", "204"],
    "Suite": ["301", "302", "303"],
}

DT_FORMAT = "%Y-%m-%d %H:%M"


BG = "#141416"
SIDEBAR = "#0E0E10"
SURFACE = "#1C1C1F"
SURFACE_ALT = "#242428"
BORDER = "#33333A"
TEXT = "#F2F2F4"
MUTED = "#8E8E99"
ACCENT = "#E50914"
SUCCESS = "#2ECC71"
WARN = "#F5A623"
DANGER = "#FF4D4F"
INFO = "#4DA3FF"

W500 = ft.FontWeight.W_500
W600 = ft.FontWeight.W_600
BOLD = ft.FontWeight.BOLD



@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                number TEXT PRIMARY KEY,
                type   TEXT NOT NULL,
                status TEXT NOT NULL
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                phone       TEXT NOT NULL,
                id_type     TEXT NOT NULL,
                room_number TEXT NOT NULL,
                room_type   TEXT NOT NULL,
                checkin     TEXT NOT NULL,
                duration    INTEGER NOT NULL,
                price       REAL NOT NULL,
                FOREIGN KEY (room_number) REFERENCES rooms (number)
            )""")

        
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(bookings)")}
        if "status" not in cols:
            conn.execute("ALTER TABLE bookings ADD COLUMN status TEXT NOT NULL DEFAULT 'Active'")
        if "checkout_actual" not in cols:
            conn.execute("ALTER TABLE bookings ADD COLUMN checkout_actual TEXT")

        
        if conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0:
            for room_type, numbers in ROOM_LAYOUT.items():
                for number in numbers:
                    conn.execute("INSERT INTO rooms (number, type, status) VALUES (?, ?, 'Available')",
                                 (number, room_type))
    logger.info("Database ready at %s", DB_PATH)


def list_rooms(room_type=None, status=None):
    sql, args = "SELECT number, type, status FROM rooms WHERE 1=1", []
    if room_type:
        sql += " AND type = ?"
        args.append(room_type)
    if status:
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY number"
    with db() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def list_bookings(status="Active", query=""):
    sql, args = "SELECT * FROM bookings WHERE status = ?", [status]
    query = (query or "").strip()
    if query:
        sql += " AND (name LIKE ? OR phone LIKE ? OR room_number LIKE ?)"
        like = f"%{query}%"
        args += [like, like, like]
    sql += " ORDER BY id DESC"
    with db() as conn:
        return [dict(r) for r in conn.execute(sql, args)]


def get_booking(booking_id):
    with db() as conn:
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        return dict(row) if row else None


def get_active_booking_for_room(room_number):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM bookings WHERE room_number = ? AND status = 'Active' ORDER BY id DESC LIMIT 1",
            (room_number,)).fetchone()
        return dict(row) if row else None


def create_booking(name, phone, id_type, room_number, checkin, duration):
    with db() as conn:
        room = conn.execute("SELECT type, status FROM rooms WHERE number = ?", (room_number,)).fetchone()
        if not room or room["status"] != "Available":
            raise ValueError("That room is no longer available.")
        price = PRICING_PHP.get(room["type"], {}).get(duration)
        if not price:
            raise ValueError("No rate is defined for this room type and duration.")
        cur = conn.execute(
            """INSERT INTO bookings (name, phone, id_type, room_number, room_type,
                                     checkin, duration, price, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Active')""",
            (name, phone, id_type, room_number, room["type"], checkin, duration, price))
        conn.execute("UPDATE rooms SET status = 'Occupied' WHERE number = ?", (room_number,))
        return cur.lastrowid


def checkout_booking(booking_id):
    with db() as conn:
        row = conn.execute("SELECT room_number, status FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not row or row["status"] != "Active":
            raise ValueError("This booking is not active.")
        conn.execute("UPDATE bookings SET status = 'Checked Out', checkout_actual = ? WHERE id = ?",
                     (datetime.datetime.now().strftime(DT_FORMAT), booking_id))
        conn.execute("UPDATE rooms SET status = 'Available' WHERE number = ?", (row["room_number"],))


def get_stats():
    today = datetime.date.today().isoformat()
    with db() as conn:
        available = conn.execute("SELECT COUNT(*) FROM rooms WHERE status = 'Available'").fetchone()[0]
        occupied = conn.execute("SELECT COUNT(*) FROM rooms WHERE status = 'Occupied'").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM bookings WHERE status = 'Active'").fetchone()[0]
        revenue = conn.execute(
            "SELECT COALESCE(SUM(price), 0) FROM bookings WHERE substr(checkin, 1, 10) = ?",
            (today,)).fetchone()[0]
    return {"available": available, "occupied": occupied, "active": active, "revenue": revenue}



def parse_dt(value):
    for fmt in (DT_FORMAT, "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime((value or "").strip(), fmt)
        except ValueError:
            continue
    return None


def checkout_dt(booking):
    start = parse_dt(booking.get("checkin"))
    if not start:
        return None
    return start + datetime.timedelta(hours=int(booking.get("duration", 0)))


def money(amount):
    return f"PHP {amount:,.2f}"


def fmt_dt(dt):
    return dt.strftime("%b %d, %Y  %I:%M %p") if dt else "N/A"


def tint(color, alpha="26"):
    """Translucent version of a #RRGGBB color (#AARRGGBB)."""
    return f"#{alpha}{color.lstrip('#')}"


def receipt_number(booking):
    return f"INF-{booking['id']:05d}"


def booking_state(booking):
    if booking.get("status") == "Checked Out":
        return "Checked Out", MUTED
    co = checkout_dt(booking)
    if co is None:
        return "Active", SUCCESS
    now = datetime.datetime.now()
    if now > co:
        return "Overdue", DANGER
    if co - now <= datetime.timedelta(minutes=30):
        return "Ending Soon", WARN
    return "Active", SUCCESS


def time_left(booking):
    co = checkout_dt(booking)
    if not co:
        return ""
    delta = (co - datetime.datetime.now()).total_seconds()
    secs = int(abs(delta))
    hours, minutes = secs // 3600, (secs % 3600) // 60
    span = f"{hours}h {minutes}m" if hours else f"{minutes}m"
    return f"{span} overdue" if delta < 0 else f"{span} left"


def receipt_rows(booking):
    co = checkout_dt(booking)
    rows = [
        ("Receipt No.", receipt_number(booking)),
        ("Issued", datetime.datetime.now().strftime("%b %d, %Y  %I:%M %p")),
        ("Guest", booking["name"]),
        ("Phone", booking["phone"]),
        ("ID Type", booking["id_type"]),
        ("Room", f"{booking['room_number']} ({booking['room_type']})"),
        ("Check-In", fmt_dt(parse_dt(booking["checkin"]))),
        ("Scheduled Check-Out", fmt_dt(co)),
        ("Duration", f"{booking['duration']} hours"),
        ("Status", booking.get("status", "Active")),
    ]
    if booking.get("checkout_actual"):
        rows.insert(8, ("Actual Check-Out", fmt_dt(parse_dt(booking["checkout_actual"]))))
    return rows


def receipt_text(booking):
    lines = [HOTEL_NAME.upper(), "OFFICIAL RECEIPT", "=" * 48]
    for label, value in receipt_rows(booking):
        lines.append(f"{label:<22}{value}")
    lines += ["-" * 48, f"{'TOTAL':<22}{money(booking['price'])}", "=" * 48,
              f"Thank you for choosing {HOTEL_NAME}."]
    return "\n".join(lines)



def T(value, size=14, color=TEXT, weight=None, **kwargs):
    return ft.Text(value, size=size, color=color, weight=weight, **kwargs)


def card(content, **kwargs):
    options = dict(
        bgcolor=SURFACE,
        border=border.all(1, BORDER),
        border_radius=border_radius.all(14),
        padding=padding.all(22),
    )
    options.update(kwargs)  
    return ft.Container(content=content, **options)


def badge(text, color):
    return ft.Container(
        content=T(text, 11, color, W600),
        bgcolor=tint(color),
        padding=padding.symmetric(horizontal=10, vertical=4),
        border_radius=border_radius.all(20),
    )


def button(text, on_click, kind="primary", icon=None, width=None, small=False):
    palette = {
        "primary": (ACCENT, "#FFFFFF"),
        "secondary": (SURFACE_ALT, TEXT),
        "danger": (tint(DANGER, "33"), DANGER),
        "success": (tint(SUCCESS, "33"), SUCCESS),
    }
    bg, fg = palette[kind]
    return ft.ElevatedButton(
        text,
        icon=icon,
        on_click=on_click,
        width=width,
        style=ft.ButtonStyle(
            bgcolor=bg,
            color=fg,
            elevation=0,
            shape=ft.RoundedRectangleBorder(radius=8),
            padding=padding.symmetric(horizontal=14 if small else 20, vertical=10 if small else 16),
        ),
    )


def option(key, text):
    cls = getattr(ft, "DropdownOption", None)
    if cls is not None:
        return cls(key=key, text=text)
    return ft.dropdown.Option(key=key, text=text)


def make_dropdown(label, options, value=None, width=None, on_change=None, expand=False):
    dd = ft.Dropdown(
        label=label,
        options=[option(k, t) for k, t in options],
        value=value,
        width=width,
        expand=expand,
        bgcolor=SURFACE_ALT,
        color=TEXT,
        border_color=BORDER,
        focused_border_color=ACCENT,
        border_radius=8,
        text_size=14,
    )
    if on_change:
        dd.on_change = on_change
        try: 
            dd.on_select = on_change
        except Exception:
            pass
    return dd


def make_field(label, hint=None, value=None, width=None, expand=False, on_change=None, icon=None):
    return ft.TextField(
        label=label,
        hint_text=hint,
        value=value,
        width=width,
        expand=expand,
        on_change=on_change,
        prefix_icon=icon,
        bgcolor=SURFACE_ALT,
        color=TEXT,
        border_color=BORDER,
        focused_border_color=ACCENT,
        border_radius=8,
        text_size=14,
    )


def page_header(title, subtitle=None, actions=None):
    left = [T(title, 26, TEXT, BOLD)]
    if subtitle:
        left.append(T(subtitle, 13, MUTED))
    return ft.Row(
        [ft.Column(left, spacing=2), ft.Row(actions or [], spacing=10)],
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def section_title(text):
    return T(text.upper(), 11, MUTED, W600, style=None)


def empty_state(icon, title, subtitle):
    return card(
        ft.Column(
            [
                ft.Icon(icon, size=48, color=MUTED),
                T(title, 18, TEXT, W600),
                T(subtitle, 13, MUTED),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
        ),
        alignment=ft.Alignment(0, 0),
        padding=padding.all(48),
    )


def stat_card(label, value, icon, color):
    return card(
        ft.Row(
            [
                ft.Container(ft.Icon(icon, color=color, size=26), bgcolor=tint(color),
                             border_radius=border_radius.all(12), padding=padding.all(12)),
                ft.Column([T(label, 12, MUTED), T(value, 24, TEXT, BOLD)], spacing=2),
            ],
            spacing=16,
        ),
        expand=True,
    )



def main(page: ft.Page):
    page.title = "Infrequent's Hotel Management System"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.padding = 0

    win = getattr(page, "window", None)
    if win is not None and hasattr(win, "width"):
        win.width, win.height = 1360, 860
        win.min_width, win.min_height = 1100, 700
    else:
        page.window_width, page.window_height = 1360, 860
        page.window_min_width, page.window_min_height = 1100, 700

    init_db()

    state = {"view": "dashboard"}
    content_area = ft.Container(expand=True, bgcolor=BG)
    nav_col = ft.Column(spacing=4)

   
    def present(control):
        if hasattr(page, "show_dialog"):
            page.show_dialog(control)
        elif hasattr(page, "open"):
            page.open(control)
        else:
            if isinstance(control, ft.SnackBar):
                page.snack_bar = control
            else:
                page.dialog = control
            control.open = True
            page.update()

    def dismiss(control):
        if hasattr(page, "pop_dialog"):
            page.pop_dialog()
        elif hasattr(page, "close"):
            page.close(control)
        else:
            control.open = False
            page.update()

    def notify(message, kind="info"):
        color = {"success": SUCCESS, "error": DANGER, "info": INFO}.get(kind, INFO)
        present(ft.SnackBar(content=T(message, 13, "#FFFFFF"), bgcolor=SURFACE_ALT,
                            show_close_icon=True, close_icon_color=color))

    def message_dialog(title, body, color=TEXT):
        dlg = ft.AlertDialog(
            modal=True,
            title=T(title, 18, color, W600),
            content=T(body, 14, TEXT),
            bgcolor=SURFACE,
            actions=[button("OK", lambda _: dismiss(dlg), "primary", small=True)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        present(dlg)

    
    def save_receipt(booking):
        try:
            RECEIPT_DIR.mkdir(exist_ok=True)
            path = RECEIPT_DIR / f"{receipt_number(booking)}.txt"
            path.write_text(receipt_text(booking), encoding="utf-8")
            notify(f"Receipt saved to {path}", "success")
        except OSError as ex:
            logger.error("Could not save receipt: %s", ex)
            notify("Could not save the receipt file.", "error")

    def show_receipt(booking):
        divider = ft.Divider(height=24, color=BORDER)
        detail_rows = [
            ft.Row(
                [T(label, 13, MUTED), T(value, 13, TEXT, W500)],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            )
            for label, value in receipt_rows(booking)
        ]
        body = ft.Column(
            [
                T(HOTEL_NAME.upper(), 20, ACCENT, BOLD, text_align=ft.TextAlign.CENTER),
                T("Official Receipt", 13, MUTED, text_align=ft.TextAlign.CENTER),
                divider,
                *detail_rows,
                divider,
                ft.Row(
                    [T("TOTAL", 15, TEXT, BOLD), T(money(booking["price"]), 22, SUCCESS, BOLD)],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                ft.Container(height=8),
                T(f"Thank you for choosing {HOTEL_NAME}.", 12, MUTED,
                  italic=True, text_align=ft.TextAlign.CENTER),
            ],
            spacing=8,
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        dlg = ft.AlertDialog(
            modal=True,
            title=T("Guest Receipt", 18, TEXT, W600),
            content=ft.Container(body, width=440),
            bgcolor=SURFACE,
            actions=[
                button("Save as File", lambda _: save_receipt(booking), "secondary",
                       icon=ft.Icons.SAVE_ALT, small=True),
                button("Close", lambda _: dismiss(dlg), "primary", small=True),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        present(dlg)

   
    def confirm_checkout(booking):
        def do_checkout(_):
            dismiss(dlg)
            try:
                checkout_booking(booking["id"])
            except ValueError as ex:
                notify(str(ex), "error")
                set_view("bookings")
                return
            except sqlite3.Error as ex:
                logger.error("Check-out failed: %s", ex)
                notify("Database error while checking out.", "error")
                return
            set_view("bookings")
            show_receipt(get_booking(booking["id"]))

        dlg = ft.AlertDialog(
            modal=True,
            title=T("Confirm check-out", 18, TEXT, W600),
            content=T(f"Check out {booking['name']} from Room {booking['room_number']}?\n"
                      f"The room will be marked available.", 14, TEXT),
            bgcolor=SURFACE,
            actions=[
                ft.TextButton("Cancel", on_click=lambda _: dismiss(dlg),
                              style=ft.ButtonStyle(color=MUTED)),
                button("Check Out", do_checkout, "primary", small=True),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        present(dlg)


    def dashboard_view():
        stats = get_stats()
        today = datetime.date.today().strftime("%A, %B %d, %Y")

        stat_row = ft.Row(
            [
                stat_card("Available Rooms", str(stats["available"]), ft.Icons.MEETING_ROOM_OUTLINED, SUCCESS),
                stat_card("Occupied Rooms", str(stats["occupied"]), ft.Icons.KEY, ACCENT),
                stat_card("Active Bookings", str(stats["active"]), ft.Icons.LIST_ALT, INFO),
                stat_card("Booked Today", money(stats["revenue"]), ft.Icons.PAYMENTS_OUTLINED, WARN),
            ],
            spacing=16,
        )

        # Bookings sorted by scheduled check-out
        active = list_bookings("Active")
        active.sort(key=lambda b: checkout_dt(b) or datetime.datetime.max)
        attention = []
        for b in active[:6]:
            label, color = booking_state(b)
            attention.append(
                ft.Container(
                    ft.Row(
                        [
                            ft.Container(T(f"Room {b['room_number']}", 14, TEXT, W600), width=90),
                            ft.Container(T(b["name"], 14, TEXT), expand=True),
                            T(time_left(b), 12, MUTED),
                            badge(label, color),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=14,
                    ),
                    padding=padding.symmetric(vertical=10),
                    border=border.only(bottom=ft.BorderSide(1, BORDER)),
                )
            )
        if not attention:
            attention = [T("No active bookings right now.", 13, MUTED)]

        attention_card = card(
            ft.Column(
                [
                    T("Upcoming check-outs", 16, TEXT, W600),
                    T("Active bookings ordered by scheduled check-out", 12, MUTED),
                    ft.Container(height=6),
                    *attention,
                ],
                spacing=4,
            ),
            expand=3,
        )

        # Rate card
        rate_header = ft.Row(
            [ft.Container(T("Type", 12, MUTED, W600), width=80)]
            + [ft.Container(T(f"{d}h", 12, MUTED, W600), expand=True) for d in DURATIONS]
        )
        rate_rows = [
            ft.Row(
                [ft.Container(T(rt, 13, TEXT, W600), width=80)]
                + [ft.Container(T(f"{PRICING_PHP[rt][d]:,}", 13, TEXT), expand=True) for d in DURATIONS]
            )
            for rt in ROOM_TYPES
        ]
        rates_card = card(
            ft.Column(
                [T("Rate card", 16, TEXT, W600), T("Prices in PHP", 12, MUTED),
                 ft.Container(height=6), rate_header, ft.Divider(height=8, color=BORDER), *rate_rows],
                spacing=10,
            ),
            expand=2,
        )

        quick = ft.Row(
            [
                button("New Check-In", lambda _: set_view("checkin"), "primary", icon=ft.Icons.LOGIN),
                button("Current Bookings", lambda _: set_view("bookings"), "secondary", icon=ft.Icons.LIST_ALT),
                button("Room Status", lambda _: set_view("rooms"), "secondary", icon=ft.Icons.MEETING_ROOM_OUTLINED),
            ],
            spacing=10,
        )

        return ft.Column(
            [
                page_header("Dashboard", today),
                stat_row,
                quick,
                ft.Row([attention_card, rates_card], spacing=16,
                       vertical_alignment=ft.CrossAxisAlignment.START),
            ],
            spacing=24,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def checkin_view(room=None):
        available = list_rooms(status="Available")
        rooms_by_number = {r["number"]: r["type"] for r in available}
        now = datetime.datetime.now()

        name_f = make_field("Guest full name", "e.g. Juan Dela Cruz", expand=True, icon=ft.Icons.PERSON_OUTLINE)
        phone_f = make_field("Phone number", "e.g. 09123456789", expand=True, icon=ft.Icons.PHONE_OUTLINED)
        id_dd = make_dropdown("ID type", [(i, i) for i in ID_TYPES], value=ID_TYPES[0], expand=True)

        room_dd = make_dropdown(
            "Room",
            [(r["number"], f"Room {r['number']}  -  {r['type']}") for r in available],
            value=room if room in rooms_by_number else None,
            expand=True,
            on_change=lambda _: refresh_summary(),
        )
        dur_dd = make_dropdown(
            "Duration",
            [(str(d), f"{d} hours") for d in DURATIONS],
            value=str(DURATIONS[0]),
            expand=True,
            on_change=lambda _: refresh_summary(),
        )
        date_f = make_field("Check-in date", "YYYY-MM-DD", now.strftime("%Y-%m-%d"), expand=True,
                            on_change=lambda _: refresh_summary(), icon=ft.Icons.CALENDAR_TODAY_OUTLINED)
        time_f = make_field("Check-in time", "HH:MM (24h)", now.strftime("%H:%M"), expand=True,
                            on_change=lambda _: refresh_summary(), icon=ft.Icons.ACCESS_TIME)

        s_room, s_type, s_dur = T("-", 14, TEXT, W500), T("-", 14, TEXT, W500), T("-", 14, TEXT, W500)
        s_in, s_out = T("-", 14, TEXT, W500), T("-", 14, TEXT, W500)
        s_total = T("PHP 0.00", 26, SUCCESS, BOLD)

        def refresh_summary(update=True):
            rnum = room_dd.value
            rtype = rooms_by_number.get(rnum)
            dur = int(dur_dd.value) if dur_dd.value else None
            start = parse_dt(f"{(date_f.value or '').strip()} {(time_f.value or '').strip()}")
            s_room.value = f"Room {rnum}" if rnum else "Not selected"
            s_type.value = rtype or "-"
            s_dur.value = f"{dur} hours" if dur else "-"
            s_in.value = fmt_dt(start) if start else "Invalid date or time"
            s_out.value = fmt_dt(start + datetime.timedelta(hours=dur)) if start and dur else "-"
            price = PRICING_PHP.get(rtype, {}).get(dur, 0) if rtype and dur else 0
            s_total.value = money(price)
            if update:
                page.update()

        def submit(_):
            for f in (name_f, phone_f, date_f, time_f, room_dd):
                f.error_text = None
            errors = False

            guest = (name_f.value or "").strip()
            if len(guest) < 2:
                name_f.error_text = "Enter the guest's full name"
                errors = True

            phone_digits = re.sub(r"[\s\-+()]", "", phone_f.value or "")
            if not phone_digits.isdigit() or not 7 <= len(phone_digits) <= 13:
                phone_f.error_text = "Enter a valid phone number"
                errors = True

            if not room_dd.value:
                room_dd.error_text = "Select a room"
                errors = True

            start = parse_dt(f"{(date_f.value or '').strip()} {(time_f.value or '').strip()}")
            if start is None:
                date_f.error_text = "Use YYYY-MM-DD"
                time_f.error_text = "Use HH:MM"
                errors = True

            if errors:
                page.update()
                return

            try:
                booking_id = create_booking(
                    guest, (phone_f.value or "").strip(), id_dd.value, room_dd.value,
                    start.strftime(DT_FORMAT), int(dur_dd.value))
            except ValueError as ex:
                notify(str(ex), "error")
                set_view("checkin")
                return
            except sqlite3.Error as ex:
                logger.error("Booking failed: %s", ex)
                notify("Database error. The booking was not saved.", "error")
                return

            logger.info("Booking %s created for %s", booking_id, guest)
            set_view("bookings")
            notify("Booking confirmed.", "success")
            show_receipt(get_booking(booking_id))

        if not available:
            form_body = ft.Column(
                [T("No rooms are available right now.", 16, TEXT, W600),
                 T("Check out a guest to free a room, then return here.", 13, MUTED)],
                spacing=6,
            )
        else:
            form_body = ft.Column(
                [
                    section_title("Guest information"),
                    ft.Row([name_f, phone_f], spacing=16),
                    ft.Row([id_dd], spacing=16),
                    ft.Container(height=8),
                    section_title("Booking details"),
                    ft.Row([room_dd, dur_dd], spacing=16),
                    ft.Row([date_f, time_f], spacing=16),
                    ft.Container(height=8),
                    ft.Row(
                        [button("Cancel", lambda _: set_view("dashboard"), "secondary"),
                         button("Confirm Booking", submit, "primary", icon=ft.Icons.CHECK)],
                        alignment=ft.MainAxisAlignment.END, spacing=10,
                    ),
                ],
                spacing=14,
            )

        def summary_row(label, control):
            return ft.Row([T(label, 13, MUTED), control], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)

        summary_card = card(
            ft.Column(
                [
                    T("Booking summary", 16, TEXT, W600),
                    ft.Divider(height=16, color=BORDER),
                    summary_row("Room", s_room),
                    summary_row("Type", s_type),
                    summary_row("Duration", s_dur),
                    summary_row("Check-in", s_in),
                    summary_row("Check-out", s_out),
                    ft.Divider(height=16, color=BORDER),
                    T("Total", 13, MUTED),
                    s_total,
                ],
                spacing=12,
            ),
            expand=2,
        )

        refresh_summary(update=False)

        return ft.Column(
            [
                page_header("Check-In", "Register a new guest and assign a room"),
                ft.Row([card(form_body, expand=3), summary_card], spacing=16,
                       vertical_alignment=ft.CrossAxisAlignment.START),
            ],
            spacing=24,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def bookings_view(mode="active"):
        history = mode == "history"
        status = "Checked Out" if history else "Active"
        list_col = ft.Column(spacing=10)
        count_text = T("", 12, MUTED)

        def caption_value(caption, value, expand):
            return ft.Container(ft.Column([T(caption, 11, MUTED), T(value, 13, TEXT, W500)], spacing=2),
                                expand=expand)

        def booking_row(b):
            label, color = booking_state(b)
            co = checkout_dt(b)
            actions = [button("Receipt", lambda _, bk=b: show_receipt(bk), "secondary",
                              icon=ft.Icons.RECEIPT_LONG_OUTLINED, small=True)]
            if not history:
                actions.append(button("Check Out", lambda _, bk=b: confirm_checkout(bk), "danger",
                                      icon=ft.Icons.LOGOUT, small=True))
            return card(
                ft.Row(
                    [
                        ft.Container(
                            ft.Column([T(b["name"], 15, TEXT, W600), T(b["phone"], 12, MUTED)], spacing=2),
                            expand=3),
                        caption_value("Room", f"{b['room_number']}  ({b['room_type']})", 2),
                        caption_value("Check-in", fmt_dt(parse_dt(b["checkin"])), 3),
                        caption_value("Check-out", fmt_dt(co), 3),
                        caption_value("Duration", f"{b['duration']} hours", 2),
                        ft.Container(
                            ft.Column([T(money(b["price"]), 14, SUCCESS, W600),
                                       T(time_left(b) if not history else "", 11, MUTED)], spacing=2),
                            expand=2),
                        badge(label, color),
                        ft.Row(actions, spacing=8),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=16,
                ),
                padding=padding.symmetric(horizontal=20, vertical=14),
            )

        def populate(query=""):
            items = list_bookings(status, query)
            if items:
                list_col.controls = [booking_row(b) for b in items]
            elif history:
                list_col.controls = [empty_state(ft.Icons.HISTORY, "No history yet",
                                                 "Completed stays will appear here.")]
            else:
                list_col.controls = [empty_state(ft.Icons.HOTEL_OUTLINED, "No current bookings",
                                                 "All rooms are available for new guests.")]
            if history:
                total = sum(b["price"] for b in items)
                count_text.value = f"{len(items)} stays  |  {money(total)} total"
            else:
                count_text.value = f"{len(items)} active"

        def on_search(e):
            populate(e.control.value)
            page.update()

        search = make_field("Search by guest, phone, or room", width=360, on_change=on_search,
                            icon=ft.Icons.SEARCH)
        populate()

        title = "History" if history else "Current Bookings"
        subtitle = "Completed stays and past receipts" if history else "Active guests, receipts and check-out"
        actions = [] if history else [button("New Check-In", lambda _: set_view("checkin"), "primary",
                                             icon=ft.Icons.LOGIN)]
        return ft.Column(
            [
                page_header(title, subtitle, actions),
                ft.Row([search, count_text], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Column([list_col], scroll=ft.ScrollMode.AUTO, expand=True),
            ],
            spacing=20,
            expand=True,
        )

    def rooms_view():
        grid = ft.Row(wrap=True, spacing=14, run_spacing=14, vertical_alignment=ft.CrossAxisAlignment.START)
        summary = T("", 12, MUTED)

        def room_tile(r):
            is_free = r["status"] == "Available"
            color = SUCCESS if is_free else DANGER
            rate = PRICING_PHP[r["type"]][DURATIONS[0]]
            lines = [
                ft.Row([T(r["number"], 24, TEXT, BOLD), badge(r["status"], color)],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                T(r["type"], 13, MUTED),
            ]
            if is_free:
                lines += [
                    T(f"From PHP {rate:,} / {DURATIONS[0]}h", 12, MUTED),
                    ft.Container(height=6),
                    button("Check In", lambda _, n=r["number"]: set_view("checkin", room=n), "primary",
                           icon=ft.Icons.LOGIN, small=True),
                ]
            else:
                booking = get_active_booking_for_room(r["number"])
                if booking:
                    lines += [
                        T(booking["name"], 13, TEXT, W500),
                        T(f"Until {fmt_dt(checkout_dt(booking))}", 11, MUTED),
                        ft.Container(height=6),
                        button("Receipt", lambda _, bk=booking: show_receipt(bk), "secondary",
                               icon=ft.Icons.RECEIPT_LONG_OUTLINED, small=True),
                    ]
                else:
                    lines.append(T("No active booking found", 12, MUTED))
            return card(ft.Column(lines, spacing=6), width=240, padding=padding.all(18))

        def populate():
            rooms = list_rooms(type_dd.value if type_dd.value != "All" else None,
                               status_dd.value if status_dd.value != "All" else None)
            grid.controls = [room_tile(r) for r in rooms]
            if not rooms:
                grid.controls = [empty_state(ft.Icons.MEETING_ROOM_OUTLINED, "No rooms match",
                                             "Try a different filter.")]
            summary.value = f"{len(rooms)} rooms shown"

        def on_filter(_):
            populate()
            page.update()

        type_dd = make_dropdown("Room type", [("All", "All types")] + [(t, t) for t in ROOM_TYPES],
                                value="All", width=200, on_change=on_filter)
        status_dd = make_dropdown("Status", [("All", "All statuses"), ("Available", "Available"),
                                             ("Occupied", "Occupied")],
                                  value="All", width=200, on_change=on_filter)
        populate()

        return ft.Column(
            [
                page_header("Rooms", "Live room status and quick actions"),
                ft.Row([type_dd, status_dd, summary], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Column([grid], scroll=ft.ScrollMode.AUTO, expand=True),
            ],
            spacing=20,
            expand=True,
        )

    views = {
        "dashboard": dashboard_view,
        "checkin": checkin_view,
        "bookings": lambda: bookings_view("active"),
        "rooms": rooms_view,
        "history": lambda: bookings_view("history"),
    }

    nav_items = [
        ("dashboard", "Dashboard", ft.Icons.DASHBOARD_OUTLINED),
        ("checkin", "Check-In", ft.Icons.LOGIN),
        ("bookings", "Current Bookings", ft.Icons.LIST_ALT),
        ("rooms", "Rooms", ft.Icons.MEETING_ROOM_OUTLINED),
        ("history", "History", ft.Icons.HISTORY),
    ]

    def render_nav(active):
        controls = []
        for key, label, icon in nav_items:
            is_active = key == active
            controls.append(
                ft.Container(
                    ft.Row(
                        [ft.Icon(icon, size=20, color=ACCENT if is_active else MUTED),
                         T(label, 14, TEXT if is_active else MUTED, W600 if is_active else W500)],
                        spacing=14,
                    ),
                    padding=padding.symmetric(horizontal=16, vertical=13),
                    border_radius=border_radius.all(10),
                    bgcolor=tint(ACCENT, "1F") if is_active else None,
                    on_click=lambda _, k=key: set_view(k),
                    ink=True,
                )
            )
        nav_col.controls = controls

    def set_view(key, **kwargs):
        state["view"] = key
        try:
            view = views[key](**kwargs)
        except Exception as ex:  # never fail silently: show the error on the page
            logger.exception("Failed to open view %s", key)
            view = ft.Column(
                [page_header("Something went wrong"),
                 card(T(f"Could not open this page: {ex}", 14, DANGER))],
                spacing=20,
            )
        content_area.content = ft.Container(view, padding=padding.all(32), expand=True)
        render_nav(key)
        page.update()

    sidebar = ft.Container(
        width=250,
        bgcolor=SIDEBAR,
        padding=padding.all(22),
        border=border.only(right=ft.BorderSide(1, BORDER)),
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Container(ft.Icon(ft.Icons.HOTEL, color="#FFFFFF", size=22), bgcolor=ACCENT,
                                     border_radius=border_radius.all(10), padding=padding.all(10)),
                        ft.Column([T("INFREQUENT'S", 15, TEXT, BOLD), T("Hotel Management", 11, MUTED)],
                                  spacing=0),
                    ],
                    spacing=12,
                ),
                ft.Container(height=18),
                nav_col,
                ft.Container(expand=True),
                T(datetime.date.today().strftime("%A, %b %d, %Y"), 11, MUTED),
            ],
            expand=True,
        ),
    )

    page.add(ft.Row([sidebar, content_area], expand=True, spacing=0))
    set_view("dashboard")


if __name__ == "__main__":
    if hasattr(ft, "run"):
        ft.run(main)
    else:
        ft.app(target=main)