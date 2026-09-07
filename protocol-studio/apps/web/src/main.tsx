/** Entry point: routes. Browser history routing; the API serves index.html for unknown paths. */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { RequireAdmin, RequireAuth, SessionProvider } from "./lib/session";
import { Admin } from "./pages/Admin";
import { Editor } from "./pages/Editor";
import { Library } from "./pages/Library";
import { Login } from "./pages/Login";
import { NewWork } from "./pages/NewWork";
import "./styles.css";

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/library"
        element={
          <RequireAuth>
            <Library />
          </RequireAuth>
        }
      />
      <Route
        path="/new"
        element={
          <RequireAuth>
            <NewWork />
          </RequireAuth>
        }
      />
      <Route
        path="/editor/:workId/:sectionId?"
        element={
          <RequireAuth>
            <Editor />
          </RequireAuth>
        }
      />
      <Route
        path="/admin/:tab?"
        element={
          <RequireAuth>
            <RequireAdmin>
              <Admin />
            </RequireAdmin>
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/library" replace />} />
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SessionProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </SessionProvider>
  </StrictMode>,
);
