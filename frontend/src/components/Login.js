import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useWorker } from "../contexts/WorkerContext";

const Login = () => {
  const [selectedWorker, setSelectedWorker] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [adminCredentials, setAdminCredentials] = useState({
    username: "",
    password: ""
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const { workers, fetchWorkers, API } = useWorker();
  const navigate = useNavigate();

  useEffect(() => {
    fetchWorkers();
  }, []);

  const handleAdminLogin = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
      const response = await fetch(`${API}/admin/login`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(adminCredentials),
      });

      if (response.ok) {
        // Store admin credentials for subsequent requests
        const encodedCredentials = btoa(`${adminCredentials.username}:${adminCredentials.password}`);
        localStorage.setItem('adminAuth', encodedCredentials);
        navigate("/admin");
      } else {
        const errorData = await response.json();
        setError(errorData.detail || "Invalid admin credentials");
      }
    } catch (err) {
      setError("Error connecting to server");
    } finally {
      setLoading(false);
    }
  };

  const handleWorkerLogin = () => {
    if (selectedWorker) {
      navigate(`/worker/${selectedWorker}`);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="max-w-md w-full space-y-8">
        <div className="text-center">
          <h1 className="text-4xl font-bold text-gray-900 mb-2">LDA Group</h1>
          <h2 className="text-xl font-semibold text-gray-600">Time Tracking</h2>
          <p className="text-gray-500 mt-2">Select your profile to continue</p>
        </div>

        <div className="bg-white p-8 rounded-lg shadow-md">
          {error && (
            <div className="mb-4 bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md">
              {error}
            </div>
          )}

          <div className="space-y-4">
            <div>
              <label className="flex items-center space-x-3">
                <input
                  type="radio"
                  name="userType"
                  value="worker"
                  checked={!isAdmin}
                  onChange={() => {
                    setIsAdmin(false);
                    setError("");
                  }}
                  className="text-red-600 focus:ring-red-500"
                />
                <span className="text-gray-700">Worker</span>
              </label>
            </div>

            <div>
              <label className="flex items-center space-x-3">
                <input
                  type="radio"
                  name="userType"
                  value="admin"
                  checked={isAdmin}
                  onChange={() => {
                    setIsAdmin(true);
                    setError("");
                  }}
                  className="text-red-600 focus:ring-red-500"
                />
                <span className="text-gray-700">Admin</span>
              </label>
            </div>

            {!isAdmin ? (
              // Worker Login
              <div className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Select Worker
                  </label>
                  <select
                    value={selectedWorker}
                    onChange={(e) => setSelectedWorker(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                  >
                    <option value="">Choose your name...</option>
                    {workers.map((worker) => (
                      <option key={worker.id} value={worker.id}>
                        {worker.name}
                      </option>
                    ))}
                  </select>
                </div>

                <button
                  onClick={handleWorkerLogin}
                  disabled={!selectedWorker}
                  className="w-full bg-red-600 text-white py-2 px-4 rounded-md hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                  style={{ backgroundColor: selectedWorker ? '#D11F2F' : '#9CA3AF' }}
                >
                  Start Working
                </button>
              </div>
            ) : (
              // Admin Login
              <form onSubmit={handleAdminLogin} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Admin Username
                  </label>
                  <input
                    type="text"
                    value={adminCredentials.username}
                    onChange={(e) => setAdminCredentials({
                      ...adminCredentials,
                      username: e.target.value
                    })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                    placeholder="Enter admin username"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Admin Password
                  </label>
                  <input
                    type="password"
                    value={adminCredentials.password}
                    onChange={(e) => setAdminCredentials({
                      ...adminCredentials,
                      password: e.target.value
                    })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                    placeholder="Enter admin password"
                    required
                  />
                </div>

                <button
                  type="submit"
                  disabled={loading || !adminCredentials.username || !adminCredentials.password}
                  className="w-full bg-red-600 text-white py-2 px-4 rounded-md hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                  style={{ backgroundColor: (loading || !adminCredentials.username || !adminCredentials.password) ? '#9CA3AF' : '#D11F2F' }}
                >
                  {loading ? (
                    <div className="flex items-center justify-center">
                      <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                      Logging in...
                    </div>
                  ) : (
                    'Access Admin Dashboard'
                  )}
                </button>
              </form>
            )}
          </div>
        </div>

        <div className="text-center text-sm text-gray-500">
          <p>Need help? Contact your supervisor.</p>
          {isAdmin && (
            <p className="mt-2 text-xs">
              <strong>Default admin credentials:</strong><br />
              Username: admin<br />
              Password: ldagroup2024
            </p>
          )}
        </div>
      </div>
    </div>
  );
};

export default Login;