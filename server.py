# ==============================
# LDA TIMESHEET PDF EXPORT ROUTE
# Paste this into server.py after your existing reports routes.
# Also add reportlab to requirements.txt:
# reportlab==4.2.5
# ==============================

from io import BytesIO
from datetime import datetime, timedelta
from fastapi import Query
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)

def _pdf_safe(value, fallback="-"):
    if value is None or value == "":
        return fallback
    return str(value)

def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text)
    except Exception:
        return None

def _format_date(value):
    dt = _parse_dt(value)
    return dt.strftime("%d/%m/%Y") if dt else "-"

def _format_time(value):
    dt = _parse_dt(value)
    if not dt:
        return "-"
    # Backend normally stores UTC. Add one hour during BST period if needed in your existing app logic.
    # If your server already stores local UK time, remove this timedelta line.
    return dt.strftime("%H:%M")

def _format_hours(minutes):
    try:
        return f"{float(minutes or 0) / 60:.2f}"
    except Exception:
        return "0.00"

def _format_money(value):
    try:
        return f"£{float(value or 0):,.2f}"
    except Exception:
        return "£0.00"

def _normalise_worker_type(value):
    value = (value or "").lower()
    if value in ["contractor", "subcontractor"]:
        return "Contractor"
    if value in ["worker", "employee", "staff"]:
        return "Worker"
    return value.title() if value else "-"

def _flag_text(entry):
    flags = entry.get("suspicious_flags") or []
    worker_division = entry.get("worker_division") or entry.get("workerDivision")
    job_division = entry.get("job_division") or entry.get("jobDivision")

    readable = []
    for flag in flags:
        readable.append(str(flag).replace("_", " ").title())

    if worker_division and job_division and worker_division != job_division:
        readable.append("Cross-Division Labour")

    return ", ".join(readable) if readable else "OK"

def _add_page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(285 * mm, 10 * mm, f"Page {doc.page}")
    canvas.drawString(12 * mm, 10 * mm, "LDA Group - Timesheet Export")
    canvas.restoreState()

