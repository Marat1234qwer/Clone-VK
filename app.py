import os
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_socketio import SocketIO, emit
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'fallback_secret_key')

# Конфигурация БД из переменных окружения
DB_CONFIG = {
    "host": os.getenv('DB_HOST'),
    "database": os.getenv('DB_NAME'),
    "user": os.getenv('DB_USER'),
    "password": os.getenv('DB_PASSWORD'),
    "port": os.getenv('DB_PORT'),
    "sslmode": os.getenv('DB_SSLMODE')
}

socketio = SocketIO(app)

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def create_tables():
    """Создание таблиц, если они не существуют"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id SERIAL PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                content TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER REFERENCES users(id)
            );
        """)
        
        conn.commit()
    except Exception as e:
        print(f"Ошибка при создании таблиц: {e}")
    finally:
        if conn:
            conn.close()

create_tables()

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
        
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            password_hash = generate_password_hash(password)
            query = """
                INSERT INTO users (username, email, password_hash) 
                VALUES (%s, %s, %s)
                RETURNING id
            """
            cursor.execute(query, (username, email, password_hash))
            
            user_id = cursor.fetchone()[0]
            conn.commit()
            
            session['user_id'] = user_id
            session['username'] = username
            flash('Регистрация успешна!', 'success')
            return redirect(url_for('feed_ws'))
            
        except Exception as e:
            if conn:
                conn.rollback()
            flash(f'Ошибка регистрации: {str(e)}', 'error')
            return redirect(url_for('register'))
        finally:
            if conn:
                conn.close()
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, username, password_hash FROM users 
                WHERE username = %s
            """, (username,))
            user = cursor.fetchone()
            
            if user and check_password_hash(user[2], password):
                session['user_id'] = user[0]
                session['username'] = user[1]
                flash('Вход выполнен успешно', 'success')
                return redirect(url_for('feed_ws'))
            
            flash('Неверное имя пользователя или пароль', 'error')
            
        except Exception as e:
            flash('Ошибка входа', 'error')
        finally:
            if conn:
                conn.close()

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))

@app.route('/feed_ws')
def feed_ws():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT p.id, p.title, p.content, p.timestamp, u.username 
            FROM posts p
            JOIN users u ON p.user_id = u.id
            ORDER BY p.timestamp DESC
            LIMIT 20
        """)
        posts = cursor.fetchall()
        
        return render_template('feed_ws.html', 
                            username=session['username'],
                            posts=posts)
    except Exception as e:
        flash('Ошибка загрузки ленты', 'error')
        return render_template('feed_ws.html', 
                            username=session['username'],
                            posts=[])
    finally:
        if conn:
            conn.close()

@app.route('/create_post', methods=['POST'])
def create_post():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    title = request.form.get('title')
    content = request.form.get('content')
    user_id = session['user_id']
    
    if not title or not content:
        flash('Заголовок и содержание обязательны', 'error')
        return redirect(url_for('feed_ws'))
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO posts (title, content, user_id)
            VALUES (%s, %s, %s)
            RETURNING id, timestamp
        """, (title, content, user_id))
        
        post_id, timestamp = cursor.fetchone()
        conn.commit()
        
        socketio.emit('new_post', {
            'id': post_id,
            'title': title,
            'content': content,
            'timestamp': timestamp.isoformat(),
            'username': session['username']
        }, broadcast=True)
        
        flash('Пост успешно создан', 'success')
    except Exception as e:
        if conn:
            conn.rollback()
        flash('Ошибка создания поста', 'error')
    finally:
        if conn:
            conn.close()
    
    return redirect(url_for('feed_ws'))

@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        emit('status', {'msg': f'Connected as {session["username"]}'})

@socketio.on('request_feed')
def handle_request_feed():
    if 'user_id' not in session:
        return
    
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT p.id, p.title, p.content, p.timestamp, u.username 
            FROM posts p
            JOIN users u ON p.user_id = u.id
            ORDER BY p.timestamp DESC
            LIMIT 20
        """)
        posts = []
        for post in cursor.fetchall():
            posts.append({
                'id': post[0],
                'title': post[1],
                'content': post[2],
                'timestamp': post[3].isoformat(),
                'username': post[4]
            })
        
        emit('feed_update', {'posts': posts})
    except Exception as e:
        pass
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    socketio.run(app, debug=True)