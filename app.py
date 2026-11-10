from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash
from datetime import datetime, timedelta
from functools import wraps
from db import get_db_connection, init_db
from werkzeug.security import generate_password_hash

app = Flask(__name__)
app.secret_key = "kunci_rahasia_perpusku_sekolah_aman"

# Aturan Bisnis Default sesuai PRD (Dapat disesuaikan)
ATURAN = {
    "durasi_siswa": 7,        # 7 hari
    "durasi_guru": 14,        # 14 hari
    "kuota_siswa": 3,         # Maksimal 3 buku
    "kuota_guru": 5,          # Maksimal 5 buku
    "maks_perpanjangan": 1,   # Maksimal 1 kali perpanjangan (7 hari)
    "tarif_denda": 500        # Rp500 per buku per hari keterlambatan
}

# Jalankan inisiasi database saat aplikasi dimulai
init_db()

# --- DECORATOR PENGAMAN AKSES ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Silakan login terlebih dahulu untuk mengakses halaman ini.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def pustakawan_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("peran") != "pustakawan":
            flash("Akses ditolak! Halaman ini khusus untuk Pustakawan.", "danger")
            return redirect(url_for("katalog"))
        return f(*args, **kwargs)
    return decorated_function

# --- FUNGSI BANTUAN HITUNG DENDA ---
def hitung_denda_berjalan(tgl_jatuh_tempo_str):
    """Menghitung selisih hari keterlambatan dan total denda hingga hari ini."""
    hari_ini = datetime.now().date()
    jatuh_tempo = datetime.strptime(tgl_jatuh_tempo_str, "%Y-%m-%d").date()
    selisih_hari = (hari_ini - jatuh_tempo).days
    if selisih_hari > 0:
        return selisih_hari, selisih_hari * ATURAN["tarif_denda"]
    return selisih_hari, 0

