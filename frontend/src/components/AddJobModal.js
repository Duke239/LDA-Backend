import React, { useState } from "react";
import { useWorker } from "../contexts/WorkerContext";
import axios from "axios";

const AddJobModal = ({ onClose, onAdded }) => {
  const { API, formatCurrency } = useWorker();
  const [formData, setFormData] = useState({
    name: "",
    description: "",
    location: "",
    client: "",
    quoted_cost: ""
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
      
      const jobData = {
        ...formData,
        quoted_cost: parseFloat(formData.quoted_cost)
      };
      
      await axios.post(`${API}/jobs`, jobData, {
        headers: getAuthHeaders()
      });
      
      onAdded();
    } catch (err) {
      setError(err.response?.data?.detail || "Error adding job");
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

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="text-lg font-semibold text-gray-900">Add New Job</h3>
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
                Job Name *
              </label>
              <input
                type="text"
                name="name"
                value={formData.name}
                onChange={handleChange}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                placeholder="e.g., Kitchen Renovation - Smith House"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Client *
              </label>
              <input
                type="text"
                name="client"
                value={formData.client}
                onChange={handleChange}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                placeholder="e.g., Smith Family, ABC Ltd"
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Location *
            </label>
            <input
              type="text"
              name="location"
              value={formData.location}
              onChange={handleChange}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
              placeholder="e.g., 123 Baker Street, London"
              required
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Description
            </label>
            <textarea
              name="description"
              value={formData.description}
              onChange={handleChange}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
              placeholder="Detailed description of the work to be done..."
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Quoted Cost (£) *
            </label>
            <input
              type="number"
              name="quoted_cost"
              value={formData.quoted_cost}
              onChange={handleChange}
              step="0.01"
              min="0"
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
              placeholder="0.00"
              required
            />
            {formData.quoted_cost && (
              <p className="mt-2 text-sm text-gray-600">
                Quoted Cost: {formatCurrency(parseFloat(formData.quoted_cost) || 0)}
              </p>
            )}
          </div>

          <div className="bg-blue-50 border border-blue-200 p-4 rounded-md">
            <h4 className="font-medium text-blue-900 mb-2">Job Information</h4>
            <ul className="text-blue-800 text-sm space-y-1">
              <li>• This job will be available for workers to clock in to</li>
              <li>• Track time entries and materials against this job</li>
              <li>• Monitor cost variance against the quoted price</li>
              <li>• Generate detailed reports and exports</li>
            </ul>
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
              style={{ backgroundColor: loading ? '#9CA3AF' : '#D11F2F' }}
            >
              {loading ? (
                <div className="flex items-center justify-center">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                  Adding...
                </div>
              ) : (
                "Add Job"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default AddJobModal;