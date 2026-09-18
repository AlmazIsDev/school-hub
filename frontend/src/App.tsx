import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { getTokens } from "./api";
import Layout from "./Layout";
import { useAuth } from "./auth";
import Login from "./pages/Login";
import Profile from "./pages/Profile";
import PollsPage from "./pages/PollsPage";
import PollResultsPage from "./pages/PollResultsPage";

function Guard({ children }: { children: React.ReactNode }) {
  const { user, mustChangePassword } = useAuth();
  const location = useLocation();
  if (!getTokens() || !user) return <Navigate to="/login" replace />;
  if (mustChangePassword && location.pathname !== "/profile") {
    return <Navigate to="/profile" replace />;
  }
  return <>{children}</>;
}

/** Роут «/» пока один — по мере появления модулей добавим редирект по роли. */
function Home() {
  return <Navigate to="/profile" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Guard><Layout /></Guard>}>
        <Route path="/" element={<Home />} />
        <Route path="/profile" element={<Profile />} />
        <Route path="/polls" element={<PollsPage />} />
        <Route path="/polls/:id/results" element={<PollResultsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
