import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { Layout } from './pages/Layout';
import { Login } from './pages/Login';
import { Gallery } from './pages/Gallery';
import { RhinoImageDetail } from './pages/RhinoImageDetail';

function Protected({ children }: { children: React.ReactNode }) {
  const { token, loading } = useAuth();
  if (loading) return <div className="loading">Loading...</div>;
  if (!token) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AdminOnly({ children }: { children: React.ReactNode }) {
  const { role, loading } = useAuth();
  if (loading) return <div className="loading">Loading...</div>;
  if (role !== 'admin') return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<Protected><Layout /></Protected>}>
            <Route index element={<Gallery />} />
            <Route
              path="lists"
              element={
                <AdminOnly>
                  <Gallery />
                </AdminOnly>
              }
            />
            <Route
              path="rhino-list"
              element={
                <AdminOnly>
                  <Gallery />
                </AdminOnly>
              }
            />
            <Route
              path=":identityId/img/:imageId"
              element={
                <AdminOnly>
                  <RhinoImageDetail />
                </AdminOnly>
              }
            />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
