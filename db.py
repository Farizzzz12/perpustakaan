import sqlite3
from werkzeug.security import generate_password_hash

DB_NAME = "perpus.db"

def get_db_connection():
    """Membuka koneksi ke database SQLite dan mengatur hasil query menjadi seperti dictionary."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    # Mengaktifkan mode WAL dan Foreign Key sesuai spesifikasi PRD
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_db():
    """Membuat tabel-tabel database dan mengisi data contoh awal (seed data)."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Tabel Pengguna (Siswa, Guru, Pustakawan)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pengguna (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nomor_induk TEXT UNIQUE NOT NULL,
        nama TEXT NOT NULL,
        peran TEXT NOT NULL CHECK(peran IN ('siswa', 'guru', 'pustakawan')),
        kelas TEXT,
        email TEXT UNIQUE,
        password_hash TEXT NOT NULL,
        status TEXT DEFAULT 'aktif'
    );
    """)

    # 2. Tabel Kategori Buku
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS kategori (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nama TEXT UNIQUE NOT NULL
    );
    """)

    # 3. Tabel Buku (Data Katalog)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS buku (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        judul TEXT NOT NULL,
        penulis TEXT NOT NULL,
        penerbit TEXT,
        tahun INTEGER,
        isbn TEXT UNIQUE,
        kategori_id INTEGER,
        sinopsis TEXT,
        sampul TEXT,
        lokasi_rak TEXT,
        FOREIGN KEY (kategori_id) REFERENCES kategori (id)
    );
    """)

    # 4. Tabel Eksemplar (Fisik buku berdasarkan kode barcode)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS eksemplar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        buku_id INTEGER NOT NULL,
        kode_barcode TEXT UNIQUE NOT NULL,
        kondisi TEXT DEFAULT 'baik' CHECK(kondisi IN ('baik', 'rusak', 'hilang')),
        status TEXT DEFAULT 'tersedia' CHECK(status IN ('tersedia', 'dipinjam', 'hilang', 'rusak')),
        FOREIGN KEY (buku_id) REFERENCES buku (id) ON DELETE CASCADE
    );
    """)

    # 5. Tabel Peminjaman & Denda
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS peminjaman (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pengguna_id INTEGER NOT NULL,
        eksemplar_id INTEGER NOT NULL,
        tgl_pinjam DATE NOT NULL,
        tgl_jatuh_tempo DATE NOT NULL,
        tgl_kembali DATE,
        jumlah_perpanjangan INTEGER DEFAULT 0,
        status TEXT DEFAULT 'dipinjam' CHECK(status IN ('dipinjam', 'kembali', 'terlambat')),
        denda INTEGER DEFAULT 0,
        status_bayar_denda TEXT DEFAULT 'tidak_ada' CHECK(status_bayar_denda IN ('tidak_ada', 'belum_lunas', 'lunas')),
        FOREIGN KEY (pengguna_id) REFERENCES pengguna (id),
        FOREIGN KEY (eksemplar_id) REFERENCES eksemplar (id)
    );
    """)

    # 6. Tabel Reservasi Buku
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reservasi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pengguna_id INTEGER NOT NULL,
        buku_id INTEGER NOT NULL,
        tgl_reservasi DATE NOT NULL,
        status TEXT DEFAULT 'antre' CHECK(status IN ('antre', 'siap_diambil', 'selesai', 'batal')),
        FOREIGN KEY (pengguna_id) REFERENCES pengguna (id),
        FOREIGN KEY (buku_id) REFERENCES buku (id)
    );
    """)

    # Cek apakah sudah ada data pengguna, jika belum maka isi data awal
    cek_pengguna = cursor.execute("SELECT COUNT(*) FROM pengguna").fetchone()[0]
    if cek_pengguna == 0:
        # Tambah akun Pustakawan, Siswa, dan Guru (Password default: 123456)
        pw_default = generate_password_hash("123456")
        pengguna_awal = [
            ("NIP001", "Budi Santoso (Pustakawan)", "pustakawan", "-", "pustakawan@sekolah.sch.id", pw_default),
            ("NIS101", "Andi Pratama", "siswa", "XI IPA 1", "andi@sekolah.sch.id", pw_default),
            ("NIS102", "Siti Aminah", "siswa", "X IPS 2", "siti@sekolah.sch.id", pw_default),
            ("NIP002", "Ibu Ratna Sari, M.Pd.", "guru", "Guru Matematika", "ratna@sekolah.sch.id", pw_default),
        ]
        cursor.executemany("""
            INSERT INTO pengguna (nomor_induk, nama, peran, kelas, email, password_hash)
            VALUES (?, ?, ?, ?, ?, ?)
        """, pengguna_awal)

        # Tambah Kategori
        kategori_awal = [("Fiksi & Sastra",), ("Sains & Teknologi",), ("Sejarah",), ("Buku Ajar",)]
        cursor.executemany("INSERT INTO kategori (nama) VALUES (?)", kategori_awal)

        # Tambah Koleksi Buku
        buku_awal = [
            ("Laskar Pelangi", "Andrea Hirata", "Bentang Pustaka", 2005, "9789793062792", 1,
             "Kisah perjuangan sepuluh anak Belitung dalam meraih mimpi lewat pendidikan.",
             "https://images.unsplash.com/photo-1544947950-fa07a98d237f?auto=format&fit=crop&w=400&q=80", "Rak A-01"),
            ("Bumi Manusia", "Pramoedya Ananta Toer", "Lentera Dipantara", 1980, "9789799731234", 3,
             "Roman sejarah pergerakan nasional di awal abad ke-20 melalui sosok Minke.",
             "https://images.unsplash.com/photo-1512820790803-83ca734da794?auto=format&fit=crop&w=400&q=80", "Rak C-02"),
            ("Fisika Dasar SMA Kelas XI", "Dr. Hendra Wijaya", "Erlangga", 2024, "9786022987654", 4,
             "Buku panduan lengkap materi mekanika, termodinamika, dan gelombang untuk SMA.",
             "https://images.unsplash.com/photo-1532012197267-da84d127e765?auto=format&fit=crop&w=400&q=80", "Rak D-05"),
            ("Pengantar Algoritma & Python", "Rina Kusuma", "Informatika", 2025, "9786021234567", 2,
             "Belajar dasar pemrograman Python dari nol untuk pelajar tingkat menengah.",
             "https://images.unsplash.com/photo-1515879218367-8466d910aaa4?auto=format&fit=crop&w=400&q=80", "Rak B-03")
        ]
        cursor.executemany("""
            INSERT INTO buku (judul, penulis, penerbit, tahun, isbn, kategori_id, sinopsis, sampul, lokasi_rak)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, buku_awal)

        # Tambah Eksemplar Fisik (Barcode) untuk masing-masing buku
        eksemplar_awal = [
            (1, "BK-001-A", "baik", "tersedia"),
            (1, "BK-001-B", "baik", "tersedia"),
            (2, "BK-002-A", "baik", "tersedia"),
            (3, "BK-003-A", "baik", "tersedia"),
            (3, "BK-003-B", "baik", "tersedia"),
            (4, "BK-004-A", "baik", "tersedia"),
        ]
        cursor.executemany("""
            INSERT INTO eksemplar (buku_id, kode_barcode, kondisi, status)
            VALUES (?, ?, ?, ?)
        """, eksemplar_awal)

        conn.commit()
        print("Database berhasil diinisiasi dengan data awal!")

    conn.close()

if __name__ == "__main__":
    init_db()