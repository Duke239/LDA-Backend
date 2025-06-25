import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useWorker } from "../contexts/WorkerContext";
import axios from "axios";
import JobEditModal from "./JobEditModal";
import AddWorkerModal from "./AddWorkerModal";
import AddJobModal from "./AddJobModal";
import JobReportModal from "./JobReportModal";
import EditWorkerModal from "./EditWorkerModal";
import AddMaterialToJobModal from "./AddMaterialToJobModal";
import EditTimeEntryModal from "./EditTimeEntryModal";

const AdminDashboard = () => {
  const navigate = useNavigate();
  const { API, formatCurrency, formatDate, formatDuration } = useWorker();
  
  const [activeTab, setActiveTab] = useState("dashboard");
  const [dashboardStats, setDashboardStats] = useState({});
  const [jobs, setJobs] = useState([]);
  const [workers, setWorkers] = useState([]);
  const [timeEntries, setTimeEntries] = useState([]);
  const [materials, setMaterials] = useState([]);
  const [loading, setLoading] = useState(false);
  
  // Filters for reports
  const [filters, setFilters] = useState({
    jobId: "",
    workerId: "",
    startDate: "",
    endDate: ""
  });
  
  // Filters for jobs
  const [jobFilters, setJobFilters] = useState({
    client: "",
    status: ""
  });
  
  // Modal states
  const [editingJob, setEditingJob] = useState(null);
  const [showAddWorker, setShowAddWorker] = useState(false);
  const [showAddJob, setShowAddJob] = useState(false);
  const [viewingJobReport, setViewingJobReport] = useState(null);
  const [editingWorker, setEditingWorker] = useState(null);
  const [addingMaterialToJob, setAddingMaterialToJob] = useState(null);
  const [editingTimeEntry, setEditingTimeEntry] = useState(null);
  const [includeArchived, setIncludeArchived] = useState(false);

  // Get auth headers for admin requests
  const getAuthHeaders = () => {
    const adminAuth = localStorage.getItem('adminAuth');
    if (!adminAuth) {
      navigate('/');
      return {};
    }
    return {
      'Authorization': `Basic ${adminAuth}`,
      'Content-Type': 'application/json'
    };
  };

  // Fetch dashboard stats
  const fetchDashboardStats = async () => {
    try {
      const response = await axios.get(`${API}/reports/dashboard`, {
        headers: getAuthHeaders()
      });
      setDashboardStats(response.data);
    } catch (error) {
      if (error.response?.status === 401) {
        handleLogout();
      } else {
        console.error("Error fetching dashboard stats:", error);
      }
    }
  };

  // Fetch all data
  const fetchData = async () => {
    setLoading(true);
    try {
      const [jobsRes, workersRes, timeEntriesRes, materialsRes] = await Promise.all([
        axios.get(`${API}/jobs?include_archived=${includeArchived}`),
        axios.get(`${API}/workers?include_archived=${includeArchived}`),
        axios.get(`${API}/time-entries`),
        axios.get(`${API}/materials`)
      ]);

      setJobs(jobsRes.data);
      setWorkers(workersRes.data);
      setTimeEntries(timeEntriesRes.data);
      setMaterials(materialsRes.data);
    } catch (error) {
      console.error("Error fetching data:", error);
    } finally {
      setLoading(false);
    }
  };

  // Archive/unarchive worker
  const archiveWorker = async (workerId) => {
    try {
      await axios.put(`${API}/workers/${workerId}/archive`, {}, {
        headers: getAuthHeaders()
      });
      fetchData();
    } catch (error) {
      console.error("Error archiving worker:", error);
    }
  };

  // Delete worker
  const deleteWorker = async (workerId) => {
    if (window.confirm("Are you sure you want to permanently delete this worker?")) {
      try {
        await axios.delete(`${API}/workers/${workerId}`, {
          headers: getAuthHeaders()
        });
        fetchData();
      } catch (error) {
        console.error("Error deleting worker:", error);
      }
    }
  };

  // Archive/unarchive job
  const archiveJob = async (jobId) => {
    try {
      await axios.put(`${API}/jobs/${jobId}/archive`, {}, {
        headers: getAuthHeaders()
      });
      fetchData();
    } catch (error) {
      console.error("Error archiving job:", error);
    }
  };

  const unarchiveJob = async (jobId) => {
    try {
      await axios.put(`${API}/jobs/${jobId}/unarchive`, {}, {
        headers: getAuthHeaders()
      });
      fetchData();
    } catch (error) {
      console.error("Error unarchiving job:", error);
    }
  };

  // Delete job
  const deleteJob = async (jobId) => {
    if (window.confirm("Are you sure you want to permanently delete this job?")) {
      try {
        await axios.delete(`${API}/jobs/${jobId}`, {
          headers: getAuthHeaders()
        });
        fetchData();
      } catch (error) {
        console.error("Error deleting job:", error);
      }
    }
  };

  // Fetch filtered time entries
  const fetchFilteredTimeEntries = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filters.jobId) params.append('job_id', filters.jobId);
      if (filters.workerId) params.append('worker_id', filters.workerId);
      if (filters.startDate) params.append('start_date', filters.startDate);
      if (filters.endDate) params.append('end_date', filters.endDate);

      const response = await axios.get(`${API}/time-entries?${params}`);
      setTimeEntries(response.data);
    } catch (error) {
      console.error("Error fetching filtered time entries:", error);
    } finally {
      setLoading(false);
    }
  };

  // Export time entries
  const exportTimeEntries = async () => {
    try {
      const params = new URLSearchParams();
      if (filters.jobId) params.append('job_id', filters.jobId);
      if (filters.startDate) params.append('start_date', filters.startDate);
      if (filters.endDate) params.append('end_date', filters.endDate);

      const response = await axios.get(`${API}/reports/export/time-entries?${params}`, {
        responseType: 'blob',
        headers: getAuthHeaders()
      });

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', 'time_entries.csv');
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (error) {
      console.error("Error exporting time entries:", error);
    }
  };

  // Export jobs
  const exportJobs = async () => {
    try {
      const filteredJobs = getFilteredJobs();
      
      // Create CSV content
      const csvContent = [
        ['Job Name', 'Client', 'Location', 'Status', 'Quoted Cost', 'Created Date'],
        ...filteredJobs.map(job => [
          job.name,
          job.client,
          job.location,
          job.status,
          job.quoted_cost,
          formatDate(job.created_date)
        ])
      ].map(row => row.join(',')).join('\n');

      const blob = new Blob([csvContent], { type: 'text/csv' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', 'jobs.csv');
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (error) {
      console.error("Error exporting jobs:", error);
    }
  };

  // Get worker name
  const getWorkerName = (workerId) => {
    const worker = workers.find(w => w.id === workerId);
    return worker ? worker.name : "Unknown";
  };

  // Get job name
  const getJobName = (jobId) => {
    const job = jobs.find(j => j.id === jobId);
    return job ? job.name : "Unknown";
  };

  // Calculate job totals with individual hourly rates
  const getJobTotals = (jobId) => {
    const jobTimeEntries = timeEntries.filter(entry => entry.job_id === jobId && entry.duration_minutes);
    const jobMaterials = materials.filter(material => material.job_id === jobId);
    
    const totalHours = jobTimeEntries.reduce((sum, entry) => sum + (entry.duration_minutes || 0), 0) / 60;
    
    // Calculate labor cost using individual worker hourly rates
    let laborCost = 0;
    jobTimeEntries.forEach(entry => {
      const worker = workers.find(w => w.id === entry.worker_id);
      const hourlyRate = worker?.hourly_rate || 15.0;
      const entryHours = (entry.duration_minutes || 0) / 60;
      laborCost += entryHours * hourlyRate;
    });
    
    const materialsCost = jobMaterials.reduce((sum, material) => sum + (material.cost * material.quantity), 0);
    const totalCost = laborCost + materialsCost;
    
    return { totalHours, laborCost, materialsCost, totalCost };
  };

  // Get filtered jobs
  const getFilteredJobs = () => {
    return jobs.filter(job => {
      if (jobFilters.client && !job.client.toLowerCase().includes(jobFilters.client.toLowerCase())) {
        return false;
      }
      if (jobFilters.status && job.status !== jobFilters.status) {
        return false;
      }
      return true;
    });
  };

  // Get unique clients and statuses for filters
  const getUniqueClients = () => {
    return [...new Set(jobs.map(job => job.client))].sort();
  };

  const getUniqueStatuses = () => {
    return [...new Set(jobs.map(job => job.status))].sort();
  };

  useEffect(() => {
    // Check if admin is authenticated
    const adminAuth = localStorage.getItem('adminAuth');
    if (!adminAuth) {
      navigate('/');
      return;
    }

    fetchDashboardStats();
    fetchData();
  }, [includeArchived]);

  useEffect(() => {
    if (activeTab === "reports") {
      fetchFilteredTimeEntries();
    }
  }, [filters, activeTab]);

  const handleLogout = () => {
    localStorage.removeItem('adminAuth');
    navigate("/");
  };

  const handleJobUpdate = () => {
    fetchData();
    setEditingJob(null);
  };

  const handleWorkerAdded = () => {
    fetchData();
    setShowAddWorker(false);
  };

  const handleJobAdded = () => {
    fetchData();
    setShowAddJob(false);
  };

  const handleWorkerUpdated = () => {
    fetchData();
    setEditingWorker(null);
  };

  const handleMaterialAdded = () => {
    fetchData();
    setAddingMaterialToJob(null);
  };

  const handleTimeEntryUpdated = () => {
    fetchFilteredTimeEntries();
    setEditingTimeEntry(null);
  };

  const StatCard = ({ title, value, color = "blue" }) => (
    <div className="bg-white rounded-lg shadow-sm p-6 border-l-4" style={{borderLeftColor: '#d01f2f'}}>
      <div className="flex items-center">
        <div className="flex-1">
          <p className="text-sm font-medium text-gray-600">{title}</p>
          <p className={`text-2xl font-bold text-${color}-600`}>{value}</p>
        </div>
      </div>
    </div>
  );

  const ActionButton = ({ onClick, children, color = "#d01f2f", disabled = false }) => (
    <button
      onClick={onClick}
      disabled={disabled}
      className="px-3 py-1 text-xs font-medium text-white rounded hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
      style={{ backgroundColor: disabled ? '#9CA3AF' : color }}
    >
      {children}
    </button>
  );

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow-sm border-b-4" style={{borderBottomColor: '#d01f2f'}}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-4">
            <div className="flex items-center space-x-4">
              <img src="/lda-logo.svg" alt="LDA Group" className="h-12 w-12" />
              <div>
                <h1 className="text-2xl font-bold text-gray-900">LDA Group</h1>
                <p className="text-gray-600">Admin Dashboard</p>
              </div>
            </div>
            <button
              onClick={handleLogout}
              className="text-gray-500 hover:text-gray-700 px-3 py-2 rounded-md text-sm font-medium"
            >
              Logout
            </button>
          </div>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <nav className="flex space-x-8">
            {[
              { id: "dashboard", label: "Dashboard" },
              { id: "jobs", label: "Jobs" },
              { id: "reports", label: "Reports" },
              { id: "workers", label: "Workers" }
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`py-4 px-1 border-b-2 font-medium text-sm ${
                  activeTab === tab.id
                    ? "text-red-600"
                    : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
                }`}
                style={{ 
                  borderBottomColor: activeTab === tab.id ? '#d01f2f' : 'transparent',
                  color: activeTab === tab.id ? '#d01f2f' : undefined
                }}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Archive Toggle */}
        <div className="mb-6 flex justify-end">
          <label className="flex items-center space-x-2">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(e) => setIncludeArchived(e.target.checked)}
              className="rounded text-red-600 focus:ring-red-500"
            />
            <span className="text-sm text-gray-600">Include archived items</span>
          </label>
        </div>

        {/* Dashboard Tab */}
        {activeTab === "dashboard" && (
          <div className="space-y-6">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
              <StatCard 
                title="Total Workers" 
                value={dashboardStats.total_workers || 0} 
                color="blue" 
              />
              <StatCard 
                title="Active Jobs" 
                value={dashboardStats.active_jobs || 0} 
                color="green" 
              />
              <StatCard 
                title="Hours This Week" 
                value={`${dashboardStats.total_hours_this_week || 0}h`} 
                color="purple" 
              />
              <StatCard 
                title="Materials This Month" 
                value={formatCurrency(dashboardStats.total_materials_cost_this_month || 0)} 
                color="orange" 
              />
            </div>

            {/* Attendance Alerts */}
            {dashboardStats.attendance_alerts && dashboardStats.attendance_alerts.length > 0 && (
              <div className="bg-white rounded-lg shadow-sm p-6 border-l-4" style={{borderLeftColor: '#d01f2f'}}>
                <h3 className="text-lg font-semibold text-gray-900 mb-4">Attendance Alerts</h3>
                <div className="space-y-2">
                  {dashboardStats.attendance_alerts.map((alert, index) => (
                    <div key={index} className={`p-3 rounded-md ${
                      alert.type === 'late_clock_in' ? 'bg-yellow-50 text-yellow-800' :
                      alert.type === 'late_clock_out' ? 'bg-orange-50 text-orange-800' :
                      'bg-red-50 text-red-800'
                    }`}>
                      <span className="font-medium">{alert.worker_name}:</span> {alert.message}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Jobs Tab */}
        {activeTab === "jobs" && (
          <div className="space-y-6">
            <div className="flex justify-between items-center">
              <h2 className="text-2xl font-bold text-gray-900">Jobs Management</h2>
              <div className="flex space-x-3">
                <button
                  onClick={exportJobs}
                  className="bg-green-600 text-white px-4 py-2 rounded-md hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
                >
                  Export Jobs CSV
                </button>
                <button
                  onClick={() => setShowAddJob(true)}
                  className="text-white px-4 py-2 rounded-md hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
                  style={{backgroundColor: '#d01f2f'}}
                >
                  Add New Job
                </button>
              </div>
            </div>

            {/* Job Filters */}
            <div className="bg-white p-6 rounded-lg shadow-sm">
              <h3 className="text-lg font-medium text-gray-900 mb-4">Filter Jobs</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Client</label>
                  <select
                    value={jobFilters.client}
                    onChange={(e) => setJobFilters({ ...jobFilters, client: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                  >
                    <option value="">All Clients</option>
                    {getUniqueClients().map((client) => (
                      <option key={client} value={client}>
                        {client}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Status</label>
                  <select
                    value={jobFilters.status}
                    onChange={(e) => setJobFilters({ ...jobFilters, status: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                  >
                    <option value="">All Statuses</option>
                    {getUniqueStatuses().map((status) => (
                      <option key={status} value={status}>
                        {status}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            <div className="bg-white shadow-sm rounded-lg overflow-hidden">
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Job
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Client
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Status
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Quoted
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Actual Cost
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Variance
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider w-64">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {getFilteredJobs().map((job) => {
                      const totals = getJobTotals(job.id);
                      const variance = job.quoted_cost - totals.totalCost;
                      
                      return (
                        <tr key={job.id} className={job.archived ? "bg-gray-100" : ""}>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div>
                              <div className="text-sm font-medium text-gray-900">
                                {job.name} {job.archived && <span className="text-xs text-gray-500">(Archived)</span>}
                              </div>
                              <div className="text-sm text-gray-500">{job.location}</div>
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {job.client}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                              job.status === 'active' 
                                ? 'bg-green-100 text-green-800' 
                                : job.status === 'completed'
                                ? 'bg-blue-100 text-blue-800'
                                : 'bg-gray-100 text-gray-800'
                            }`}>
                              {job.status}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {formatCurrency(job.quoted_cost)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {formatCurrency(totals.totalCost)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm">
                            <span className={variance >= 0 ? 'text-green-600' : 'text-red-600'}>
                              {formatCurrency(variance)}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                            <div className="flex flex-wrap gap-1">
                              <ActionButton onClick={() => setEditingJob(job)}>
                                {job.archived ? 'View' : 'Edit'}
                              </ActionButton>
                              <ActionButton onClick={() => setViewingJobReport(job.id)} color="#3B82F6">
                                Report
                              </ActionButton>
                              <ActionButton onClick={() => setAddingMaterialToJob(job.id)} color="#8B5CF6">
                                Add Material
                              </ActionButton>
                              {job.archived ? (
                                <ActionButton onClick={() => unarchiveJob(job.id)} color="#10B981">
                                  Unarchive
                                </ActionButton>
                              ) : (
                                <ActionButton onClick={() => archiveJob(job.id)} color="#F59E0B">
                                  Archive
                                </ActionButton>
                              )}
                              <ActionButton onClick={() => deleteJob(job.id)} color="#EF4444">
                                Delete
                              </ActionButton>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* Reports Tab */}
        {activeTab === "reports" && (
          <div className="space-y-6">
            <div className="flex justify-between items-center">
              <h2 className="text-2xl font-bold text-gray-900">Time & Material Reports</h2>
              <button
                onClick={exportTimeEntries}
                className="bg-green-600 text-white px-4 py-2 rounded-md hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-green-500 focus:ring-offset-2"
              >
                Export CSV
              </button>
            </div>

            {/* Filters */}
            <div className="bg-white p-6 rounded-lg shadow-sm">
              <h3 className="text-lg font-medium text-gray-900 mb-4">Filters</h3>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Job</label>
                  <select
                    value={filters.jobId}
                    onChange={(e) => setFilters({ ...filters, jobId: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                  >
                    <option value="">All Jobs</option>
                    {jobs.map((job) => (
                      <option key={job.id} value={job.id}>
                        {job.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Worker</label>
                  <select
                    value={filters.workerId}
                    onChange={(e) => setFilters({ ...filters, workerId: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                  >
                    <option value="">All Workers</option>
                    {workers.map((worker) => (
                      <option key={worker.id} value={worker.id}>
                        {worker.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">Start Date</label>
                  <input
                    type="date"
                    value={filters.startDate}
                    onChange={(e) => setFilters({ ...filters, startDate: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">End Date</label>
                  <input
                    type="date"
                    value={filters.endDate}
                    onChange={(e) => setFilters({ ...filters, endDate: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                  />
                </div>
              </div>
            </div>

            {/* Time Entries Table */}
            <div className="bg-white shadow-sm rounded-lg overflow-hidden">
              <div className="px-6 py-4 border-b border-gray-200">
                <h3 className="text-lg font-medium text-gray-900">Time Entries</h3>
              </div>
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Worker
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Job
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Clock In
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Clock Out
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Duration
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Hourly Rate
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Cost
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {timeEntries.map((entry) => {
                      const worker = workers.find(w => w.id === entry.worker_id);
                      const hourlyRate = worker?.hourly_rate || 15.0;
                      const laborCost = entry.duration_minutes ? (entry.duration_minutes / 60) * hourlyRate : 0;
                      return (
                        <tr key={entry.id}>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {getWorkerName(entry.worker_id)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {getJobName(entry.job_id)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {formatDate(entry.clock_in)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {entry.clock_out ? formatDate(entry.clock_out) : "Active"}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {entry.duration_minutes ? formatDuration(entry.duration_minutes) : "Active"}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {formatCurrency(hourlyRate)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {formatCurrency(laborCost)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            <ActionButton onClick={() => setEditingTimeEntry(entry)} color="#3B82F6">
                              Edit
                            </ActionButton>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* Workers Tab */}
        {activeTab === "workers" && (
          <div className="space-y-6">
            <div className="flex justify-between items-center">
              <h2 className="text-2xl font-bold text-gray-900">Workers Management</h2>
              <button
                onClick={() => setShowAddWorker(true)}
                className="text-white px-4 py-2 rounded-md hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2"
                style={{backgroundColor: '#d01f2f'}}
              >
                Add New Worker
              </button>
            </div>

            <div className="bg-white shadow-sm rounded-lg overflow-hidden">
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Name
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Email
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Phone
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Role
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Hourly Rate
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Status
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {workers.map((worker) => (
                      <tr key={worker.id} className={worker.archived ? "bg-gray-100" : ""}>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                          {worker.name} {worker.archived && <span className="text-xs text-gray-500">(Archived)</span>}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          {worker.email}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          {worker.phone}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          {worker.role}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                          {formatCurrency(worker.hourly_rate || 15.0)}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                            worker.active 
                              ? 'bg-green-100 text-green-800' 
                              : 'bg-red-100 text-red-800'
                          }`}>
                            {worker.active ? 'Active' : 'Inactive'}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                          <div className="flex flex-wrap gap-1">
                            <ActionButton onClick={() => setEditingWorker(worker)}>
                              Edit
                            </ActionButton>
                            {!worker.archived ? (
                              <ActionButton onClick={() => archiveWorker(worker.id)} color="#F59E0B">
                                Archive
                              </ActionButton>
                            ) : null}
                            <ActionButton onClick={() => deleteWorker(worker.id)} color="#EF4444">
                              Delete
                            </ActionButton>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Modals */}
      {editingJob && (
        <JobEditModal 
          job={editingJob} 
          onClose={() => setEditingJob(null)}
          onUpdate={handleJobUpdate}
        />
      )}

      {showAddWorker && (
        <AddWorkerModal 
          onClose={() => setShowAddWorker(false)}
          onAdded={handleWorkerAdded}
        />
      )}

      {showAddJob && (
        <AddJobModal 
          onClose={() => setShowAddJob(false)}
          onAdded={handleJobAdded}
        />
      )}

      {viewingJobReport && (
        <JobReportModal 
          jobId={viewingJobReport}
          onClose={() => setViewingJobReport(null)}
        />
      )}

      {editingWorker && (
        <EditWorkerModal 
          worker={editingWorker}
          onClose={() => setEditingWorker(null)}
          onUpdate={handleWorkerUpdated}
        />
      )}

      {addingMaterialToJob && (
        <AddMaterialToJobModal 
          jobId={addingMaterialToJob}
          onClose={() => setAddingMaterialToJob(null)}
          onAdded={handleMaterialAdded}
        />
      )}

      {editingTimeEntry && (
        <EditTimeEntryModal 
          timeEntry={editingTimeEntry}
          workers={workers}
          jobs={jobs}
          onClose={() => setEditingTimeEntry(null)}
          onUpdate={handleTimeEntryUpdated}
        />
      )}
    </div>
  );
};

export default AdminDashboard;