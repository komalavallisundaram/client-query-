import streamlit as st
import psycopg2
import hashlib
import pandas as pd
from datetime import datetime
import csv
import os
from psycopg2.extras import execute_values

DB_CONFIG = {
    "host": "localhost",
    "dbname": "client_queries",
    "user": "postgres",
    "password": "Mahivalli@24"
}

def get_conn():
    return psycopg2.connect(**DB_CONFIG)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            hashed_password TEXT NOT NULL,
            role TEXT CHECK(role IN ('Client','Support')) NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS queries (
            query_id SERIAL PRIMARY KEY,
            mail_id TEXT NOT NULL,
            mobile_number TEXT NOT NULL,
            query_heading TEXT NOT NULL,
            query_description TEXT NOT NULL,
            status TEXT CHECK(status IN ('Open','Closed')) NOT NULL DEFAULT 'Open',
            query_created_time TIMESTAMP NOT NULL,
            query_closed_time TIMESTAMP,
            closed_by TEXT
        )
    """)
    conn.commit()
    conn.close()

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def authenticate_user(username, password):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT hashed_password, role FROM users WHERE username=%s", (username,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    stored_hash, role = row
    return role if stored_hash == hash_password(password) else None

def insert_query(mail_id, mobile_number, heading, description):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now()
    cur.execute("""
        INSERT INTO queries (mail_id, mobile_number, query_heading, query_description, status, query_created_time)
        VALUES (%s, %s, %s, %s, 'Open', %s)
        RETURNING query_id
    """, (mail_id, mobile_number, heading, description, now))
    qid = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return qid

def get_queries(status=None):
    conn = get_conn()
    q = "SELECT * FROM queries"
    params = []
    if status:
        q += " WHERE status=%s"
        params.append(status)
    df = pd.read_sql(q, conn, params=params)
    conn.close()
    return df

def close_query(qid, support_user):
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now()
    cur.execute("""
        UPDATE queries
        SET status='Closed', query_closed_time=%s, closed_by=%s
        WHERE query_id=%s AND status='Open'
    """, (now, support_user, qid))
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed

def read_csv(path):
    rows = []
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        expected = {'username','password','role'}
        if not expected.issubset(set(reader.fieldnames or [])):
            raise ValueError("CSV must contain username,password,role")
        for r in reader:
            username = (r.get('username') or '').strip()
            password = (r.get('password') or '')
            role = (r.get('role') or '').strip()
            if not username or not password or not role:
                continue
            rows.append((username, password, role))
    return rows

def backup_users(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users_backup (
            username TEXT,
            hashed_password TEXT,
            role TEXT
        )
    """)
    cur.execute("TRUNCATE users_backup")
    cur.execute("INSERT INTO users_backup SELECT username, hashed_password, role FROM users")
    conn.commit()
    cur.close()

def upsert_users(conn, rows):
    cur = conn.cursor()
    data = []
    for username, password, role in rows:
        hashed = hashlib.sha256(password.encode()).hexdigest()
        data.append((username, hashed, role))
    sql = """
        INSERT INTO users (username, hashed_password, role)
        VALUES %s
        ON CONFLICT (username) DO UPDATE
        SET hashed_password = EXCLUDED.hashed_password,
            role = EXCLUDED.role
    """
    execute_values(cur, sql, data, template=None, page_size=100)
    conn.commit()
    cur.close()

st.set_page_config(page_title="Client Query System", layout="wide")
st.sidebar.header("   CLIENT QUERY MANAGEMENT SYSTEM   ")
init_db()

csv_path = "C:\\Users\\shenbagam\\Downloads\\management.csv" 
try:
    if os.path.isfile(csv_path):
        rows = read_csv(csv_path)
        if rows:
            conn = get_conn()
            backup_users(conn)
            upsert_users(conn, rows)
            conn.close()
            st.success(f"Imported {len(rows)} users from {csv_path}")
        else:
            st.warning("No valid rows found in CSV.")
    else:
        st.error(f"CSV file not found: {csv_path}")
except Exception as e:
    st.error(f"ERROR during import: {e}")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.username = None
    st.session_state.role = None

st.sidebar.header("Login Page ")
u = st.sidebar.text_input("Username")
p = st.sidebar.text_input("Password", type="password")
if st.sidebar.button("Login"):
    role = authenticate_user(u, p)
    if role:
        st.session_state.authenticated = True
        st.session_state.username = u
        st.session_state.role = role
        st.sidebar.success(f"Logged in successfully as ({role})")
        st.rerun()
    else:
        st.sidebar.error("Invalid credentials")

if st.session_state.authenticated:
    role = st.session_state.role
    if role == "Client":
        st.header("CLIENT DASHBOARD")
        with st.form("client_form", clear_on_submit=True):
            mail = st.text_input("Email ID")
            mobile = st.text_input("Mobile Number")
            heading = st.text_input("Query Heading")
            desc = st.text_area("Query Description")
            submit = st.form_submit_button("Submit Query")
            if submit:
                if mail and mobile and heading and desc:
                    qid = insert_query(mail, mobile, heading, desc)
                    st.success(f"Query {qid} submitted successfully")
                else:
                    st.error("All fields required")
    elif role == "Support":
        st.header("SUPPORT DASHBOARD")
        if st.button("Refresh data"):
            st.rerun()
        status = st.selectbox("Filter by status", ["All", "Open", "Closed"])
        df_queries = get_queries(None if status == "All" else status)
        st.dataframe(df_queries, use_container_width=True)
        open_df = df_queries[df_queries["status"] == "Open"]
        if not open_df.empty:
            qid = st.selectbox("Select query to close", open_df["query_id"].tolist())
            if st.button("Close Query"):
                if close_query(int(qid), st.session_state.username):
                    st.success(f"Query {qid} closed by {st.session_state.username}")
                    st.rerun()