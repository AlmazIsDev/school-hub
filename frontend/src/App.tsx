import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { getTokens } from "./api";
import Layout from "./Layout";
import { useAuth } from "./auth";
import Login from "./pages/Login";
import Profile from "./pages/Profile";
import PollsPage from "./pages/PollsPage";
import PollResultsPage from "./pages/PollResultsPage";
import BridgePage from "./pages/BridgePage";
import DutyPage from "./pages/DutyPage";
import NavigatorPage from "./pages/NavigatorPage";
import BuilderPage from "./pages/BuilderPage";
import QuestPlayPage from "./pages/QuestPlayPage";
import AdminPage from "./pages/AdminPage";
import SchoolsPage from "./pages/SchoolsPage";
import MediaPage from "./pages/MediaPage";

function Guard({ children }: { children: React.ReactNode }) {
  const { user, mustChangePassword } = useAuth();
  const location = useLocation();
  if (!getTokens() || !user) return <Navigate to="/login" replace />;
  if (mustChangePassword && location.pathname !== "/profile") {
    return <Navigate to="/profile" replace />;
  }
  return <>{children}</>;
}

/** Роут «/» пока один - по мере появления модулей добавим редирект по роли. */
function Home() {
  return <Navigate to="/profile" replace />;
}

/** Страница только для указанных ролей: остальные даже не видят ошибку API. */
function RoleGuard({ roles, children }: { roles: string[]; children: React.ReactNode }) {
  const { user } = useAuth();
  if (!user || !roles.includes(user.role)) return <Navigate to="/profile" replace />;
  return <>{children}</>;
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
        <Route path="/bridge" element={<BridgePage />} />
        <Route path="/duty" element={<DutyPage />} />
        <Route path="/navigator" element={<NavigatorPage />} />
        <Route path="/builder" element={<BuilderPage />} />
        <Route path="/quests" element={<QuestPlayPage />} />
        <Route path="/admin" element={<RoleGuard roles={["admin", "superadmin"]}><AdminPage /></RoleGuard>} />
        <Route path="/schools" element={<RoleGuard roles={["superadmin"]}><SchoolsPage /></RoleGuard>} />
        <Route path="/media" element={<MediaPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
