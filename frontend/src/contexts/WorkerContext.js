import React, { createContext, useContext, useState, useEffect } from "react";
import axios from "axios";

const WorkerContext = createContext();

export const useWorker = () => {
  const context = useContext(WorkerContext);
  if (!context) {
    throw new Error("useWorker must be used within a WorkerProvider");
  }
  return context;
};

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

export const WorkerProvider = ({ children }) => {
  const [workers, setWorkers] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [currentWorker, setCurrentWorker] = useState(null);
  const [activeTimeEntry, setActiveTimeEntry] = useState(null);
  const [loading, setLoading] = useState(false);

  // Fetch workers
  const fetchWorkers = async () => {
    try {
      const response = await axios.get(`${API}/workers`);
      setWorkers(response.data);
    } catch (error) {
      console.error("Error fetching workers:", error);
    }
  };

  // Fetch jobs
  const fetchJobs = async () => {
    try {
      const response = await axios.get(`${API}/jobs`);
      setJobs(response.data);
    } catch (error) {
      console.error("Error fetching jobs:", error);
    }
  };

  // Get current position
  const getCurrentPosition = () => {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) {
        reject(new Error("Geolocation is not supported"));
        return;
      }

      navigator.geolocation.getCurrentPosition(
        (position) => {
          resolve({
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy: position.coords.accuracy,
          });
        },
        (error) => {
          console.warn("GPS error:", error);
          resolve(null); // Don't fail if GPS is not available
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
      );
    });
  };

  // Clock in
  const clockIn = async (workerId, jobId, notes = "") => {
    try {
      setLoading(true);
      const gpsLocation = await getCurrentPosition();
      
      const response = await axios.post(`${API}/time-entries/clock-in`, {
        worker_id: workerId,
        job_id: jobId,
        gps_location: gpsLocation,
        notes: notes,
      });

      setActiveTimeEntry(response.data);
      return response.data;
    } catch (error) {
      console.error("Error clocking in:", error);
      throw error;
    } finally {
      setLoading(false);
    }
  };

  // Clock out
  const clockOut = async (entryId, notes = "") => {
    try {
      setLoading(true);
      const gpsLocation = await getCurrentPosition();
      
      const response = await axios.put(`${API}/time-entries/${entryId}/clock-out`, {
        gps_location: gpsLocation,
        notes: notes,
      });

      setActiveTimeEntry(null);
      return response.data;
    } catch (error) {
      console.error("Error clocking out:", error);
      throw error;
    } finally {
      setLoading(false);
    }
  };

  // Check for active time entry
  const checkActiveTimeEntry = async (workerId) => {
    try {
      const response = await axios.get(`${API}/workers/${workerId}/active-entry`);
      setActiveTimeEntry(response.data.active_entry);
      return response.data.active_entry;
    } catch (error) {
      console.error("Error checking active time entry:", error);
      return null;
    }
  };

  // Add material
  const addMaterial = async (materialData) => {
    try {
      const response = await axios.post(`${API}/materials`, materialData);
      return response.data;
    } catch (error) {
      console.error("Error adding material:", error);
      throw error;
    }
  };

  // Get materials for job
  const getMaterialsForJob = async (jobId) => {
    try {
      const response = await axios.get(`${API}/materials?job_id=${jobId}`);
      return response.data;
    } catch (error) {
      console.error("Error fetching materials:", error);
      return [];
    }
  };

  // Format currency
  const formatCurrency = (amount) => {
    return new Intl.NumberFormat('en-GB', {
      style: 'currency',
      currency: 'GBP'
    }).format(amount);
  };

  // Format date
  const formatDate = (date) => {
    return new Date(date).toLocaleDateString('en-GB', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  // Format duration
  const formatDuration = (minutes) => {
    const hours = Math.floor(minutes / 60);
    const mins = minutes % 60;
    return `${hours}h ${mins}m`;
  };

  useEffect(() => {
    fetchWorkers();
    fetchJobs();
  }, []);

  const value = {
    workers,
    jobs,
    currentWorker,
    setCurrentWorker,
    activeTimeEntry,
    setActiveTimeEntry,
    loading,
    fetchWorkers,
    fetchJobs,
    clockIn,
    clockOut,
    checkActiveTimeEntry,
    addMaterial,
    getMaterialsForJob,
    formatCurrency,
    formatDate,
    formatDuration,
    API,
  };

  return (
    <WorkerContext.Provider value={value}>
      {children}
    </WorkerContext.Provider>
  );
};