@api_router.get("/reports/export/time-entries-pdf")
async def export_time_entries_pdf(
    worker_id: str = Query(None),
    job_id: str = Query(None),
    start_date: str = Query(None),
    end_date: str = Query(None),
    worker_division: str = Query(None),
    job_division: str = Query(None),
    worker_type: str = Query(None),
    current_admin: dict = Depends(get_current_admin)
):
    query = {}

    if worker_id:
        query["worker_id"] = worker_id

    if job_id:
        query["job_id"] = job_id

    if start_date or end_date:
        date_query = {}
        if start_date:
            date_query["$gte"] = datetime.fromisoformat(start_date)
        if end_date:
            end_dt = datetime.fromisoformat(end_date) + timedelta(days=1)
            date_query["$lt"] = end_dt
        query["clock_in"] = date_query

    entries = await db.time_entries.find(query).sort("clock_in", 1).to_list(5000)
    workers = await db.workers.find({}).to_list(5000)
    jobs = await db.jobs.find({}).to_list(5000)

    worker_lookup = {w.get("id"): w for w in workers}
    job_lookup = {j.get("id"): j for j in jobs}

    enriched = []
    for entry in entries:
        worker = worker_lookup.get(entry.get("worker_id"), {})
        job = job_lookup.get(entry.get("job_id"), {})

        item = {
            **entry,
            "worker_name": entry.get("worker_name") or worker.get("name") or "Unknown",
            "job_name": entry.get("job_name") or job.get("name") or "Unknown",
            "worker_division": worker.get("division") or entry.get("worker_division") or entry.get("workerDivision") or "-",
            "job_division": job.get("division") or entry.get("job_division") or entry.get("jobDivision") or "-",
            "worker_type": worker.get("worker_type") or worker.get("type") or worker.get("role") or entry.get("worker_type") or "-",
            "hourly_rate": entry.get("hourly_rate") or worker.get("hourly_rate") or worker.get("hourlyRate") or 0,
        }

        if not item.get("cost"):
            try:
                item["cost"] = (float(item.get("duration_minutes") or 0) / 60) * float(item.get("hourly_rate") or 0)
            except Exception:
                item["cost"] = 0

        if worker_division and item["worker_division"] != worker_division:
            continue
        if job_division and item["job_division"] != job_division:
            continue
        if worker_type:
            wt = str(item["worker_type"]).lower()
            if worker_type == "contractor" and "contractor" not in wt:
                continue
            if worker_type == "worker" and "contractor" in wt:
                continue

        enriched.append(item)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=10 * mm,
        leftMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "LDATitle",
        parent=styles["Title"],
        fontSize=22,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#111827"),
        spaceAfter=8,
    )
    h2 = ParagraphStyle(
        "LDAHeading",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=colors.HexColor("#d01f2f"),
        spaceBefore=8,
        spaceAfter=6,
    )
    small = ParagraphStyle("Small", parent=styles["Normal"], fontSize=8, leading=10)

    story = []
    story.append(Paragraph("LDA Group", title_style))
    story.append(Paragraph("Timesheet Export Report", h2))

    period = f"{start_date or 'All'} to {end_date or 'All'}"
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    story.append(Paragraph(f"<b>Report Period:</b> {period}", styles["Normal"]))
    story.append(Paragraph(f"<b>Generated On:</b> {generated}", styles["Normal"]))
    story.append(Spacer(1, 8))

    filter_rows = [
        ["Filter", "Selection"],
        ["Job Division", job_division or "All"],
        ["Worker Division", worker_division or "All"],
        ["Worker Type", worker_type or "Employees + Contractors"],
        ["Worker", worker_id or "All"],
        ["Job", job_id or "All"],
    ]
    filter_table = Table(filter_rows, colWidths=[55 * mm, 100 * mm])
    filter_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(filter_table)
    story.append(Spacer(1, 10))

    # Division summary by job division
    division_summary = {}
    worker_summary = {}
    job_summary = {}
    exception_rows = [["Date", "Worker", "Job", "Issue"]]

    for e in enriched:
        jd = e.get("job_division") or "-"
        wn = e.get("worker_name") or "Unknown"
        jn = e.get("job_name") or "Unknown"
        mins = float(e.get("duration_minutes") or 0)
        cost = float(e.get("cost") or 0)

        division_summary.setdefault(jd, {"workers": set(), "shifts": 0, "minutes": 0, "cost": 0})
        division_summary[jd]["workers"].add(wn)
        division_summary[jd]["shifts"] += 1
        division_summary[jd]["minutes"] += mins
        division_summary[jd]["cost"] += cost

        worker_summary.setdefault(wn, {"division": e.get("worker_division") or "-", "shifts": 0, "minutes": 0, "cost": 0})
        worker_summary[wn]["shifts"] += 1
        worker_summary[wn]["minutes"] += mins
        worker_summary[wn]["cost"] += cost

        job_summary.setdefault(jn, {"division": jd, "workers": set(), "minutes": 0, "cost": 0})
        job_summary[jn]["workers"].add(wn)
        job_summary[jn]["minutes"] += mins
        job_summary[jn]["cost"] += cost

        flag = _flag_text(e)
        if flag != "OK":
            exception_rows.append([_format_date(e.get("clock_in")), wn, jn, flag])

    summary_rows = [["Division", "Total Workers", "Total Shifts", "Total Hours", "Labour Cost"]]
    total_workers = set()
    total_shifts = 0
    total_minutes = 0
    total_cost = 0

    for div, data in sorted(division_summary.items()):
        summary_rows.append([
            div,
            str(len(data["workers"])),
            str(data["shifts"]),
            _format_hours(data["minutes"]),
            _format_money(data["cost"]),
        ])
        total_workers.update(data["workers"])
        total_shifts += data["shifts"]
        total_minutes += data["minutes"]
        total_cost += data["cost"]

    summary_rows.append(["Total", str(len(total_workers)), str(total_shifts), _format_hours(total_minutes), _format_money(total_cost)])

    story.append(Paragraph("Summary", h2))
    summary_table = Table(summary_rows, colWidths=[70 * mm, 35 * mm, 35 * mm, 35 * mm, 40 * mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d01f2f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f3f4f6")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(summary_table)
    story.append(PageBreak())

    story.append(Paragraph("Timesheet Detail", h2))
    detail_rows = [[
        "Date", "Worker", "Worker Division", "Job", "Job Division", "Type",
        "Clock In", "Clock Out", "Hours", "Rate", "Cost", "Flags"
    ]]

    for e in enriched:
        detail_rows.append([
            _format_date(e.get("clock_in")),
            _pdf_safe(e.get("worker_name")),
            _pdf_safe(e.get("worker_division")),
            _pdf_safe(e.get("job_name")),
            _pdf_safe(e.get("job_division")),
            _normalise_worker_type(e.get("worker_type")),
            _format_time(e.get("clock_in")),
            _format_time(e.get("clock_out")),
            _format_hours(e.get("duration_minutes")),
            _format_money(e.get("hourly_rate")),
            _format_money(e.get("cost")),
            Paragraph(_flag_text(e), small),
        ])

    detail_table = Table(
        detail_rows,
        repeatRows=1,
        colWidths=[20*mm, 28*mm, 27*mm, 35*mm, 25*mm, 20*mm, 18*mm, 18*mm, 16*mm, 18*mm, 20*mm, 42*mm]
    )
    detail_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.2, colors.HexColor("#d1d5db")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(detail_table)
    story.append(PageBreak())

    story.append(Paragraph("Worker Summary", h2))
    wr = [["Worker", "Worker Division", "Shifts", "Total Hours", "Total Cost"]]
    for worker, data in sorted(worker_summary.items()):
        wr.append([worker, data["division"], str(data["shifts"]), _format_hours(data["minutes"]), _format_money(data["cost"])])
    wt = Table(wr, repeatRows=1, colWidths=[70*mm, 55*mm, 25*mm, 35*mm, 40*mm])
    wt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d01f2f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(wt)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Job Summary", h2))
    jr = [["Job", "Job Division", "Workers Used", "Total Hours", "Total Cost"]]
    for job, data in sorted(job_summary.items()):
        jr.append([job, data["division"], str(len(data["workers"])), _format_hours(data["minutes"]), _format_money(data["cost"])])
    jt = Table(jr, repeatRows=1, colWidths=[80*mm, 55*mm, 30*mm, 35*mm, 40*mm])
    jt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111827")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
    ]))
    story.append(jt)
    story.append(PageBreak())

    story.append(Paragraph("Exception / Flag Section", h2))
    if len(exception_rows) == 1:
        exception_rows.append(["-", "-", "-", "No exceptions found"])
    et = Table(exception_rows, repeatRows=1, colWidths=[30*mm, 55*mm, 70*mm, 115*mm])
    et.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d01f2f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(et)
    story.append(Spacer(1, 18))

    approval_rows = [
        ["Prepared By", ""],
        ["Reviewed By", ""],
        ["Approved By", ""],
        ["Date", ""],
    ]
    at = Table(approval_rows, colWidths=[45*mm, 120*mm], rowHeights=[12*mm, 12*mm, 12*mm, 12*mm])
    at.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9ca3af")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(Paragraph("Approval", h2))
    story.append(at)

    doc.build(story, onFirstPage=_add_page_number, onLaterPages=_add_page_number)

    buffer.seek(0)
    filename = f"LDA_timesheet_{start_date or 'all'}_{end_date or 'all'}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
