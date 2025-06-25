import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useWorker } from "../contexts/WorkerContext";
import axios from "axios";
import JobEditModal from "./JobEditModal";

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
  const [filters, setFilters] = useState({
    jobId: "",
    workerId: "",
    startDate: "",
    endDate: ""
  });
  const [editingJob, setEditingJob] = useState(null);

  // Fetch dashboard stats
  const fetchDashboardStats = async () => {
    try {
      const response = await axios.get(`${API}/reports/dashboard`);
      setDashboardStats(response.data);
    } catch (error) {
      console.error("Error fetching dashboard stats:", error);
    }
  };

  // Fetch all data
  const fetchData = async () => {
    setLoading(true);
    try {
      const [jobsRes, workersRes, timeEntriesRes, materialsRes] = await Promise.all([
        axios.get(`${API}/jobs`),
        axios.get(`${API}/workers`),
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
        responseType: 'blob'
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

  // Calculate job totals
  const getJobTotals = (jobId) => {
    const jobTimeEntries = timeEntries.filter(entry => entry.job_id === jobId && entry.duration_minutes);
    const jobMaterials = materials.filter(material => material.job_id === jobId);
    
    const totalHours = jobTimeEntries.reduce((sum, entry) => sum + (entry.duration_minutes || 0), 0) / 60;
    const laborCost = totalHours * 15; // £15/hour
    const materialsCost = jobMaterials.reduce((sum, material) => sum + (material.cost * material.quantity), 0);
    const totalCost = laborCost + materialsCost;
    
    return { totalHours, laborCost, materialsCost, totalCost };
  };

  useEffect(() => {
    fetchDashboardStats();
    fetchData();
  }, []);

  useEffect(() => {
    if (activeTab === "reports") {
      fetchFilteredTimeEntries();
    }
  }, [filters, activeTab]);

  const handleLogout = () => {
    navigate("/");
  };

  const handleJobUpdate = () => {
    fetchData(); // Refresh data after job update
    setEditingJob(null);
  };

  const StatCard = ({ title, value, color = "blue" }) => (
    <div className="bg-white rounded-lg shadow-sm p-6">
      <div className="flex items-center">
        <div className="flex-1">
          <p className="text-sm font-medium text-gray-600">{title}</p>
          <p className={`text-2xl font-bold text-${color}-600`}>{value}</p>
        </div>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-4">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">LDA Group</h1>
              <p className="text-gray-600">Admin Dashboard</p>
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
                    ? "border-red-600 text-red-600"
                    : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
                }`}
                style={{ 
                  borderBottomColor: activeTab === tab.id ? '#D11F2F' : 'transparent',
                  color: activeTab === tab.id ? '#D11F2F' : undefined
                }}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
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
          </div>
        )}

        {/* Jobs Tab */}
        {activeTab === "jobs" && (
          <div className="space-y-6">
            <div className="flex justify-between items-center">
              <h2 className="text-2xl font-bold text-gray-900">Jobs Management</h2>
            </div>

            <div className="bg-white shadow-sm rounded-lg overflow-hidden">
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
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {jobs.map((job) => {
                    const totals = getJobTotals(job.id);
                    const variance = job.quoted_cost - totals.totalCost;
                    
                    return (
                      <tr key={job.id}>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div>
                            <div className="text-sm font-medium text-gray-900">{job.name}</div>
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
                          <button
                            onClick={() => setEditingJob(job)}
                            className="text-red-600 hover:text-red-900"
                            style={{ color: '#D11F2F' }}
                          >
                            Edit
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
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
                        Cost
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {timeEntries.map((entry) => {
                      const laborCost = entry.duration_minutes ? (entry.duration_minutes / 60) * 15 : 0;
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
                            {formatCurrency(laborCost)}
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
            </div>

            <div className="bg-white shadow-sm rounded-lg overflow-hidden">
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
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {workers.map((worker) => (
                    <tr key={worker.id}>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        {worker.name}
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
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                          worker.active 
                            ? 'bg-green-100 text-green-800' 
                            : 'bg-red-100 text-red-800'
                        }`}>
                          {worker.active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Job Edit Modal */}
      {editingJob && (
        <JobEditModal 
          job={editingJob} 
          onClose={() => setEditingJob(null)}
          onUpdate={handleJobUpdate}
        />
      )}
    </div>
  );
};

export default AdminDashboard;