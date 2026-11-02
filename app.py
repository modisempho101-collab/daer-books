from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from sqlalchemy import func
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'daer-books-secret-key-2026-distinction')

# Database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///daerbooks.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Email (optional)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your_email@gmail.com'
app.config['MAIL_PASSWORD'] = 'your_app_password'
app.config['MAIL_DEFAULT_SENDER'] = 'Daer Books <noreply@daerbooks.com>'

db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# ====================== MODELS ======================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    orders = db.relationship('Order', backref='customer', lazy=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(150))
    isbn = db.Column(db.String(20), unique=True)
    price = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    reorder_level = db.Column(db.Integer, default=5)
    description = db.Column(db.Text)
    category = db.Column(db.String(100))
    image_url = db.Column(db.String(300), default='https://via.placeholder.com/200x300?text=Book')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class DiscountCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_percent = db.Column(db.Float, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    min_order_amount = db.Column(db.Float, default=0)
    max_uses = db.Column(db.Integer, default=0)
    times_used = db.Column(db.Integer, default=0)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    order_date = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(50), default='Pending')
    subtotal = db.Column(db.Float)
    discount_amount = db.Column(db.Float, default=0)
    total = db.Column(db.Float)
    discount_code_used = db.Column(db.String(50))
    shipping_address = db.Column(db.Text)
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')

class OrderItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)
    product = db.relationship('Product')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ====================== HELPERS ======================

def send_email(to, subject, body):
    try:
        msg = Message(subject, recipients=[to])
        msg.body = body
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Email error (ignored for demo): {e}")
        return False

def get_cart():
    return session.get('cart', {})

def get_cart_items():
    cart = get_cart()
    items = []
    subtotal = 0.0

    for product_id, quantity in cart.items():
        product = Product.query.get(int(product_id))
        if product and product.is_active:
            line_total = product.price * quantity
            subtotal += line_total
            items.append({
                'product': product,
                'quantity': quantity,
                'line_total': line_total
            })

    discount_code = session.get('discount_code')
    discount_amount = 0.0
    discount_percent = 0.0

    if discount_code:
        code = DiscountCode.query.filter_by(code=discount_code, is_active=True).first()
        if code and subtotal >= code.min_order_amount:
            discount_percent = code.discount_percent
            discount_amount = round(subtotal * (discount_percent / 100), 2)
        else:
            session.pop('discount_code', None)
            discount_code = None

    total = round(subtotal - discount_amount, 2)

    return {
        'items': items,
        'subtotal': round(subtotal, 2),
        'discount_code': discount_code,
        'discount_percent': discount_percent,
        'discount_amount': discount_amount,
        'total': total,
        'item_count': sum(item['quantity'] for item in items)
    }

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ====================== PUBLIC ROUTES ======================

