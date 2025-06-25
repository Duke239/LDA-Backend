import React, { useState } from "react";
import { useWorker } from "../contexts/WorkerContext";

const AddMaterial = ({ jobId, onClose }) => {
  const { addMaterial, formatCurrency } = useWorker();
  const [material, setMaterial] = useState({
    name: "",
    cost: "",
    quantity: 1,
    notes: ""
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!material.name || !material.cost) {
      setError("Name and cost are required");
      return;
    }

    try {
      setLoading(true);
      setError("");
      
      await addMaterial({
        job_id: jobId,
        name: material.name,
        cost: parseFloat(material.cost),
        quantity: parseInt(material.quantity),
        notes: material.notes
      });

      onClose();
    } catch (err) {
      setError(err.response?.data?.detail || "Error adding material");
    } finally {
      setLoading(false);
    }
  };

  const totalCost = material.cost && material.quantity ? 
    parseFloat(material.cost) * parseInt(material.quantity) : 0;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
        <div className="px-6 py-4 border-b border-gray-200">
          <h3 className="text-lg font-semibold text-gray-900">Add Material</h3>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md">
              {error}
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Material Name *
            </label>
            <input
              type="text"
              value={material.name}
              onChange={(e) => setMaterial({ ...material, name: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
              placeholder="e.g., Screws, Paint, Timber"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Unit Cost (£) *
              </label>
              <input
                type="number"
                step="0.01"
                min="0"
                value={material.cost}
                onChange={(e) => setMaterial({ ...material, cost: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
                placeholder="0.00"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Quantity
              </label>
              <input
                type="number"
                min="1"
                value={material.quantity}
                onChange={(e) => setMaterial({ ...material, quantity: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
              />
            </div>
          </div>

          {totalCost > 0 && (
            <div className="bg-blue-50 border border-blue-200 p-3 rounded-md">
              <p className="text-blue-800 font-medium">
                Total Cost: {formatCurrency(totalCost)}
              </p>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Notes (Optional)
            </label>
            <textarea
              value={material.notes}
              onChange={(e) => setMaterial({ ...material, notes: e.target.value })}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-red-500"
              placeholder="Additional details, receipt info, etc."
            />
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
                "Add Material"
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default AddMaterial;