import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useWorker } from "../contexts/WorkerContext";

const Login = () => {
  const [selectedWorker, setSelectedWorker] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const { workers, fetchWorkers } = useWorker();
  const navigate = useNavigate();

  useEffect(() => {
    fetchWorkers();
  }, []);

  const handleLogin = () => {
    if (isAdmin) {
      navigate("/admin");
    } else if (selectedWorker) {
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
          <div className="space-y-4">
            <div>
              <label className="flex items-center space-x-3">
                <input
                  type="radio"
                  name="userType"
                  value="worker"
                  checked={!isAdmin}
                  onChange={() => setIsAdmin(false)}
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
                  onChange={() => setIsAdmin(true)}
                  className="text-red-600 focus:ring-red-500"
                />
                <span className="text-gray-700">Admin</span>
              </label>
            </div>

            {!isAdmin && (
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
            )}

            <button
              onClick={handleLogin}
              disabled={!isAdmin && !selectedWorker}
              className="w-full bg-red-600 text-white py-2 px-4 rounded-md hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
              style={{ backgroundColor: isAdmin || selectedWorker ? '#D11F2F' : '#9CA3AF' }}
            >
              {isAdmin ? 'Access Admin Dashboard' : 'Start Working'}
            </button>
          </div>
        </div>

        <div className="text-center text-sm text-gray-500">
          <p>Need help? Contact your supervisor.</p>
        </div>
      </div>
    </div>
  );
};

export default Login;