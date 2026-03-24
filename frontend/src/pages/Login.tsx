import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { auth } from '../api';
import { useAuth } from '../contexts/AuthContext';

export function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [registerMode, setRegisterMode] = useState(false);
  const [error, setError] = useState('');
  const { login } = useAuth();
  const navigate = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      const res = registerMode
        ? await auth.register(username, password)
        : await auth.login(username, password);
      login(res.data.access_token);
      navigate('/');
    } catch (err: unknown) {
      setError((err as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Login failed');
    }
  };

  return (
    <div className="page login-page">
      <div className="login-card">
        <h1>Rhino ReID</h1>
        <p className="subtitle">Sign in to continue</p>
        <form onSubmit={submit}>
          <input
            type="text"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          {error && <p className="error">{error}</p>}
          <button type="submit">{registerMode ? 'Register' : 'Sign in'}</button>
        </form>
        <button type="button" className="link" onClick={() => setRegisterMode(!registerMode)}>
          {registerMode ? 'Already have an account? Sign in' : "Don't have an account? Register"}
        </button>
      </div>
    </div>
  );
}
