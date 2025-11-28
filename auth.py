import streamlit as st
import sqlite3
import bcrypt
import os

DB_NAME = "users.db"

def init_db():
    """Initialize the database with a users table."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash BLOB NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

def create_user(email, username, password):
    """Create a new user with a hashed password."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    
    try:
        c.execute('INSERT INTO users (email, username, password_hash) VALUES (?, ?, ?)', 
                  (email, username, hashed))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def check_user(username, password):
    """Check if the username and password match."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('SELECT password_hash FROM users WHERE username = ?', (username,))
    data = c.fetchone()
    conn.close()
    
    if data:
        stored_hash = data[0]
        if bcrypt.checkpw(password.encode('utf-8'), stored_hash):
            return True
    return False

def login_page():
    """Render the login/signup page."""
    st.title("Welcome to PVJ Research Extractor")
    
    tab1, tab2 = st.tabs(["Sign In", "Sign Up"])
    
    with tab1:
        st.subheader("Sign In")
        login_user = st.text_input("Username", key="login_user")
        login_pass = st.text_input("Password", type="password", key="login_pass")
        
        if st.button("Login"):
            if check_user(login_user, login_pass):
                st.session_state["authenticated"] = True
                st.session_state["username"] = login_user
                st.success(f"Welcome back, {login_user}!")
                st.rerun()
            else:
                st.error("Invalid username or password")

    with tab2:
        st.subheader("Sign Up")
        new_email = st.text_input("Email", key="new_email")
        new_user = st.text_input("Username", key="new_user")
        new_pass = st.text_input("Password", type="password", key="new_pass")
        
        if st.button("Create Account"):
            if new_email and new_user and new_pass:
                if create_user(new_email, new_user, new_pass):
                    st.success("Account created successfully! Please sign in.")
                else:
                    st.error("Username or Email already exists.")
            else:
                st.warning("Please fill in all fields.")
