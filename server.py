import React, { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { useWorker } from "../contexts/WorkerContext";

const emptyLine = () => ({
  description: "",
  quantity: 1,
  unit_cost: 0,
  vat_rate: 20,
  job_section_id: "",
  job_section_name: "",
  cost_category: "Materials",
});

const emptySupplier = {
  name: "",
  contact_name: "",
  orders_email: "",
  accounts_email: "",
  phone: "",
  address: "",
  vat_number: "",
  payment_terms: "30 days",
  notes: "",
};

const statusStyles = {
  draft: "bg-gray-100 text-gray-800",
  pending_approval: "bg-amber-100 text-amber-800",
  approved: "bg-blue-100 text-blue-800",
  sent: "bg-purple-100 text-purple-800",
  materials_assigned: "bg-indigo-100 text-indigo-800",
  part_received: "bg-orange-100 text-orange-800",
  received: "bg-green-100 text-green-800",
  invoiced: "bg-emerald-100 text-emerald-800",
  closed: "bg-slate-200 text-slate-800",
  cancelled: "bg-red-100 text-red-800",
};

const PurchaseOrdersPage = () => {
  const { API, jobs, fetchJobs, formatCurrency } = useWorker();

  const [activeView, setActiveView] = useState("orders");
  const [purchaseOrders, setPurchaseOrders] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [jobFilter, setJobFilter] = useState("");

  const [supplierForm, setSupplierForm] = useState(emptySupplier);
  const [editingSupplierId, setEditingSupplierId] = useState(null);

  const [poForm, setPoForm] = useState({
    supplier_id: "",
    job_id: "",
    division: "",
    delivery_address: "",
    required_date: "",
    notes: "",
    supplier_quote_number: "",
    source_type: "manual",
    source_upload_id: null,
    source_file_name: "",
    extraction_status: "not_required",
    extraction_confidence: "",
    lines: [emptyLine()],
  });
  const [editingPoId, setEditingPoId] = useState(null);

  const [quoteFile, setQuoteFile] = useState(null);
  const [quoteImporting, setQuoteImporting] = useState(false);
  const [quotePreview, setQuotePreview] = useState(null);
  const [quoteDragActive, setQuoteDragActive] = useState(false);
  const [quickSupplierLoading, setQuickSupplierLoading] = useState(false);

  const authHeaders = () => {
    const adminAuth = localStorage.getItem("adminAuth");
    return { Authorization: `Basic ${adminAuth}`, "Content-Type": "application/json" };
  };

  const clearAlerts = () => {
    setMessage("");
    setError("");
  };

  const fetchSuppliers = async () => {
    const response = await axios.get(`${API}/suppliers`, { headers: authHeaders() });
    setSuppliers(response.data || []);
  };

  const fetchPurchaseOrders = async () => {
    const params = new URLSearchParams();
    if (statusFilter) params.append("status", statusFilter);
    if (jobFilter) params.append("job_id", jobFilter);
    const url = params.toString() ? `${API}/purchase-orders?${params}` : `${API}/purchase-orders`;
    const response = await axios.get(url, { headers: authHeaders() });
    setPurchaseOrders(response.data || []);
  };

  const refreshAll = async () => {
    try {
      setLoading(true);
      clearAlerts();
      await Promise.all([fetchSuppliers(), fetchPurchaseOrders()]);
      if (!jobs || jobs.length === 0) await fetchJobs();
    } catch (err) {
      console.error("Purchase order refresh failed", err);
      setError(err.response?.data?.detail || "Could not load purchase order data.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refreshAll();
  }, []);

  useEffect(() => {
    fetchPurchaseOrders().catch((err) => {
      console.error(err);
      setError("Could not refresh purchase orders.");
    });
  }, [statusFilter, jobFilter]);

  const selectedSupplier = useMemo(
    () => suppliers.find((supplier) => supplier.id === poForm.supplier_id),
    [poForm.supplier_id, suppliers]
  );

  const selectedJob = useMemo(
    () => jobs.find((job) => job.id === poForm.job_id),
    [poForm.job_id, jobs]
  );

  const totals = useMemo(() => {
    const net = poForm.lines.reduce((sum, line) => {
      if (line.prices_include_vat && line.source_line_net_total !== undefined && line.source_line_net_total !== null) {
        return sum + (Number(line.source_line_net_total) || 0);
      }
      return sum + (Number(line.quantity) || 0) * (Number(line.unit_cost) || 0);
    }, 0);
    const vat = poForm.lines.reduce((sum, line) => {
      if (line.prices_include_vat && line.source_line_vat_total !== undefined && line.source_line_vat_total !== null) {
        return sum + (Number(line.source_line_vat_total) || 0);
      }
      const lineNet = (Number(line.quantity) || 0) * (Number(line.unit_cost) || 0);
      return sum + lineNet * ((Number(line.vat_rate) || 0) / 100);
    }, 0);
    const gross = poForm.lines.reduce((sum, line) => {
      if (line.prices_include_vat && line.source_line_gross_total !== undefined && line.source_line_gross_total !== null) {
        return sum + (Number(line.source_line_gross_total) || 0);
      }
      const lineNet = (Number(line.quantity) || 0) * (Number(line.unit_cost) || 0);
      return sum + lineNet + lineNet * ((Number(line.vat_rate) || 0) / 100);
    }, 0);
    return { net, vat, gross };
  }, [poForm.lines]);

  const updatePoField = (field, value) => {
    setPoForm((prev) => ({ ...prev, [field]: value }));
  };

  const updatePoLine = (index, field, value) => {
    setPoForm((prev) => ({
      ...prev,
      lines: prev.lines.map((line, i) => {
        if (i !== index) return line;
        const next = { ...line, [field]: value };
        if (["quantity", "unit_cost", "vat_rate"].includes(field)) {
          delete next.source_line_net_total;
          delete next.source_line_vat_total;
          delete next.source_line_gross_total;
          next.prices_include_vat = false;
        }
        return next;
      }),
    }));
  };

  const addPoLine = () => {
    setPoForm((prev) => ({ ...prev, lines: [...prev.lines, emptyLine()] }));
  };

  const removePoLine = (index) => {
    setPoForm((prev) => ({ ...prev, lines: prev.lines.filter((_, i) => i !== index).length ? prev.lines.filter((_, i) => i !== index) : [emptyLine()] }));
  };

  const resetPoForm = () => {
    setEditingPoId(null);
    setPoForm({
      supplier_id: "",
      job_id: "",
      division: "",
      delivery_address: "",
      required_date: "",
      notes: "",
      supplier_quote_number: "",
      source_type: "manual",
      source_upload_id: null,
      source_file_name: "",
      extraction_status: "not_required",
      extraction_confidence: "",
      lines: [emptyLine()],
    });
    setQuoteFile(null);
    setQuotePreview(null);
  };

  const saveSupplier = async (event) => {
    event.preventDefault();
    clearAlerts();
    try {
      setLoading(true);
      if (editingSupplierId) {
        await axios.put(`${API}/suppliers/${editingSupplierId}`, supplierForm, { headers: authHeaders() });
        setMessage("Supplier updated.");
      } else {
        await axios.post(`${API}/suppliers`, supplierForm, { headers: authHeaders() });
        setMessage("Supplier created.");
      }
      setSupplierForm(emptySupplier);
      setEditingSupplierId(null);
      await fetchSuppliers();
    } catch (err) {
      console.error("Supplier save failed", err);
      setError(err.response?.data?.detail || "Could not save supplier.");
    } finally {
      setLoading(false);
    }
  };

  const editSupplier = (supplier) => {
    setEditingSupplierId(supplier.id);
    setSupplierForm({ ...emptySupplier, ...supplier });
    setActiveView("suppliers");
  };

  const deleteSupplier = async (supplierId) => {
    if (!window.confirm("Archive this supplier?")) return;
    clearAlerts();
    try {
      await axios.delete(`${API}/suppliers/${supplierId}`, { headers: authHeaders() });
      setMessage("Supplier archived.");
      await fetchSuppliers();
    } catch (err) {
      console.error(err);
      setError(err.response?.data?.detail || "Could not archive supplier.");
    }
  };

  const savePurchaseOrder = async (event) => {
    event.preventDefault();
    clearAlerts();
    try {
      setLoading(true);
      const payload = {
        ...poForm,
        supplier_name: selectedSupplier?.name || "",
        supplier_email: selectedSupplier?.orders_email || selectedSupplier?.accounts_email || "",
        job_name: selectedJob?.name || "",
        job_number: selectedJob?.job_number || null,
        division: poForm.division || selectedJob?.division || "",
        net_total: totals.net,
        vat_total: totals.vat,
        gross_total: totals.gross,
        lines: poForm.lines.map((line) => ({
          ...line,
          quantity: Number(line.quantity) || 0,
          unit_cost: Number(line.unit_cost) || 0,
          vat_rate: Number(line.vat_rate) || 0,
        })),
      };

      if (editingPoId) {
        await axios.put(`${API}/purchase-orders/${editingPoId}`, payload, { headers: authHeaders() });
        setMessage("Purchase order updated.");
      } else {
        await axios.post(`${API}/purchase-orders`, payload, { headers: authHeaders() });
        setMessage("Draft purchase order created.");
      }

      resetPoForm();
      setActiveView("orders");
      await fetchPurchaseOrders();
    } catch (err) {
      console.error("PO save failed", err);
      setError(err.response?.data?.detail || "Could not save purchase order.");
    } finally {
      setLoading(false);
    }
  };

  const editPurchaseOrder = (po) => {
    setEditingPoId(po.id);
    setPoForm({
      supplier_id: po.supplier_id || "",
      job_id: po.job_id || "",
      division: po.division || "",
      delivery_address: po.delivery_address || "",
      required_date: po.required_date || "",
      notes: po.notes || "",
      supplier_quote_number: po.supplier_quote_number || "",
      source_type: po.source_type || "manual",
      source_upload_id: po.source_upload_id || null,
      source_file_name: po.source_file_name || "",
      extraction_status: po.extraction_status || "not_required",
      extraction_confidence: po.extraction_confidence || "",
      lines: (po.lines && po.lines.length ? po.lines : [emptyLine()]).map((line) => ({ ...emptyLine(), ...line })),
    });
    setActiveView("create");
  };

  const deletePurchaseOrder = async (poId) => {
    if (!window.confirm("Delete this purchase order? This cannot be undone.")) return;
    clearAlerts();
    try {
      await axios.delete(`${API}/purchase-orders/${poId}`, { headers: authHeaders() });
      setMessage("Purchase order deleted.");
      await fetchPurchaseOrders();
    } catch (err) {
      console.error(err);
      setError(err.response?.data?.detail || "Could not delete purchase order.");
    }
  };

  const runPoAction = async (poId, action, successText) => {
    clearAlerts();
    try {
      setLoading(true);
      await axios.post(`${API}/purchase-orders/${poId}/${action}`, {}, { headers: authHeaders() });
      setMessage(successText);
      await fetchPurchaseOrders();
    } catch (err) {
      console.error(err);
      setError(err.response?.data?.detail || `Could not ${action.replace("-", " ")} purchase order.`);
    } finally {
      setLoading(false);
    }
  };

  const downloadPoPdf = async (po) => {
    clearAlerts();
    try {
      const response = await axios.get(`${API}/purchase-orders/${po.id}/pdf`, {
        headers: authHeaders(),
        responseType: "blob",
      });
      const url = window.URL.createObjectURL(new Blob([response.data], { type: "application/pdf" }));
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", `${po.po_number || "purchase_order"}.pdf`);
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error(err);
      setError(err.response?.data?.detail || "Could not download PO PDF.");
    }
  };

  const sendPoEmail = async (po) => {
    const recipient = po.supplier_email || "the supplier email saved against this PO";
    if (!window.confirm(`Email ${po.po_number} to ${recipient}?`)) return;
    await runPoAction(po.id, "send-email", "PO email sent and status updated.");
  };

  const assignMaterials = async (po) => {
    if (!window.confirm(`Assign ${po.po_number} line items as materials against ${po.job_name}?`)) return;
    await runPoAction(po.id, "assign-materials", "PO line items assigned to job materials.");
  };

  const createSupplierFromQuote = async () => {
    if (!quotePreview?.supplier_name) {
      setError("No supplier name was detected from the quote.");
      return;
    }
    clearAlerts();
    try {
      setQuickSupplierLoading(true);
      const response = await axios.post(`${API}/suppliers`, {
        ...emptySupplier,
        name: quotePreview.supplier_name,
        orders_email: quotePreview.supplier_email || "",
        notes: `Created from uploaded quote ${quotePreview.filename || ""}`.trim(),
      }, { headers: authHeaders() });
      await fetchSuppliers();
      updatePoField("supplier_id", response.data?.id || "");
      setMessage(`Supplier ${quotePreview.supplier_name} created and selected.`);
    } catch (err) {
      console.error("Quick supplier create failed", err);
      setError(err.response?.data?.detail || "Could not create supplier from quote.");
    } finally {
      setQuickSupplierLoading(false);
    }
  };

  const handleQuoteDrop = (event) => {
    event.preventDefault();
    setQuoteDragActive(false);
    const file = event.dataTransfer?.files?.[0];
    if (file) setQuoteFile(file);
  };

  const importQuote = async () => {
    if (!quoteFile) {
      setError("Please select a quote file first.");
      return;
    }
    clearAlerts();
    try {
      setQuoteImporting(true);
      const formData = new FormData();
      formData.append("file", quoteFile);
      const query = poForm.job_id ? `?job_id=${encodeURIComponent(poForm.job_id)}` : "";
      const response = await axios.post(`${API}/purchase-orders/import-quote${query}`, formData, {
        headers: { Authorization: `Basic ${localStorage.getItem("adminAuth")}` },
      });
      const data = response.data || {};
      setQuotePreview(data);
      const warningText = data.warnings?.length ? data.warnings.join("\n") : data.warning;
      setPoForm((prev) => ({
        ...prev,
        supplier_id: data.matched_supplier_id || prev.supplier_id,
        supplier_quote_number: data.quote_number || prev.supplier_quote_number,
        source_type: "uploaded_quote",
        source_upload_id: data.upload_id || null,
        source_file_name: data.filename || "",
        extraction_status: "review_required",
        extraction_confidence: data.confidence || "low",
        notes: [prev.notes, warningText].filter(Boolean).join("\n"),
        lines: data.lines && data.lines.length ? data.lines.map((line) => ({ ...emptyLine(), ...line })) : prev.lines,
      }));
      if (data.matched_supplier_id) {
        setMessage(`Quote imported and matched to supplier ${data.matched_supplier_name || ""}. Please review before creating the PO.`);
      } else {
        setMessage("Quote imported. Please review the details before creating the PO.");
      }
    } catch (err) {
      console.error("Quote import failed", err);
      setError(err.response?.data?.detail || "Could not read quote. You can still create the PO manually.");
    } finally {
      setQuoteImporting(false);
    }
  };

  const statusBadge = (status) => (
    <span className={`inline-flex px-2 py-1 rounded-full text-xs font-semibold ${statusStyles[status] || "bg-gray-100 text-gray-800"}`}>
      {(status || "draft").replace(/_/g, " ")}
    </span>
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Purchase Orders</h2>
          <p className="text-sm text-gray-500">Create POs from quotes, email suppliers, and assign materials to jobs.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => { resetPoForm(); setActiveView("create"); }} className="px-4 py-2 rounded-md bg-red-600 text-white text-sm font-semibold hover:bg-red-700">New PO</button>
          <button onClick={() => setActiveView("orders")} className="px-4 py-2 rounded-md bg-slate-900 text-white text-sm font-semibold hover:bg-slate-800">PO List</button>
          <button onClick={() => setActiveView("suppliers")} className="px-4 py-2 rounded-md bg-white border border-slate-300 text-slate-700 text-sm font-semibold hover:bg-slate-50">Suppliers</button>
        </div>
      </div>

      {message && <div className="bg-green-50 border border-green-200 text-green-800 rounded-md p-3 text-sm">{message}</div>}
      {error && <div className="bg-red-50 border border-red-200 text-red-800 rounded-md p-3 text-sm">{typeof error === "string" ? error : JSON.stringify(error)}</div>}

      {activeView === "orders" && (
        <div className="space-y-4">
          <div className="bg-white rounded-lg shadow-sm p-4 grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} className="w-full p-2 border border-gray-300 rounded-md">
                <option value="">All statuses</option>
                {Object.keys(statusStyles).map((status) => <option key={status} value={status}>{status.replace(/_/g, " ")}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Job</label>
              <select value={jobFilter} onChange={(e) => setJobFilter(e.target.value)} className="w-full p-2 border border-gray-300 rounded-md">
                <option value="">All jobs</option>
                {(jobs || []).map((job) => <option key={job.id} value={job.id}>{job.display_name || job.name}</option>)}
              </select>
            </div>
            <button onClick={refreshAll} disabled={loading} className="px-4 py-2 rounded-md bg-slate-900 text-white text-sm font-semibold disabled:opacity-50">Refresh</button>
          </div>

          <div className="bg-white shadow-sm rounded-lg overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">PO</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Supplier</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Job</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Net</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Gross</th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {purchaseOrders.map((po) => (
                    <tr key={po.id}>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <div className="text-sm font-semibold text-gray-900">{po.po_number}</div>
                        <div className="text-xs text-gray-500">Quote: {po.supplier_quote_number || "-"}</div>
                      </td>
                      <td className="px-4 py-3 text-sm text-gray-900">{po.supplier_name || "-"}</td>
                      <td className="px-4 py-3 text-sm text-gray-900">{po.job_name || "-"}</td>
                      <td className="px-4 py-3">{statusBadge(po.status)}</td>
                      <td className="px-4 py-3 text-sm text-gray-900">{formatCurrency(po.net_total)}</td>
                      <td className="px-4 py-3 text-sm text-gray-900">{formatCurrency(po.gross_total)}</td>
                      <td className="px-4 py-3 text-sm">
                        <div className="flex flex-wrap gap-1">
                          <button onClick={() => editPurchaseOrder(po)} className="px-2 py-1 bg-gray-100 rounded text-xs">Edit</button>
                          <button onClick={() => runPoAction(po.id, "approve", "PO approved.")} className="px-2 py-1 bg-blue-50 text-blue-700 rounded text-xs">Approve</button>
                          <button onClick={() => downloadPoPdf(po)} className="px-2 py-1 bg-slate-100 text-slate-800 rounded text-xs">PDF</button>
                          <button onClick={() => sendPoEmail(po)} className="px-2 py-1 bg-purple-50 text-purple-700 rounded text-xs">Email</button>
                          <button onClick={() => assignMaterials(po)} className="px-2 py-1 bg-indigo-50 text-indigo-700 rounded text-xs">Assign Materials</button>
                          <button onClick={() => deletePurchaseOrder(po.id)} className="px-2 py-1 bg-red-50 text-red-700 rounded text-xs">Delete</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {purchaseOrders.length === 0 && (
                    <tr><td colSpan="7" className="px-4 py-8 text-center text-gray-500">No purchase orders found.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {activeView === "create" && (
        <form onSubmit={savePurchaseOrder} className="space-y-6">
          <div className="bg-white rounded-lg shadow-sm p-5">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Create PO from quote</h3>
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-end">
              <div className="lg:col-span-2">
                <label className="block text-sm font-medium text-gray-700 mb-1">Upload supplier quote</label>
                <div
                  onDragOver={(e) => { e.preventDefault(); setQuoteDragActive(true); }}
                  onDragLeave={() => setQuoteDragActive(false)}
                  onDrop={handleQuoteDrop}
                  className={`w-full p-4 border-2 border-dashed rounded-md bg-gray-50 transition ${quoteDragActive ? "border-red-500 bg-red-50" : "border-gray-300"}`}
                >
                  <input
                    id="quote-upload"
                    type="file"
                    accept=".pdf,.docx,.txt,.csv,.jpg,.jpeg,.png"
                    onChange={(e) => setQuoteFile(e.target.files?.[0] || null)}
                    className="w-full p-2 border border-gray-200 rounded-md bg-white"
                  />
                  <p className="text-xs text-gray-500 mt-2">Drag and drop or browse. Digital PDFs, Word docs, TXT and CSV can be read. Scanned images can be attached, but OCR is a later upgrade.</p>
                  {quoteFile && <p className="text-xs text-slate-700 mt-2 font-semibold">Selected: {quoteFile.name}</p>}
                </div>
              </div>
              <button type="button" onClick={importQuote} disabled={quoteImporting || !quoteFile} className="px-4 py-2 rounded-md bg-slate-900 text-white text-sm font-semibold disabled:opacity-50">
                {quoteImporting ? "Reading Quote..." : "Read Quote"}
              </button>
            </div>
            {quotePreview && (
              <div className="mt-4 bg-blue-50 border border-blue-200 rounded-md p-4 text-sm text-blue-950 space-y-3">
                <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
                  <div>
                    <div className="font-semibold text-blue-950">Quote import review</div>
                    <div>Confidence: <span className="font-semibold">{quotePreview.confidence || "low"}</span> ({quotePreview.confidence_score || 0}/100)</div>
                    <div>Lines detected: <span className="font-semibold">{quotePreview.lines?.length || 0}</span></div>
                  </div>
                  {quotePreview.supplier_name && !quotePreview.matched_supplier_id && (
                    <div className="bg-white border border-blue-300 rounded-md p-3 max-w-md">
                      <div className="text-xs font-semibold text-blue-950 mb-1">Supplier not recognised</div>
                      <div className="text-xs text-blue-900 mb-2">Detected: {quotePreview.supplier_name}{quotePreview.supplier_email ? ` (${quotePreview.supplier_email})` : ""}</div>
                      <button type="button" onClick={createSupplierFromQuote} disabled={quickSupplierLoading} className="px-3 py-2 rounded-md bg-blue-700 text-white text-xs font-semibold disabled:opacity-50">
                        {quickSupplierLoading ? "Creating supplier..." : "Create supplier from quote and select it"}
                      </button>
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <div className="bg-white/70 rounded p-2"><span className="font-semibold">Supplier:</span><br />{quotePreview.matched_supplier_name || quotePreview.supplier_name || "Not found"}{quotePreview.supplier_email ? ` (${quotePreview.supplier_email})` : ""}</div>
                  <div className="bg-white/70 rounded p-2"><span className="font-semibold">Quote ref/date:</span><br />{quotePreview.quote_number || "No ref"}{quotePreview.quote_date ? ` / ${quotePreview.quote_date}` : ""}</div>
                  <div className="bg-white/70 rounded p-2"><span className="font-semibold">Quote totals:</span><br />Net {formatCurrency(quotePreview.quote_net_total || 0)} / VAT {formatCurrency(quotePreview.quote_vat_total || 0)} / Gross {formatCurrency(quotePreview.quote_gross_total || 0)}<br /><span className="text-xs">VAT mode: {quotePreview.vat_inclusive ? "amounts include VAT" : "amounts treated as net"}</span></div>
                </div>

                {quotePreview.warnings?.length > 0 && (
                  <div className="bg-amber-50 border border-amber-200 rounded p-2 text-amber-900">
                    <div className="font-semibold mb-1">Needs review</div>
                    <ul className="list-disc ml-5 space-y-1">
                      {quotePreview.warnings.map((warning, index) => <li key={index}>{warning}</li>)}
                    </ul>
                  </div>
                )}

                <details className="bg-white/70 rounded p-2">
                  <summary className="cursor-pointer font-semibold">Extracted text preview</summary>
                  <pre className="mt-2 whitespace-pre-wrap text-xs text-slate-700 max-h-48 overflow-y-auto">{quotePreview.extracted_text_preview || "No readable text extracted."}</pre>
                </details>
              </div>
            )}
          </div>

          <div className="bg-white rounded-lg shadow-sm p-5">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">PO Details</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Supplier *</label>
                <select required value={poForm.supplier_id} onChange={(e) => updatePoField("supplier_id", e.target.value)} className="w-full p-2 border border-gray-300 rounded-md">
                  <option value="">Select supplier</option>
                  {suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Job *</label>
                <select required value={poForm.job_id} onChange={(e) => updatePoField("job_id", e.target.value)} className="w-full p-2 border border-gray-300 rounded-md">
                  <option value="">Select job</option>
                  {(jobs || []).map((job) => <option key={job.id} value={job.id}>{job.display_name || job.name}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Supplier quote ref</label>
                <input value={poForm.supplier_quote_number} onChange={(e) => updatePoField("supplier_quote_number", e.target.value)} className="w-full p-2 border border-gray-300 rounded-md" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Required date</label>
                <input type="date" value={poForm.required_date} onChange={(e) => updatePoField("required_date", e.target.value)} className="w-full p-2 border border-gray-300 rounded-md" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Division</label>
                <input value={poForm.division} onChange={(e) => updatePoField("division", e.target.value)} placeholder={selectedJob?.division || ""} className="w-full p-2 border border-gray-300 rounded-md" />
              </div>
              <div className="md:col-span-2 lg:col-span-1">
                <label className="block text-sm font-medium text-gray-700 mb-1">Delivery address</label>
                <input value={poForm.delivery_address} onChange={(e) => updatePoField("delivery_address", e.target.value)} placeholder={selectedJob?.location || ""} className="w-full p-2 border border-gray-300 rounded-md" />
              </div>
              <div className="md:col-span-2 lg:col-span-3">
                <label className="block text-sm font-medium text-gray-700 mb-1">Notes</label>
                <textarea rows="3" value={poForm.notes} onChange={(e) => updatePoField("notes", e.target.value)} className="w-full p-2 border border-gray-300 rounded-md" />
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow-sm p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-900">Line Items</h3>
              <button type="button" onClick={addPoLine} className="px-3 py-2 rounded bg-slate-900 text-white text-sm">Add Line</button>
            </div>
            <div className="space-y-3">
              {poForm.lines.map((line, index) => {
                const lineNet = (Number(line.quantity) || 0) * (Number(line.unit_cost) || 0);
                return (
                  <div key={index} className="grid grid-cols-1 lg:grid-cols-12 gap-3 items-end border border-gray-200 rounded-md p-3">
                    <div className="lg:col-span-5">
                      <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
                      <input required value={line.description} onChange={(e) => updatePoLine(index, "description", e.target.value)} className="w-full p-2 border border-gray-300 rounded-md" />
                    </div>
                    <div className="lg:col-span-1">
                      <label className="block text-xs font-medium text-gray-600 mb-1">Qty</label>
                      <input type="number" step="0.01" min="0" value={line.quantity} onChange={(e) => updatePoLine(index, "quantity", e.target.value)} className="w-full p-2 border border-gray-300 rounded-md" />
                    </div>
                    <div className="lg:col-span-2">
                      <label className="block text-xs font-medium text-gray-600 mb-1">Unit cost</label>
                      <input type="number" step="0.01" min="0" value={line.unit_cost} onChange={(e) => updatePoLine(index, "unit_cost", e.target.value)} className="w-full p-2 border border-gray-300 rounded-md" />
                    </div>
                    <div className="lg:col-span-1">
                      <label className="block text-xs font-medium text-gray-600 mb-1">VAT %</label>
                      <input type="number" step="0.01" min="0" value={line.vat_rate} onChange={(e) => updatePoLine(index, "vat_rate", e.target.value)} className="w-full p-2 border border-gray-300 rounded-md" />
                    </div>
                    <div className="lg:col-span-2">
                      <label className="block text-xs font-medium text-gray-600 mb-1">Line net</label>
                      <div className="p-2 bg-gray-50 rounded-md text-sm font-semibold">{formatCurrency(lineNet)}</div>
                    </div>
                    <button type="button" onClick={() => removePoLine(index)} className="lg:col-span-1 px-2 py-2 rounded bg-red-50 text-red-700 text-sm">Remove</button>
                  </div>
                );
              })}
            </div>
            <div className="mt-4 flex flex-col items-end gap-1 text-sm">
              <div>Net: <span className="font-semibold">{formatCurrency(totals.net)}</span></div>
              <div>VAT: <span className="font-semibold">{formatCurrency(totals.vat)}</span></div>
              <div className="text-lg">Gross: <span className="font-bold">{formatCurrency(totals.gross)}</span></div>
            </div>
          </div>

          <div className="flex justify-end gap-3">
            <button type="button" onClick={() => { resetPoForm(); setActiveView("orders"); }} className="px-4 py-2 rounded-md border border-gray-300 text-gray-700">Cancel</button>
            <button type="submit" disabled={loading} className="px-5 py-2 rounded-md bg-red-600 text-white font-semibold disabled:opacity-50">{editingPoId ? "Update PO" : "Create Draft PO"}</button>
          </div>
        </form>
      )}

      {activeView === "suppliers" && (
        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <form onSubmit={saveSupplier} className="bg-white rounded-lg shadow-sm p-5 space-y-4">
            <h3 className="text-lg font-semibold text-gray-900">{editingSupplierId ? "Edit Supplier" : "Add Supplier"}</h3>
            <input required placeholder="Supplier name" value={supplierForm.name} onChange={(e) => setSupplierForm({ ...supplierForm, name: e.target.value })} className="w-full p-2 border border-gray-300 rounded-md" />
            <input placeholder="Contact name" value={supplierForm.contact_name} onChange={(e) => setSupplierForm({ ...supplierForm, contact_name: e.target.value })} className="w-full p-2 border border-gray-300 rounded-md" />
            <input type="email" placeholder="Orders email" value={supplierForm.orders_email} onChange={(e) => setSupplierForm({ ...supplierForm, orders_email: e.target.value })} className="w-full p-2 border border-gray-300 rounded-md" />
            <input type="email" placeholder="Accounts email" value={supplierForm.accounts_email} onChange={(e) => setSupplierForm({ ...supplierForm, accounts_email: e.target.value })} className="w-full p-2 border border-gray-300 rounded-md" />
            <input placeholder="Phone" value={supplierForm.phone} onChange={(e) => setSupplierForm({ ...supplierForm, phone: e.target.value })} className="w-full p-2 border border-gray-300 rounded-md" />
            <textarea rows="3" placeholder="Address" value={supplierForm.address} onChange={(e) => setSupplierForm({ ...supplierForm, address: e.target.value })} className="w-full p-2 border border-gray-300 rounded-md" />
            <input placeholder="VAT number" value={supplierForm.vat_number} onChange={(e) => setSupplierForm({ ...supplierForm, vat_number: e.target.value })} className="w-full p-2 border border-gray-300 rounded-md" />
            <input placeholder="Payment terms" value={supplierForm.payment_terms} onChange={(e) => setSupplierForm({ ...supplierForm, payment_terms: e.target.value })} className="w-full p-2 border border-gray-300 rounded-md" />
            <textarea rows="3" placeholder="Notes" value={supplierForm.notes} onChange={(e) => setSupplierForm({ ...supplierForm, notes: e.target.value })} className="w-full p-2 border border-gray-300 rounded-md" />
            <div className="flex gap-2">
              <button type="submit" className="px-4 py-2 rounded-md bg-red-600 text-white font-semibold">{editingSupplierId ? "Update" : "Create"}</button>
              {editingSupplierId && <button type="button" onClick={() => { setEditingSupplierId(null); setSupplierForm(emptySupplier); }} className="px-4 py-2 rounded-md border border-gray-300">Cancel</button>}
            </div>
          </form>

          <div className="xl:col-span-2 bg-white rounded-lg shadow-sm overflow-hidden">
            <div className="p-5 border-b border-gray-200"><h3 className="text-lg font-semibold text-gray-900">Suppliers</h3></div>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50"><tr><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Supplier</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Email</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Phone</th><th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th></tr></thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {suppliers.map((supplier) => (
                    <tr key={supplier.id}>
                      <td className="px-4 py-3 text-sm font-medium text-gray-900">{supplier.name}</td>
                      <td className="px-4 py-3 text-sm text-gray-700">{supplier.orders_email || supplier.accounts_email || "-"}</td>
                      <td className="px-4 py-3 text-sm text-gray-700">{supplier.phone || "-"}</td>
                      <td className="px-4 py-3 text-sm"><div className="flex gap-2"><button onClick={() => editSupplier(supplier)} className="px-2 py-1 bg-gray-100 rounded text-xs">Edit</button><button onClick={() => deleteSupplier(supplier.id)} className="px-2 py-1 bg-red-50 text-red-700 rounded text-xs">Archive</button></div></td>
                    </tr>
                  ))}
                  {suppliers.length === 0 && <tr><td colSpan="4" className="px-4 py-8 text-center text-gray-500">No suppliers found.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default PurchaseOrdersPage;
