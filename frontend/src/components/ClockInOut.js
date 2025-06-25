import React, { useState } from "react";
import { useWorker } from "../contexts/WorkerContext";

const ClockInOut = () => {
  const { 
    jobs, 
    currentWorker, 
    activeTimeEntry, 
    loading, 
    clockIn, 
    clockOut 
  } = useWorker();

  const [selectedJob, setSelectedJob] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");

  const handleClockIn = async () => {
    if (!selectedJob) {
      setError("Please select a job");
      return;
    }

    try {
      setError("");
      await clockIn(currentWorker.id, selectedJob, notes);
      setNotes("");
      setSelectedJob("");
    } catch (err) {
      setError(err.response?.data?.detail || "Error clocking in");
    }
  };

  const handleClockOut = async () => {
    try {
      setError("");
      await clockOut(activeTimeEntry.id, notes);
      setNotes("");
    } catch (err) {
      setError(err.response?.data?.detail || "Error clocking out");
    }
  };

  const activeJobs = jobs.filter(job => job.status === "active");

  return (
    <div className="space-y-4">
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md">
          {error}
        </div>
      )}

      {!activeTimeEntry ? (
        // Clock In Form
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Select Job
            </label>
            <select
              value={selectedJob}
              onChange={(e) => setSelectedJob(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
            >
              <option value="">Choose a job...</option>
              {activeJobs.map((job) => (
                <option key={job.id} value={job.id}>
                  {job.name} - {job.client}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Notes (Optional)
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
              placeholder="Any notes about starting work..."
            />
          </div>

          <button
            onClick={handleClockIn}
            disabled={loading || !selectedJob}
            className="w-full py-3 px-4 rounded-md text-white font-medium focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
            style={{ backgroundColor: loading || !selectedJob ? '#9CA3AF' : '#D11F2F' }}
          >
            {loading ? (
              <div className="flex items-center justify-center">
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                Clocking In...
              </div>
            ) : (
              "Clock In"
            )}
          </button>
        </div>
      ) : (
        // Clock Out Form
        <div className="space-y-4">
          <div className="bg-green-50 border border-green-200 p-4 rounded-md">
            <p className="text-green-800 font-medium">Currently Clocked In</p>
            <p className="text-green-600 text-sm mt-1">
              Started: {new Date(activeTimeEntry.clock_in).toLocaleString()}
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Work Completed Notes
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
              placeholder="Describe the work completed..."
            />
          </div>

          <button
            onClick={handleClockOut}
            disabled={loading}
            className="w-full py-3 px-4 rounded-md text-white font-medium focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
            style={{ backgroundColor: loading ? '#9CA3AF' : '#D11F2F' }}
          >
            {loading ? (
              <div className="flex items-center justify-center">
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                Clocking Out...
              </div>
            ) : (
              "Clock Out"
            )}
          </button>
        </div>
      )}
    </div>
  );
};

export default ClockInOut;