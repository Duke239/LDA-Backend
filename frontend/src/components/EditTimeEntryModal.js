import React, { useState } from "react";
import { useWorker } from "../contexts/WorkerContext";
import axios from "axios";

const EditTimeEntryModal = ({ timeEntry, workers, jobs, onClose, onUpdate }) => {
  const { API, formatDate } = useWorker();
  const [formData, setFormData] = useState({
    worker_id: timeEntry.worker_id,
    job_id: timeEntry.job_id,
    clock_in: timeEntry.clock_in ? new Date(timeEntry.clock_in).toISOString().slice(0, 16) : "",
    clock_out: timeEntry.clock_out ? new Date(timeEntry.clock_out).toISOString().slice(0, 16) : "",
    notes: timeEntry.notes || ""
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Get auth headers for admin requests
  const getAuthHeaders = () => {
    const adminAuth = localStorage.getItem('adminAuth');
    return {
      'Authorization': `Basic ${adminAuth}`,
      'Content-Type': 'application/json'
    };
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    try {
      setLoading(true);
      setError("");
      
      // Calculate duration if both clock in and out are provided
      let duration_minutes = null;
      if (formData.clock_out && formData.clock_in) {
        const clockIn = new Date(formData.clock_in);
        const clockOut = new Date(formData.clock_out);
        duration_minutes = Math.floor((clockOut - clockIn) / 60000); // Convert to minutes
      }

      const updateData = {
        worker_id: formData.worker_id,
        job_id: formData.job_id,
        clock_in: new Date(formData.clock_in).toISOString(),
        clock_out: formData.clock_out ? new Date(formData.clock_out).toISOString() : null,
        duration_minutes: duration_minutes,
        notes: formData.notes
      };

      // For now, we'll update via a custom endpoint (you may need to add this to backend)
      // Using the existing time entry update logic
      await axios.put(`${API}/time-entries/${timeEntry.id}`, updateData, {
        headers: getAuthHeaders()
      });
      
      onUpdate();
    } catch (err) {
      setError(err.response?.data?.detail || "Error updating time entry");
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value
    }));
  };

  // Manual clock out for active entries
  const handleClockOut = async () => {
    try {
      setLoading(true);
      setError("");
      
      await axios.put(`${API}/time-entries/${timeEntry.id}/clock-out`, {
        notes: formData.notes
      }, {
        headers: getAuthHeaders()
      });
      
      onUpdate();
    } catch (err) {
      setError(err.response?.data?.detail || "Error clocking out");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full">
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="text-lg font-semibold text-gray-900">Edit Time Entry</h3>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md">
              {error}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Worker *
              </label>
              <select
                name="worker_id"
                value={formData.worker_id}
                onChange={handleChange}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                required
              >
                {workers.map((worker) => (
                  <option key={worker.id} value={worker.id}>
                    {worker.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Job *
              </label>
              <select
                name="job_id"
                value={formData.job_id}
                onChange={handleChange}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                required
              >
                {jobs.map((job) => (
                  <option key={job.id} value={job.id}>
                    {job.name}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Clock In *
              </label>
              <input
                type="datetime-local"
                name="clock_in"
                value={formData.clock_in}
                onChange={handleChange}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Clock Out
              </label>
              <input
                type="datetime-local"
                name="clock_out"
                value={formData.clock_out}
                onChange={handleChange}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Notes
            </label>
            <textarea
              name="notes"
              value={formData.notes}
              onChange={handleChange}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
              placeholder="Any notes about this time entry..."
            />
          </div>

          {/* Show current status if active */}
          {!timeEntry.clock_out && (
            <div className="bg-yellow-50 border border-yellow-200 p-4 rounded-md">
              <p className="text-yellow-800 font-medium">This is an active time entry (worker is still clocked in)</p>
              <button
                type="button"
                onClick={handleClockOut}
                disabled={loading}
                className="mt-2 px-4 py-2 bg-yellow-600 text-white rounded-md hover:bg-yellow-700 disabled:bg-gray-400"
              >
                Clock Out Now
              </button>
            </div>
          )}

          <div className="bg-blue-50 border border-blue-200 p-4 rounded-md">
            <h4 className="font-medium text-blue-900 mb-2">Admin Note</h4>
            <p className="text-blue-800 text-sm">
              You can edit time entries to correct mistakes or add missing clock-outs. 
              Changes will be reflected in all reports and cost calculations.
            </p>
          </div>

          <div className="flex space-x-3 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 py-2 px-4 border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 py-2 px-4 rounded-md text-white font-medium focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
              style={{ backgroundColor: loading ? '#9CA3AF' : '#d01f2f' }}
            >
              {loading ? (
                <div className="flex items-center justify-center">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                  Updating...
                </div>
              ) : (
                "Update Time Entry"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default EditTimeEntryModal;