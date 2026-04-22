from __future__ import annotations

import base64
import csv
import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("MAGAZZINO_DATA_DIR", str(ROOT / "data")))
DB_PATH = Path(os.environ.get("MAGAZZINO_DB_PATH", str(DATA_DIR / "magazzino.db")))
UPLOAD_DIR = Path(os.environ.get("MAGAZZINO_UPLOAD_DIR", str(DATA_DIR / "uploads")))
OCR_SCRIPT = ROOT / "ocr_pdf.swift"
HOST = os.environ.get("MAGAZZINO_HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT") or os.environ.get("MAGAZZINO_PORT", "8000"))

STATIC_FILES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/styles.css": "styles.css",
    "/app.js": "app.js",
}

SOFT_KEYWORDS = {
    "coca", "cola", "sprite", "fanta", "tonica", "soda", "ginger", "lemon",
    "chinotto", "acqua", "red bull", "succo", "the", "tea", "monster", "schweppes",
}
ALCOHOL_KEYWORDS = {
    "gin", "vodka", "rum", "whisky", "whiskey", "campari", "aperol", "vermouth",
    "amaro", "prosecco", "spumante", "vino", "tequila", "mezcal", "brandy", "grappa",
    "limoncello", "liquore", "birra", "champagne",
}
CASE_TOKENS = {"cass", "cassa", "casse", "cart", "cartone", "cartoni", "cs"}
BOTTLE_TOKENS = {"bott", "bott.", "bottiglie", "bottiglia", "bt", "pz", "pezzi", "pezzo", "unit", "unita"}


def ensure_dirs() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def get_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    ensure_dirs()
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                quantity REAL NOT NULL DEFAULT 0,
                alert REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL DEFAULT 'bottiglie',
                category TEXT NOT NULL DEFAULT 'alcol',
                case_size REAL NOT NULL DEFAULT 6,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                type TEXT NOT NULL CHECK (type IN ('load', 'unload')),
                quantity REAL NOT NULL,
                note TEXT,
                source TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute("PRAGMA foreign_keys = ON")
        count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        if count == 0:
            seed_products(conn)


