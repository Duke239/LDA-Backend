import React from "react";
import "./App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { WorkerProvider } from "./contexts/WorkerContext";
import WorkerDashboard from "./components/WorkerDashboard";
import AdminDashboard from "./components/AdminDashboard";
import Login from "./components/Login";

function App() {
  return (
    <WorkerProvider>
      <div className="App">
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Login />} />
            <Route path="/worker/:workerId" element={<WorkerDashboard />} />
            <Route path="/admin" element={<AdminDashboard />} />
          </Routes>
        </BrowserRouter>
      </div>
    </WorkerProvider>
  );
}

export default App;