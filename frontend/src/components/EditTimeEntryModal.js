import React, { useState } from "react";
import { useWorker } from "../contexts/WorkerContext";
import axios from "axios";

const EditTimeEntryModal = ({ timeEntry, workers, jobs, onClose, onUpdate }) => {
  const { API, formatDate, getCurrentUKTimeForInput } = useWorker();
  
  // Convert UTC times from backend to UK local time for datetime-local inputs
  const convertUTCToUKInput = (utcDateString) => {
    if (!utcDateString) return "";
    
    const utcDate = new Date(utcDateString);
    
    // Format as UK local time for datetime-local input
    return new Intl.DateTimeFormat('sv-SE', {
      timeZone: 'Europe/London',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    }).format(utcDate).replace(' ', 'T');
  };
  
  // Convert UK local time from input to UTC for backend
  const convertUKInputToUTC = (ukTimeString) => {
    if (!ukTimeString) return null;
    
    // Create a date object treating the input as UK local time
    const ukDate = new Date(ukTimeString);
    
    // Get the timezone offset for UK at this date
    const ukFormatter = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Europe/London',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    });
    
    const utcFormatter = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'UTC',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    });
    
    // Create a test date to find the offset
    const testDate = new Date(ukTimeString);
    const ukTime = ukFormatter.format(testDate);
    const utcTime = utcFormatter.format(testDate);
    
    // Calculate offset and adjust
    const ukTimestamp = new Date(ukTime).getTime();
    const utcTimestamp = new Date(utcTime).getTime();
    const offset = ukTimestamp - utcTimestamp;
    
    return new Date(testDate.getTime() - offset).toISOString();
  };

  const [formData, setFormData] = useState({
    worker_id: timeEntry.worker_id,
    job_id: timeEntry.job_id,
    clock_in: convertUTCToUKInput(timeEntry.clock_in),
    clock_out: convertUTCToUKInput(timeEntry.clock_out),
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
        const clockInUTC = convertUKInputToUTC(formData.clock_in);
        const clockOutUTC = convertUKInputToUTC(formData.clock_out);
        const clockIn = new Date(clockInUTC);
        const clockOut = new Date(clockOutUTC);
        duration_minutes = Math.floor((clockOut - clockIn) / 60000); // Convert to minutes
      }

      const updateData = {
        worker_id: formData.worker_id,
        job_id: formData.job_id,
        clock_in: convertUKInputToUTC(formData.clock_in),
        clock_out: formData.clock_out ? convertUKInputToUTC(formData.clock_out) : null,
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
            <p className="text-blue-800 text-sm mt-1">
              <strong>Times shown in UK local time (GMT/BST automatically handled)</strong>
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