@app.route('/')
def index():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    sort = request.args.get('sort', 'title')

    query = Product.query.filter_by(is_active=True)

    if q:
        query = query.filter(
            db.or_(
                Product.title.ilike(f'%{q}%'),
                Product.author.ilike(f'%{q}%'),
                Product.isbn.ilike(f'%{q}%')
            )
        )

    if category:
        query = query.filter_by(category=category)

    if sort == 'price_low':
        query = query.order_by(Product.price.asc())
    elif sort == 'price_high':
        query = query.order_by(Product.price.desc())
    elif sort == 'newest':
        query = query.order_by(Product.created_at.desc())
    else:
        query = query.order_by(Product.title.asc())

    products = query.all()
    categories = db.session.query(Product.category).filter_by(is_active=True).distinct().all()
    categories = [c[0] for c in categories if c[0]]

    cart_data = get_cart_items()
    return render_template('index.html',
                           products=products,
                           categories=categories,
                           cart_count=cart_data['item_count'],
                           search_q=q,
                           selected_category=category,
                           selected_sort=sort)

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    product = Product.query.get_or_404(product_id)
    cart_data = get_cart_items()
    return render_template('product.html', product=product, cart_count=cart_data['item_count'])

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password')
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()

        if not email or not password or not first_name:
            flash('Please fill in all required fields.', 'warning')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Email already registered. Please login.', 'danger')
            return redirect(url_for('login'))

        hashed = generate_password_hash(password, method='pbkdf2:sha256')
        user = User(email=email, password=hashed, first_name=first_name, last_name=last_name)
        db.session.add(user)
        db.session.commit()

        flash('Account created successfully! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'POST':
        email = request.form.get('email', '').lower().strip()
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password, password):
            login_user(user)
            flash(f'Welcome back, {user.first_name}!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page or url_for('index'))
        else:
            flash('Invalid email or password.', 'danger')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# ---------- CART ----------

@app.route('/add_to_cart/<int:product_id>', methods=['POST'])
def add_to_cart(product_id):
    product = Product.query.get_or_404(product_id)
    if not product.is_active:
        flash('This book is no longer available.', 'danger')
        return redirect(url_for('index'))

    quantity = int(request.form.get('quantity', 1))
    if quantity < 1:
        quantity = 1

    cart = get_cart()
    pid = str(product_id)
    new_qty = cart.get(pid, 0) + quantity

    if new_qty > product.stock:
        flash(f'Sorry, only {product.stock} copies of "{product.title}" are available.', 'warning')
        return redirect(request.referrer or url_for('index'))

    cart[pid] = new_qty
    session['cart'] = cart
    session.modified = True
    flash(f'"{product.title}" added to cart!', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/cart')
def view_cart():
    cart_data = get_cart_items()
    return render_template('cart.html', cart=cart_data, cart_count=cart_data['item_count'])

@app.route('/update_cart', methods=['POST'])
def update_cart():
    cart = get_cart()
    for key, value in request.form.items():
        if key.startswith('quantity_'):
            pid = key.replace('quantity_', '')
            try:
                qty = int(value)
            except ValueError:
                qty = 1
            product = Product.query.get(int(pid))
            if not product:
                continue
            if qty <= 0:
                cart.pop(pid, None)
            else:
                if qty > product.stock:
                    flash(f'Only {product.stock} copies of "{product.title}" available.', 'warning')
                    qty = product.stock
                cart[pid] = qty
    session['cart'] = cart
    session.modified = True
    flash('Cart updated.', 'success')
    return redirect(url_for('view_cart'))

@app.route('/remove_from_cart/<int:product_id>')
def remove_from_cart(product_id):
    cart = get_cart()
    pid = str(product_id)
    if pid in cart:
        product = Product.query.get(product_id)
        title = product.title if product else "Item"
        del cart[pid]
        session['cart'] = cart
        session.modified = True
        flash(f'"{title}" removed from cart.', 'info')
    return redirect(url_for('view_cart'))

@app.route('/apply_discount', methods=['POST'])
def apply_discount():
    code_input = request.form.get('discount_code', '').strip().upper()
    if not code_input:
        flash('Please enter a discount code.', 'warning')
        return redirect(url_for('view_cart'))

    discount = DiscountCode.query.filter_by(code=code_input, is_active=True).first()
    if not discount:
        flash('Invalid or expired discount code.', 'danger')
        return redirect(url_for('view_cart'))

    cart_data = get_cart_items()
    if cart_data['subtotal'] < discount.min_order_amount:
        flash(f'This code requires a minimum order of R{discount.min_order_amount:.2f}.', 'warning')
        return redirect(url_for('view_cart'))

    if discount.max_uses > 0 and discount.times_used >= discount.max_uses:
        flash('This discount code has reached its usage limit.', 'danger')
        return redirect(url_for('view_cart'))

    session['discount_code'] = discount.code
    session.modified = True
    flash(f'Discount code "{discount.code}" applied! You save {discount.discount_percent}%.', 'success')
    return redirect(url_for('view_cart'))

@app.route('/remove_discount')
def remove_discount():
    session.pop('discount_code', None)
    session.modified = True
    flash('Discount code removed.', 'info')
    return redirect(url_for('view_cart'))

@app.route('/clear_cart')
def clear_cart():
    session.pop('cart', None)
    session.pop('discount_code', None)
    session.modified = True
    flash('Cart cleared.', 'info')
    return redirect(url_for('view_cart'))

# ---------- CHECKOUT & ORDERS ----------

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    cart_data = get_cart_items()
    if not cart_data['items']:
        flash('Your cart is empty.', 'warning')
        return redirect(url_for('view_cart'))

    if request.method == 'POST':
        address = request.form.get('shipping_address', '').strip()
        if not address:
            flash('Please enter a shipping address.', 'warning')
            return redirect(url_for('checkout'))

        for item in cart_data['items']:
            if item['quantity'] > item['product'].stock:
                flash(f'Not enough stock for "{item["product"].title}".', 'danger')
                return redirect(url_for('view_cart'))

        order = Order(
            user_id=current_user.id,
            subtotal=cart_data['subtotal'],
            discount_amount=cart_data['discount_amount'],
            total=cart_data['total'],
            discount_code_used=cart_data['discount_code'],
            shipping_address=address,
            status='Paid'
        )
        db.session.add(order)
        db.session.flush()

        for item in cart_data['items']:
            oi = OrderItem(
                order_id=order.id,
                product_id=item['product'].id,
                quantity=item['quantity'],
                price=item['product'].price
            )
            db.session.add(oi)
            item['product'].stock -= item['quantity']

        if cart_data['discount_code']:
            code = DiscountCode.query.filter_by(code=cart_data['discount_code']).first()
            if code:
                code.times_used += 1

        db.session.commit()

        session.pop('cart', None)
        session.pop('discount_code', None)
        session.modified = True

        send_email(
            current_user.email,
            f"Order Confirmation #{order.id} - Daer Books",
            f"Hi {current_user.first_name},\n\nThank you for your order!\n\nOrder Number: #{order.id}\nTotal: R{order.total:.2f}\nStatus: {order.status}\n\nBest regards,\nDaer Books Team"
        )

        flash(f'Order #{order.id} placed successfully! Total: R{order.total:.2f}', 'success')
        return redirect(url_for('order_confirmation', order_id=order.id))

    return render_template('checkout.html', cart=cart_data, cart_count=cart_data['item_count'])

@app.route('/order/<int:order_id>')
@login_required
def order_confirmation(order_id):
    order = Order.query.get_or_404(order_id)
    if order.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    cart_data = get_cart_items()
    return render_template('order_confirmation.html', order=order, cart_count=cart_data['item_count'])

@app.route('/my-orders')
@login_required
def my_orders():
    orders = Order.query.filter_by(user_id=current_user.id).order_by(Order.order_date.desc()).all()
    cart_data = get_cart_items()
    return render_template('my_orders.html', orders=orders, cart_count=cart_data['item_count'])

# ====================== ADMIN ======================

@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    total_products = Product.query.count()
    total_orders = Order.query.count()
    total_users = User.query.count()
    total_revenue = db.session.query(func.sum(Order.total)).filter(Order.status != 'Cancelled').scalar() or 0
    low_stock = Product.query.filter(Product.stock <= Product.reorder_level, Product.is_active == True).all()
    recent_orders = Order.query.order_by(Order.order_date.desc()).limit(8).all()

    seven_days_ago = datetime.utcnow() - timedelta(days=7)
    recent_revenue = db.session.query(func.sum(Order.total)).filter(
        Order.order_date >= seven_days_ago,
        Order.status != 'Cancelled'
    ).scalar() or 0

    cart_data = get_cart_items()
    return render_template('admin/dashboard.html',
                           total_products=total_products,
                           total_orders=total_orders,
                           total_users=total_users,
                           total_revenue=total_revenue,
                           recent_revenue=recent_revenue,
                           low_stock=low_stock,
                           recent_orders=recent_orders,
                           cart_count=cart_data['item_count'])

@app.route('/admin/products')
@login_required
@admin_required
def admin_products():
    products = Product.query.order_by(Product.title).all()
    cart_data = get_cart_items()
    return render_template('admin/products.html', products=products, cart_count=cart_data['item_count'])

@app.route('/admin/products/add', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_add_product():
    if request.method == 'POST':
        product = Product(
            title=request.form.get('title'),
            author=request.form.get('author'),
            isbn=request.form.get('isbn'),
            price=float(request.form.get('price', 0)),
            stock=int(request.form.get('stock', 0)),
            reorder_level=int(request.form.get('reorder_level', 5)),
            category=request.form.get('category'),
            description=request.form.get('description'),
            image_url=request.form.get('image_url') or 'https://via.placeholder.com/200x300?text=Book'
        )
        db.session.add(product)
        db.session.commit()
        flash('Product added successfully.', 'success')
        return redirect(url_for('admin_products'))
    cart_data = get_cart_items()
    return render_template('admin/product_form.html', product=None, cart_count=cart_data['item_count'])

@app.route('/admin/products/edit/<int:product_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        product.title = request.form.get('title')
        product.author = request.form.get('author')
        product.isbn = request.form.get('isbn')
        product.price = float(request.form.get('price', 0))
        product.stock = int(request.form.get('stock', 0))
        product.reorder_level = int(request.form.get('reorder_level', 5))
        product.category = request.form.get('category')
        product.description = request.form.get('description')
        product.image_url = request.form.get('image_url') or product.image_url
        product.is_active = True if request.form.get('is_active') == 'on' else False
        db.session.commit()
        flash('Product updated successfully.', 'success')
        return redirect(url_for('admin_products'))
    cart_data = get_cart_items()
    return render_template('admin/product_form.html', product=product, cart_count=cart_data['item_count'])

@app.route('/admin/products/delete/<int:product_id>')
@login_required
@admin_required
def admin_delete_product(product_id):
    product = Product.query.get_or_404(product_id)
    product.is_active = False
    db.session.commit()
    flash(f'"{product.title}" has been deactivated.', 'info')
    return redirect(url_for('admin_products'))

@app.route('/admin/orders')
@login_required
@admin_required
def admin_orders():
    status = request.args.get('status', '')
    query = Order.query
    if status:
        query = query.filter_by(status=status)
    orders = query.order_by(Order.order_date.desc()).all()
    cart_data = get_cart_items()
    return render_template('admin/orders.html', orders=orders, selected_status=status, cart_count=cart_data['item_count'])

@app.route('/admin/orders/<int:order_id>/status', methods=['POST'])
@login_required
@admin_required
def admin_update_order_status(order_id):
    order = Order.query.get_or_404(order_id)
    new_status = request.form.get('status')
    if new_status in ['Pending', 'Paid', 'Shipped', 'Delivered', 'Cancelled']:
        order.status = new_status
        db.session.commit()
        flash(f'Order #{order.id} status updated to {new_status}.', 'success')
    return redirect(url_for('admin_orders'))

@app.route('/admin/discounts')
@login_required
@admin_required
def admin_discounts():
    discounts = DiscountCode.query.order_by(DiscountCode.code).all()
    cart_data = get_cart_items()
    return render_template('admin/discounts.html', discounts=discounts, cart_count=cart_data['item_count'])

@app.route('/admin/discounts/add', methods=['POST'])
@login_required
@admin_required
def admin_add_discount():
    code = request.form.get('code', '').strip().upper()
    percent = float(request.form.get('discount_percent', 0))
    min_amount = float(request.form.get('min_order_amount', 0))
    max_uses = int(request.form.get('max_uses', 0))

    if DiscountCode.query.filter_by(code=code).first():
        flash('This code already exists.', 'danger')
    else:
        d = DiscountCode(code=code, discount_percent=percent, min_order_amount=min_amount, max_uses=max_uses)
        db.session.add(d)
        db.session.commit()
        flash(f'Discount code {code} created.', 'success')
    return redirect(url_for('admin_discounts'))

@app.route('/admin/discounts/toggle/<int:discount_id>')
@login_required
@admin_required
def admin_toggle_discount(discount_id):
    d = DiscountCode.query.get_or_404(discount_id)
    d.is_active = not d.is_active
    db.session.commit()
    flash(f'Code {d.code} is now {"active" if d.is_active else "inactive"}.', 'info')
    return redirect(url_for('admin_discounts'))

# ====================== DATABASE INIT ======================

with app.app_context():
    db.create_all()

    if Product.query.count() == 0:
        sample_books = [
            Product(title="The Great Gatsby", author="F. Scott Fitzgerald", isbn="9780743273565",
                    price=189.99, stock=25, category="Fiction",
                    description="A classic novel of the Jazz Age."),
            Product(title="1984", author="George Orwell", isbn="9780451524935",
                    price=159.50, stock=40, category="Dystopian",
                    description="A dystopian social science fiction novel."),
            Product(title="To Kill a Mockingbird", author="Harper Lee", isbn="9780061120084",
                    price=175.99, stock=30, category="Fiction",
                    description="A novel about racial injustice."),
            Product(title="Pride and Prejudice", author="Jane Austen", isbn="9780141439518",
                    price=149.99, stock=20, category="Romance",
                    description="A romantic novel of manners."),
            Product(title="The Hobbit", author="J.R.R. Tolkien", isbn="9780547928227",
                    price=219.99, stock=15, category="Fantasy",
                    description="A fantasy adventure novel."),
            Product(title="Atomic Habits", author="James Clear", isbn="9780735211292",
                    price=249.99, stock=35, category="Self-Help",
                    description="Tiny changes, remarkable results."),
            Product(title="Sapiens", author="Yuval Noah Harari", isbn="9780062316097",
                    price=279.99, stock=18, category="History",
                    description="A brief history of humankind."),
            Product(title="The Alchemist", author="Paulo Coelho", isbn="9780062315007",
                    price=169.99, stock=22, category="Fiction",
                    description="A philosophical story about following your dreams."),
        ]
        db.session.add_all(sample_books)

        db.session.add(DiscountCode(code="WELCOME10", discount_percent=10, min_order_amount=200, max_uses=0))
        db.session.add(DiscountCode(code="SAVE20", discount_percent=20, min_order_amount=400, max_uses=50))
        db.session.add(DiscountCode(code="BOOK5", discount_percent=5, min_order_amount=0, max_uses=0))

        admin = User(
            email="admin@daerbooks.com",
            password=generate_password_hash("admin123", method='pbkdf2:sha256'),
            first_name="Admin",
            last_name="User",
            is_admin=True
        )
        db.session.add(admin)

        customer = User(
            email="customer@example.com",
            password=generate_password_hash("customer123", method='pbkdf2:sha256'),
            first_name="Thabo",
            last_name="Molefe"
        )
        db.session.add(customer)

        db.session.commit()
        print("Sample data created successfully!")

if __name__ == '__main__':
    app.run(debug=True)