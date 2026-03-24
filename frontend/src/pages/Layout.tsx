import { Outlet, Link, useLocation } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export function Layout() {
  const { username, role, logout } = useAuth();
  const loc = useLocation();

  const nav = [{ path: '/', label: 'Predict' }, ...(role === 'admin' ? [{ path: '/rhino-list', label: 'Rhino list' }] : [])];

  return (
    <div className="app-layout">
      <header className="header">
        <Link to="/" className="logo">Rhino ReID</Link>
        <nav>
          {nav.map((n) => (
            <Link
              key={n.path}
              to={n.path}
              className={(n.path === '/rhino-list' ? (loc.pathname === '/rhino-list' || loc.pathname === '/lists') : loc.pathname === n.path) ? 'active' : ''}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="user">
          <span>{username}</span>
          <button type="button" onClick={logout}>Sign out</button>
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