# --- ROUTES AUTENTIKASI ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identitas = request.form.get("identitas", "").strip()
        password = request.form.get("password", "")

        conn = get_db_connection()
        user = conn.execute(
            "SELECT * FROM pengguna WHERE nomor_induk = ? OR email = ?",
            (identitas, identitas)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["nomor_induk"] = user["nomor_induk"]
            session["nama"] = user["nama"]
            session["peran"] = user["peran"]
            session["kelas"] = user["kelas"]
            flash(f"Selamat datang kembali, {user['nama']}!", "success")

            if user["peran"] == "pustakawan":
                return redirect(url_for("dashboard_pustakawan"))
            return redirect(url_for("katalog"))
        else:
            flash("NIS/NIP/Email atau kata sandi salah.", "danger")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nomor_induk = request.form.get("nomor_induk", "").strip()  # NIS Siswa
        nama = request.form.get("nama", "").strip()
        kelas = request.form.get("kelas", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        conn = get_db_connection()

        # Cek apakah NIS atau Email sudah terdaftar
        cek_user = conn.execute(
            "SELECT * FROM pengguna WHERE nomor_induk = ? OR email = ?",
            (nomor_induk, email)
        ).fetchone()

        if cek_user:
            flash("NIS atau Email tersebut sudah terdaftar di dalam sistem.", "danger")
            conn.close()
            return redirect(url_for("register"))

        # Hash password agar aman
        password_hash = generate_password_hash(password)

        # Simpan data siswa baru ke database (peran otomatis 'siswa')
        conn.execute("""
                     INSERT INTO pengguna (nomor_induk, nama, peran, kelas, email, password_hash, status)
                     VALUES (?, ?, 'siswa', ?, ?, ?, 'aktif')
                     """, (nomor_induk, nama, kelas, email, password_hash))

        conn.commit()
        conn.close()

        flash("Registrasi berhasil! Silakan masuk menggunakan NIS dan kata sandi Anda.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Anda telah keluar dari sistem.", "info")
    return redirect(url_for("login"))

# --- ROUTES PEMINJAM (SISWA & GURU) ---
@app.route("/")
def katalog():
    cari = request.args.get("q", "").strip()
    kategori_id = request.args.get("kategori", "")
    hanya_tersedia = request.args.get("tersedia", "")

    conn = get_db_connection()
    daftar_kategori = conn.execute("SELECT * FROM kategori").fetchall()

    query = """
        SELECT b.*, k.nama as nama_kategori,
               COUNT(e.id) as total_eksemplar,
               SUM(CASE WHEN e.status = 'tersedia' THEN 1 ELSE 0 END) as stok_tersedia
        FROM buku b
        LEFT JOIN kategori k ON b.kategori_id = k.id
        LEFT JOIN eksemplar e ON b.id = e.buku_id
        WHERE 1=1
    """
    params = []

    if cari:
        query += " AND (b.judul LIKE ? OR b.penulis LIKE ? OR b.isbn LIKE ?)"
        params.extend([f"%{cari}%", f"%{cari}%", f"%{cari}%"])

    if kategori_id:
        query += " AND b.kategori_id = ?"
        params.append(kategori_id)

    query += " GROUP BY b.id"

    if hanya_tersedia == "1":
        query += " HAVING stok_tersedia > 0"

    query += " ORDER BY b.id DESC"
    daftar_buku = conn.execute(query, params).fetchall()
    conn.close()

    return render_template(
        "katalog.html",
        buku_list=daftar_buku,
        kategori_list=daftar_kategori,
        cari=cari,
        kategori_aktif=kategori_id,
        hanya_tersedia=hanya_tersedia
    )

@app.route("/pinjaman-saya")
@login_required
def pinjaman_saya():
    conn = get_db_connection()
    user_id = session["user_id"]

    # Ambil daftar pinjaman milik pengguna yang sedang login
    rows = conn.execute("""
        SELECT p.*, b.judul, b.penulis, b.sampul, e.kode_barcode
        FROM peminjaman p
        JOIN eksemplar e ON p.eksemplar_id = e.id
        JOIN buku b ON e.buku_id = b.id
        WHERE p.pengguna_id = ?
        ORDER BY p.status ASC, p.tgl_jatuh_tempo ASC
    """, (user_id,)).fetchall()

    pinjaman_aktif = []
    riwayat_pinjaman = []

    for r in rows:
        item = dict(r)
        if item["status"] == "dipinjam":
            selisih, denda_estimasi = hitung_denda_berjalan(item["tgl_jatuh_tempo"])
            item["sisa_hari"] = -selisih  # Positif jika masih ada sisa hari, negatif jika lewat
            item["denda_berjalan"] = denda_estimasi
            pinjaman_aktif.append(item)
        else:
            riwayat_pinjaman.append(item)

    # Ambil daftar reservasi aktif
    reservasi_list = conn.execute("""
        SELECT r.*, b.judul, b.penulis, b.lokasi_rak
        FROM reservasi r
        JOIN buku b ON r.buku_id = b.id
        WHERE r.pengguna_id = ? AND r.status IN ('antre', 'siap_diambil')
        ORDER BY r.tgl_reservasi DESC
    """, (user_id,)).fetchall()

    conn.close()
    return render_template(
        "pinjaman_saya.html",
        pinjaman_aktif=pinjaman_aktif,
        riwayat_pinjaman=riwayat_pinjaman,
        reservasi_list=reservasi_list,
        aturan=ATURAN
    )

@app.route("/perpanjang/<int:peminjaman_id>", methods=["POST"])
@login_required
def perpanjang_pinjaman(peminjaman_id):
    conn = get_db_connection()
    pinjam = conn.execute("""
        SELECT p.*, e.buku_id
        FROM peminjaman p
        JOIN eksemplar e ON p.eksemplar_id = e.id
        WHERE p.id = ? AND p.pengguna_id = ?
    """, (peminjaman_id, session["user_id"])).fetchone()

    if not pinjam or pinjam["status"] != "dipinjam":
        flash("Data peminjaman tidak ditemukan atau sudah dikembalikan.", "danger")
        conn.close()
        return redirect(url_for("pinjaman_saya"))

    # Validasi jumlah perpanjangan maksimal 1 kali
    if pinjam["jumlah_perpanjangan"] >= ATURAN["maks_perpanjangan"]:
        flash("Batas maksimal perpanjangan (1 kali) sudah tercapai.", "warning")
        conn.close()
        return redirect(url_for("pinjaman_saya"))

    # Validasi apakah buku sedang diantre/direservasi orang lain
    antrean = conn.execute(
        "SELECT COUNT(*) FROM reservasi WHERE buku_id = ? AND status = 'antre'",
        (pinjam["buku_id"],)
    ).fetchone()[0]

    if antrean > 0:
        flash("Pinjaman tidak dapat diperpanjang karena buku ini sedang dalam antrean reservasi anggota lain.", "warning")
        conn.close()
        return redirect(url_for("pinjaman_saya"))

    # Tambah jatuh tempo 7 hari
    jatuh_tempo_lama = datetime.strptime(pinjam["tgl_jatuh_tempo"], "%Y-%m-%d").date()
    jatuh_tempo_baru = (jatuh_tempo_lama + timedelta(days=7)).strftime("%Y-%m-%d")

    conn.execute("""
        UPDATE peminjaman
        SET tgl_jatuh_tempo = ?, jumlah_perpanjangan = jumlah_perpanjangan + 1
        WHERE id = ?
    """, (jatuh_tempo_baru, peminjaman_id))
    conn.commit()
    conn.close()

    flash(f"Berhasil diperpanjang! Tanggal jatuh tempo baru: {jatuh_tempo_baru}.", "success")
    return redirect(url_for("pinjaman_saya"))

@app.route("/reservasi/<int:buku_id>", methods=["POST"])
@login_required
def buat_reservasi(buku_id):
    conn = get_db_connection()
    sudah_ada = conn.execute("""
        SELECT COUNT(*) FROM reservasi
        WHERE pengguna_id = ? AND buku_id = ? AND status IN ('antre', 'siap_diambil')
    """, (session["user_id"], buku_id)).fetchone()[0]

    if sudah_ada > 0:
        flash("Anda sudah berada dalam antrean reservasi untuk buku ini.", "warning")
    else:
        hari_ini = datetime.now().strftime("%Y-%m-%d")
        conn.execute("""
            INSERT INTO reservasi (pengguna_id, buku_id, tgl_reservasi, status)
            VALUES (?, ?, ?, 'antre')
        """, (session["user_id"], buku_id, hari_ini))
        conn.commit()
        flash("Reservasi berhasil dicatat! Anda akan diberi tahu saat buku tersedia.", "success")

    conn.close()
    return redirect(url_for("pinjaman_saya"))

# --- ROUTES PUSTAKAWAN ---
@app.route("/pustakawan")
@login_required
@pustakawan_required
def dashboard_pustakawan():
    conn = get_db_connection()
    hari_ini = datetime.now().strftime("%Y-%m-%d")

    # Statistik Ringkasan Dashboard sesuai PRD (F-40)
    total_judul = conn.execute("SELECT COUNT(*) FROM buku").fetchone()[0]
    pinjaman_aktif_count = conn.execute("SELECT COUNT(*) FROM peminjaman WHERE status = 'dipinjam'").fetchone()[0]
    jatuh_tempo_hari_ini = conn.execute(
        "SELECT COUNT(*) FROM peminjaman WHERE status = 'dipinjam' AND tgl_jatuh_tempo = ?", (hari_ini,)
    ).fetchone()[0]
    terlambat_count = conn.execute(
        "SELECT COUNT(*) FROM peminjaman WHERE status = 'dipinjam' AND tgl_jatuh_tempo < ?", (hari_ini,)
    ).fetchone()[0]

    # Daftar Transaksi Peminjaman Aktif & Denda
    transaksi_rows = conn.execute("""
        SELECT p.*, u.nomor_induk, u.nama as nama_peminjam, u.peran, u.kelas,
               b.judul, e.kode_barcode
        FROM peminjaman p
        JOIN pengguna u ON p.pengguna_id = u.id
        JOIN eksemplar e ON p.eksemplar_id = e.id
        JOIN buku b ON e.buku_id = b.id
        ORDER BY p.status ASC, p.tgl_jatuh_tempo ASC
    """).fetchall()

    daftar_transaksi = []
    for r in transaksi_rows:
        item = dict(r)
        if item["status"] == "dipinjam":
            selisih, denda_estimasi = hitung_denda_berjalan(item["tgl_jatuh_tempo"])
            item["hari_terlambat"] = max(0, selisih)
            item["denda_hitung"] = denda_estimasi
        else:
            item["hari_terlambat"] = 0
            item["denda_hitung"] = item["denda"]
        daftar_transaksi.append(item)

    kategori_list = conn.execute("SELECT * FROM kategori").fetchall()
    eksemplar_tersedia = conn.execute("""
        SELECT e.kode_barcode, b.judul
        FROM eksemplar e JOIN buku b ON e.buku_id = b.id
        WHERE e.status = 'tersedia'
    """).fetchall()
    anggota_list = conn.execute(
        "SELECT nomor_induk, nama, peran, kelas FROM pengguna WHERE peran IN ('siswa', 'guru')"
    ).fetchall()

    conn.close()
    return render_template(
        "pustakawan.html",
        stats={
            "total_judul": total_judul,
            "pinjaman_aktif": pinjaman_aktif_count,
            "jatuh_tempo_hari_ini": jatuh_tempo_hari_ini,
            "terlambat": terlambat_count
        },
        transaksi_list=daftar_transaksi,
        kategori_list=kategori_list,
        eksemplar_tersedia=eksemplar_tersedia,
        anggota_list=anggota_list
    )

@app.route("/pustakawan/pinjam", methods=["POST"])
@login_required
@pustakawan_required
def proses_peminjaman():
    nomor_induk = request.form.get("nomor_induk", "").strip()
    kode_barcode = request.form.get("kode_barcode", "").strip()

    conn = get_db_connection()
    anggota = conn.execute("SELECT * FROM pengguna WHERE nomor_induk = ?", (nomor_induk,)).fetchone()
    if not anggota:
        flash(f"Anggota dengan NIS/NIP '{nomor_induk}' tidak ditemukan!", "danger")
        conn.close()
        return redirect(url_for("dashboard_pustakawan"))

    # 1. Cek apakah anggota punya denda yang belum lunas (Aturan Pemblokiran PRD)
    denda_belum_lunas = conn.execute("""
        SELECT COUNT(*) FROM peminjaman
        WHERE pengguna_id = ? AND status_bayar_denda = 'belum_lunas'
    """, (anggota["id"],)).fetchone()[0]

    if denda_belum_lunas > 0:
        flash(f"Transaksi ditolak! {anggota['nama']} memiliki tunggakan denda yang belum lunas.", "danger")
        conn.close()
        return redirect(url_for("dashboard_pustakawan"))

    # 2. Cek kuota pinjaman aktif (Siswa: 3 buku, Guru: 5 buku)
    kuota_maks = ATURAN["kuota_guru"] if anggota["peran"] == "guru" else ATURAN["kuota_siswa"]
    sedang_dipinjam = conn.execute("""
        SELECT COUNT(*) FROM peminjaman WHERE pengguna_id = ? AND status = 'dipinjam'
    """, (anggota["id"],)).fetchone()[0]

    if sedang_dipinjam >= kuota_maks:
        flash(f"Kuota penuh! {anggota['nama']} sedang meminjam {sedang_dipinjam} buku (Maksimal {kuota_maks}).", "warning")
        conn.close()
        return redirect(url_for("dashboard_pustakawan"))

    # 3. Cek ketersediaan eksemplar buku berdasarkan barcode
    eks = conn.execute("""
        SELECT e.*, b.judul FROM eksemplar e
        JOIN buku b ON e.buku_id = b.id
        WHERE e.kode_barcode = ?
    """, (kode_barcode,)).fetchone()

    if not eks:
        flash(f"Eksemplar dengan kode barcode '{kode_barcode}' tidak ditemukan!", "danger")
        conn.close()
        return redirect(url_for("dashboard_pustakawan"))

    if eks["status"] != "tersedia":
        flash(f"Buku '{eks['judul']}' ({kode_barcode}) sedang tidak tersedia (Status: {eks['status']}).", "warning")
        conn.close()
        return redirect(url_for("dashboard_pustakawan"))

    # 4. Hitung tanggal pinjam & jatuh tempo (Siswa: 7 hari, Guru: 14 hari)
    durasi = ATURAN["durasi_guru"] if anggota["peran"] == "guru" else ATURAN["durasi_siswa"]
    tgl_pinjam = datetime.now().date()
    tgl_jatuh_tempo = tgl_pinjam + timedelta(days=durasi)

    conn.execute("""
        INSERT INTO peminjaman (pengguna_id, eksemplar_id, tgl_pinjam, tgl_jatuh_tempo, status)
        VALUES (?, ?, ?, ?, 'dipinjam')
    """, (anggota["id"], eks["id"], tgl_pinjam.strftime("%Y-%m-%d"), tgl_jatuh_tempo.strftime("%Y-%m-%d")))

    conn.execute("UPDATE eksemplar SET status = 'dipinjam' WHERE id = ?", (eks["id"],))
    conn.commit()
    conn.close()

    flash(f"Peminjaman berhasil! '{eks['judul']}' dipinjam oleh {anggota['nama']} hingga {tgl_jatuh_tempo}.", "success")
    return redirect(url_for("dashboard_pustakawan"))

@app.route("/pustakawan/kembali/<int:peminjaman_id>", methods=["POST"])
@login_required
@pustakawan_required
def proses_pengembalian(peminjaman_id):
    kondisi_buku = request.form.get("kondisi", "baik")
    conn = get_db_connection()

    pinjam = conn.execute("""
        SELECT p.*, e.buku_id, e.kode_barcode, b.judul
        FROM peminjaman p
        JOIN eksemplar e ON p.eksemplar_id = e.id
        JOIN buku b ON e.buku_id = b.id
        WHERE p.id = ?
    """, (peminjaman_id,)).fetchone()

    if not pinjam or pinjam["status"] != "dipinjam":
        flash("Data peminjaman tidak valid atau sudah selesai.", "warning")
        conn.close()
        return redirect(url_for("dashboard_pustakawan"))

    hari_ini = datetime.now().strftime("%Y-%m-%d")
    _, total_denda = hitung_denda_berjalan(pinjam["tgl_jatuh_tempo"])
    status_denda = "belum_lunas" if total_denda > 0 else "tidak_ada"

    # Update transaksi peminjaman
    conn.execute("""
        UPDATE peminjaman
        SET tgl_kembali = ?, status = 'kembali', denda = ?, status_bayar_denda = ?
        WHERE id = ?
    """, (hari_ini, total_denda, status_denda, peminjaman_id))

    # Update status eksemplar fisik sesuai kondisinya saat kembali (F-24)
    status_eksemplar_baru = "tersedia" if kondisi_buku == "baik" else kondisi_buku
    conn.execute("""
        UPDATE eksemplar SET kondisi = ?, status = ? WHERE id = ?
    """, (kondisi_buku, status_eksemplar_baru, pinjam["eksemplar_id"]))

    # Bila buku tersedia kembali dan ada antrean reservasi, ubah status pengantre pertama
    if status_eksemplar_baru == "tersedia":
        antrean_pertama = conn.execute("""
            SELECT id FROM reservasi
            WHERE buku_id = ? AND status = 'antre'
            ORDER BY tgl_reservasi ASC, id ASC LIMIT 1
        """, (pinjam["buku_id"],)).fetchone()
        if antrean_pertama:
            conn.execute("UPDATE reservasi SET status = 'siap_diambil' WHERE id = ?", (antrean_pertama["id"],))

    conn.commit()
    conn.close()

    if total_denda > 0:
        flash(f"Buku '{pinjam['judul']}' dikembalikan dengan denda keterlambatan Rp{total_denda:,}.", "warning")
    else:
        flash(f"Buku '{pinjam['judul']}' ({pinjam['kode_barcode']}) berhasil dikembalikan tepat waktu!", "success")

    return redirect(url_for("dashboard_pustakawan"))

@app.route("/pustakawan/lunas-denda/<int:peminjaman_id>", methods=["POST"])
@login_required
@pustakawan_required
def lunasi_denda(peminjaman_id):
    conn = get_db_connection()
    conn.execute("UPDATE peminjaman SET status_bayar_denda = 'lunas' WHERE id = ?", (peminjaman_id,))
    conn.commit()
    conn.close()
    flash("Pembayaran denda berhasil dicatat sebagai LUNAS!", "success")
    return redirect(url_for("dashboard_pustakawan"))

@app.route("/pustakawan/tambah-buku", methods=["POST"])
@login_required
@pustakawan_required
def tambah_buku():
    judul = request.form.get("judul", "").strip()
    penulis = request.form.get("penulis", "").strip()
    penerbit = request.form.get("penerbit", "").strip()
    tahun = request.form.get("tahun", 2026)
    isbn = request.form.get("isbn", "").strip()
    kategori_id = request.form.get("kategori_id")
    lokasi_rak = request.form.get("lokasi_rak", "").strip()
    sampul = request.form.get("sampul", "").strip() or "https://images.unsplash.com/photo-1543002588-bfa74002ed7e?auto=format&fit=crop&w=400&q=80"
    sinopsis = request.form.get("sinopsis", "").strip()
    jumlah_eksemplar = int(request.form.get("jumlah_eksemplar", 1))
    prefix_barcode = request.form.get("prefix_barcode", "BK-NEW").strip().upper()

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO buku (judul, penulis, penerbit, tahun, isbn, kategori_id, sinopsis, sampul, lokasi_rak)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (judul, penulis, penerbit, tahun, isbn, kategori_id, sinopsis, sampul, lokasi_rak))
        buku_id = cursor.lastrowid

        # Buat kode barcode otomatis sejumlah eksemplar yang diinput
        for i in range(1, jumlah_eksemplar + 1):
            kode = f"{prefix_barcode}-{buku_id:03d}-{i}"
            cursor.execute("""
                INSERT INTO eksemplar (buku_id, kode_barcode, kondisi, status)
                VALUES (?, ?, 'baik', 'tersedia')
            """, (buku_id, kode))

        conn.commit()
        flash(f"Buku '{judul}' beserta {jumlah_eksemplar} eksemplar berhasil ditambahkan!", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Gagal menambahkan buku: {str(e)}", "danger")
    finally:
        conn.close()

    return redirect(url_for("dashboard_pustakawan"))

if __name__ == "__main__":
    app.run(debug=True, port=5000)