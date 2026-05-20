--- server (9).py
+++ server_patched_po_approval_callback.py
@@ -625,6 +625,18 @@
     net_total: Optional[float] = None
     vat_total: Optional[float] = None
     gross_total: Optional[float] = None
+
+class PurchaseOrderBulkDeleteRequest(BaseModel):
+    po_ids: List[str]
+
+class PurchaseOrderApprovalResponseRequest(BaseModel):
+    secret: str = ""
+    decision: str = ""  # Approve / Reject / Approved / Rejected
+    selected_option: str = ""  # Power Automate Send email with options response
+    responder_name: str = ""
+    responder_email: str = ""
+    comments: str = ""
+    reason: str = ""
 
 class AdminLogin(BaseModel):
     username: str
@@ -6397,11 +6409,54 @@
     return {"matched_supplier_id": None, "matched_supplier_name": "", "match_score": best_score if best_match else 0}
 
 
+def po_company_details() -> Dict[str, Any]:
+    """Company details shown on PO PDFs. Override these with Render env vars if needed."""
+    address_lines = os.environ.get(
+        "PO_COMPANY_ADDRESS_LINES",
+        "LDA Group Building Services Ltd|Newcastle upon Tyne|United Kingdom",
+    )
+    return {
+        "name": os.environ.get("PO_COMPANY_NAME", "LDA Group Building Services Ltd"),
+        "address_lines": [line.strip() for line in address_lines.split("|") if line.strip()],
+        "phone": os.environ.get("PO_COMPANY_PHONE", ""),
+        "email": os.environ.get("PO_COMPANY_EMAIL", "info@ldagroup.co.uk"),
+        "website": os.environ.get("PO_COMPANY_WEBSITE", "www.ldagroup.co.uk"),
+        "vat_number": os.environ.get("PO_COMPANY_VAT_NUMBER", ""),
+        "company_number": os.environ.get("PO_COMPANY_NUMBER", ""),
+        "logo_url": os.environ.get("PO_COMPANY_LOGO_URL", "https://ldagroup.co.uk/wp-content/uploads/2022/01/lda-group-200x200.png"),
+    }
+
+
+def po_pdf_escape(value: Any) -> str:
+    from xml.sax.saxutils import escape
+    return escape(str(value or ""))
+
+
+def get_po_logo_flowable(width_cm: float = 2.2):
+    """Return a ReportLab image flowable for the LDA logo, or None if unavailable."""
+    try:
+        from reportlab.lib.units import cm
+        from reportlab.platypus import Image
+        details = po_company_details()
+        logo_url = details.get("logo_url")
+        if not logo_url:
+            return None
+        response = requests.get(logo_url, timeout=8)
+        response.raise_for_status()
+        image = Image(io.BytesIO(response.content))
+        image.drawWidth = width_cm * cm
+        image.drawHeight = width_cm * cm
+        return image
+    except Exception as exc:
+        logger.warning("Could not load PO logo for PDF: %s", exc)
+        return None
+
+
 def generate_purchase_order_pdf_bytes(po: Dict[str, Any]) -> bytes:
     try:
         from reportlab.lib import colors
         from reportlab.lib.pagesizes import A4
-        from reportlab.lib.styles import getSampleStyleSheet
+        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
         from reportlab.lib.units import cm
         from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
     except Exception as exc:
@@ -6409,28 +6464,69 @@
         raise HTTPException(status_code=500, detail="PDF generation is not available on this server. Check reportlab is installed.")
 
     buffer = io.BytesIO()
-    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.2*cm, leftMargin=1.2*cm, topMargin=1.2*cm, bottomMargin=1.2*cm)
+    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=1.2*cm, leftMargin=1.2*cm, topMargin=1.0*cm, bottomMargin=1.0*cm)
     styles = getSampleStyleSheet()
