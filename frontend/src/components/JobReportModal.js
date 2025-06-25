import React, { useState, useEffect } from "react";
import { useWorker } from "../contexts/WorkerContext";
import axios from "axios";

const JobReportModal = ({ jobId, onClose }) => {
  const { API, formatCurrency, formatDate, formatDuration } = useWorker();
  const [reportData, setReportData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Get auth headers for admin requests
  const getAuthHeaders = () => {
    const adminAuth = localStorage.getItem('adminAuth');
    return {
      'Authorization': `Basic ${adminAuth}`,
      'Content-Type': 'application/json'
    };
  };

  // Fetch job report data
  const fetchJobReport = async () => {
    try {
      setLoading(true);
      setError("");
      
      console.log(`Fetching job report for job ID: ${jobId}`);
      const response = await axios.get(`${API}/reports/job-costs/${jobId}`, {
        headers: getAuthHeaders()
      });
      
      console.log("Job report data received:", response.data);
      setReportData(response.data);
    } catch (err) {
      console.error("Error fetching job report:", err);
      setError(err.response?.data?.detail || "Error fetching job report");
    } finally {
      setLoading(false);
    }
  };

  // Export job report
  const exportReport = async () => {
    try {
      const response = await axios.get(`${API}/reports/export/job/${jobId}`, {
        responseType: 'blob',
        headers: getAuthHeaders()
      });

      const filename = `job_report_${reportData?.job?.name?.replace(/\s+/g, '_') || 'unknown'}.csv`;

      const url = window.URL.createObjectURL(new Blob([response.data]));
      const link = document.createElement('a');
      link.href = url;
      link.setAttribute('download', filename);
      document.body.appendChild(link);
      link.click();
      link.remove();
    } catch (error) {
      console.error("Error exporting job report:", error);
    }
  };

  useEffect(() => {
    console.log(`JobReportModal mounted with jobId: ${jobId}`);
    if (jobId) {
      fetchJobReport();
    }
  }, [jobId]);

  if (loading) {
    return (
      <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
        <div className="bg-white rounded-lg shadow-xl p-8">
          <div className="flex items-center justify-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-red-600"></div>
            <span className="ml-3 text-gray-600">Loading job report...</span>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
        <div className="bg-white rounded-lg shadow-xl p-8">
          <div className="text-center">
            <div className="text-red-600 mb-4">Error loading job report</div>
            <div className="text-gray-600 mb-4">{error}</div>
            <button
              onClick={onClose}
              className="px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-gray-200 flex justify-between items-center">
          <h3 className="text-lg font-semibold text-gray-900">Job Report</h3>
          <div className="flex space-x-2">
            <button
              onClick={exportReport}
              className="px-3 py-1 bg-green-600 text-white text-sm rounded-md hover:bg-green-700"
            >
              Export CSV
            </button>
            <button
              onClick={onClose}
              className="px-3 py-1 bg-gray-600 text-white text-sm rounded-md hover:bg-gray-700"
            >
              Close
            </button>
          </div>
        </div>

        <div className="p-6 space-y-6">
          {/* Job Summary */}
          <div className="bg-gray-50 p-4 rounded-lg">
            <h4 className="text-lg font-semibold text-gray-900 mb-3">{reportData.job.name}</h4>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <p className="text-sm text-gray-600">Client</p>
                <p className="font-medium">{reportData.job.client}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Location</p>
                <p className="font-medium">{reportData.job.location}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Status</p>
                <span className={`inline-flex px-2 py-1 text-xs font-semibold rounded-full ${
                  reportData.job.status === 'active' 
                    ? 'bg-green-100 text-green-800' 
                    : reportData.job.status === 'completed'
                    ? 'bg-blue-100 text-blue-800'
                    : 'bg-gray-100 text-gray-800'
                }`}>
                  {reportData.job.status}
                </span>
              </div>
              <div>
                <p className="text-sm text-gray-600">Created</p>
                <p className="font-medium">{formatDate(reportData.job.created_date)}</p>
              </div>
            </div>
            {reportData.job.description && (
              <div className="mt-3">
                <p className="text-sm text-gray-600">Description</p>
                <p className="font-medium">{reportData.job.description}</p>
              </div>
            )}
          </div>

          {/* Cost Summary */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="bg-blue-50 p-4 rounded-lg">
              <p className="text-sm text-blue-600 font-medium">Total Hours</p>
              <p className="text-2xl font-bold text-blue-800">{reportData.total_hours}h</p>
            </div>
            <div className="bg-green-50 p-4 rounded-lg">
              <p className="text-sm text-green-600 font-medium">Labor Cost</p>
              <p className="text-2xl font-bold text-green-800">{formatCurrency(reportData.labor_cost)}</p>
            </div>
            <div className="bg-orange-50 p-4 rounded-lg">
              <p className="text-sm text-orange-600 font-medium">Materials Cost</p>
              <p className="text-2xl font-bold text-orange-800">{formatCurrency(reportData.materials_cost)}</p>
            </div>
            <div className="bg-purple-50 p-4 rounded-lg">
              <p className="text-sm text-purple-600 font-medium">Total Cost</p>
              <p className="text-2xl font-bold text-purple-800">{formatCurrency(reportData.total_cost)}</p>
            </div>
          </div>

          {/* Cost Analysis */}
          <div className="bg-gray-50 p-4 rounded-lg">
            <h4 className="text-lg font-semibold text-gray-900 mb-3">Cost Analysis</h4>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <p className="text-sm text-gray-600">Quoted Cost</p>
                <p className="text-xl font-bold text-gray-900">{formatCurrency(reportData.quoted_cost)}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Actual Cost</p>
                <p className="text-xl font-bold text-gray-900">{formatCurrency(reportData.total_cost)}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Variance</p>
                <p className={`text-xl font-bold ${
                  reportData.cost_variance >= 0 ? 'text-green-600' : 'text-red-600'
                }`}>
                  {formatCurrency(reportData.cost_variance)}
                </p>
                <p className="text-xs text-gray-500">
                  {reportData.cost_variance >= 0 ? 'Under budget' : 'Over budget'}
                </p>
              </div>
            </div>
          </div>

          {/* Time Entries */}
          {reportData.time_entries && reportData.time_entries.length > 0 && (
            <div>
              <h4 className="text-lg font-semibold text-gray-900 mb-3">Time Entries</h4>
              <div className="bg-white border rounded-lg overflow-hidden">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Worker
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
                    {reportData.time_entries.map((entry) => {
                      const laborCost = entry.duration_minutes ? (entry.duration_minutes / 60) * 15 : 0;
                      return (
                        <tr key={entry.id}>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {entry.worker_name}
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
          )}

          {/* Materials */}
          {reportData.materials && reportData.materials.length > 0 && (
            <div>
              <h4 className="text-lg font-semibold text-gray-900 mb-3">Materials</h4>
              <div className="bg-white border rounded-lg overflow-hidden">
                <table className="min-w-full divide-y divide-gray-200">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Material
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Quantity
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Unit Cost
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Total Cost
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Purchase Date
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {reportData.materials.map((material) => {
                      const totalCost = material.cost * material.quantity;
                      return (
                        <tr key={material.id}>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {material.name}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {material.quantity}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {formatCurrency(material.cost)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {formatCurrency(totalCost)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                            {formatDate(material.purchase_date)}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Summary Stats */}
          <div className="bg-blue-50 p-4 rounded-lg">
            <h4 className="text-lg font-semibold text-blue-900 mb-3">Summary</h4>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
              <div>
                <p className="text-2xl font-bold text-blue-800">{reportData.time_entries_count}</p>
                <p className="text-sm text-blue-600">Time Entries</p>
              </div>
              <div>
                <p className="text-2xl font-bold text-blue-800">{reportData.materials_count}</p>
                <p className="text-sm text-blue-600">Materials</p>
              </div>
              <div>
                <p className="text-2xl font-bold text-blue-800">{reportData.total_hours}h</p>
                <p className="text-sm text-blue-600">Total Hours</p>
              </div>
              <div>
                <p className={`text-2xl font-bold ${
                  reportData.cost_variance >= 0 ? 'text-green-600' : 'text-red-600'
                }`}>
                  {Math.abs(reportData.cost_variance) > 0 ? 
                    `${((Math.abs(reportData.cost_variance) / reportData.quoted_cost) * 100).toFixed(1)}%` : 
                    '0%'
                  }
                </p>
                <p className="text-sm text-blue-600">
                  {reportData.cost_variance >= 0 ? 'Under Budget' : 'Over Budget'}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default JobReportModal;