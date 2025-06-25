import React, { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useWorker } from "../contexts/WorkerContext";
import ClockInOut from "./ClockInOut";
import AddMaterial from "./AddMaterial";

const WorkerDashboard = () => {
  const { workerId } = useParams();
  const navigate = useNavigate();
  const { 
    workers, 
    jobs, 
    currentWorker, 
    setCurrentWorker, 
    activeTimeEntry, 
    checkActiveTimeEntry,
    formatDate,
    formatDuration
  } = useWorker();

  const [showAddMaterial, setShowAddMaterial] = useState(false);

  useEffect(() => {
    const worker = workers.find(w => w.id === workerId);
    if (worker) {
      setCurrentWorker(worker);
      checkActiveTimeEntry(workerId);
    }
  }, [workerId, workers, setCurrentWorker, checkActiveTimeEntry]);

  const handleLogout = () => {
    setCurrentWorker(null);
    navigate("/");
  };

  const getCurrentJob = () => {
    if (!activeTimeEntry) return null;
    return jobs.find(job => job.id === activeTimeEntry.job_id);
  };

  const currentJob = getCurrentJob();

  if (!currentWorker) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-red-600 mx-auto" style={{borderBottomColor: '#d01f2f'}}></div>
          <p className="mt-4 text-gray-600">Loading...</p>
        </div>
      </div>
    );
  }

  const companyValues = [
    "We Care",
    "We Deliver", 
    "We are Professional",
    "We Celebrate"
  ];

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white shadow-sm border-b border-gray-200" style={{borderBottomColor: '#d01f2f', borderBottomWidth: '3px'}}>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-4">
            <div className="flex items-center space-x-4">
              <img src="/lda-logo.svg" alt="LDA Group" className="h-12 w-12" />
              <div>
                <h1 className="text-2xl font-bold text-gray-900">LDA Group</h1>
                <p className="text-gray-600">Welcome, {currentWorker.name}</p>
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

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Clock In/Out Section */}
          <div className="bg-white rounded-lg shadow-sm p-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-4">Time Tracking</h2>
            <ClockInOut />
          </div>

          {/* Current Job Info */}
          {activeTimeEntry && currentJob && (
            <div className="bg-white rounded-lg shadow-sm p-6">
              <h2 className="text-xl font-semibold text-gray-900 mb-4">Current Job</h2>
              <div className="space-y-3">
                <div>
                  <p className="text-sm text-gray-600">Job Name</p>
                  <p className="font-medium">{currentJob.name}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-600">Client</p>
                  <p className="font-medium">{currentJob.client}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-600">Location</p>
                  <p className="font-medium">{currentJob.location}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-600">Started</p>
                  <p className="font-medium">{formatDate(activeTimeEntry.clock_in)}</p>
                </div>
                <div>
                  <p className="text-sm text-gray-600">Duration</p>
                  <p className="font-medium text-green-600">
                    {formatDuration(Math.floor((new Date() - new Date(activeTimeEntry.clock_in)) / 60000))}
                  </p>
                </div>
              </div>
              
              <div className="mt-6">
                <button
                  onClick={() => setShowAddMaterial(true)}
                  className="w-full text-white py-2 px-4 rounded-md hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 transition-colors"
                  style={{backgroundColor: '#d01f2f'}}
                >
                  Add Materials
                </button>
              </div>
            </div>
          )}

          {/* Instructions */}
          <div className="bg-white rounded-lg shadow-sm p-6 lg:col-span-2">
            <h2 className="text-xl font-semibold text-gray-900 mb-4">Instructions</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="bg-blue-50 p-4 rounded-lg">
                <h3 className="font-medium text-blue-900 mb-2">Clock In</h3>
                <p className="text-blue-800 text-sm">
                  Select a job and click "Clock In" to start tracking your time. 
                  Your GPS location will be recorded for verification.
                </p>
              </div>
              <div className="bg-green-50 p-4 rounded-lg">
                <h3 className="font-medium text-green-900 mb-2">Clock Out</h3>
                <p className="text-green-800 text-sm">
                  Click "Clock Out" when you finish working. 
                  Add any notes about the work completed.
                </p>
              </div>
              <div className="bg-purple-50 p-4 rounded-lg">
                <h3 className="font-medium text-purple-900 mb-2">Add Materials</h3>
                <p className="text-purple-800 text-sm">
                  While clocked in, you can add materials purchased for the job. 
                  Include supplier details and receipt numbers.
                </p>
              </div>
              <div className="bg-orange-50 p-4 rounded-lg">
                <h3 className="font-medium text-orange-900 mb-2">GPS Tracking</h3>
                <p className="text-orange-800 text-sm">
                  Allow location access when prompted. 
                  GPS helps verify you're at the correct job site.
                </p>
              </div>
            </div>
          </div>

          {/* Company Values */}
          <div className="lg:col-span-2">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {companyValues.map((value, index) => (
                <div
                  key={index}
                  className="text-white text-center py-4 px-2 rounded-lg font-bold text-sm md:text-base"
                  style={{backgroundColor: '#d01f2f'}}
                >
                  {value}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Add Material Modal */}
      {showAddMaterial && activeTimeEntry && (
        <AddMaterial 
          jobId={activeTimeEntry.job_id}
          onClose={() => setShowAddMaterial(false)}
        />
      )}
    </div>
  );
};

export default WorkerDashboard;