def seed_products(conn: sqlite3.Connection) -> None:
    now = utc_now()
    sample = [
        ("Gin della casa", 4, 2, "bottiglie", "alcol", 6),
        ("Tonica premium", 18, 8, "bottiglie", "soft", 24),
        ("Prosecco DOC", 6, 3, "bottiglie", "alcol", 6),
    ]
    conn.executemany(
        """
        INSERT INTO products (name, quantity, alert, unit, category, case_size, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [(name, qty, alert, unit, category, case_size, now, now) for name, qty, alert, unit, category, case_size in sample],
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def detect_network_url() -> str:
    try:
        result = subprocess.run(
            ["python3", "-c", "import socket; print(socket.gethostbyname(socket.gethostname()))"],
            capture_output=True,
            text=True,
            check=True,
        )
        ip_address = result.stdout.strip()
        if ip_address and ip_address != "127.0.0.1":
            return f"http://{ip_address}:{PORT}"
    except Exception:
        pass
    return f"http://localhost:{PORT}"


def list_products() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, quantity, alert, unit, category, case_size, updated_at FROM products ORDER BY name COLLATE NOCASE"
        ).fetchall()
    return [dict(row) for row in rows]


def list_movements(limit: int = 25) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, product_id, product_name, type, quantity, note, source, created_at
            FROM movements
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def infer_category(name: str) -> str:
    lower_name = name.lower()
    if any(keyword in lower_name for keyword in SOFT_KEYWORDS):
        return "soft"
    if any(keyword in lower_name for keyword in ALCOHOL_KEYWORDS):
        return "alcol"
    return "altro"


def default_case_size(category: str) -> float:
    if category == "soft":
        return 24
    if category == "alcol":
        return 6
    return 1


def parse_number(value) -> float:
    if value is None:
        return 0
    return float(str(value).replace(",", ".").strip() or 0)


def normalize_product_name(name: str) -> str:
    return re.sub(r"\s+", " ", name or "").strip()


def create_product(payload: dict) -> dict:
    name = normalize_product_name(payload.get("name"))
    if not name:
        raise ValueError("Nome prodotto obbligatorio")

    category = payload.get("category") or infer_category(name)
    case_size = parse_number(payload.get("case_size")) or default_case_size(category)
    quantity = parse_number(payload.get("quantity"))
    alert = parse_number(payload.get("alert"))
    unit = payload.get("unit") or "bottiglie"
    now = utc_now()

    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO products (name, quantity, alert, unit, category, case_size, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, quantity, alert, unit, category, case_size, now, now),
        )
        row = conn.execute("SELECT * FROM products WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def update_product(product_id: int, payload: dict) -> dict:
    name = normalize_product_name(payload.get("name"))
    category = payload.get("category") or infer_category(name)
    case_size = parse_number(payload.get("case_size")) or default_case_size(category)
    quantity = parse_number(payload.get("quantity"))
    alert = parse_number(payload.get("alert"))
    unit = payload.get("unit") or "bottiglie"
    now = utc_now()

    with get_db() as conn:
        conn.execute(
            """
            UPDATE products
            SET name = ?, quantity = ?, alert = ?, unit = ?, category = ?, case_size = ?, updated_at = ?
            WHERE id = ?
            """,
            (name, quantity, alert, unit, category, case_size, now, product_id),
        )
        row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if row is None:
        raise ValueError("Prodotto non trovato")
    return dict(row)


def delete_product(product_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM products WHERE id = ?", (product_id,))


def get_product_by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM products WHERE LOWER(name) = LOWER(?)", (normalize_product_name(name),)).fetchone()


def apply_movement(payload: dict) -> dict:
    product_id = int(payload.get("product_id"))
    quantity = parse_number(payload.get("quantity"))
    movement_type = payload.get("type")
    note = payload.get("note") or ""
    source = payload.get("source") or "manuale"
    now = utc_now()

    if quantity <= 0:
        raise ValueError("Quantita non valida")
    if movement_type not in {"load", "unload"}:
        raise ValueError("Tipo movimento non valido")

    with get_db() as conn:
        product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if product is None:
            raise ValueError("Prodotto non trovato")

        new_quantity = float(product["quantity"]) + quantity if movement_type == "load" else max(0, float(product["quantity"]) - quantity)
        conn.execute("UPDATE products SET quantity = ?, updated_at = ? WHERE id = ?", (new_quantity, now, product_id))
        cursor = conn.execute(
            """
            INSERT INTO movements (product_id, product_name, type, quantity, note, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (product_id, product["name"], movement_type, quantity, note, source, now),
        )
        row = conn.execute("SELECT * FROM movements WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def ensure_product(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    existing = get_product_by_name(conn, name)
    if existing is not None:
        return existing

    category = infer_category(name)
    case_size = default_case_size(category)
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO products (name, quantity, alert, unit, category, case_size, created_at, updated_at)
        VALUES (?, 0, 0, 'bottiglie', ?, ?, ?, ?)
        """,
        (normalize_product_name(name), category, case_size, now, now),
    )
    return conn.execute("SELECT * FROM products WHERE id = ?", (cursor.lastrowid,)).fetchone()


def save_temp_file(file_name: str, content_base64: str) -> Path:
    suffix = Path(file_name).suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=UPLOAD_DIR) as temp_file:
        temp_file.write(base64.b64decode(content_base64))
        return Path(temp_file.name)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def extract_text_with_pdftotext(path: Path) -> str:
    if not command_exists("pdftotext"):
        return ""
    result = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def extract_text_with_swift_pdfkit(path: Path) -> str:
    if not OCR_SCRIPT.exists() or not command_exists("swift"):
        return ""
    result = subprocess.run(
        ["swift", str(OCR_SCRIPT), str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def extract_text_with_tesseract(path: Path) -> str:
    if not (command_exists("pdftoppm") and command_exists("tesseract")):
        return ""

    with tempfile.TemporaryDirectory(dir=UPLOAD_DIR) as temp_dir:
        prefix = Path(temp_dir) / "page"
        subprocess.run(
            ["pdftoppm", "-png", str(path), str(prefix)],
            capture_output=True,
            text=True,
            check=True,
        )

        chunks: list[str] = []
        for image_path in sorted(Path(temp_dir).glob("page-*.png")):
            result = subprocess.run(
                ["tesseract", str(image_path), "stdout", "-l", "ita+eng", "--psm", "6"],
                capture_output=True,
                text=True,
                check=True,
            )
            text = result.stdout.strip()
            if text:
                chunks.append(text)
        return "\n".join(chunks).strip()


def extract_text_from_pdf(path: Path) -> str:
    native_text = extract_text_with_pdftotext(path)
    if native_text:
        return native_text

    if os.uname().sysname == "Darwin":
        swift_text = extract_text_with_swift_pdfkit(path)
        if swift_text:
            return swift_text

    ocr_text = extract_text_with_tesseract(path)
    if ocr_text:
        return ocr_text

    raise RuntimeError(
        "Nessun motore PDF/OCR disponibile. Su Render usa il container con pdftotext, pdftoppm e tesseract."
    )


def extract_document_text(file_name: str | None, content_base64: str | None, pasted_text: str) -> tuple[str, str]:
    if pasted_text.strip():
        return pasted_text, "Testo incollato analizzato."

    if not file_name or not content_base64:
        return "", "Nessun contenuto da analizzare."

    temp_path = save_temp_file(file_name, content_base64)
    try:
        extension = temp_path.suffix.lower()
        if extension == ".pdf":
            text = extract_text_from_pdf(temp_path)
            return text, "PDF analizzato con OCR/testo nativo."
        text = temp_path.read_text(encoding="utf-8", errors="ignore")
        return text, "File di testo analizzato."
    finally:
        temp_path.unlink(missing_ok=True)


def parse_imported_text(raw_text: str) -> list[dict]:
    if not raw_text.strip():
        return []

    rows: list[dict] = []
    with get_db() as conn:
        products_by_name = {
            row["name"].lower(): row
            for row in conn.execute("SELECT name, case_size, category FROM products").fetchall()
        }

    for original_line in raw_text.splitlines():
        line = normalize_line(original_line)
        if not line:
            continue
        parsed = parse_line(line, products_by_name)
        if parsed:
            rows.append(parsed)
    return rows


def normalize_line(line: str) -> str:
    line = line.strip()
    if not line:
        return ""
    line = re.sub(r"[;,\t]+", " ", line)
    line = re.sub(r"\s+", " ", line)
    return line


def parse_line(line: str, products_by_name: dict[str, sqlite3.Row]) -> dict | None:
    lower_line = line.lower()
    tokens = lower_line.split()
    original_tokens = line.split()

    quantity = None
    unit_token = None
    consumed_indexes: set[int] = set()

    for index, token in enumerate(tokens):
        clean_token = token.rstrip(".")
        if clean_token in CASE_TOKENS or clean_token in BOTTLE_TOKENS:
            unit_token = clean_token
            consumed_indexes.add(index)
            if index > 0 and is_numeric(tokens[index - 1]):
                quantity = parse_number(tokens[index - 1])
                consumed_indexes.add(index - 1)
            elif index + 1 < len(tokens) and is_numeric(tokens[index + 1]):
                quantity = parse_number(tokens[index + 1])
                consumed_indexes.add(index + 1)
            break

    if quantity is None:
        numeric_positions = [(i, token) for i, token in enumerate(tokens) if is_numeric(token)]
        if numeric_positions:
            idx, token = numeric_positions[0]
            quantity = parse_number(token)
            consumed_indexes.add(idx)

    if quantity is None or quantity <= 0:
        return None

    name_tokens = [original_tokens[i] for i in range(len(original_tokens)) if i not in consumed_indexes]
    product_name = normalize_product_name(" ".join(name_tokens))
    if not product_name:
        return None

    existing = products_by_name.get(product_name.lower())
    category = existing["category"] if existing else infer_category(product_name)
    case_size = float(existing["case_size"]) if existing else default_case_size(category)
    multiplier = case_size if unit_token in CASE_TOKENS else 1
    detected_unit_label = "cassa" if unit_token in CASE_TOKENS else "bottiglia"

    return {
        "product_name": product_name,
        "raw_quantity": quantity,
        "multiplier": multiplier,
        "base_quantity": quantity * multiplier,
        "detected_unit_label": detected_unit_label,
        "category": category,
    }


def is_numeric(token: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:[.,]\d+)?", token))


def apply_import_rows(mode: str, rows: list[dict]) -> int:
    if mode not in {"load", "unload"}:
        raise ValueError("Modalita import non valida")

    now = utc_now()
    with get_db() as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        count = 0
        for row in rows:
            name = normalize_product_name(row.get("product_name"))
            quantity = parse_number(row.get("base_quantity"))
            if not name or quantity <= 0:
                continue

            product = ensure_product(conn, name)
            new_quantity = float(product["quantity"]) + quantity if mode == "load" else max(0, float(product["quantity"]) - quantity)
            conn.execute("UPDATE products SET quantity = ?, updated_at = ? WHERE id = ?", (new_quantity, now, product["id"]))
            conn.execute(
                """
                INSERT INTO movements (product_id, product_name, type, quantity, note, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (product["id"], product["name"], mode, quantity, "Import documento", "import", now),
            )
            count += 1
    return count


def write_csv(rows: list[dict], fieldnames: list[str]) -> bytes:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "MagazzinoLoungeBar/1.0"

    def base_url(self) -> str:
        forwarded_proto = self.headers.get("X-Forwarded-Proto")
        forwarded_host = self.headers.get("X-Forwarded-Host")
        host = forwarded_host or self.headers.get("Host")
        proto = forwarded_proto or ("https" if host and "onrender.com" in host else "http")
        if host:
            return f"{proto}://{host}"
        return f"http://localhost:{PORT}"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in STATIC_FILES:
            self.serve_static(STATIC_FILES[parsed.path])
            return
        if parsed.path == "/api/info":
            self.send_json({
                "local_url": f"http://localhost:{PORT}",
                "network_url": detect_network_url(),
                "public_url": self.base_url(),
                "database": str(DB_PATH),
            })
            return
        if parsed.path == "/health":
            self.send_json({"ok": True, "time": utc_now()})
            return
        if parsed.path == "/api/products":
            self.send_json(list_products())
            return
        if parsed.path == "/api/movements":
            limit = int(parse_qs(parsed.query).get("limit", ["25"])[0])
            self.send_json(list_movements(limit))
            return
        if parsed.path == "/api/export/products.csv":
            self.send_file(
                write_csv(list_products(), ["id", "name", "quantity", "alert", "unit", "category", "case_size", "updated_at"]),
                "text/csv; charset=utf-8",
                "prodotti.csv",
            )
            return
        if parsed.path == "/api/export/movements.csv":
            self.send_file(
                write_csv(list_movements(10000), ["id", "product_id", "product_name", "type", "quantity", "note", "source", "created_at"]),
                "text/csv; charset=utf-8",
                "movimenti.csv",
            )
            return
        if parsed.path == "/api/export/backup.json":
            backup = {
                "products": list_products(),
                "movements": list_movements(10000),
                "exported_at": utc_now(),
            }
            self.send_file(json.dumps(backup, ensure_ascii=False, indent=2).encode("utf-8"), "application/json", "backup-magazzino.json")
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Risorsa non trovata")

    def do_POST(self) -> None:
        try:
            if self.path == "/api/products":
                payload = self.read_json()
                self.send_json(create_product(payload), status=HTTPStatus.CREATED)
                return
            if self.path == "/api/movements":
                payload = self.read_json()
                self.send_json(apply_movement(payload), status=HTTPStatus.CREATED)
                return
            if self.path == "/api/import/parse":
                payload = self.read_json()
                text, message = extract_document_text(
                    payload.get("file_name"),
                    payload.get("file_content_base64"),
                    payload.get("text") or "",
                )
                rows = parse_imported_text(text)
                self.send_json({"rows": rows, "message": f"{message} Righe trovate: {len(rows)}."})
                return
            if self.path == "/api/import/apply":
                payload = self.read_json()
                count = apply_import_rows(payload.get("mode"), payload.get("rows", []))
                self.send_json({"imported": count})
                return
        except subprocess.CalledProcessError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, exc.stderr or "Errore OCR su PDF")
            return
        except RuntimeError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Endpoint non trovato")

    def do_PUT(self) -> None:
        match = re.fullmatch(r"/api/products/(\d+)", self.path)
        if not match:
            self.send_error(HTTPStatus.NOT_FOUND, "Endpoint non trovato")
            return
        try:
            payload = self.read_json()
            self.send_json(update_product(int(match.group(1)), payload))
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

    def do_DELETE(self) -> None:
        match = re.fullmatch(r"/api/products/(\d+)", self.path)
        if not match:
            self.send_error(HTTPStatus.NOT_FOUND, "Endpoint non trovato")
            return
        delete_product(int(match.group(1)))
        self.send_json({"ok": True})

    def serve_static(self, file_name: str) -> None:
        path = ROOT / file_name
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "File statico non trovato")
            return
        content_type = "text/html; charset=utf-8"
        if path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        self.send_file(path.read_bytes(), content_type)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b"{}"
        return json.loads(body.decode("utf-8"))

    def send_json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, content: bytes, content_type: str, download_name: str | None = None) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if download_name:
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args) -> None:
        return


def run() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Server avviato su http://localhost:{PORT}")
    print(f"Rete locale: {detect_network_url()}")
    print(f"Database SQLite: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    run()