+    styles.add(ParagraphStyle(name="SmallMuted", parent=styles["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor("#475569")))
+    styles.add(ParagraphStyle(name="RightTitle", parent=styles["Title"], alignment=2, fontSize=18, leading=22, textColor=colors.HexColor("#111827")))
     story = []
 
-    story.append(Paragraph("LDA Group - Purchase Order", styles["Title"]))
-    story.append(Paragraph(f"<b>PO Number:</b> {po.get('po_number', '')}", styles["Normal"]))
-    story.append(Paragraph(f"<b>Status:</b> {po.get('status', '').replace('_', ' ').title()}", styles["Normal"]))
-    story.append(Paragraph(f"<b>Date:</b> {get_uk_time().strftime('%d/%m/%Y')}", styles["Normal"]))
+    company = po_company_details()
+    company_lines = [f"<b>{po_pdf_escape(company.get('name'))}</b>"]
+    company_lines.extend(po_pdf_escape(line) for line in company.get("address_lines", []))
+    contact_bits = [bit for bit in [company.get("phone"), company.get("email"), company.get("website")] if bit]
+    if contact_bits:
+        company_lines.append(po_pdf_escape(" | ".join(contact_bits)))
+    reg_bits = []
+    if company.get("company_number"):
+        reg_bits.append(f"Company No: {company.get('company_number')}")
+    if company.get("vat_number"):
+        reg_bits.append(f"VAT No: {company.get('vat_number')}")
+    if reg_bits:
+        company_lines.append(po_pdf_escape(" | ".join(reg_bits)))
+
+    logo = get_po_logo_flowable()
+    header_left = logo if logo else Paragraph(f"<b>{po_pdf_escape(company.get('name'))}</b>", styles["Heading2"])
+    header_right = Paragraph(
+        f"<b>PURCHASE ORDER</b><br/><font size='10'>PO Number: {po_pdf_escape(po.get('po_number', ''))}</font><br/>"
+        f"<font size='9'>Status: {po_pdf_escape(str(po.get('status', 'draft')).replace('_', ' ').title())}</font><br/>"
+        f"<font size='9'>Date: {get_uk_time().strftime('%d/%m/%Y')}</font>",
+        styles["RightTitle"],
+    )
+    header_table = Table([[header_left, header_right]], colWidths=[6.5*cm, 11.5*cm])
+    header_table.setStyle(TableStyle([
+        ("VALIGN", (0, 0), (-1, -1), "TOP"),
+        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
+        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
+    ]))
+    story.append(header_table)
+    story.append(Paragraph("<br/>".join(company_lines), styles["SmallMuted"]))
     story.append(Spacer(1, 0.35*cm))
+
+    supplier_lines = [po_pdf_escape(po.get("supplier_name", ""))]
+    if po.get("supplier_email"):
+        supplier_lines.append(po_pdf_escape(po.get("supplier_email")))
+    if po.get("supplier_address"):
+        supplier_lines.append(po_pdf_escape(po.get("supplier_address")))
+
+    job_lines = [po_pdf_escape(po.get("job_name", ""))]
+    if po.get("delivery_address"):
+        job_lines.append(po_pdf_escape(po.get("delivery_address")))
 
     detail_data = [
         [Paragraph("<b>Supplier</b>", styles["BodyText"]), Paragraph("<b>Job / Delivery</b>", styles["BodyText"])],
         [
-            Paragraph(f"{po.get('supplier_name', '')}<br/>{po.get('supplier_email', '')}", styles["BodyText"]),
-            Paragraph(f"{po.get('job_name', '')}<br/>{po.get('delivery_address') or ''}", styles["BodyText"]),
+            Paragraph("<br/>".join(supplier_lines) or "-", styles["BodyText"]),
+            Paragraph("<br/>".join(job_lines) or "-", styles["BodyText"]),
         ],
-        [Paragraph(f"<b>Supplier Quote Ref:</b> {po.get('supplier_quote_number') or '-'}", styles["BodyText"]), Paragraph(f"<b>Required Date:</b> {format_uk_date_only(po.get('required_date'))}", styles["BodyText"])],
+        [
+            Paragraph(f"<b>Supplier Quote Ref:</b> {po_pdf_escape(po.get('supplier_quote_number') or '-')}", styles["BodyText"]),
+            Paragraph(f"<b>Required Date:</b> {po_pdf_escape(format_uk_date_only(po.get('required_date')))}", styles["BodyText"]),
+        ],
     ]
     detail_table = Table(detail_data, colWidths=[9*cm, 9*cm])
     detail_table.setStyle(TableStyle([
-        ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
-        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
+        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
+        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
         ("VALIGN", (0, 0), (-1, -1), "TOP"),
         ("PADDING", (0, 0), (-1, -1), 6),
     ]))
@@ -6439,26 +6535,32 @@
 
     table_data = [["Description", "Qty", "Unit", "VAT %", "Net", "VAT", "Gross"]]
     for line in po.get("lines", []):
+        qty = finance_material_to_float(line.get("quantity"), 0.0)
+        unit_cost = finance_material_to_float(line.get("unit_cost"), 0.0)
+        vat_rate = finance_material_to_float(line.get("vat_rate"), 0.0)
+        net_total = finance_material_to_float(line.get("net_total"), qty * unit_cost)
+        vat_total = finance_material_to_float(line.get("vat_total"), net_total * vat_rate / 100)
+        gross_total = finance_material_to_float(line.get("gross_total"), net_total + vat_total)
         table_data.append([
-            Paragraph(str(line.get("description", "")), styles["BodyText"]),
-            f"{line.get('quantity', 0):g}",
-            f"£{line.get('unit_cost', 0):,.2f}",
-            f"{line.get('vat_rate', 0):g}%",
-            f"£{line.get('net_total', 0):,.2f}",
-            f"£{line.get('vat_total', 0):,.2f}",
-            f"£{line.get('gross_total', 0):,.2f}",
+            Paragraph(po_pdf_escape(line.get("description", "")), styles["BodyText"]),
+            f"{qty:g}",
+            f"£{unit_cost:,.2f}",
+            f"{vat_rate:g}%",
+            f"£{net_total:,.2f}",
+            f"£{vat_total:,.2f}",
+            f"£{gross_total:,.2f}",
         ])
     table_data.extend([
-        ["", "", "", "", "Net", "", f"£{po.get('net_total', 0):,.2f}"],
-        ["", "", "", "", "VAT", "", f"£{po.get('vat_total', 0):,.2f}"],
-        ["", "", "", "", "Gross", "", f"£{po.get('gross_total', 0):,.2f}"],
+        ["", "", "", "", "Net", "", f"£{finance_material_to_float(po.get('net_total')):,.2f}"],
+        ["", "", "", "", "VAT", "", f"£{finance_material_to_float(po.get('vat_total')):,.2f}"],
+        ["", "", "", "", "Gross", "", f"£{finance_material_to_float(po.get('gross_total')):,.2f}"],
     ])
     line_table = Table(table_data, colWidths=[7*cm, 1.3*cm, 2*cm, 1.5*cm, 2*cm, 2*cm, 2.2*cm], repeatRows=1)
     line_table.setStyle(TableStyle([
         ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d01f2f")),
         ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
         ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
-        ("GRID", (0, 0), (-1, -1), 0.35, colors.grey),
+        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
         ("VALIGN", (0, 0), (-1, -1), "TOP"),
         ("FONTSIZE", (0, 0), (-1, -1), 8),
         ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
@@ -6470,7 +6572,7 @@
     if po.get("notes"):
         story.append(Spacer(1, 0.45*cm))
         story.append(Paragraph("<b>Notes</b>", styles["Heading3"]))
-        story.append(Paragraph(str(po.get("notes", "")).replace("\n", "<br/>"), styles["BodyText"]))
+        story.append(Paragraph(po_pdf_escape(po.get("notes", "")).replace("\n", "<br/>"), styles["BodyText"]))
 
     story.append(Spacer(1, 0.45*cm))
     story.append(Paragraph("Please confirm receipt and advise expected delivery date.", styles["Normal"]))
@@ -6478,6 +6580,66 @@
     buffer.seek(0)
     return buffer.getvalue()
 
+
+def generate_purchase_orders_export_pdf_bytes(purchase_orders: List[Dict[str, Any]], title: str = "Purchase Orders Export") -> bytes:
+    try:
+        from reportlab.lib import colors
+        from reportlab.lib.pagesizes import A4, landscape
+        from reportlab.lib.styles import getSampleStyleSheet
+        from reportlab.lib.units import cm
+        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
+    except Exception as exc:
+        logger.error("PO export PDF dependency error: %s", exc)
+        raise HTTPException(status_code=500, detail="PDF generation is not available on this server. Check reportlab is installed.")
+
+    buffer = io.BytesIO()
+    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=1.0*cm, leftMargin=1.0*cm, topMargin=1.0*cm, bottomMargin=1.0*cm)
+    styles = getSampleStyleSheet()
+    story = []
+    company = po_company_details()
+    logo = get_po_logo_flowable(width_cm=1.6)
+    heading = Paragraph(f"<b>{po_pdf_escape(title)}</b><br/><font size='9'>{po_pdf_escape(company.get('name'))} | Generated {get_uk_time().strftime('%d/%m/%Y %H:%M')}</font>", styles["Title"])
+    header = Table([[logo or "", heading]], colWidths=[2.4*cm, 24*cm])
+    header.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
+    story.append(header)
+    story.append(Spacer(1, 0.3*cm))
+
+    totals = {
+        "net": sum(finance_material_to_float(po.get("net_total")) for po in purchase_orders),
+        "vat": sum(finance_material_to_float(po.get("vat_total")) for po in purchase_orders),
+        "gross": sum(finance_material_to_float(po.get("gross_total")) for po in purchase_orders),
+    }
+    story.append(Paragraph(f"<b>POs:</b> {len(purchase_orders)} &nbsp;&nbsp; <b>Net:</b> £{totals['net']:,.2f} &nbsp;&nbsp; <b>VAT:</b> £{totals['vat']:,.2f} &nbsp;&nbsp; <b>Gross:</b> £{totals['gross']:,.2f}", styles["Normal"]))
+    story.append(Spacer(1, 0.25*cm))
+
+    table_data = [["PO", "Date", "Supplier", "Job", "Required", "Status", "Net", "VAT", "Gross"]]
+    for po in purchase_orders:
+        created = finance_material_iso(po.get("created_at")) or ""
+        table_data.append([
+            po_pdf_escape(po.get("po_number")),
+            created,
+            Paragraph(po_pdf_escape(po.get("supplier_name") or "-"), styles["BodyText"]),
+            Paragraph(po_pdf_escape(po.get("job_name") or "-"), styles["BodyText"]),
+            format_uk_date_only(po.get("required_date")),
+            po_pdf_escape(str(po.get("status") or "draft").replace("_", " ").title()),
+            f"£{finance_material_to_float(po.get('net_total')):,.2f}",
+            f"£{finance_material_to_float(po.get('vat_total')):,.2f}",
+            f"£{finance_material_to_float(po.get('gross_total')):,.2f}",
+        ])
+    table = Table(table_data, colWidths=[3*cm, 2.3*cm, 4.2*cm, 5.2*cm, 2.3*cm, 3.0*cm, 2.2*cm, 2.2*cm, 2.3*cm], repeatRows=1)
+    table.setStyle(TableStyle([
+        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#111827")),
+        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
+        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
+        ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#cbd5e1")),
+        ("FONTSIZE", (0,0), (-1,-1), 7),
+        ("VALIGN", (0,0), (-1,-1), "TOP"),
+        ("ALIGN", (6,1), (-1,-1), "RIGHT"),
+    ]))
+    story.append(table)
+    doc.build(story)
+    buffer.seek(0)
+    return buffer.getvalue()
 
 @api_router.get("/suppliers")
 async def get_suppliers(include_archived: bool = Query(False), admin: str = Depends(verify_admin)):
@@ -6731,6 +6893,324 @@
     return purchase_orders
 
 
+def parse_po_id_list(ids: Optional[str] = None, po_ids: Optional[List[str]] = None) -> List[str]:
+    values: List[str] = []
+    if ids:
+        values.extend([item.strip() for item in str(ids).split(",") if item.strip()])
+    if po_ids:
+        values.extend([str(item).strip() for item in po_ids if str(item).strip()])
+    # Preserve order but remove duplicates.
+    seen = set()
+    cleaned = []
+    for value in values:
+        if value not in seen:
+            seen.add(value)
+            cleaned.append(value)
+    return cleaned
+
+
+async def find_purchase_orders_for_export(
+    status: Optional[str] = None,
+    job_id: Optional[str] = None,
+    supplier_id: Optional[str] = None,
+    ids: Optional[str] = None,
+    include_cancelled: bool = True,
+) -> List[Dict[str, Any]]:
+    filter_dict: Dict[str, Any] = {}
+    selected_ids = parse_po_id_list(ids)
+    if selected_ids:
+        filter_dict["id"] = {"$in": selected_ids}
+    else:
+        if status:
+            filter_dict["status"] = status
+        elif not include_cancelled:
+            filter_dict["status"] = {"$ne": "cancelled"}
+        if job_id:
+            filter_dict["job_id"] = job_id
+        if supplier_id:
+            filter_dict["supplier_id"] = supplier_id
+
+    purchase_orders = await db.purchase_orders.find(filter_dict, {"_id": 0}).sort("created_at", -1).to_list(10000)
+    if selected_ids:
+        order = {po_id: index for index, po_id in enumerate(selected_ids)}
+        purchase_orders.sort(key=lambda po: order.get(po.get("id"), 999999))
+    return purchase_orders
+
+
+@api_router.get("/purchase-orders/export.csv")
+async def export_purchase_orders_csv(
+    status: Optional[str] = Query(None),
+    job_id: Optional[str] = Query(None),
+    supplier_id: Optional[str] = Query(None),
+    ids: Optional[str] = Query(None),
+    include_cancelled: bool = Query(True),
+    admin: str = Depends(verify_admin),
+):
+    purchase_orders = await find_purchase_orders_for_export(status, job_id, supplier_id, ids, include_cancelled)
+    output = io.StringIO()
+    writer = csv.writer(output)
+    writer.writerow(["LDA Group - Purchase Orders Export"])
+    writer.writerow(["Generated", get_uk_time().strftime("%d/%m/%Y %H:%M")])
+    writer.writerow([])
+    writer.writerow([
+        "PO Number", "Created", "Required Date", "Supplier", "Supplier Email", "Job", "Job Number", "Division",
+        "Status", "Quote Ref", "Line Description", "Quantity", "Unit Cost", "VAT Rate", "Line Net", "Line VAT", "Line Gross",
+        "PO Net", "PO VAT", "PO Gross", "Requested By", "Approved By", "Sent At", "Notes",
+    ])
+    for po in purchase_orders:
+        lines = po.get("lines") or [{}]
+        for line in lines:
+            writer.writerow([
+                po.get("po_number", ""),
+                format_uk_datetime_for_export(po.get("created_at")),
+                format_uk_date_only(po.get("required_date")),
+                po.get("supplier_name", ""),
+                po.get("supplier_email", ""),
+                po.get("job_name", ""),
+                po.get("job_number", ""),
+                po.get("division", ""),
+                po.get("status", ""),
+                po.get("supplier_quote_number", ""),
+                line.get("description", ""),
+                line.get("quantity", ""),
+                line.get("unit_cost", ""),
+                line.get("vat_rate", ""),
+                line.get("net_total", ""),
+                line.get("vat_total", ""),
+                line.get("gross_total", ""),
+                po.get("net_total", ""),
+                po.get("vat_total", ""),
+                po.get("gross_total", ""),
+                po.get("requested_by_name", ""),
+                po.get("approved_by_name", ""),
+                format_uk_datetime_for_export(po.get("sent_at")),
+                po.get("notes", ""),
+            ])
+    output.seek(0)
+    filename = f"purchase_orders_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.csv"
+    return StreamingResponse(
+        io.BytesIO(output.getvalue().encode("utf-8-sig")),
+        media_type="text/csv; charset=utf-8",
+        headers={"Content-Disposition": f"attachment; filename={filename}"},
+    )
+
+
+@api_router.get("/purchase-orders/export.pdf")
+async def export_purchase_orders_pdf(
+    status: Optional[str] = Query(None),
+    job_id: Optional[str] = Query(None),
+    supplier_id: Optional[str] = Query(None),
+    ids: Optional[str] = Query(None),
+    include_cancelled: bool = Query(True),
+    admin: str = Depends(verify_admin),
+):
+    purchase_orders = await find_purchase_orders_for_export(status, job_id, supplier_id, ids, include_cancelled)
+    pdf_bytes = generate_purchase_orders_export_pdf_bytes(purchase_orders)
+    filename = f"purchase_orders_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.pdf"
+    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={filename}"})
+
+
+def build_po_approval_notification_payload(po: Dict[str, Any], requested_by: str = "") -> Dict[str, Any]:
+    """Build a compact approval notification payload for Power Automate/SMTP."""
+    po_number = po.get("po_number") or "Purchase Order"
+    required_date_display = format_uk_date_only(po.get("required_date"))
+    if required_date_display == "-":
+        required_date_display = "TBC"
+
+    subject = f"PO Approval Required - {po_number} - {po.get('job_name', '')}"
+    lines = po.get("lines") or []
+    line_summary = "\n".join(
+        f"- {line.get('description', '')} | Qty: {line.get('quantity', '')} | Net: £{float(line.get('net_total') or 0):,.2f}"
+        for line in lines[:10]
+    )
+    if len(lines) > 10:
+        line_summary += f"\n- plus {len(lines) - 10} more line(s)"
+
+    body_text = f"""A purchase order has been created and requires approval.
+
+PO Number: {po_number}
+Supplier: {po.get('supplier_name', '')}
+Job: {po.get('job_name', '')}
+Required Date: {required_date_display}
+Requested By: {po.get('requested_by_name') or requested_by or 'Admin'}
+
+Net Total: £{float(po.get('net_total') or 0):,.2f}
+VAT Total: £{float(po.get('vat_total') or 0):,.2f}
+Gross Total: £{float(po.get('gross_total') or 0):,.2f}
+
+Line Summary:
+{line_summary or '-'}
+
+Notes:
+{po.get('notes') or '-'}
+"""
+
+    line_rows = "".join(
+        f"""
+        <tr>
+          <td style=\"padding:6px 8px; border-bottom:1px solid #e5e7eb;\">{line.get('description', '')}</td>
+          <td style=\"padding:6px 8px; border-bottom:1px solid #e5e7eb; text-align:right;\">{line.get('quantity', '')}</td>
+          <td style=\"padding:6px 8px; border-bottom:1px solid #e5e7eb; text-align:right;\">£{float(line.get('net_total') or 0):,.2f}</td>
+        </tr>
+        """
+        for line in lines[:10]
+    ) or "<tr><td colspan=\"3\" style=\"padding:6px 8px;\">No line items</td></tr>"
+
+    body_html = f"""
+    <div style=\"font-family:Arial, sans-serif; color:#111827;\">
+      <h2 style=\"margin:0 0 12px;\">Purchase Order Approval Required</h2>
+      <p>A purchase order has been created and requires approval.</p>
+      <table style=\"border-collapse:collapse; font-size:14px; margin-bottom:14px;\">
+        <tr><td style=\"padding:4px 14px 4px 0;\"><strong>PO Number:</strong></td><td>{po_number}</td></tr>
+        <tr><td style=\"padding:4px 14px 4px 0;\"><strong>Supplier:</strong></td><td>{po.get('supplier_name', '')}</td></tr>
+        <tr><td style=\"padding:4px 14px 4px 0;\"><strong>Job:</strong></td><td>{po.get('job_name', '')}</td></tr>
+        <tr><td style=\"padding:4px 14px 4px 0;\"><strong>Required Date:</strong></td><td>{required_date_display}</td></tr>
+        <tr><td style=\"padding:4px 14px 4px 0;\"><strong>Requested By:</strong></td><td>{po.get('requested_by_name') or requested_by or 'Admin'}</td></tr>
+      </table>
+      <table style=\"border-collapse:collapse; font-size:14px; margin-bottom:14px; min-width:360px;\">
+        <tr><td style=\"padding:4px 14px 4px 0;\"><strong>Net Total:</strong></td><td>£{float(po.get('net_total') or 0):,.2f}</td></tr>
+        <tr><td style=\"padding:4px 14px 4px 0;\"><strong>VAT Total:</strong></td><td>£{float(po.get('vat_total') or 0):,.2f}</td></tr>
+        <tr><td style=\"padding:4px 14px 4px 0;\"><strong>Gross Total:</strong></td><td><strong>£{float(po.get('gross_total') or 0):,.2f}</strong></td></tr>
+      </table>
+      <h3 style=\"font-size:15px; margin:14px 0 6px;\">Line Summary</h3>
+      <table style=\"border-collapse:collapse; font-size:13px; width:100%; max-width:720px;\">
+        <thead>
+          <tr style=\"background:#f3f4f6;\">
+            <th style=\"padding:7px 8px; text-align:left;\">Description</th>
+            <th style=\"padding:7px 8px; text-align:right;\">Qty</th>
+            <th style=\"padding:7px 8px; text-align:right;\">Net</th>
+          </tr>
+        </thead>
+        <tbody>{line_rows}</tbody>
+      </table>
+      <p style=\"margin-top:14px;\"><strong>Notes:</strong><br>{po.get('notes') or '-'}</p>
+    </div>
+    """.strip()
+
+    return {
+        "subject": subject,
+        "body_text": body_text,
+        "body_html": body_html,
+        "required_date_display": required_date_display,
+    }
+
+
+async def send_po_approval_notification(po: Dict[str, Any], requested_by: str = "") -> Dict[str, Any]:
+    """Send an internal PO approval notification without blocking PO creation on failure.
+
+    Preferred configuration:
+    - POWER_AUTOMATE_PO_APPROVAL_URL
+    - POWER_AUTOMATE_PO_APPROVAL_SECRET (optional)
+
+    Fallback configuration:
+    - SMTP_HOST / SMTP_PORT / SMTP_USERNAME / SMTP_PASSWORD / SMTP_FROM_EMAIL
+
+    Recipient defaults to info@ldagroup.co.uk and can be overridden with PO_APPROVAL_NOTIFY_EMAIL.
+    """
+    approval_email = os.environ.get("PO_APPROVAL_NOTIFY_EMAIL", "info@ldagroup.co.uk").strip() or "info@ldagroup.co.uk"
+    notification = build_po_approval_notification_payload(po, requested_by=requested_by)
+    po_number = po.get("po_number", "purchase_order")
+
+    try:
+        pdf_bytes = generate_purchase_order_pdf_bytes(po)
+    except Exception as exc:
+        logger.warning("Could not generate PO approval PDF attachment for %s: %s", po_number, exc)
+        pdf_bytes = b""
+
+    power_automate_url = os.environ.get("POWER_AUTOMATE_PO_APPROVAL_URL", "").strip()
+    power_automate_secret = os.environ.get("POWER_AUTOMATE_PO_APPROVAL_SECRET", "").strip()
+
+    if power_automate_url:
+        public_backend_url = (
+            os.environ.get("PUBLIC_BACKEND_URL")
+            or os.environ.get("BACKEND_PUBLIC_URL")
+            or os.environ.get("REACT_APP_BACKEND_URL")
+            or ""
+        ).strip().rstrip("/")
+        approval_callback_secret = os.environ.get("PO_APPROVAL_CALLBACK_SECRET", power_automate_secret).strip()
+        approval_callback_url = f"{public_backend_url}/api/purchase-orders/{po.get('id')}/approval-response" if public_backend_url and po.get("id") else ""
+
+        payload = {
+            "secret": power_automate_secret,
+            "callback_secret": approval_callback_secret,
+            "approval_callback_url": approval_callback_url,
+            "notification_type": "purchase_order_approval_required",
+            "to": approval_email,
+            "po_id": po.get("id"),
+            "po_number": po_number,
+            "supplier_id": po.get("supplier_id", ""),
+            "supplier_name": po.get("supplier_name", ""),
+            "supplier_email": po.get("supplier_email", ""),
+            "job_id": po.get("job_id", ""),
+            "job_name": po.get("job_name", ""),
+            "job_number": po.get("job_number", ""),
+            "division": po.get("division", ""),
+            "required_date": notification["required_date_display"],
+            "delivery_address": po.get("delivery_address", ""),
+            "status": po.get("status", "draft"),
+            "requested_by": po.get("requested_by_name") or requested_by or "Admin",
+            "net_total": po.get("net_total", 0),
+            "vat_total": po.get("vat_total", 0),
+            "gross_total": po.get("gross_total", 0),
+            "subject": notification["subject"],
+            "body_text": notification["body_text"],
+            "body_html": notification["body_html"],
+            "pdf_filename": f"{po_number}.pdf",
+            "pdf_base64": base64.b64encode(pdf_bytes).decode("utf-8") if pdf_bytes else "",
+        }
+
+        response = requests.post(power_automate_url, json=payload, timeout=20)
+        if response.status_code < 200 or response.status_code >= 300:
+            raise RuntimeError(f"Power Automate approval notification failed: {response.status_code} - {response.text[:500]}")
+        return {"sent": True, "method": "power_automate", "to": approval_email}
+
+    smtp_host = os.environ.get("SMTP_HOST", "").strip()
+    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
+    smtp_username = os.environ.get("SMTP_USERNAME", "").strip()
+    smtp_password = os.environ.get("SMTP_PASSWORD", "").strip()
+    smtp_from = os.environ.get("SMTP_FROM_EMAIL", smtp_username).strip()
+    smtp_from_name = os.environ.get("SMTP_FROM_NAME", "LDA Group").strip()
+    smtp_reply_to = os.environ.get("SMTP_REPLY_TO", os.environ.get("PO_REPLY_TO_EMAIL", "")).strip()
+    smtp_use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() != "false"
+
+    if not smtp_host or not smtp_from:
+        return {"sent": False, "method": "not_configured", "to": approval_email}
+
+    message = EmailMessage()
+    message["From"] = f"{smtp_from_name} <{smtp_from}>"
+    message["To"] = approval_email
+    message["Subject"] = notification["subject"]
+    if smtp_reply_to:
+        message["Reply-To"] = smtp_reply_to
+    message.set_content(notification["body_text"])
+    message.add_alternative(notification["body_html"], subtype="html")
+    if pdf_bytes:
+        message.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=f"{po_number}.pdf")
+
+    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
+        if smtp_use_tls:
+            smtp.starttls()
+        if smtp_username and smtp_password:
+            smtp.login(smtp_username, smtp_password)
+        smtp.send_message(message)
+
+    return {"sent": True, "method": "smtp", "to": approval_email}
+
+
+@api_router.delete("/purchase-orders/bulk-delete")
+async def bulk_delete_purchase_orders(request: PurchaseOrderBulkDeleteRequest, super_admin: Dict[str, Any] = Depends(get_super_admin_user)):
+    selected_ids = parse_po_id_list(po_ids=request.po_ids)
+    if not selected_ids:
+        raise HTTPException(status_code=400, detail="No purchase orders selected")
+    result = await db.purchase_orders.delete_many({"id": {"$in": selected_ids}})
+    return {
+        "message": f"Deleted {result.deleted_count} purchase order(s)",
+        "deleted_count": result.deleted_count,
+        "requested_count": len(selected_ids),
+        "deleted_by": super_admin.get("name") or super_admin.get("email") or "Super Admin",
+    }
+
+
 @api_router.get("/purchase-orders/{po_id}")
 async def get_purchase_order(po_id: str, admin: str = Depends(verify_admin)):
     po = await db.purchase_orders.find_one({"id": po_id}, {"_id": 0})
@@ -6761,7 +7241,33 @@
     po_dict = calculate_po_totals(po_dict)
 
     po_obj = PurchaseOrder(**po_dict)
-    await db.purchase_orders.insert_one(po_obj.dict())
+    po_doc = po_obj.dict()
+    await db.purchase_orders.insert_one(po_doc)
+
+    try:
+        notification_result = await send_po_approval_notification(po_doc, requested_by=admin)
+        await db.purchase_orders.update_one(
+            {"id": po_obj.id},
+            {"$set": {
+                "approval_notification_sent": bool(notification_result.get("sent")),
+                "approval_notification_method": notification_result.get("method", "unknown"),
+                "approval_notification_to": notification_result.get("to", "info@ldagroup.co.uk"),
+                "approval_notification_at": datetime.utcnow() if notification_result.get("sent") else None,
+                "approval_notification_error": "" if notification_result.get("sent") else "Approval notification email is not configured",
+            }}
+        )
+    except Exception as exc:
+        logger.exception("PO approval notification failed for %s: %s", po_obj.po_number, exc)
+        await db.purchase_orders.update_one(
+            {"id": po_obj.id},
+            {"$set": {
+                "approval_notification_sent": False,
+                "approval_notification_method": "failed",
+                "approval_notification_to": os.environ.get("PO_APPROVAL_NOTIFY_EMAIL", "info@ldagroup.co.uk"),
+                "approval_notification_error": str(exc)[:1000],
+            }}
+        )
+
     return po_obj
 
 
@@ -6791,6 +7297,76 @@
     if result.deleted_count == 0:
         raise HTTPException(status_code=404, detail="Purchase order not found")
     return {"message": "Purchase order deleted successfully"}
+
+
+@api_router.post("/purchase-orders/{po_id}/approval-response")
+async def update_purchase_order_from_approval_response(po_id: str, response: PurchaseOrderApprovalResponseRequest):
+    """Update a PO after Power Automate Send email with options returns Approve/Reject.
+
+    This endpoint is intentionally protected by a shared secret instead of Basic auth,
+    because it is called server-to-server by Power Automate after the approver clicks an option.
+    """
+    expected_secret = (
+        os.environ.get("PO_APPROVAL_CALLBACK_SECRET")
+        or os.environ.get("POWER_AUTOMATE_PO_APPROVAL_SECRET")
+        or ""
+    ).strip()
+
+    if expected_secret and not secrets.compare_digest(str(response.secret or ""), expected_secret):
+        raise HTTPException(status_code=403, detail="Invalid approval callback secret")
+
+    decision_raw = (response.decision or response.selected_option or "").strip().lower()
+    decision_raw = decision_raw.replace(" ", "_").replace("-", "_")
+
+    if decision_raw in ["approve", "approved", "yes", "accept", "accepted"]:
+        new_status = "approved"
+    elif decision_raw in ["reject", "rejected", "no", "decline", "declined"]:
+        new_status = "rejected"
+    else:
+        raise HTTPException(status_code=400, detail="Approval decision must be Approve or Reject")
+
+    po = await db.purchase_orders.find_one({"id": po_id}, {"_id": 0})
+    if not po:
+        raise HTTPException(status_code=404, detail="Purchase order not found")
+
+    now = datetime.utcnow()
+    responder_name = response.responder_name or response.responder_email or "Power Automate approval"
+    comments = response.comments or response.reason or ""
+
+    update = {
+        "status": new_status,
+        "approval_response": "approved" if new_status == "approved" else "rejected",
+        "approval_response_at": now,
+        "approval_response_by": responder_name,
+        "approval_response_email": response.responder_email or "",
+        "approval_response_comments": comments,
+        "updated_at": now,
+    }
+
+    if new_status == "approved":
+        update.update({
+            "approved_by_user_id": response.responder_email or "power_automate",
+            "approved_by_name": responder_name,
+            "approved_at": now,
+        })
+    else:
+        update.update({
+            "rejected_by_user_id": response.responder_email or "power_automate",
+            "rejected_by_name": responder_name,
+            "rejected_at": now,
+            "rejection_reason": comments,
+        })
+
+    await db.purchase_orders.update_one({"id": po_id}, {"$set": update})
+    updated = await db.purchase_orders.find_one({"id": po_id}, {"_id": 0})
+
+    return {
+        "success": True,
+        "message": f"Purchase order {updated.get('po_number', po_id)} marked as {new_status}",
+        "po_id": po_id,
+        "po_number": updated.get("po_number"),
+        "status": updated.get("status"),
+    }
 
 
 @api_router.post("/purchase-orders/{po_id}/approve")
@@ -7644,9 +8220,12 @@
         item["actual_spend"] = round(item["actual_spend"], 2)
         item["po_commitments"] = round(item["po_commitments"], 2)
         item["forecast_spend"] = round(item["forecast_spend"], 2)
-        item["total_committed"] = round(item["actual_spend"] + item["po_commitments"] + item["forecast_spend"], 2)
+        item["total_committed"] = round(item["actual_spend"] + item["po_commitments"], 2)
+        item["total_exposure"] = round(item["actual_spend"] + item["po_commitments"] + item["forecast_spend"], 2)
         item["variance"] = round(item["allowance"] - item["total_committed"], 2)
+        item["forecast_variance"] = round(item["allowance"] - item["total_exposure"], 2)
         item["percent_used"] = round((item["total_committed"] / item["allowance"] * 100.0), 1) if item["allowance"] > 0 else 0.0
+        item["percent_exposed"] = round((item["total_exposure"] / item["allowance"] * 100.0), 1) if item["allowance"] > 0 else 0.0
         if item["allowance"] > 0 and item["total_committed"] > item["allowance"]:
             jobs_over_allowance += 1
 
