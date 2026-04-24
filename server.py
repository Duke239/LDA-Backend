import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useWorker } from "../contexts/WorkerContext";

const dayLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const toISODate = (date) => {
  const copy = new Date(date);
  copy.setMinutes(copy.getMinutes() - copy.getTimezoneOffset());
  return copy.toISOString().slice(0, 10);
};

const getMonday = (date = new Date()) => {
  const copy = new Date(date);
  const day = copy.getDay();
  const diff = copy.getDate() - day + (day === 0 ? -6 : 1);
  copy.setDate(diff);
  copy.setHours(0, 0, 0, 0);
  return copy;
};

const addDays = (date, days) => {
  const copy = new Date(date);
  copy.setDate(copy.getDate() + days);
  return copy;
};

const formatDisplayDate = (isoDate) => {
  const date = new Date(`${isoDate}T00:00:00`);
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
};

const SchedulePage = () => {
  const { API } = useWorker();

  const [weekStart, setWeekStart] = useState(getMonday());
  const [workers, setWorkers] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [schedule, setSchedule] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedCell, setSelectedCell] = useState(null);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [selectedExportWorkers, setSelectedExportWorkers] = useState([]);
  const [exportSelectionInitialised, setExportSelectionInitialised] = useState(false);
  const [exporting, setExporting] = useState("");

  const authHeaders = () => {
    const adminAuth = localStorage.getItem("adminAuth");
    return {
      Authorization: `Basic ${adminAuth}`,
      "Content-Type": "application/json",
    };
  };

  const weekDays = useMemo(() => {
    return Array.from({ length: 7 }, (_, index) => {
      const date = addDays(weekStart, index);
      return {
        label: dayLabels[index],
        iso: toISODate(date),
        display: formatDisplayDate(toISODate(date)),
      };
    });
  }, [weekStart]);

  const activeJobs = useMemo(() => {
    return jobs
      .filter((job) => job.status === "active" && !job.archived)
      .sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  }, [jobs]);

  const visibleWorkers = useMemo(() => {
    return workers
      .filter((worker) => worker.active !== false && !worker.archived && worker.role !== "admin")
      .sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  }, [workers]);

  useEffect(() => {
    if (visibleWorkers.length > 0 && !exportSelectionInitialised) {
      setSelectedExportWorkers(visibleWorkers.map((worker) => worker.id));
      setExportSelectionInitialised(true);
    }
  }, [visibleWorkers, exportSelectionInitialised]);

  const toggleExportWorker = (workerId) => {
    setSelectedExportWorkers((current) => {
      if (current.includes(workerId)) {
        return current.filter((id) => id !== workerId);
      }
      return [...current, workerId];
    });
  };

  const selectAllExportWorkers = () => {
    setExportSelectionInitialised(true);
    setSelectedExportWorkers(visibleWorkers.map((worker) => worker.id));
  };

  const clearExportWorkers = () => {
    setExportSelectionInitialised(true);
    setSelectedExportWorkers([]);
  };

  const downloadSchedule = async (format) => {
    if (selectedExportWorkers.length === 0) {
      setError("Select at least one worker to export.");
      return;
    }

    setExporting(format);
    setError("");

    try {
      const startDate = weekDays[0].iso;
      const endDate = weekDays[6].iso;
      const workerIds = encodeURIComponent(selectedExportWorkers.join(","));
      const response = await axios.get(
        `${API}/schedule/export?start_date=${startDate}&end_date=${endDate}&worker_ids=${workerIds}&format=${format}`,
        {
          headers: authHeaders(),
          responseType: "blob",
        }
      );

      const blob = new Blob([response.data], {
        type: format === "pdf" ? "application/pdf" : "text/csv;charset=utf-8;",
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `worker_schedule_${startDate}_to_${endDate}.${format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error("Error exporting schedule:", err);
      setError(err.response?.data?.detail || "Could not export schedule.");
    } finally {
      setExporting("");
    }
  };

  const loadBaseData = async () => {
    try {
      const [workersRes, jobsRes] = await Promise.all([
        axios.get(`${API}/workers?active_only=false&include_archived=false`),
        axios.get(`${API}/jobs?active_only=true&include_archived=false`),
      ]);
      setWorkers(workersRes.data || []);
      setJobs(jobsRes.data || []);
    } catch (err) {
      console.error("Error loading schedule base data:", err);
      setError("Could not load workers or jobs.");
    }
  };

  const loadSchedule = async () => {
    setLoading(true);
    setError("");
    try {
      const startDate = weekDays[0].iso;
      const endDate = weekDays[6].iso;

      const response = await axios.get(
        `${API}/schedule?start_date=${startDate}&end_date=${endDate}`,
        { headers: authHeaders() }
      );

      setSchedule(response.data || []);
    } catch (err) {
      console.error("Error loading schedule:", err);
      setSchedule([]);
      setError(err.response?.data?.detail || "Could not load schedule.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadBaseData();
  }, []);

  useEffect(() => {
    loadSchedule();
  }, [weekStart]);

  const getEntryForCell = (workerId, scheduledDate) => {
    return schedule.find(
      (entry) => entry.worker_id === workerId && entry.scheduled_date === scheduledDate
    );
  };

  const openCell = (worker, day, existingEntry = null) => {
    setSelectedCell({ worker, day, entry: existingEntry });
    setSelectedJobId(existingEntry?.job_id || "");
    setNotes(existingEntry?.notes || "");
    setError("");
  };

  const closeModal = () => {
    setSelectedCell(null);
    setSelectedJobId("");
    setNotes("");
    setSaving(false);
    setError("");
  };

  const saveAllocation = async () => {
    if (!selectedCell || !selectedJobId) {
      setError("Select an active job first.");
      return;
    }

    setSaving(true);
    setError("");

    const payload = {
      worker_id: selectedCell.worker.id,
      job_id: selectedJobId,
      scheduled_date: selectedCell.day.iso,
      notes,
      status: "scheduled",
    };

    try {
      if (selectedCell.entry) {
        await axios.put(`${API}/schedule/${selectedCell.entry.id}`, payload, {
          headers: authHeaders(),
        });
      } else {
        await axios.post(`${API}/schedule`, payload, {
          headers: authHeaders(),
        });
      }

      await loadSchedule();
      closeModal();
    } catch (err) {
      console.error("Error saving schedule allocation:", err);
      setError(err.response?.data?.detail || "Could not save allocation.");
    } finally {
      setSaving(false);
    }
  };

  const deleteAllocation = async () => {
    if (!selectedCell?.entry) return;
    if (!window.confirm("Remove this scheduled job?")) return;

    setSaving(true);
    setError("");

    try {
      await axios.delete(`${API}/schedule/${selectedCell.entry.id}`, {
        headers: authHeaders(),
      });
      await loadSchedule();
      closeModal();
    } catch (err) {
      console.error("Error deleting schedule allocation:", err);
      setError(err.response?.data?.detail || "Could not delete allocation.");
    } finally {
      setSaving(false);
    }
  };

  const goPreviousWeek = () => setWeekStart((current) => addDays(current, -7));
  const goNextWeek = () => setWeekStart((current) => addDays(current, 7));
  const goThisWeek = () => setWeekStart(getMonday());

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-lg shadow-sm p-6">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">Worker Schedule</h2>
            <p className="text-sm text-gray-500 mt-1">
              Allocate active jobs to workers by week.
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              onClick={goPreviousWeek}
              className="px-4 py-2 rounded-md border border-gray-300 bg-white text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Previous Week
            </button>
            <button
              onClick={goThisWeek}
              className="px-4 py-2 rounded-md border border-gray-300 bg-white text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              This Week
            </button>
            <button
              onClick={goNextWeek}
              className="px-4 py-2 rounded-md text-white text-sm font-medium hover:opacity-90"
              style={{ backgroundColor: "#d01f2f" }}
            >
              Next Week
            </button>
          </div>
        </div>

        <div className="mt-4 text-sm font-medium text-gray-700">
          Week commencing: {formatDisplayDate(weekDays[0].iso)} {new Date(`${weekDays[0].iso}T00:00:00`).getFullYear()}
        </div>

        {error && (
          <div className="mt-4 rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700">
            {error}
          </div>
        )}
      </div>

      <div className="bg-white rounded-lg shadow-sm p-6">
        <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Export Schedule</h3>
            <p className="text-sm text-gray-500 mt-1">
              Select workers and export this week as CSV or PDF.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => downloadSchedule("csv")}
              disabled={!!exporting}
              className="px-4 py-2 rounded-md border border-gray-300 bg-white text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              {exporting === "csv" ? "Exporting..." : "Export CSV"}
            </button>
            <button
              onClick={() => downloadSchedule("pdf")}
              disabled={!!exporting}
              className="px-4 py-2 rounded-md text-white text-sm font-medium hover:opacity-90 disabled:opacity-50"
              style={{ backgroundColor: "#d01f2f" }}
            >
              {exporting === "pdf" ? "Exporting..." : "Export PDF"}
            </button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            onClick={selectAllExportWorkers}
            className="text-xs px-3 py-1 rounded-full bg-gray-100 text-gray-700 hover:bg-gray-200"
          >
            Select all
          </button>
          <button
            onClick={clearExportWorkers}
            className="text-xs px-3 py-1 rounded-full bg-gray-100 text-gray-700 hover:bg-gray-200"
          >
            Clear
          </button>
        </div>

        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
          {visibleWorkers.map((worker) => (
            <label
              key={worker.id}
              className={`flex items-center gap-2 rounded-md border px-3 py-2 text-sm cursor-pointer ${
                selectedExportWorkers.includes(worker.id)
                  ? "border-red-300 bg-red-50 text-gray-900"
                  : "border-gray-200 bg-white text-gray-700"
              }`}
            >
              <input
                type="checkbox"
                checked={selectedExportWorkers.includes(worker.id)}
                onChange={() => toggleExportWorker(worker.id)}
                className="h-4 w-4 text-red-600 focus:ring-red-500 border-gray-300 rounded"
              />
              <span>{worker.name}</span>
            </label>
          ))}
        </div>
      </div>

      <div className="bg-white shadow-sm rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse">
            <thead className="bg-gray-50">
              <tr>
                <th className="sticky left-0 bg-gray-50 z-10 px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider border-r border-gray-200 min-w-[180px]">
                  Worker
                </th>
                {weekDays.map((day) => (
                  <th
                    key={day.iso}
                    className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider border-r border-gray-200 min-w-[145px]"
                  >
                    <div>{day.label}</div>
                    <div className="font-normal normal-case text-gray-400">{day.display}</div>
                  </th>
                ))}
              </tr>
            </thead>

            <tbody className="bg-white divide-y divide-gray-200">
              {loading ? (
                <tr>
                  <td colSpan={8} className="px-6 py-10 text-center text-gray-500">
                    Loading schedule...
                  </td>
                </tr>
              ) : visibleWorkers.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-6 py-10 text-center text-gray-500">
                    No active workers found.
                  </td>
                </tr>
              ) : (
                visibleWorkers.map((worker) => (
                  <tr key={worker.id}>
                    <td className="sticky left-0 bg-white z-10 px-4 py-4 border-r border-gray-200">
                      <div className="text-sm font-semibold text-gray-900">{worker.name}</div>
                      <div className="text-xs text-gray-500">{worker.role || "worker"}</div>
                    </td>

                    {weekDays.map((day) => {
                      const entry = getEntryForCell(worker.id, day.iso);
                      return (
                        <td key={`${worker.id}-${day.iso}`} className="p-2 border-r border-gray-100 align-top">
                          <button
                            onClick={() => openCell(worker, day, entry)}
                            className={`w-full min-h-[76px] rounded-lg border px-3 py-2 text-left transition ${
                              entry
                                ? "bg-red-50 border-red-200 hover:bg-red-100"
                                : "bg-gray-50 border-dashed border-gray-300 hover:bg-gray-100"
                            }`}
                          >
                            {entry ? (
                              <div>
                                <div className="text-sm font-semibold text-gray-900 line-clamp-2">
                                  {entry.job_name || "Scheduled job"}
                                </div>
                                {entry.job_client && (
                                  <div className="text-xs text-gray-500 mt-1 line-clamp-1">
                                    {entry.job_client}
                                  </div>
                                )}
                                {entry.notes && (
                                  <div className="text-xs text-gray-600 mt-1 line-clamp-2">
                                    {entry.notes}
                                  </div>
                                )}
                              </div>
                            ) : (
                              <div className="flex h-full items-center justify-center text-sm text-gray-400">
                                + Add job
                              </div>
                            )}
                          </button>
                        </td>
                      );
                    })}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {selectedCell && (
        <div className="fixed inset-0 bg-gray-600 bg-opacity-50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-lg w-full">
            <div className="p-6 border-b border-gray-200">
              <h3 className="text-lg font-semibold text-gray-900">
                {selectedCell.entry ? "Edit Scheduled Job" : "Schedule Job"}
              </h3>
              <p className="text-sm text-gray-500 mt-1">
                {selectedCell.worker.name} — {selectedCell.day.label} {selectedCell.day.display}
              </p>
            </div>

            <div className="p-6 space-y-4">
              {error && (
                <div className="rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700">
                  {error}
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Active Job
                </label>
                <select
                  value={selectedJobId}
                  onChange={(event) => setSelectedJobId(event.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                >
                  <option value="">Select active job...</option>
                  {activeJobs.map((job) => (
                    <option key={job.id} value={job.id}>
                      {job.name} {job.client ? `— ${job.client}` : ""}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Notes
                </label>
                <textarea
                  value={notes}
                  onChange={(event) => setNotes(event.target.value)}
                  rows={3}
                  placeholder="Optional notes for the allocation..."
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                />
              </div>
            </div>

            <div className="px-6 py-4 bg-gray-50 flex justify-between rounded-b-lg">
              <div>
                {selectedCell.entry && (
                  <button
                    onClick={deleteAllocation}
                    disabled={saving}
                    className="px-4 py-2 bg-red-100 text-red-700 rounded-md text-sm font-medium hover:bg-red-200 disabled:opacity-50"
                  >
                    Delete
                  </button>
                )}
              </div>

              <div className="flex gap-2">
                <button
                  onClick={closeModal}
                  disabled={saving}
                  className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  onClick={saveAllocation}
                  disabled={saving}
                  className="px-4 py-2 text-white rounded-md text-sm font-medium hover:opacity-90 disabled:opacity-50"
                  style={{ backgroundColor: "#d01f2f" }}
                >
                  {saving ? "Saving..." : "Save Allocation"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default SchedulePage;
