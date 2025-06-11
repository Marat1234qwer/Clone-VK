from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_socketio import SocketIO, emit
from models import db, User, Post
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

socketio = SocketIO(app)

db.init_app(app)

with app.app_context():
    db.create_all()


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('feed_ws'))
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        if not all([username, email, password]):
            flash('All fields are required')
            return redirect(url_for('register'))

        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Email already registered')
            return redirect(url_for('register'))

        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.commit()

        flash('Registration successful. Please login.')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('Login successful')
            return redirect(url_for('feed_ws'))
        else:
            flash('Invalid username or password')

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash('You have been logged out')
    return redirect(url_for('index'))


@app.route('/feed_ws')
def feed_ws():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    posts = Post.query.order_by(Post.timestamp.desc()).all()
    return render_template('feed_ws.html', posts=posts)


@app.route('/create_post', methods=['POST'])
def create_post():
    if 'user_id' not in session:
        return {'error': 'Not authorized'}, 401

    content = request.form.get('content', '').strip()
    if not content:
        return {'error': 'Post content cannot be empty'}, 400

    try:
        new_post = Post(
            content=content,
            user_id=session['user_id'],
            timestamp=datetime.now(timezone.utc)
        )
        db.session.add(new_post)
        db.session.commit()

        post_data = {
            'id': new_post.id,
            'content': new_post.content,
            'username': session['username'],
            'timestamp': new_post.timestamp.strftime('%Y-%m-%d %H:%M')
        }

        socketio.emit('new_post', post_data)

        return {'success': True, 'post': post_data}

    except Exception as e:
        return {'error': str(e)}, 500


@app.route('/profile/<username>')
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    posts = Post.query.filter_by(user_id=user.id).order_by(Post.timestamp.desc()).all()
    return render_template('profile.html', user=user, posts=posts)


@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        emit('connection_response', {'status': 'connected'})


if __name__ == '__main__':
    socketio.run(app, debug=True)
