import React, { useState } from 'react';
import { API_URL } from '../config';

const LoginPage = ({ onLogin }) => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      // Direct fetch to bypass the interceptor if it was strict, though it's fine
      const res = await fetch(`${API_URL}/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || 'Login failed');
      }

      // Save token and trigger login
      sessionStorage.setItem('jwt_token', data.token);
      sessionStorage.setItem('username', data.username);
      onLogin();
      
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <div style={styles.header}>
          <h1 style={styles.title}>Data Hygiene</h1>
          <p style={styles.subtitle}>Please log in to continue</p>
        </div>

        {error && (
          <div style={styles.errorBanner}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} style={styles.form}>
          <div style={styles.inputGroup}>
            <label style={styles.label}>Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              style={styles.input}
              placeholder="Enter your username"
              required
            />
          </div>

          <div style={styles.inputGroup}>
            <label style={styles.label}>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={styles.input}
              placeholder="••••••••"
              required
            />
          </div>

          <button 
            type="submit" 
            style={{...styles.button, opacity: loading ? 0.7 : 1}}
            disabled={loading}
          >
            {loading ? 'Authenticating...' : 'Sign In'}
          </button>
        </form>
        
        <div style={styles.footer}>
          <p style={styles.hint}>Testing credentials: <b>admin</b> / <b>password123</b></p>
        </div>
      </div>
    </div>
  );
};

const styles = {
  container: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    minHeight: '100vh',
    backgroundColor: '#0f172a',
    fontFamily: '"Inter", sans-serif',
  },
  card: {
    backgroundColor: '#1e293b',
    borderRadius: '12px',
    boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5), 0 10px 10px -5px rgba(0, 0, 0, 0.2)',
    width: '100%',
    maxWidth: '400px',
    padding: '40px',
    border: '1px solid #334155'
  },
  header: {
    textAlign: 'center',
    marginBottom: '32px'
  },
  title: {
    margin: 0,
    color: '#f8fafc',
    fontSize: '28px',
    fontWeight: '700',
    letterSpacing: '-0.5px'
  },
  subtitle: {
    margin: '8px 0 0',
    color: '#94a3b8',
    fontSize: '14px'
  },
  errorBanner: {
    backgroundColor: '#7f1d1d',
    color: '#fca5a5',
    padding: '12px',
    borderRadius: '6px',
    marginBottom: '20px',
    fontSize: '14px',
    textAlign: 'center',
    border: '1px solid #991b1b'
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: '20px'
  },
  inputGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px'
  },
  label: {
    color: '#cbd5e1',
    fontSize: '14px',
    fontWeight: '500'
  },
  input: {
    padding: '12px 16px',
    borderRadius: '6px',
    border: '1px solid #475569',
    backgroundColor: '#0f172a',
    color: '#f8fafc',
    fontSize: '15px',
    outline: 'none',
    transition: 'border-color 0.2s'
  },
  button: {
    backgroundColor: '#3b82f6',
    color: 'white',
    border: 'none',
    padding: '12px',
    borderRadius: '6px',
    fontSize: '16px',
    fontWeight: '600',
    cursor: 'pointer',
    marginTop: '8px',
    transition: 'background-color 0.2s',
    boxShadow: '0 4px 6px -1px rgba(59, 130, 246, 0.3)'
  },
  footer: {
    marginTop: '24px',
    textAlign: 'center',
    borderTop: '1px solid #334155',
    paddingTop: '16px'
  },
  hint: {
    color: '#64748b',
    fontSize: '13px',
    margin: 0
  }
};

export default LoginPage;
