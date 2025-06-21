# api/index.py

import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from markupsafe import Markup, escape
from pymongo import MongoClient
from bson.objectid import ObjectId
import requests
from dotenv import load_dotenv
import re
from werkzeug.security import generate_password_hash, check_password_hash
from math import ceil

# Muat variabel lingkungan dari file .env
load_dotenv()

# Dapatkan jalur absolut ke direktori ini (api/)
current_dir = os.path.dirname(os.path.abspath(__file__))
# Tentukan jalur ke root proyek (satu tingkat di atas api/)
project_root = os.path.join(current_dir, "..")

# Inisialisasi aplikasi Flask
app = Flask(__name__, root_path=project_root, template_folder="templates")

# SECRET_KEY harus diatur sebagai Environment Variable di Vercel
app.secret_key = os.getenv('SECRET_KEY') 
if not app.secret_key:
    print("Warning: SECRET_KEY not set. Session will not be secure.")
    app.secret_key = 'temporary_insecure_key_for_dev_only'


# Konfigurasi MongoDB Atlas
MONGO_URI = os.getenv('MONGO_URI')
if not MONGO_URI:
    raise ValueError("MONGO_URI environment variable not set. Please set it in Vercel.")

client = MongoClient(MONGO_URI)
db = client['ecommerce_db']
products_collection = db['products']
users_collection = db['users']

# Konfigurasi Imgur API
IMGUR_CLIENT_ID = os.getenv('IMGUR_CLIENT_ID')
if not IMGUR_CLIENT_ID:
    print("Warning: IMGUR_CLIENT_ID not set. Imgur upload will not work.")
IMGUR_UPLOAD_URL = "https://api.imgur.com/3/image"


# Konstanta Paginasi
PER_PAGE = 9 # Jumlah produk per halaman

# Fungsi untuk mengunggah satu gambar ke Imgur
def upload_single_image_to_imgur(image_file_stream):
    """
    Mengunggah satu stream file gambar ke Imgur dan mengembalikan URL gambar.
    """
    if not IMGUR_CLIENT_ID:
        flash("Imgur Client ID tidak diatur, unggah gambar tidak berfungsi.", 'danger')
        return None
    if not image_file_stream:
        return None

    headers = {'Authorization': f'Client-ID {IMGUR_CLIENT_ID}'}
    files = {'image': image_file_stream.read()}

    try:
        response = requests.post(IMGUR_UPLOAD_URL, headers=headers, files=files)
        response.raise_for_status()
        data = response.json()
        if data['success']:
            return data['data']['link']
        else:
            print(f"Imgur upload error: {data.get('data', {}).get('error', 'Unknown error')}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Connection error during Imgur upload: {e}")
        return None

# Filter kustom nl2br
@app.template_filter('nl2br')
def nl2br_filter(s):
    """
    Filter Jinja2 kustom untuk mengubah karakter newline (\n) menjadi tag HTML <br>.
    Digunakan untuk menampilkan teks dengan pemformatan baris baru dari input textarea.
    """
    if s is None:
        return ''
    return Markup(s.replace('\n', '<br>'))

# Filter kustom escapejs
@app.template_filter('escapejs')
def escapejs_filter(s):
    """
    Filter Jinja2 kustom untuk meng-escape string agar aman digunakan dalam JavaScript.
    """
    if s is None:
        return ''
    return escape(s).replace("'", "\\'").replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r')

# Inisialisasi variabel sesi
@app.before_request
def initialize_session_variables():
    if 'cart' not in session:
        session['cart'] = {}
    
    if 'user_id' not in session:
        session['user_id'] = None
    if 'username' not in session:
        session['username'] = None
    if 'is_admin' not in session:
        session['is_admin'] = False
    if 'is_customer' not in session:
        session['is_customer'] = False

    app.jinja_env.globals['current_logged_in_user'] = session.get('username')
    app.jinja_env.globals['is_admin_logged_in'] = session.get('is_admin')
    app.jinja_env.globals['is_customer_logged_in'] = session.get('is_customer')

# Dekorator untuk memeriksa login admin
def admin_required(f):
    def wrap(*args, **kwargs):
        if not session.get('is_admin'):
            flash('Anda tidak memiliki izin untuk mengakses halaman ini.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

# Dekorator untuk memeriksa login customer atau admin
def login_required(f):
    def wrap(*args, **kwargs):
        if not session.get('user_id'):
            flash('Anda harus login untuk mengakses halaman ini.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

@app.route('/')
def index():
    """Menampilkan daftar semua produk, dengan opsi filter kategori, pencarian, dan paginasi."""
    selected_category_param = request.args.get('category')
    search_query = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    query = {}
    selected_category_for_template = selected_category_param

    if selected_category_param and selected_category_param not in ['all', 'None']:
        query['category'] = selected_category_param
    else:
        selected_category_for_template = 'all'

    if search_query:
        query['name'] = {'$regex': re.compile(search_query, re.IGNORECASE)}

    total_products = products_collection.count_documents(query)
    total_pages = ceil(total_products / PER_PAGE)
    
    if total_pages > 0 and page > total_pages:
        page = total_pages
    elif total_pages == 0:
        page = 1

    skip_count = (page - 1) * PER_PAGE
    
    products = list(products_collection.find(query).skip(skip_count).limit(PER_PAGE))
    
    all_categories = sorted(list(set(p['category'] for p in products_collection.find({}, {'category': 1}) if p.get('category'))))

    print(f"MongoDB Query: {query}, Page: {page}, Skip: {skip_count}, Limit: {PER_PAGE}, Total Products: {total_products}")


    return render_template('index.html', 
                           products=products, 
                           all_categories=all_categories, 
                           selected_category=selected_category_for_template,
                           search_query=search_query,
                           current_page=page,
                           total_pages=total_pages,
                           total_products=total_products
                           )

@app.route('/add_product', methods=['GET', 'POST'])
@admin_required
def add_product():
    """Menambahkan produk baru ke database."""
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        price = float(request.form['price'])
        category = request.form['category'].strip() 
        
        image_files = request.files.getlist('images') # Menggunakan 'images' (plural)
        uploaded_image_urls = []

        for img_file in image_files:
            if img_file and img_file.filename != '':
                image_url = upload_single_image_to_imgur(img_file)
                if image_url:
                    uploaded_image_urls.append(image_url)
        
        # Jika tidak ada gambar yang diunggah dan tidak ada gambar yang berhasil diunggah
        if not uploaded_image_urls and any(f.filename for f in image_files):
            flash('Gagal mengunggah beberapa atau semua gambar.', 'danger')
            return render_template('add_product.html')

        product_data = {
            'name': name,
            'description': description,
            'price': price,
            'category': category,
            'image_urls': uploaded_image_urls # Menyimpan sebagai array
        }
        products_collection.insert_one(product_data)
        flash('Produk berhasil ditambahkan!', 'success')
        return redirect(url_for('index'))
    return render_template('add_product.html')

@app.route('/product/<id>')
def product_detail(id):
    """Menampilkan detail satu produk."""
    product = products_collection.find_one({'_id': ObjectId(id)})
    if product:
        # Untuk kompatibilitas mundur dengan produk lama yang mungkin hanya punya 'image_url' (string)
        if 'image_url' in product and not isinstance(product.get('image_urls'), list):
            product['image_urls'] = [product['image_url']]
        elif 'image_urls' not in product:
            product['image_urls'] = [] # Pastikan selalu ada list kosong
        return render_template('product_detail.html', product=product)
    flash('Produk tidak ditemukan.', 'danger')
    return redirect(url_for('index'))

@app.route('/edit_product/<id>', methods=['GET', 'POST'])
@admin_required
def edit_product(id):
    """Mengedit produk yang sudah ada."""
    product = products_collection.find_one({'_id': ObjectId(id)})
    if not product:
        flash('Produk tidak ditemukan.', 'danger')
        return redirect(url_for('index'))

    # Untuk kompatibilitas mundur: pastikan image_urls adalah list
    if 'image_url' in product and not isinstance(product.get('image_urls'), list):
        current_image_urls = [product['image_url']]
    else:
        current_image_urls = product.get('image_urls', [])

    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        price = float(request.form['price'])
        category = request.form['category'].strip() 
        
        # Dapatkan daftar URL gambar yang akan dipertahankan dari formulir
        # Jika tidak ada yang dikirim (misal, semua dihapus), ini akan menjadi string kosong,
        # jadi kita pecah berdasarkan koma dan filter string kosong.
        kept_image_urls_str = request.form.get('kept_image_urls', '')
        kept_image_urls = [url.strip() for url in kept_image_urls_str.split(',') if url.strip()]

        # Tangani file gambar baru yang diunggah
        new_image_files = request.files.getlist('new_images')
        uploaded_new_image_urls = []

        for img_file in new_image_files:
            if img_file and img_file.filename != '':
                image_url = upload_single_image_to_imgur(img_file)
                if image_url:
                    uploaded_new_image_urls.append(image_url)

        # Gabungkan gambar yang dipertahankan dengan gambar yang baru diunggah
        final_image_urls = kept_image_urls + uploaded_new_image_urls
        
        # Validasi: Jika tidak ada gambar sama sekali setelah edit/hapus
        if not final_image_urls:
            flash('Produk harus memiliki setidaknya satu gambar. Tidak ada gambar yang disimpan.', 'danger')
            # Kembali ke halaman edit, tampilkan gambar yang awalnya ada
            product['image_urls'] = current_image_urls
            return render_template('edit_product.html', product=product)

        products_collection.update_one(
            {'_id': ObjectId(id)},
            {'$set': {
                'name': name,
                'description': description,
                'price': price,
                'category': category,
                'image_urls': final_image_urls # Simpan sebagai array
            }}
        )
        flash('Produk berhasil diperbarui!', 'success')
        return redirect(url_for('product_detail', id=id))

    product['image_urls'] = current_image_urls # Pastikan product object yang dikirim ke template juga punya list
    return render_template('edit_product.html', product=product)

@app.route('/delete_product/<id>', methods=['POST'])
@admin_required
def delete_product(id):
    """Menghapus produk dari database."""
    result = products_collection.delete_one({'_id': ObjectId(id)})
    if result.deleted_count > 0:
        flash('Produk berhasil dihapus!', 'success')
    else:
        flash('Produk tidak ditemukan.', 'danger')
    return redirect(url_for('index'))

# ---- Rute untuk Keranjang Belanja ----

@app.route('/add_to_cart/<product_id>', methods=['POST'])
def add_to_cart(product_id):
    """Menambahkan produk ke keranjang belanja."""
    product = products_collection.find_one({'_id': ObjectId(product_id)})
    if product:
        product['_id'] = str(product['_id']) 
        
        if product_id in session['cart']:
            session['cart'][product_id]['quantity'] += 1
        else:
            # Di keranjang, kita hanya menyimpan gambar pertama untuk tampilan
            first_image_url = product.get('image_urls', [None])[0] 
            session['cart'][product_id] = {
                'name': product['name'],
                'price': product['price'],
                'image_url': first_image_url,
                'quantity': 1
            }
        session.modified = True
        flash(f'{product["name"]} telah ditambahkan ke keranjang!', 'success')
    else:
        flash('Produk tidak ditemukan.', 'danger')
    return redirect(request.referrer or url_for('index'))

@app.route('/remove_from_cart/<product_id>', methods=['POST'])
def remove_from_cart(product_id):
    """Menghapus satu item atau seluruh produk dari keranjang belanja."""
    if product_id in session['cart']:
        session['cart'][product_id]['quantity'] -= 1
        if session['cart'][product_id]['quantity'] <= 0:
            del session['cart'][product_id]
        session.modified = True
        flash('Item berhasil diperbarui di keranjang.', 'info')
    else:
        flash('Item tidak ditemukan di keranjang.', 'warning')
    return redirect(url_for('view_cart'))

@app.route('/clear_item_from_cart/<product_id>', methods=['POST'])
def clear_item_from_cart(product_id):
    """Menghapus seluruh kuantitas produk dari keranjang belanja."""
    if product_id in session['cart']:
        product_name = session['cart'][product_id]['name']
        del session['cart'][product_id]
        session.modified = True
        flash(f'{product_name} telah dihapus sepenuhnya dari keranjang.', 'info')
    else:
        flash('Item tidak ditemukan di keranjang.', 'warning')
    return redirect(url_for('view_cart'))


@app.route('/cart')
def view_cart():
    """Menampilkan isi keranjang belanja."""
    cart_items = []
    total_price = 0
    for product_id, item_data in session['cart'].items():
        cart_items.append({
            'id': product_id,
            'name': item_data['name'],
            'price': item_data['price'],
            'quantity': item_data['quantity'],
            'image_url': item_data.get('image_url'),
            'subtotal': item_data['price'] * item_data['quantity']
        })
        total_price += item_data['price'] * item_data['quantity']
    return render_template('cart.html', cart_items=cart_items, total_price=total_price)

@app.context_processor
def inject_cart_count():
    """Menyuntikkan jumlah item di keranjang ke semua template."""
    cart_count = sum(item['quantity'] for item in session.get('cart', {}).values())
    return dict(cart_count=cart_count)

# ---- Rute Autentikasi Admin & Pelanggan ----

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('is_admin') or session.get('is_customer'):
        flash('Anda sudah login.', 'info')
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = users_collection.find_one({'username': username})

        if user and check_password_hash(user['password'], password):
            session['user_id'] = str(user['_id'])
            session['username'] = user['username']
            session['is_admin'] = (user.get('role') == 'admin')
            session['is_customer'] = (user.get('role') == 'customer')
            flash(f'Selamat datang, {user["username"]}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Nama pengguna atau kata sandi salah.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    """Rute untuk pendaftaran pelanggan baru."""
    if session.get('user_id'):
        flash('Anda sudah login.', 'info')
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        
        if not username or not password:
            flash('Nama pengguna dan kata sandi tidak boleh kosong.', 'danger')
            return render_template('register.html')
        
        if users_collection.find_one({'username': username}):
            flash('Nama pengguna sudah ada. Pilih nama pengguna lain.', 'warning')
            return render_template('register.html')

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        
        users_collection.insert_one({
            'username': username,
            'password': hashed_password,
            'role': 'customer'
        })
        flash(f'Akun "{username}" berhasil dibuat! Silakan login.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('is_admin', None)
    session.pop('is_customer', None)
    flash('Anda telah berhasil logout.', 'info')
    return redirect(url_for('index'))

@app.route('/create_first_admin', methods=['GET', 'POST'])
def create_first_admin():
    """
    Rute sementara untuk membuat akun admin pertama.
    Ini harus DIHAPUS atau diamankan setelah admin pertama dibuat.
    """
    if users_collection.find_one({'role': 'admin'}):
        flash('Admin sudah ada. Anda tidak bisa membuat admin baru dari sini.', 'warning')
        return redirect(url_for('login'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        
        if not username or not password:
            flash('Nama pengguna dan kata sandi tidak boleh kosong.', 'danger')
            return render_template('create_first_admin.html')

        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        
        users_collection.insert_one({
            'username': username,
            'password': hashed_password,
            'role': 'admin'
        })
        flash(f'Akun admin "{username}" berhasil dibuat! Silakan login.', 'success')
        return redirect(url_for('login'))
    return render_template('create_first_admin.html')

